"""Recibir eventos sin exponer un endpoint (CRM-00.02.02.10).

Los webhooks exigen que quien escucha tenga una dirección pública y estable. Eso
deja fuera a media integración real: un navegador, una aplicación móvil, un
servicio dentro de una red cerrada, un cuaderno de análisis. Todos pueden
**llamar** al CRM y ninguno puede recibir una llamada.

Se resuelve con **SSE** (`text/event-stream`) y no con WebSocket, y la razón es
práctica: el flujo va en un solo sentido —el CRM cuenta lo que pasa— y SSE es
HTTP normal, así que atraviesa proxies corporativos, se reconecta solo y se
depura con `curl`. Un WebSocket para empujar en un sentido es un protocolo más
que mantener y una cosa más que un proxy puede romper.

Dos decisiones que evitan los fallos de siempre:

**Se reanuda desde donde se quedó** (`Last-Event-ID`). Sin eso, cada corte de red
—que en un móvil es cada túnel— pierde los eventos de ese hueco, y el cliente no
tiene forma de saber cuántos ni cuáles.

**Hay latido.** Un flujo sin datos durante minutos lo cierra cualquier
intermediario por inactividad, y el cliente cree que el servidor se ha caído
cuando lo que pasa es que no pasa nada.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any, AsyncIterator
from uuid import UUID

from crmcore.logging import get_logger

logger = get_logger(__name__)


@dataclass
class _Cola:
    """Lo reciente de un tenant, para poder reanudar tras un corte.

    En memoria y acotada a propósito: esto **no** es la garantía de entrega —eso
    es el bus y su tabla de salida— sino un puente para que una reconexión corta
    no pierda nada. Quien necesite garantía usa un webhook o consume del bus; el
    tope se dice para que nadie confunda las dos cosas.
    """

    eventos: deque[tuple[int, dict[str, Any]]] = field(default_factory=lambda: deque(maxlen=500))
    siguiente_id: int = 1
    oyentes: int = 0


_colas: dict[UUID, _Cola] = {}
_aviso = asyncio.Event()


def publicar(tenant_id: UUID, evento: dict[str, Any]) -> int:
    """Deja un evento disponible para quien esté escuchando. Devuelve su id."""
    cola = _colas.setdefault(tenant_id, _Cola())
    identificador = cola.siguiente_id
    cola.siguiente_id += 1
    cola.eventos.append((identificador, evento))
    _aviso.set()
    _aviso.clear()
    return identificador


def pendientes(tenant_id: UUID, desde: int) -> list[tuple[int, dict[str, Any]]]:
    """Lo ocurrido después de un identificador dado."""
    cola = _colas.get(tenant_id)
    if cola is None:
        return []
    return [(i, e) for i, e in cola.eventos if i > desde]


def hueco(tenant_id: UUID, desde: int) -> bool:
    """Si lo que el cliente pide ya se ha caído de la cola.

    Decirlo importa más que rellenarlo: un cliente que cree haberlo recibido
    todo y no lo ha recibido toma decisiones sobre datos incompletos. Sabiendo
    que hay hueco, puede recargar el estado entero, que es lo correcto.
    """
    cola = _colas.get(tenant_id)
    if cola is None or not cola.eventos:
        return False
    return desde > 0 and desde < cola.eventos[0][0] - 1


async def flujo(tenant_id: UUID, *, desde: int = 0, latido_s: float = 20.0) -> AsyncIterator[str]:
    """Un flujo SSE para este tenant, reanudable.

    El primer mensaje dice si hay hueco. Ir directamente a lo nuevo sin avisar
    sería la peor opción: el cliente se quedaría con un estado incompleto sin
    saberlo.
    """
    cola = _colas.setdefault(tenant_id, _Cola())
    cola.oyentes += 1
    ultimo = desde
    try:
        if hueco(tenant_id, desde):
            yield _sse(
                0,
                "hueco",
                {
                    "desde_pedido": desde,
                    "disponible_desde": cola.eventos[0][0],
                    "que_hacer": "Recarga el estado: se han perdido eventos de ese tramo",
                },
            )

        while True:
            for identificador, evento in pendientes(tenant_id, ultimo):
                ultimo = identificador
                yield _sse(identificador, str(evento.get("tipo", "evento")), evento)

            try:
                # Se espera al aviso o al latido, lo que llegue antes. Sin el
                # latido, un intermediario cierra el flujo por inactividad y el
                # cliente cree que el servidor se ha caído.
                await asyncio.wait_for(_aviso.wait(), timeout=latido_s)
            except asyncio.TimeoutError:
                yield ": latido\n\n"
    finally:
        cola.oyentes = max(0, cola.oyentes - 1)
        logger.info("empuje.desconectado", tenant=str(tenant_id), oyentes=cola.oyentes)


def _sse(identificador: int, tipo: str, datos: dict[str, Any]) -> str:
    """Un mensaje en el formato de `text/event-stream`.

    El `id` va siempre, incluso en el aviso de hueco: es lo que el navegador
    guarda y devuelve en `Last-Event-ID` al reconectar solo, sin que el cliente
    tenga que programar nada.
    """
    cuerpo = json.dumps(datos, ensure_ascii=False)
    return f"id: {identificador}\nevent: {tipo}\ndata: {cuerpo}\n\n"


def estado() -> dict[str, Any]:
    return {
        str(tenant): {"oyentes": cola.oyentes, "en_cola": len(cola.eventos)}
        for tenant, cola in _colas.items()
    }


def reiniciar() -> None:
    _colas.clear()
