"""Puntos de extensión del dominio (CRM-00.04.02.02, CRM-00.04.02.03).

Un CRM al que no se le puede enganchar nada obliga a modificarlo para cada
cliente, y a los dos años hay cinco versiones del producto. Lo que estas pruebas
defienden es la única diferencia que importa entre las dos formas de
engancharse: **antes puede rechazar y después no**, y lo asíncrono no puede
romper nada.
"""

from __future__ import annotations

from typing import Any

import pytest
from crmcore import extensiones


@pytest.fixture(autouse=True)
def _limpio() -> Any:
    extensiones.limpiar_hooks()
    yield
    extensiones.limpiar_hooks()


# ── Síncrono ──────────────────────────────────────────────────────────────


def test_un_hook_previo_puede_rechazar_la_operacion() -> None:
    """Es lo único que distingue `antes` de `despues`: si tragara el error,
    «rechazar un guardado» dejaría de ser posible."""

    def veta(**_: Any) -> None:
        raise ValueError("este cliente no admite descuentos")

    extensiones.registrar_hook("veta", "oportunidad", "antes", veta)

    with pytest.raises(ValueError, match="descuentos"):
        extensiones.antes_de("oportunidad", registro={})


def test_un_hook_posterior_que_falla_no_aborta_nada() -> None:
    """El cambio ya está hecho: propagar haría que el usuario viera un error
    sobre algo que sí se guardó, y lo volvería a intentar duplicándolo."""

    def revienta(**_: Any) -> None:
        raise RuntimeError("el servicio de al lado no responde")

    extensiones.registrar_hook("revienta", "cuenta", "despues", revienta)
    extensiones.despues_de("cuenta", registro={})  # no lanza


def test_los_hooks_reciben_el_contexto() -> None:
    vistos: list[Any] = []
    extensiones.registrar_hook("apunta", "cuenta", "antes", lambda **kw: vistos.append(kw))
    extensiones.antes_de("cuenta", registro={"nombre": "ACME"}, usuario="u1")
    assert vistos == [{"registro": {"nombre": "ACME"}, "usuario": "u1"}]


def test_solo_corren_los_hooks_de_su_objeto_y_su_momento() -> None:
    llamados: list[str] = []
    extensiones.registrar_hook("a", "cuenta", "antes", lambda **_: llamados.append("a"))
    extensiones.registrar_hook("b", "cuenta", "despues", lambda **_: llamados.append("b"))
    extensiones.registrar_hook("c", "lead", "antes", lambda **_: llamados.append("c"))

    extensiones.antes_de("cuenta")
    assert llamados == ["a"]


def test_un_momento_inventado_se_rechaza_al_registrar() -> None:
    with pytest.raises(ValueError):
        extensiones.registrar_hook("x", "cuenta", "mientras", lambda **_: None)


def test_un_hook_lento_se_avisa_pero_no_se_corta(caplog: Any) -> None:
    """Cortarlo a mitad dejaría la operación en un estado que la extensión no
    esperaba. Lo que hace falta es saber quién está frenando el guardado."""
    import time

    extensiones.registrar_hook("lento", "cuenta", "antes", lambda **_: time.sleep(0.02), max_ms=1)
    extensiones.antes_de("cuenta")  # no lanza


# ── Asíncrono ─────────────────────────────────────────────────────────────


def test_el_patron_con_comodin_no_se_pasa_de_listo() -> None:
    """Sin el punto, `cuenta.*` casaría también con `cuenta_borrador.creada` y
    una extensión escucharía objetos que no son el suyo."""
    extensiones.al_ocurrir("x", "cuenta.*", lambda m: None)

    assert [s.nombre for s in extensiones.suscripciones_para("cuenta.creada")] == ["x"]
    assert extensiones.suscripciones_para("cuenta_borrador.creada") == []


def test_una_extension_rota_no_para_el_bus() -> None:
    """Si se propagara, una extensión mal escrita bloquearía la cola para todas
    las demás y el sistema se pararía entero por algo que es de un tenant."""
    import asyncio

    llamadas: list[str] = []

    def revienta(_: Any) -> None:
        raise RuntimeError("mal")

    extensiones.al_ocurrir("rota", "cuenta.creada", revienta)
    extensiones.al_ocurrir("buena", "cuenta.creada", lambda _: llamadas.append("ok"))

    asyncio.run(extensiones.consumidor_de_extensiones()({"tipo": "cuenta.creada"}))
    assert llamadas == ["ok"]


def test_un_comodin_total_escucha_todo() -> None:
    extensiones.al_ocurrir("todo", "*", lambda m: None)
    assert len(extensiones.suscripciones_para("lo.que.sea")) == 1
