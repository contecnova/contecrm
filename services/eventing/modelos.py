"""Modelo de datos de los webhooks."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.ids import nuevo_id
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column


class Suscripcion(Base, TimestampMixin):
    """Un endpoint del tenant suscrito a ciertos eventos."""

    __tablename__ = "suscripciones_webhook"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)

    # Tipos de evento, admitiendo comodín por sufijo: `opportunity.*`.
    eventos: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    # Filtro adicional sobre el contenido (CRM-00.02.02.01): entregar solo las
    # oportunidades de más de X. Sin él, un integrador recibe todo y filtra en su
    # lado, lo que multiplica el tráfico por nada.
    condiciones: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    # Secreto de firma HMAC. Se guarda cifrado; se enseña una vez al crear.
    secreto: Mapped[str] = mapped_column(String(128), nullable=False)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Cabeceras extra que pide el receptor (autenticación propia, enrutado).
    cabeceras: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    # Salud de la suscripción. Un endpoint que lleva mil fallos seguidos está
    # muerto, y seguir intentándolo cada minuto es tráfico y ruido: pasado el
    # tope se desactiva sola y se avisa.
    fallos_consecutivos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    desactivada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ultimo_exito_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_suscripciones_activas", "tenant_id", "activa"),)


class Entrega(Base):
    """Un intento de entrega, con su resultado.

    Se guarda cada intento y no solo el último: un endpoint que responde 200 al
    tercer intento pero tarda treinta segundos es un problema distinto de uno
    que responde a la primera, y sin el historial los dos parecen iguales.
    """

    __tablename__ = "entregas_webhook"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    suscripcion_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("suscripciones_webhook.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evento_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    tipo: Mapped[str] = mapped_column(String(120), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False)

    intento: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # entregado | fallido | pendiente | descartado
    resultado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    codigo_http: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Respuesta del receptor, recortada. Es lo que permite depurar con él sin
    # pedirle sus logs: «nos devuelves un 422 diciendo esto».
    respuesta: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duracion_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    proximo_intento_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_entregas_pendientes", "resultado", "proximo_intento_at"),
        Index("ix_entregas_evento", "tenant_id", "evento_id"),
    )


class EventoArchivado(Base):
    """Copia de los eventos publicados, para poder reproducirlos.

    Es lo que hace posible el replay (CRM-00.02.02.09). El bus retiene treinta
    días; esto retiene lo que diga la política del tenant, y sobre todo permite
    responder a «mándame otra vez todo lo del martes» sin depender de la
    retención del broker.
    """

    __tablename__ = "eventos_archivados"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    tipo: Mapped[str] = mapped_column(String(120), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False)
    sobre: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_archivados_busqueda", "tenant_id", "tipo", "occurred_at"),)


# Tabla común: la clave propia del tenant (BYOK, CRM-00.01.04.09) se replica
# al esquema de cada servicio, porque cada uno cifra y descifra los campos de sus
# propias tablas dentro de sus transacciones.
from crmcore.security.byok import ClaveTenant  # noqa: E402,F401
