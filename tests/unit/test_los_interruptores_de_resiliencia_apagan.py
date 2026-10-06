"""Cuatro interruptores de resiliencia y arranque que no leía nadie.

Medidos el 06-10-2026 con el barrido de ajustes sin lector. Los cuatro estaban
en `.env.example`, estaban en el manual de referencia y de ahí no pasaban.

`CIRCUIT_BREAKER_ENABLED` y `DEGRADACION_ENABLED` son los peores de los cuatro
porque se apagan **durante un incidente**: alguien ve que el cortacircuitos está
cortando un proveedor que ya va bien, o que la degradación está rechazando
trabajo que la instalación aguanta, lo pone a `false`, reinicia, y no cambia
nada. Y entonces busca la avería donde no está.

Tres decisiones que no son obvias:

  · Apagar el cortacircuitos **cierra los que ya estuvieran abiertos**, no sólo
    impide abrir nuevos. Si no, apagarlo dejaría el recurso cortado hasta que
    venciera su descanso, que es lo contrario de lo que pide quien lo apaga
    para salir de un corte.
  · Apagado se sigue **contando** el fallo. Si no, al volver a encenderlo en
    mitad de un incidente el circuito tendría que fallar el umbral entero otra
    vez antes de proteger: cinco veces el mismo timeout para todos los que
    pasen por ahí.
  · `INBOX_ENABLED` apagado procesa el hecho y **no lo marca**. Marcar sin
    deduplicar sería lo peor de los dos mundos: la tabla crece y, al volver a
    encender, hay claves de hechos que nunca se comprobaron contra ellas.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from crmcore import resiliencia


@pytest.fixture
def ajuste(request: Any) -> Any:
    """`(NOMBRE, "true"|"false")`, y lo deja como estaba."""
    from crmcore.config import limpiar_cache_settings

    clave, valor = request.param
    previo = os.environ.get(clave)
    os.environ[clave] = valor
    limpiar_cache_settings()
    resiliencia.reiniciar()
    try:
        yield
    finally:
        if previo is None:
            os.environ.pop(clave, None)
        else:
            os.environ[clave] = previo
        limpiar_cache_settings()
        resiliencia.reiniciar()


# ── Cortacircuitos ────────────────────────────────────────────────────────


@pytest.mark.parametrize("ajuste", [("CIRCUIT_BREAKER_ENABLED", "true")], indirect=True)
def test_encendido_abre_el_circuito(ajuste: Any) -> None:
    for _ in range(10):
        resiliencia.anotar_fallo("proveedor-x")
    assert resiliencia.circuito_abierto("proveedor-x") is True


@pytest.mark.parametrize("ajuste", [("CIRCUIT_BREAKER_ENABLED", "false")], indirect=True)
def test_apagado_no_abre_nada(ajuste: Any) -> None:
    for _ in range(10):
        resiliencia.anotar_fallo("proveedor-x")
    assert resiliencia.circuito_abierto("proveedor-x") is False


@pytest.mark.parametrize("ajuste", [("CIRCUIT_BREAKER_ENABLED", "false")], indirect=True)
def test_apagado_sigue_contando_el_fallo(ajuste: Any) -> None:
    """Apagado se cuenta igual, y eso importa al volver a encenderlo: si se
    hubiera dejado de contar, al encenderlo en mitad de un incidente el
    circuito tendría que fallar el umbral entero otra vez antes de proteger —
    cinco veces el mismo timeout para todos los que pasen por ahí."""
    for _ in range(3):
        resiliencia.anotar_fallo("proveedor-x")
    assert resiliencia._circuitos["proveedor-x"].fallos == 3


@pytest.mark.parametrize("ajuste", [("CIRCUIT_BREAKER_ENABLED", "false")], indirect=True)
def test_apagado_no_apunta_aperturas_que_no_han_pasado(ajuste: Any) -> None:
    """Sin esto, apagado se seguiría anotando «circuito abierto» en el contador
    y en el log —con nivel de error— de circuitos que no se abren. Quien mire el
    panel durante el incidente vería aperturas inventadas, que es exactamente lo
    que estorba cuando se busca qué está fallando de verdad."""
    for _ in range(10):
        resiliencia.anotar_fallo("proveedor-z")
    circuito = resiliencia._circuitos["proveedor-z"]
    assert circuito.fallos == 10
    assert circuito.aperturas == 0, "ha contado una apertura con el cortacircuitos apagado"
    assert circuito.abierto_hasta == 0.0


def test_apagarlo_cierra_los_que_ya_estaban_abiertos() -> None:
    """Es la mitad que importa: se apaga PARA SALIR de un corte, no para
    prevenir el siguiente."""
    from crmcore.config import limpiar_cache_settings

    previo = os.environ.get("CIRCUIT_BREAKER_ENABLED")
    try:
        os.environ["CIRCUIT_BREAKER_ENABLED"] = "true"
        limpiar_cache_settings()
        resiliencia.reiniciar()
        for _ in range(10):
            resiliencia.anotar_fallo("proveedor-y")
        assert resiliencia.circuito_abierto("proveedor-y") is True

        # Y ahora se apaga, sin tocar nada más: el circuito ya estaba abierto.
        os.environ["CIRCUIT_BREAKER_ENABLED"] = "false"
        limpiar_cache_settings()
        assert resiliencia.circuito_abierto("proveedor-y") is False
    finally:
        if previo is None:
            os.environ.pop("CIRCUIT_BREAKER_ENABLED", None)
        else:
            os.environ["CIRCUIT_BREAKER_ENABLED"] = previo
        limpiar_cache_settings()
        resiliencia.reiniciar()


# ── Degradación bajo carga ────────────────────────────────────────────────


@pytest.mark.parametrize("ajuste", [("DEGRADACION_ENABLED", "true")], indirect=True)
def test_encendida_difiere_lo_diferible(ajuste: Any) -> None:
    resiliencia.fijar_presion(0.95)
    assert resiliencia.admite(resiliencia.DIFERIBLE) is False


@pytest.mark.parametrize("ajuste", [("DEGRADACION_ENABLED", "false")], indirect=True)
def test_apagada_pasa_todo(ajuste: Any) -> None:
    resiliencia.fijar_presion(0.99)
    assert resiliencia.admite(resiliencia.DIFERIBLE) is True
    assert resiliencia.admite(resiliencia.NORMAL) is True


@pytest.mark.parametrize("ajuste", [("DEGRADACION_ENABLED", "false")], indirect=True)
def test_lo_critico_nunca_cae_tampoco_apagada(ajuste: Any) -> None:
    resiliencia.fijar_presion(1.0)
    assert resiliencia.admite(resiliencia.CRITICA) is True


# ── El armado de alembic, en un solo sitio ────────────────────────────────


def test_el_script_de_migraciones_usa_el_armado_del_nucleo() -> None:
    """Dos armados divergen, y el que menos se mire acabará migrando el esquema
    equivocado — el error que más caro sale con un esquema por servicio."""
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    fuente = (raiz / "scripts" / "migrar.py").read_text(encoding="utf-8")
    cuerpo = fuente.split("def _config(")[1].split("\ndef ")[0]
    assert "from crmcore.db.migraciones import config" in cuerpo
    # Y no se ha quedado una copia del armado aquí.
    assert "set_main_option" not in cuerpo


def test_el_cerrojo_de_migracion_es_estable_entre_procesos() -> None:
    """`hash()` de Python lleva semilla aleatoria por proceso: dos réplicas
    tomarían cerrojos distintos y el cerrojo no serviría de nada, que es peor
    que no tenerlo porque parece puesto."""
    from crmcore.db.migraciones import _sufijo

    assert _sufijo("party") == _sufijo("party")
    assert _sufijo("party") != _sufijo("sales")
    assert _sufijo("party") == 0x7FFFFFFF & __import__("zlib").crc32(b"party")


def test_la_migracion_al_arrancar_espera_en_vez_de_rendirse() -> None:
    """Rendirse dejaría a esta réplica arrancando contra el esquema a medio
    migrar de la otra, que es el peor de los tres casos."""
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    fuente = (raiz / "packages/crmcore/crmcore/db/migraciones.py").read_text(encoding="utf-8")
    assert "pg_advisory_lock" in fuente
    assert "pg_try_advisory_lock" not in fuente


def test_migrar_al_arrancar_va_antes_de_todo_lo_que_toca_tablas() -> None:
    """Los guardianes, las suscripciones y los barridos tocan tablas: hacerlo
    después sería arrancarlos contra el esquema de antes."""
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    fuente = (raiz / "packages/crmcore/crmcore/service.py").read_text(encoding="utf-8")
    cuerpo = fuente.split("async def ciclo_de_vida(")[1]
    assert cuerpo.index("db_migrate_on_boot") < cuerpo.index("instalar_guard()")
    assert cuerpo.index("db_migrate_on_boot") < cuerpo.index("_barridos_del_nucleo")
