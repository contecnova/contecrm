"""Punto de entrada del servicio de eventos salientes."""

from __future__ import annotations

import asyncio
from typing import Any

from crmcore.service import crear_servicio

from services.eventing import estado_componentes  # noqa: F401 — registra su componente de estado
from services.eventing.api import ROUTERS
from services.eventing.consumidores import RelevoDeReintentos, consumir_evento

_relevo = RelevoDeReintentos()
_tarea: Any = None


async def _arrancar() -> None:
    global _tarea
    _tarea = asyncio.create_task(_relevo.correr(), name="webhooks-reintentos")


async def _parar() -> None:
    _relevo.parar()
    if _tarea is not None:
        _tarea.cancel()


app = crear_servicio(
    nombre="eventing",
    descripcion=(
        "Webhooks con firma HMAC y anti-replay, reintentos con backoff, "
        "desactivación automática de endpoints muertos, catálogo AsyncAPI "
        "generado del código, archivo de eventos y replay por ventana de tiempo."
    ),
    routers=ROUTERS,
    # SIN ESTO EL SERVICIO NO ENTREGABA NADA. El reparto estaba entero en
    # `entrega.py` —firma, reintentos, desactivación del endpoint muerto— y no
    # lo llamaba nadie: el servicio declaraba sus rutas y ningún consumidor, así
    # que un integrador creaba su suscripción y no le llegaba un solo evento.
    #
    # El patrón es ancho a propósito: el filtro fino es por tipo y por
    # condiciones, y lo hace `suscripciones_interesadas` con lo que cada tenant
    # tenga suscrito. Mantener aquí una lista de tipos sería otra cosa más que
    # se desincroniza sola.
    consumidores=[("*", consumir_evento, "eventing-webhooks")],
    # Y el backoff necesita quien lo recoja: sin este relevo, `proximo_intento_at`
    # es una fecha guardada en una fila que nadie vuelve a mirar.
    al_arrancar=_arrancar,
    al_parar=_parar,
)
