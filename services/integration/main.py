"""Punto de entrada del servicio de integración."""

from __future__ import annotations

from crmcore.service import crear_servicio

from services.integration.api import ROUTERS

app = crear_servicio(
    nombre="integration",
    descripcion=(
        "Conector HTTP/REST declarativo: integrar un sistema externo es "
        "configuración, no código. Credenciales cifradas con rotación, prueba "
        "de conectividad, paginación declarativa y monitor de ejecuciones."
    ),
    routers=ROUTERS,
)
