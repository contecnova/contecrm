"""Punto de entrada del servicio de automatizaciones."""

from __future__ import annotations

from typing import Any

from crmcore.service import crear_servicio

from services.automation.api import ROUTERS
from services.automation.api_codigo import ROUTERS_CODIGO
from services.automation.consumidores import consumir_evento

_relevo: Any = None
_tarea_relevo: Any = None


async def _al_arrancar() -> None:
    """Declara el medidor de código propio y arranca el planificador.

    El planificador es lo que hace verdad el «momento» de cada regla: atiende
    la cola de las diferidas y el reloj de las programadas
    (`services.automation.planificador`). Sin él, las dos se guardaban y no
    corrían nunca.
    """
    global _relevo, _tarea_relevo
    import asyncio

    from crmcore.config import get_settings
    from crmcore.consumo import registrar_medidor
    from crmcore.tareas import RelevoDeTareas

    from services.automation import planificador
    from services.automation.codigo_tenant import _ejecuciones_del_mes

    def _medir(db: object, tenant_id: object) -> tuple[int, str]:
        return _ejecuciones_del_mes(db, tenant_id), "cuota_extensiones_mes"  # type: ignore[arg-type]

    registrar_medidor("extensiones", _medir)

    if get_settings().tareas_fondo_enabled:
        _relevo = RelevoDeTareas(planificador.tareas())
        _tarea_relevo = asyncio.create_task(_relevo.correr(), name="automation-planificador")


async def _al_parar() -> None:
    if _relevo is not None:
        _relevo.parar()
    if _tarea_relevo is not None:
        _tarea_relevo.cancel()


app = crear_servicio(
    nombre="automation",
    descripcion=(
        "Automatizaciones declarativas «cuando X, si Y, entonces Z», con orden "
        "determinista entre reglas, corte de cascada, prueba en seco y traza de "
        "por qué una regla no se disparó."
    ),
    routers=[*ROUTERS, *ROUTERS_CODIGO],
    # Las reglas se disparan con los eventos de dominio de los demás servicios.
    # El patrón es ancho y filtra la tabla `DISPARADORES`: mantener una lista de
    # suscripciones al día con esa tabla sería una segunda fuente de verdad.
    consumidores=[("*", consumir_evento, "automation-reglas")],
    al_arrancar=_al_arrancar,
    al_parar=_al_parar,
)
