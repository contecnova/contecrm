"""Tablas de auditoría: la traza y el historial de campo."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from crmcore.db.base import Base
from crmcore.ids import nuevo_id


class ApunteAuditoria(Base):
    """Un hecho auditado, encadenado con el anterior por hash.

    La cadena es lo que convierte un log en una prueba: cada apunte incluye el
    hash del anterior, así que alterar o borrar uno rompe todos los siguientes y
    se puede demostrar. Sin cadena, un log de auditoría solo prueba lo que diga
    quien tenga permiso de escritura en la tabla.

    Hay **una cadena por tenant**, no una global. Si fuera global, los apuntes de
    todos los tenants se entrelazarían y verificar la cadena de uno exigiría leer
    los de los demás — que es justo lo que el aislamiento prohíbe.
    """

    __tablename__ = "auditoria"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    # Posición en la cadena del tenant. Un hueco en la secuencia es, por sí solo,
    # señal de manipulación: no hace falta recalcular hashes para detectarlo.
    secuencia: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)

    accion: Mapped[str] = mapped_column(String(80), nullable=False)
    objeto: Mapped[str] = mapped_column(String(80), nullable=False)
    objeto_id: Mapped[str | None] = mapped_column(String(80), nullable=True)

    actor_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    actor_tipo: Mapped[str] = mapped_column(String(32), nullable=False, default="usuario")
    # Quién suplantaba, si había suplantación. Sin este campo, una acción hecha
    # por soporte en nombre de un usuario queda registrada como del usuario, y
    # eso hace inútil la auditoría justo en el caso en que más se necesita.
    actor_real_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    origen: Mapped[str] = mapped_column(String(32), nullable=False, default="api")

    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    datos: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Justificación obligatoria en las acciones que la exigen: acceso de soporte
    # a datos de un tenant, exportación masiva, restauración (CRM-00.01.02.06).
    motivo: Mapped[str | None] = mapped_column(Text, nullable=True)

    hash_previo: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_auditoria_tenant_secuencia", "tenant_id", "secuencia", unique=True),
        Index("ix_auditoria_objeto", "tenant_id", "objeto", "objeto_id"),
        Index("ix_auditoria_fecha", "tenant_id", "created_at"),
    )


class CambioCampo(Base):
    """Historial de campo: valor anterior, nuevo, autor y origen.

    Separado de la traza de auditoría a propósito. La traza responde «quién hizo
    qué»; esto responde «cómo llegó este campo a valer esto», que es la pregunta
    que de verdad se hace en un CRM cuando un importe no cuadra. Mezclarlos
    obligaría a que la traza tuviera una fila por campo modificado, y una
    importación de mil registros generaría cincuenta mil apuntes de auditoría
    que enterrarían lo que sí hay que vigilar.
    """

    __tablename__ = "historial_campos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    objeto: Mapped[str] = mapped_column(String(80), nullable=False)
    objeto_id: Mapped[str] = mapped_column(String(80), nullable=False)
    campo: Mapped[str] = mapped_column(String(120), nullable=False)
    # Texto y no JSONB: aquí se guarda la representación, no el valor tipado. El
    # historial tiene que sobrevivir a que el campo cambie de tipo, y un valor
    # guardado como número no se puede releer si el campo pasó a ser texto.
    valor_anterior: Mapped[str | None] = mapped_column(Text, nullable=True)
    valor_nuevo: Mapped[str | None] = mapped_column(Text, nullable=True)

    actor_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    origen: Mapped[str] = mapped_column(String(32), nullable=False, default="api")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_historial_objeto", "tenant_id", "objeto", "objeto_id", "created_at"),
    )
