"""Punto de entrada del servicio de explotación."""

from __future__ import annotations

from typing import Any

from crmcore.service import crear_servicio

# Importarlo registra el ejecutor del trabajo de alta de fuente. La API lo
# necesita para poder ENCOLARLO —`encolar` se niega si no hay ejecutor, y hace
# bien: aceptar un trabajo que nadie va a ejecutar es dejarlo encolado para
# siempre—, y el worker lo importa por su cuenta porque es otro proceso.
import services.analytics.trabajos_fuente  # noqa: F401,E402
from services.analytics.api import ROUTERS
from services.analytics.api_almacen import ROUTERS_ALMACEN
from services.analytics.api_cuadros import ROUTERS_CUADROS
from services.analytics.api_fuente import ROUTERS_FUENTE
from services.analytics.api_informes import ROUTERS_INFORMES
from services.analytics.cliente import comprobar_al_arrancar
from services.analytics.fuente import consumir_esquema_cambiado, ejecutar_plan
from services.analytics.informes import correr_programadas, registrar_ejecutor

_relevo: Any = None
_tarea_relevo: Any = None


def _tenants_con_programaciones() -> list[Any]:
    """Los tenants que tienen algo programado, de NUESTRA propia tabla.

    Así no hace falta la lista de tenants —que es de `tenancy` y no se puede
    leer desde aquí— y además no se pasea por los que no tienen nada.
    """
    from crmcore.db.session import sesion
    from sqlalchemy import select

    from services.analytics.informes import ProgramacionInforme

    with sesion(sistema=True) as db:
        return list(
            db.execute(
                select(ProgramacionInforme.tenant_id)
                .where(ProgramacionInforme.activa.is_(True))
                .distinct()
            )
            .scalars()
            .all()
        )


def _correr_para(tenant_id: Any) -> dict[str, Any]:
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto

    with (
        con_contexto(tenant_id=tenant_id, origen="tareas"),
        unidad_de_trabajo(tenant_id) as uow,
    ):
        return dict(correr_programadas(uow, tenant_id))


def _tareas() -> list[Any]:
    """El barrido de informes programados, que no ejecutaba nadie.

    Existía la ruta `POST /informes/correr-programadas` y **nada la disparaba**:
    un usuario programaba un informe, lo veía activo con su horario al lado, y
    no llegaba nunca. Sin error.
    """
    from crmcore.config import get_settings
    from crmcore.tareas import Tarea, por_tenant

    return [
        Tarea(
            "analytics.informes_programados",
            get_settings().tarea_informes_intervalo_s,
            por_tenant(_tenants_con_programaciones, _correr_para),
        )
    ]


async def _al_arrancar() -> None:
    """Comprueba la integración y **conecta el ejecutor de informes**.

    El motor de informes no importa a nadie: le registran quién ejecuta sus
    planes. Aquí es donde se conecta, y por eso un despliegue sin
    contecintelligence deja los informes definibles y no ejecutables, que es
    exactamente lo que se le dice a quien los abra.
    """
    global _relevo, _tarea_relevo
    import asyncio

    from crmcore.tareas import RelevoDeTareas

    registrar_ejecutor(ejecutar_plan)
    comprobar_al_arrancar()
    _relevo = RelevoDeTareas(_tareas())
    _tarea_relevo = asyncio.create_task(_relevo.correr(), name="analytics-tareas")


async def _al_parar() -> None:
    if _relevo is not None:
        _relevo.parar()
    if _tarea_relevo is not None:
        _tarea_relevo.cancel()


app = crear_servicio(
    nombre="analytics",
    descripcion=(
        "Puerta a contecintelligence: correspondencia de organizaciones, canje "
        "del token de usuario final y salud de la integración. Los informes no "
        "pasan por aquí; los pide el navegador con ese token. Lo que sí vive "
        "aquí es el motor de informes: la definición, el sobre de seguridad, el "
        "plan compilado, la programación y el histórico de instantáneas. La "
        "consulta la ejecuta quien tiene el dato."
    ),
    routers=[
        *ROUTERS,
        *ROUTERS_INFORMES,
        *ROUTERS_FUENTE,
        *ROUTERS_CUADROS,
        *ROUTERS_ALMACEN,
    ],
    # Cuando el tenant cambia su esquema, la descripción que tiene
    # contecintelligence se queda vieja. Se rehace por evento y no por reloj: un
    # registro que se refresca cada noche está desfasado justo después de que
    # alguien añada un campo, que es cuando lo va a buscar.
    consumidores=[("metadata.schema.changed", consumir_esquema_cambiado, "analytics-fuente")],
    # La comprobación va al arranque para que el fallo le llegue a quien
    # despliega, y no a quien abre el primer informe tres días después.
    al_arrancar=_al_arrancar,
    al_parar=_al_parar,
)
