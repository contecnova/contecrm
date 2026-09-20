"""El registro de lo que se intentó entregar y cómo acabó (CRM-06.02.01.02).

«No me llegó el aviso» es la incidencia más frecuente de un CRM y la más difícil
de contestar. Sin este registro se acaba mirando el log del servidor de correo
de otra empresa, o diciendo «nosotros lo mandamos», que no es una respuesta.

Con él se contesta con hechos: se intentó a las 09:12, el servidor devolvió
«550 mailbox unavailable», no se reintentó porque ese código es definitivo, y la
dirección de esa persona es la que es.

La tabla vive en el esquema del servicio que reparte —`identity`, que es quien
conoce a las personas y sus direcciones— y no en uno común, por lo de siempre:
ningún servicio lee el esquema de otro.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Index, Integer, String, Text, func, select
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.db.base import Base
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger

logger = get_logger(__name__)

ESTADOS = ("pendiente", "entregada", "fallida", "descartada")


class EntregaNotificacion(Base):
    """Un intento de sacar un aviso por un canal.

    Una fila **por canal y por notificación**, no una por notificación: un aviso
    que va por correo y por SMS puede entregarse por uno y fallar por el otro, y
    una sola fila obligaría a elegir cuál de las dos verdades se guarda.
    """

    __tablename__ = "entregas_notificacion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    notificacion_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    canal: Mapped[str] = mapped_column(String(20), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")

    # La dirección a la que se intentó, tal como estaba en ese momento. Se
    # guarda aunque esté en la ficha del usuario: la ficha cambia, y la pregunta
    # que se hace después es «¿a qué dirección lo mandasteis?», no «¿cuál tiene
    # ahora?».
    direccion: Mapped[str] = mapped_column(String(320), nullable=False, default="")

    intentos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ultimo_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    referencia: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    proximo_intento_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    entregada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Los nombres llevan `notif` porque `entregas_webhook` ya usa
        # `ix_entregas_pendientes`. En producción viven en esquemas distintos y
        # no chocarían, pero en un despliegue pequeño —varios dominios en un
        # esquema— y en la suite sí: el índice del segundo modelo no se crea y
        # la consulta que lo necesita hace un `seq scan` sobre toda la tabla.
        Index("ix_entregas_notif_pendientes", "estado", "proximo_intento_at"),
        Index("ix_entregas_notif_aviso", "tenant_id", "notificacion_id"),
    )


def registrar_intento(
    db: Session,
    *,
    tenant_id: UUID,
    notificacion_id: UUID,
    usuario_id: UUID,
    canal: str,
    direccion: str,
) -> EntregaNotificacion:
    """Abre —o recupera— la ficha de entrega de este aviso por este canal."""
    fila = (
        db.execute(
            select(EntregaNotificacion).where(
                EntregaNotificacion.notificacion_id == notificacion_id,
                EntregaNotificacion.canal == canal,
            )
        )
        .scalars()
        .first()
    )
    if fila is None:
        fila = EntregaNotificacion(
            tenant_id=tenant_id,
            notificacion_id=notificacion_id,
            usuario_id=usuario_id,
            canal=canal,
            direccion=direccion[:320],
        )
        db.add(fila)
        db.flush()
    return fila


def anotar_resultado(db: Session, fila: EntregaNotificacion, resultado: Any) -> None:
    """Guarda cómo fue el intento y decide si habrá otro.

    La espera crece con el cuadrado del intento (1 min, 4, 9, 16, 25): lineal se
    queda corta con un proveedor caído una hora, y exponencial se pasa de largo
    —al quinto intento serían dieciséis horas— para un aviso que deja de tener
    valor pasada la tarde.
    """
    from crmcore.config import get_settings

    s = get_settings()
    fila.intentos += 1
    fila.referencia = resultado.referencia or fila.referencia

    if resultado.entregado:
        fila.estado = "entregada"
        fila.entregada_at = datetime.now(timezone.utc)
        fila.proximo_intento_at = None
        fila.ultimo_error = ""
        return

    fila.ultimo_error = str(resultado.detalle)[:2000]
    if not resultado.reintentar:
        # Un destinatario sin dirección o un correo rechazado como inexistente
        # no mejoran reintentando. Se descarta y se dice, en vez de dejarlo
        # girando en la cola cada cinco minutos para siempre.
        fila.estado = "descartada"
        fila.proximo_intento_at = None
        logger.info(
            "notificacion.descartada",
            canal=fila.canal,
            motivo=fila.ultimo_error[:160],
        )
        return

    if fila.intentos >= s.notificacion_max_intentos:
        fila.estado = "fallida"
        fila.proximo_intento_at = None
        logger.warning(
            "notificacion.fallida",
            canal=fila.canal,
            intentos=fila.intentos,
            error=fila.ultimo_error[:160],
        )
        return

    fila.estado = "pendiente"
    fila.proximo_intento_at = datetime.now(timezone.utc) + timedelta(
        seconds=s.notificacion_espera_base_s * (fila.intentos**2)
    )


def reintentables(db: Session, *, limite: int = 100) -> list[EntregaNotificacion]:
    """Entregas que tocan reintentar ahora.

    `SKIP LOCKED` para que varias réplicas repartan a la vez sin mandar dos
    veces el mismo aviso ni bloquearse entre ellas.
    """
    ahora = datetime.now(timezone.utc)
    return list(
        db.execute(
            select(EntregaNotificacion)
            .where(
                EntregaNotificacion.estado == "pendiente",
                EntregaNotificacion.intentos > 0,
                EntregaNotificacion.proximo_intento_at.is_not(None),
                EntregaNotificacion.proximo_intento_at <= ahora,
            )
            .order_by(EntregaNotificacion.proximo_intento_at)
            .limit(limite)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )


def historial(db: Session, notificacion_id: UUID) -> list[dict[str, Any]]:
    """Qué se intentó con este aviso. Es la respuesta a «no me llegó»."""
    filas = (
        db.execute(
            select(EntregaNotificacion)
            .where(EntregaNotificacion.notificacion_id == notificacion_id)
            .order_by(EntregaNotificacion.canal)
        )
        .scalars()
        .all()
    )
    return [
        {
            "canal": f.canal,
            "estado": f.estado,
            "direccion": f.direccion,
            "intentos": f.intentos,
            "ultimo_error": f.ultimo_error,
            "referencia": f.referencia,
            "entregada_at": f.entregada_at.isoformat() if f.entregada_at else None,
            "proximo_intento_at": (
                f.proximo_intento_at.isoformat() if f.proximo_intento_at else None
            ),
        }
        for f in filas
    ]
