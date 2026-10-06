"""`LOG_REQUEST_BODY` no lo leía nadie (`CRM-00.06.01`).

Medido el 06-10-2026 con el barrido de ajustes sin lector. Encenderlo no
registraba ningún cuerpo, así que quien lo encendía para perseguir un 500 seguía
sin el dato y no sabía por qué: ni error, ni aviso, ni nada.

Y enchufarlo a secas habría sido peor que dejarlo apagado. El procesador de logs
censura **por clave del apunte**, así que un campo `cuerpo` con el JSON entero
dentro pasa en claro: la contraseña de un inicio de sesión fallido —que es
justo una petición que se registra— y el correo de quien se acaba de dar de
alta. El propio comentario del ajuste lo avisa: «es la vía más rápida de filtrar
datos personales a un sistema de logs que no está pensado para guardarlos».

Tres decisiones:

  · El cuerpo se censura **por dentro**, con la misma lista de claves que usa el
    procesador. Dos listas divergen, y la que menos se mira se queda corta.
  · Lo que no se puede analizar **no se suelta**: de un cuerpo binario o
    cortado se dice el tamaño. Lo que no se puede censurar no se puede publicar.
  · El `receive` de ASGI se consume una sola vez, así que la copia tiene que
    dejar pasar el cuerpo intacto. Quedárselo daría un 422 en todas las
    escrituras en cuanto alguien encendiera el ajuste para depurar.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from crmcore.http.middleware import TOPE_CUERPO_LOG, _cuerpo_para_el_log
from crmcore.logging import redactar_estructura


@pytest.fixture
def pii_censurada() -> Any:
    """Como en producción.

    `LOG_REDACT_PII` cae a **apagado en desarrollo** a propósito: poder buscar un
    correo en el log es justo lo que hace falta para depurar. Así que las
    pruebas de PII fijan el valor en vez de dar por supuesto el del entorno — si
    no, dirían que el correo pasa en claro y eso sería cierto aquí y falso
    donde importa.
    """
    from crmcore.config import limpiar_cache_settings

    previo = os.environ.get("LOG_REDACT_PII")
    os.environ["LOG_REDACT_PII"] = "true"
    limpiar_cache_settings()
    try:
        yield
    finally:
        if previo is None:
            os.environ.pop("LOG_REDACT_PII", None)
        else:
            os.environ["LOG_REDACT_PII"] = previo
        limpiar_cache_settings()


def test_una_contrasena_no_llega_al_log() -> None:
    """Es el caso concreto: un inicio de sesión que falla **se registra**.

    Sin fixture: un secreto se tapa SIEMPRE, también en desarrollo. Una
    contraseña en el log de un portátil es una contraseña filtrada igual.
    """
    salida = _cuerpo_para_el_log(b'{"email":"ana@x.com","password":"la-de-verdad"}')
    texto = str(salida)
    assert "la-de-verdad" not in texto
    assert salida["json"]["password"] == "***"


def test_un_correo_no_llega_en_claro(pii_censurada: Any) -> None:
    salida = _cuerpo_para_el_log(b'{"email":"ana@x.com"}')
    assert "ana@x.com" not in str(salida)


def test_tambien_anidado(pii_censurada: Any) -> None:
    """Censurar solo la raíz deja pasar el caso normal: los datos van dentro."""
    crudo = b'{"usuario":{"credenciales":{"password":"x"},"contactos":[{"email":"a@b.c"}]}}'
    texto = str(_cuerpo_para_el_log(crudo))
    assert '"x"' not in texto
    assert "a@b.c" not in texto


def test_lo_que_no_se_puede_analizar_no_se_suelta(pii_censurada: Any) -> None:
    """Lo que no se puede censurar no se puede publicar. Se dice el tamaño, que
    para perseguir un 500 es casi todo lo que hacía falta."""
    salida = _cuerpo_para_el_log(b"\\x89PNG\\r\\n\\x1a\\n binario con ana@x.com dentro")
    assert salida["ilegible"] is True
    assert "ana@x.com" not in str(salida)
    assert salida["bytes"] > 0


def test_lo_que_no_es_sensible_sigue_viéndose() -> None:
    """Censurarlo todo dejaría el ajuste sin utilidad: se enciende para ver qué
    se mandó."""
    salida = _cuerpo_para_el_log(b'{"nombre_campo":"importe","valor":42}')
    assert salida["json"] == {"nombre_campo": "importe", "valor": 42}


def test_el_tope_corta_y_lo_dice() -> None:
    crudo = b'{"nota":"' + b"a" * (TOPE_CUERPO_LOG + 100) + b'"}'
    assert _cuerpo_para_el_log(crudo[:TOPE_CUERPO_LOG])["cortado"] is True


def test_la_censura_por_dentro_usa_la_misma_lista_que_el_procesador() -> None:
    """Dos listas de claves sensibles divergen, y la que menos se mira es la que
    se queda corta. Ya pasó con el HMAC de las firmas."""
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    fuente = (raiz / "packages/crmcore/crmcore/logging.py").read_text(encoding="utf-8")
    cuerpo = fuente.split("def redactar_estructura(")[1].split("\ndef ")[0]
    assert "_CLAVES_SECRETAS" in cuerpo and "_CLAVES_PII" in cuerpo


def test_el_cuerpo_se_deja_pasar_intacto() -> None:
    """Quedárselo daría un 422 en todas las escrituras en cuanto alguien
    encendiera el ajuste."""
    import asyncio

    from crmcore.http.middleware import _receive_que_copia

    trozos = [
        {"type": "http.request", "body": b'{"a":1}', "more_body": False},
    ]

    async def receive() -> Any:
        return trozos.pop(0)

    copia: list[bytes] = []
    envuelto = _receive_que_copia(receive, copia)
    mensaje = asyncio.run(envuelto())
    assert mensaje["body"] == b'{"a":1}', "la aplicación se ha quedado sin cuerpo"
    assert b"".join(copia) == b'{"a":1}'


def test_apagado_no_envuelve_nada() -> None:
    """De fábrica va apagado y se queda apagado: en el camino caliente no se
    copia ni un byte."""
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    fuente = (raiz / "packages/crmcore/crmcore/http/middleware.py").read_text(encoding="utf-8")
    # El de `TiemposMiddleware`, que es el que copia: en este fichero hay
    # varios middlewares y quedarse con el primero probaba otro.
    cuerpo = fuente.split("class TiemposMiddleware:")[1]
    assert "if _settings_obs().log_request_body:" in cuerpo
    from crmcore.config import get_settings

    assert get_settings().log_request_body is False, "ha dejado de venir apagado de fábrica"


def test_redactar_estructura_no_rompe_lo_que_no_es_diccionario() -> None:
    assert redactar_estructura(42) == 42
    assert redactar_estructura(["a", 1]) == ["a", 1]
    assert redactar_estructura(None) is None


def test_en_desarrollo_el_correo_se_ve_a_proposito() -> None:
    """No es un descuido: `LOG_REDACT_PII` cae a apagado en desarrollo porque
    poder buscar un correo en el log es lo que se necesita para depurar. Se
    comprueba para que quede dicho cuál es el comportamiento y no se «arregle»
    por error."""
    from crmcore.config import get_settings

    if get_settings().redactar_pii_resuelto:
        pytest.skip("este entorno ya censura PII; el caso es el de desarrollo")
    salida = _cuerpo_para_el_log(b'{"email":"ana@x.com","password":"x"}')
    assert salida["json"]["email"] == "ana@x.com"
    # Pero el secreto sigue tapado: son dos cosas distintas.
    assert salida["json"]["password"] == "***"
