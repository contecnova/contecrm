"""Tabla de salida y su relevo.

`encolar()` escribe el evento dentro de la transacción del negocio.
`Relevo` lo publica después, reintentando con backoff, y manda a la cola de
fallidos lo que no hay manera de publicar.

Ver `crmcore.db.uow` para el uso normal: casi nunca hay que llamar a `encolar`
directamente, porque la unidad de trabajo ya lo hace al cerrar.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from crmcore.bus.modelos import EventoFallido, EventoSaliente
from crmcore.events.envelope import crear_evento
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Se despierta al relevo tras un commit para no esperar al siguiente sondeo.
# Es un Event de asyncio y no una llamada directa porque quien hace commit puede
# estar en un hilo síncrono, y ahí no se puede await nada.
_despertador: asyncio.Event | None = None


def encolar(
    db: Session,
    *,
    tenant_id: UUID | None,
    tipo: str,
    subject_tipo: str,
    subject_id: Any,
    data: dict[str, Any] | None = None,
    dedup_key: str | None = None,
    version: int = 1,
) -> EventoSaliente:
    """Escribe el evento en la tabla de salida. NO publica.

    Se llama dentro de la transacción del cambio; publicarlo es cosa del relevo.
    """
    from crmcore.ids import nuevo_id

    evento = crear_evento(
        tipo,
        tenant_id=tenant_id or nuevo_id(),
        subject=(subject_tipo, subject_id),
        data=data or {},
        version=version,
        dedup_key=dedup_key,
    )
    fila = EventoSaliente(
        tenant_id=tenant_id,
        tipo=tipo,
        version=version,
        subject_tipo=subject_tipo,
        subject_id=str(subject_id),
        dedup_key=evento.dedup_key,
        sobre=evento.a_dict(),
    )
    db.add(fila)
    return fila


def despertar_relevo() -> None:
    """Avisa al relevo de que hay trabajo. Seguro de llamar siempre."""
    if _despertador is not None:
        try:
            _despertador.set()
        except RuntimeError:
            # El bucle de eventos puede no estar corriendo (proceso síncrono,
            # apagado en curso). El relevo lo cogerá en su sondeo; perder el
            # aviso solo cuesta latencia, nunca eventos.
            pass


class Relevo:
    """Publica lo pendiente de la tabla de salida.

    Corre como tarea de fondo en cada servicio que produce eventos. Varias
    réplicas pueden correrlo a la vez: el `FOR UPDATE SKIP LOCKED` hace que cada
    una se lleve un lote distinto sin bloquearse entre ellas.
    """

    def __init__(self, bus: Any, *, sesion_factory: Any = None) -> None:
        self._bus = bus
        self._sesion_factory = sesion_factory
        self._parar = asyncio.Event()

    async def correr(self) -> None:
        """Bucle principal. Termina cuando se llama a `parar()`."""
        global _despertador
        _despertador = asyncio.Event()
        from crmcore.config import get_settings

        s = get_settings()
        logger.info("outbox.relevo_arranca", intervalo_s=s.outbox_intervalo_s)

        while not self._parar.is_set():
            try:
                publicados = await self._una_vuelta()
            except Exception as exc:  # noqa: BLE001 — el relevo no puede morirse
                logger.warning("outbox.vuelta_fallida", error=str(exc)[:200])
                publicados = 0

            if publicados > 0:
                # Con trabajo, sigue de seguido: un lote lleno casi siempre
                # significa que hay más esperando.
                continue
            try:
                await asyncio.wait_for(
                    _despertador.wait(), timeout=s.outbox_intervalo_s
                )
                _despertador.clear()
            except asyncio.TimeoutError:
                pass

    async def _una_vuelta(self) -> int:
        """Toma un lote, lo publica y lo marca. Devuelve cuántos publicó."""
        from crmcore.config import get_settings
        from crmcore.db.session import nueva_sesion

        s = get_settings()
        db = (self._sesion_factory or (lambda: nueva_sesion(sistema=True)))()
        publicados = 0
        try:
            ahora = datetime.now(timezone.utc)
            filas = (
                db.execute(
                    select(EventoSaliente)
                    .where(
                        EventoSaliente.publicado_at.is_(None),
                        EventoSaliente.proximo_intento_at <= ahora,
                    )
                    .order_by(EventoSaliente.created_at)
                    .limit(s.outbox_lote)
                    # Cada réplica se lleva filas distintas en vez de esperar a
                    # que la otra suelte: sin SKIP LOCKED, N réplicas dan el
                    # rendimiento de una.
                    .with_for_update(skip_locked=True)
                )
                .scalars()
                .all()
            )

            for fila in filas:
                if await self._publicar_una(db, fila, s):
                    publicados += 1
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        return publicados

    async def _publicar_una(self, db: Session, fila: EventoSaliente, s: Any) -> bool:
        from crmcore.events.envelope import Evento

        try:
            await self._bus.publicar(Evento.desde_dict(fila.sobre))
        except Exception as exc:  # noqa: BLE001 — se reintenta o se aparta
            fila.intentos += 1
            fila.ultimo_error = str(exc)[:1000]
            if fila.intentos >= s.outbox_max_intentos:
                # Agotado: a la cola de fallidos, y fuera de los pendientes para
                # que no siga consumiendo lotes eternamente. No se borra.
                db.add(
                    EventoFallido(
                        tenant_id=fila.tenant_id,
                        origen="outbox",
                        tipo=fila.tipo,
                        dedup_key=fila.dedup_key,
                        sobre=fila.sobre,
                        intentos=fila.intentos,
                        ultimo_error=fila.ultimo_error,
                    )
                )
                fila.publicado_at = datetime.now(timezone.utc)
                logger.error(
                    "outbox.a_fallidos",
                    tipo=fila.tipo,
                    intentos=fila.intentos,
                    error=fila.ultimo_error[:200] if fila.ultimo_error else "",
                )
            else:
                espera = s.outbox_backoff_base_s * (2 ** (fila.intentos - 1))
                fila.proximo_intento_at = datetime.now(timezone.utc) + timedelta(
                    seconds=min(espera, 3600)
                )
                logger.warning(
                    "outbox.reintento",
                    tipo=fila.tipo,
                    intento=fila.intentos,
                    espera_s=round(espera, 1),
                )
            return False

        fila.publicado_at = datetime.now(timezone.utc)
        return True

    def parar(self) -> None:
        self._parar.set()
        despertar_relevo()


def reenviar_fallido(db: Session, fallido_id: UUID, *, por: UUID | None = None) -> EventoSaliente:
    """Devuelve un evento de la cola de fallidos a la de salida.

    Lo vuelve a encolar en vez de publicarlo aquí mismo para que el reenvío pase
    por exactamente el mismo camino que el envío normal: si vuelve a fallar,
    reintenta y vuelve a fallidos igual, sin un segundo camino que mantener.
    """
    fallido = db.get(EventoFallido, fallido_id)
    if fallido is None:
        from crmcore.errors import NoEncontrado

        raise NoEncontrado(
            "No existe ese evento en la cola de fallidos",
            error_code="bus.fallido_no_encontrado",
        )
    nuevo = EventoSaliente(
        tenant_id=fallido.tenant_id,
        tipo=fallido.tipo,
        version=int(fallido.sobre.get("version", 1)),
        subject_tipo=str(fallido.sobre.get("subject", {}).get("tipo", "")),
        subject_id=str(fallido.sobre.get("subject", {}).get("id", "")),
        dedup_key=fallido.dedup_key,
        sobre=fallido.sobre,
    )
    db.add(nuevo)
    fallido.reenviado_at = datetime.now(timezone.utc)
    fallido.reenviado_por = por
    return nuevo


def purgar_publicados(db: Session, *, dias: int) -> int:
    """Borra los eventos ya publicados más antiguos que N días.

    La tabla de salida es un buzón, no un histórico: el histórico de qué pasó
    está en la auditoría. Sin purga, esta tabla crece para siempre y el índice
    parcial de pendientes deja de compensar.
    """
    limite = datetime.now(timezone.utc) - timedelta(days=dias)
    res = db.execute(
        delete(EventoSaliente).where(
            EventoSaliente.publicado_at.is_not(None),
            EventoSaliente.publicado_at < limite,
        )
    )
    return int(res.rowcount or 0)
