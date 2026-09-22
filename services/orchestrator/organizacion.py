"""Quién manda sobre quién, replicado aquí (CRM-00.03.05.07).

Para decidir a quién le toca aprobar hace falta el organigrama: el superior de
una persona, sus roles, su unidad. Eso vive en `membresias`, en el esquema de
`identity`, y ningún servicio lee el esquema de otro. Llega **por evento**, como
los tipos de cambio, los calendarios y el esquema del tenant.

El precio, dicho en voz alta:

**El organigrama va por detrás.** Un ascenso de hace dos segundos puede no estar.
Para una aprobación es aceptable —una cadena de mando no cambia cada minuto—,
pero quien mire a quién le tocaría aprobar tiene que poder saber de cuándo es el
dato, y por eso se guarda `sincronizado_at` y se enseña.

**A quien no consta, no se le asigna nada.** Si el organigrama no conoce a una
persona, resolver el aprobador **falla y lo dice** en vez de caer en un valor por
defecto. Un aprobador elegido por defecto es una aprobación que alguien firma sin
que le correspondiera, y eso se descubre en una auditoría.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base
from crmcore.errors import NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import Boolean, DateTime, Index, UniqueConstraint, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)


class PersonaOrg(Base):
    """Posición de una persona en la organización, replicada."""

    __tablename__ = "personas_org"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    superior_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    unidad_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    roles: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    atributos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # De cuándo es el dato. Se enseña siempre que se enseñe un aprobador
    # resuelto: sin esto, una cadena de mando desfasada parece actual.
    sincronizado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "usuario_id", name="uq_persona_org"),
        Index("ix_personas_org_superior", "tenant_id", "superior_id"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _uuid(valor: Any) -> UUID | None:
    texto = str(valor or "").strip()
    return UUID(texto) if texto else None


def aplicar(db: Session, tenant_id: UUID, datos: dict[str, Any]) -> PersonaOrg | None:
    """Vuelca en la proyección lo que dice el evento."""
    usuario_id = _uuid(datos.get("user_id"))
    if usuario_id is None:
        logger.warning("org.evento_sin_usuario", tenant=str(tenant_id))
        return None

    fila = db.execute(
        select(PersonaOrg).where(
            PersonaOrg.tenant_id == tenant_id, PersonaOrg.usuario_id == usuario_id
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = PersonaOrg(tenant_id=tenant_id, usuario_id=usuario_id)
        db.add(fila)

    fila.superior_id = _uuid(datos.get("superior_id"))
    fila.unidad_id = _uuid(datos.get("unidad_id"))
    fila.roles = [str(r) for r in (datos.get("roles") or [])]
    fila.atributos = dict(datos.get("atributos") or {})
    fila.activa = bool(datos.get("activa", True))
    fila.sincronizado_at = _ahora()
    db.flush()
    return fila


def persona(db: Session, tenant_id: UUID, usuario_id: UUID) -> PersonaOrg:
    fila = db.execute(
        select(PersonaOrg).where(
            PersonaOrg.tenant_id == tenant_id, PersonaOrg.usuario_id == usuario_id
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado(
            "Esa persona no está en el organigrama replicado. Sin ella no se "
            "puede resolver quién aprueba.",
            error_code="org.persona_desconocida",
        )
    return fila


def cadena_de_mando(
    db: Session, tenant_id: UUID, usuario_id: UUID, *, tope: int = 10
) -> list[UUID]:
    """De quien pide hacia arriba, sin incluirle a él.

    Se corta con un tope y con un conjunto de vistos: un ciclo en el organigrama
    —A reporta a B y B a A— es raro pero existe, y con recursión ingenua tumbaría
    el proceso en vez de dar una cadena corta y rara.

    Los inactivos **se saltan, no se paran**: un jefe de baja no puede bloquear
    todas las aprobaciones de su equipo, y subir un escalón más es exactamente lo
    que haría una persona.
    """
    salida: list[UUID] = []
    vistos = {usuario_id}
    actual = persona(db, tenant_id, usuario_id).superior_id
    while actual and len(salida) < tope:
        if actual in vistos:
            logger.warning("org.ciclo_en_la_jerarquia", tenant=str(tenant_id), en=str(actual))
            break
        vistos.add(actual)
        fila = db.execute(
            select(PersonaOrg).where(
                PersonaOrg.tenant_id == tenant_id, PersonaOrg.usuario_id == actual
            )
        ).scalar_one_or_none()
        if fila is None:
            break
        if fila.activa:
            salida.append(actual)
        actual = fila.superior_id
    return salida


def con_rol(db: Session, tenant_id: UUID, rol: str, *, unidad_id: UUID | None = None) -> list[UUID]:
    """Quién tiene ese rol, opcionalmente acotado a una unidad."""
    consulta = select(PersonaOrg).where(
        PersonaOrg.tenant_id == tenant_id,
        PersonaOrg.activa.is_(True),
        PersonaOrg.roles.contains([rol]),
    )
    if unidad_id is not None:
        consulta = consulta.where(PersonaOrg.unidad_id == unidad_id)
    return [f.usuario_id for f in db.execute(consulta.order_by(PersonaOrg.usuario_id)).scalars()]


async def consumir(mensaje: Any) -> None:
    """Escucha los cambios de organigrama que publica `identity`."""
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto

    if str(getattr(mensaje, "tipo", "") or "") != "user.org.changed":
        return
    bruto = getattr(mensaje, "tenant_id", None)
    if not bruto:
        logger.warning("org.evento_sin_tenant")
        return
    tenant_id = UUID(str(bruto))
    datos = getattr(mensaje, "data", None) or {}
    with con_contexto(tenant_id=tenant_id, origen="bus"), unidad_de_trabajo(tenant_id) as uow:
        aplicar(uow.db, tenant_id, datos)
