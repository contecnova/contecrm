"""Punto de entrada del servicio de automatizaciones."""

from __future__ import annotations

from crmcore.service import crear_servicio

from services.automation.api import ROUTERS
from services.automation.consumidores import consumir_evento

app = crear_servicio(
    nombre="automation",
    descripcion=(
        "Automatizaciones declarativas «cuando X, si Y, entonces Z», con orden "
        "determinista entre reglas, corte de cascada, prueba en seco y traza de "
        "por qué una regla no se disparó."
    ),
    routers=ROUTERS,
    # Las reglas se disparan con los eventos de dominio de los demás servicios.
    # El patrón es ancho y filtra la tabla `DISPARADORES`: mantener una lista de
    # suscripciones al día con esa tabla sería una segunda fuente de verdad.
    consumidores=[("*", consumir_evento, "automation-reglas")],
)
