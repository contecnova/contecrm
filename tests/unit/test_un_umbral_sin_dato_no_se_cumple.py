"""Una comparación numérica contra un dato que falta NO se cumple (FUN-A-7).

Auditoría del 13-11-2026. Las dos conversiones a número —la de las
aprobaciones y la del motor de procesos— daban 0 a lo que no lo era. Con eso
`importe < 1000` y el importe vacío valía `0 < 1000`, que es cierto:

  * una regla de aprobación automática aprobaba sola la solicitud a la que le
    faltaba justo el dato que la justificaba;
  * una condición de proceso, de automatización o de webhook se cumplía cuando
    no había nada que comparar, contra lo que su propio docstring prometía.

Sin base de datos: es una decisión sobre valores y se prueba sobre valores.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from services.orchestrator.motor import OPERADORES, cumple_condicion

VACIOS: list[Any] = [None, "", "   ", "abc", "nan", "inf", [], {}]


# ── Motor de procesos (y con él automatizaciones y webhooks) ──────────────


@pytest.mark.parametrize("op", ["<", "<=", ">", ">="])
@pytest.mark.parametrize("vacio", VACIOS)
def test_un_operador_numerico_con_el_dato_vacio_no_se_cumple(op: str, vacio: Any) -> None:
    """**Esta es la del agujero**: `<` y `<=` daban cierto con el dato vacío."""
    assert OPERADORES[op](vacio, 1000) is False
    assert OPERADORES[op](1000, vacio) is False


@pytest.mark.parametrize(
    ("op", "a", "b", "esperado"),
    [
        ("<", 999, 1000, True),
        ("<", "999.5", "1000", True),
        ("<", Decimal("1000"), 1000, False),
        ("<=", 1000, "1000", True),
        (">", " 1001 ", 1000, True),
        (">=", 0, 0, True),
        (">", -1, 0, False),
    ],
)
def test_con_numeros_de_verdad_se_compara_como_siempre(
    op: str, a: Any, b: Any, esperado: bool
) -> None:
    """Lo arreglado no puede romper lo que funcionaba: el 0 de verdad es un
    número, y el texto numérico que manda un formulario también."""
    assert OPERADORES[op](a, b) is esperado


def test_la_antiguedad_sin_umbral_no_se_cumple() -> None:
    """`hace_mas_de_horas` sin horas comparaba contra 0: cualquier fecha del
    pasado «hacía más de 0 horas»."""
    hace_un_dia = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert OPERADORES["hace_mas_de_horas"](hace_un_dia, None) is False
    assert OPERADORES["hace_mas_de_horas"](hace_un_dia, "") is False
    assert OPERADORES["hace_mas_de_horas"](hace_un_dia, 12) is True
    assert OPERADORES["hace_menos_de_horas"](hace_un_dia, 48) is True
    assert OPERADORES["hace_mas_de_horas"](None, 12) is False


def test_una_decision_sin_el_dato_se_va_por_el_si_no() -> None:
    condicion = {"atributo": "importe", "op": "<", "valor": 1000}
    assert cumple_condicion(condicion, {}) is False
    assert cumple_condicion(condicion, {"importe": ""}) is False
    assert cumple_condicion(condicion, {"importe": 500}) is True


def test_un_webhook_con_condicion_numerica_no_recibe_lo_que_no_la_cumple() -> None:
    """`eventing.entrega.coincide` evalúa con los mismos operadores: un evento
    sin el importe se le mandaba al integrador que pidió «importe < 1000»."""
    from services.eventing.entrega import coincide

    suscripcion = SimpleNamespace(
        eventos=["quote.*"], condiciones=[{"atributo": "importe", "op": "<", "valor": 1000}]
    )
    assert coincide(suscripcion, SimpleNamespace(type="quote.accepted", data={})) is False  # type: ignore[arg-type]
    assert (
        coincide(suscripcion, SimpleNamespace(type="quote.accepted", data={"importe": ""}))  # type: ignore[arg-type]
        is False
    )
    assert (
        coincide(suscripcion, SimpleNamespace(type="quote.accepted", data={"importe": 10}))  # type: ignore[arg-type]
        is True
    )


# ── Aprobación automática bajo umbral (CRM-00.03.05.11) ───────────────────


UMBRAL = {"campo": "importe", "menor_que": 1000}


@pytest.mark.parametrize("contexto", [{}, {"importe": None}, {"importe": ""}, {"importe": "abc"}])
def test_sin_el_dato_la_solicitud_no_se_aprueba_sola(contexto: dict[str, Any]) -> None:
    from services.orchestrator.aprobaciones import bajo_umbral_automatico

    assert bajo_umbral_automatico(UMBRAL, contexto) is None


@pytest.mark.parametrize(
    "umbral",
    [
        {"campo": "importe"},
        {"campo": "importe", "menor_que": ""},
        {"campo": "importe", "menor_que": "mil"},
        {"campo": "", "menor_que": 1000},
        {},
        None,
    ],
)
def test_un_umbral_mal_escrito_no_aprueba_nada(umbral: dict[str, Any] | None) -> None:
    """Un tope ausente valía 0, y un importe negativo —un abono— «estaba por
    debajo»."""
    from services.orchestrator.aprobaciones import bajo_umbral_automatico

    assert bajo_umbral_automatico(umbral, {"importe": -50}) is None


def test_bajo_umbral_con_el_dato_si_se_aprueba_sola() -> None:
    from services.orchestrator.aprobaciones import bajo_umbral_automatico

    assert bajo_umbral_automatico(UMBRAL, {"importe": "999.99"}) == (
        "importe",
        Decimal("999.99"),
        Decimal("1000"),
    )
    assert bajo_umbral_automatico(UMBRAL, {"importe": 0}) == ("importe", Decimal(0), Decimal(1000))
    assert bajo_umbral_automatico(UMBRAL, {"importe": 1000}) is None
