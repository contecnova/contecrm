"""Punto de entrada del servicio de eventos salientes."""

from __future__ import annotations

from crmcore.service import crear_servicio

from services.eventing import estado_componentes  # noqa: F401 — registra su componente de estado
from services.eventing.api import ROUTERS

app = crear_servicio(
    nombre="eventing",
    descripcion=(
        "Webhooks con firma HMAC y anti-replay, reintentos con backoff, "
        "desactivación automática de endpoints muertos, catálogo AsyncAPI "
        "generado del código, archivo de eventos y replay por ventana de tiempo."
    ),
    routers=ROUTERS,
)
