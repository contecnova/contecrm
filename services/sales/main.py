"""Punto de entrada del servicio de ventas."""

from __future__ import annotations

from crmcore.service import crear_servicio

from services.sales import eventos  # noqa: F401  — registra los tipos de evento
from services.sales.api import ROUTERS
from services.sales.consumidores import consumir_comando

app = crear_servicio(
    nombre="sales",
    descripcion=(
        "Leads con SLA de primera respuesta, conversión trazable, pipelines "
        "múltiples con criterios de salida por etapa, oportunidades con líneas "
        "y competidores, y cierre bloqueado con reapertura auditada."
    ),
    routers=ROUTERS,
    # Las automatizaciones piden por el bus lo que no pueden escribir ellas: sus
    # comandos los atiende el servicio dueño del objeto. El patrón es ancho
    # porque el despachador ya filtra por manejador registrado.
    consumidores=[("comando.*", consumir_comando, f"{__name__.split('.')[1]}-comandos")],
)
