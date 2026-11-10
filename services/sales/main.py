"""Punto de entrada del servicio de ventas."""

from __future__ import annotations

from typing import Any

from crmcore.service import crear_servicio

from services.sales import (
    ajustes,  # noqa: F401 — registra los ajustes de negocio de este servicio
    visibilidad,  # noqa: F401 — registra los resolutores
)
from services.sales.api import ROUTERS, ROUTERS_SIN_PREFIJO
from services.sales.api_cadencias import ROUTERS_CADENCIAS
from services.sales.api_calidad_leads import ROUTERS_CALIDAD_LEADS
from services.sales.api_comisiones import ROUTERS_COMISIONES
from services.sales.api_coste import ROUTERS_COSTE
from services.sales.api_cotizacion import ROUTERS_COTIZACION
from services.sales.api_embebido import router_embebido
from services.sales.api_ingresos import ROUTERS_INGRESOS
from services.sales.api_lecciones import ROUTERS_LECCIONES
from services.sales.api_partners import ROUTERS_PARTNERS
from services.sales.api_proveedores import ROUTERS_PROVEEDORES
from services.sales.api_territorios import ROUTERS_TERRITORIOS
from services.sales.consumidores import (
    consumir_aprobacion,
    consumir_comando,
    consumir_cualificacion,
    consumir_firma,
    consumir_organigrama,
)
from services.sales.respuesta_erp import consumir_respuesta_erp

_relevo: Any = None
_tarea_relevo: Any = None


def _tareas() -> list[Any]:
    """Lo que este servicio hace solo, cada tanto.

    El resumen de lecciones aprendidas (CRM-03.01.01.18). Se mira a menudo
    —`lecciones_resumen_revisar_s`— y se genera sólo cuando toca, que es lo que
    lo hace inmune a los reinicios: un reloj de siete días se reiniciaría con
    cada despliegue y no saldría nunca.
    """
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.fechas import hoy
    from crmcore.tareas import Tarea, por_tenant

    from services.sales.ajustes import ajustes as ajustes_sales
    from services.sales.consejos import resumen, tenants_con_lecciones

    def _resumen(tenant_id: Any) -> dict[str, Any]:
        with unidad_de_trabajo(tenant_id, sistema=True) as uow:
            fila = resumen(uow, hoy=hoy(uow.db))
        return {"generado": fila is not None}

    from services.sales.presupuestos import revisar_renovaciones, tenants_con_contratos

    def _renovaciones(tenant_id: Any) -> dict[str, Any]:
        # Los preavisos, las renovaciones automáticas y las oportunidades de
        # renovación (CRM-03.03.02.10). Antes sólo lo hacía quien pulsara
        # «revisar renovaciones», es decir: nadie.
        with unidad_de_trabajo(tenant_id, sistema=True) as uow:
            salida = revisar_renovaciones(uow, tenant_id)
        return {
            "avisados": len(salida["avisados"]),
            "renovados": len(salida["renovados"]),
            "oportunidades": len(salida["oportunidades"]),
        }

    return [
        Tarea(
            "sales.renovaciones",
            int(ajustes_sales().renovacion_revisar_s),
            por_tenant(tenants_con_contratos, _renovaciones),
            al_arrancar=False,
        ),
        Tarea(
            "sales.resumen_lecciones",
            int(ajustes_sales().lecciones_resumen_revisar_s),
            por_tenant(tenants_con_lecciones, _resumen),
            al_arrancar=False,
        ),
    ]


async def _al_arrancar() -> None:
    """Comprueba el gestor documental al desplegar, y arranca las tareas.

    El gestor no impide arrancar salvo que se pida (`DMS_EXIGIR_AL_ARRANCAR`):
    el CRM operativo no puede depender del corpus documental.
    """
    global _relevo, _tarea_relevo
    import asyncio

    from crmcore.config import get_settings
    from crmcore.documental.cliente import comprobar_al_arrancar
    from crmcore.tareas import RelevoDeTareas

    comprobar_al_arrancar()
    if get_settings().tareas_fondo_enabled:
        _relevo = RelevoDeTareas(_tareas())
        _tarea_relevo = asyncio.create_task(_relevo.correr(), name="sales-tareas")


async def _al_parar() -> None:
    if _relevo is not None:
        _relevo.parar()
    if _tarea_relevo is not None:
        _tarea_relevo.cancel()


app = crear_servicio(
    nombre="sales",
    descripcion=(
        "Leads con SLA de primera respuesta, conversión trazable, pipelines "
        "múltiples con criterios de salida por etapa, oportunidades con líneas "
        "y competidores, y cierre bloqueado con reapertura auditada. Encima, "
        "la cotización: catálogo con configuración, motor de precios explicable, "
        "presupuestos versionados con matriz de descuentos por margen, "
        "contratos con preaviso, suscripciones con prorrateo y traspaso al ERP "
        "que no se cierra hasta que el ERP contesta."
    ),
    routers=[
        # Antes que los de leads: `/leads/calidad-dato/…` no debe caer en una
        # ruta `/leads/{lead_id}/…`.
        *ROUTERS_CALIDAD_LEADS,
        *ROUTERS,
        *ROUTERS_COSTE,
        *ROUTERS_INGRESOS,
        *ROUTERS_COTIZACION,
        *ROUTERS_CADENCIAS,
        *ROUTERS_TERRITORIOS,
        *ROUTERS_PARTNERS,
        *ROUTERS_COMISIONES,
        *ROUTERS_PROVEEDORES,
        *ROUTERS_LECCIONES,
        router_embebido,
    ],
    al_arrancar=_al_arrancar,
    al_parar=_al_parar,
    routers_sin_prefijo=ROUTERS_SIN_PREFIJO,
    # Las automatizaciones piden por el bus lo que no pueden escribir ellas: sus
    # comandos los atiende el servicio dueño del objeto. El patrón es ancho
    # porque el despachador ya filtra por manejador registrado.
    consumidores=[
        ("comando.*", consumir_comando, f"{__name__.split('.')[1]}-comandos"),
        # La jerarquía de mando se replica aquí para que la compartición por
        # jerarquía aplique en los listados (CRM-00.05.02.12): `superior_id` vive
        # en la membresía de identity y este servicio no lee su esquema.
        ("user.org.changed", consumir_organigrama, f"{__name__.split('.')[1]}-organigrama"),
        # Y el mapa de territorios (CRM-00.05.02.07). `visibilidad.py`
        # resolvía el acceso por territorio contra una tabla replicada que
        # **no escribía nadie**: el evento lo emitía `sales` y no lo
        # consumía ningún servicio, así que esa vía devolvía siempre vacío.
        # El sobre firmado mueve la oportunidad (CRM-03.03.02.07): el motor ya
        # emitía el evento con el registro de origen dentro, y lo que faltaba
        # era que alguien lo escuchara.
        ("signature.envelope.*", consumir_firma, f"{__name__.split('.')[1]}-firma"),
        # Y lo que el ERP conteste del pedido. `enviar_a_erp` lo deja esperando
        # confirmación a propósito —el ERP puede aceptar el mensaje y rechazar
        # el pedido después— y lo que faltaba era quien recoge la respuesta: el
        # pedido se quedaba en «enviado_erp» para siempre, y eso se descubre en
        # el cierre de mes.
        ("order.erp.*", consumir_respuesta_erp, f"{__name__.split('.')[1]}-erp"),
        # Lo que se decidió en la aprobación de un presupuesto (orchestrator).
        ("approval.decided", consumir_aprobacion, f"{__name__.split('.')[1]}-aprobaciones"),
        # Marketing califica el lead (MQL/SQL) y ventas lo recoge: puntuación en
        # la ficha y, al llegar a SQL, «cualificado» (CRM-02.01.02.05).
        ("lead.qualified", consumir_cualificacion, f"{__name__.split('.')[1]}-cualificacion"),
    ],
)
