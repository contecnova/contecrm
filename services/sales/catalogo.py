"""Maestro de productos, listas de precio y configuración (CRM-03.03.02.02, .03).

La oportunidad ya llevaba líneas con `producto_id`, pero ese identificador no
apuntaba a nada: el comercial escribía la descripción y el precio a mano. Eso
funciona en una demostración y se rompe en el segundo cliente, porque nadie puede
responder «¿qué le cobramos a este por esto?» sin abrir presupuestos antiguos.

Tres decisiones que gobiernan el módulo:

**El precio no es un campo del producto: es el resultado de unas reglas.** El
precio de catálogo es el punto de partida; encima van las listas por cliente, por
canal, por volumen, por moneda y por vigencia. Con un campo `precio` en el
producto, cada acuerdo comercial acaba siendo un producto duplicado —«CAJA-10
ACME»— y a los dos años el catálogo tiene tres mil referencias y doscientas
reales.

**La configuración se declara, no se programa.** Qué va con qué, qué exige qué y
qué excluye qué son reglas del cliente, y meterlas en el código convierte cada
implantación en una rama del producto.

**Lo que se calcula se explica.** Cada precio devuelve qué reglas se aplicaron y
en qué orden. Un precio que no se puede explicar se discute con el cliente
delante, y entonces se acaba dando el descuento igual.

Portado de la forma del motor de contecpos
(`services/catalogo/src/pricing/pricing.engine.ts`, 2026-09-22): reglas ordenadas
por prioridad, acciones tipadas y rastro de lo aplicado. Se cambia el lenguaje de
condiciones: allí es JSON-logic, aquí la misma gramática que ya usan el reparto de
leads, la asignación de casos, los segmentos y la elección de transportista. Dos
gramáticas en el mismo producto obligarían a aprender las dos para configurar una
implantación.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, EntidadBase, TimestampMixin
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
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

logger = get_logger(__name__)

CENTIMO = Decimal("0.01")

# Qué le hace una regla al precio. Lista cerrada: una regla es dato del tenant y
# no puede convertirse en código ejecutable.
ACCIONES = ("fijar", "descuento_pct", "descuento_importe", "recargo_pct", "recargo_importe")
# Cómo se relacionan dos productos en la configuración (CRM-03.03.02.02).
RELACIONES = ("requiere", "excluye", "incluye", "sugiere")


class Producto(EntidadBase):
    """Lo que se vende."""

    __tablename__ = "productos"

    sku: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(300), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    familia: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    # puntual | recurrente. Decide si la línea genera ARR y si puede ir en una
    # suscripción.
    tipo_ingreso: Mapped[str] = mapped_column(String(20), nullable=False, default="puntual")
    periodicidad: Mapped[str | None] = mapped_column(String(20), nullable=True)
    unidad: Mapped[str] = mapped_column(String(20), nullable=False, default="ud")

    # Precio de catálogo: el punto de partida, no el precio final.
    precio_base: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    # Coste estándar, para el margen. Nulo cuando no se conoce: un cero fingido
    # daría un margen del 100 % que nadie cuestionaría.
    coste: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    # Suelo de descuento. Por debajo, el presupuesto necesita aprobación aunque
    # el comercial tenga permiso: el permiso dice quién puede pedirlo, esto dice
    # a partir de dónde no se decide solo.
    margen_minimo_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Un producto retirado no desaparece: los presupuestos y contratos de hace
    # dos años lo siguen nombrando, y borrarlo dejaría líneas apuntando a nada.
    retirado_el: Mapped[date | None] = mapped_column(Date, nullable=True)
    atributos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "sku", name="uq_producto_sku"),
        Index("ix_productos_activos", "tenant_id", "activo", "familia"),
    )


class RelacionProducto(Base, TimestampMixin):
    """Qué va con qué (CRM-03.03.02.02)."""

    __tablename__ = "relaciones_producto"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    producto_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("productos.id", ondelete="CASCADE"), nullable=False
    )
    relacion: Mapped[str] = mapped_column(String(20), nullable=False)
    otro_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # Con `incluye`: cuántas unidades del otro entran por cada una de este.
    cantidad: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=1)
    # Por qué. Se enseña cuando la configuración falla: «no se puede» sin motivo
    # hace que quien está con el cliente delante lo salte por otro camino.
    motivo: Mapped[str] = mapped_column(String(300), nullable=False, default="")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "producto_id", "relacion", "otro_id", name="uq_relacion_producto"
        ),
        Index("ix_relaciones_producto", "tenant_id", "producto_id"),
    )


class ListaPrecio(Base, TimestampMixin):
    """Un acuerdo de precios con vigencia (CRM-03.03.02.03)."""

    __tablename__ = "listas_precio"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    # A quién se le aplica. Vacío = a cualquiera, y entonces manda la condición.
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    canal: Mapped[str | None] = mapped_column(String(60), nullable=True)
    desde: Mapped[date | None] = mapped_column(Date, nullable=True)
    hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Cuando dos listas encajan, gana la de prioridad más baja. Sin un orden
    # declarado, el precio dependería del orden de inserción en la base — y
    # cambiaría al restaurar una copia.
    prioridad: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_lista_precio"),
        Index("ix_listas_precio_vigencia", "tenant_id", "activa", "prioridad"),
    )


class ReglaPrecio(Base, TimestampMixin):
    """Qué le hace una lista al precio de un producto."""

    __tablename__ = "reglas_precio"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    lista_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("listas_precio.id", ondelete="CASCADE"), nullable=False
    )
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    prioridad: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    # A qué se aplica: a un producto, a una familia o a todo lo que cumpla la
    # condición.
    producto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    familia: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Escalado por volumen: desde qué cantidad vale esta regla.
    desde_cantidad: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    condiciones: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    accion: Mapped[str] = mapped_column(String(30), nullable=False)
    valor: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    # Una regla que corta el paso a las siguientes. Hace falta para los precios
    # cerrados por contrato: sin ella, una promoción posterior podría bajar un
    # precio ya pactado y nadie lo vería hasta la factura.
    exclusiva: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (Index("ix_reglas_precio_orden", "tenant_id", "lista_id", "prioridad"),)


# ── El motor de precios ───────────────────────────────────────────────────


def _redondear(valor: Decimal) -> Decimal:
    return Decimal(valor).quantize(CENTIMO, rounding=ROUND_HALF_UP)


def _aplicar(accion: str, precio: Decimal, valor: Decimal) -> Decimal:
    if accion == "fijar":
        return valor
    if accion == "descuento_pct":
        return precio * (Decimal(1) - valor / Decimal(100))
    if accion == "descuento_importe":
        return precio - valor
    if accion == "recargo_pct":
        return precio * (Decimal(1) + valor / Decimal(100))
    if accion == "recargo_importe":
        return precio + valor
    raise ErrorValidacion(
        f"Acción de precio «{accion}» no válida.",
        error_code="catalogo.accion_no_valida",
        detalle={"validas": list(ACCIONES)},
    )


def listas_aplicables(
    db: Session,
    tenant_id: UUID,
    *,
    cuenta_id: UUID | None = None,
    canal: str = "",
    moneda: str = "",
    en_fecha: date | None = None,
) -> list[ListaPrecio]:
    """Las listas que encajan, de más prioritaria a menos.

    Una lista con cuenta gana a una general porque su prioridad se declara más
    baja, no por una regla escondida: si el desempate fuera implícito, nadie
    podría explicar por qué se aplicó una y no otra.
    """
    hoy = en_fecha or date.today()
    filas = (
        db.execute(
            select(ListaPrecio)
            .where(ListaPrecio.tenant_id == tenant_id, ListaPrecio.activa.is_(True))
            .order_by(ListaPrecio.prioridad, ListaPrecio.clave)
        )
        .scalars()
        .all()
    )
    salida = []
    for lista in filas:
        if lista.cuenta_id is not None and lista.cuenta_id != cuenta_id:
            continue
        if lista.canal and canal and lista.canal != canal:
            continue
        if lista.canal and not canal:
            continue
        if moneda and lista.moneda != moneda:
            continue
        if lista.desde and hoy < lista.desde:
            continue
        if lista.hasta and hoy > lista.hasta:
            continue
        salida.append(lista)
    return salida


def calcular_precio(
    db: Session,
    tenant_id: UUID,
    *,
    producto_id: UUID,
    cantidad: Decimal = Decimal(1),
    cuenta_id: UUID | None = None,
    canal: str = "",
    moneda: str = "",
    en_fecha: date | None = None,
    contexto: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Precio de un producto para un cliente concreto, con su explicación.

    Devuelve **qué reglas se aplicaron y en qué orden**. Un precio que no se
    puede explicar se discute con el cliente delante, y entonces se acaba dando
    el descuento igual.

    El precio **nunca baja de cero**: una regla mal escrita que lo dejara en
    negativo produciría un abono en vez de una venta, y eso llega hasta la
    contabilidad antes de que nadie lo mire.
    """
    from crmcore.authz.abac import Condicion

    producto = db.execute(
        select(Producto).where(Producto.id == producto_id, Producto.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if producto is None:
        raise NoEncontrado("El producto no existe", error_code="catalogo.producto_no_encontrado")

    precio = Decimal(producto.precio_base)
    base = precio
    ambito = {
        "producto": {
            "sku": producto.sku,
            "familia": producto.familia,
            "tipo_ingreso": producto.tipo_ingreso,
            **(producto.atributos or {}),
        },
        "cantidad": float(cantidad),
        "canal": canal,
        **(contexto or {}),
    }

    aplicadas: list[dict[str, Any]] = []
    listas = listas_aplicables(
        db,
        tenant_id,
        cuenta_id=cuenta_id,
        canal=canal,
        moneda=moneda or producto.moneda,
        en_fecha=en_fecha,
    )
    cortado = False
    for lista in listas:
        if cortado:
            break
        reglas = (
            db.execute(
                select(ReglaPrecio)
                .where(ReglaPrecio.tenant_id == tenant_id, ReglaPrecio.lista_id == lista.id)
                .order_by(ReglaPrecio.prioridad, ReglaPrecio.nombre)
            )
            .scalars()
            .all()
        )
        for regla in reglas:
            if regla.producto_id and regla.producto_id != producto.id:
                continue
            if regla.familia and regla.familia != producto.familia:
                continue
            if cantidad < regla.desde_cantidad:
                continue
            condiciones = [
                Condicion(
                    atributo=str(c.get("atributo", "")),
                    operador=str(c.get("operador", "=")),
                    valor=c.get("valor"),
                )
                for c in (regla.condiciones or [])
                if isinstance(c, dict)
            ]
            if not all(c.evaluar(ambito) for c in condiciones):
                continue

            antes = precio
            precio = _redondear(_aplicar(regla.accion, precio, Decimal(regla.valor)))
            if precio < 0:
                logger.warning(
                    "catalogo.precio_negativo",
                    regla=str(regla.id),
                    producto=producto.sku,
                    tenant=str(tenant_id),
                )
                precio = Decimal(0)
            aplicadas.append(
                {
                    "lista": lista.clave,
                    "regla": regla.nombre or str(regla.id),
                    "accion": regla.accion,
                    "valor": str(regla.valor),
                    "antes": str(antes),
                    "despues": str(precio),
                }
            )
            if regla.exclusiva:
                cortado = True
                break

    coste = Decimal(producto.coste) if producto.coste is not None else None
    return {
        "producto_id": str(producto.id),
        "sku": producto.sku,
        "moneda": moneda or producto.moneda,
        "precio_base": str(_redondear(base)),
        "precio": str(precio),
        "coste": str(coste) if coste is not None else None,
        # Sin coste no se dice margen cero: se dice que no se sabe. Un margen
        # inventado es peor que ninguno, porque se usa para decidir descuentos.
        "margen_pct": (
            str(_redondear((precio - coste) / precio * Decimal(100)))
            if coste is not None and precio > 0
            else None
        ),
        "reglas_aplicadas": aplicadas,
        # Cuando no se aplicó ninguna regla se dice, en vez de dejar creer que
        # el precio salió de un acuerdo: es la diferencia entre «le cobramos su
        # tarifa» y «le cobramos la de catálogo porque no tiene tarifa».
        "de_catalogo": not aplicadas,
    }


# ── Configuración de producto (CRM-03.03.02.02) ───────────────────────────


def comprobar_configuracion(
    db: Session, tenant_id: UUID, lineas: list[dict[str, Any]]
) -> dict[str, Any]:
    """Comprueba que lo que se ha metido en el presupuesto se puede vender junto.

    Devuelve **los problemas y las sugerencias por separado**, y no bloquea por
    las segundas: una regla `sugiere` que impidiera guardar convertiría una
    recomendación comercial en un obstáculo, y lo que se hace entonces es
    borrarla del catálogo.

    Lo que falta por `requiere` sale con **el motivo escrito en la regla**. Un
    «no se puede» sin motivo hace que quien está con el cliente delante lo salte
    por otro camino.
    """
    presentes = {UUID(str(linea["producto_id"])) for linea in lineas if linea.get("producto_id")}
    if not presentes:
        return {"valida": True, "problemas": [], "sugerencias": [], "a_incluir": []}

    productos = {
        p.id: p
        for p in db.execute(
            select(Producto).where(Producto.tenant_id == tenant_id, Producto.id.in_(presentes))
        ).scalars()
    }
    relaciones = (
        db.execute(
            select(RelacionProducto).where(
                RelacionProducto.tenant_id == tenant_id,
                RelacionProducto.producto_id.in_(presentes),
            )
        )
        .scalars()
        .all()
    )

    problemas: list[dict[str, Any]] = []
    sugerencias: list[dict[str, Any]] = []
    a_incluir: list[dict[str, Any]] = []

    for producto in productos.values():
        if not producto.activo:
            problemas.append(
                {
                    "tipo": "retirado",
                    "producto": producto.sku,
                    "motivo": "Está retirado del catálogo y no se puede vender.",
                }
            )

    for rel in relaciones:
        origen = productos.get(rel.producto_id)
        nombre = origen.sku if origen else str(rel.producto_id)
        if rel.relacion == "requiere" and rel.otro_id not in presentes:
            problemas.append(
                {
                    "tipo": "falta_requerido",
                    "producto": nombre,
                    "otro_id": str(rel.otro_id),
                    "motivo": rel.motivo or f"«{nombre}» no funciona sin ese otro producto.",
                }
            )
        elif rel.relacion == "excluye" and rel.otro_id in presentes:
            otro = productos.get(rel.otro_id)
            problemas.append(
                {
                    "tipo": "incompatible",
                    "producto": nombre,
                    "otro": otro.sku if otro else str(rel.otro_id),
                    "motivo": rel.motivo or "Estos dos no se pueden vender juntos.",
                }
            )
        elif rel.relacion == "incluye":
            a_incluir.append(
                {
                    "producto": nombre,
                    "otro_id": str(rel.otro_id),
                    "cantidad": str(rel.cantidad),
                    "motivo": rel.motivo,
                }
            )
        elif rel.relacion == "sugiere" and rel.otro_id not in presentes:
            sugerencias.append(
                {"producto": nombre, "otro_id": str(rel.otro_id), "motivo": rel.motivo}
            )

    return {
        "valida": not problemas,
        "problemas": problemas,
        "sugerencias": sugerencias,
        "a_incluir": a_incluir,
    }
