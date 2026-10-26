"""La cola de posibles duplicados, para decidirlos de uno en uno (CRM-01.01.03.03).

Buscar duplicados ya se hacía, pero **solo al crear**: se escribía un nombre y
el sistema avisaba de a qué se parecía. Eso protege lo que entra desde hoy y no
dice nada de las ocho mil fichas que ya están dentro — que es donde está el
problema, porque los duplicados no se crean de uno en uno: llegan de golpe con
una importación o con la integración del ERP.

Lo que hace esto es lo contrario: recorre el maestro, propone parejas **con su
probabilidad y con el porqué**, y deja que alguien decida. Sin el porqué no hay
decisión posible: «mismo NIF» y «el nombre se parece» son dos cosas muy
distintas, y una lista que solo dice «87 %» obliga a abrir las dos fichas para
saber qué se está comparando.

**Fusionar no se hace solo, nunca.** Aunque la señal sea concluyente. Una fusión
mal hecha mezcla el histórico de dos clientes y deshacerla es un trabajo manual:
el coste de equivocarse no es simétrico, así que decide una persona.

**Y «no es un duplicado» se recuerda.** Si no, el siguiente barrido vuelve a
proponer la misma pareja y quien la descartó la descarta otra vez. Una cola que
reaparece entera es una cola que se deja de mirar.

El que puntúa es `duplicados.buscar_cuentas_duplicadas`, el mismo que protege el
alta, y por eso: dos formas de decidir si algo es un duplicado acaban
discrepando, y entonces el alta deja pasar lo que la cola marca — o al revés.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from sqlalchemy import Boolean, DateTime, Float, Index, String, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

# Qué se puede decidir. `no_es_duplicado` no es «descartar»: descartar es «ahora
# no me ocupo», y no ser un duplicado es un hecho sobre esa pareja que hay que
# recordar para no volver a preguntarlo.
DECISIONES = ("fusionar", "no_es_duplicado", "descartar")


# Por debajo de esto no se propone nada. No es un umbral escrito a mano: se lee
# de los ajustes, y este es solo el valor con el que se estrena.
def _duplicados_umbral_defecto() -> float:
    """Antes `_duplicados_umbral_defecto() = 0.72`.

    Era una constante de módulo. Sale del `.env`, que es donde una instalación
    puede afinarla sin tocar código.
    """
    from crmcore.config import get_settings

    return get_settings().duplicados_umbral_defecto


class CandidatoDuplicado(Base, TimestampMixin):
    """Una pareja que podría ser la misma ficha, y qué se decidió."""

    __tablename__ = "candidatos_duplicado"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    objeto: Mapped[str] = mapped_column(String(30), nullable=False, default="cuenta")
    # Ordenados a<b siempre, y con restricción única: si no, la misma pareja
    # entra dos veces —una por cada lado— y la cola dobla de tamaño con el
    # mismo trabajo dentro.
    a_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    b_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    a_nombre: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    b_nombre: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    probabilidad: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Qué ha coincidido: `nif`, `dominio`, `nombre`, `email`. Es lo que permite
    # decidir sin abrir las dos fichas.
    senales: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    concluyente: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Vacío mientras está pendiente.
    decision: Mapped[str] = mapped_column(
        String(20), nullable=False, default="", info={"opciones": DECISIONES}
    )
    decidido_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    decidido_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    nota: Mapped[str] = mapped_column(String(1000), nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("tenant_id", "objeto", "a_id", "b_id", name="uq_candidato_duplicado"),
        Index("ix_candidatos_duplicado", "tenant_id", "objeto", "decision"),
    )


def _umbral(db: Session) -> float:
    from crmcore.runtime import settings as rt

    valor = rt.efectivo("duplicados_umbral_propuesta", db)
    try:
        return float(valor) if valor is not None else _duplicados_umbral_defecto()
    except (TypeError, ValueError):
        return _duplicados_umbral_defecto()


def barrido(uow: UnidadDeTrabajo, *, limite: int = 500) -> dict[str, Any]:
    """Recorre las cuentas y propone las parejas que se parecen.

    Repetible: la pareja ya propuesta se actualiza en vez de duplicarse, y la
    que alguien marcó como «no es un duplicado» no se vuelve a proponer.
    """
    from services.party import duplicados
    from services.party.modelos import Cuenta

    umbral = _umbral(uow.db)
    cuentas = list(
        uow.db.execute(
            select(Cuenta)
            .where(Cuenta.deleted_at.is_(None), Cuenta.fusionada_en_id.is_(None))
            .order_by(Cuenta.created_at)
            .limit(limite)
        )
        .scalars()
        .all()
    )
    # Lo ya decidido, para no volver a proponerlo. Se lee entero de una vez: una
    # consulta por pareja serían miles en un barrido.
    decididos = {
        (f.a_id, f.b_id): f
        for f in uow.db.execute(
            select(CandidatoDuplicado).where(CandidatoDuplicado.objeto == "cuenta")
        )
        .scalars()
        .all()
    }

    propuestas = 0
    for cuenta in cuentas:
        candidatos = duplicados.buscar_cuentas_duplicadas(
            uow.db,
            tenant_id=uow.tenant_id,
            nombre=cuenta.nombre,
            email=cuenta.email,
            web=cuenta.web,
            excluir_id=cuenta.id,
        )
        for candidato in candidatos:
            if candidato.similitud < umbral:
                continue
            a_id, b_id = sorted((cuenta.id, candidato.id), key=str)
            existente = decididos.get((a_id, b_id))
            if existente is not None:
                # Lo pendiente se actualiza —la probabilidad cambia cuando las
                # fichas cambian—; lo decidido se deja en paz.
                if not existente.decision:
                    existente.probabilidad = candidato.similitud
                    existente.senales = list(candidato.senales)
                    existente.concluyente = candidato.concluyente
                continue
            nombres = {cuenta.id: cuenta.nombre, candidato.id: candidato.nombre}
            fila = CandidatoDuplicado(
                tenant_id=uow.tenant_id,
                objeto="cuenta",
                a_id=a_id,
                b_id=b_id,
                a_nombre=nombres.get(a_id, ""),
                b_nombre=nombres.get(b_id, ""),
                probabilidad=candidato.similitud,
                senales=list(candidato.senales),
                concluyente=candidato.concluyente,
            )
            uow.db.add(fila)
            decididos[(a_id, b_id)] = fila
            propuestas += 1

    uow.db.flush()
    return {"revisadas": len(cuentas), "propuestas": propuestas, "umbral": umbral}


def cola(db: Session, *, pendientes: bool = True, limite: int = 100) -> list[dict[str, Any]]:
    """Lo que hay por decidir, lo más probable primero."""
    consulta = select(CandidatoDuplicado).where(CandidatoDuplicado.objeto == "cuenta")
    if pendientes:
        consulta = consulta.where(CandidatoDuplicado.decision == "")
    filas = (
        db.execute(consulta.order_by(CandidatoDuplicado.probabilidad.desc()).limit(limite))
        .scalars()
        .all()
    )
    return [_a_dict(f) for f in filas]


def decidir(
    uow: UnidadDeTrabajo,
    *,
    candidato_id: UUID,
    decision: str,
    por: UUID | None,
    superviviente_id: UUID | None = None,
    nota: str = "",
) -> dict[str, Any]:
    """Resuelve una pareja: fusionarla, decir que no lo es, o dejarla.

    Al fusionar hay que decir **cuál sobrevive**, y no se elige solo: la que se
    queda es la que conserva el identificador que usan los sistemas de fuera, y
    eso no lo sabe un algoritmo.
    """
    if decision not in DECISIONES:
        raise ErrorValidacion(
            f"«{decision}» no es una decisión reconocida",
            error_code="duplicados.decision_invalida",
            detalle={"admitidas": list(DECISIONES)},
        )
    fila = uow.db.get(CandidatoDuplicado, candidato_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado(
            "No hay ningún candidato con ese identificador",
            error_code="duplicados.candidato_no_encontrado",
        )

    if decision == "fusionar":
        if superviviente_id not in (fila.a_id, fila.b_id):
            raise ErrorValidacion(
                "Hay que decir cuál de las dos fichas se queda",
                error_code="duplicados.falta_superviviente",
                detalle={"opciones": [str(fila.a_id), str(fila.b_id)]},
            )
        from services.party import duplicados

        absorbido = fila.b_id if superviviente_id == fila.a_id else fila.a_id
        duplicados.fusionar_cuentas(
            uow.db,
            superviviente_id=superviviente_id,
            absorbida_id=absorbido,
            motivo=nota or "Duplicado confirmado desde la cola de revisión",
            por=por,
        )

    fila.decision = decision
    fila.decidido_por = por
    fila.decidido_at = datetime.now(timezone.utc)
    fila.nota = nota[:1000]
    uow.db.flush()
    return _a_dict(fila)


def _a_dict(f: CandidatoDuplicado) -> dict[str, Any]:
    return {
        "id": str(f.id),
        "objeto": f.objeto,
        "a_id": str(f.a_id),
        "b_id": str(f.b_id),
        "a_nombre": f.a_nombre,
        "b_nombre": f.b_nombre,
        # En porcentaje para la pantalla: «0.873» obliga a traducirlo mentalmente
        # y «87 %» se lee de un vistazo.
        "probabilidad": round(f.probabilidad * 100),
        "senales": list(f.senales or []),
        "concluyente": f.concluyente,
        "decision": f.decision,
        "decidido_por": str(f.decidido_por) if f.decidido_por else None,
        "decidido_at": f.decidido_at.isoformat() if f.decidido_at else None,
        "nota": f.nota,
    }
