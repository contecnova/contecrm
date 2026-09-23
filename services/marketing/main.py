"""Punto de entrada del servicio de marketing."""

from __future__ import annotations

from crmcore.service import crear_servicio

from services.marketing import (
    ajustes,  # noqa: F401  (registra las claves de ajuste)
    eventos,  # noqa: F401  (registra los tipos de evento)
)
from services.marketing.api import ROUTERS
from services.marketing.api_canales import ROUTERS_CANALES
from services.marketing.api_canales_externos import ROUTERS_CANALES_EXTERNOS
from services.marketing.api_consentimiento import ROUTERS_CONSENTIMIENTO
from services.marketing.api_fondos import ROUTERS_FONDOS
from services.marketing.api_momento import ROUTERS_MOMENTO
from services.marketing.api_recorridos import ROUTERS_RECORRIDOS
from services.marketing.proyeccion import consumir

app = crear_servicio(
    nombre="marketing",
    descripcion=(
        "Segmentos con condiciones anidadas y operadores temporales, dinámicos o "
        "congelados, con supresiones que se aplican siempre por encima; y "
        "puntuación de leads en dos ejes —encaje e interés— con decaimiento y "
        "umbrales que exigen los dos. Encima, los recorridos: el lienzo es la "
        "definición, las salidas se comprueban antes de cada paso y la "
        "supresión manda sobre lo que diga el recorrido."
    ),
    routers=[
        *ROUTERS,
        *ROUTERS_RECORRIDOS,
        *ROUTERS_CANALES,
        *ROUTERS_FONDOS,
        *ROUTERS_CONSENTIMIENTO,
        *ROUTERS_MOMENTO,
        *ROUTERS_CANALES_EXTERNOS,
    ],
    # El perfil de marketing se alimenta por evento: este servicio no puede leer
    # el esquema de `party` ni el de `sales`, y calcular un segmento no puede
    # depender de que estén en pie. El patrón es ancho porque el propio
    # consumidor filtra por tipo conocido.
    consumidores=[("*", consumir, "marketing-perfiles")],
)
