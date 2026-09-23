"""Punto de entrada del servicio de explotación."""

from __future__ import annotations

from crmcore.service import crear_servicio

from services.analytics.api import ROUTERS
from services.analytics.api_almacen import ROUTERS_ALMACEN
from services.analytics.api_cuadros import ROUTERS_CUADROS
from services.analytics.api_fuente import ROUTERS_FUENTE
from services.analytics.api_informes import ROUTERS_INFORMES
from services.analytics.cliente import comprobar_al_arrancar
from services.analytics.fuente import consumir_esquema_cambiado, ejecutar_plan
from services.analytics.informes import registrar_ejecutor


def _al_arrancar() -> None:
    """Comprueba la integración y **conecta el ejecutor de informes**.

    El motor de informes no importa a nadie: le registran quién ejecuta sus
    planes. Aquí es donde se conecta, y por eso un despliegue sin
    contecintelligence deja los informes definibles y no ejecutables, que es
    exactamente lo que se le dice a quien los abra.
    """
    registrar_ejecutor(ejecutar_plan)
    comprobar_al_arrancar()


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
)
