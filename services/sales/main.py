"""Punto de entrada del servicio de ventas."""

from __future__ import annotations

from crmcore.service import crear_servicio

from services.sales import eventos  # noqa: F401  — registra los tipos de evento
from services.sales.api import ROUTERS

app = crear_servicio(
    nombre="sales",
    descripcion=(
        "Leads con SLA de primera respuesta, conversión trazable, pipelines "
        "múltiples con criterios de salida por etapa, oportunidades con líneas "
        "y competidores, y cierre bloqueado con reapertura auditada."
    ),
    routers=ROUTERS,
)
