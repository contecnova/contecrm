"""Punto de entrada del servicio de tenancy."""

from __future__ import annotations

from crmcore.documental.inventario import INVENTARIO_REPORTADO
from crmcore.service import crear_servicio

from services.tenancy import estado_componentes  # noqa: F401 — registra su componente de estado
from services.tenancy.api import ROUTERS
from services.tenancy.baja import consumir_reporte_inventario

_relevo: object = None
_tarea_relevo: object = None


def _tareas() -> list[object]:
    """La purga de solicitudes de alta.

    Se importa AQUÍ, al construir la lista, y no dentro del `_correr`: si
    alguien renombra la función, el arranque revienta —que es cuando hay alguien
    mirando— en vez de fallar en la primera vuelta y tardar tres en marcarse
    averiada.
    """
    from crmcore.config import get_settings
    from crmcore.db.session import sesion
    from crmcore.tareas import Tarea

    from services.tenancy.alta import purgar

    s = get_settings()

    def _purgar_altas() -> dict[str, object]:
        # Sin tenant: las solicitudes son de antes de que exista ninguno.
        with sesion(sistema=True) as db:
            return {"borradas": purgar(db, dias=int(s.onboarding_retencion_dias))}

    return [Tarea("tenancy.altas_pendientes", int(s.tarea_purgas_intervalo_s), _purgar_altas)]


async def _al_arrancar() -> None:
    """Arranca el relevo con la purga de solicitudes de alta.

    Sin él, `altas_pendientes` crecería con cada intento —incluidos los de quien
    prueba nombres de empresa— y sería la tabla más grande del esquema, llena de
    correos de gente que nunca llegó a ser cliente. Eso es dato personal que no
    hay motivo para guardar.
    """
    global _relevo, _tarea_relevo
    import asyncio

    from crmcore.tareas import RelevoDeTareas

    _relevo = RelevoDeTareas(_tareas())
    _tarea_relevo = asyncio.create_task(_relevo.correr(), name="tenancy-tareas")


async def _al_parar() -> None:
    if _relevo is not None:
        _relevo.parar()
    if _tarea_relevo is not None:
        _tarea_relevo.cancel()


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
    al_arrancar=_al_arrancar,
    al_parar=_al_parar,
)
