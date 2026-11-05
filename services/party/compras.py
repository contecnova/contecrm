"""Compras al proveedor: lo que los cálculos de coste y de proveedor necesitaban
para dejar de ser calculadoras (CRM-09.02.01.04 a .09, CRM-09.01.01.04, .05,
.07, .09 y .10).

Esos once cálculos estaban escritos y probados, y **no tenían datos detrás**:
cada ruta recibía del que llamaba las ofertas, la capacidad, los tramos o las
entregas, y devolvía el resultado sin guardar nada. Una pantalla sobre ellos
tenía que pedirle a alguien que teclease los hechos, que es justo lo contrario
de lo que prometen: una evaluación «con hechos medidos» a la que se le escriben
los hechos es una opinión con formato. Medido el 05-11-2026, y por eso
constaron como en curso hasta que esto existió.

Aquí se guardan los hechos **donde nacen**, y los cálculos los leen:

- **La petición de oferta y sus respuestas.** Ligada a la oportunidad que la
  motiva, con fecha límite, a qué proveedores se pidió y qué contestó cada uno.
  De ahí salen la comparación (con la homologación y los papeles de cada uno,
  que viven en este mismo servicio), quién no ha contestado, la fecha que se
  puede prometer y el reparto.
- **La adjudicación, la entrega y las incidencias** de cada respuesta elegida.
  Es lo que mide al proveedor: en plazo o no, cuánto acabó costando, qué falló.
  Y es lo que dice qué hay comprometido con clientes —para la baja y para el
  contrato— y cuánto se le ha comprado —para el rappel y para el riesgo de
  depender de él—.
- **La capacidad contratada por periodo** y lo reservado contra ella, firme o
  en oferta.
- **Los tramos de rappel, el contrato y el alcance** de cada proveedor.

Vive en `party` y no en ventas porque el proveedor, su homologación y sus
papeles están aquí: la comparación los necesita a la vez que las respuestas, y
partirlo entre dos servicios obligaría a preguntar por HTTP en cada cálculo.
Los cálculos puros siguen en `crmcore.costes` y `crmcore.proveedores_comercial`,
que es donde va lo que no toca base, y ventas los usa igual que antes.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore import costes as cst
from crmcore import proveedores_comercial as pcom
from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.fechas import hoy as hoy_del_cliente
from crmcore.ids import nuevo_id
from crmcore.runtime.settings import efectivo
from sqlalchemy import (
    Boolean,
    Date,
    Index,
    Integer,
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

from services.party import proveedores as prv

ESTADOS_PETICION = ("abierta", "adjudicada", "cerrada")
ESTADOS_RESPUESTA = ("recibida", "adjudicada", "descartada")
GRAVEDADES = ("baja", "media", "alta", "critica")


# ── Modelos ───────────────────────────────────────────────────────────────


class PeticionOferta(Base, TimestampMixin):
    """Una petición de oferta a varios proveedores (CRM-09.02.01.05)."""

    __tablename__ = "peticiones_oferta"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # La oportunidad que la motiva. Vive en ventas: se guarda la referencia, no
    # se lee su base.
    oportunidad_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # La categoría decide la homologación: «homologado» sin categoría no dice nada.
    categoria: Mapped[str] = mapped_column(String(80), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cantidad: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=1)
    unidad: Mapped[str] = mapped_column(String(20), nullable=False, default="ud")
    fecha_limite: Mapped[date] = mapped_column(Date, nullable=False)
    # Para cuándo hace falta. Sin ella, el que llega tarde no se descarta.
    fecha_necesaria: Mapped[date | None] = mapped_column(Date, nullable=True)
    proveedores: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="abierta")


class RespuestaOferta(Base, TimestampMixin):
    """Lo que contestó un proveedor, y lo que pasó después si se le adjudicó."""

    __tablename__ = "respuestas_oferta"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    peticion_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    proveedor_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    coste_unitario: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    # Sin plazo no se inventa una fecha: se dice que no se puede prometer.
    plazo_dias: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recibida_el: Mapped[date] = mapped_column(Date, nullable=False)
    notas: Mapped[str] = mapped_column(Text, nullable=False, default="")
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="recibida")
    # Lo que se le adjudicó, y lo que pasó: es lo que mide al proveedor.
    cantidad_adjudicada: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    fecha_comprometida: Mapped[date | None] = mapped_column(Date, nullable=True)
    entregada_el: Mapped[date | None] = mapped_column(Date, nullable=True)
    coste_final: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    incidencias: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "peticion_id", "proveedor_id", name="uq_respuesta_oferta"),
    )


class CapacidadProveedor(Base, TimestampMixin):
    """Cuánto puede servir un proveedor en un periodo (CRM-09.02.01.06)."""

    __tablename__ = "capacidades_proveedor"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    proveedor_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    categoria: Mapped[str] = mapped_column(String(80), nullable=False)
    desde: Mapped[date] = mapped_column(Date, nullable=False)
    hasta: Mapped[date] = mapped_column(Date, nullable=False)
    unidad: Mapped[str] = mapped_column(String(20), nullable=False, default="ud")
    contratada: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)

    __table_args__ = (Index("ix_capacidades_periodo", "tenant_id", "proveedor_id", "desde"),)


class ReservaCapacidad(Base, TimestampMixin):
    """Lo comprometido contra una capacidad: firme o todavía en oferta."""

    __tablename__ = "reservas_capacidad"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    capacidad_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    respuesta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    oportunidad_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    cantidad: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    # Firme: adjudicado. No firme: en una oferta abierta, que todavía no compromete
    # pero tampoco cabría si se ganaran todas.
    firme: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Reservado por encima de lo disponible a sabiendas. Queda dicho.
    forzada: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    motivo: Mapped[str] = mapped_column(Text, nullable=False, default="")


class AcuerdoRappel(Base, TimestampMixin):
    """Los tramos de rappel de un proveedor en un periodo (CRM-09.02.01.09)."""

    __tablename__ = "acuerdos_rappel"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    proveedor_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    desde: Mapped[date] = mapped_column(Date, nullable=False)
    hasta: Mapped[date] = mapped_column(Date, nullable=False)
    # [{"desde": 10000, "pct": 2}, …]: el mismo formato que el cálculo.
    tramos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    cerrado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ContratoProveedor(Base, TimestampMixin):
    """El contrato con un proveedor: vigencia, renovación y preaviso (CRM-09.01.01.07)."""

    __tablename__ = "contratos_proveedor"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    proveedor_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    numero: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    vigente_desde: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Sin fecha no es indefinido: es que nadie la ha escrito, y se dice.
    vigente_hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    renovacion_automatica: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dias_preaviso: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notas: Mapped[str] = mapped_column(Text, nullable=False, default="")


class AlcanceProveedor(Base, TimestampMixin):
    """Qué puede servir un proveedor, en positivo (CRM-09.01.01.09)."""

    __tablename__ = "alcances_proveedor"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    proveedor_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # Por eje —categoría, geografía, cliente, canal—: lo que no está, no se puede
    # comprometer. Un eje vacío es «cualquiera», y eso se dice.
    alcance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (UniqueConstraint("tenant_id", "proveedor_id", name="uq_alcance_proveedor"),)


# ── Ayudantes ─────────────────────────────────────────────────────────────


def _uno(db: Session, modelo: type, registro_id: UUID, tenant_id: UUID, nombre: str) -> Any:
    fila = db.get(modelo, registro_id)
    if fila is None or fila.tenant_id != tenant_id:
        raise NoEncontrado(f"No existe ese registro de {nombre}", error_code=f"compras.{nombre}")
    return fila


def _nombre(db: Session, tenant_id: UUID, cuenta_id: UUID) -> str:
    from services.party.modelos import Cuenta

    cuenta = db.get(Cuenta, cuenta_id)
    return cuenta.nombre if cuenta is not None and cuenta.tenant_id == tenant_id else str(cuenta_id)


def _respuestas(db: Session, tenant_id: UUID, **filtros: Any) -> list[RespuestaOferta]:
    consulta = select(RespuestaOferta).where(RespuestaOferta.tenant_id == tenant_id)
    for campo, valor in filtros.items():
        consulta = consulta.where(getattr(RespuestaOferta, campo) == valor)
    return list(db.execute(consulta.order_by(RespuestaOferta.recibida_el)).scalars())


def _categorias_de(db: Session, tenant_id: UUID, proveedor_id: UUID) -> list[str]:
    return [
        h.categoria
        for h in db.execute(
            select(prv.Homologacion).where(
                prv.Homologacion.tenant_id == tenant_id,
                prv.Homologacion.cuenta_id == proveedor_id,
            )
        ).scalars()
    ]


def _alternativas(db: Session, tenant_id: UUID, proveedor_id: UUID, hoy: date) -> list[str]:
    """Otros proveedores homologados hoy para alguna de sus categorías."""
    salida: set[str] = set()
    for categoria in _categorias_de(db, tenant_id, proveedor_id):
        for h in db.execute(
            select(prv.Homologacion).where(
                prv.Homologacion.tenant_id == tenant_id,
                prv.Homologacion.categoria == categoria,
                prv.Homologacion.cuenta_id != proveedor_id,
            )
        ).scalars():
            if prv.esta_homologado(
                db, tenant_id, cuenta_id=h.cuenta_id, categoria=categoria, hoy=hoy
            )["puede"]:
                salida.add(str(h.cuenta_id))
    return sorted(salida)


def _compromisos_abiertos(db: Session, tenant_id: UUID, proveedor_id: UUID) -> list[dict[str, Any]]:
    """Lo adjudicado y todavía sin entregar: lo que hay vendido con él detrás."""
    salida = []
    for r in _respuestas(db, tenant_id, proveedor_id=proveedor_id, estado="adjudicada"):
        if r.entregada_el is not None:
            continue
        peticion = db.get(PeticionOferta, r.peticion_id)
        salida.append(
            {
                "referencia": (peticion.descripcion if peticion else "") or str(r.id),
                "fecha": r.fecha_comprometida,
                "respuesta_id": str(r.id),
                "oportunidad_id": (
                    str(peticion.oportunidad_id) if peticion and peticion.oportunidad_id else None
                ),
            }
        )
    return salida


# ── Petición de oferta y respuestas (CRM-09.02.01.05) ─────────────────────


def crear_peticion(
    uow: UnidadDeTrabajo,
    *,
    categoria: str,
    proveedores: list[UUID],
    fecha_limite: date,
    descripcion: str = "",
    cantidad: Decimal = Decimal(1),
    unidad: str = "ud",
    fecha_necesaria: date | None = None,
    oportunidad_id: UUID | None = None,
) -> tuple[PeticionOferta, str]:
    """Crea la petición con las comprobaciones del cálculo de siempre: con
    proveedores, con algo que pedir y con una fecha límite que no ha pasado."""
    db, tenant_id = uow.db, uow.tenant_id
    for proveedor in proveedores:
        prv.exigir_proveedor(db, tenant_id, proveedor)
    plan = cst.preparar_peticion(
        proveedores=proveedores,
        lineas=[{"descripcion": descripcion or categoria, "cantidad": str(cantidad)}],
        fecha_limite=fecha_limite,
        oportunidad_id=oportunidad_id,
        hoy=hoy_del_cliente(db),
    )
    fila = PeticionOferta(
        tenant_id=tenant_id,
        oportunidad_id=oportunidad_id,
        categoria=categoria,
        descripcion=descripcion,
        cantidad=cantidad,
        unidad=unidad,
        fecha_limite=fecha_limite,
        fecha_necesaria=fecha_necesaria,
        proveedores=[str(p) for p in proveedores],
    )
    db.add(fila)
    db.flush()
    return fila, plan["aviso"]


def registrar_respuesta(
    uow: UnidadDeTrabajo,
    peticion_id: UUID,
    *,
    proveedor_id: UUID,
    coste_unitario: Decimal,
    plazo_dias: int | None = None,
    moneda: str = "EUR",
    recibida_el: date | None = None,
    notas: str = "",
) -> RespuestaOferta:
    db, tenant_id = uow.db, uow.tenant_id
    peticion = _uno(db, PeticionOferta, peticion_id, tenant_id, "peticion")
    # Sólo contesta a quien se le pidió: una respuesta de otro no compara con
    # nada y descoloca el «quién no ha contestado».
    if str(proveedor_id) not in [str(p) for p in peticion.proveedores]:
        raise ErrorValidacion(
            "A ese proveedor no se le pidió oferta en esta petición.",
            error_code="compras.no_se_le_pidio",
        )
    if peticion.estado != "abierta":
        raise Conflicto(
            "La petición ya no está abierta: se adjudicó o se cerró.",
            error_code="compras.peticion_cerrada",
        )
    if _respuestas(db, tenant_id, peticion_id=peticion.id, proveedor_id=proveedor_id):
        raise Conflicto(
            "Ese proveedor ya contestó a esta petición. Si cambió su oferta, edita la "
            "respuesta: dos respuestas del mismo proveedor cuentan dos veces.",
            error_code="compras.respuesta_ya_existe",
        )
    fila = RespuestaOferta(
        tenant_id=tenant_id,
        peticion_id=peticion.id,
        proveedor_id=proveedor_id,
        coste_unitario=coste_unitario,
        plazo_dias=plazo_dias,
        moneda=moneda,
        recibida_el=recibida_el or hoy_del_cliente(db),
        notas=notas,
    )
    db.add(fila)
    db.flush()
    return fila


def quien_ha_contestado(db: Session, tenant_id: UUID, peticion_id: UUID) -> dict[str, Any]:
    peticion = _uno(db, PeticionOferta, peticion_id, tenant_id, "peticion")
    respuestas = _respuestas(db, tenant_id, peticion_id=peticion.id)
    salida = cst.recoger_respuestas(
        pedidas_a=[UUID(str(p)) for p in peticion.proveedores],
        respuestas=[
            {"proveedor_id": str(r.proveedor_id), "recibida_el": r.recibida_el} for r in respuestas
        ],
        fecha_limite=peticion.fecha_limite,
        hoy=hoy_del_cliente(db),
    )
    # Con nombre: «faltan tres identificadores» no le dice a nadie a quién llamar.
    salida["sin_contestar"] = [
        {"proveedor_id": p, "nombre": _nombre(db, tenant_id, UUID(p))}
        for p in salida["sin_contestar"]
    ]
    return salida


# ── Comparar (CRM-09.02.01.04) y fecha prometible (CRM-09.02.01.07) ──────


def _dias_propios(db: Session) -> int:
    return int(efectivo("compras_dias_propios_entrega", db))


def fecha_prometible(db: Session, tenant_id: UUID, respuesta_id: UUID) -> dict[str, Any]:
    respuesta = _uno(db, RespuestaOferta, respuesta_id, tenant_id, "respuesta")
    return cst.fecha_que_se_puede_prometer(
        plazo_proveedor_dias=respuesta.plazo_dias,
        dias_propios=_dias_propios(db),
        desde=hoy_del_cliente(db),
    )


def comparar(db: Session, tenant_id: UUID, peticion_id: UUID) -> dict[str, Any]:
    """Las respuestas guardadas, con la homologación y los papeles de cada uno.

    Lo que antes había que escribir a mano —si está homologado, si tiene papeles
    vencidos, cuándo entrega— sale de lo que ya consta: la homologación para la
    categoría de la petición, el estado documental y la fecha que se puede
    prometer con su plazo.
    """
    peticion = _uno(db, PeticionOferta, peticion_id, tenant_id, "peticion")
    hoy = hoy_del_cliente(db)
    ofertas = []
    for r in _respuestas(db, tenant_id, peticion_id=peticion.id):
        if r.estado == "descartada":
            continue
        promesa = cst.fecha_que_se_puede_prometer(
            plazo_proveedor_dias=r.plazo_dias, dias_propios=_dias_propios(db), desde=hoy
        )
        ofertas.append(
            {
                "proveedor_id": r.proveedor_id,
                "nombre": _nombre(db, tenant_id, r.proveedor_id),
                "coste": r.coste_unitario,
                "homologado": prv.esta_homologado(
                    db, tenant_id, cuenta_id=r.proveedor_id, categoria=peticion.categoria, hoy=hoy
                )["puede"],
                "documentos_vencidos": prv.estado_documental(
                    db, tenant_id, cuenta_id=r.proveedor_id, hoy=hoy
                )["bloqueado"],
                "fecha_entrega": (
                    date.fromisoformat(promesa["fecha"]) if promesa.get("fecha") else None
                ),
            }
        )
    salida = cst.comparar_proveedores(ofertas=ofertas, fecha_necesaria=peticion.fecha_necesaria)
    salida["recogida"] = quien_ha_contestado(db, tenant_id, peticion.id)
    return salida


# ── Capacidad (CRM-09.02.01.06) y reparto (CRM-09.02.01.08) ──────────────


def _reservas(db: Session, capacidad: CapacidadProveedor) -> list[ReservaCapacidad]:
    return list(
        db.execute(
            select(ReservaCapacidad).where(
                ReservaCapacidad.tenant_id == capacidad.tenant_id,
                ReservaCapacidad.capacidad_id == capacidad.id,
            )
        ).scalars()
    )


def disponible(db: Session, tenant_id: UUID, capacidad_id: UUID) -> dict[str, Any]:
    capacidad = _uno(db, CapacidadProveedor, capacidad_id, tenant_id, "capacidad")
    reservas = _reservas(db, capacidad)
    return cst.capacidad_disponible(
        contratada=Decimal(capacidad.contratada),
        ya_comprometida=sum((Decimal(r.cantidad) for r in reservas if r.firme), Decimal(0)),
        en_ofertas_abiertas=sum((Decimal(r.cantidad) for r in reservas if not r.firme), Decimal(0)),
    )


def reservar(
    uow: UnidadDeTrabajo,
    capacidad_id: UUID,
    *,
    cantidad: Decimal,
    firme: bool = True,
    forzar: bool = False,
    motivo: str = "",
    oportunidad_id: UUID | None = None,
    respuesta_id: UUID | None = None,
) -> dict[str, Any]:
    db, tenant_id = uow.db, uow.tenant_id
    capacidad = _uno(db, CapacidadProveedor, capacidad_id, tenant_id, "capacidad")
    libre = Decimal(disponible(db, tenant_id, capacidad.id)["libre"])
    if forzar and not motivo.strip():
        raise ErrorValidacion(
            "Reservar por encima de lo disponible se puede, diciendo por qué.",
            error_code="capacidad.forzar_sin_motivo",
        )
    resultado = cst.reservar(disponible=libre, cantidad=cantidad, permitir_exceso=forzar)
    db.add(
        ReservaCapacidad(
            tenant_id=tenant_id,
            capacidad_id=capacidad.id,
            cantidad=cantidad,
            firme=firme,
            forzada=Decimal(cantidad) > libre,
            motivo=motivo,
            oportunidad_id=oportunidad_id,
            respuesta_id=respuesta_id,
        )
    )
    db.flush()
    return resultado


def _capacidad_vigente(
    db: Session, tenant_id: UUID, proveedor_id: UUID, categoria: str, dia: date
) -> CapacidadProveedor | None:
    return (
        db.execute(
            select(CapacidadProveedor)
            .where(
                CapacidadProveedor.tenant_id == tenant_id,
                CapacidadProveedor.proveedor_id == proveedor_id,
                CapacidadProveedor.categoria == categoria,
                CapacidadProveedor.desde <= dia,
                CapacidadProveedor.hasta >= dia,
            )
            .order_by(CapacidadProveedor.desde.desc())
        )
        .scalars()
        .first()
    )


def repartir(
    db: Session, tenant_id: UUID, peticion_id: UUID, *, regla: str = "menor_coste"
) -> dict[str, Any]:
    """Reparte la cantidad de la petición entre quienes contestaron, con su
    capacidad libre de verdad. Quien no tiene capacidad declarada no entra, y se
    dice: callarlo haría creer que se consideró."""
    peticion = _uno(db, PeticionOferta, peticion_id, tenant_id, "peticion")
    hoy = hoy_del_cliente(db)
    candidatos = []
    sin_capacidad: list[str] = []
    for r in _respuestas(db, tenant_id, peticion_id=peticion.id):
        if r.estado == "descartada":
            continue
        capacidad = _capacidad_vigente(db, tenant_id, r.proveedor_id, peticion.categoria, hoy)
        nombre = _nombre(db, tenant_id, r.proveedor_id)
        if capacidad is None:
            sin_capacidad.append(nombre)
            continue
        candidatos.append(
            {
                "id": r.proveedor_id,
                "nombre": nombre,
                "coste": r.coste_unitario,
                "plazo_dias": r.plazo_dias,
                "homologado": prv.esta_homologado(
                    db, tenant_id, cuenta_id=r.proveedor_id, categoria=peticion.categoria, hoy=hoy
                )["puede"],
                "libre": disponible(db, tenant_id, capacidad.id)["libre"],
            }
        )
    salida = cst.repartir(candidatos=candidatos, cantidad=Decimal(peticion.cantidad), regla=regla)
    salida["sin_capacidad_declarada"] = sin_capacidad
    return salida


# ── Adjudicar, entregar, incidencias ──────────────────────────────────────


def adjudicar(
    uow: UnidadDeTrabajo,
    respuesta_id: UUID,
    *,
    cantidad: Decimal | None = None,
    forzar: bool = False,
    motivo: str = "",
) -> dict[str, Any]:
    """Elige una respuesta. Compromete su capacidad si la hay declarada, y fija
    la fecha comprometida con su plazo: es contra lo que se medirá la entrega."""
    db, tenant_id = uow.db, uow.tenant_id
    respuesta = _uno(db, RespuestaOferta, respuesta_id, tenant_id, "respuesta")
    peticion = _uno(db, PeticionOferta, respuesta.peticion_id, tenant_id, "peticion")
    if respuesta.estado != "recibida":
        raise Conflicto(
            f"Esta respuesta ya está {respuesta.estado}.", error_code="compras.respuesta_no_libre"
        )
    hoy = hoy_del_cliente(db)
    if not prv.esta_homologado(
        db, tenant_id, cuenta_id=respuesta.proveedor_id, categoria=peticion.categoria, hoy=hoy
    )["puede"]:
        raise Conflicto(
            f"No está homologado para «{peticion.categoria}». Adjudicarle es encargarle "
            "algo a quien no debe hacerlo.",
            error_code="compras.sin_homologar",
        )
    cuanto = Decimal(cantidad if cantidad is not None else peticion.cantidad)
    capacidad = _capacidad_vigente(db, tenant_id, respuesta.proveedor_id, peticion.categoria, hoy)
    reserva = None
    if capacidad is not None:
        reserva = reservar(
            uow,
            capacidad.id,
            cantidad=cuanto,
            firme=True,
            forzar=forzar,
            motivo=motivo,
            oportunidad_id=peticion.oportunidad_id,
            respuesta_id=respuesta.id,
        )
    promesa = cst.fecha_que_se_puede_prometer(
        plazo_proveedor_dias=respuesta.plazo_dias, dias_propios=_dias_propios(db), desde=hoy
    )
    respuesta.estado = "adjudicada"
    respuesta.cantidad_adjudicada = cuanto
    respuesta.fecha_comprometida = (
        date.fromisoformat(promesa["fecha"]) if promesa.get("fecha") else None
    )
    peticion.estado = "adjudicada"
    db.flush()
    return {
        "adjudicada": True,
        "fecha_comprometida": (
            respuesta.fecha_comprometida.isoformat() if respuesta.fecha_comprometida else None
        ),
        "capacidad": reserva,
        "aviso": (
            "Este proveedor no tiene capacidad declarada para el periodo: no se ha "
            "descontado de ninguna parte."
            if capacidad is None
            else ""
        ),
    }


def anotar_entrega(
    uow: UnidadDeTrabajo,
    respuesta_id: UUID,
    *,
    entregada_el: date | None = None,
    coste_final: Decimal | None = None,
) -> RespuestaOferta:
    db, tenant_id = uow.db, uow.tenant_id
    respuesta = _uno(db, RespuestaOferta, respuesta_id, tenant_id, "respuesta")
    if respuesta.estado != "adjudicada":
        raise Conflicto(
            "Sólo se entrega lo adjudicado.", error_code="compras.entrega_sin_adjudicar"
        )
    respuesta.entregada_el = entregada_el or hoy_del_cliente(db)
    if coste_final is not None:
        respuesta.coste_final = coste_final
    db.flush()
    return respuesta


def anotar_incidencia(
    uow: UnidadDeTrabajo, respuesta_id: UUID, *, gravedad: str, descripcion: str
) -> RespuestaOferta:
    db, tenant_id = uow.db, uow.tenant_id
    if gravedad not in GRAVEDADES:
        raise ErrorValidacion(
            f"Gravedad «{gravedad}» no válida.",
            error_code="compras.gravedad",
            detalle={"validas": list(GRAVEDADES)},
        )
    respuesta = _uno(db, RespuestaOferta, respuesta_id, tenant_id, "respuesta")
    respuesta.incidencias = [
        *(respuesta.incidencias or []),
        {
            "gravedad": gravedad,
            "descripcion": descripcion,
            "fecha": hoy_del_cliente(db).isoformat(),
        },
    ]
    db.flush()
    return respuesta


# ── Rappel (CRM-09.02.01.09) ──────────────────────────────────────────────


def rappel(db: Session, tenant_id: UUID, acuerdo_id: UUID) -> dict[str, Any]:
    """Con la compra de verdad: lo adjudicado al proveedor dentro del periodo,
    al coste final si consta y al ofertado si no."""
    acuerdo = _uno(db, AcuerdoRappel, acuerdo_id, tenant_id, "rappel")
    compra = Decimal(0)
    for r in _respuestas(db, tenant_id, proveedor_id=acuerdo.proveedor_id, estado="adjudicada"):
        if not (acuerdo.desde <= r.recibida_el <= acuerdo.hasta):
            continue
        unitario = Decimal(r.coste_final if r.coste_final is not None else r.coste_unitario)
        compra += unitario * Decimal(r.cantidad_adjudicada or 0)
    salida = cst.rappel_estimado(
        compra_acumulada=compra, tramos=list(acuerdo.tramos or []), cerrado=acuerdo.cerrado
    )
    salida["compra_acumulada"] = str(compra)
    return salida


# ── Contrato (CRM-09.01.01.07) y alcance (CRM-09.01.01.09) ───────────────


def estado_del_contrato(db: Session, tenant_id: UUID, contrato_id: UUID) -> dict[str, Any]:
    """Avisa por lo que hay vendido con el proveedor detrás, no por la fecha:
    los compromisos son las adjudicaciones sin entregar."""
    contrato = _uno(db, ContratoProveedor, contrato_id, tenant_id, "contrato")
    return pcom.estado_del_contrato(
        vigente_hasta=contrato.vigente_hasta,
        renovacion_automatica=contrato.renovacion_automatica,
        dias_preaviso=contrato.dias_preaviso,
        compromisos_con_clientes=_compromisos_abiertos(db, tenant_id, contrato.proveedor_id),
        hoy=hoy_del_cliente(db),
    )


def puede_servir(
    db: Session,
    tenant_id: UUID,
    proveedor_id: UUID,
    *,
    categoria: str = "",
    geografia: str = "",
    cliente_id: str | None = None,
) -> dict[str, Any]:
    fila = db.execute(
        select(AlcanceProveedor).where(
            AlcanceProveedor.tenant_id == tenant_id,
            AlcanceProveedor.proveedor_id == proveedor_id,
        )
    ).scalar_one_or_none()
    if fila is None:
        return {
            "puede": False,
            "porque": (
                "No tiene alcance declarado. Lo que no está declarado no se puede "
                "comprometer: suponer que sirve para todo es como se le encarga algo "
                "que no hace."
            ),
        }
    return pcom.puede_servir(
        alcance=dict(fila.alcance or {}),
        categoria=categoria,
        geografia=geografia,
        cliente_id=cliente_id,
    )


# ── Riesgo (CRM-09.01.01.04), evaluación (.05) y baja (.10) ───────────────


def riesgo_de_dependencia(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """La concentración sale de lo comprado de verdad: lo adjudicado a cada uno."""
    hoy = hoy_del_cliente(db)
    volumen: dict[UUID, Decimal] = {}
    for r in _respuestas(db, tenant_id, estado="adjudicada"):
        unitario = Decimal(r.coste_final if r.coste_final is not None else r.coste_unitario)
        volumen[r.proveedor_id] = volumen.get(r.proveedor_id, Decimal(0)) + unitario * Decimal(
            r.cantidad_adjudicada or 0
        )
    return prv.riesgo_de_dependencia(
        proveedores=[
            {
                "id": proveedor,
                "nombre": _nombre(db, tenant_id, proveedor),
                "volumen": float(cuanto),
                "alternativas_homologadas": _alternativas(db, tenant_id, proveedor, hoy),
            }
            for proveedor, cuanto in volumen.items()
        ],
        umbral_concentracion=float(efectivo("riesgo_concentracion_pct", db)),
    )


def evaluacion(db: Session, tenant_id: UUID, proveedor_id: UUID) -> dict[str, Any]:
    """Con las entregas anotadas: en plazo si llegó para la fecha comprometida."""
    entregas: list[dict[str, Any]] = []
    incidencias: list[dict[str, Any]] = []
    for r in _respuestas(db, tenant_id, proveedor_id=proveedor_id, estado="adjudicada"):
        incidencias.extend(r.incidencias or [])
        if r.entregada_el is None:
            continue
        entregas.append(
            {
                "en_plazo": r.fecha_comprometida is None or r.entregada_el <= r.fecha_comprometida,
                "desvio_coste": (
                    str(Decimal(r.coste_final) - Decimal(r.coste_unitario))
                    if r.coste_final is not None
                    else None
                ),
            }
        )
    salida = prv.evaluar(entregas=entregas, incidencias=incidencias)
    desvios = [Decimal(e["desvio_coste"]) for e in entregas if e["desvio_coste"] is not None]
    salida["entregas_con_coste_final"] = len(desvios)
    salida["desvio_coste_medio"] = str(sum(desvios, Decimal(0)) / len(desvios)) if desvios else None
    return salida


def puede_darse_de_baja(db: Session, tenant_id: UUID, proveedor_id: UUID) -> dict[str, Any]:
    """Con lo comprometido de verdad y las alternativas homologadas que constan."""
    prv.exigir_proveedor(db, tenant_id, proveedor_id)
    return prv.puede_darse_de_baja(
        compromisos_abiertos=_compromisos_abiertos(db, tenant_id, proveedor_id),
        alternativas_homologadas=len(
            _alternativas(db, tenant_id, proveedor_id, hoy_del_cliente(db))
        ),
    )
