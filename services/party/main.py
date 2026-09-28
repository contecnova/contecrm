"""Punto de entrada del servicio `party`."""

from __future__ import annotations

from typing import Any

from crmcore.service import crear_servicio

from services.party import (
    visibilidad,  # noqa: F401 — registra el resolutor de equipos
)
from services.party.api import ROUTERS
from services.party.api_actividades_extra import ROUTERS_ACTIVIDADES_EXTRA
from services.party.api_calidad import ROUTERS_CALIDAD
from services.party.api_proveedores import ROUTERS_PROVEEDORES
from services.party.consumidores import (
    consumir_comando,
    consumir_organigrama,
    consumir_salud,
)

_relevo: Any = None
_tarea_relevo: Any = None


def _tareas() -> list[Any]:
    """Los dos barridos de este servicio, que no los ejecutaba nadie.

    `barrer_recordatorios` es el que más se nota: un comercial pone un
    recordatorio en una actividad, lo ve guardado con su fecha, **y no le llega
    nunca**. Estaba escrito y probado desde el principio, y sin llamador.
    """
    from crmcore.config import get_settings
    from crmcore.db.session import sesion
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tareas import Tarea

    # SE IMPORTAN AQUÍ, al construir la lista, y no dentro de cada `_correr`: un
    # renombrado tiene que reventar el arranque, que es cuando hay alguien
    # mirando. Resuelto tarde, el fallo cae dentro del `except` del relevo y
    # harían falta tres vueltas para que se marque averiada.
    from services.party.servicio import barrer_recordatorios, barrer_reverificaciones

    s = get_settings()

    def _recordatorios() -> dict[str, Any]:
        with sesion(sistema=True) as db:
            return dict(barrer_recordatorios(db))

    def _reverificaciones() -> dict[str, Any]:
        with unidad_de_trabajo(None, sistema=True) as uow:
            return dict(barrer_reverificaciones(uow))

    return [
        Tarea("party.recordatorios", s.tarea_recordatorios_intervalo_s, _recordatorios),
        Tarea("party.reverificaciones", s.tarea_reverificaciones_intervalo_s, _reverificaciones),
    ]


async def _al_arrancar() -> None:
    """Comprueba el gestor documental al desplegar, no al abrir el primero.

    No impide arrancar salvo que se pida (`DMS_EXIGIR_AL_ARRANCAR`): el CRM
    operativo no puede depender del corpus documental.

    Y arranca el relevo de tareas periódicas, **que es lo que faltaba**: los dos
    barridos de este servicio estaban escritos, probados y sin nadie que los
    llamara.
    """
    global _relevo, _tarea_relevo
    import asyncio

    from crmcore.documental.cliente import comprobar_al_arrancar
    from crmcore.tareas import RelevoDeTareas

    comprobar_al_arrancar()
    _relevo = RelevoDeTareas(_tareas())
    _tarea_relevo = asyncio.create_task(_relevo.correr(), name="party-tareas")


async def _al_parar() -> None:
    if _relevo is not None:
        _relevo.parar()
    if _tarea_relevo is not None:
        _tarea_relevo.cancel()


app = crear_servicio(
    nombre="party",
    descripcion=(
        "Cuentas y contactos con jerarquías múltiples, actividades polimórficas, "
        "consentimientos con prueba, deduplicación con fusión reversible y vista "
        "360 consultable por cualquier frontend."
    ),
    routers=[*ROUTERS, *ROUTERS_ACTIVIDADES_EXTRA, *ROUTERS_CALIDAD, *ROUTERS_PROVEEDORES],
    al_arrancar=_al_arrancar,
    al_parar=_al_parar,
    # Las automatizaciones piden por el bus lo que no pueden escribir ellas: sus
    # comandos los atiende el servicio dueño del objeto. El patrón es ancho
    # porque el despachador ya filtra por manejador registrado.
    consumidores=[
        ("comando.*", consumir_comando, f"{__name__.split('.')[1]}-comandos"),
        # La jerarquía de mando se replica aquí para que la compartición por
        # jerarquía aplique en los listados (CRM-00.05.02.12): `superior_id` vive
        # en la membresía de identity y este servicio no lee su esquema.
        ("user.org.changed", consumir_organigrama, f"{__name__.split('.')[1]}-organigrama"),
        # La salud de la cuenta se calcula en `intelligence` y aquí se proyecta
        # (CRM-01.01.05.07): un número que solo existe allí no lo ve quien tiene
        # al cliente delante, y entonces no cambia ninguna conversación.
        ("account.health.scored", consumir_salud, f"{__name__.split('.')[1]}-salud"),
    ],
)
