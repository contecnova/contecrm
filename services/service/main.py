"""Punto de entrada del servicio de atención al cliente."""

from __future__ import annotations

from crmcore.service import crear_servicio

from services.service.api import ROUTERS, ROUTERS_SIN_PREFIJO

app = crear_servicio(
    nombre="service",
    descripcion=(
        "Casos con taxonomía en árbol, severidad y prioridad separadas, "
        "jerarquía e incidencias masivas, cierre tipificado y reapertura con "
        "ventana, y relojes de SLA en horas laborables con pausas que desplazan "
        "el vencimiento."
    ),
    routers=ROUTERS,
    # La entrada de mensajes va sin el prefijo de versión: la URL se pega en la
    # configuración de un buzón, de una pasarela de WhatsApp o en el HTML de una
    # web, y una versión dentro invita a cambiarla el día que exista `v2`.
    routers_sin_prefijo=ROUTERS_SIN_PREFIJO,
)
