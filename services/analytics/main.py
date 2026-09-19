"""Punto de entrada del servicio de explotación."""

from __future__ import annotations

from crmcore.service import crear_servicio

from services.analytics.api import ROUTERS
from services.analytics.cliente import comprobar_al_arrancar

app = crear_servicio(
    nombre="analytics",
    descripcion=(
        "Puerta a contecintelligence: correspondencia de organizaciones, canje "
        "del token de usuario final y salud de la integración. Los informes no "
        "pasan por aquí; los pide el navegador con ese token."
    ),
    routers=ROUTERS,
    # La comprobación va al arranque para que el fallo le llegue a quien
    # despliega, y no a quien abre el primer informe tres días después.
    al_arrancar=comprobar_al_arrancar,
)
