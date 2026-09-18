"""Papelera de reciclaje (CRM-00.06.02.04).

Borrar de verdad un registro con años de historia es irreversible y casi siempre
un error humano. Aquí se marca, se conserva durante un plazo y se puede
restaurar; la purga definitiva la hace una tarea, **salvo que haya un legal
hold**, que la bloquea.

Tres decisiones que hacen que esto sirva:

**Restauración en cascada.** Al borrar una cuenta se marcan también sus
direcciones, sus vínculos y sus actividades. Si al restaurar no se devolvieran
todas, quedaría una cuenta viva con la mitad de su historia perdida — y eso es
peor que no haber restaurado, porque parece completa.

**Se guarda QUÉ se borró en cascada.** Sin eso, restaurar tendría que adivinar
qué filas iban con la cabecera, y no puede distinguir las que ya estaban
borradas antes.

**La purga es una operación con nombre y auditada.** No es un `DELETE` suelto en
una tarea nocturna: destruye datos de un cliente y tiene que poder demostrarse
cuándo y por qué se hizo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Index, String, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.db.base import Base
from crmcore.errors import Conflicto, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger

logger = get_logger(__name__)


class EntradaPapelera(Base):
    """Un borrado, con todo lo que arrastró.

    Es el registro que permite restaurar: sin él, devolver una cuenta a la vida
    no sabría qué hijos estaban borrados *por* ese borrado y cuáles ya lo
    estaban antes.
    """

    __tablename__ = "papelera"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    objeto: Mapped[str] = mapped_column(String(80), nullable=False)
    registro_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # Etiqueta legible, copiada al borrar. La papelera tiene que poder enseñar
    # «ACME Ibérica» sin resucitar la fila para leer su nombre.
    etiqueta: Mapped[str] = mapped_column(String(300), nullable=False, default="")

    # Lo que se borró en cascada: {"direcciones": ["id", …], …}
    cascada: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    borrado_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    borrado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Cuándo se puede destruir de verdad.
    purgable_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    restaurado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    restaurado_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    purgado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_papelera_tenant", "tenant_id", "objeto", "borrado_at"),
        # Índice parcial sobre lo que de verdad recorre la purga: lo pendiente.
        # Sin el `where`, el índice incluiría todo el histórico de borrados ya
        # resueltos, que es la mayor parte y no se consulta nunca.
        Index(
            "ix_papelera_purgables",
            "tenant_id",
            "purgable_at",
            postgresql_where=text("restaurado_at IS NULL AND purgado_at IS NULL"),
        ),
    )


@dataclass(frozen=True, slots=True)
class Cascada:
    """Qué hay que marcar además del registro principal.

    `modelo` es la clase, `columna` la que apunta al padre. Cada servicio declara
    las suyas: el núcleo no puede saber que una cuenta tiene direcciones.
    """

    modelo: type
    columna: str


def borrar(
    db: Session,
    registro: Any,
    *,
    objeto: str,
    etiqueta: str = "",
    cascadas: tuple[Cascada, ...] = (),
    por: UUID | None = None,
    dias_retencion: int | None = None,
) -> EntradaPapelera:
    """Envía un registro a la papelera, con lo que cuelgue de él."""
    from crmcore.audit.chain import registrar
    from crmcore.runtime import settings as rt

    if getattr(registro, "deleted_at", None) is not None:
        raise Conflicto("Ese registro ya está en la papelera", error_code="papelera.ya_borrado")

    dias = int(dias_retencion or rt.efectivo("papelera_dias_retencion", db) or 30)
    ahora = datetime.now(timezone.utc)

    registro.deleted_at = ahora
    if hasattr(registro, "deleted_by"):
        registro.deleted_by = por

    cascada: dict[str, list[str]] = {}
    for enlace in cascadas:
        hijos = (
            db.execute(
                select(enlace.modelo).where(
                    getattr(enlace.modelo, enlace.columna) == registro.id,
                    enlace.modelo.deleted_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
        for hijo in hijos:
            hijo.deleted_at = ahora
            if hasattr(hijo, "deleted_by"):
                hijo.deleted_by = por
        if hijos:
            cascada[enlace.modelo.__tablename__] = [str(h.id) for h in hijos]

    entrada = EntradaPapelera(
        tenant_id=registro.tenant_id,
        objeto=objeto,
        registro_id=registro.id,
        etiqueta=(etiqueta or getattr(registro, "nombre", "") or "")[:300],
        cascada=cascada,
        borrado_por=por,
        purgable_at=ahora + timedelta(days=dias),
    )
    db.add(entrada)
    registrar(
        db,
        accion="registro.borrado",
        objeto=objeto,
        objeto_id=registro.id,
        datos={"cascada": {k: len(v) for k, v in cascada.items()}, "purgable_en_dias": dias},
        tenant_id=registro.tenant_id,
    )
    logger.info("papelera.borrado", objeto=objeto, registro=str(registro.id), cascada=len(cascada))
    return entrada


def restaurar(
    db: Session,
    entrada_id: UUID,
    *,
    modelos: dict[str, type],
    por: UUID | None = None,
) -> EntradaPapelera:
    """Devuelve a la vida un registro y lo que se borró con él.

    `modelos` mapea nombre de tabla a clase, y lo pasa el servicio: el núcleo no
    conoce los modelos de nadie.
    """
    from crmcore.audit.chain import registrar

    entrada = db.get(EntradaPapelera, entrada_id)
    if entrada is None:
        raise NoEncontrado("Esa entrada de papelera no existe", error_code="papelera.no_encontrada")
    if entrada.purgado_at is not None:
        raise Conflicto(
            "Ese registro ya se purgó definitivamente y no se puede restaurar",
            error_code="papelera.ya_purgado",
        )
    if entrada.restaurado_at is not None:
        raise Conflicto("Ese registro ya se restauró", error_code="papelera.ya_restaurado")

    principal = modelos.get(entrada.objeto)
    if principal is None:
        raise NoEncontrado(
            f"No se sabe restaurar objetos de tipo «{entrada.objeto}»",
            error_code="papelera.objeto_desconocido",
        )
    fila = db.get(principal, entrada.registro_id)
    if fila is None:
        raise NoEncontrado(
            "El registro ya no existe en la base", error_code="papelera.registro_ausente"
        )
    fila.deleted_at = None
    if hasattr(fila, "deleted_by"):
        fila.deleted_by = None

    restaurados = 0
    for tabla, ids in (entrada.cascada or {}).items():
        modelo = modelos.get(tabla)
        if modelo is None:
            # Se avisa y se sigue: restaurar la cabecera sin un tipo de hijo es
            # mejor que no restaurar nada, pero hay que saberlo.
            logger.warning("papelera.cascada_desconocida", tabla=tabla, entrada=str(entrada_id))
            continue
        for hijo in (
            db.execute(select(modelo).where(modelo.id.in_([UUID(i) for i in ids]))).scalars().all()
        ):
            hijo.deleted_at = None
            if hasattr(hijo, "deleted_by"):
                hijo.deleted_by = None
            restaurados += 1

    entrada.restaurado_at = datetime.now(timezone.utc)
    entrada.restaurado_por = por
    registrar(
        db,
        accion="registro.restaurado",
        objeto=entrada.objeto,
        objeto_id=entrada.registro_id,
        datos={"hijos_restaurados": restaurados},
        tenant_id=entrada.tenant_id,
    )
    return entrada


def purgar(
    db: Session,
    *,
    tenant_id: UUID,
    modelos: dict[str, type],
    limite: int = 100,
    motivo: str,
) -> dict[str, int]:
    """Destruye definitivamente lo que ya pasó su plazo.

    **Exige motivo** y queda auditado: esto destruye datos de un cliente y tiene
    que poder demostrarse cuándo y por qué se hizo. Respeta el legal hold, que
    bloquea la destrucción aunque el plazo haya pasado.
    """
    from crmcore.audit.chain import registrar

    ahora = datetime.now(timezone.utc)
    entradas = (
        db.execute(
            select(EntradaPapelera)
            .where(
                EntradaPapelera.tenant_id == tenant_id,
                EntradaPapelera.purgable_at <= ahora,
                EntradaPapelera.restaurado_at.is_(None),
                EntradaPapelera.purgado_at.is_(None),
            )
            .limit(limite)
        )
        .scalars()
        .all()
    )

    purgados: dict[str, int] = {}
    for entrada in entradas:
        if _hay_legal_hold(db, entrada):
            logger.info(
                "papelera.purga_bloqueada_por_legal_hold",
                objeto=entrada.objeto,
                registro=str(entrada.registro_id),
            )
            continue
        modelo = modelos.get(entrada.objeto)
        if modelo is None:
            continue
        fila = db.get(modelo, entrada.registro_id)
        if fila is not None:
            db.delete(fila)
        entrada.purgado_at = ahora
        purgados[entrada.objeto] = purgados.get(entrada.objeto, 0) + 1

    if purgados:
        registrar(
            db,
            accion="datos.purga",
            objeto="papelera",
            datos={"purgados": purgados},
            motivo=motivo,
            tenant_id=tenant_id,
        )
    return purgados


def _hay_legal_hold(db: Session, entrada: EntradaPapelera) -> bool:
    """Si una retención legal impide destruir este registro (CRM-07.03.01.06).

    Hoy devuelve siempre `False` porque el servicio de legal hold llega en una
    fase posterior — y se dice aquí en vez de omitirlo, para que nadie dé por
    hecho que la protección ya está puesta.
    """
    return False
