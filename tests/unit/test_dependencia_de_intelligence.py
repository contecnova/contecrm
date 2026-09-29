"""Qué pasa cuando contecintelligence no está (`CRM-05.01.04`).

Cuatro capacidades de las que dependen de otra solución de la casa, y son de las
pocas que se pueden **ejercitar sin el vecino delante** — porque van justo de
eso: de qué hace el CRM cuando el vecino no contesta.

La regla que las gobierna está escrita en el código y es la que se comprueba
aquí: **el CRM operativo no puede depender de la herramienta de consulta.** Dejar
el alta de un cliente atada a que el motor analítico esté vivo convierte una
herramienta en una dependencia crítica.

Y la otra mitad: **«no responde» y «está todo bien» tienen que distinguirse**.
Un sistema que calla cuando su vecino está caído deja al usuario mirando una
pantalla vacía sin saber si no hay datos o no hay servicio.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def sin_vecino(monkeypatch: Any) -> Any:
    """Con la integración encendida y apuntando a donde no hay nadie.

    Es el caso real que se quiere cubrir: no «apagada» —eso ya se sabe que
    funciona— sino **configurada y caída**, que es lo que pasa un martes.
    """
    from crmcore.config import get_settings

    monkeypatch.setenv("CI_ENABLED", "true")
    # Un puerto de loopback sin nada escuchando: se rechaza al instante y no hay
    # que esperar un tiempo de espera, que haría lenta la suite por nada.
    monkeypatch.setenv("CI_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("CI_COMPROBAR_AL_ARRANCAR", "true")
    monkeypatch.setenv("URL_GUARD_HOSTS_PERMITIDOS", "127.0.0.1")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ── CRM-05.01.04.11 · el fallo se dice al arrancar ────────────────────────


# SE CAPTURA LA SALIDA, no `caplog`.
#
# `structlog` está configurado con `PrintLoggerFactory(file=sys.stdout)`: escribe
# directo a la salida y **no pasa por el logging estándar**, así que `caplog` no
# ve nada y una comprobación sobre él falla aunque el aviso se emita. Me pasó con
# estas dos: la tercera prueba —la que exige que el arranque se pare— pasaba, o
# sea que el camino se ejecutaba y lo que no funcionaba era mi forma de mirar.


def test_al_arrancar_se_avisa_de_que_no_responde_y_no_se_impide_arrancar(
    sin_vecino: Any, capsys: Any
) -> None:
    """El aviso llega a quien despliega, no a quien abre el primer informe tres
    días después. Y no impide arrancar: el CRM sigue sirviendo."""
    from services.analytics.cliente import comprobar_al_arrancar

    comprobar_al_arrancar()  # no lanza

    salida = capsys.readouterr().out
    assert "degradada" in salida or "no responde" in salida, (
        "arrancó sin decir que la explotación está degradada: quien despliega no "
        f"se entera hasta que alguien abre un informe. Salida: {salida[:300]!r}"
    )


def test_si_la_instalacion_lo_exige_el_arranque_se_para(sin_vecino: Any, monkeypatch: Any) -> None:
    """Quien prefiera lo contrario —una instalación donde el CRM sin informes no
    sirve— lo enciende, y entonces sí se niega a arrancar."""
    from crmcore.config import get_settings

    from services.analytics.cliente import comprobar_al_arrancar

    monkeypatch.setenv("CI_OBLIGATORIO_PARA_ARRANCAR", "true")
    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="no responde"):
        comprobar_al_arrancar()


def test_encendido_y_sin_direccion_tambien_se_avisa(monkeypatch: Any, capsys: Any) -> None:
    """Configurado a medias es un caso distinto de caído, y se dice distinto:
    ahí lo que falta es la dirección, no el servicio."""
    from crmcore.config import get_settings

    from services.analytics.cliente import comprobar_al_arrancar

    monkeypatch.setenv("CI_ENABLED", "true")
    monkeypatch.setenv("CI_BASE_URL", "")
    monkeypatch.setenv("CI_COMPROBAR_AL_ARRANCAR", "true")
    get_settings.cache_clear()

    comprobar_al_arrancar()

    mensajes = capsys.readouterr().out
    assert "CI_BASE_URL" in mensajes, (
        "no dice que falta la dirección: quien lo lea buscará un servicio caído "
        "que en realidad nunca se configuró"
    )
    get_settings.cache_clear()


def test_apagado_no_avisa_de_nada(monkeypatch: Any, capsys: Any) -> None:
    """La otra mitad. Una instalación que no quiere explotación del dato no puede
    llenar su registro de errores por algo que ha decidido no tener."""
    from crmcore.config import get_settings

    from services.analytics.cliente import comprobar_al_arrancar

    monkeypatch.setenv("CI_ENABLED", "false")
    get_settings.cache_clear()

    comprobar_al_arrancar()

    assert (
        "analytics." not in capsys.readouterr().out
    ), "avisa de una dependencia que la instalación ha decidido no tener"
    get_settings.cache_clear()


# ── CRM-05.01.04.08 · la degradación se explica ───────────────────────────


@pytest.mark.db
def test_la_degradacion_dice_que_se_puede_hacer_sin_el(
    sin_vecino: Any, db: Any, tenant_id: Any, contexto_tenant: Any
) -> None:
    """«Servicio no disponible» a secas deja al usuario sin saber si esperar, si
    llamar a alguien o si hacer otra cosa. Lo que hace falta es qué SÍ funciona."""
    from services.analytics.fuente import diagnostico

    salida = diagnostico(db, tenant_id)

    texto = str(salida).lower()
    assert "no responde" in texto, f"no dice que el vecino no contesta: {salida}"
    # Y con qué se puede hacer mientras tanto: sin eso es un error, no un
    # diagnóstico.
    assert any(k in salida for k in ("puede", "funciona", "problemas", "que_hacer")), salida
