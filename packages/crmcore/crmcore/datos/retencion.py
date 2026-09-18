"""Retención, borrado automático y legal hold.

Cubre CRM-07.03.01.01 (políticas de retención y eliminación automática por tipo
de dato) y CRM-07.03.01.06 (legal hold: bloqueo de eliminación por litigio).

Van juntos porque **separarlos es un problema legal**: una tarea de purga que no
consulta los bloqueos borra, puntualmente y sin que nadie se entere, la prueba
que un juzgado acaba de pedir. El bloqueo no es una capa encima de la retención:
es una condición que la retención consulta **antes** de cada borrado.

Portado de `contecmind` (`app/services/legal_hold.py` y su modelo), con dos
cambios que aquí son obligados:

**Los bloqueos viven en el esquema del servicio que guarda el dato.** No hay una
tabla central: los permisos de base de datos impiden —a propósito— que un
servicio escriba en el esquema de otro, así que un bloqueo central no lo podría
consultar la purga de `party`. Un bloqueo que cubre todo el tenant se pone en
cada servicio, y de coordinarlo se encarga quien llama a las APIs, igual que con
la papelera.

**Las clases de dato se declaran, no se listan aquí.** Allí eran una tupla fija
de cinco; aquí cada servicio registra las suyas con su modelo y su campo de
fecha. Una lista fija en el núcleo obligaría a tocarlo cada vez que un servicio
añade un objeto, y acabaría desfasada.

**Ante la duda, no se borra.** Si no se puede determinar si hay un bloqueo, la
purga se abstiene. El coste de conservar de más es almacenamiento; el de borrar
de menos no se puede deshacer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.db.base import Base
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ClaseDato:
    """Un tipo de dato con vida limitada.

    `campo_fecha` dice desde cuándo se cuenta la retención, y **no siempre es la
    fecha de creación**: una actividad se retiene desde que se completó, y un
    caso desde que se cerró. Contar desde la creación borraría una actividad
    abierta de hace tres años que sigue siendo la única tarea pendiente de un
    cliente.
    """

    clave: str
    descripcion: str
    modelo: type
    campo_fecha: str = "created_at"
    # Días por defecto si el tenant no fija política. 0 = no se purga nunca.
    dias_defecto: int = 0
    # `logico` marca la fila (recuperable desde la papelera); `fisico` la borra.
    # El físico se reserva para lo que ocupa de verdad —registros de entrega,
    # trazas— y para lo que la ley obliga a destruir.
    borrado: str = "logico"
    # Si la fila solo se purga cuando ya está borrada lógicamente. Es lo normal
    # para la papelera: la retención define cuánto vive lo ya borrado.
    solo_si_borrado: bool = False


CLASES: dict[str, ClaseDato] = {}


def registrar_clase(clase: ClaseDato) -> ClaseDato:
    """Declara una clase de dato purgable. Lo hace cada servicio con las suyas.

    Se comprueba **al declararla** que el modelo tiene los campos que la clase
    dice usar. Descubrirlo al purgar significaría un `AttributeError` en mitad
    de una tarea nocturna, con la mitad de las clases ya procesadas y nadie
    delante — y con la clase rota sin purgar en silencio hasta que alguien mire
    los logs.
    """
    if clase.borrado not in ("logico", "fisico"):
        raise ValueError(f"Tipo de borrado desconocido: {clase.borrado}")
    if not hasattr(clase.modelo, clase.campo_fecha):
        raise ValueError(
            f"La clase «{clase.clave}» cuenta desde «{clase.campo_fecha}», y "
            f"{clase.modelo.__name__} no tiene ese campo"
        )
    if not hasattr(clase.modelo, "tenant_id"):
        raise ValueError(
            f"«{clase.clave}» apunta a {clase.modelo.__name__}, que no tiene "
            "tenant_id: no se podría purgar de un tenant sin tocar a los demás"
        )
    if (clase.borrado == "logico" or clase.solo_si_borrado) and not hasattr(
        clase.modelo, "deleted_at"
    ):
        raise ValueError(
            f"«{clase.clave}» usa borrado lógico y {clase.modelo.__name__} no "
            "tiene `deleted_at`: usa borrado='fisico' o añade la papelera al modelo"
        )
    CLASES[clase.clave] = clase
    return clase


class PoliticaRetencion(Base):
    """Cuánto se guarda una clase de dato en este tenant."""

    __tablename__ = "politicas_retencion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    clase: Mapped[str] = mapped_column(String(60), nullable=False)
    # 0 = se guarda indefinidamente. Es el valor por defecto a propósito: una
    # política de retención mal puesta destruye datos, así que no hacer nada
    # tiene que ser lo que pase cuando nadie ha decidido.
    dias: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    motivo: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "clase", name="uq_politica_retencion"),
        Index("ix_politicas_retencion", "tenant_id", "activa"),
    )


class BloqueoLegal(Base):
    """Un litigio o una investigación que impide borrar.

    El ámbito va de lo general a lo concreto: sin `objeto` cubre **todo** lo de
    este servicio; con `objeto` cubre ese tipo; con `objeto` y `objeto_id`, ese
    registro. El caso real en un CRM es el concreto —la cuenta y el histórico de
    un cliente con el que hay un pleito—, pero el general hace falta para una
    inspección.

    No se borra al levantarlo: se marca. Un bloqueo tiene que poder demostrarse
    después, incluidas sus fechas de inicio y de fin.
    """

    __tablename__ = "bloqueos_legales"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    objeto: Mapped[str | None] = mapped_column(String(60), nullable=True)
    objeto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    motivo: Mapped[str] = mapped_column(Text, nullable=False)
    referencia: Mapped[str | None] = mapped_column(String(120), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    puesto_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    levantado_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    levantado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motivo_levantamiento: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_bloqueos_activos", "tenant_id", "activo", "objeto"),
        Index("ix_bloqueos_registro", "tenant_id", "objeto", "objeto_id"),
    )


# ── Consultas ─────────────────────────────────────────────────────────────


def bajo_bloqueo(
    db: Session,
    *,
    tenant_id: UUID,
    objeto: str | None = None,
    objeto_id: UUID | None = None,
) -> BloqueoLegal | None:
    """El bloqueo que cubre esto, si lo hay.

    Una sola consulta, no una por nivel de ámbito: con tres consultas por fila,
    una purga de cien mil registros hace trescientas mil consultas y deja de
    poder ejecutarse.
    """
    from sqlalchemy import or_

    consulta = select(BloqueoLegal).where(
        BloqueoLegal.tenant_id == tenant_id,
        BloqueoLegal.activo.is_(True),
        or_(
            # Cubre todo el servicio.
            BloqueoLegal.objeto.is_(None),
            # Cubre este tipo de objeto entero.
            (BloqueoLegal.objeto == objeto) & BloqueoLegal.objeto_id.is_(None),
            # Cubre este registro concreto.
            (BloqueoLegal.objeto == objeto) & (BloqueoLegal.objeto_id == objeto_id),
        ),
    )
    return db.execute(consulta.limit(1)).scalar_one_or_none()


def hay_algun_bloqueo(db: Session, tenant_id: UUID) -> bool:
    """Si el tenant tiene cualquier bloqueo activo.

    Lo consultan las purgas que no distinguen por registro. Ante uno activo se
    **abstienen enteras**: es preferible conservar de más a borrar la prueba
    equivocada, y afinar cuál de los cien mil registros cubre el bloqueo cuesta
    más que esperar a que se levante.
    """
    return (
        db.execute(
            select(BloqueoLegal.id)
            .where(BloqueoLegal.tenant_id == tenant_id, BloqueoLegal.activo.is_(True))
            .limit(1)
        ).first()
        is not None
    )


def dias_efectivos(db: Session, *, tenant_id: UUID, clase: str) -> int:
    """Días de retención de una clase: política del tenant, o el valor declarado."""
    declarada = CLASES.get(clase)
    por_defecto = declarada.dias_defecto if declarada else 0

    fila = db.execute(
        select(PoliticaRetencion).where(
            PoliticaRetencion.tenant_id == tenant_id,
            PoliticaRetencion.clase == clase,
            PoliticaRetencion.activa.is_(True),
        )
    ).scalar_one_or_none()
    return int(fila.dias) if fila is not None else int(por_defecto)


# ── Gestión de bloqueos ───────────────────────────────────────────────────


def bloquear(
    db: Session,
    *,
    tenant_id: UUID,
    motivo: str,
    objeto: str | None = None,
    objeto_id: UUID | None = None,
    referencia: str | None = None,
    por: UUID | None = None,
) -> BloqueoLegal:
    """Pone un bloqueo. Exige motivo escrito.

    El motivo no es burocracia: un bloqueo puede durar años y sobrevivir a quien
    lo puso, y «¿por qué no se puede borrar esto?» es una pregunta que alguien
    hará cuando esa persona ya no esté.
    """
    from crmcore.audit.chain import registrar

    if not (motivo or "").strip():
        raise ErrorValidacion(
            "Un bloqueo legal exige motivo escrito",
            error_code="retencion.bloqueo_sin_motivo",
        )
    if objeto_id is not None and not objeto:
        raise ErrorValidacion(
            "Un bloqueo sobre un registro concreto necesita también su tipo de objeto",
            error_code="retencion.bloqueo_sin_objeto",
        )

    bloqueo = BloqueoLegal(
        tenant_id=tenant_id,
        objeto=objeto,
        objeto_id=objeto_id,
        motivo=motivo.strip(),
        referencia=referencia,
        puesto_por=por,
    )
    db.add(bloqueo)
    db.flush()
    registrar(
        db,
        accion="bloqueo_legal.puesto",
        objeto=objeto or "tenant",
        objeto_id=objeto_id or tenant_id,
        datos={"bloqueo_id": str(bloqueo.id), "referencia": referencia},
        motivo=motivo.strip(),
        tenant_id=tenant_id,
    )
    logger.warning(
        "retencion.bloqueo_puesto",
        tenant=str(tenant_id),
        objeto=objeto or "(todo)",
        registro=str(objeto_id) if objeto_id else "(todos)",
    )
    return bloqueo


def levantar(
    db: Session, bloqueo_id: UUID, *, motivo: str, por: UUID | None = None
) -> BloqueoLegal:
    """Levanta un bloqueo. También exige motivo, y no se borra la fila.

    A partir de aquí lo que cubría vuelve a ser purgable, así que levantarlo es
    una decisión tan seria como ponerlo — y tiene que quedar igual de trazada.
    """
    from crmcore.audit.chain import registrar

    bloqueo = db.get(BloqueoLegal, bloqueo_id)
    if bloqueo is None:
        raise NoEncontrado("Ese bloqueo no existe", error_code="retencion.bloqueo_no_existe")
    if not bloqueo.activo:
        raise Conflicto(
            "Ese bloqueo ya está levantado", error_code="retencion.bloqueo_ya_levantado"
        )
    if not (motivo or "").strip():
        raise ErrorValidacion(
            "Levantar un bloqueo exige motivo escrito",
            error_code="retencion.levantamiento_sin_motivo",
        )

    bloqueo.activo = False
    bloqueo.levantado_at = datetime.now(timezone.utc)
    bloqueo.levantado_por = por
    bloqueo.motivo_levantamiento = motivo.strip()
    registrar(
        db,
        accion="bloqueo_legal.levantado",
        objeto=bloqueo.objeto or "tenant",
        objeto_id=bloqueo.objeto_id or bloqueo.tenant_id,
        datos={"bloqueo_id": str(bloqueo.id)},
        motivo=motivo.strip(),
        tenant_id=bloqueo.tenant_id,
    )
    return bloqueo


# ── Purga ─────────────────────────────────────────────────────────────────


@dataclass
class Informe:
    """Qué haría o qué hizo una purga."""

    clase: str
    dias: int
    candidatos: int = 0
    purgados: int = 0
    simulado: bool = True
    bloqueado_por: str | None = None
    corte: str | None = None

    def a_dict(self) -> dict[str, Any]:
        return {
            "clase": self.clase,
            "dias_retencion": self.dias,
            "candidatos": self.candidatos,
            "purgados": self.purgados,
            "simulado": self.simulado,
            "bloqueado_por": self.bloqueado_por,
            "corte": self.corte,
        }


def purgar(
    db: Session,
    *,
    tenant_id: UUID,
    clase: str,
    simular: bool = True,
    tope: int = 5_000,
    por: UUID | None = None,
) -> Informe:
    """Aplica la retención de una clase de dato.

    **Simula por defecto**, como la importación masiva y por el mismo motivo: lo
    que enseña cuántas filas se llevaría por delante hay que poder verlo antes,
    no después. Un `dias=0` no purga nada — es lo que pasa cuando nadie ha
    decidido, y no decidir no puede significar destruir.

    El `tope` acota cada pasada. Borrar cien mil filas en una transacción la
    mantiene abierta minutos, bloquea el vacuum y, si falla a la mitad, revierte
    entero. Con tope, la purga avanza en pasadas y cada una es firme.
    """
    from crmcore.audit.chain import registrar

    declarada = CLASES.get(clase)
    if declarada is None:
        raise ErrorValidacion(
            f"Clase de dato desconocida: «{clase}»",
            error_code="retencion.clase_desconocida",
            detalle={"declaradas": sorted(CLASES)},
        )

    dias = dias_efectivos(db, tenant_id=tenant_id, clase=clase)
    informe = Informe(clase=clase, dias=dias, simulado=simular)
    if dias <= 0:
        return informe

    bloqueo = bajo_bloqueo(db, tenant_id=tenant_id, objeto=declarada.modelo.__tablename__)
    if bloqueo is not None:
        # Se abstiene la purga ENTERA, no fila a fila. Afinar cuál de cien mil
        # registros cubre el bloqueo cuesta más que esperar a que se levante, y
        # equivocarse en esa criba borra justo lo que había que conservar.
        informe.bloqueado_por = str(bloqueo.id)
        logger.info(
            "retencion.purga_abstenida",
            clase=clase,
            tenant=str(tenant_id),
            bloqueo=str(bloqueo.id),
        )
        return informe

    corte = datetime.now(timezone.utc) - timedelta(days=dias)
    informe.corte = corte.isoformat()
    campo = getattr(declarada.modelo, declarada.campo_fecha)

    consulta = select(declarada.modelo).where(
        declarada.modelo.tenant_id == tenant_id,
        campo.is_not(None),
        campo < corte,
    )
    if declarada.solo_si_borrado:
        consulta = consulta.where(declarada.modelo.deleted_at.is_not(None))
    elif declarada.borrado == "logico" and hasattr(declarada.modelo, "deleted_at"):
        # Lo ya borrado no se vuelve a borrar: contaría dos veces y ensuciaría
        # el informe con filas sobre las que no se hace nada.
        consulta = consulta.where(declarada.modelo.deleted_at.is_(None))

    filas = db.execute(consulta.limit(tope)).scalars().all()
    informe.candidatos = len(filas)
    if simular or not filas:
        return informe

    ahora = datetime.now(timezone.utc)
    for fila in filas:
        if declarada.borrado == "fisico":
            db.delete(fila)
        else:
            fila.deleted_at = ahora
            if hasattr(fila, "deleted_by"):
                fila.deleted_by = por
    db.flush()
    informe.purgados = len(filas)

    # Se audita el HECHO, con el recuento: sin esto, un día faltan diez mil
    # filas y no hay forma de saber si las borró la retención o alguien.
    registrar(
        db,
        accion="retencion.purgada",
        objeto=declarada.modelo.__tablename__,
        objeto_id=tenant_id,
        datos={
            "clase": clase,
            "dias": dias,
            "purgados": len(filas),
            "corte": corte.isoformat(),
            "borrado": declarada.borrado,
        },
        motivo=f"Política de retención de «{clase}»: {dias} días",
        tenant_id=tenant_id,
    )
    logger.info(
        "retencion.purgada", clase=clase, tenant=str(tenant_id), purgados=len(filas), dias=dias
    )
    return informe


def purgar_todo(
    db: Session, *, tenant_id: UUID, simular: bool = True, por: UUID | None = None
) -> list[Informe]:
    """Aplica la retención de todas las clases declaradas en este servicio."""
    return [
        purgar(db, tenant_id=tenant_id, clase=clave, simular=simular, por=por)
        for clave in sorted(CLASES)
    ]
