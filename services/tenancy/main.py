"""Punto de entrada del servicio de tenancy."""

from __future__ import annotations

from crmcore.documental.inventario import INVENTARIO_REPORTADO
from crmcore.service import crear_servicio

from services.tenancy import estado_componentes  # noqa: F401 — registra su componente de estado
from services.tenancy.api import ROUTERS
from services.tenancy.baja import consumir_reporte_inventario

app = crear_servicio(
    nombre="tenancy",
    descripcion=(
        "Ciclo de vida del tenant, jerarquía de configuración, planes y "
        "capacidades, feature flags, cuotas y medición de consumo."
    ),
    routers=ROUTERS,
    # Solo `tenancy` consume las respuestas al inventario documental: es quien
    # emite el certificado de destrucción y quien las necesita (RT-5). La
    # solicitud, en cambio, la consumen todos, y de eso se encarga
    # `crear_servicio` sin que ningún servicio tenga que acordarse.
    consumidores=[
        (INVENTARIO_REPORTADO, consumir_reporte_inventario, "tenancy-invdoc-reportes"),
    ],
)
