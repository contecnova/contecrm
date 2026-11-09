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
    from crmcore.tareas import Tarea, por_tenant

    from services.tenancy.alta import purgar

    s = get_settings()

    def _purgar_altas() -> dict[str, object]:
        # Sin tenant: las solicitudes son de antes de que exista ninguno.
        with sesion(sistema=True) as db:
            return {"borradas": purgar(db, dias=int(s.onboarding_retencion_dias))}

    return [
        Tarea("tenancy.altas_pendientes", int(s.tarea_purgas_intervalo_s), _purgar_altas),
        # El corte de consumo para facturación (CRM-00.01.06.07): se rehace el
        # del periodo en curso y se mandan los de periodos cerrados. Cada tenant
        # decide con su ajuste si se exporta solo; los que no, no hacen nada.
        Tarea(
            "tenancy.consumo_a_facturacion",
            int(s.tarea_facturacion_intervalo_s),
            por_tenant(_tenants_activos, _cortar_consumo),
        ),
    ]


def _tenants_activos() -> list[object]:
    from crmcore.db.session import sesion
    from sqlalchemy import select

    from services.tenancy.modelos import Tenant

    with sesion(sistema=True) as db:
        return list(db.execute(select(Tenant.id).where(Tenant.estado == "activo")).scalars().all())


def _cortar_consumo(tenant_id: object) -> dict[str, object]:
    from crmcore.db.session import sesion
    from crmcore.tenancy.context import con_contexto

    from services.tenancy.facturacion import barrer

    with con_contexto(tenant_id=tenant_id, origen="tareas"), sesion(tenant_id) as db:  # type: ignore[arg-type]
        return barrer(db, tenant_id)  # type: ignore[arg-type]


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
