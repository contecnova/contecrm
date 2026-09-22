"""Punto de entrada del servicio de marketing."""

from __future__ import annotations

from crmcore.service import crear_servicio

from services.marketing.api import ROUTERS
from services.marketing.proyeccion import consumir

app = crear_servicio(
    nombre="marketing",
    descripcion=(
        "Segmentos con condiciones anidadas y operadores temporales, dinámicos o "
        "congelados, con supresiones que se aplican siempre por encima; y "
        "puntuación de leads en dos ejes —encaje e interés— con decaimiento y "
        "umbrales que exigen los dos."
    ),
    routers=ROUTERS,
    # El perfil de marketing se alimenta por evento: este servicio no puede leer
    # el esquema de `party` ni el de `sales`, y calcular un segmento no puede
    # depender de que estén en pie. El patrón es ancho porque el propio
    # consumidor filtra por tipo conocido.
    consumidores=[("*", consumir, "marketing-perfiles")],
)
