"""Modelo de datos de las automatizaciones."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.ids import nuevo_id
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
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


class Automatizacion(Base, TimestampMixin, SoftDeleteMixin):
    """Una regla: disparador, condiciones y acciones.

    Cubre CRM-00.03.03.01 (constructor «cuando X, si Y, entonces Z»),
    CRM-00.03.03.02 (los siete tipos de disparador) y CRM-00.03.03.05
    (inmediata, diferida o programada).
    """

    __tablename__ = "automatizaciones"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # creacion | modificacion | eliminacion | evento | webhook | programada | manual
    disparador: Mapped[str] = mapped_column(String(30), nullable=False)
    # Objeto o tipo de evento al que se engancha.
    objetivo: Mapped[str] = mapped_column(String(120), nullable=False)
    # Para `modificacion`: qué campos la disparan. Vacío = cualquiera. Acotarlo
    # es lo que evita que una regla de «cuando cambie la etapa» se dispare
    # también al corregir un teléfono.
    campos_vigilados: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Para `programada`: expresión cron.
    programacion: Mapped[str | None] = mapped_column(String(120), nullable=True)

    condiciones: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    combinacion: Mapped[str] = mapped_column(String(10), nullable=False, default="todas")
    acciones: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)

    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Orden de ejecución entre reglas del mismo disparador (CRM-00.03.03.06).
    # Sin orden explícito, dos reglas que tocan el mismo campo dan resultados
    # distintos según cómo las devuelva la base.
    prioridad: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    # inmediata | diferida | programada
    momento: Mapped[str] = mapped_column(String(20), nullable=False, default="inmediata")

    # Contadores de uso: sin ellos no hay forma de saber si una regla se
    # dispara de más, ni de encontrar las que no se disparan nunca.
    ejecuciones: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fallos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ultima_ejecucion_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "nombre", name="uq_automatizacion_nombre"),
        Index("ix_automatizaciones_disparador", "tenant_id", "disparador", "objetivo", "activa"),
    )


class EjecucionAutomatizacion(Base):
    """Traza de una ejecución, con la decisión tomada en cada condición.

    Es el depurador (CRM-00.03.03.07): sin registrar por qué una regla NO se
    disparó, la pregunta «¿por qué no se ha asignado este lead?» no tiene
    respuesta, y es la pregunta que más se hace.
    """

    __tablename__ = "ejecuciones_automatizacion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    automatizacion_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("automatizaciones.id", ondelete="CASCADE"), nullable=False
    )
    objeto: Mapped[str] = mapped_column(String(80), nullable=False)
    registro_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # disparada | condiciones_no_cumplidas | fallida | omitida_por_cascada
    resultado: Mapped[str] = mapped_column(String(30), nullable=False)
    # Evaluación de cada condición, para poder explicarlo.
    decisiones: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    acciones_ejecutadas: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Las variables con las que acabó la ejecución. Van en su propia columna y
    # no dentro de `decisiones`, que es una LISTA —una entrada por condición—:
    # meterlas ahí con `{**decisiones, "variables": …}` reventaba con
    # «'list' object is not a mapping» en cuanto una regla cumplía sus
    # condiciones. O sea que ninguna automatización que se disparara de verdad
    # llegaba a terminar. Medido el 26-10-2026 auditando la familia.
    variables: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    profundidad_cascada: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duracion_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_ejecuciones_automatizacion", "automatizacion_id", "created_at"),
        Index("ix_ejecuciones_registro", "tenant_id", "objeto", "registro_id"),
    )


# Tabla común: la clave propia del tenant (BYOK, CRM-00.01.04.09) se replica
# al esquema de cada servicio, porque cada uno cifra y descifra los campos de sus
# propias tablas dentro de sus transacciones.
# La papelera de este servicio. Su router se monta —`/<servicio>/papelera`— y sin
# la tabla la pantalla devolvía 500: `relation "papelera" does not exist`. El
# borrado es lógico y cada servicio guarda la suya en su esquema, que es lo que
# impide que uno lea las tablas de otro.
from crmcore.security.byok import ClaveTenant  # noqa: E402,F401
