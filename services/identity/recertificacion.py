"""Revisión periódica de accesos: la recertificación (CRM-07.03.02.15).

Pedido el 09-11-2026 dentro de «todo lo que hay en la aplicación, controlado
por el GRC»: medido ese día, **no había revisión periódica de accesos**. Los
roles se dan con un motivo y se quedan para siempre: la persona cambia de
puesto, el motivo deja de existir y el permiso sigue.

Una campaña pide a **cada responsable** que confirme o retire lo que tiene su
gente, con un plazo. Cuatro decisiones:

- **El responsable es el superior de la membresía**, que es quien sabe si esa
  persona sigue necesitando ese rol. Quien no tiene superior va a un revisor por
  defecto de la campaña —y si no lo hay, a quien la lanzó—: un acceso sin nadie
  que lo revise es exactamente el que se queda olvidado.
- **Retirar quita el acceso de verdad**: el rol sale de la membresía, se cierran
  sus sesiones en esta empresa —el token lleva los permisos dentro— y queda en la
  auditoría. Una revisión que sólo anota «retirar» y no retira es un formulario.
- **Lo no contestado a tiempo se marca y se avisa**: una tarea periódica lo
  marca vencido y le llega un aviso al responsable y a quien lanzó la campaña.
  Al cerrar, lo que sigue sin contestar se queda marcado o se retira, según el
  ajuste `recertificacion_al_cerrar` de la empresa.
- **El resultado es la evidencia del control de accesos del GRC.** Tenancy lo
  pide por HTTP (`/recertificacion/resumen`): ningún servicio lee el esquema
  de otro.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.audit.chain import registrar
from crmcore.db.base import Base
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado, Prohibido
from crmcore.fechas import hoy
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import Date, DateTime, Index, String, Text, func, select, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

# Los modelos de identidad y el organigrama se importan dentro de cada función:
# `modelos.py` importa este módulo al final para registrar sus tablas, y
# importarlos aquí arriba cerraría el círculo.

logger = get_logger(__name__)

PENDIENTE, CONFIRMADO, RETIRADO = "pendiente", "confirmado", "retirado"
DECISIONES = (CONFIRMADO, RETIRADO)
ABIERTA, CERRADA = "abierta", "cerrada"


class CampanaRecertificacion(Base):
    """Una ronda de revisión de accesos, con su plazo."""

    __tablename__ = "recert_campanas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    plazo_at: Mapped[date] = mapped_column(Date, nullable=False)
    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ABIERTA, server_default=text("'abierta'")
    )
    # A quién van las personas sin superior.
    revisor_por_defecto: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    creada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    cerrada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_recert_campanas", "tenant_id", "estado"),)


class RevisionAcceso(Base):
    """Un acceso concreto —un rol o un conjunto de permisos— de una persona."""

    __tablename__ = "recert_revisiones"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    campana_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    responsable_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # `rol` o `conjunto` (de permisos).
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    valor: Mapped[str] = mapped_column(String(120), nullable=False)
    decision: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PENDIENTE, server_default=text("'pendiente'")
    )
    comentario: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    decidido_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    decidido_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Se marca cuando vence el plazo sin contestar, y se queda marcada aunque
    # se conteste después: llegar tarde también es un dato del control.
    vencida_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_recert_revisiones_campana", "tenant_id", "campana_id"),
        Index("ix_recert_revisiones_responsable", "tenant_id", "responsable_id", "decision"),
    )


def _ajuste(clave: str, db: Session) -> Any:
    from crmcore.config import get_settings
    from crmcore.runtime.settings import efectivo

    return efectivo(clave, db, default=getattr(get_settings(), clave, None))


def _avisar(
    db: Session,
    *,
    tenant_id: UUID,
    usuarios: list[UUID],
    campana: CampanaRecertificacion,
    titulo: str,
    cuerpo: str,
    prioridad: str = "normal",
) -> None:
    from crmcore.datos.seguimiento import notificar

    if not usuarios:
        return
    notificar(
        db,
        tenant_id=tenant_id,
        tipo="recertificacion.pendiente",
        titulo=titulo,
        cuerpo=cuerpo,
        objeto_tipo="campana_recertificacion",
        objeto_id=campana.id,
        prioridad=prioridad,
        usuarios=sorted(set(usuarios), key=str),
        datos={"campana_id": str(campana.id)},
    )


# ── Lanzar ────────────────────────────────────────────────────────────────


def lanzar(
    uow: UnidadDeTrabajo,
    *,
    tenant_id: UUID,
    nombre: str,
    por: UUID,
    plazo_dias: int | None = None,
    revisor_por_defecto: UUID | None = None,
) -> CampanaRecertificacion:
    """Abre una campaña: una revisión por cada rol y conjunto de cada persona activa."""
    from services.identity.modelos import Membresia

    db = uow.db
    if not nombre.strip():
        raise ErrorValidacion("La campaña necesita un nombre", error_code="recert.sin_nombre")
    dias = int(plazo_dias or _ajuste("recertificacion_plazo_dias", db) or 14)
    if dias < 1:
        raise ErrorValidacion("El plazo es de un día o más", error_code="recert.plazo_invalido")
    campana = CampanaRecertificacion(
        tenant_id=tenant_id,
        nombre=nombre.strip(),
        plazo_at=hoy(db) + timedelta(days=dias),
        revisor_por_defecto=revisor_por_defecto,
        creada_por=por,
    )
    db.add(campana)
    db.flush()

    responsables: set[UUID] = set()
    revisiones = 0
    for m in db.execute(
        select(Membresia).where(Membresia.tenant_id == tenant_id, Membresia.activa.is_(True))
    ).scalars():
        responsable = m.superior_id or revisor_por_defecto or por
        accesos = [("rol", r) for r in (m.roles or [])] + [
            ("conjunto", c) for c in (m.conjuntos_permisos or [])
        ]
        for tipo, valor in accesos:
            db.add(
                RevisionAcceso(
                    tenant_id=tenant_id,
                    campana_id=campana.id,
                    responsable_id=responsable,
                    usuario_id=m.usuario_id,
                    tipo=tipo,
                    valor=str(valor),
                )
            )
            revisiones += 1
        if accesos:
            responsables.add(responsable)
    if not revisiones:
        raise Conflicto(
            "No hay ningún acceso que revisar: ninguna persona activa tiene roles",
            error_code="recert.nada_que_revisar",
        )
    registrar(
        db,
        accion="recertificacion.lanzada",
        objeto="campana_recertificacion",
        objeto_id=campana.id,
        datos={"revisiones": revisiones, "responsables": len(responsables), "plazo_dias": dias},
        tenant_id=tenant_id,
    )
    _avisar(
        db,
        tenant_id=tenant_id,
        usuarios=list(responsables),
        campana=campana,
        titulo=f"Revisión de accesos: «{campana.nombre}»",
        cuerpo=(
            f"Confirma o retira los accesos de tu gente antes del "
            f"{campana.plazo_at.isoformat()}. Está en tu bandeja de aprobaciones."
        ),
    )
    db.flush()
    logger.info("recert.lanzada", campana=str(campana.id), revisiones=revisiones)
    return campana


# ── Contestar ─────────────────────────────────────────────────────────────


def _revocar_sesiones(db: Session, usuario_id: UUID, tenant_id: UUID) -> int:
    """Cierra sus sesiones en esta empresa: el token lleva los permisos dentro."""
    from services.identity.modelos import Sesion

    ahora = datetime.now(timezone.utc)
    sesiones = db.execute(
        select(Sesion).where(
            Sesion.usuario_id == usuario_id,
            Sesion.tenant_id == tenant_id,
            Sesion.revocada_at.is_(None),
        )
    ).scalars()
    cuantas = 0
    for s_ in sesiones:
        s_.revocada_at = ahora
        s_.motivo_revocacion = "recertificacion"
        cuantas += 1
    return cuantas


def _retirar(uow: UnidadDeTrabajo, revision: RevisionAcceso, *, via: str) -> bool:
    """Quita el acceso de la membresía. False si ya no lo tenía."""
    from services.identity import organigrama
    from services.identity.modelos import Membresia

    db = uow.db
    m = db.execute(
        select(Membresia).where(
            Membresia.tenant_id == revision.tenant_id,
            Membresia.usuario_id == revision.usuario_id,
        )
    ).scalar_one_or_none()
    if m is None:
        return False
    campo = "roles" if revision.tipo == "rol" else "conjuntos_permisos"
    actuales = list(getattr(m, campo) or [])
    if revision.valor not in actuales:
        return False
    setattr(m, campo, [v for v in actuales if v != revision.valor])
    sesiones = _revocar_sesiones(db, revision.usuario_id, revision.tenant_id)
    registrar(
        db,
        accion="recertificacion.retirada",
        objeto="usuario",
        objeto_id=revision.usuario_id,
        datos={
            "tipo": revision.tipo,
            "valor": revision.valor,
            "campana_id": str(revision.campana_id),
            "sesiones_cerradas": sesiones,
            "via": via,
        },
        tenant_id=revision.tenant_id,
    )
    organigrama.publicar(uow, revision.tenant_id, revision.usuario_id)
    return True


def decidir(
    uow: UnidadDeTrabajo,
    *,
    tenant_id: UUID,
    revision_id: UUID,
    decision: str,
    por: UUID,
    comentario: str = "",
) -> RevisionAcceso:
    """El responsable confirma o retira un acceso. Retirar lo quita en el momento."""
    db = uow.db
    if decision not in DECISIONES:
        raise ErrorValidacion(
            "La decisión es «confirmado» o «retirado»", error_code="recert.decision_invalida"
        )
    revision = db.execute(
        select(RevisionAcceso).where(
            RevisionAcceso.tenant_id == tenant_id, RevisionAcceso.id == revision_id
        )
    ).scalar_one_or_none()
    if revision is None:
        raise NoEncontrado("Esa revisión no existe", error_code="recert.revision_no_existe")
    # Sólo el responsable: si cualquiera con permisos pudiera contestar, la
    # campaña acabaría contestada por quien la lanzó, y eso no es revisar.
    if revision.responsable_id != por:
        raise Prohibido("Esta revisión es de otro responsable", error_code="recert.no_es_tuya")
    campana = db.get(CampanaRecertificacion, revision.campana_id)
    if campana is None or campana.estado != ABIERTA:
        raise Conflicto("La campaña ya está cerrada", error_code="recert.campana_cerrada")
    if revision.decision != PENDIENTE:
        raise Conflicto("Esta revisión ya está contestada", error_code="recert.ya_contestada")
    if decision == RETIRADO and not comentario.strip():
        raise ErrorValidacion(
            "Retirar un acceso exige decir por qué", error_code="recert.retirar_sin_motivo"
        )
    revision.decision = decision
    revision.comentario = comentario.strip()
    revision.decidido_por = por
    revision.decidido_at = datetime.now(timezone.utc)
    if decision == RETIRADO:
        _retirar(uow, revision, via="responsable")
    else:
        registrar(
            db,
            accion="recertificacion.confirmada",
            objeto="usuario",
            objeto_id=revision.usuario_id,
            datos={"tipo": revision.tipo, "valor": revision.valor, "campana_id": str(campana.id)},
            tenant_id=tenant_id,
        )
    db.flush()
    return revision


# ── Plazos ────────────────────────────────────────────────────────────────


def marcar_vencidas(db: Session, tenant_id: UUID) -> dict[str, int]:
    """Marca lo no contestado de las campañas fuera de plazo y avisa.

    Al responsable, con prioridad alta, y a quien lanzó la campaña: el plazo
    vencido es suyo también. Se avisa una vez, al marcar; la marca se queda.
    """
    dia = hoy(db)
    ahora = datetime.now(timezone.utc)
    marcadas = avisos = 0
    for campana in db.execute(
        select(CampanaRecertificacion).where(
            CampanaRecertificacion.tenant_id == tenant_id,
            CampanaRecertificacion.estado == ABIERTA,
            CampanaRecertificacion.plazo_at < dia,
        )
    ).scalars():
        pendientes = list(
            db.execute(
                select(RevisionAcceso).where(
                    RevisionAcceso.tenant_id == tenant_id,
                    RevisionAcceso.campana_id == campana.id,
                    RevisionAcceso.decision == PENDIENTE,
                    RevisionAcceso.vencida_at.is_(None),
                )
            ).scalars()
        )
        if not pendientes:
            continue
        por_responsable: dict[UUID, int] = {}
        for r in pendientes:
            r.vencida_at = ahora
            por_responsable[r.responsable_id] = por_responsable.get(r.responsable_id, 0) + 1
        marcadas += len(pendientes)
        for responsable, cuantas in por_responsable.items():
            _avisar(
                db,
                tenant_id=tenant_id,
                usuarios=[responsable],
                campana=campana,
                titulo=f"Revisión de accesos fuera de plazo: «{campana.nombre}»",
                cuerpo=(
                    f"Tienes {cuantas} accesos sin contestar y el plazo acabó el "
                    f"{campana.plazo_at.isoformat()}."
                ),
                prioridad="alta",
            )
            avisos += 1
        if campana.creada_por:
            _avisar(
                db,
                tenant_id=tenant_id,
                usuarios=[campana.creada_por],
                campana=campana,
                titulo=f"Campaña «{campana.nombre}» fuera de plazo",
                cuerpo=f"{len(pendientes)} revisiones sin contestar.",
                prioridad="alta",
            )
            avisos += 1
        registrar(
            db,
            accion="recertificacion.vencida",
            objeto="campana_recertificacion",
            objeto_id=campana.id,
            datos={"vencidas": len(pendientes)},
            tenant_id=tenant_id,
        )
    db.flush()
    return {"marcadas": marcadas, "avisos": avisos}


def tenants_con_campanas_abiertas(db: Session) -> list[UUID]:
    return list(
        db.execute(
            select(CampanaRecertificacion.tenant_id)
            .where(CampanaRecertificacion.estado == ABIERTA)
            .distinct()
        ).scalars()
    )


def cerrar(uow: UnidadDeTrabajo, *, tenant_id: UUID, campana_id: UUID, por: UUID) -> dict[str, Any]:
    """Cierra la campaña. Lo que nadie contestó se marca o se retira, según el ajuste."""
    db = uow.db
    campana = _campana(db, tenant_id, campana_id)
    if campana.estado != ABIERTA:
        raise Conflicto("La campaña ya está cerrada", error_code="recert.campana_cerrada")
    marcar_vencidas(db, tenant_id)
    politica = str(_ajuste("recertificacion_al_cerrar", db) or "marcar")
    ahora = datetime.now(timezone.utc)
    retiradas = 0
    for r in db.execute(
        select(RevisionAcceso).where(
            RevisionAcceso.tenant_id == tenant_id,
            RevisionAcceso.campana_id == campana.id,
            RevisionAcceso.decision == PENDIENTE,
        )
    ).scalars():
        r.vencida_at = r.vencida_at or ahora
        if politica == "retirar":
            # Lo que nadie confirmó no se queda por inercia.
            r.decision = RETIRADO
            r.comentario = "Retirado al cerrar la campaña: nadie lo confirmó a tiempo."
            r.decidido_at = ahora
            if _retirar(uow, r, via="cierre"):
                retiradas += 1
    campana.estado = CERRADA
    campana.cerrada_at = ahora
    registrar(
        db,
        accion="recertificacion.cerrada",
        objeto="campana_recertificacion",
        objeto_id=campana.id,
        datos={"politica": politica, "retiradas_al_cerrar": retiradas},
        tenant_id=tenant_id,
    )
    db.flush()
    return {**resumen_de(db, campana), "politica": politica, "retiradas_al_cerrar": retiradas}


# ── Leer ──────────────────────────────────────────────────────────────────


def _campana(db: Session, tenant_id: UUID, campana_id: UUID) -> CampanaRecertificacion:
    campana = db.execute(
        select(CampanaRecertificacion).where(
            CampanaRecertificacion.tenant_id == tenant_id,
            CampanaRecertificacion.id == campana_id,
        )
    ).scalar_one_or_none()
    if campana is None:
        raise NoEncontrado("Esa campaña no existe", error_code="recert.campana_no_existe")
    return campana


def resumen_de(db: Session, campana: CampanaRecertificacion) -> dict[str, Any]:
    filas = list(
        db.execute(
            select(RevisionAcceso).where(
                RevisionAcceso.tenant_id == campana.tenant_id,
                RevisionAcceso.campana_id == campana.id,
            )
        ).scalars()
    )
    return {
        "id": str(campana.id),
        "nombre": campana.nombre,
        "estado": campana.estado,
        "plazo_at": campana.plazo_at.isoformat(),
        "fuera_de_plazo": campana.estado == ABIERTA and campana.plazo_at < hoy(db),
        "created_at": campana.created_at.isoformat() if campana.created_at else None,
        "cerrada_at": campana.cerrada_at.isoformat() if campana.cerrada_at else None,
        "creada_por": str(campana.creada_por) if campana.creada_por else None,
        "total": len(filas),
        "confirmados": sum(1 for f in filas if f.decision == CONFIRMADO),
        "retirados": sum(1 for f in filas if f.decision == RETIRADO),
        "pendientes": sum(1 for f in filas if f.decision == PENDIENTE),
        "vencidas": sum(1 for f in filas if f.vencida_at is not None),
        "responsables": len({f.responsable_id for f in filas}),
    }


def campanas(db: Session, tenant_id: UUID) -> list[dict[str, Any]]:
    return [
        resumen_de(db, c)
        for c in db.execute(
            select(CampanaRecertificacion)
            .where(CampanaRecertificacion.tenant_id == tenant_id)
            .order_by(CampanaRecertificacion.created_at.desc())
        ).scalars()
    ]


def _nombres(db: Session, ids: set[UUID]) -> dict[UUID, str]:
    from services.identity.modelos import Usuario

    if not ids:
        return {}
    return {
        u.id: u.nombre or u.email
        for u in db.execute(select(Usuario).where(Usuario.id.in_(ids))).scalars()
    }


def _revision(r: RevisionAcceso, nombres: dict[UUID, str]) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "campana_id": str(r.campana_id),
        "usuario_id": str(r.usuario_id),
        "usuario": nombres.get(r.usuario_id, ""),
        "responsable_id": str(r.responsable_id),
        "responsable": nombres.get(r.responsable_id, ""),
        "tipo": r.tipo,
        "valor": r.valor,
        "decision": r.decision,
        "comentario": r.comentario,
        "decidido_at": r.decidido_at.isoformat() if r.decidido_at else None,
        "vencida": r.vencida_at is not None,
    }


def detalle(db: Session, tenant_id: UUID, campana_id: UUID) -> dict[str, Any]:
    campana = _campana(db, tenant_id, campana_id)
    filas = list(
        db.execute(
            select(RevisionAcceso)
            .where(RevisionAcceso.tenant_id == tenant_id, RevisionAcceso.campana_id == campana.id)
            .order_by(RevisionAcceso.responsable_id, RevisionAcceso.usuario_id)
        ).scalars()
    )
    nombres = _nombres(db, {f.usuario_id for f in filas} | {f.responsable_id for f in filas})
    return {**resumen_de(db, campana), "revisiones": [_revision(f, nombres) for f in filas]}


def mias(db: Session, tenant_id: UUID, responsable_id: UUID) -> list[dict[str, Any]]:
    """Lo que me toca revisar en las campañas abiertas, agrupado por campaña."""
    abiertas = {
        c.id: c
        for c in db.execute(
            select(CampanaRecertificacion).where(
                CampanaRecertificacion.tenant_id == tenant_id,
                CampanaRecertificacion.estado == ABIERTA,
            )
        ).scalars()
    }
    if not abiertas:
        return []
    filas = list(
        db.execute(
            select(RevisionAcceso)
            .where(
                RevisionAcceso.tenant_id == tenant_id,
                RevisionAcceso.responsable_id == responsable_id,
                RevisionAcceso.campana_id.in_(list(abiertas)),
            )
            .order_by(RevisionAcceso.usuario_id, RevisionAcceso.valor)
        ).scalars()
    )
    nombres = _nombres(db, {f.usuario_id for f in filas} | {responsable_id})
    salida = []
    for cid, campana in abiertas.items():
        suyas = [f for f in filas if f.campana_id == cid]
        if not suyas:
            continue
        salida.append(
            {
                "campana_id": str(cid),
                "nombre": campana.nombre,
                "plazo_at": campana.plazo_at.isoformat(),
                "fuera_de_plazo": campana.plazo_at < hoy(db),
                "revisiones": [_revision(f, nombres) for f in suyas],
            }
        )
    return salida


def resumen(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Lo que el control de accesos del GRC lee como evidencia."""
    todas = campanas(db, tenant_id)
    cerradas = [c for c in todas if c["estado"] == CERRADA]
    cerradas.sort(key=lambda c: c["cerrada_at"] or "", reverse=True)
    return {
        "ultima_cerrada": cerradas[0] if cerradas else None,
        "cerradas": cerradas,
        "en_curso": [c for c in todas if c["estado"] == ABIERTA],
    }
