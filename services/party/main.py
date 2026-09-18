"""Punto de entrada del servicio `party`."""

from __future__ import annotations

from crmcore.service import crear_servicio

# Los tipos de evento se registran al importar el módulo, antes de crear la
# aplicación: el catálogo de eventos tiene que estar completo cuando alguien
# consulte el AsyncAPI o se suscriba a un webhook.
from services.party import eventos  # noqa: F401
from services.party.api import ROUTERS

app = crear_servicio(
    nombre="party",
    descripcion=(
        "Cuentas y contactos con jerarquías múltiples, actividades polimórficas, "
        "consentimientos con prueba, deduplicación con fusión reversible y vista "
        "360 consultable por cualquier frontend."
    ),
    routers=ROUTERS,
)
