"""Tablas del bus: salida (outbox), entrada (inbox) y cola de fallidos (DLQ).

Las tres viven en el esquema de CADA servicio, no en uno común. Es deliberado:
si la tabla de salida fuera compartida, escribir un evento obligaría a una
transacción distribuida —justo lo que el patrón outbox evita— y el servicio
perdería la propiedad exclusiva de sus datos (CRM-00.03.01.02).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from crmcore.db.base import Base
from crmcore.ids import nuevo_id


class EventoSaliente(Base):
    """Evento escrito en la misma transacción que el cambio que lo provoca.

    El relevo lo publica después y lo marca. Mientras `publicado_at` sea NULL, el
    evento sigue pendiente: si el proceso muere entre el commit y la
    publicación, el siguiente relevo lo encuentra y lo publica. Eso es toda la
    garantía, y por eso esta tabla no es un detalle de implementación sino la
    pieza que hace que el sistema no pierda hechos.
    """

    __tablename__ = "eventos_salientes"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    # Nullable solo aquí: hay eventos de plataforma sin tenant (alta de tenant).
    # Es la única tabla del sistema donde eso es correcto, y por eso el guard la
    # trata aparte.
    tenant_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    tipo: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    subject_tipo: Mapped[str] = mapped_column(String(60), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(80), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False)
    # El sobre completo, ya serializado. Se guarda entero y no por campos para
    # que publicar sea copiar: si el relevo tuviera que reconstruir el sobre,
    # un cambio en el formato rompería los eventos que quedaron pendientes
    # durante el despliegue.
    sobre: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    publicado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    intentos: Mapped[int] = mapped_column(nullable=False, default=0)
    # Cuándo se puede volver a intentar. Es lo que implementa el backoff sin
    # necesidad de un planificador aparte: el relevo solo mira lo vencido.
    proximo_intento_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ultimo_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Índice parcial sobre lo PENDIENTE. Es lo que hace que el relevo siga
        # siendo rápido con millones de eventos ya publicados en la tabla: el
        # índice solo contiene las filas que quedan por publicar.
        Index(
            "ix_eventos_salientes_pendientes",
            "proximo_intento_at",
            postgresql_where=text("publicado_at IS NULL"),
        ),
    )


class EventoEntrante(Base):
    """Claves de eventos ya procesados (inbox).

    Convierte la entrega at-least-once del bus en efecto exactly-once visto
    desde el negocio: antes de procesar se intenta insertar la clave, y si ya
    estaba, el evento es un duplicado y se descarta sin tocar nada.

    La clave primaria es `(dedup_key, consumidor)` y no solo `dedup_key`: dos
    servicios distintos consumen el MISMO evento legítimamente, y con una clave
    única global el segundo lo vería como duplicado y no lo procesaría nunca.
    """

    __tablename__ = "eventos_entrantes"

    dedup_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    consumidor: Mapped[str] = mapped_column(String(120), primary_key=True)
    tenant_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    tipo: Mapped[str] = mapped_column(String(120), nullable=False)
    procesado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Barrido de lo caducado por fecha: sin este índice la purga hace un
        # recorrido completo de una tabla que crece con cada evento.
        Index("ix_eventos_entrantes_procesado", "procesado_at"),
    )


class EventoFallido(Base):
    """Cola de fallidos (CRM-00.02.02.03, CRM-00.03.04.07).

    Aquí acaba lo que agotó los reintentos. No se borra ni se pierde: se guarda
    con el último error para que un administrador pueda corregir la causa y
    reenviarlo desde la consola.

    Que exista esta tabla es lo que permite que el relevo se rinda sin drama: un
    evento que no se puede publicar deja de consumir intentos, pero sigue
    existiendo y se puede recuperar.
    """

    __tablename__ = "eventos_fallidos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    origen: Mapped[str] = mapped_column(String(40), nullable=False)  # outbox | consumo | webhook
    tipo: Mapped[str] = mapped_column(String(120), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False)
    sobre: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    intentos: Mapped[int] = mapped_column(nullable=False, default=0)
    ultimo_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Quién y cuándo lo reenvió, si se reenvió. Sin esto no se puede responder a
    # «¿esto se llegó a reprocesar?», que es la primera pregunta del incidente.
    reenviado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reenviado_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
