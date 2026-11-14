"""Sumar importes de monedas distintas sin mezclarlas (auditoría 13-11-2026, FUN-B-9).

MRR y ARR, el ingreso previsto por mes, el embudo por etapa y el acierto de los
ajustes de previsión sumaban `importe` a secas. Con una suscripción en dólares
y otra en euros, el MRR salía como si un dólar fuera un euro, y nada lo decía.
La previsión (`forecast.calcular`) ya convertía; el resto, no.

Un sitio para hacerlo igual en todos: se convierte a la **moneda funcional** del
tenant con el cambio vigente en la fecha que toca (`crmcore.datos.cambio`), y lo
que no se puede convertir **no se suma**: se cuenta aparte para decirlo, porque
sumarlo crudo es dar un número falso con aspecto de bueno.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.datos.cambio import convertir
from crmcore.errors import NoEncontrado
from sqlalchemy.orm import Session


def moneda_funcional(db: Session) -> str:
    """La moneda en la que el tenant lleva sus cuentas (ajuste `moneda_funcional`)."""
    from crmcore.runtime import settings as rt

    return str(rt.efectivo("moneda_funcional", db) or "EUR").upper()


@dataclass
class Conversor:
    """Convierte a la moneda funcional y apunta lo que no ha podido convertir."""

    db: Session
    tenant_id: UUID
    moneda: str = ""
    sin_tipo_de_cambio: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.moneda = (self.moneda or moneda_funcional(self.db)).upper()

    def __call__(
        self, importe: Any, desde: str | None, en_fecha: date | None, *, ref: Any = ""
    ) -> Decimal | None:
        """El importe convertido, o `None` si no hay cambio (y queda apuntado)."""
        valor = Decimal(str(importe or 0))
        origen = (desde or self.moneda).upper()
        if origen == self.moneda:
            return valor
        try:
            return convertir(
                self.db,
                tenant_id=self.tenant_id,
                importe=valor,
                desde=origen,
                hasta=self.moneda,
                en_fecha=en_fecha,
            )
        except NoEncontrado:
            self.sin_tipo_de_cambio.append(str(ref))
            return None

    def resumen(self) -> dict[str, Any]:
        """Lo que acompaña a cualquier suma convertida: en qué moneda va y qué faltó."""
        return {
            "moneda": self.moneda,
            "sin_tipo_de_cambio": len(self.sin_tipo_de_cambio),
            "aviso_moneda": (
                f"{len(self.sin_tipo_de_cambio)} importes no se han sumado porque no hay "
                f"tipo de cambio a {self.moneda} para su fecha."
                if self.sin_tipo_de_cambio
                else ""
            ),
        }
