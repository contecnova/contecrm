"""Punto de entrada del servicio de atención al cliente."""

from __future__ import annotations

from crmcore.service import crear_servicio

from services.service.api import ROUTERS, ROUTERS_SIN_PREFIJO
from services.service.api_campo import ROUTERS_CAMPO
from services.service.api_postventa import ROUTERS_POSTVENTA
from services.service.consumidores import consumir_comando

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
)
