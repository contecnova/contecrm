"""Aprobaciones: quién decide, con qué quórum y qué pasa si no decide nadie
(CRM-00.03.05.06 a .13).

Una aprobación no es una tarea con un botón. Es una pregunta con cuatro partes
que se equivocan por separado:

  * **a quién le toca** — y cuando el sistema se lo inventa, alguien firma lo que
    no le correspondía y eso sale en una auditoría, no en una pantalla;
  * **cuántos hacen falta** — «que lo vean los tres» y «que lo vea cualquiera de
    los tres» son políticas distintas y ninguna es la de por defecto;
  * **qué pasa si nadie contesta** — que es lo que ocurre de verdad la mayoría de
    las veces;
  * **qué pasa si lo aprobado cambia después** — un descuento del 10 % aprobado
    que alguien sube al 30 % está aprobado por el papel y no por la persona.

Todo lo que decide se guarda como **dato del tenant**, no como código: la
política de aprobaciones cambia cada trimestre y un `if` en el producto la
convierte en una versión nueva por cliente.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoAutenticado, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
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
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from services.orchestrator import organizacion as org

logger = get_logger(__name__)

# Cómo se cuenta el voto de una etapa (CRM-00.03.05.06).
QUORUMS = ("todos", "mayoria", "cualquiera", "n_de_m")
# De dónde sale el aprobador (CRM-00.03.05.07).
ORIGENES = ("jerarquia", "rol", "usuario", "campo", "unidad")
DECISIONES = ("aprobar", "rechazar", "pedir_cambios")


class SolicitudAprobacion(Base, TimestampMixin):
    """Una cosa puesta a aprobar."""

    __tablename__ = "solicitudes_aprobacion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    politica: Mapped[str] = mapped_column(String(80), nullable=False)
    # Sobre qué. Identificadores opacos: el descuento vive en `sales` y el gasto
    # en otro sitio, y ningún servicio lee el esquema de otro.
    objeto: Mapped[str] = mapped_column(String(40), nullable=False)
    objeto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    titulo: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    # Lo que hace falta para decidir sin abrir otra pantalla (CRM-00.03.05.13).
    contexto: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    solicitante_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # pendiente | aprobada | rechazada | cambios_pedidos | cancelada | caducada
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente", index=True)
    etapa_actual: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resuelta_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Huella de LO QUE SE APROBÓ (CRM-00.03.05.10). Si lo aprobado cambia, la
    # huella no coincide y hay que volver a aprobar. Sin ella, un descuento del
    # 10 % aprobado y subido después al 30 % queda aprobado por el papel.
    huella: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    campos_vigilados: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    reaprobaciones: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Se aprobó sola por estar bajo umbral (CRM-00.03.05.11).
    automatica: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # A quién le habría tocado si no hubiera sido automática. Se guarda porque
    # sin ese nombre, «aprobación automática» es una decisión sin responsable, y
    # la primera pregunta de cualquier auditoría es de quién era la firma.
    habria_aprobado: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    motivo_automatica: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # La instancia de proceso que la pidió, si vino de un flujo.
    instancia_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (
        Index("ix_aprobaciones_pendientes", "tenant_id", "estado", "created_at"),
        Index("ix_aprobaciones_objeto", "tenant_id", "objeto", "objeto_id"),
    )


class EtapaAprobacion(Base):
    """Un escalón de la cadena, con su quórum y sus aprobadores."""

    __tablename__ = "etapas_aprobacion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    solicitud_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("solicitudes_aprobacion.id", ondelete="CASCADE"),
        nullable=False,
    )
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    quorum: Mapped[str] = mapped_column(
        String(20), nullable=False, default="todos", info={"opciones": QUORUMS}
    )
    # Para `n_de_m`: cuántos hacen falta.
    minimo: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Los aprobadores ya RESUELTOS, congelados al abrir la etapa. Se congelan a
    # propósito: si se recalcularan a cada consulta, una reorganización a mitad
    # de una aprobación cambiaría a quién le tocaba mientras está decidiendo.
    aprobadores: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # pendiente | aprobada | rechazada | saltada
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    # Qué vuelta se está votando. Sube con cada reaprobación, y es lo que impide
    # que los votos de la versión anterior cuenten para la nueva: sin esto, un
    # descuento reabierto se aprobaría solo con las firmas de lo que ya no es.
    vuelta: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    abierta_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cerrada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Escalado (CRM-00.03.05.09).
    vence_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    avisar_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    avisada: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    escalada: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("solicitud_id", "orden", name="uq_etapa_orden"),
        Index("ix_etapas_vencimiento", "tenant_id", "estado", "vence_at"),
    )


class DecisionAprobacion(Base):
    """Lo que dijo una persona. Append-only: nada se edita ni se borra."""

    __tablename__ = "decisiones_aprobacion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    etapa_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("etapas_aprobacion.id", ondelete="CASCADE"), nullable=False
    )
    # A quién le tocaba.
    titular_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # Quién firmó de verdad. Con delegación, no es el mismo — y la diferencia es
    # justo lo que no se puede perder (CRM-00.03.05.08).
    decidio_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False, info={"opciones": DECISIONES})
    comentario: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # ui | correo | movil | api | automatica
    via: Mapped[str] = mapped_column(String(20), nullable=False, default="ui")
    decidida_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # La vuelta en la que se emitió. Los votos viejos se conservan —son la
    # prueba de que aquella versión sí se aprobó— y dejan de contar.
    vuelta: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("etapa_id", "titular_id", "vuelta", name="uq_decision_titular"),
        Index("ix_decisiones_etapa", "tenant_id", "etapa_id"),
    )


class Delegacion(Base, TimestampMixin):
    """Quién decide por quién mientras no está (CRM-00.03.05.08)."""

    __tablename__ = "delegaciones"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    titular_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    suplente_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # Con vigencia obligatoria: una delegación sin fecha de fin es una cesión
    # permanente que nadie recuerda haber hecho, y en la práctica se queda.
    desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hasta: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    motivo: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    # Acotable a una política: delegar las vacaciones no es delegar la firma de
    # los contratos.
    politica: Mapped[str | None] = mapped_column(String(80), nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (Index("ix_delegaciones_vigentes", "tenant_id", "titular_id", "activa"),)


class EnlaceDecision(Base):
    """Enlace firmado de un solo uso para decidir desde el correo
    (CRM-00.03.05.12).

    Se guarda el **hash** del token y no el token: quien lea esta tabla —una
    copia de seguridad, un volcado de soporte— no puede aprobar en nombre de
    nadie.
    """

    __tablename__ = "enlaces_decision"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    etapa_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    titular_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    hash_token: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, info={"secreto": True}
    )
    caduca_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ── Utilidades ────────────────────────────────────────────────────────────


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _con_tz(v: datetime | None) -> datetime | None:
    if v is None:
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def _hash(valor: str) -> str:
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


def huella_de(datos: dict[str, Any], campos: list[str]) -> str:
    """Huella de lo que se aprueba.

    Solo de los **campos vigilados**, no del registro entero: si entrara todo, un
    cambio en la descripción obligaría a volver a aprobar un importe que nadie ha
    tocado, y a la tercera vez la gente aprueba sin mirar — que es peor que no
    tener reaprobación.
    """
    recorte = {c: datos.get(c) for c in sorted(campos)}
    return _hash(json.dumps(recorte, sort_keys=True, default=str))


def _num(valor: Any) -> Decimal:
    try:
        return Decimal(str(valor))
    except Exception:
        return Decimal(0)


# ── Resolver el aprobador (CRM-00.03.05.07) ───────────────────────────────


def resolver_aprobadores(
    db: Session, tenant_id: UUID, definicion: dict[str, Any], contexto: dict[str, Any]
) -> list[UUID]:
    """Quién tiene que decidir en esta etapa.

    Cinco orígenes, y ninguno por defecto: `jerarquia` (el superior de quien
    pide, subiendo los escalones que diga), `rol`, `usuario`, `campo` (el
    identificador que venga en el contexto, p. ej. el dueño de la cuenta) y
    `unidad` (quien tenga el rol dentro de la unidad del solicitante).

    **Una etapa sin aprobadores no se salta.** Se levanta un error: saltarla haría
    que una cadena mal configurada aprobara sola y en silencio, que es el fallo
    que nadie detecta hasta que ya se ha aprobado un año de gasto.
    """
    origen = str(definicion.get("origen") or "")
    if origen not in ORIGENES:
        raise ErrorValidacion(
            f"Origen de aprobador «{origen}» no válido.",
            error_code="aprobacion.origen_no_valido",
            detalle={"validos": list(ORIGENES)},
        )

    solicitante = contexto.get("_solicitante_id")
    salida: list[UUID] = []

    if origen == "usuario":
        salida = [UUID(str(u)) for u in (definicion.get("usuarios") or [])]

    elif origen == "jerarquia":
        if not solicitante:
            raise ErrorValidacion(
                "No se sabe quién pide, y sin eso no hay jerarquía que subir.",
                error_code="aprobacion.sin_solicitante",
            )
        escalones = int(definicion.get("escalones", 1))
        cadena = org.cadena_de_mando(db, tenant_id, UUID(str(solicitante)))
        salida = cadena[:escalones]

    elif origen == "rol":
        salida = org.con_rol(db, tenant_id, str(definicion.get("rol") or ""))

    elif origen == "unidad":
        if not solicitante:
            raise ErrorValidacion(
                "No se sabe quién pide, y sin eso no hay unidad.",
                error_code="aprobacion.sin_solicitante",
            )
        quien = org.persona(db, tenant_id, UUID(str(solicitante)))
        salida = org.con_rol(
            db, tenant_id, str(definicion.get("rol") or ""), unidad_id=quien.unidad_id
        )

    elif origen == "campo":
        valor = contexto.get(str(definicion.get("campo") or ""))
        if valor:
            salida = [UUID(str(valor))]

    # Quien pide no se aprueba a sí mismo aunque la regla le señale: es la
    # separación de funciones más básica y la que más veces se cuela, porque el
    # responsable de zona suele ser también el dueño de la cuenta.
    if solicitante and definicion.get("permitir_autoaprobacion", False) is False:
        salida = [u for u in salida if str(u) != str(solicitante)]

    unicos = list(dict.fromkeys(salida))
    if not unicos:
        raise ErrorValidacion(
            f"La etapa «{definicion.get('nombre') or origen}» no resuelve ningún "
            "aprobador. Se para aquí: saltarla la aprobaría sola y en silencio.",
            error_code="aprobacion.sin_aprobadores",
            detalle={"origen": origen},
        )
    return unicos


# ── Delegación (CRM-00.03.05.08) ──────────────────────────────────────────


def delegar(
    uow: UnidadDeTrabajo,
    *,
    titular_id: UUID,
    suplente_id: UUID,
    desde: datetime,
    hasta: datetime,
    motivo: str = "",
    politica: str | None = None,
) -> Delegacion:
    """Pone un suplente mientras el titular no está."""
    if suplente_id == titular_id:
        raise ErrorValidacion(
            "Delegar en uno mismo no es delegar.", error_code="aprobacion.delegacion_circular"
        )
    if _con_tz(hasta) <= _con_tz(desde):
        raise ErrorValidacion(
            "La vigencia acaba antes de empezar.", error_code="aprobacion.vigencia_invalida"
        )
    fila = Delegacion(
        tenant_id=uow.tenant_id,
        titular_id=titular_id,
        suplente_id=suplente_id,
        desde=desde,
        hasta=hasta,
        motivo=motivo,
        politica=politica,
    )
    uow.db.add(fila)
    uow.db.flush()
    registrar(
        uow.db,
        accion="aprobacion.delegada",
        objeto="delegacion",
        objeto_id=fila.id,
        datos={
            "titular": str(titular_id),
            "suplente": str(suplente_id),
            "hasta": hasta.isoformat(),
            "politica": politica or "todas",
        },
        tenant_id=uow.tenant_id,
    )
    return fila


def suplente_de(
    db: Session, tenant_id: UUID, titular_id: UUID, *, politica: str = ""
) -> UUID | None:
    """Quién puede decidir hoy por el titular, si hay alguien."""
    ahora = _ahora()
    filas = (
        db.execute(
            select(Delegacion).where(
                Delegacion.tenant_id == tenant_id,
                Delegacion.titular_id == titular_id,
                Delegacion.activa.is_(True),
            )
        )
        .scalars()
        .all()
    )
    for fila in filas:
        if not (_con_tz(fila.desde) <= ahora <= _con_tz(fila.hasta)):
            continue
        # La delegación acotada a una política solo vale para esa. Una
        # delegación de vacaciones que también firmara los contratos es cómo se
        # firma un contrato sin que nadie lo decidiera.
        if fila.politica and fila.politica != politica:
            continue
        return fila.suplente_id
    return None


def puede_decidir(
    db: Session, tenant_id: UUID, etapa: EtapaAprobacion, usuario_id: UUID, *, politica: str = ""
) -> UUID | None:
    """Devuelve el titular por el que decide esta persona, o `None`.

    Si es titular, decide por sí misma. Si es suplente de un titular de la
    etapa, decide por él **y se guardan los dos**: perder quién firmó de verdad
    convierte la delegación en un agujero de responsabilidad.
    """
    titulares = [UUID(str(a)) for a in (etapa.aprobadores or [])]
    if usuario_id in titulares:
        return usuario_id
    for titular in titulares:
        if suplente_de(db, tenant_id, titular, politica=politica) == usuario_id:
            return titular
    return None


# ── Abrir una solicitud (CRM-00.03.05.06, .10, .11) ───────────────────────


def _abrir_etapa(
    db: Session, solicitud: SolicitudAprobacion, etapa: EtapaAprobacion, definicion: dict[str, Any]
) -> None:
    etapa.estado = "pendiente"
    etapa.abierta_at = _ahora()
    horas = definicion.get("vence_en_horas")
    if horas:
        etapa.vence_at = etapa.abierta_at + timedelta(hours=int(horas))
        # Se avisa ANTES de escalar, no solo después (CRM-00.03.05.09). Un
        # escalado que llega sin aviso previo se vive como un castigo y la
        # reacción es discutirlo, no decidir.
        aviso_pct = float(definicion.get("avisar_al_pct", 0.7))
        etapa.avisar_at = etapa.abierta_at + timedelta(hours=int(horas) * aviso_pct)
    db.flush()


def crear(
    uow: UnidadDeTrabajo,
    *,
    politica: str,
    objeto: str,
    objeto_id: UUID,
    etapas: list[dict[str, Any]],
    contexto: dict[str, Any] | None = None,
    solicitante_id: UUID | None = None,
    titulo: str = "",
    campos_vigilados: list[str] | None = None,
    umbral_automatico: dict[str, Any] | None = None,
    instancia_id: UUID | None = None,
) -> SolicitudAprobacion:
    """Abre una aprobación con su cadena de etapas.

    Las etapas se resuelven y **se congelan** al crearla. Recalcular los
    aprobadores a cada consulta haría que una reorganización a mitad de una
    aprobación cambiara a quién le tocaba mientras está decidiendo.
    """
    tenant_id = uow.tenant_id
    if not etapas:
        raise ErrorValidacion(
            "Una aprobación sin etapas no aprueba nada.",
            error_code="aprobacion.sin_etapas",
        )
    contexto = dict(contexto or {})
    if solicitante_id:
        contexto["_solicitante_id"] = str(solicitante_id)
    campos = list(campos_vigilados or [])

    solicitud = SolicitudAprobacion(
        tenant_id=tenant_id,
        politica=politica,
        objeto=objeto,
        objeto_id=objeto_id,
        titulo=titulo,
        contexto=contexto,
        solicitante_id=solicitante_id,
        campos_vigilados=campos,
        huella=huella_de(contexto, campos),
        instancia_id=instancia_id,
    )
    uow.db.add(solicitud)
    uow.db.flush()

    filas: list[EtapaAprobacion] = []
    for i, definicion in enumerate(etapas):
        quorum = str(definicion.get("quorum") or "todos")
        if quorum not in QUORUMS:
            raise ErrorValidacion(
                f"Quórum «{quorum}» no válido.",
                error_code="aprobacion.quorum_no_valido",
                detalle={"validos": list(QUORUMS)},
            )
        aprobadores = resolver_aprobadores(uow.db, tenant_id, definicion, contexto)
        minimo = int(definicion.get("minimo", 1))
        if quorum == "n_de_m" and not 1 <= minimo <= len(aprobadores):
            raise ErrorValidacion(
                f"La etapa pide {minimo} de {len(aprobadores)} aprobadores, y eso "
                "no se puede cumplir nunca.",
                error_code="aprobacion.minimo_imposible",
            )
        fila = EtapaAprobacion(
            tenant_id=tenant_id,
            solicitud_id=solicitud.id,
            orden=i,
            nombre=str(definicion.get("nombre") or f"etapa {i + 1}"),
            quorum=quorum,
            minimo=minimo,
            aprobadores=[str(a) for a in aprobadores],
            estado="pendiente" if i == 0 else "espera",
        )
        uow.db.add(fila)
        filas.append(fila)
    uow.db.flush()
    _abrir_etapa(uow.db, solicitud, filas[0], etapas[0])

    # Aprobación automática bajo umbral (CRM-00.03.05.11). Se comprueba DESPUÉS
    # de resolver los aprobadores, a propósito: así queda escrito a quién le
    # habría tocado. Sin ese nombre, «aprobación automática» es una decisión sin
    # responsable.
    if umbral_automatico:
        campo = str(umbral_automatico.get("campo") or "")
        tope = _num(umbral_automatico.get("menor_que"))
        valor = _num(contexto.get(campo))
        if campo and valor < tope:
            solicitud.automatica = True
            solicitud.estado = "aprobada"
            solicitud.resuelta_at = _ahora()
            solicitud.habria_aprobado = [str(a) for a in filas[0].aprobadores]
            solicitud.motivo_automatica = f"{campo} = {valor} está por debajo del umbral de {tope}"
            for fila in filas:
                fila.estado = "saltada"
                fila.cerrada_at = _ahora()
            uow.db.flush()
            registrar(
                uow.db,
                accion="aprobacion.automatica",
                objeto="solicitud_aprobacion",
                objeto_id=solicitud.id,
                datos={
                    "politica": politica,
                    "motivo": solicitud.motivo_automatica,
                    "habria_aprobado": solicitud.habria_aprobado,
                },
                tenant_id=tenant_id,
            )
            uow.emitir(
                "approval.decided",
                subject=("aprobacion", solicitud.id),
                data={
                    "solicitud_id": str(solicitud.id),
                    "objeto": objeto,
                    "objeto_id": str(objeto_id),
                    "estado": "aprobada",
                    "automatica": True,
                },
            )
            return solicitud

    uow.emitir(
        "approval.requested",
        subject=("aprobacion", solicitud.id),
        data={
            "solicitud_id": str(solicitud.id),
            "politica": politica,
            "objeto": objeto,
            "objeto_id": str(objeto_id),
            "aprobadores": [str(a) for a in filas[0].aprobadores],
        },
    )
    return solicitud


# ── Decidir (CRM-00.03.05.06) ─────────────────────────────────────────────


def _etapa_actual(db: Session, solicitud: SolicitudAprobacion) -> EtapaAprobacion | None:
    return db.execute(
        select(EtapaAprobacion).where(
            EtapaAprobacion.solicitud_id == solicitud.id,
            EtapaAprobacion.orden == solicitud.etapa_actual,
        )
    ).scalar_one_or_none()


def _cuenta(db: Session, etapa: EtapaAprobacion) -> tuple[int, int, int]:
    """Votos de **esta** vuelta. Los de las anteriores no cuentan: quien aprobó
    el 10 % no aprobó el 30 %."""
    filas = (
        db.execute(
            select(DecisionAprobacion).where(
                DecisionAprobacion.etapa_id == etapa.id,
                DecisionAprobacion.vuelta == etapa.vuelta,
            )
        )
        .scalars()
        .all()
    )
    a = len([f for f in filas if f.decision == "aprobar"])
    r = len([f for f in filas if f.decision == "rechazar"])
    return a, r, len(filas)


def _quorum_cumplido(etapa: EtapaAprobacion, favor: int) -> bool:
    total = len(etapa.aprobadores or [])
    if etapa.quorum == "cualquiera":
        return favor >= 1
    if etapa.quorum == "todos":
        return favor >= total
    if etapa.quorum == "mayoria":
        return favor > total / 2
    return favor >= etapa.minimo


def _quorum_imposible(etapa: EtapaAprobacion, favor: int, contra: int) -> bool:
    """Si ya no puede salir que sí, no se espera a los demás.

    Con «todos» y un voto en contra ya está decidido: seguir pidiendo firmas a
    los que faltan es hacerles perder el tiempo con algo que ya no puede
    aprobarse, y encima retrasa el rechazo a quien lo pidió.
    """
    total = len(etapa.aprobadores or [])
    restantes = total - favor - contra
    if etapa.quorum == "cualquiera":
        return favor == 0 and restantes == 0
    if etapa.quorum == "todos":
        return contra > 0
    if etapa.quorum == "mayoria":
        return favor + restantes <= total / 2
    return favor + restantes < etapa.minimo


def decidir(
    uow: UnidadDeTrabajo,
    solicitud_id: UUID,
    *,
    usuario_id: UUID,
    decision: str,
    comentario: str = "",
    via: str = "ui",
) -> dict[str, Any]:
    """Registra un voto y avanza la cadena si el quórum lo permite."""
    if decision not in DECISIONES:
        raise ErrorValidacion(
            f"Decisión «{decision}» no válida.",
            error_code="aprobacion.decision_no_valida",
            detalle={"validas": list(DECISIONES)},
        )
    tenant_id = uow.tenant_id
    solicitud = uow.db.get(SolicitudAprobacion, solicitud_id)
    if solicitud is None or solicitud.tenant_id != tenant_id:
        raise NoEncontrado("La solicitud no existe", error_code="aprobacion.no_encontrada")
    if solicitud.estado != "pendiente":
        raise Conflicto(
            "Esa aprobación ya está resuelta",
            error_code="aprobacion.ya_resuelta",
            detalle={"estado": solicitud.estado},
        )

    etapa = _etapa_actual(uow.db, solicitud)
    if etapa is None:
        raise NoEncontrado("La etapa no existe", error_code="aprobacion.etapa_no_encontrada")

    titular = puede_decidir(uow.db, tenant_id, etapa, usuario_id, politica=solicitud.politica)
    if titular is None:
        # 404 y no 403 por la misma razón que en el resto del producto: un 403
        # confirma que esa aprobación existe y sobre qué.
        raise NoEncontrado("La solicitud no existe", error_code="aprobacion.no_encontrada")

    ya = uow.db.execute(
        select(DecisionAprobacion).where(
            DecisionAprobacion.etapa_id == etapa.id,
            DecisionAprobacion.titular_id == titular,
            DecisionAprobacion.vuelta == etapa.vuelta,
        )
    ).scalar_one_or_none()
    if ya is not None:
        raise Conflicto(
            "Esa persona ya ha decidido en esta etapa",
            error_code="aprobacion.voto_repetido",
            detalle={"decision": ya.decision},
        )

    uow.db.add(
        DecisionAprobacion(
            tenant_id=tenant_id,
            etapa_id=etapa.id,
            titular_id=titular,
            decidio_id=usuario_id,
            decision=decision,
            comentario=comentario,
            via=via,
            vuelta=etapa.vuelta,
        )
    )
    uow.db.flush()
    registrar(
        uow.db,
        accion="aprobacion.decidida",
        objeto="solicitud_aprobacion",
        objeto_id=solicitud.id,
        datos={
            "etapa": etapa.nombre,
            "decision": decision,
            "titular": str(titular),
            "decidio": str(usuario_id),
            "delegada": str(titular) != str(usuario_id),
            "via": via,
        },
        tenant_id=tenant_id,
    )

    if decision in ("rechazar", "pedir_cambios"):
        etapa.estado = "rechazada"
        etapa.cerrada_at = _ahora()
        solicitud.estado = "rechazada" if decision == "rechazar" else "cambios_pedidos"
        solicitud.resuelta_at = _ahora()
        _emitir_fin(uow, solicitud)
        return _estado(uow.db, solicitud)

    favor, contra, _ = _cuenta(uow.db, etapa)
    if _quorum_imposible(etapa, favor, contra):
        etapa.estado = "rechazada"
        etapa.cerrada_at = _ahora()
        solicitud.estado = "rechazada"
        solicitud.resuelta_at = _ahora()
        _emitir_fin(uow, solicitud)
        return _estado(uow.db, solicitud)

    if _quorum_cumplido(etapa, favor):
        etapa.estado = "aprobada"
        etapa.cerrada_at = _ahora()
        siguiente = uow.db.execute(
            select(EtapaAprobacion).where(
                EtapaAprobacion.solicitud_id == solicitud.id,
                EtapaAprobacion.orden == etapa.orden + 1,
            )
        ).scalar_one_or_none()
        if siguiente is None:
            solicitud.estado = "aprobada"
            solicitud.resuelta_at = _ahora()
            _emitir_fin(uow, solicitud)
        else:
            solicitud.etapa_actual = siguiente.orden
            _abrir_etapa(uow.db, solicitud, siguiente, {})
            uow.emitir(
                "approval.stage.opened",
                subject=("aprobacion", solicitud.id),
                data={
                    "solicitud_id": str(solicitud.id),
                    "etapa": siguiente.nombre,
                    "aprobadores": [str(a) for a in siguiente.aprobadores],
                },
            )
    uow.db.flush()
    return _estado(uow.db, solicitud)


def _reanudar_proceso(uow: UnidadDeTrabajo, solicitud: SolicitudAprobacion) -> None:
    """Despierta el proceso que estaba esperando esta aprobación.

    Se hace aquí y no por el bus aunque el evento salga igual: la instancia vive
    en este mismo esquema y en esta misma transacción, y pasar por el bus para
    hablar con uno mismo añade una ventana en la que la aprobación está decidida
    y el proceso sigue parado. El evento se emite igual, porque **fuera** sí hay
    quien lo necesita.
    """
    if solicitud.instancia_id is None:
        return
    from services.orchestrator.modelos import InstanciaProceso

    instancia = uow.db.get(InstanciaProceso, solicitud.instancia_id)
    if instancia is None or instancia.tenant_id != solicitud.tenant_id:
        logger.warning(
            "aprobacion.instancia_desaparecida",
            solicitud=str(solicitud.id),
            instancia=str(solicitud.instancia_id),
        )
        return
    instancia.variables = {
        **instancia.variables,
        "aprobacion_estado": solicitud.estado,
        "aprobacion_id": str(solicitud.id),
        "aprobacion_automatica": solicitud.automatica,
    }
    # No se le mueve el paso: el proceso decide por dónde sigue con su propia
    # ruta. Empujarlo desde aquí metería la lógica del flujo dentro de las
    # aprobaciones, y entonces cambiar una rama exigiría tocar este módulo.
    instancia.estado = "ejecutando"
    instancia.despertar_at = _ahora()
    uow.db.flush()


def _emitir_fin(uow: UnidadDeTrabajo, solicitud: SolicitudAprobacion) -> None:
    _reanudar_proceso(uow, solicitud)
    uow.emitir(
        "approval.decided",
        subject=("aprobacion", solicitud.id),
        data={
            "solicitud_id": str(solicitud.id),
            "objeto": solicitud.objeto,
            "objeto_id": str(solicitud.objeto_id),
            "estado": solicitud.estado,
            "automatica": solicitud.automatica,
            "instancia_id": str(solicitud.instancia_id) if solicitud.instancia_id else "",
        },
    )


def _estado(db: Session, solicitud: SolicitudAprobacion) -> dict[str, Any]:
    etapas = (
        db.execute(
            select(EtapaAprobacion)
            .where(EtapaAprobacion.solicitud_id == solicitud.id)
            .order_by(EtapaAprobacion.orden)
        )
        .scalars()
        .all()
    )
    return {
        "solicitud_id": str(solicitud.id),
        "estado": solicitud.estado,
        "etapa_actual": solicitud.etapa_actual,
        "automatica": solicitud.automatica,
        "reaprobaciones": solicitud.reaprobaciones,
        "etapas": [
            {
                "orden": e.orden,
                "nombre": e.nombre,
                "quorum": e.quorum,
                "minimo": e.minimo,
                "estado": e.estado,
                "aprobadores": list(e.aprobadores or []),
                "a_favor": _cuenta(db, e)[0],
                "en_contra": _cuenta(db, e)[1],
            }
            for e in etapas
        ],
    }


def estado(db: Session, tenant_id: UUID, solicitud_id: UUID) -> dict[str, Any]:
    solicitud = db.get(SolicitudAprobacion, solicitud_id)
    if solicitud is None or solicitud.tenant_id != tenant_id:
        raise NoEncontrado("La solicitud no existe", error_code="aprobacion.no_encontrada")
    return _estado(db, solicitud)


# ── Reaprobación (CRM-00.03.05.10) ────────────────────────────────────────


def comprobar_vigencia(
    uow: UnidadDeTrabajo, solicitud_id: UUID, datos_actuales: dict[str, Any]
) -> dict[str, Any]:
    """Comprueba si lo aprobado sigue siendo lo que se aprobó.

    Si cambió, la aprobación **se reabre desde la primera etapa**. No desde donde
    estaba: quien ya había aprobado el 10 % no ha aprobado el 30 %, y conservarle
    el voto es hacerle firmar algo que no vio.
    """
    tenant_id = uow.tenant_id
    solicitud = uow.db.get(SolicitudAprobacion, solicitud_id)
    if solicitud is None or solicitud.tenant_id != tenant_id:
        raise NoEncontrado("La solicitud no existe", error_code="aprobacion.no_encontrada")

    nueva = huella_de(datos_actuales, list(solicitud.campos_vigilados or []))
    if nueva == solicitud.huella:
        return {"cambiado": False, "estado": solicitud.estado}

    cambios = {
        c: {"antes": solicitud.contexto.get(c), "ahora": datos_actuales.get(c)}
        for c in (solicitud.campos_vigilados or [])
        if solicitud.contexto.get(c) != datos_actuales.get(c)
    }
    solicitud.contexto = {**solicitud.contexto, **datos_actuales}
    solicitud.huella = nueva
    solicitud.estado = "pendiente"
    solicitud.resuelta_at = None
    solicitud.etapa_actual = 0
    solicitud.reaprobaciones += 1

    etapas = (
        uow.db.execute(
            select(EtapaAprobacion)
            .where(EtapaAprobacion.solicitud_id == solicitud.id)
            .order_by(EtapaAprobacion.orden)
        )
        .scalars()
        .all()
    )
    for etapa in etapas:
        # Los votos anteriores NO se borran: son la prueba de que aquella
        # versión sí se aprobó, y borrarlos dejaría la historia contando que
        # nunca hubo una primera aprobación.
        etapa.estado = "pendiente" if etapa.orden == 0 else "espera"
        etapa.cerrada_at = None
        etapa.avisada = False
        etapa.escalada = False
        etapa.vuelta += 1
    if etapas:
        _abrir_etapa(uow.db, solicitud, etapas[0], {})
    uow.db.flush()

    registrar(
        uow.db,
        accion="aprobacion.reabierta",
        objeto="solicitud_aprobacion",
        objeto_id=solicitud.id,
        datos={"cambios": cambios, "vuelta": solicitud.reaprobaciones},
        tenant_id=tenant_id,
    )
    uow.emitir(
        "approval.reopened",
        subject=("aprobacion", solicitud.id),
        data={
            "solicitud_id": str(solicitud.id),
            "objeto": solicitud.objeto,
            "objeto_id": str(solicitud.objeto_id),
            "cambios": list(cambios.keys()),
        },
    )
    return {"cambiado": True, "cambios": cambios, "estado": "pendiente"}


# ── Escalado (CRM-00.03.05.09) ────────────────────────────────────────────


def revisar_plazos(uow: UnidadDeTrabajo, tenant_id: UUID) -> dict[str, Any]:
    """Avisa a los que van a pasarse de plazo y escala a los que ya se pasaron.

    **Primero se avisa y después se escala.** Un escalado que llega sin aviso
    previo se vive como un castigo, y la reacción es discutirlo en vez de
    decidir.

    Al escalar, el superior **se añade**, no sustituye: quitar al titular haría
    que el escalado le quitara la decisión a quien todavía puede tomarla, y
    además borraría el rastro de a quién le tocaba.
    """
    ahora = _ahora()
    abiertas = (
        uow.db.execute(
            select(EtapaAprobacion).where(
                EtapaAprobacion.tenant_id == tenant_id,
                EtapaAprobacion.estado == "pendiente",
            )
        )
        .scalars()
        .all()
    )
    avisadas: list[str] = []
    escaladas: list[dict[str, Any]] = []

    for etapa in abiertas:
        if etapa.avisar_at and not etapa.avisada and _con_tz(etapa.avisar_at) <= ahora:
            etapa.avisada = True
            avisadas.append(str(etapa.id))
            uow.emitir(
                "approval.due.soon",
                subject=("aprobacion", etapa.solicitud_id),
                data={
                    "solicitud_id": str(etapa.solicitud_id),
                    "etapa": etapa.nombre,
                    "vence_at": _con_tz(etapa.vence_at).isoformat() if etapa.vence_at else "",
                    "aprobadores": [str(a) for a in etapa.aprobadores],
                },
                dedup_key=f"aviso:{etapa.id}",
            )

        if etapa.vence_at and not etapa.escalada and _con_tz(etapa.vence_at) <= ahora:
            nuevos: list[str] = []
            for titular in list(etapa.aprobadores or []):
                cadena = org.cadena_de_mando(uow.db, tenant_id, UUID(str(titular)))
                if cadena:
                    nuevos.append(str(cadena[0]))
            if nuevos:
                etapa.aprobadores = list(dict.fromkeys([*etapa.aprobadores, *nuevos]))
                etapa.escalada = True
                escaladas.append({"etapa_id": str(etapa.id), "anadidos": nuevos})
                uow.emitir(
                    "approval.escalated",
                    subject=("aprobacion", etapa.solicitud_id),
                    data={
                        "solicitud_id": str(etapa.solicitud_id),
                        "etapa": etapa.nombre,
                        "anadidos": nuevos,
                    },
                    dedup_key=f"escalado:{etapa.id}",
                )
            else:
                # Nadie por encima. Se marca igual para no volver a intentarlo
                # cada minuto, y se deja dicho: una etapa vencida cuyos
                # aprobadores no tienen superior necesita que alguien la mire,
                # y callarlo la deja parada para siempre.
                etapa.escalada = True
                logger.warning(
                    "aprobacion.sin_a_quien_escalar",
                    etapa=str(etapa.id),
                    tenant=str(tenant_id),
                )
    uow.db.flush()
    return {
        "revisadas": len(abiertas),
        "avisadas": avisadas,
        "escaladas": escaladas,
        # Sin etapas abiertas no se dice «todo al día»: no hay nada que medir.
        "medible": bool(abiertas),
    }


# ── Decidir desde el correo (CRM-00.03.05.12) ─────────────────────────────


def emitir_enlace(
    uow: UnidadDeTrabajo, *, etapa_id: UUID, titular_id: UUID, validez_horas: int = 72
) -> tuple[EnlaceDecision, str]:
    """Enlace firmado, de un solo uso y con caducidad.

    Se devuelve el token **una sola vez** y en la base queda solo su hash: quien
    lea esta tabla —una copia de seguridad, un volcado de soporte— no puede
    aprobar en nombre de nadie.
    """
    token = secrets.token_urlsafe(32)
    fila = EnlaceDecision(
        tenant_id=uow.tenant_id,
        etapa_id=etapa_id,
        titular_id=titular_id,
        hash_token=_hash(token),
        caduca_at=_ahora() + timedelta(hours=validez_horas),
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila, token


def decidir_con_enlace(
    uow: UnidadDeTrabajo, token: str, *, decision: str, comentario: str = "", via: str = "correo"
) -> dict[str, Any]:
    """Canjea el enlace y decide.

    Un token inexistente, usado o caducado dan **el mismo error**: distinguirlos
    le diría a quien prueba si ese enlace existió, y con eso se puede saber que
    hay una aprobación en marcha sobre algo.
    """
    fila = uow.db.execute(
        select(EnlaceDecision).where(
            EnlaceDecision.tenant_id == uow.tenant_id,
            EnlaceDecision.hash_token == _hash(token),
        )
    ).scalar_one_or_none()
    invalido = NoAutenticado(
        "Ese enlace no sirve: puede haberse usado ya o haber caducado.",
        error_code="aprobacion.enlace_invalido",
    )
    if fila is None or fila.usado_at is not None or _con_tz(fila.caduca_at) < _ahora():
        raise invalido

    etapa = uow.db.get(EtapaAprobacion, fila.etapa_id)
    if etapa is None:
        raise invalido

    # Se marca usado ANTES de decidir. Si decidir falla, el enlace ya está
    # gastado y hay que pedir otro — molesto, y mucho mejor que dejar vivo un
    # enlace que ya ha viajado por un correo que puede reenviarse.
    fila.usado_at = _ahora()
    uow.db.flush()

    return decidir(
        uow,
        etapa.solicitud_id,
        usuario_id=fila.titular_id,
        decision=decision,
        comentario=comentario,
        via=via,
    )


# ── La bandeja (CRM-00.03.05.13) ──────────────────────────────────────────


def bandeja(
    db: Session, tenant_id: UUID, usuario_id: UUID, *, limite: int = 50
) -> list[dict[str, Any]]:
    """Lo que le toca decidir a una persona, con el contexto para decidirlo.

    Va todo en una llamada y **con el contexto dentro**: una bandeja que solo
    dice «tienes 14 cosas» obliga a abrir catorce pantallas, y lo que pasa
    entonces es que se aprueba en bloque sin mirar.

    Incluye lo que le toca **por delegación**, marcado como tal: si no se
    distinguiera, el suplente no sabría que está firmando por otro.
    """
    ahora = _ahora()
    etapas = (
        db.execute(
            select(EtapaAprobacion).where(
                EtapaAprobacion.tenant_id == tenant_id,
                EtapaAprobacion.estado == "pendiente",
            )
        )
        .scalars()
        .all()
    )
    salida: list[dict[str, Any]] = []
    for etapa in etapas:
        solicitud = db.get(SolicitudAprobacion, etapa.solicitud_id)
        if solicitud is None or solicitud.estado != "pendiente":
            continue
        titular = puede_decidir(db, tenant_id, etapa, usuario_id, politica=solicitud.politica)
        if titular is None:
            continue
        ya = db.execute(
            select(DecisionAprobacion).where(
                DecisionAprobacion.etapa_id == etapa.id,
                DecisionAprobacion.titular_id == titular,
                DecisionAprobacion.vuelta == etapa.vuelta,
            )
        ).scalar_one_or_none()
        if ya is not None:
            continue
        vence = _con_tz(etapa.vence_at)
        salida.append(
            {
                "solicitud_id": str(solicitud.id),
                "politica": solicitud.politica,
                "titulo": solicitud.titulo,
                "objeto": solicitud.objeto,
                "objeto_id": str(solicitud.objeto_id),
                "etapa": etapa.nombre,
                "quorum": etapa.quorum,
                # El contexto va entero menos lo interno: es lo que permite
                # decidir sin abrir el registro.
                "contexto": {
                    k: v for k, v in (solicitud.contexto or {}).items() if not k.startswith("_")
                },
                "pedida_at": _con_tz(solicitud.created_at).isoformat()
                if solicitud.created_at
                else None,
                "vence_at": vence.isoformat() if vence else None,
                "va_tarde": bool(vence and vence < ahora),
                "por_delegacion": str(titular) != str(usuario_id),
                "en_nombre_de": str(titular) if str(titular) != str(usuario_id) else None,
                "reaprobacion": solicitud.reaprobaciones > 0,
                "esperando_dias": (ahora - _con_tz(solicitud.created_at)).days
                if solicitud.created_at
                else 0,
            }
        )
    # Lo más urgente primero: lo vencido, y después lo que lleva más esperando.
    salida.sort(key=lambda s: (not s["va_tarde"], -s["esperando_dias"]))
    return salida[:limite]
