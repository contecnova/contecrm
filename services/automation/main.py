"""Punto de entrada del servicio de automatizaciones."""

from __future__ import annotations

from crmcore.service import crear_servicio
from services.automation.api import ROUTERS

app = crear_servicio(
    nombre="automation",
    descripcion=(
        "Automatizaciones declarativas «cuando X, si Y, entonces Z», con orden "
        "determinista entre reglas, corte de cascada, prueba en seco y traza de "
        "por qué una regla no se disparó."
    ),
    routers=ROUTERS,
)
