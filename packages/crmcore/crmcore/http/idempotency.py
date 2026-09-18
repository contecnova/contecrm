"""Idempotencia de escrituras mediante `Idempotency-Key` (CRM-00.02.01.08).

El problema real: un cliente manda `POST /opportunities`, la red se corta antes
de que llegue la respuesta, y el cliente reintenta. Sin idempotencia hay dos
oportunidades. Con ella, el segundo intento devuelve **la respuesta del primero**,
byte por byte, y no ejecuta nada.

Tres decisiones que hacen que esto funcione de verdad:

**Se guarda la respuesta, no solo la clave.** Devolver 409 al reintento obligaría
al cliente a averiguar si la primera vez funcionó. Devolver la respuesta
original le da exactamente lo que habría recibido si la red no hubiera fallado.

**Se comprueba el hash del cuerpo.** Si alguien reutiliza una clave con un cuerpo
distinto, es un error del cliente, no un reintento: se responde 409 y se dice.
Sin esta comprobación, reciclar una clave devolvería la respuesta de otra
operación como si fuera la suya.

**Se reserva la clave ANTES de ejecutar.** La fila se inserta al empezar, con
estado «en curso». Dos peticiones simultáneas con la misma clave: una inserta y
ejecuta, la otra choca con la clave primaria y espera o responde 409 «en curso».
Si se guardara al final, las dos ejecutarían.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Integer, String, Text, delete, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.db.base import Base
from crmcore.errors import Conflicto
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Cuánto se recuerda una clave. Debe cubrir de sobra el tiempo durante el que un
# cliente razonable reintenta; 24 h cubre incluso un proceso por lotes que se
# retoma al día siguiente.
RETENCION_HORAS = 24


class ClaveIdempotencia(Base):
    __tablename__ = "claves_idempotencia"

    clave: Mapped[str] = mapped_column(String(200), primary_key=True)
    # Forma parte de la primaria: dos tenants pueden usar la misma clave sin
    # pisarse, y una clave de un tenant nunca devuelve la respuesta de otro.
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    metodo: Mapped[str] = mapped_column(String(10), nullable=False)
    ruta: Mapped[str] = mapped_column(String(400), nullable=False)
    hash_cuerpo: Mapped[str] = mapped_column(String(64), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="en_curso")
    respuesta_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    respuesta_cuerpo: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


def hash_cuerpo(cuerpo: bytes) -> str:
    return hashlib.sha256(cuerpo).hexdigest()


def reservar(
    db: Session,
    *,
    clave: str,
    tenant_id: UUID,
    metodo: str,
    ruta: str,
    cuerpo: bytes,
) -> ClaveIdempotencia | None:
    """Reserva la clave. Devuelve `None` si es nueva; la fila previa si repetida.

    `None` significa «sigue, eres el primero». Una fila significa «esto ya pasó»:
    el llamante decide si devuelve la respuesta guardada o espera.
    """
    h = hash_cuerpo(cuerpo)
    res = db.execute(
        pg_insert(ClaveIdempotencia)
        .values(
            clave=clave,
            tenant_id=tenant_id,
            metodo=metodo,
            ruta=ruta,
            hash_cuerpo=h,
            estado="en_curso",
        )
        .on_conflict_do_nothing(index_elements=["clave", "tenant_id"])
    )
    if res.rowcount:
        return None

    previa = db.get(ClaveIdempotencia, {"clave": clave, "tenant_id": tenant_id})
    if previa is None:  # pragma: no cover — carrera improbable con la purga
        return None

    if previa.hash_cuerpo != h:
        raise Conflicto(
            "Esa clave de idempotencia ya se usó con un cuerpo distinto. Usa una "
            "clave nueva para una operación nueva.",
            error_code="idempotencia.cuerpo_distinto",
        )
    if previa.metodo != metodo or previa.ruta != ruta:
        raise Conflicto(
            "Esa clave de idempotencia ya se usó en otra operación",
            error_code="idempotencia.operacion_distinta",
        )
    return previa


def completar(
    db: Session,
    *,
    clave: str,
    tenant_id: UUID,
    status: int,
    cuerpo: dict[str, Any] | None,
) -> None:
    """Guarda la respuesta para que el reintento la reciba igual."""
    fila = db.get(ClaveIdempotencia, {"clave": clave, "tenant_id": tenant_id})
    if fila is None:  # pragma: no cover
        return
    fila.estado = "completada"
    fila.respuesta_status = status
    fila.respuesta_cuerpo = cuerpo


def fallar(db: Session, *, clave: str, tenant_id: UUID, error: str) -> None:
    """Libera la clave cuando la operación falló.

    Se **borra**, no se marca como fallida: si la operación no llegó a ocurrir,
    el cliente tiene todo el derecho a reintentar con la misma clave. Dejarla
    bloqueada le obligaría a inventar una clave nueva para reintentar algo que
    nunca pasó.
    """
    db.execute(
        delete(ClaveIdempotencia).where(
            ClaveIdempotencia.clave == clave,
            ClaveIdempotencia.tenant_id == tenant_id,
        )
    )
    logger.info("idempotencia.liberada_por_fallo", error=error[:200])


def purgar(db: Session, *, horas: int = RETENCION_HORAS) -> int:
    limite = datetime.now(timezone.utc) - timedelta(hours=horas)
    res = db.execute(delete(ClaveIdempotencia).where(ClaveIdempotencia.created_at < limite))
    return int(res.rowcount or 0)
