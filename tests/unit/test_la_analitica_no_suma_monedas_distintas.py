"""FUN-B-9 en analytics: la correlación actividad-ganadas sumaba
`importe_funcional or importe`, y como `sales` no rellena `importe_funcional`,
sumaba dólares con euros. Ahora el importe crudo sólo vale si ya está en la
moneda funcional; el resto se cuenta aparte."""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import patch

from services.analytics import datos_crm as dc

HOY = date(2026, 11, 14)


class _Lector:
    procedencia: dict[str, Any] = {}

    def leer(self, objeto: str, **_: Any) -> list[dict[str, Any]]:
        if objeto != "oportunidad":
            return []
        base = {"owner_id": "u1", "estado": "ganada", "fecha_cierre": "2026-11-01"}
        return [
            {**base, "importe": "100", "moneda": "EUR"},
            {**base, "importe": "100", "moneda": "USD"},
            {**base, "importe": "999", "moneda": "USD", "importe_funcional": "50"},
        ]


def test_las_ganadas_en_otra_moneda_sin_convertir_no_se_suman() -> None:
    with (
        patch.object(
            dc.rt,
            "efectivo",
            lambda clave, db=None, **_: "EUR" if clave == "moneda_funcional" else None,
        ),
        patch.object(dc, "_ajuste", lambda clave, db, defecto: defecto),
    ):
        salida = dc.actividad_crm(None, None, hoy=HOY, desde=date(2026, 1, 1), lector=_Lector())

    [persona] = salida["por_persona"]
    assert persona["ganadas"] == 3
    assert persona["importe"] == 150.0  # 100 € + 50 convertidos; los 100 $ crudos, fuera
    assert salida["ganadas_sin_convertir"] == 1
    assert salida["moneda"] == "EUR"
