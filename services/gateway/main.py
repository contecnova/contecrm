"""Punto de entrada del gateway."""

from __future__ import annotations

from crmcore.service import crear_servicio
from services.gateway.api import ROUTERS, ROUTERS_SIN_PREFIJO, arrancar, parar

app = crear_servicio(
    nombre="gateway",
    descripcion=(
        "Única puerta de entrada: resolución de tenant, autenticación, límites "
        "y enrutado con identidad firmada. Sin lógica de negocio, a propósito."
    ),
    routers=ROUTERS,
    routers_sin_prefijo=ROUTERS_SIN_PREFIJO,
    al_arrancar=arrancar,
    al_parar=parar,
    # El gateway no publica eventos de dominio ni tiene tablas propias: su
    # estado es la tabla de rutas, que viene de la configuración.
    necesita_bus=False,
    necesita_db=False,
)
