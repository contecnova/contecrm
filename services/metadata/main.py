"""Punto de entrada del servicio de metadatos."""

from __future__ import annotations

from crmcore.service import crear_servicio

from services.metadata.api import ROUTERS

app = crear_servicio(
    nombre="metadata",
    descripcion=(
        "Objetos y campos definidos por el tenant, validaciones declarativas "
        "consultables antes de enviar, layouts para frontends headless, listas "
        "maestras y clasificación de sensibilidad."
    ),
    routers=ROUTERS,
)
