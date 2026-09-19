"""Modelo de datos del motor de procesos."""

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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column


class DefinicionProceso(Base, TimestampMixin):
    """Definición de un proceso, versionada.

    Las versiones **no se sobrescriben**: publicar una versión nueva crea una
    fila nueva y las instancias en vuelo siguen con la suya. Es lo que evita el
    fallo clásico de los motores de proceso — cambiar el diagrama un martes y
    que doscientas instancias a medias pasen a ejecutar pasos que no existían
    cuando empezaron.
    """

    __tablename__ = "definiciones_proceso"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # El grafo del proceso: pasos, transiciones y compensaciones. Es JSON y no
    # código porque tiene que poder editarse, versionarse, simularse y enseñarse
    # en un diagrama. La forma está documentada en `motor.py`.
    definicion: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    # publicada | borrador | retirada. Solo se instancian las publicadas; un
    # borrador se puede simular pero no arrancar contra datos reales.
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="borrador")
    # Eventos que arrancan el proceso automáticamente (coreografía).
    disparadores: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", "version", name="uq_definicion_version"),
        Index("ix_definiciones_clave", "tenant_id", "clave", "estado"),
    )


class InstanciaProceso(Base, TimestampMixin):
    """Una ejecución concreta de un proceso, siempre de un tenant (CRM-00.03.02.15).

    `variables` es el estado del proceso y se persiste en **cada paso**, no al
    final. Ese es todo el truco de la durabilidad: si el proceso muere entre el
    paso 3 y el 4, al retomarlo el estado es exactamente el de después del 3.
    """

    __tablename__ = "instancias_proceso"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    definicion_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("definiciones_proceso.id"), nullable=False
    )
    clave: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    # ejecutando | esperando | esperando_humano | completada | fallida |
    # compensando | compensada | cancelada
    estado: Mapped[str] = mapped_column(String(24), nullable=False, default="ejecutando")
    paso_actual: Mapped[str | None] = mapped_column(String(120), nullable=True)
    variables: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    # Qué disparó el proceso, para poder rastrear de dónde salió.
    origen_tipo: Mapped[str | None] = mapped_column(String(60), nullable=True)
    origen_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Proceso padre, cuando es un subproceso (CRM-00.03.02.08).
    padre_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    profundidad: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    pasos_ejecutados: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Cuándo debe despertar: temporizador, espera o reintento. NULL = no espera
    # nada por tiempo. El planificador solo mira lo vencido, así que este campo
    # es el que hace que las esperas no cuesten nada mientras esperan.
    despertar_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # Bloqueo de ejecución: qué worker la tiene tomada y hasta cuándo. Sin esto,
    # dos réplicas pueden avanzar la misma instancia a la vez y duplicar sus
    # efectos.
    tomada_por: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tomada_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    finalizada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_instancias_pendientes", "estado", "despertar_at"),
        Index("ix_instancias_origen", "tenant_id", "origen_tipo", "origen_id"),
    )


class PasoEjecutado(Base):
    """Historial de ejecución, paso a paso.

    Es lo que responde a «¿por dónde va y por qué se paró?» (CRM-00.03.02.11).
    Se guarda la entrada y la salida de cada paso, no solo que se ejecutó: sin
    los valores, reproducir un fallo obliga a adivinar con qué datos ocurrió.
    """

    __tablename__ = "pasos_ejecutados"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    instancia_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("instancias_proceso.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    paso: Mapped[str] = mapped_column(String(120), nullable=False)
    tipo: Mapped[str] = mapped_column(String(40), nullable=False)
    # ok | fallido | omitido | compensado
    resultado: Mapped[str] = mapped_column(String(20), nullable=False)
    intento: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    entrada: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    salida: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duracion_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_pasos_instancia_orden", "instancia_id", "created_at"),)


class TareaHumana(Base, TimestampMixin):
    """Paso que espera a una persona (CRM-00.03.02.09).

    Aprobar un descuento, validar un contrato, decidir si se escala. La
    diferencia con una notificación es que el proceso **está detenido** hasta que
    alguien responde, y que ese alguien tiene una bandeja donde lo ve.
    """

    __tablename__ = "tareas_humanas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    instancia_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("instancias_proceso.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    paso: Mapped[str] = mapped_column(String(120), nullable=False)
    titulo: Mapped[str] = mapped_column(String(300), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # A quién le toca. Asignación a una persona o a un rol; con rol, la coge
    # quien esté disponible, que es lo que evita que una baja detenga el proceso.
    asignada_a: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    asignada_rol: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Delegación: a quién se le pasó y quién la delegó.
    delegada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # pendiente | en_curso | completada | rechazada | escalada | caducada
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    # Opciones de respuesta: ["aprobar", "rechazar", "pedir_cambios"]
    opciones: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    respuesta: Mapped[str | None] = mapped_column(String(60), nullable=True)
    comentario: Mapped[str | None] = mapped_column(Text, nullable=True)
    datos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    # SLA: cuándo vence y qué hacer al vencer. Sin vencimiento, una tarea que
    # nadie mira detiene el proceso para siempre en silencio.
    vence_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    escalada_a: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    completada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (Index("ix_tareas_bandeja", "tenant_id", "estado", "asignada_a"),)


class TablaDecision(Base, TimestampMixin):
    """Tabla de decisión editable por negocio (DMN, CRM-00.03.02.10).

    Reglas del tipo «si el importe supera X y el margen baja de Y, aprueba el
    director». Viven como datos para que las cambie quien manda en ellas, que
    normalmente no es quien escribe el código.
    """

    __tablename__ = "tablas_decision"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(120), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    # Política de aciertos: `primera` (gana la primera regla que case) o
    # `todas` (se acumulan todas). Se declara porque, sin ella, dos reglas que
    # casan a la vez dan un resultado que depende del orden de lectura.
    politica: Mapped[str] = mapped_column(String(20), nullable=False, default="primera")
    entradas: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    salidas: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    reglas: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "clave", name="uq_tabla_decision"),)


# Tabla común: la clave propia del tenant (BYOK, CRM-00.01.04.09) se replica
# al esquema de cada servicio, porque cada uno cifra y descifra los campos de sus
# propias tablas dentro de sus transacciones.
from crmcore.security.byok import ClaveTenant  # noqa: E402,F401
