"""Base declarativa y mixins comunes a todo el modelo de datos.

Aquí se decide, de una vez y para todas las tablas, lo que en otros sistemas se
queda a criterio de quien escribe cada modelo: que toda tabla de negocio lleve
`tenant_id`, que toda fila sepa cuándo y quién la creó, que toda entidad
editable tenga versión para la concurrencia optimista, y que borrar sea reversible.

**Toda tabla de negocio lleva `tenant_id`. Sin excepciones.**

Es la corrección deliberada de una limitación conocida y documentada de
`contecmind`: allí 58 de 107 modelos tienen `tenant_id` y los otros 49 dependen
de filtros de propiedad o de que el router esté restringido. Funciona, está
auditado endpoint a endpoint y hay pruebas que lo sostienen — pero significa que
las dos redes automáticas (RLS y el guard ORM) comparten el mismo punto ciego,
porque las dos seleccionan las tablas por el mismo predicado: tener la columna.

Aquí la columna es obligatoria, y hay un gate (`test_tenant_scope_contract.py`)
que falla si aparece una tabla de negocio sin ella. El coste es una columna
redundante en las tablas hijas; la ganancia es que las dos redes cubren el 100 %
y no hay que razonar tabla por tabla nunca más.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, MetaData, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from crmcore.ids import nuevo_id

# Nombres deterministas para índices y restricciones. Sin esto, Alembic genera
# nombres distintos en cada máquina y un `downgrade` no encuentra lo que creó el
# `upgrade`: la migración funciona al aplicarla y falla al revertirla, que es
# justo el momento en que uno depende de ella.
CONVENCION_NOMBRES = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base declarativa de todos los servicios.

    El esquema NO se fija aquí: lo pone cada servicio al crear su engine, porque
    cada uno vive en el suyo y el mismo modelo se usa en pruebas contra un
    esquema efímero.
    """

    metadata = MetaData(naming_convention=CONVENCION_NOMBRES)

    def a_dict(self, excluir: set[str] | None = None) -> dict[str, Any]:
        """Volcado plano de las columnas. Para auditoría y para el historial.

        No serializa relaciones a propósito: el historial de campo registra
        columnas, y recorrer relaciones aquí dispararía cargas perezosas en
        mitad de un `after_flush`.
        """
        excluir = excluir or set()
        return {
            c.name: getattr(self, c.name) for c in self.__table__.columns if c.name not in excluir
        }


def _ahora() -> datetime:
    """UTC con zona explícita. Nunca `utcnow()`, que devuelve un naive y acaba
    comparándose con un aware: es el origen del clásico «can't compare offset-naive
    and offset-aware datetimes» en un cálculo de SLA a las tres de la mañana."""
    return datetime.now(timezone.utc)


class IdMixin:
    """Clave primaria UUIDv7 (ver `crmcore.ids` para el porqué)."""

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)


class TenantMixin:
    """`tenant_id` obligatorio, indexado y no nulo.

    Es la columna sobre la que trabajan RLS (`deploy/sql/rls.sql`) y el guard
    ORM (`crmcore.tenancy.guard`). Que sea NOT NULL es parte de la garantía: una
    fila con tenant nulo sería visible desde cualquier tenant bajo una política
    permisiva, y ese es exactamente el agujero que se quiere cerrar.
    """

    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)


class TimestampMixin:
    """Cuándo se creó y cuándo se tocó por última vez.

    El default lo pone el servidor (`now()`) y no Python: así una inserción por
    SQL directo —una migración, una carga masiva, una corrección manual— también
    queda fechada, y las fechas de todas las filas salen del mismo reloj.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=_ahora,
        nullable=False,
    )


class ActorMixin:
    """Quién creó y quién modificó, y por qué vía.

    `*_origen` distingue si el cambio vino de la API, de la UI, de una
    automatización o del orquestador. Sin eso, el historial de campo
    (CRM-00.05.04.02) enseña un usuario en un cambio que en realidad hizo una
    regla automática en su nombre, y la conversación con el cliente se atasca
    ahí.
    """

    created_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    updated_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    created_origen: Mapped[str] = mapped_column(String(32), nullable=False, default="api")
    updated_origen: Mapped[str] = mapped_column(String(32), nullable=False, default="api")


class VersionMixin:
    """Contador de versión para concurrencia optimista (CRM-00.02.01.09).

    Es lo que hay detrás del `ETag`: el cliente lee con `version=7`, manda
    `If-Match: "7"`, y si entretanto otro escribió, la actualización afecta a
    cero filas y se responde 409 en vez de pisar el cambio ajeno en silencio.

    `version_id_col` hace que SQLAlchemy lo incremente y lo compruebe solo; no
    hay que acordarse en cada `update`.
    """

    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default=text("1"))

    __mapper_args__ = {"version_id_col": None}  # lo activa cada modelo (ver nota)
    # Nota: SQLAlchemy exige que `version_id_col` apunte a la columna del propio
    # mapper, y desde un mixin no se puede referenciar todavía. Cada modelo que
    # quiera el bloqueo automático declara:
    #     __mapper_args__ = {"version_id_col": version}
    # Los que no lo declaren siguen teniendo la columna (y el ETag funciona),
    # pero sin la comprobación automática en el flush.


class SoftDeleteMixin:
    """Borrado reversible: papelera de reciclaje (CRM-00.06.02.04).

    Borrar de verdad una cuenta con diez años de historia es irreversible y casi
    siempre un error humano. Aquí se marca, y la purga definitiva la hace una
    tarea pasado el plazo de retención — salvo que haya un legal hold, que la
    bloquea (CRM-07.03.01.06).
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    deleted_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    @property
    def esta_borrado(self) -> bool:
        return self.deleted_at is not None


class MetadatosMixin:
    """Campos personalizados del tenant, en JSONB (CRM-00.04.01.02).

    Los campos que el tenant añade viven aquí, no en columnas nuevas. La razón
    es el aislamiento: si añadir un campo en un tenant alterara la tabla, sería
    un DDL que afecta a todos los demás, con su bloqueo y su riesgo. En JSONB el
    esquema de cada tenant es suyo, y los índices GIN parciales por tenant
    cubren las consultas que lo necesiten.

    La forma y las validaciones de estos campos las define el servicio de
    metadatos; aquí solo se guarda el valor.
    """

    campos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class EntidadBase(Base, IdMixin, TenantMixin, TimestampMixin, ActorMixin, VersionMixin):
    """Lo que hereda cualquier entidad de negocio.

    Junta lo obligatorio: identificador opaco, tenant, fechas, autoría y
    versión. La papelera y los campos personalizados se añaden aparte porque no
    toda entidad los quiere (una línea de auditoría no se borra ni se extiende).
    """

    __abstract__ = True
