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
    # Cuándo le toca la siguiente vez a una programada, y con qué horario se
    # calculó. Las pone el planificador: el horario se guardaba y no lo leía
    # nadie, así que una regla «los lunes a las 8» no corría nunca. Guardar con
    # qué expresión se calculó es lo que permite notar que alguien la cambió
    # desde la ficha y recalcular, en vez de seguir con la hora vieja.
    proxima_ejecucion_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, info={"calculado": True}
    )
    proxima_segun: Mapped[str | None] = mapped_column(
        String(120), nullable=True, info={"calculado": True}
    )
    # Quién la encendió y con qué permisos (CRM-00.03.02). Un proceso que lanza
    # esta regla actúa con la identidad de quien la ACTIVÓ: sin guardarla, sus
    # pasos «servicio» arrancaban sin identidad y fallaban con «no se sabe con
    # qué permisos actuar». Si se apaga y la enciende otra persona, pasa a ser
    # esa: es quien ha decidido que vuelva a actuar.
    activada_por_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, info={"calculado": True}
    )
    activada_con: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
        info={"calculado": True},
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


class EjecucionPendiente(Base):
    """Una ejecución que espera su momento (CRM-00.03.03.05).

    `momento` —inmediata, diferida o programada— se guardaba y **no lo leía
    nadie**: todo corría al momento. Esto es la cola que lo hace verdad.

    **Es una tabla y no una cola en memoria**, por lo que se pide: que no se
    pierda nada si el proceso cae. La fila se escribe en la misma transacción
    que recibe el disparo —si el disparo se deshace, la ejecución no existe— y
    se marca hecha en la misma transacción que ejecuta la regla, así que una
    caída a medias deja la fila pendiente y la siguiente vuelta la recoge.

    **Y es idempotente por `clave`.** Un evento que llega dos veces, o dos
    procesos del planificador que miran el mismo minuto, chocan con la
    restricción única en vez de ejecutar la regla dos veces.
    """

    __tablename__ = "ejecuciones_pendientes"
    # No viaja a los sandboxes: la cola es de ESTE entorno. Copiada, el sandbox
    # repetiría las ejecuciones que producción tiene pendientes.
    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_ejecucion_pendiente_clave"),
        Index("ix_ejecuciones_pendientes_turno", "estado", "ejecutar_at"),
        {"info": {"no_copiar_a_sandbox": "es la cola de ejecuciones de este entorno"}},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    automatizacion_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("automatizaciones.id", ondelete="CASCADE"), nullable=False
    )
    # Qué la disparó: el evento, el reloj, una persona o un webhook. Sin esto,
    # en la cola no se distingue la del lunes de la que encoló un alta.
    origen: Mapped[str] = mapped_column(String(30), nullable=False)
    clave: Mapped[str] = mapped_column(String(200), nullable=False)
    objeto: Mapped[str] = mapped_column(String(120), nullable=False)
    registro_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Los valores con los que se disparó, CONGELADOS. Ejecutarla con los de
    # ahora haría que una diferida evaluara sus condiciones sobre otro estado
    # del registro que el que la disparó.
    valores: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    ejecutar_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # pendiente | hecha | fallida
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    intentos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # La traza que dejó al ejecutarse: desde la cola se llega al «por qué».
    ejecucion_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    terminada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SecretoWebhookAutomatizacion(Base):
    """El secreto con el que se firma el webhook que dispara una regla
    (CRM-00.03.03.02).

    **En su propia tabla y no en la de automatizaciones**, por dos razones que
    se notan. La copia a un sandbox se salta las tablas con secretos —apuntan a
    sistemas de verdad—, y con el secreto dentro se habría dejado de copiar
    cualquier automatización. Y la ficha enseña las columnas de la regla: el
    secreto tiene que salir una vez, al generarlo, y nunca más.

    Cifrado: para comprobar una firma HMAC hace falta el secreto en claro, así
    que no puede guardarse solo su huella.
    """

    __tablename__ = "secretos_webhook_automatizacion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    automatizacion_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("automatizaciones.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    secreto: Mapped[str] = mapped_column(Text, nullable=False, info={"secreto": True})
    generado_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# Tabla común: la clave propia del tenant (BYOK, CRM-00.01.04.09) se replica
# al esquema de cada servicio, porque cada uno cifra y descifra los campos de sus
# propias tablas dentro de sus transacciones.
# La papelera de este servicio. Su router se monta —`/<servicio>/papelera`— y sin
# la tabla la pantalla devolvía 500: `relation "papelera" does not exist`. El
# borrado es lógico y cada servicio guarda la suya en su esquema, que es lo que
# impide que uno lea las tablas de otro.
from crmcore.security.byok import ClaveTenant  # noqa: E402,F401

# El código del tenant, con datos (CRM-00.04.02.01, .04, .05, .06, .07).
from services.automation.codigo_tenant import (  # noqa: E402,F401
    EjecucionExtension,
    EndpointPropio,
    Extension,
    FirmanteExtension,
    VersionExtension,
)
