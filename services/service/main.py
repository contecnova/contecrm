"""Punto de entrada del servicio de atención al cliente."""

from __future__ import annotations

from crmcore.service import crear_servicio

from services.service.api import ROUTERS

app = crear_servicio(
    nombre="service",
    descripcion=(
        "Casos con taxonomía en árbol, severidad y prioridad separadas, "
        "jerarquía e incidencias masivas, cierre tipificado y reapertura con "
        "ventana, y relojes de SLA en horas laborables con pausas que desplazan "
        "el vencimiento."
    ),
    routers=ROUTERS,
)
