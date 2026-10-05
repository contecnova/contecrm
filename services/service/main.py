"""Punto de entrada del servicio de atención al cliente."""

from __future__ import annotations

from typing import Any

from crmcore.service import crear_servicio

from services.service.api import ROUTERS, ROUTERS_SIN_PREFIJO
from services.service.api_campo import ROUTERS_CAMPO
from services.service.api_postventa import ROUTERS_POSTVENTA
from services.service.consumidores import consumir_comando

_relevo: Any = None
_tarea_relevo: Any = None


def _tareas() -> list[Any]:
    """Lo que este servicio hace solo, cada tanto.

    **El mantenimiento preventivo no se genera pulsando un botón.** Un plan
    mensual existe precisamente para que nadie tenga que acordarse: si la orden
    sólo sale cuando alguien entra en la pantalla y pulsa, el plan es una
    anotación y la máquina se revisa cuando se rompe. `generar_preventivas`
    tenía ruta y ningún reloj detrás.

    Las funciones se importan **aquí y no dentro del cuerpo**: si alguien
    renombra una, el arranque revienta —que es cuando hay alguien mirando— en
    vez de fallar en la primera vuelta.
    """
    from crmcore.config import get_settings
    from crmcore.db.session import sesion
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tareas import Tarea, por_tenant
    from sqlalchemy import select

    from services.service.campo import PlanPreventivo, generar_preventivas

    s = get_settings()

    def _tenants_con_planes() -> list[Any]:
        """Los que tienen planes, de **su propia tabla**.

        No se le pide la lista de tenants a `tenancy`: es de otro servicio y no
        se lee desde aquí. Y la lista buena es más corta.
        """
        with sesion(sistema=True) as db:
            return [
                t
                for (t,) in db.execute(
                    select(PlanPreventivo.tenant_id)
                    .where(PlanPreventivo.activo.is_(True))
                    .distinct()
                ).all()
            ]

    def _preventivas(tenant_id: Any) -> dict[str, Any]:
        with unidad_de_trabajo(tenant_id, sistema=True) as uow:
            salida = generar_preventivas(uow)
        return {"creadas": len(salida.get("creadas") or [])}

    return [
        Tarea(
            "service.preventivas",
            int(s.tarea_purgas_intervalo_s),
            por_tenant(_tenants_con_planes, _preventivas),
            # No al arrancar: catorce procesos levantándose a la vez generarían
            # catorce rondas, y la protección de «una por plan a la vez» va por
            # transacción, no entre procesos.
            al_arrancar=False,
        ),
    ]


async def _al_arrancar() -> None:
    global _relevo, _tarea_relevo
    import asyncio

    from crmcore.tareas import RelevoDeTareas

    _relevo = RelevoDeTareas(_tareas())
    _tarea_relevo = asyncio.create_task(_relevo.correr(), name="service-tareas")


async def _al_parar() -> None:
    if _relevo is not None:
        _relevo.parar()
    if _tarea_relevo is not None:
        _tarea_relevo.cancel()


app = crear_servicio(
    nombre="service",
    descripcion=(
        "Casos con taxonomía en árbol, severidad y prioridad separadas, "
        "jerarquía e incidencias masivas, cierre tipificado y reapertura con "
        "ventana, y relojes de SLA en horas laborables con pausas que desplazan "
        "el vencimiento."
    ),
    routers=[*ROUTERS, *ROUTERS_CAMPO, *ROUTERS_POSTVENTA],
    # La entrada de mensajes va sin el prefijo de versión: la URL se pega en la
    # configuración de un buzón, de una pasarela de WhatsApp o en el HTML de una
    # web, y una versión dentro invita a cambiarla el día que exista `v2`.
    routers_sin_prefijo=ROUTERS_SIN_PREFIJO,
    # Lo que otro servicio no puede escribir aquí, lo pide por el bus: hoy, la
    # telemetría de dispositivos, que abre casos sin tocar este esquema.
    consumidores=[("comando.*", consumir_comando, "service-comandos")],
    al_arrancar=_al_arrancar,
    al_parar=_al_parar,
)
