"""Punto de entrada del servicio de ventas."""

from __future__ import annotations

from crmcore.service import crear_servicio

from services.sales import eventos  # noqa: F401  — registra los tipos de evento
from services.sales.api import ROUTERS, ROUTERS_SIN_PREFIJO
from services.sales.api_cadencias import ROUTERS_CADENCIAS
from services.sales.api_cotizacion import ROUTERS_COTIZACION
from services.sales.consumidores import consumir_comando


def _al_arrancar() -> None:
    """Comprueba el gestor documental al desplegar, no al abrir el primero.

    No impide arrancar salvo que se pida (`DMS_EXIGIR_AL_ARRANCAR`): el CRM
    operativo no puede depender del corpus documental.
    """
    from crmcore.documental.cliente import comprobar_al_arrancar

    comprobar_al_arrancar()


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
    routers=[*ROUTERS, *ROUTERS_COTIZACION, *ROUTERS_CADENCIAS],
    al_arrancar=_al_arrancar,
    routers_sin_prefijo=ROUTERS_SIN_PREFIJO,
    # Las automatizaciones piden por el bus lo que no pueden escribir ellas: sus
    # comandos los atiende el servicio dueño del objeto. El patrón es ancho
    # porque el despachador ya filtra por manejador registrado.
    consumidores=[("comando.*", consumir_comando, f"{__name__.split('.')[1]}-comandos")],
)
