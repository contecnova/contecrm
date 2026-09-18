"""Punto de entrada del servicio de identidad."""

from __future__ import annotations

from crmcore.service import crear_servicio

from services.identity.api import ROUTERS
from services.identity.notificaciones import consumir_evento

app = crear_servicio(
    nombre="identity",
    descripcion=(
        "Usuarios, membresías por tenant, roles y permisos, sesiones "
        "revocables, MFA, claves de API, federación y suplantación auditada."
    ),
    routers=ROUTERS,
    # Las notificaciones se alimentan de eventos, no de escrituras cruzadas: los
    # servicios dueños de cada objeto no tienen permiso sobre este esquema, y no
    # tenerlo es lo que garantiza la propiedad exclusiva del dato. El patrón es
    # ancho a propósito —la tabla `AVISOS` filtra— para que añadir un aviso no
    # obligue a redesplegar con una suscripción nueva.
    consumidores=[("*", consumir_evento, "identity-notificaciones")],
)
