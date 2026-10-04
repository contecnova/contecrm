"""Presupuestos, contratos, suscripciones y renovaciones
(CRM-03.03.02.01, CRM-03.03.02.04, CRM-03.03.02.05, CRM-03.03.02.08,
CRM-03.03.02.09, CRM-03.03.02.10, CRM-03.03.02.11).

Un presupuesto es lo primero que el cliente ve por escrito, y por eso es lo
primero que se discute. Cuatro decisiones salen de ahí:

**Un presupuesto no se edita: se versiona.** La versión 2 es otro documento, no la
1 corregida. Editar en sitio hace imposible responder a «esto no es lo que me
mandaste», que es la conversación que de verdad ocurre.

**El descuento se decide contra el margen, no contra el porcentaje.** Un 20 % sobre
un producto con 60 puntos de margen y un 20 % sobre uno con 12 son cosas
distintas, y la matriz que solo mira el porcentaje aprueba la segunda.

**Una línea guarda lo que se ofreció, no lo que dice el catálogo hoy.** Es la misma
regla que ya seguía la oportunidad, y por el mismo motivo: si mañana sube el
precio, el presupuesto de ayer tiene que seguir diciendo lo de ayer.

**Lo que se manda al ERP vuelve, o no está hecho.** Un traspaso que se da por
bueno porque la llamada no dio error es cómo se descubre en el cierre de mes que
faltan pedidos.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.db.base import Base, EntidadBase, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.fechas import hoy
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
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

from services.sales import catalogo as cat

logger = get_logger(__name__)

CENTIMO = Decimal("0.01")

ESTADOS_PRESUPUESTO = (
    "borrador",
    "en_aprobacion",
    "aprobado",
    "enviado",
    "aceptado",
    "rechazado",
    "caducado",
    "sustituido",
)
ESTADOS_CONTRATO = ("borrador", "vigente", "suspendido", "terminado", "renovado")
ESTADOS_PEDIDO = ("pendiente", "enviado_erp", "confirmado", "rechazado_erp", "conciliado")


class Presupuesto(EntidadBase, SoftDeleteMixin):
    """Una oferta con fecha, versión y estado (CRM-03.03.02.01)."""

    __tablename__ = "presupuestos"

    numero: Mapped[str] = mapped_column(String(60), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # La versión anterior, si la hay. La cadena completa es lo que permite
    # enseñar qué cambió entre la 1 y la 3 sin guardar diferencias a mano.
    anterior_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    oportunidad_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, index=True
    )
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    contacto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    titulo: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    # Sin `index=True`: SQLAlchemy lo llamaría `ix_presupuestos_estado`, que es
    # el nombre del índice compuesto de abajo, y el segundo choca con el primero.
    # El compuesto ya sirve para filtrar por estado, porque empieza por él.
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="borrador")
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    canal: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    idioma: Mapped[str] = mapped_column(String(10), nullable=False, default="es")
    marca: Mapped[str] = mapped_column(String(60), nullable=False, default="")

    # Vigencia. Un presupuesto sin fecha de caducidad se convierte en un precio
    # eterno, y el cliente lo saca dos años después.
    valido_hasta: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    enviado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    aceptado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    descuento_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    coste_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    margen_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)

    # La aprobación, cuando hace falta. El identificador es opaco: la solicitud
    # vive en `orchestrator` y ningún servicio lee el esquema de otro.
    aprobacion_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    motivo_aprobacion: Mapped[str] = mapped_column(Text, nullable=False, default="")

    notas: Mapped[str] = mapped_column(Text, nullable=False, default="")
    condiciones: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("tenant_id", "numero", "version", name="uq_presupuesto_version"),
        Index("ix_presupuestos_estado", "tenant_id", "estado", "valido_hasta"),
    )


class LineaPresupuesto(Base, TimestampMixin):
    """Una línea, con lo que se ofreció congelado dentro."""

    __tablename__ = "lineas_presupuesto"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    presupuesto_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("presupuestos.id", ondelete="CASCADE"), nullable=False
    )
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    producto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    sku: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    descripcion: Mapped[str] = mapped_column(String(300), nullable=False)
    familia: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cantidad: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=1)

    # El precio de catálogo y el que sale de las listas, los dos. La diferencia
    # entre ellos es el descuento que damos SIN que nadie lo pida, y sin
    # guardarlo no se puede medir.
    precio_catalogo: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    precio_tarifa: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    # El descuento que mete el comercial encima de la tarifa.
    descuento_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    precio_final: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)

    coste_unitario: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    margen_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)

    tipo_ingreso: Mapped[str] = mapped_column(String(20), nullable=False, default="puntual")
    periodicidad: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Cómo se calculó el precio. Es la explicación que se enseña cuando el
    # cliente pregunta, y la que evita rehacer el cálculo para auditarlo.
    explicacion: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    __table_args__ = (Index("ix_lineas_presupuesto", "tenant_id", "presupuesto_id", "orden"),)


class Contrato(EntidadBase, SoftDeleteMixin):
    """Lo que se firma y obliga (CRM-03.03.02.08)."""

    __tablename__ = "contratos"

    numero: Mapped[str] = mapped_column(String(60), nullable=False)
    cuenta_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    presupuesto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    titulo: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="borrador", index=True)

    inicio: Mapped[date] = mapped_column(Date, nullable=False)
    fin: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    # Renovación automática y preaviso. El preaviso es la fecha que importa: el
    # día del vencimiento ya es tarde para no renovar.
    renovacion_automatica: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    preaviso_dias: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    meses_renovacion: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    renovado_de_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # Se avisó del preaviso. Sin esta marca, el aviso se manda cada noche hasta
    # que alguien lo silencia apagando la alerta entera.
    preaviso_dado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    importe: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    clausulas: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "numero", name="uq_contrato_numero"),
        Index("ix_contratos_vencimiento", "tenant_id", "estado", "fin"),
    )


class SuscripcionCliente(EntidadBase, SoftDeleteMixin):
    """Ingreso recurrente con su ciclo (CRM-03.03.02.09).

    Se llama `SuscripcionCliente` y no `Suscripcion` porque `eventing` ya tiene
    una `Suscripcion` —la de un webhook—. No es cosmético: el gate de aislamiento
    entre tenants indexa los modelos **por nombre de clase**, así que dos con el
    mismo nombre hacen que uno pise al otro y esa ruta se deje de probar sin que
    nadie se entere.
    """

    __tablename__ = "suscripciones"

    contrato_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    cuenta_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    producto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    plan: Mapped[str] = mapped_column(String(120), nullable=False)
    cantidad: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=1)
    importe_periodo: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    # mensual | trimestral | anual
    periodicidad: Mapped[str] = mapped_column(String(20), nullable=False, default="mensual")
    inicio: Mapped[date] = mapped_column(Date, nullable=False)
    fin: Mapped[date | None] = mapped_column(Date, nullable=True)
    # activa | pausada | cancelada
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="activa", index=True)
    proxima_factura: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    __table_args__ = (Index("ix_suscripciones_cuenta", "tenant_id", "cuenta_id", "estado"),)


class CambioSuscripcion(Base):
    """Alta, baja o cambio de plan, con su prorrateo. Append-only."""

    __tablename__ = "cambios_suscripcion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    suscripcion_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("suscripciones.id", ondelete="CASCADE"), nullable=False
    )
    # alta | cambio_plan | cambio_cantidad | pausa | reanudacion | baja
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    efectivo_el: Mapped[date] = mapped_column(Date, nullable=False)
    plan_antes: Mapped[str | None] = mapped_column(String(120), nullable=True)
    plan_despues: Mapped[str | None] = mapped_column(String(120), nullable=True)
    importe_antes: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    importe_despues: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    # Lo que se cobra o se abona por los días del periodo en curso.
    prorrateo: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    motivo: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_cambios_suscripcion", "tenant_id", "suscripcion_id", "efectivo_el"),
    )


class Pedido(EntidadBase, SoftDeleteMixin):
    """Lo aceptado, camino del ERP (CRM-03.03.02.11)."""

    __tablename__ = "pedidos"

    numero: Mapped[str] = mapped_column(String(60), nullable=False)
    presupuesto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    cuenta_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente", index=True)
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")

    # Lo que dice el ERP. `referencia_erp` es la que se cita por teléfono; el
    # estado y la fecha de conciliación dicen si el traspaso terminó de verdad.
    referencia_erp: Mapped[str | None] = mapped_column(String(120), nullable=True)
    enviado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    conciliado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_erp: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Lo que el ERP devolvió, tal cual. Es lo que se cita al reclamarle.
    respuesta_erp: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "numero", name="uq_pedido_numero"),
        Index("ix_pedidos_traspaso", "tenant_id", "estado", "enviado_at"),
    )


# ── Utilidades ────────────────────────────────────────────────────────────


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _redondear(v: Decimal) -> Decimal:
    return Decimal(v).quantize(CENTIMO, rounding=ROUND_HALF_UP)


def _siguiente(db: Session, tenant_id: UUID, modelo: Any, prefijo: str) -> str:
    cuantos = int(
        db.execute(
            select(func.count()).select_from(modelo).where(modelo.tenant_id == tenant_id)
        ).scalar_one()
        or 0
    )
    return f"{prefijo}-{hoy(db).year}-{cuantos + 1:05d}"


# ── Presupuestos (CRM-03.03.02.01, CRM-03.03.02.05) ───────────────────────


def _totalizar(db: Session, presupuesto: Presupuesto) -> None:
    """Recalcula totales y margen del presupuesto a partir de sus líneas."""
    lineas = (
        db.execute(
            select(LineaPresupuesto).where(LineaPresupuesto.presupuesto_id == presupuesto.id)
        )
        .scalars()
        .all()
    )
    subtotal = sum(
        (Decimal(ln.precio_catalogo) * Decimal(ln.cantidad) for ln in lineas), Decimal(0)
    )
    total = sum((Decimal(ln.total) for ln in lineas), Decimal(0))
    # El coste solo se suma si se conoce en TODAS las líneas. Con una sola sin
    # coste, el margen del presupuesto saldría inflado y se usaría para aprobar
    # un descuento que no se puede dar.
    costes = [ln.coste_unitario for ln in lineas]
    coste_total: Decimal | None = None
    if lineas and all(c is not None for c in costes):
        coste_total = sum(
            (Decimal(ln.coste_unitario) * Decimal(ln.cantidad) for ln in lineas), Decimal(0)
        )

    presupuesto.subtotal = _redondear(subtotal)
    presupuesto.total = _redondear(total)
    presupuesto.descuento_total = _redondear(subtotal - total)
    presupuesto.coste_total = _redondear(coste_total) if coste_total is not None else None
    presupuesto.margen_pct = (
        _redondear((total - coste_total) / total * Decimal(100))
        if coste_total is not None and total > 0
        else None
    )


def crear(
    uow: UnidadDeTrabajo,
    *,
    lineas: list[dict[str, Any]],
    cuenta_id: UUID | None = None,
    oportunidad_id: UUID | None = None,
    contacto_id: UUID | None = None,
    titulo: str = "",
    moneda: str = "EUR",
    canal: str = "",
    idioma: str = "es",
    marca: str = "",
    dias_validez: int = 30,
    notas: str = "",
    condiciones: str = "",
) -> Presupuesto:
    """Crea un presupuesto calculando cada precio con el motor.

    El precio **no lo pone quien llama**: lo calcula el motor y el presupuesto
    guarda la explicación. Si lo trajera el llamante, el precio dependería de la
    pantalla que se usara, y dos canales darían dos números para el mismo cliente.
    """
    tenant_id = uow.tenant_id
    if not lineas:
        raise ErrorValidacion(
            "Un presupuesto sin líneas no ofrece nada.",
            error_code="presupuesto.sin_lineas",
        )

    configuracion = cat.comprobar_configuracion(uow.db, tenant_id, lineas)
    if not configuracion["valida"]:
        raise ErrorValidacion(
            "Esa combinación de productos no se puede vender junta.",
            error_code="presupuesto.configuracion_invalida",
            detalle={"problemas": configuracion["problemas"]},
        )

    presupuesto = Presupuesto(
        tenant_id=tenant_id,
        numero=_siguiente(uow.db, tenant_id, Presupuesto, "PRE"),
        version=1,
        cuenta_id=cuenta_id,
        oportunidad_id=oportunidad_id,
        contacto_id=contacto_id,
        titulo=titulo,
        moneda=moneda,
        canal=canal,
        idioma=idioma,
        marca=marca,
        notas=notas,
        condiciones=condiciones,
        valido_hasta=hoy(uow.db) + timedelta(days=dias_validez),
    )
    uow.db.add(presupuesto)
    uow.db.flush()
    _volcar_lineas(uow.db, presupuesto, lineas, cuenta_id=cuenta_id, canal=canal, moneda=moneda)
    _totalizar(uow.db, presupuesto)
    uow.db.flush()

    uow.emitir(
        "quote.created",
        subject=("presupuesto", presupuesto.id),
        data={
            "presupuesto_id": str(presupuesto.id),
            "numero": presupuesto.numero,
            "version": presupuesto.version,
            "total": str(presupuesto.total),
            "moneda": moneda,
            "oportunidad_id": str(oportunidad_id) if oportunidad_id else "",
        },
    )
    return presupuesto


def _volcar_lineas(
    db: Session,
    presupuesto: Presupuesto,
    lineas: list[dict[str, Any]],
    *,
    cuenta_id: UUID | None,
    canal: str,
    moneda: str,
) -> None:
    for i, entrada in enumerate(lineas):
        producto_id = entrada.get("producto_id")
        cantidad = Decimal(str(entrada.get("cantidad", 1)))
        descuento = Decimal(str(entrada.get("descuento_pct", 0)))

        if producto_id:
            calculo = cat.calcular_precio(
                db,
                presupuesto.tenant_id,
                producto_id=UUID(str(producto_id)),
                cantidad=cantidad,
                cuenta_id=cuenta_id,
                canal=canal,
                moneda=moneda,
            )
            producto = db.get(cat.Producto, UUID(str(producto_id)))
            tarifa = Decimal(calculo["precio"])
            catalogo_precio = Decimal(calculo["precio_base"])
            coste = Decimal(calculo["coste"]) if calculo["coste"] else None
            descripcion = str(entrada.get("descripcion") or (producto.nombre if producto else ""))
            sku = producto.sku if producto else ""
            familia = producto.familia if producto else None
            tipo_ingreso = producto.tipo_ingreso if producto else "puntual"
            periodicidad = producto.periodicidad if producto else None
            explicacion = calculo["reglas_aplicadas"]
        else:
            # Línea libre: un concepto que no está en el catálogo. Se admite
            # porque en la práctica siempre hay uno —«portes», «puesta en
            # marcha»— y prohibirlo lleva a crear productos basura para
            # colarlos.
            tarifa = Decimal(str(entrada.get("precio_unitario", 0)))
            catalogo_precio = tarifa
            coste = (
                Decimal(str(entrada["coste_unitario"]))
                if entrada.get("coste_unitario") is not None
                else None
            )
            descripcion = str(entrada.get("descripcion") or "")
            sku = ""
            familia = None
            tipo_ingreso = str(entrada.get("tipo_ingreso") or "puntual")
            periodicidad = entrada.get("periodicidad")
            explicacion = []

        final = _redondear(tarifa * (Decimal(1) - descuento / Decimal(100)))
        db.add(
            LineaPresupuesto(
                tenant_id=presupuesto.tenant_id,
                presupuesto_id=presupuesto.id,
                orden=i,
                producto_id=UUID(str(producto_id)) if producto_id else None,
                sku=sku,
                descripcion=descripcion,
                familia=familia,
                cantidad=cantidad,
                precio_catalogo=catalogo_precio,
                precio_tarifa=tarifa,
                descuento_pct=descuento,
                precio_final=final,
                total=_redondear(final * cantidad),
                coste_unitario=coste,
                margen_pct=(
                    _redondear((final - coste) / final * Decimal(100))
                    if coste is not None and final > 0
                    else None
                ),
                tipo_ingreso=tipo_ingreso,
                periodicidad=periodicidad,
                explicacion=explicacion,
            )
        )
    db.flush()


def nueva_version(
    uow: UnidadDeTrabajo,
    presupuesto_id: UUID,
    *,
    lineas: list[dict[str, Any]] | None = None,
    **cambios: Any,
) -> Presupuesto:
    """Crea la versión siguiente. **La anterior no se toca.**

    Editar en sitio hace imposible responder a «esto no es lo que me mandaste»,
    que es la conversación que de verdad ocurre. La anterior queda `sustituido`,
    no borrada: sigue siendo lo que el cliente tiene en su correo.
    """
    tenant_id = uow.tenant_id
    viejo = uow.db.get(Presupuesto, presupuesto_id)
    if viejo is None or viejo.tenant_id != tenant_id:
        raise NoEncontrado("El presupuesto no existe", error_code="presupuesto.no_encontrado")
    if viejo.estado == "aceptado":
        raise Conflicto(
            "Ese presupuesto ya está aceptado: para cambiarlo hace falta un "
            "presupuesto nuevo, no otra versión del aceptado.",
            error_code="presupuesto.ya_aceptado",
        )

    nuevo = Presupuesto(
        tenant_id=tenant_id,
        numero=viejo.numero,
        version=viejo.version + 1,
        anterior_id=viejo.id,
        cuenta_id=viejo.cuenta_id,
        oportunidad_id=viejo.oportunidad_id,
        contacto_id=viejo.contacto_id,
        titulo=cambios.get("titulo", viejo.titulo),
        moneda=viejo.moneda,
        canal=viejo.canal,
        idioma=cambios.get("idioma", viejo.idioma),
        marca=cambios.get("marca", viejo.marca),
        notas=cambios.get("notas", viejo.notas),
        condiciones=cambios.get("condiciones", viejo.condiciones),
        valido_hasta=cambios.get("valido_hasta", viejo.valido_hasta),
    )
    uow.db.add(nuevo)
    uow.db.flush()

    if lineas is None:
        # Sin líneas nuevas se copian las de la versión anterior **tal cual**,
        # sin recalcular precios: si se recalcularan, cambiar una coma del
        # título movería el precio porque las tarifas habrían cambiado entre
        # medias, y nadie entendería por qué.
        for vieja in uow.db.execute(
            select(LineaPresupuesto)
            .where(LineaPresupuesto.presupuesto_id == viejo.id)
            .order_by(LineaPresupuesto.orden)
        ).scalars():
            uow.db.add(
                LineaPresupuesto(
                    tenant_id=tenant_id,
                    presupuesto_id=nuevo.id,
                    orden=vieja.orden,
                    producto_id=vieja.producto_id,
                    sku=vieja.sku,
                    descripcion=vieja.descripcion,
                    familia=vieja.familia,
                    cantidad=vieja.cantidad,
                    precio_catalogo=vieja.precio_catalogo,
                    precio_tarifa=vieja.precio_tarifa,
                    descuento_pct=vieja.descuento_pct,
                    precio_final=vieja.precio_final,
                    total=vieja.total,
                    coste_unitario=vieja.coste_unitario,
                    margen_pct=vieja.margen_pct,
                    tipo_ingreso=vieja.tipo_ingreso,
                    periodicidad=vieja.periodicidad,
                    explicacion=vieja.explicacion,
                )
            )
        uow.db.flush()
    else:
        _volcar_lineas(
            uow.db,
            nuevo,
            lineas,
            cuenta_id=viejo.cuenta_id,
            canal=viejo.canal,
            moneda=viejo.moneda,
        )

    _totalizar(uow.db, nuevo)
    viejo.estado = "sustituido"
    uow.db.flush()

    registrar(
        uow.db,
        accion="presupuesto.nueva_version",
        objeto="presupuesto",
        objeto_id=nuevo.id,
        datos={"numero": nuevo.numero, "version": nuevo.version, "desde": str(viejo.id)},
        tenant_id=tenant_id,
    )
    return nuevo


def comparar_versiones(db: Session, tenant_id: UUID, presupuesto_id: UUID) -> dict[str, Any]:
    """Qué cambió respecto de la versión anterior.

    Se calcula al pedirlo y no se guarda: una diferencia guardada se queda
    desfasada en cuanto alguien corrige una línea, y entonces miente con toda la
    apariencia de ser un dato.
    """
    actual = db.get(Presupuesto, presupuesto_id)
    if actual is None or actual.tenant_id != tenant_id:
        raise NoEncontrado("El presupuesto no existe", error_code="presupuesto.no_encontrado")
    if actual.anterior_id is None:
        return {"version": actual.version, "primera": True, "cambios": []}

    def _lineas(pid: UUID) -> dict[str, LineaPresupuesto]:
        return {
            (ln.sku or ln.descripcion): ln
            for ln in db.execute(
                select(LineaPresupuesto).where(LineaPresupuesto.presupuesto_id == pid)
            ).scalars()
        }

    antes, ahora = _lineas(actual.anterior_id), _lineas(actual.id)
    cambios: list[dict[str, Any]] = []
    for clave in sorted(set(antes) | set(ahora)):
        vieja, nueva = antes.get(clave), ahora.get(clave)
        if vieja is None:
            cambios.append({"linea": clave, "cambio": "anadida", "total": str(nueva.total)})
        elif nueva is None:
            cambios.append({"linea": clave, "cambio": "quitada", "total": str(vieja.total)})
        elif vieja.total != nueva.total or vieja.cantidad != nueva.cantidad:
            cambios.append(
                {
                    "linea": clave,
                    "cambio": "modificada",
                    "cantidad_antes": str(vieja.cantidad),
                    "cantidad_ahora": str(nueva.cantidad),
                    "total_antes": str(vieja.total),
                    "total_ahora": str(nueva.total),
                }
            )
    anterior = db.get(Presupuesto, actual.anterior_id)
    return {
        "version": actual.version,
        "primera": False,
        "total_antes": str(anterior.total) if anterior else None,
        "total_ahora": str(actual.total),
        "cambios": cambios,
    }


# ── Matriz de descuentos (CRM-03.03.02.04) ────────────────────────────────


def politica_de_descuento(db: Session, tenant_id: UUID, presupuesto: Presupuesto) -> dict[str, Any]:
    """Dice si el presupuesto puede salir solo o necesita aprobación, y por qué.

    Mira **las dos cosas**: el descuento sobre tarifa y el margen que queda. Un
    20 % sobre un producto con 60 puntos de margen y un 20 % sobre uno con 12 son
    cosas distintas, y una matriz que solo mire el porcentaje aprueba la segunda
    sin que nadie se entere.

    Cuando el margen **no se sabe** no se deja pasar: se exige aprobación y se
    dice que es por eso. Tratar «no lo sé» como «está bien» es cómo se firma un
    presupuesto que pierde dinero.
    """
    from crmcore.runtime.settings import efectivo

    lineas = (
        db.execute(
            select(LineaPresupuesto).where(LineaPresupuesto.presupuesto_id == presupuesto.id)
        )
        .scalars()
        .all()
    )
    # Los dos umbrales son ajustes en caliente, no constantes: la política de
    # descuentos cambia con cada campaña, y un despliegue por cada cambio hace
    # que se acabe aprobando a mano «esta vez».
    umbral_descuento = Decimal(str(efectivo("descuento_libre_pct", db, default=10)))
    margen_minimo = Decimal(str(efectivo("margen_minimo_pct", db, default=20)))

    motivos: list[str] = []
    descuento_max = max(
        (Decimal(ln.descuento_pct) for ln in lineas),
        default=Decimal(0),
    )
    if descuento_max > umbral_descuento:
        motivos.append(
            f"Hay un descuento del {descuento_max} %, por encima del "
            f"{umbral_descuento} % que se puede dar sin aprobar."
        )

    if presupuesto.margen_pct is None:
        motivos.append(
            "No se conoce el coste de todas las líneas, así que no se puede "
            "saber el margen. Se aprueba a mano en vez de suponer que está bien."
        )
    elif Decimal(presupuesto.margen_pct) < margen_minimo:
        motivos.append(
            f"El margen queda en el {presupuesto.margen_pct} %, por debajo del "
            f"mínimo del {margen_minimo} %."
        )

    # El suelo por producto manda sobre el general: un producto con margen
    # mínimo propio lo tiene porque el general no le vale.
    for linea in lineas:
        if linea.producto_id is None or linea.margen_pct is None:
            continue
        producto = db.get(cat.Producto, linea.producto_id)
        if producto is None or producto.margen_minimo_pct is None:
            continue
        if Decimal(linea.margen_pct) < Decimal(producto.margen_minimo_pct):
            motivos.append(
                f"«{linea.sku or linea.descripcion}» queda al {linea.margen_pct} % "
                f"y su mínimo propio es {producto.margen_minimo_pct} %."
            )

    return {
        "necesita_aprobacion": bool(motivos),
        "motivos": motivos,
        "descuento_maximo": str(descuento_max),
        "margen_pct": str(presupuesto.margen_pct) if presupuesto.margen_pct is not None else None,
        "umbral_descuento": str(umbral_descuento),
        "margen_minimo": str(margen_minimo),
    }


def enviar(uow: UnidadDeTrabajo, presupuesto_id: UUID) -> dict[str, Any]:
    """Manda el presupuesto al cliente, o lo para si necesita aprobación.

    El control está **aquí y no en la pantalla**: si dependiera del front,
    bastaría una integración que llamara a la API para saltarse la matriz entera.
    """
    tenant_id = uow.tenant_id
    presupuesto = uow.db.get(Presupuesto, presupuesto_id)
    if presupuesto is None or presupuesto.tenant_id != tenant_id:
        raise NoEncontrado("El presupuesto no existe", error_code="presupuesto.no_encontrado")
    if presupuesto.estado not in ("borrador", "aprobado"):
        raise Conflicto(
            f"Un presupuesto en estado «{presupuesto.estado}» no se manda.",
            error_code="presupuesto.estado_no_enviable",
        )

    politica = politica_de_descuento(uow.db, tenant_id, presupuesto)
    if politica["necesita_aprobacion"] and presupuesto.estado != "aprobado":
        presupuesto.estado = "en_aprobacion"
        presupuesto.motivo_aprobacion = " ".join(politica["motivos"])
        uow.db.flush()
        # La aprobación la abre `orchestrator`: aquí solo se dice que hace falta
        # y por qué. Llamarle desde dentro de esta transacción ataría poder
        # mandar un presupuesto a que otro servicio esté en pie.
        uow.emitir(
            "quote.approval.needed",
            subject=("presupuesto", presupuesto.id),
            data={
                "presupuesto_id": str(presupuesto.id),
                "numero": presupuesto.numero,
                "cuenta_id": str(presupuesto.cuenta_id) if presupuesto.cuenta_id else "",
                "total": str(presupuesto.total),
                "descuento_maximo": politica["descuento_maximo"],
                "margen_pct": politica["margen_pct"] or "",
                "motivos": politica["motivos"],
            },
        )
        return {"enviado": False, "estado": presupuesto.estado, "motivos": politica["motivos"]}

    presupuesto.estado = "enviado"
    presupuesto.enviado_at = _ahora()
    uow.db.flush()
    uow.emitir(
        "quote.sent",
        subject=("presupuesto", presupuesto.id),
        data={
            "presupuesto_id": str(presupuesto.id),
            "numero": presupuesto.numero,
            "version": presupuesto.version,
            "total": str(presupuesto.total),
            "cuenta_id": str(presupuesto.cuenta_id) if presupuesto.cuenta_id else "",
        },
    )
    return {"enviado": True, "estado": presupuesto.estado, "motivos": []}


def aceptar(uow: UnidadDeTrabajo, presupuesto_id: UUID) -> Pedido:
    """El cliente acepta: nace el pedido.

    Se comprueba la vigencia. Aceptar un presupuesto caducado sin decir nada es
    cómo se sirve a precio de hace un año, y el descubrimiento llega con la
    factura.
    """
    tenant_id = uow.tenant_id
    presupuesto = uow.db.get(Presupuesto, presupuesto_id)
    if presupuesto is None or presupuesto.tenant_id != tenant_id:
        raise NoEncontrado("El presupuesto no existe", error_code="presupuesto.no_encontrado")
    if presupuesto.estado != "enviado":
        raise Conflicto(
            f"Solo se acepta un presupuesto enviado; este está «{presupuesto.estado}».",
            error_code="presupuesto.no_enviado",
        )
    if presupuesto.cuenta_id is None:
        # Un presupuesto se puede preparar para un posible cliente que todavía no
        # es cuenta; un pedido no. Sin cuenta no hay a quién facturar, y dejarlo
        # pasar convierte el problema en un rechazo del ERP dos días después, con
        # el pedido ya prometido al cliente.
        raise Conflicto(
            "Ese presupuesto no tiene cuenta, y un pedido sin cliente no se "
            "puede facturar. Conviértelo antes de aceptarlo.",
            error_code="presupuesto.sin_cuenta",
        )
    if presupuesto.valido_hasta and presupuesto.valido_hasta < hoy(uow.db):
        raise Conflicto(
            f"Ese presupuesto caducó el {presupuesto.valido_hasta}. Haz una "
            "versión nueva con los precios de hoy.",
            error_code="presupuesto.caducado",
            detalle={"valido_hasta": str(presupuesto.valido_hasta)},
        )

    presupuesto.estado = "aceptado"
    presupuesto.aceptado_at = _ahora()
    pedido = Pedido(
        tenant_id=tenant_id,
        numero=_siguiente(uow.db, tenant_id, Pedido, "PED"),
        presupuesto_id=presupuesto.id,
        cuenta_id=presupuesto.cuenta_id,
        total=presupuesto.total,
        moneda=presupuesto.moneda,
    )
    uow.db.add(pedido)
    uow.db.flush()

    uow.emitir(
        "quote.accepted",
        subject=("presupuesto", presupuesto.id),
        data={
            "presupuesto_id": str(presupuesto.id),
            "numero": presupuesto.numero,
            "pedido_id": str(pedido.id),
            "total": str(presupuesto.total),
            "oportunidad_id": str(presupuesto.oportunidad_id) if presupuesto.oportunidad_id else "",
        },
    )
    return pedido


def caducar_vencidos(uow: UnidadDeTrabajo, tenant_id: UUID) -> dict[str, Any]:
    """Marca caducados los presupuestos que pasaron su vigencia.

    Hace falta como paso explícito: un presupuesto que sigue diciendo «enviado»
    seis meses después aparece en el pipeline como negocio vivo, y la previsión
    lo cuenta.
    """
    dia = hoy(uow.db)
    filas = (
        uow.db.execute(
            select(Presupuesto).where(
                Presupuesto.tenant_id == tenant_id,
                Presupuesto.estado.in_(("borrador", "enviado", "aprobado")),
                Presupuesto.valido_hasta.isnot(None),
                Presupuesto.valido_hasta < dia,
            )
        )
        .scalars()
        .all()
    )
    for fila in filas:
        fila.estado = "caducado"
    uow.db.flush()
    return {
        "caducados": [f.numero for f in filas],
        "cuantos": len(filas),
        "medible": True,
    }


# ── Documento (CRM-03.03.02.06) ───────────────────────────────────────────


def documento(db: Session, tenant_id: UUID, presupuesto_id: UUID) -> dict[str, Any]:
    """Los datos del presupuesto listos para componer el PDF.

    Devuelve **datos y no un PDF**: la maquetación, la marca y el idioma son del
    generador documental, que ya existe y es común a toda la suite. Generar el
    binario aquí metería tipografías y plantillas dentro del servicio de ventas y
    obligaría a desplegarlo para cambiar un logotipo.

    Lleva la marca y el idioma del propio presupuesto, no los del tenant: un
    grupo con tres marcas manda ofertas con la que corresponda, y quien la
    compone no tiene que adivinarlo.
    """
    presupuesto = db.get(Presupuesto, presupuesto_id)
    if presupuesto is None or presupuesto.tenant_id != tenant_id:
        raise NoEncontrado("El presupuesto no existe", error_code="presupuesto.no_encontrado")
    lineas = (
        db.execute(
            select(LineaPresupuesto)
            .where(LineaPresupuesto.presupuesto_id == presupuesto.id)
            .order_by(LineaPresupuesto.orden)
        )
        .scalars()
        .all()
    )
    return {
        "plantilla": f"presupuesto/{presupuesto.marca or 'general'}/{presupuesto.idioma}",
        "marca": presupuesto.marca,
        "idioma": presupuesto.idioma,
        "numero": presupuesto.numero,
        "version": presupuesto.version,
        "fecha": presupuesto.created_at.date().isoformat() if presupuesto.created_at else None,
        "valido_hasta": str(presupuesto.valido_hasta) if presupuesto.valido_hasta else None,
        "cuenta_id": str(presupuesto.cuenta_id) if presupuesto.cuenta_id else None,
        "titulo": presupuesto.titulo,
        "moneda": presupuesto.moneda,
        "lineas": [
            {
                "sku": ln.sku,
                "descripcion": ln.descripcion,
                "cantidad": str(ln.cantidad),
                "precio": str(ln.precio_final),
                "total": str(ln.total),
                # El descuento se enseña solo si lo hay: una columna con ceros
                # invita a pedir descuento a quien no lo había pedido.
                "descuento_pct": str(ln.descuento_pct) if ln.descuento_pct else None,
            }
            for ln in lineas
        ],
        "subtotal": str(presupuesto.subtotal),
        "descuento_total": str(presupuesto.descuento_total),
        "total": str(presupuesto.total),
        "notas": presupuesto.notas,
        "condiciones": presupuesto.condiciones,
        # El coste y el margen NO salen. Es el error más caro que se puede
        # cometer al componer una oferta, y por eso se decide aquí y no en la
        # plantilla.
    }


# ── Contratos y renovaciones (CRM-03.03.02.08, CRM-03.03.02.10) ───────────


def crear_contrato(
    uow: UnidadDeTrabajo,
    *,
    cuenta_id: UUID,
    inicio: date,
    fin: date | None = None,
    presupuesto_id: UUID | None = None,
    titulo: str = "",
    importe: Decimal = Decimal(0),
    moneda: str = "EUR",
    renovacion_automatica: bool = False,
    preaviso_dias: int = 30,
    meses_renovacion: int = 12,
    clausulas: list[dict[str, Any]] | None = None,
) -> Contrato:
    """Da de alta un contrato.

    El **preaviso** se exige cuando hay renovación automática: un contrato que se
    renueva solo y no avisa es el que se descubre renovado, y para entonces ya
    obliga otro año.
    """
    if fin and fin <= inicio:
        raise ErrorValidacion(
            "El contrato acaba antes de empezar.", error_code="contrato.vigencia_invalida"
        )
    if renovacion_automatica and not fin:
        raise ErrorValidacion(
            "Un contrato que se renueva solo necesita fecha de fin: sin ella no "
            "hay nada que renovar ni cuándo avisar.",
            error_code="contrato.renovacion_sin_fin",
        )

    fila = Contrato(
        tenant_id=uow.tenant_id,
        numero=_siguiente(uow.db, uow.tenant_id, Contrato, "CTR"),
        cuenta_id=cuenta_id,
        presupuesto_id=presupuesto_id,
        titulo=titulo,
        inicio=inicio,
        fin=fin,
        importe=importe,
        moneda=moneda,
        renovacion_automatica=renovacion_automatica,
        preaviso_dias=preaviso_dias,
        meses_renovacion=meses_renovacion,
        clausulas=clausulas or [],
        estado="vigente",
    )
    uow.db.add(fila)
    uow.db.flush()
    uow.emitir(
        "contract.signed",
        subject=("contrato", fila.id),
        data={
            "contrato_id": str(fila.id),
            "numero": fila.numero,
            "cuenta_id": str(cuenta_id),
            "importe": str(importe),
            "fin": str(fin) if fin else "",
        },
    )
    return fila


def _sumar_meses(desde: date, meses: int) -> date:
    """Suma meses cuidando el final de mes.

    Un contrato que vence el 31 de enero y se renueva doce meses no puede
    convertirse en el 3 de marzo, que es lo que pasa sumando días.
    """
    mes = desde.month - 1 + meses
    anio = desde.year + mes // 12
    mes = mes % 12 + 1
    import calendar

    dia = min(desde.day, calendar.monthrange(anio, mes)[1])
    return date(anio, mes, dia)


def revisar_renovaciones(uow: UnidadDeTrabajo, tenant_id: UUID) -> dict[str, Any]:
    """Avisa de los preavisos y renueva lo que toca renovar solo.

    **El preaviso es la fecha que importa**, no el vencimiento: el día que vence
    ya es tarde para no renovar, y quien quería negociar se encuentra con otro
    año firmado.

    Los contratos sin renovación automática también avisan. Son los que se
    olvidan: nadie los renueva y el cliente se va sin que nadie lo haya decidido.
    """
    dia = hoy(uow.db)
    vigentes = (
        uow.db.execute(
            select(Contrato).where(
                Contrato.tenant_id == tenant_id,
                Contrato.estado == "vigente",
                Contrato.fin.isnot(None),
            )
        )
        .scalars()
        .all()
    )
    avisados: list[dict[str, Any]] = []
    renovados: list[dict[str, Any]] = []

    for contrato in vigentes:
        aviso = contrato.fin - timedelta(days=contrato.preaviso_dias)
        if not contrato.preaviso_dado and dia >= aviso:
            contrato.preaviso_dado = True
            avisados.append(
                {
                    "contrato_id": str(contrato.id),
                    "numero": contrato.numero,
                    "vence": str(contrato.fin),
                    "dias": (contrato.fin - dia).days,
                    "automatica": contrato.renovacion_automatica,
                }
            )
            uow.emitir(
                "contract.renewal.due",
                subject=("contrato", contrato.id),
                data={
                    "contrato_id": str(contrato.id),
                    "numero": contrato.numero,
                    "cuenta_id": str(contrato.cuenta_id),
                    "vence": str(contrato.fin),
                    "dias_restantes": (contrato.fin - dia).days,
                    "renovacion_automatica": contrato.renovacion_automatica,
                },
                dedup_key=f"preaviso:{contrato.id}",
            )

        if contrato.renovacion_automatica and dia > contrato.fin:
            nuevo = Contrato(
                tenant_id=tenant_id,
                numero=_siguiente(uow.db, tenant_id, Contrato, "CTR"),
                cuenta_id=contrato.cuenta_id,
                titulo=contrato.titulo,
                inicio=contrato.fin + timedelta(days=1),
                fin=_sumar_meses(contrato.fin, contrato.meses_renovacion),
                importe=contrato.importe,
                moneda=contrato.moneda,
                renovacion_automatica=True,
                preaviso_dias=contrato.preaviso_dias,
                meses_renovacion=contrato.meses_renovacion,
                clausulas=contrato.clausulas,
                renovado_de_id=contrato.id,
                estado="vigente",
            )
            uow.db.add(nuevo)
            # El viejo queda «renovado» y no «terminado»: la diferencia dice si
            # el cliente sigue con nosotros, y mezclarlas hace que la tasa de
            # bajas cuente como pérdidas las renovaciones.
            contrato.estado = "renovado"
            renovados.append({"de": contrato.numero, "a": nuevo.numero})

    uow.db.flush()
    return {
        "revisados": len(vigentes),
        "avisados": avisados,
        "renovados": renovados,
        # Sin contratos con fecha de fin no se dice que todo está al día.
        "medible": bool(vigentes),
    }


# ── Suscripciones (CRM-03.03.02.09) ───────────────────────────────────────


DIAS_PERIODO = {"mensual": 30, "trimestral": 91, "anual": 365}


def _fin_de_periodo(desde: date, periodicidad: str) -> date:
    return desde + timedelta(days=DIAS_PERIODO.get(periodicidad, 30))


def _prorrateo(
    importe_periodo: Decimal, periodicidad: str, desde: date, hasta: date | None
) -> Decimal:
    """Lo que corresponde a los días que quedan del periodo.

    Se prorratea **por días reales del periodo**, no por treintavos. Un cambio a
    mitad de febrero con treintavos cobra de menos, y es la diferencia que el
    cliente encuentra cuando revisa la factura.
    """
    dias_periodo = DIAS_PERIODO.get(periodicidad, 30)
    fin = hasta or (desde + timedelta(days=dias_periodo))
    dias = max((fin - desde).days, 0)
    return _redondear(importe_periodo * Decimal(dias) / Decimal(dias_periodo))


def alta_suscripcion(
    uow: UnidadDeTrabajo,
    *,
    cuenta_id: UUID,
    plan: str,
    importe_periodo: Decimal,
    inicio: date,
    periodicidad: str = "mensual",
    contrato_id: UUID | None = None,
    producto_id: UUID | None = None,
    cantidad: Decimal = Decimal(1),
    moneda: str = "EUR",
) -> SuscripcionCliente:
    fila = SuscripcionCliente(
        tenant_id=uow.tenant_id,
        cuenta_id=cuenta_id,
        contrato_id=contrato_id,
        producto_id=producto_id,
        plan=plan,
        cantidad=cantidad,
        importe_periodo=importe_periodo,
        moneda=moneda,
        periodicidad=periodicidad,
        inicio=inicio,
        # La próxima factura es el final del primer periodo, no el día del alta.
        # Ponerla en el inicio dejaba el prorrateo en cero: un cambio de plan a
        # los tres días no cobraba nada de diferencia, y el error no se ve hasta
        # que alguien compara la factura con el contrato.
        proxima_factura=_fin_de_periodo(inicio, periodicidad),
    )
    uow.db.add(fila)
    uow.db.flush()
    uow.db.add(
        CambioSuscripcion(
            tenant_id=uow.tenant_id,
            suscripcion_id=fila.id,
            tipo="alta",
            efectivo_el=inicio,
            plan_despues=plan,
            importe_despues=importe_periodo,
        )
    )
    uow.db.flush()
    uow.emitir(
        "subscription.changed",
        subject=("suscripcion", fila.id),
        data={
            "suscripcion_id": str(fila.id),
            "cuenta_id": str(cuenta_id),
            "tipo": "alta",
            "plan": plan,
            "importe": str(importe_periodo),
        },
    )
    return fila


def cambiar_suscripcion(
    uow: UnidadDeTrabajo,
    suscripcion_id: UUID,
    *,
    tipo: str,
    efectivo_el: date | None = None,
    plan: str | None = None,
    cantidad: Decimal | None = None,
    importe_periodo: Decimal | None = None,
    motivo: str = "",
) -> dict[str, Any]:
    """Cambia una suscripción y calcula el prorrateo.

    El histórico es **append-only**: cada cambio deja su fila con el antes y el
    después. Sin eso, responder «¿desde cuándo paga esto?» exige mirar facturas,
    y el ARR de hace seis meses no se puede reconstruir.
    """
    tenant_id = uow.tenant_id
    fila = uow.db.get(SuscripcionCliente, suscripcion_id)
    if fila is None or fila.tenant_id != tenant_id:
        raise NoEncontrado("La suscripción no existe", error_code="suscripcion.no_encontrada")
    if fila.estado == "cancelada":
        raise Conflicto(
            "Esa suscripción está cancelada: para volver hay que dar una de alta.",
            error_code="suscripcion.cancelada",
        )

    dia = efectivo_el or hoy(uow.db)
    antes_plan, antes_importe = fila.plan, Decimal(fila.importe_periodo)

    if tipo == "cambio_plan" and plan:
        fila.plan = plan
    if tipo == "cambio_cantidad" and cantidad is not None:
        fila.cantidad = cantidad
    if importe_periodo is not None:
        fila.importe_periodo = importe_periodo
    if tipo == "pausa":
        fila.estado = "pausada"
    if tipo == "reanudacion":
        fila.estado = "activa"
    if tipo == "baja":
        fila.estado = "cancelada"
        fila.fin = dia
        fila.proxima_factura = None

    diferencia = Decimal(fila.importe_periodo) - antes_importe
    prorrateo = (
        _prorrateo(diferencia, fila.periodicidad, dia, fila.proxima_factura)
        if tipo in ("cambio_plan", "cambio_cantidad")
        else (
            -_prorrateo(antes_importe, fila.periodicidad, dia, fila.proxima_factura)
            if tipo == "baja"
            else Decimal(0)
        )
    )

    uow.db.add(
        CambioSuscripcion(
            tenant_id=tenant_id,
            suscripcion_id=fila.id,
            tipo=tipo,
            efectivo_el=dia,
            plan_antes=antes_plan,
            plan_despues=fila.plan,
            importe_antes=antes_importe,
            importe_despues=Decimal(fila.importe_periodo),
            prorrateo=prorrateo,
            motivo=motivo,
        )
    )
    uow.db.flush()
    uow.emitir(
        "subscription.changed",
        subject=("suscripcion", fila.id),
        data={
            "suscripcion_id": str(fila.id),
            "cuenta_id": str(fila.cuenta_id),
            "tipo": tipo,
            "plan": fila.plan,
            "importe": str(fila.importe_periodo),
            "prorrateo": str(prorrateo),
        },
    )
    return {
        "suscripcion_id": str(fila.id),
        "tipo": tipo,
        "estado": fila.estado,
        "plan": fila.plan,
        "importe_periodo": str(fila.importe_periodo),
        "prorrateo": str(prorrateo),
    }


def ingreso_recurrente(
    db: Session, tenant_id: UUID, *, en_fecha: date | None = None
) -> dict[str, Any]:
    """MRR y ARR de las suscripciones activas.

    Las **pausadas no cuentan**: una suscripción pausada no factura, y contarla
    infla el recurrente con dinero que no entra. Se dicen aparte, porque es la
    cifra que avisa de una fuga antes de que se convierta en baja.
    """
    dia = en_fecha or hoy(db)
    filas = (
        db.execute(select(SuscripcionCliente).where(SuscripcionCliente.tenant_id == tenant_id))
        .scalars()
        .all()
    )
    factor = {
        "mensual": Decimal(1),
        "trimestral": Decimal(1) / Decimal(3),
        "anual": Decimal(1) / Decimal(12),
    }
    mrr = Decimal(0)
    pausado = Decimal(0)
    for fila in filas:
        mensual = Decimal(fila.importe_periodo) * factor.get(fila.periodicidad, Decimal(1))
        if fila.estado == "activa" and fila.inicio <= dia and (fila.fin is None or fila.fin >= dia):
            mrr += mensual
        elif fila.estado == "pausada":
            pausado += mensual
    return {
        "mrr": str(_redondear(mrr)),
        "arr": str(_redondear(mrr * 12)),
        "mrr_pausado": str(_redondear(pausado)),
        "activas": len([f for f in filas if f.estado == "activa"]),
        "pausadas": len([f for f in filas if f.estado == "pausada"]),
        "medible": bool(filas),
    }


# ── Traspaso al ERP (CRM-03.03.02.11) ─────────────────────────────────────


def enviar_a_erp(uow: UnidadDeTrabajo, pedido_id: UUID) -> dict[str, Any]:
    """Manda el pedido al ERP y lo deja **esperando confirmación**.

    No se da por bueno porque la llamada no diera error: el ERP puede aceptar el
    mensaje y rechazar el pedido después, y un traspaso que se cierra al enviar
    es cómo se descubre en el cierre de mes que faltan pedidos.

    La llamada la hace `integration` con su conector declarativo: aquí solo se
    emite el pedido. Llamar al ERP desde esta transacción ataría aceptar un
    presupuesto a que el ERP del cliente esté en pie.
    """
    tenant_id = uow.tenant_id
    pedido = uow.db.get(Pedido, pedido_id)
    if pedido is None or pedido.tenant_id != tenant_id:
        raise NoEncontrado("El pedido no existe", error_code="pedido.no_encontrado")
    if pedido.estado not in ("pendiente", "rechazado_erp"):
        raise Conflicto(
            f"Ese pedido ya está «{pedido.estado}».", error_code="pedido.estado_no_enviable"
        )

    pedido.estado = "enviado_erp"
    pedido.enviado_at = _ahora()
    pedido.error_erp = None
    uow.db.flush()

    lineas: list[dict[str, Any]] = []
    if pedido.presupuesto_id:
        for ln in uow.db.execute(
            select(LineaPresupuesto)
            .where(LineaPresupuesto.presupuesto_id == pedido.presupuesto_id)
            .order_by(LineaPresupuesto.orden)
        ).scalars():
            lineas.append(
                {
                    "sku": ln.sku,
                    "descripcion": ln.descripcion,
                    "cantidad": str(ln.cantidad),
                    "precio": str(ln.precio_final),
                    "total": str(ln.total),
                }
            )

    uow.emitir(
        "order.submitted",
        subject=("pedido", pedido.id),
        data={
            "pedido_id": str(pedido.id),
            "numero": pedido.numero,
            "cuenta_id": str(pedido.cuenta_id),
            "total": str(pedido.total),
            "moneda": pedido.moneda,
            "lineas": lineas,
        },
        # Idempotente por pedido: un reintento del relevo no puede crear dos
        # pedidos en el ERP del cliente.
        dedup_key=f"erp:{pedido.id}",
    )
    return {"pedido_id": str(pedido.id), "estado": pedido.estado}


def confirmar_desde_erp(
    uow: UnidadDeTrabajo,
    pedido_id: UUID,
    *,
    aceptado: bool,
    referencia_erp: str = "",
    error: str = "",
    respuesta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Anota lo que el ERP respondió."""
    tenant_id = uow.tenant_id
    pedido = uow.db.get(Pedido, pedido_id)
    if pedido is None or pedido.tenant_id != tenant_id:
        raise NoEncontrado("El pedido no existe", error_code="pedido.no_encontrado")

    pedido.respuesta_erp = respuesta or {}
    if aceptado:
        pedido.estado = "confirmado"
        pedido.referencia_erp = referencia_erp or None
        pedido.confirmado_at = _ahora()
        pedido.error_erp = None
    else:
        pedido.estado = "rechazado_erp"
        pedido.error_erp = error or "El ERP lo rechazó sin decir por qué."
    uow.db.flush()

    registrar(
        uow.db,
        accion="pedido.respuesta_erp",
        objeto="pedido",
        objeto_id=pedido.id,
        datos={"aceptado": aceptado, "referencia": referencia_erp, "error": error},
        tenant_id=tenant_id,
    )
    return {"pedido_id": str(pedido.id), "estado": pedido.estado, "referencia_erp": referencia_erp}


def conciliar_erp(
    uow: UnidadDeTrabajo, tenant_id: UUID, *, horas_espera: int = 24
) -> dict[str, Any]:
    """Los pedidos que se mandaron y de los que el ERP no ha dicho nada.

    Es el mismo problema que el encargo mudo del seguimiento externo, y por eso
    se resuelve igual: **el silencio no es una confirmación**. Un pedido enviado
    del que nadie contesta parece en curso, y lo que hay detrás casi siempre es
    un mensaje perdido.

    Los rechazados salen también: un pedido rechazado por el ERP que nadie mira
    es una venta cerrada que no se sirve.
    """
    limite = _ahora() - timedelta(hours=horas_espera)
    enviados = (
        uow.db.execute(
            select(Pedido).where(
                Pedido.tenant_id == tenant_id,
                Pedido.estado.in_(("enviado_erp", "rechazado_erp")),
            )
        )
        .scalars()
        .all()
    )
    # Se recorre en bucle y no en comprensión: el filtro junta tres condiciones
    # y una zona horaria, y un filtro que nadie puede leer es un filtro que
    # nadie corrige.
    mudos: list[dict[str, Any]] = []
    for p in enviados:
        if p.estado != "enviado_erp" or p.enviado_at is None:
            continue
        enviado = p.enviado_at if p.enviado_at.tzinfo else p.enviado_at.replace(tzinfo=timezone.utc)
        if enviado <= limite:
            mudos.append(
                {
                    "pedido_id": str(p.id),
                    "numero": p.numero,
                    "enviado_at": enviado.isoformat(),
                    "horas": int((_ahora() - enviado).total_seconds() // 3600),
                }
            )

    rechazados = [
        {"pedido_id": str(p.id), "numero": p.numero, "error": p.error_erp}
        for p in enviados
        if p.estado == "rechazado_erp"
    ]
    for p in enviados:
        if p.estado == "confirmado":
            p.conciliado_at = _ahora()
    uow.db.flush()

    return {
        "en_vuelo": len([p for p in enviados if p.estado == "enviado_erp"]),
        "sin_respuesta": mudos,
        "rechazados": rechazados,
        "en_verde": not mudos and not rechazados,
        "medible": bool(enviados),
    }
