"""Fondos de marketing para el canal: MDF (CRM-03.04.01.04).

Un fondo de marketing es dinero del fabricante que gasta el partner. Todo lo
difícil sale de esa frase: quien decide no es quien paga, quien justifica no
trabaja aquí, y el ejercicio se cierra pase lo que pase.

**Lo comprometido cuenta como gastado.** Es el error clásico: un fondo que solo
descuenta lo ya pagado enseña saldo disponible cuando en realidad está todo
aprobado y pendiente de factura. Se sobrecompromete, y en noviembre alguien tiene
que decirle a un partner que su campaña aprobada no se paga.

**Justificar tiene fecha.** Sin plazo, las facturas llegan en enero del año
siguiente contra un presupuesto que ya no existe. El plazo libera el dinero
cuando vence, pero **de forma explícita y auditada**: el partner tiene derecho a
ver qué día se le cayó la reserva y por qué.

**Lo justificado puede ser menos que lo aprobado.** Se aprueba una campaña de
10.000 y se justifican 6.000: se paga 6.000 y se devuelven 4.000 al fondo. Pagar
lo aprobado sin mirar la justificación es regalar dinero; no devolver el resto es
perderlo.

**El retorno se declara, no se supone.** Si el partner no dice cuántos leads
salieron, el fondo no dice que la campaña fue mal: dice que no se midió. Son cosas
distintas y llevan a decisiones opuestas — una se corrige con otra campaña y la
otra, exigiendo el dato.

`marketing` no lee el esquema de `sales`: el partner llega **por evento** a una
proyección local, igual que el perfil de marketing. Se guarda cuándo se
sincronizó y se enseña.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from crmcore.runtime import settings as rt
from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

CENTIMO = Decimal("0.01")

# Estados de una solicitud.
#
#   pendiente     esperando decisión
#   aprobada      dinero comprometido, pendiente de justificar
#   rechazada     con motivo
#   justificada   con evidencia aceptada, lista para pagar
#   pagada        con referencia
#   caducada      venció el plazo de justificación y el dinero volvió al fondo
ESTADOS = ("pendiente", "aprobada", "rechazada", "justificada", "pagada", "caducada")

# Lo que compromete dinero del fondo. Aparte porque es la lista que decide el
# saldo, y tenerla escrita evita que un estado nuevo entre sin que nadie piense
# si resta o no.
COMPROMETEN = ("aprobada", "justificada", "pagada")


class PartnerConocido(Base):
    """Proyección local del partner (CRM-03.04.01.04).

    Llega por el evento `partner.activated`. Va por detrás del alta real, y por
    eso se guarda `sincronizado_at` y se enseña: un fondo abierto a un partner que
    todavía no ha llegado aquí es un error de datos, no un error del usuario.
    """

    __tablename__ = "partners_conocidos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    partner_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    clave: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    canal: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    sincronizado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (UniqueConstraint("tenant_id", "partner_id", name="uq_partner_conocido"),)


class FondoMdf(Base, TimestampMixin, SoftDeleteMixin):
    """Dinero asignado a un partner para un periodo (CRM-03.04.01.04)."""

    __tablename__ = "fondos_mdf"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    partner_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    desde: Mapped[date] = mapped_column(Date, nullable=False)
    hasta: Mapped[date] = mapped_column(Date, nullable=False)
    asignado: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    # Cerrado: ya no admite solicitudes nuevas. El ejercicio se cierra aunque
    # queden facturas por llegar, y eso hay que poder decirlo.
    cerrado: Mapped[bool] = mapped_column(
        default=False, nullable=False, server_default=text("false")
    )

    __table_args__ = (Index("ix_fondos_mdf", "tenant_id", "partner_id", "desde"),)


class SolicitudMdf(Base, TimestampMixin, SoftDeleteMixin):
    """Una petición de gasto contra el fondo (CRM-03.04.01.04)."""

    __tablename__ = "solicitudes_mdf"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    fondo_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("fondos_mdf.id", ondelete="CASCADE"), nullable=False
    )
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    actividad: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    importe_solicitado: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    # Se aprueba un importe, que puede ser menor que el pedido. Es la decisión
    # real: «aprobado» a secas obliga a aprobar todo o nada.
    importe_aprobado: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    importe_justificado: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    fecha_actividad: Mapped[date | None] = mapped_column(Date, nullable=True)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    motivo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    justificar_antes_de: Mapped[date | None] = mapped_column(Date, nullable=True)
    decidida_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    decidida_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pago_referencia: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    pagada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Resultados declarados por el partner: leads, oportunidades, asistentes…
    # Vacío significa **sin medir**, no «cero».
    resultados: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        Index("ix_solicitudes_mdf", "tenant_id", "fondo_id", "estado"),
        Index("ix_solicitudes_mdf_plazo", "tenant_id", "estado", "justificar_antes_de"),
    )


class JustificacionMdf(Base, TimestampMixin):
    """La prueba del gasto (CRM-03.04.01.04).

    Las evidencias se guardan como **referencias** al gestor documental, no como
    ficheros en esta tabla: una factura escaneada por cada campaña de cada partner
    convertiría el esquema de marketing en un archivo documental, que ya existe y
    tiene su retención.
    """

    __tablename__ = "justificaciones_mdf"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    solicitud_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("solicitudes_mdf.id", ondelete="CASCADE"), nullable=False
    )
    importe: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    evidencias: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    resultados: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    motivo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    revisada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (Index("ix_justificaciones_mdf", "tenant_id", "solicitud_id"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _hoy() -> date:
    return datetime.now(timezone.utc).date()


def _redondear(valor: Decimal) -> Decimal:
    return Decimal(valor).quantize(CENTIMO, rounding=ROUND_HALF_UP)


def _fondo(db: Session, tenant_id: UUID, fondo_id: UUID) -> FondoMdf:
    fila = db.get(FondoMdf, fondo_id)
    if fila is None or fila.tenant_id != tenant_id:
        raise NoEncontrado("El fondo no existe", error_code="mdf.fondo_no_encontrado")
    return fila


# ── Proyección de partners ────────────────────────────────────────────────


def registrar_partner(
    db: Session,
    *,
    tenant_id: UUID,
    partner_id: UUID,
    clave: str = "",
    nombre: str = "",
    canal: str = "",
) -> PartnerConocido:
    """Guarda o actualiza el partner que llega por evento."""
    fila = db.execute(
        select(PartnerConocido).where(
            PartnerConocido.tenant_id == tenant_id, PartnerConocido.partner_id == partner_id
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = PartnerConocido(tenant_id=tenant_id, partner_id=partner_id)
        db.add(fila)
    fila.clave = clave or fila.clave
    fila.nombre = nombre or fila.nombre
    fila.canal = canal or fila.canal
    fila.sincronizado_at = _ahora()
    db.flush()
    return fila


# ── Fondos y saldo (CRM-03.04.01.04) ──────────────────────────────────────


def crear_fondo(
    uow: UnidadDeTrabajo,
    *,
    partner_id: UUID,
    desde: date,
    hasta: date,
    asignado: Decimal,
    nombre: str = "",
    moneda: str = "EUR",
) -> tuple[FondoMdf, list[str]]:
    """Abre un fondo para un partner y un periodo.

    Devuelve avisos en vez de fallar cuando el partner todavía no ha llegado a la
    proyección: el fondo es correcto y el dato llegará. Bloquear aquí haría que un
    retraso de milisegundos en el bus pareciera un error del usuario.
    """
    if hasta < desde:
        raise ErrorValidacion(
            "El fondo termina antes de empezar.", error_code="mdf.periodo_invalido"
        )
    if Decimal(asignado) <= 0:
        raise ErrorValidacion(
            "Un fondo de cero no es un fondo: si no hay dinero, no se abre.",
            error_code="mdf.importe_invalido",
        )
    avisos: list[str] = []
    conocido = uow.db.execute(
        select(PartnerConocido).where(
            PartnerConocido.tenant_id == uow.tenant_id,
            PartnerConocido.partner_id == partner_id,
        )
    ).scalar_one_or_none()
    if conocido is None:
        avisos.append(
            "Ese partner todavía no ha llegado a marketing por el bus de eventos: "
            "el fondo queda abierto, pero el nombre saldrá vacío hasta que llegue."
        )

    fila = FondoMdf(
        tenant_id=uow.tenant_id,
        partner_id=partner_id,
        nombre=nombre.strip(),
        desde=desde,
        hasta=hasta,
        asignado=Decimal(asignado),
        moneda=moneda,
    )
    uow.db.add(fila)
    uow.db.flush()
    registrar(
        uow.db,
        accion="mdf.fondo_abierto",
        objeto="fondo_mdf",
        objeto_id=fila.id,
        datos={"partner_id": str(partner_id), "asignado": str(asignado)},
        tenant_id=uow.tenant_id,
    )
    return fila, avisos


def saldo(db: Session, tenant_id: UUID, fondo_id: UUID) -> dict[str, Any]:
    """El estado del fondo: asignado, comprometido, justificado, pagado, libre.

    **Lo comprometido resta.** Un saldo que solo descuenta lo pagado enseña dinero
    que ya tiene dueño, y con ese saldo se aprueban campañas que luego no se
    pueden pagar.
    """
    fondo = _fondo(db, tenant_id, fondo_id)
    solicitudes = (
        db.execute(
            select(SolicitudMdf).where(
                SolicitudMdf.tenant_id == tenant_id, SolicitudMdf.fondo_id == fondo_id
            )
        )
        .scalars()
        .all()
    )
    comprometido = sum(
        (Decimal(s.importe_aprobado or 0) for s in solicitudes if s.estado in COMPROMETEN),
        Decimal(0),
    )
    justificado = sum(
        (
            Decimal(s.importe_justificado or 0)
            for s in solicitudes
            if s.estado in ("justificada", "pagada")
        ),
        Decimal(0),
    )
    pagado = sum(
        (Decimal(s.importe_justificado or 0) for s in solicitudes if s.estado == "pagada"),
        Decimal(0),
    )
    pendiente_decidir = sum(
        (Decimal(s.importe_solicitado) for s in solicitudes if s.estado == "pendiente"),
        Decimal(0),
    )
    libre = _redondear(Decimal(fondo.asignado) - comprometido)
    return {
        "fondo_id": str(fondo.id),
        "partner_id": str(fondo.partner_id),
        "moneda": fondo.moneda,
        "asignado": str(_redondear(Decimal(fondo.asignado))),
        "comprometido": str(_redondear(comprometido)),
        "justificado": str(_redondear(justificado)),
        "pagado": str(_redondear(pagado)),
        "disponible": str(libre),
        # Lo pedido y sin decidir no resta todavía, pero se enseña: es lo que
        # haría falta si se aprobara todo, y es la cifra que evita aprobar dos
        # campañas que juntas no caben.
        "pendiente_de_decidir": str(_redondear(pendiente_decidir)),
        "cabria_todo": libre >= pendiente_decidir,
        "cerrado": fondo.cerrado,
        "solicitudes": len(solicitudes),
    }


def solicitar(
    uow: UnidadDeTrabajo,
    fondo_id: UUID,
    *,
    titulo: str,
    importe: Decimal,
    actividad: str = "",
    descripcion: str = "",
    fecha_actividad: date | None = None,
) -> SolicitudMdf:
    """El partner pide gastar. No se comprueba el saldo aquí: se comprueba al
    aprobar.

    A propósito. Impedir pedir cuando no hay saldo esconde la demanda real: el
    fabricante necesita saber cuánto se le está pidiendo de más para decidir si
    amplía el fondo, y si el sistema no deja ni pedirlo, esa información no existe.
    """
    fondo = _fondo(uow.db, uow.tenant_id, fondo_id)
    if fondo.cerrado:
        raise Conflicto(
            "Ese fondo está cerrado",
            error_code="mdf.fondo_cerrado",
            detalle={"fondo": str(fondo.id)},
        )
    if Decimal(importe) <= 0:
        raise ErrorValidacion(
            "Una solicitud sin importe no se puede aprobar.", error_code="mdf.importe_invalido"
        )
    fila = SolicitudMdf(
        tenant_id=uow.tenant_id,
        fondo_id=fondo_id,
        titulo=titulo.strip(),
        actividad=actividad.strip(),
        descripcion=descripcion,
        importe_solicitado=Decimal(importe),
        fecha_actividad=fecha_actividad,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def decidir(
    uow: UnidadDeTrabajo,
    solicitud_id: UUID,
    *,
    aprobar: bool,
    importe_aprobado: Decimal | None = None,
    motivo: str = "",
    dias_para_justificar: int | None = None,
    decidida_por: UUID | None = None,
) -> SolicitudMdf:
    """Aprueba —con importe y plazo— o rechaza con motivo.

    Aprobar por encima del saldo **se rechaza**: es el momento exacto en que se
    sobrecompromete un fondo, y dejarlo pasar traslada el problema a quien tenga
    que decir que no en noviembre.
    """
    fila = uow.db.get(SolicitudMdf, solicitud_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("La solicitud no existe", error_code="mdf.solicitud_no_encontrada")
    if fila.estado != "pendiente":
        raise Conflicto(
            "Esa solicitud ya está decidida",
            error_code="mdf.solicitud_decidida",
            detalle={"estado": fila.estado},
        )
    if not aprobar:
        if not motivo.strip():
            raise ErrorValidacion(
                "Rechazar una solicitud de fondos exige motivo.",
                error_code="mdf.motivo_obligatorio",
            )
        fila.estado = "rechazada"
        fila.motivo = motivo.strip()
        fila.decidida_por = decidida_por
        fila.decidida_at = _ahora()
        return fila

    importe = Decimal(importe_aprobado if importe_aprobado is not None else fila.importe_solicitado)
    if importe <= 0:
        raise ErrorValidacion(
            "Aprobar cero no es aprobar: es rechazar, y entonces hace falta motivo.",
            error_code="mdf.importe_invalido",
        )
    estado = saldo(uow.db, uow.tenant_id, fila.fondo_id)
    if importe > Decimal(estado["disponible"]):
        raise Conflicto(
            "No hay saldo suficiente en el fondo",
            error_code="mdf.sin_saldo",
            detalle={"disponible": estado["disponible"], "pedido": str(importe)},
        )

    dias = int(
        dias_para_justificar
        if dias_para_justificar is not None
        else (rt.efectivo("mdf_dias_para_justificar", uow.db) or 60)
    )
    fondo = _fondo(uow.db, uow.tenant_id, fila.fondo_id)
    base = fila.fecha_actividad or _hoy()
    fila.estado = "aprobada"
    fila.importe_aprobado = importe
    fila.motivo = motivo.strip()
    fila.decidida_por = decidida_por
    fila.decidida_at = _ahora()
    # El plazo no puede pasarse del cierre del fondo: justificar en marzo contra
    # un presupuesto que cerró en diciembre no lo cobra nadie.
    fila.justificar_antes_de = min(base + timedelta(days=dias), fondo.hasta)
    uow.db.flush()
    registrar(
        uow.db,
        accion="mdf.aprobada",
        objeto="solicitud_mdf",
        objeto_id=fila.id,
        datos={
            "importe_solicitado": str(fila.importe_solicitado),
            "importe_aprobado": str(importe),
            "justificar_antes_de": str(fila.justificar_antes_de),
        },
        tenant_id=uow.tenant_id,
    )
    return fila


def justificar(
    uow: UnidadDeTrabajo,
    solicitud_id: UUID,
    *,
    importe: Decimal,
    evidencias: list[dict[str, Any]] | None = None,
    resultados: dict[str, Any] | None = None,
) -> tuple[JustificacionMdf, list[str]]:
    """El partner presenta la prueba del gasto.

    **Sin evidencia no hay justificación**: una justificación sin factura ni
    material es una declaración, y lo que se paga con ella no se puede defender
    ante una auditoría.

    Se admite justificar **fuera de plazo**, marcándolo. La alternativa —no
    dejar— hace que el partner mande la factura por correo y alguien la meta a
    mano sin plazo ninguno.
    """
    fila = uow.db.get(SolicitudMdf, solicitud_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("La solicitud no existe", error_code="mdf.solicitud_no_encontrada")
    if fila.estado not in ("aprobada", "caducada"):
        raise Conflicto(
            "Solo se justifica lo aprobado",
            error_code="mdf.no_aprobada",
            detalle={"estado": fila.estado},
        )
    pruebas = list(evidencias or [])
    if bool(rt.efectivo("mdf_exigir_evidencia", uow.db, default=True)) and not pruebas:
        raise ErrorValidacion(
            "Hace falta al menos una evidencia (factura, material, informe).",
            error_code="mdf.sin_evidencia",
        )
    if Decimal(importe) <= 0:
        raise ErrorValidacion(
            "Una justificación de cero no justifica nada.", error_code="mdf.importe_invalido"
        )

    avisos: list[str] = []
    if fila.justificar_antes_de and _hoy() > fila.justificar_antes_de:
        avisos.append(f"Fuera de plazo: había que justificar antes del {fila.justificar_antes_de}.")
    aprobado = Decimal(fila.importe_aprobado or 0)
    if Decimal(importe) > aprobado:
        avisos.append(
            f"Se justifica más de lo aprobado ({importe} > {aprobado}): se paga hasta "
            f"lo aprobado y el resto lo asume el partner."
        )
    if not (resultados or {}):
        avisos.append(
            "Sin resultados declarados: esta campaña no podrá medirse. No significa "
            "que fuera mal, significa que no se sabe."
        )

    justificacion = JustificacionMdf(
        tenant_id=uow.tenant_id,
        solicitud_id=fila.id,
        importe=Decimal(importe),
        evidencias=pruebas,
        resultados=dict(resultados or {}),
    )
    uow.db.add(justificacion)
    uow.db.flush()
    return justificacion, avisos


def revisar_justificacion(
    uow: UnidadDeTrabajo,
    justificacion_id: UUID,
    *,
    aceptar: bool,
    motivo: str = "",
    revisada_por: UUID | None = None,
) -> SolicitudMdf:
    """Acepta o rechaza la justificación. Lo aceptado es **lo menor** de las dos
    cifras.

    Pagar lo aprobado sin mirar lo justificado regala la diferencia; y lo que
    sobra vuelve al fondo en vez de perderse, que es lo que pasa cuando la
    solicitud se cierra sin tocar el saldo.
    """
    justificacion = uow.db.get(JustificacionMdf, justificacion_id)
    if justificacion is None or justificacion.tenant_id != uow.tenant_id:
        raise NoEncontrado(
            "La justificación no existe", error_code="mdf.justificacion_no_encontrada"
        )
    if not aceptar and not motivo.strip():
        raise ErrorValidacion(
            "Rechazar una justificación exige motivo.", error_code="mdf.motivo_obligatorio"
        )
    solicitud = uow.db.get(SolicitudMdf, justificacion.solicitud_id)
    assert solicitud is not None

    justificacion.estado = "aceptada" if aceptar else "rechazada"
    justificacion.motivo = motivo.strip()
    justificacion.revisada_por = revisada_por
    if aceptar:
        aceptado = min(Decimal(justificacion.importe), Decimal(solicitud.importe_aprobado or 0))
        solicitud.importe_justificado = aceptado
        solicitud.estado = "justificada"
        solicitud.resultados = dict(justificacion.resultados or {})
    uow.db.flush()
    registrar(
        uow.db,
        accion="mdf.justificacion_revisada",
        objeto="solicitud_mdf",
        objeto_id=solicitud.id,
        datos={
            "aceptada": aceptar,
            "presentado": str(justificacion.importe),
            "aceptado": str(solicitud.importe_justificado)
            if solicitud.importe_justificado is not None
            else None,
            "motivo": motivo,
        },
        tenant_id=uow.tenant_id,
    )
    return solicitud


def pagar(uow: UnidadDeTrabajo, solicitud_id: UUID, *, referencia: str) -> SolicitudMdf:
    """Marca el pago con su referencia. Igual que en comisiones: sin referencia,
    «pagado» no se puede comprobar."""
    fila = uow.db.get(SolicitudMdf, solicitud_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("La solicitud no existe", error_code="mdf.solicitud_no_encontrada")
    if fila.estado != "justificada":
        raise Conflicto(
            "Solo se paga lo justificado y aceptado",
            error_code="mdf.no_justificada",
            detalle={"estado": fila.estado},
        )
    if not referencia.strip():
        raise ErrorValidacion(
            "Marcar pagada exige la referencia del pago.",
            error_code="mdf.referencia_obligatoria",
        )
    fila.estado = "pagada"
    fila.pago_referencia = referencia.strip()
    fila.pagada_at = _ahora()
    registrar(
        uow.db,
        accion="mdf.pagada",
        objeto="solicitud_mdf",
        objeto_id=fila.id,
        datos={"referencia": fila.pago_referencia, "importe": str(fila.importe_justificado)},
        tenant_id=uow.tenant_id,
    )
    return fila


def caducar_pendientes(uow: UnidadDeTrabajo, *, en_fecha: date | None = None) -> dict[str, Any]:
    """Libera el dinero de lo aprobado que nadie justificó en plazo.

    Explícito y auditado: el partner tiene derecho a ver qué día se le cayó la
    reserva. Una caducidad calculada al vuelo no deja constancia de nada y acaba
    en «a mí nadie me avisó».
    """
    hoy = en_fecha or _hoy()
    filas = (
        uow.db.execute(
            select(SolicitudMdf).where(
                SolicitudMdf.tenant_id == uow.tenant_id,
                SolicitudMdf.estado == "aprobada",
                SolicitudMdf.justificar_antes_de.is_not(None),
                SolicitudMdf.justificar_antes_de < hoy,
            )
        )
        .scalars()
        .all()
    )
    liberado = Decimal(0)
    for fila in filas:
        fila.estado = "caducada"
        fila.motivo = (
            f"Sin justificar antes del {fila.justificar_antes_de}: el importe vuelve al fondo."
        )
        liberado += Decimal(fila.importe_aprobado or 0)
        registrar(
            uow.db,
            accion="mdf.caducada",
            objeto="solicitud_mdf",
            objeto_id=fila.id,
            datos={"importe": str(fila.importe_aprobado), "plazo": str(fila.justificar_antes_de)},
            tenant_id=uow.tenant_id,
        )
    uow.db.flush()
    return {
        "en_fecha": str(hoy),
        "caducadas": [str(f.id) for f in filas],
        "liberado": str(_redondear(liberado)),
    }


def retorno(db: Session, tenant_id: UUID, fondo_id: UUID) -> dict[str, Any]:
    """Qué salió de lo gastado, y **qué no se midió** (CRM-03.04.01.04).

    La cifra que importa no es el total de leads: es cuántas campañas declararon
    resultados. Un retorno calculado sobre las tres que sí los declararon, y
    presentado como el del fondo entero, es un número inventado con datos reales.
    """
    fondo = _fondo(db, tenant_id, fondo_id)
    solicitudes = (
        db.execute(
            select(SolicitudMdf).where(
                SolicitudMdf.tenant_id == tenant_id,
                SolicitudMdf.fondo_id == fondo_id,
                SolicitudMdf.estado.in_(("justificada", "pagada")),
            )
        )
        .scalars()
        .all()
    )
    con_datos = [s for s in solicitudes if s.resultados]
    totales: dict[str, Decimal] = {}
    for solicitud in con_datos:
        for clave, valor in (solicitud.resultados or {}).items():
            try:
                totales[clave] = totales.get(clave, Decimal(0)) + Decimal(str(valor))
            except (TypeError, ValueError):
                continue
    gastado_con_datos = sum((Decimal(s.importe_justificado or 0) for s in con_datos), Decimal(0))
    gastado_total = sum((Decimal(s.importe_justificado or 0) for s in solicitudes), Decimal(0))
    return {
        "fondo_id": str(fondo.id),
        "campanas": len(solicitudes),
        "campanas_con_resultados": len(con_datos),
        "gastado_total": str(_redondear(gastado_total)),
        "gastado_medido": str(_redondear(gastado_con_datos)),
        "resultados": {k: str(v) for k, v in totales.items()},
        "coste_por": {
            k: str(_redondear(gastado_con_datos / v)) for k, v in totales.items() if v > 0
        },
        # La cobertura de la medición. Sin esto, un retorno estupendo calculado
        # sobre el 10 % del gasto pasa por el retorno del fondo.
        "cobertura_pct": (
            float(round(100 * gastado_con_datos / gastado_total, 1)) if gastado_total > 0 else None
        ),
        "medible": bool(con_datos),
        "aviso": (
            ""
            if len(con_datos) == len(solicitudes)
            else f"{len(solicitudes) - len(con_datos)} campañas sin resultados declarados: "
            "no entran en el cálculo y no significan que fueran mal."
        ),
    }
