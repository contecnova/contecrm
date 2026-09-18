"""Bus de eventos: transporte, garantía de entrega y deduplicación.

Tres piezas que se reparten el trabajo:

  * `base`/`nats_js`/`redis_streams`/`memoria` — el **transporte**.
  * `outbox` — la **garantía** de que un hecho commiteado acabe publicado.
  * `inbox` — la **deduplicación**, que convierte at-least-once en efecto
    exactly-once desde el punto de vista del negocio.

Ninguna de las tres basta sola, y ese es el motivo de que estén separadas.
"""

from crmcore.bus.base import Bus, Manejador, Suscripcion, crear_bus

__all__ = ["Bus", "Manejador", "Suscripcion", "crear_bus"]
