"""Deduplicación en el consumo.

La entrega del bus es at-least-once: el mismo hecho puede llegar dos veces. Si
el consumidor no deduplica, un reintento del productor crea la cuenta dos veces,
suma el importe dos veces o manda el correo dos veces — y esos tres fallos son
visibles para el cliente final.

El mecanismo es el más simple que funciona: antes de procesar se intenta
insertar `(dedup_key, consumidor)`. Si la inserción choca con la clave primaria,
ese evento ya se procesó y se descarta.

Va **dentro de la misma transacción** que el efecto del evento. Si fuera antes,
un fallo posterior dejaría el evento marcado como procesado sin haberlo
procesado, y el reintento lo descartaría: el hecho se perdería para siempre.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from crmcore.bus.modelos import EventoEntrante
from crmcore.events.envelope import Evento
from crmcore.logging import get_logger

logger = get_logger(__name__)


def marcar_si_nuevo(db: Session, evento: Evento, *, consumidor: str) -> bool:
    """`True` si el evento es nuevo para este consumidor; `False` si es repetido.

    `ON CONFLICT DO NOTHING` en vez de comprobar-y-luego-insertar: entre la
    comprobación y la inserción cabe otra réplica haciendo lo mismo, y las dos
    concluirían que es nuevo. Aquí lo decide la clave primaria, que es atómica.
    """
    res = db.execute(
        pg_insert(EventoEntrante)
        .values(
            dedup_key=evento.dedup_key,
            consumidor=consumidor,
            tenant_id=evento.tenant_id,
            tipo=evento.type,
        )
        .on_conflict_do_nothing(index_elements=["dedup_key", "consumidor"])
    )
    nuevo = bool(res.rowcount)
    if not nuevo:
        logger.debug(
            "inbox.duplicado_descartado",
            tipo=evento.type,
            consumidor=consumidor,
        )
    return nuevo


def purgar(db: Session, *, dias: int) -> int:
    """Olvida las claves más antiguas que N días.

    El plazo tiene que cubrir de sobra la ventana de reintentos del productor:
    si se olvida una clave antes de que el productor deje de reintentarla, el
    reintento tardío pasaría como nuevo y se procesaría dos veces.
    """
    limite = datetime.now(timezone.utc) - timedelta(days=dias)
    res = db.execute(delete(EventoEntrante).where(EventoEntrante.procesado_at < limite))
    return int(res.rowcount or 0)
