"""Estado propio del servicio de explotación."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.ids import nuevo_id
from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column


class OrganizacionExterna(Base, TimestampMixin):
    """A qué organización de contecintelligence corresponde este tenant.

    Se guarda aquí y no se deduce del identificador del tenant porque el mapeo
    es **suyo**: contecintelligence solo acepta nombrar organizaciones que tenga
    mapeadas, y ese es justo el control que impide que un token diga pertenecer
    a un cliente cualquiera. Reconstruirlo cada vez a partir del identificador
    convertiría el control en una convención.
    """

    __tablename__ = "organizaciones_externas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    organizacion: Mapped[str] = mapped_column(String(120), nullable=False)
    # pendiente | activa | error
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    ultimo_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    verificada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_organizacion_tenant"),
        Index("ix_organizaciones_estado", "tenant_id", "estado"),
    )


class ConsultaAnalitica(Base):
    """Qué se preguntó, quién y qué se devolvió (CRM-05.01.04.07).

    La explotación es la vía por la que más dato sale de un CRM de una sola vez.
    Sin este registro, «¿quién sacó la lista de clientes antes de irse?» no tiene
    respuesta — y esa es exactamente la pregunta que se hace después.

    Se guarda la pregunta y el **recuento** de lo devuelto, no las filas: copiar
    aquí lo que ya está en las tablas duplicaría el dato personal y multiplicaría
    la superficie que hay que proteger.
    """

    __tablename__ = "consultas_analiticas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    usuario_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    pregunta: Mapped[str] = mapped_column(Text, nullable=False)
    fuente: Mapped[str | None] = mapped_column(String(120), nullable=True)
    filas_devueltas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duracion_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    contexto: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_consultas_tenant", "tenant_id", "created_at"),)


# ── Tablas compartidas que viven en ESTE esquema ──────────────────────────
from crmcore.authz.politicas import PoliticaAbac, VersionPoliticaAbac  # noqa: E402
from crmcore.datos.retencion import BloqueoLegal, PoliticaRetencion  # noqa: E402
from crmcore.security.byok import ClaveTenant  # noqa: E402

__all__ = [
    "PoliticaAbac",
    "VersionPoliticaAbac",
    "ClaveTenant",
    "BloqueoLegal",
    "ConsultaAnalitica",
    "OrganizacionExterna",
    "PoliticaRetencion",
]
