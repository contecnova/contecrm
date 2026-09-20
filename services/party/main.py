"""Punto de entrada del servicio `party`."""

from __future__ import annotations

from crmcore.service import crear_servicio

# Los tipos de evento se registran al importar el módulo, antes de crear la
# aplicación: el catálogo de eventos tiene que estar completo cuando alguien
# consulte el AsyncAPI o se suscriba a un webhook.
from services.party import (
    eventos,  # noqa: F401
    visibilidad,  # noqa: F401 — registra el resolutor de equipos
)
from services.party.api import ROUTERS
from services.party.consumidores import consumir_comando

app = crear_servicio(
    nombre="party",
    descripcion=(
        "Cuentas y contactos con jerarquías múltiples, actividades polimórficas, "
        "consentimientos con prueba, deduplicación con fusión reversible y vista "
        "360 consultable por cualquier frontend."
    ),
    routers=ROUTERS,
    # Las automatizaciones piden por el bus lo que no pueden escribir ellas: sus
    # comandos los atiende el servicio dueño del objeto. El patrón es ancho
    # porque el despachador ya filtra por manejador registrado.
    consumidores=[("comando.*", consumir_comando, f"{__name__.split('.')[1]}-comandos")],
)
