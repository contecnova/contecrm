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
from typing import Any

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from crmcore.bus.modelos import EventoEntrante
from crmcore.events.envelope import Evento, acotar_clave
from crmcore.logging import get_logger

logger = get_logger(__name__)


def _clave_del_tenant(evento: Evento) -> str:
    """La marca va **acotada al tenant**, y no solo a la clave del productor.

    La clave la pone el productor. Las derivadas ya llevan el tenant dentro, y
    las que se escriben a mano hoy llevan todas un identificador único —medido,
    una por una—, así que el choque entre dos clientes no es alcanzable ahora
    mismo. Pero es una trampa puesta: el primero que escriba `pedido:42` —y es
    la forma natural de escribirla— haría que el alta de un cliente descartara
    la del otro, en silencio y sin error, porque para el buzón serían el mismo
    hecho.

    Se acota aquí y no pidiéndole a cada productor que se acuerde: hay una
    docena de sitios que componen claves y pedirle a cada uno que recuerde algo
    es pedirle al próximo que se olvide.
    """
    return acotar_clave(f"{evento.tenant_id}|{evento.dedup_key}")


def marcar_si_nuevo(db: Session, evento: Evento, *, consumidor: str) -> bool:
    """`True` si el evento es nuevo para este consumidor; `False` si es repetido.

    `ON CONFLICT DO NOTHING` en vez de comprobar-y-luego-insertar: entre la
    comprobación y la inserción cabe otra réplica haciendo lo mismo, y las dos
    concluirían que es nuevo. Aquí lo decide la clave primaria, que es atómica.
    """
    res = db.execute(
        pg_insert(EventoEntrante)
        .values(
            dedup_key=_clave_del_tenant(evento),
            consumidor=consumidor,
            tenant_id=evento.tenant_id,
            tipo=evento.type,
        )
        .on_conflict_do_nothing(index_elements=["dedup_key", "consumidor"])
        # `RETURNING` y no `rowcount`. **Medido**: en este `INSERT ... ON
        # CONFLICT DO NOTHING`, `rowcount` vale -1 tanto si insertó como si no,
        # y `bool(-1)` es `True` — así que esta función decía «es nuevo»
        # siempre, también ante un duplicado. O sea: aunque alguien la hubiera
        # llamado, la deduplicación no habría deduplicado nada.
        #
        # Con `RETURNING`, la fila vuelve cuando se insertó y no vuelve cuando
        # el conflicto la saltó. Lo decide el servidor, que es quien lo sabe.
        .returning(EventoEntrante.dedup_key)
    )
    nuevo = res.first() is not None
    if not nuevo:
        logger.debug(
            "inbox.duplicado_descartado",
            tipo=evento.type,
            consumidor=consumidor,
        )
    return nuevo


def _evento_de(mensaje: Any) -> Evento | None:
    """El sobre, venga como venga.

    En producción el bus entrega un `Evento`; en las pruebas y en el bus en
    memoria a veces llega un diccionario. Lo que no se hace es **inventar una
    clave de deduplicación** cuando no la hay: deduplicar por una clave
    inventada es peor que no deduplicar, porque dos hechos distintos pueden
    compartirla y el segundo se descartaría en silencio.
    """
    if isinstance(mensaje, Evento):
        return mensaje
    if not isinstance(mensaje, dict):
        clave = getattr(mensaje, "dedup_key", "")
        return mensaje if clave else None
    return None


def idempotente(manejador: Any, *, consumidor: str) -> Any:
    """Envuelve un consumidor para que **no procese dos veces el mismo hecho**.

    Esto era lo que faltaba. La tabla estaba, el barrido que la purga estaba —y
    barría una tabla siempre vacía, que es por lo que nadie lo notó—, y
    `marcar_si_nuevo` no la llamaba nadie: **ningún consumidor deduplicaba**. La
    entrega del bus es at-least-once, así que el mismo hecho llega dos veces de
    serie, y sin esto un reintento del productor crea la cuenta dos veces, suma
    el importe dos veces o manda el correo dos veces. Los tres los ve el cliente
    final.

    La marca va **dentro de la misma transacción que el efecto**, compartiendo la
    unidad de trabajo con lo que haya dentro del manejador:

      * **antes y aparte** dejaría el evento marcado sin haberlo procesado si
        algo falla después, y el reintento lo descartaría: el hecho se pierde
        para siempre;
      * **después y aparte** no protege del caso real: el bus reclama lo que
        lleva mucho sin confirmar, así que la segunda entrega entra mientras la
        primera sigue dentro, y las dos hacen el efecto.

    Un mensaje sin sobre reconocible **se procesa igual**, sin deduplicar y
    diciéndolo: dejar de procesarlo convertiría un problema de formato en un
    hecho perdido, que es mucho peor.
    """

    async def _envuelto(mensaje: Any) -> None:
        from crmcore.db.uow import compartir, soltar, unidad_de_trabajo

        evento = _evento_de(mensaje)
        if evento is None:
            logger.warning("inbox.sin_sobre", consumidor=consumidor)
            await manejador(mensaje)
            return

        with unidad_de_trabajo(evento.tenant_id) as uow:
            if not marcar_si_nuevo(uow.db, evento, consumidor=consumidor):
                return
            testigo = compartir(uow)
            try:
                await manejador(mensaje)
            finally:
                soltar(testigo)

    _envuelto.__name__ = f"idempotente__{getattr(manejador, '__name__', 'manejador')}"
    # Se deja a la vista con qué se envolvió: un recorrido que compruebe que
    # todas las suscripciones pasan por aquí necesita poder mirarlo, y sin esto
    # lo único que se ve desde fuera es una función anónima.
    _envuelto.envuelve = manejador  # type: ignore[attr-defined]
    _envuelto.consumidor = consumidor  # type: ignore[attr-defined]
    return _envuelto


def purgar(db: Session, *, dias: int) -> int:
    """Olvida las claves más antiguas que N días.

    El plazo tiene que cubrir de sobra la ventana de reintentos del productor:
    si se olvida una clave antes de que el productor deje de reintentarla, el
    reintento tardío pasaría como nuevo y se procesaría dos veces.
    """
    limite = datetime.now(timezone.utc) - timedelta(days=dias)
    res = db.execute(delete(EventoEntrante).where(EventoEntrante.procesado_at < limite))
    return int(res.rowcount or 0)
