"""Punto de entrada del servicio de tenancy."""

from __future__ import annotations

from crmcore.service import crear_servicio

from services.tenancy import estado_componentes  # noqa: F401 — registra su componente de estado
from services.tenancy.api import ROUTERS

app = crear_servicio(
    nombre="tenancy",
    descripcion=(
        "Ciclo de vida del tenant, jerarquía de configuración, planes y "
        "capacidades, feature flags, cuotas y medición de consumo."
    ),
    routers=ROUTERS,
)
