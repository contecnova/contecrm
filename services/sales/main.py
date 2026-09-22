"""Punto de entrada del servicio de ventas."""

from __future__ import annotations

from crmcore.service import crear_servicio

from services.sales import (
    eventos,  # noqa: F401  — registra los tipos de evento
    visibilidad,  # noqa: F401 — registra los resolutores
)
from services.sales.api import ROUTERS, ROUTERS_SIN_PREFIJO
from services.sales.api_cadencias import ROUTERS_CADENCIAS
from services.sales.api_comisiones import ROUTERS_COMISIONES
from services.sales.api_cotizacion import ROUTERS_COTIZACION
from services.sales.api_partners import ROUTERS_PARTNERS
from services.sales.api_territorios import ROUTERS_TERRITORIOS
from services.sales.consumidores import (
    consumir_comando,
    consumir_firma,
    consumir_organigrama,
)


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
    routers=[
        *ROUTERS,
        *ROUTERS_COTIZACION,
        *ROUTERS_CADENCIAS,
        *ROUTERS_TERRITORIOS,
        *ROUTERS_PARTNERS,
        *ROUTERS_COMISIONES,
    ],
    al_arrancar=_al_arrancar,
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
        # El sobre firmado mueve la oportunidad (CRM-03.03.02.07): el motor ya
        # emitía el evento con el registro de origen dentro, y lo que faltaba
        # era que alguien lo escuchara.
        ("signature.envelope.*", consumir_firma, f"{__name__.split('.')[1]}-firma"),
    ],
)
