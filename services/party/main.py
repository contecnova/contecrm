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
from services.party.api_actividades_extra import ROUTERS_ACTIVIDADES_EXTRA
from services.party.api_calidad import ROUTERS_CALIDAD
from services.party.consumidores import consumir_comando, consumir_organigrama


def _al_arrancar() -> None:
    """Comprueba el gestor documental al desplegar, no al abrir el primero.

    No impide arrancar salvo que se pida (`DMS_EXIGIR_AL_ARRANCAR`): el CRM
    operativo no puede depender del corpus documental.
    """
    from crmcore.documental.cliente import comprobar_al_arrancar

    comprobar_al_arrancar()


app = crear_servicio(
    nombre="party",
    descripcion=(
        "Cuentas y contactos con jerarquías múltiples, actividades polimórficas, "
        "consentimientos con prueba, deduplicación con fusión reversible y vista "
        "360 consultable por cualquier frontend."
    ),
    routers=[*ROUTERS, *ROUTERS_ACTIVIDADES_EXTRA, *ROUTERS_CALIDAD],
    al_arrancar=_al_arrancar,
    # Las automatizaciones piden por el bus lo que no pueden escribir ellas: sus
    # comandos los atiende el servicio dueño del objeto. El patrón es ancho
    # porque el despachador ya filtra por manejador registrado.
    consumidores=[
        ("comando.*", consumir_comando, f"{__name__.split('.')[1]}-comandos"),
        # La jerarquía de mando se replica aquí para que la compartición por
        # jerarquía aplique en los listados (CRM-00.05.02.12): `superior_id` vive
        # en la membresía de identity y este servicio no lee su esquema.
        ("user.org.changed", consumir_organigrama, f"{__name__.split('.')[1]}-organigrama"),
    ],
)
