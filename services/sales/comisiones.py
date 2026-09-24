"""Incentivos y comisiones (CRM-03.02.03.01, .02, .03).

La comisión es lo único del CRM que la gente comprueba a mano, con una hoja de
cálculo propia, todos los meses. Y tienen razón en hacerlo: es su sueldo. Un
motor de comisiones que no se pueda cuadrar con esa hoja no se usa, se discute.

De ahí sale todo lo demás:

**Cada euro trae su explicación.** Cada línea guarda de qué operación sale, qué
regla se aplicó, sobre qué base y con qué porcentaje. Un total sin desglose es
exactamente lo que provoca la hoja de cálculo paralela.

**El escalado declara si es marginal o retroactivo.** Es la ambigüedad que más
disputas causa: al pasar de tramo, ¿cobra el tramo nuevo solo por lo que excede o
por todo lo vendido? Las dos formas existen y son legítimas, y ninguna es
«obvia». Aquí hay que decirlo, y se dice en cada tramo.

**Lo liquidado es una foto, no una vista.** Los planes cambian, las operaciones
se corrigen y los precios se renegocian. Si la liquidación de marzo se recalculara
en junio daría otro número, y quien cobró en marzo tendría razón al no
reconocerlo. Se guarda lo calculado, con el plan y la regla que se usaron.

**La disputa es parte del proceso, no una incidencia.** Quien no está de acuerdo
abre una disputa, y mientras está abierta el pago no sale. Sin ese freno, lo que
pasa es que se paga, luego se corrige en la siguiente y nadie entiende su nómina.

**Las operaciones no las calcula este módulo.** Lo vendido vive en oportunidades
y pedidos, y lo trae quien llama. Recalcularlo aquí daría un segundo número del
mismo negocio, que es el problema que este módulo existe para evitar.
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

# Sobre qué se comisiona.
#
#   importe    la cifra de venta
#   margen     lo que queda después del coste
#   unidades   cantidad vendida, para productos de precio fijo
BASES = ("importe", "margen", "unidades")

# Tipos de regla.
#
#   porcentaje  un tanto por ciento de la base
#   escalado    tramos con porcentajes distintos
#   acelerador  multiplicador a partir de un grado de consecución
#   spiff       premio fijo por operación que cumple una condición
TIPOS = ("porcentaje", "escalado", "acelerador", "spiff")

# Cómo se aplica un tramo al cambiar de escalón.
#
#   marginal     el porcentaje nuevo solo a la parte que excede el tramo
#   retroactivo  el porcentaje nuevo a todo lo acumulado
#
# Se declara siempre y no hay valor «natural»: las dos formas se usan en
# empresas reales y la diferencia en la nómina es enorme.
MODOS_TRAMO = ("marginal", "retroactivo")

ESTADOS_LIQUIDACION = ("calculada", "en_revision", "disputada", "aprobada", "pagada", "anulada")


class PlanComision(Base, TimestampMixin, SoftDeleteMixin):
    """Un plan de retribución variable con vigencia (CRM-03.02.03.01)."""

    __tablename__ = "planes_comision"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    base: Mapped[str] = mapped_column(String(20), nullable=False, default="importe")
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    periodicidad: Mapped[str] = mapped_column(String(20), nullable=False, default="mensual")
    desde: Mapped[date] = mapped_column(Date, nullable=False)
    hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Un plan en borrador no liquida. Es lo que permite prepararlo y simularlo
    # entero antes de que genere un solo euro.
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="borrador")
    # Cuándo se devenga: al cerrar la venta o al cobrarla. Cambia por completo el
    # calendario de pagos y es la primera pregunta de cualquier comercial.
    devengo: Mapped[str] = mapped_column(String(20), nullable=False, default="cierre")
    # Tope de comisión por periodo. Nulo = sin tope, que también es una decisión:
    # un tope implícito de cero sería catastrófico y uno infinito por descuido,
    # caro. Por eso se guarda explícito.
    tope_periodo: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_plan_comision"),
        Index("ix_planes_comision_vigencia", "tenant_id", "estado", "desde"),
    )


class ReglaComision(Base, TimestampMixin):
    """Una regla del plan (CRM-03.02.03.01)."""

    __tablename__ = "reglas_comision"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    plan_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("planes_comision.id", ondelete="CASCADE"), nullable=False
    )
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    tipo: Mapped[str] = mapped_column(
        String(20), nullable=False, default="porcentaje", info={"opciones": TIPOS}
    )
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    # Tramo del escalado o umbral del acelerador, en la unidad de la base.
    desde_valor: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    hasta_valor: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    porcentaje: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=0)
    importe_fijo: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    multiplicador: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=1)
    modo_tramo: Mapped[str] = mapped_column(
        String(20), nullable=False, default="marginal", info={"opciones": MODOS_TRAMO}
    )
    # Condición ABAC sobre la operación: familia de producto, canal, tipo de
    # cliente… Se reutiliza la gramática de siempre en vez de inventar otra, que
    # es lo que convierte un SPIFF en código a medida.
    condiciones: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Ventana del SPIFF. Un premio sin fechas se acaba pagando dos años después
    # de la campaña que lo motivó.
    vigente_desde: Mapped[date | None] = mapped_column(Date, nullable=True)
    vigente_hasta: Mapped[date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (Index("ix_reglas_comision_plan", "tenant_id", "plan_id", "orden"),)


class AsignacionPlan(Base, TimestampMixin):
    """A quién se le aplica un plan, y desde cuándo (CRM-03.02.03.01)."""

    __tablename__ = "asignaciones_plan_comision"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    plan_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("planes_comision.id", ondelete="CASCADE"), nullable=False
    )
    # Una persona o un partner: el canal indirecto se retribuye con el mismo
    # motor (CRM-03.04.01.06). Un segundo motor para lo mismo habría dado dos
    # formas de calcular un rappel.
    usuario_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    partner_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    desde: Mapped[date] = mapped_column(Date, nullable=False)
    hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Cuota del periodo para el acelerador. Puede venir de la cuota de ventas;
    # se copia aquí porque el plan tiene que poder tener la suya —hay planes que
    # aceleran sobre el 80 % de una cuota distinta de la comercial—.
    cuota: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    __table_args__ = (Index("ix_asignaciones_plan", "tenant_id", "plan_id", "desde"),)


class Liquidacion(Base, TimestampMixin):
    """Lo que le toca a alguien en un periodo (CRM-03.02.03.02, .03)."""

    __tablename__ = "liquidaciones_comision"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    plan_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    usuario_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    partner_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    desde: Mapped[date] = mapped_column(Date, nullable=False)
    hasta: Mapped[date] = mapped_column(Date, nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="calculada")
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    # Lo que el tope dejó fuera. Se guarda para poder explicarlo: un total que
    # llega al tope y no lo dice parece un error de cálculo.
    recortado_por_tope: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    calculada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    aprobada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    aprobada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Trazabilidad del pago: referencia externa (nómina, factura, remesa) y
    # fecha. Sin referencia no se marca pagada — «pagada» sin dónde mirarlo no
    # se puede comprobar, y es lo primero que se pregunta.
    pago_referencia: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    pagada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # El plan tal y como estaba al calcular. Es la foto: si el plan cambia
    # después, esta liquidación sigue explicándose con lo que se le aplicó.
    plan_aplicado: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "plan_id", "usuario_id", "partner_id", "desde", name="uq_liquidacion"
        ),
        Index("ix_liquidaciones_estado", "tenant_id", "estado", "desde"),
    )


class LineaComision(Base):
    """Un euro de comisión con su porqué (CRM-03.02.03.02)."""

    __tablename__ = "lineas_comision"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    liquidacion_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("liquidaciones_comision.id", ondelete="CASCADE"),
        nullable=False,
    )
    # De qué operación sale. Se guarda el tipo y el identificador sin clave
    # ajena: la operación puede ser una oportunidad, un pedido o una factura del
    # ERP, y una FK a cada una de las tres sería una columna vacía de cada dos.
    origen: Mapped[str] = mapped_column(String(40), nullable=False, default="oportunidad")
    origen_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    concepto: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    base: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    porcentaje: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=0)
    importe: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    regla_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    explicacion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Una reversión es una línea negativa con su motivo, no un borrado. Borrar la
    # línea original dejaría la liquidación cuadrando con un total que nadie
    # podría reconstruir.
    reversion_de: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (Index("ix_lineas_comision", "tenant_id", "liquidacion_id"),)


class DisputaComision(Base, TimestampMixin):
    """Alguien no está de acuerdo con su liquidación (CRM-03.02.03.03)."""

    __tablename__ = "disputas_comision"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    liquidacion_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("liquidaciones_comision.id", ondelete="CASCADE"),
        nullable=False,
    )
    linea_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    abierta_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    motivo: Mapped[str] = mapped_column(Text, nullable=False)
    importe_reclamado: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="abierta")
    resolucion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    resuelta_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    resuelta_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_disputas_comision", "tenant_id", "liquidacion_id", "estado"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _hoy() -> date:
    return datetime.now(timezone.utc).date()


def _redondear(valor: Decimal) -> Decimal:
    return Decimal(valor).quantize(CENTIMO, rounding=ROUND_HALF_UP)


# ── Planes y reglas (CRM-03.02.03.01) ─────────────────────────────────────


def crear_plan(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    nombre: str,
    desde: date,
    hasta: date | None = None,
    base: str = "importe",
    moneda: str = "EUR",
    periodicidad: str = "mensual",
    devengo: str = "cierre",
    tope_periodo: Decimal | None = None,
) -> PlanComision:
    """Crea un plan. **Nace en borrador**: un plan activo liquida."""
    if base not in BASES:
        raise ErrorValidacion(
            f"Base «{base}» no válida.",
            error_code="comisiones.base_no_valida",
            detalle={"validas": list(BASES)},
        )
    if devengo not in ("cierre", "cobro"):
        raise ErrorValidacion(
            "El devengo es «cierre» o «cobro»: es la primera pregunta de cualquier "
            "comercial y no puede quedar implícita.",
            error_code="comisiones.devengo_no_valido",
        )
    fila = PlanComision(
        tenant_id=uow.tenant_id,
        clave=clave.strip(),
        nombre=nombre.strip(),
        base=base,
        moneda=moneda,
        periodicidad=periodicidad,
        devengo=devengo,
        desde=desde,
        hasta=hasta,
        tope_periodo=tope_periodo,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def anadir_regla(
    uow: UnidadDeTrabajo,
    plan_id: UUID,
    *,
    tipo: str,
    nombre: str = "",
    orden: int = 100,
    desde_valor: Decimal = Decimal(0),
    hasta_valor: Decimal | None = None,
    porcentaje: Decimal = Decimal(0),
    importe_fijo: Decimal = Decimal(0),
    multiplicador: Decimal = Decimal(1),
    modo_tramo: str = "marginal",
    condiciones: list[dict[str, Any]] | None = None,
    vigente_desde: date | None = None,
    vigente_hasta: date | None = None,
) -> ReglaComision:
    """Añade una regla al plan."""
    if tipo not in TIPOS:
        raise ErrorValidacion(
            f"Tipo de regla «{tipo}» no válido.",
            error_code="comisiones.tipo_no_valido",
            detalle={"validos": list(TIPOS)},
        )
    if modo_tramo not in MODOS_TRAMO:
        raise ErrorValidacion(
            f"Modo de tramo «{modo_tramo}» no válido.",
            error_code="comisiones.modo_no_valido",
            detalle={"validos": list(MODOS_TRAMO)},
        )
    if tipo == "spiff" and importe_fijo == 0 and porcentaje == 0:
        raise ErrorValidacion(
            "Un SPIFF sin importe ni porcentaje no premia nada.",
            error_code="comisiones.spiff_vacio",
        )
    # Las condiciones se validan al guardarlas. Un operador mal escrito no da
    # error en ningún sitio: la condición no se cumple nunca, el SPIFF no premia
    # a nadie y no protesta nadie, porque nadie sabía que le tocaba.
    for i, cruda in enumerate(condiciones or [], 1):
        from crmcore.authz.abac import OPERADORES

        if not isinstance(cruda, dict) or not cruda.get("atributo"):
            raise ErrorValidacion(
                f"La condición {i} no dice sobre qué atributo compara.",
                error_code="comisiones.condicion_invalida",
            )
        if cruda.get("operador") not in OPERADORES:
            raise ErrorValidacion(
                f"Operador «{cruda.get('operador')}» no válido en la condición {i}.",
                error_code="comisiones.operador_no_valido",
                detalle={"validos": sorted(OPERADORES)},
            )
    plan = uow.db.get(PlanComision, plan_id)
    if plan is None or plan.tenant_id != uow.tenant_id:
        raise NoEncontrado("El plan no existe", error_code="comisiones.plan_no_encontrado")
    if plan.estado != "borrador":
        raise Conflicto(
            "Un plan que ya liquida no se modifica: se cierra y se crea el siguiente. "
            "Cambiarlo en caliente haría que dos liquidaciones del mismo periodo "
            "salieran distintas según cuándo se calcularan.",
            error_code="comisiones.plan_no_editable",
            detalle={"estado": plan.estado},
        )
    fila = ReglaComision(
        tenant_id=uow.tenant_id,
        plan_id=plan_id,
        tipo=tipo,
        nombre=nombre.strip(),
        orden=orden,
        desde_valor=desde_valor,
        hasta_valor=hasta_valor,
        porcentaje=porcentaje,
        importe_fijo=importe_fijo,
        multiplicador=multiplicador,
        modo_tramo=modo_tramo,
        condiciones=list(condiciones or []),
        vigente_desde=vigente_desde,
        vigente_hasta=vigente_hasta,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def revisar_plan(db: Session, tenant_id: UUID, plan_id: UUID) -> dict[str, Any]:
    """Comprueba el plan antes de activarlo: huecos y solapes en los tramos.

    Un hueco entre 50.000 y 60.000 no da error en ningún sitio: **da cero**. El
    comercial que venda 55.000 cobra menos que el que vendió 49.000 y nadie
    sabrá por qué hasta que lo reclame.
    """
    plan = db.get(PlanComision, plan_id)
    if plan is None or plan.tenant_id != tenant_id:
        raise NoEncontrado("El plan no existe", error_code="comisiones.plan_no_encontrado")
    reglas = (
        db.execute(
            select(ReglaComision)
            .where(ReglaComision.tenant_id == tenant_id, ReglaComision.plan_id == plan_id)
            .order_by(ReglaComision.orden, ReglaComision.desde_valor)
        )
        .scalars()
        .all()
    )
    tramos = sorted(
        [r for r in reglas if r.tipo == "escalado"], key=lambda r: Decimal(r.desde_valor)
    )
    problemas: list[str] = []
    anterior: ReglaComision | None = None
    for tramo in tramos:
        if anterior is not None:
            fin = anterior.hasta_valor
            if fin is None:
                problemas.append(
                    f"El tramo que empieza en {anterior.desde_valor} no tiene fin y hay "
                    f"otro después: el segundo no se alcanzaría nunca."
                )
            elif Decimal(tramo.desde_valor) > Decimal(fin):
                problemas.append(
                    f"Hueco entre {fin} y {tramo.desde_valor}: lo que caiga ahí comisiona a cero."
                )
            elif Decimal(tramo.desde_valor) < Decimal(fin):
                problemas.append(
                    f"Solape entre {tramo.desde_valor} y {fin}: el orden de las reglas "
                    f"decidiría el sueldo."
                )
        anterior = tramo
    if tramos and tramos[-1].hasta_valor is not None:
        problemas.append(
            f"El último tramo acaba en {tramos[-1].hasta_valor}: por encima no comisiona nada. "
            "Si es a propósito, se declara con un tope de plan."
        )
    modos = {t.modo_tramo for t in tramos}
    if len(modos) > 1:
        problemas.append(
            "Los tramos mezclan modo marginal y retroactivo: el resultado depende del "
            "orden y nadie podrá explicarlo."
        )
    return {
        "plan": plan.clave,
        "reglas": len(reglas),
        "tramos": len(tramos),
        "problemas": problemas,
        "listo": not problemas and bool(reglas),
        # Un plan sin reglas no es un plan correcto: es un plan que paga cero.
        "aviso": ""
        if reglas
        else "El plan no tiene ninguna regla: liquidaría cero a todo el mundo.",
    }


def activar_plan(uow: UnidadDeTrabajo, plan_id: UUID, *, forzar: bool = False) -> PlanComision:
    """Activa el plan si su revisión está limpia."""
    revision = revisar_plan(uow.db, uow.tenant_id, plan_id)
    if not revision["listo"] and not forzar:
        raise Conflicto(
            "El plan tiene problemas que cambiarían lo que cobra la gente",
            error_code="comisiones.plan_con_problemas",
            detalle=revision,
        )
    plan = uow.db.get(PlanComision, plan_id)
    assert plan is not None
    plan.estado = "activo"
    registrar(
        uow.db,
        accion="comision.plan_activado",
        objeto="plan_comision",
        objeto_id=plan.id,
        datos={"clave": plan.clave, "problemas": revision["problemas"], "forzado": forzar},
        tenant_id=uow.tenant_id,
    )
    return plan


def asignar(
    uow: UnidadDeTrabajo,
    plan_id: UUID,
    *,
    usuario_id: UUID | None = None,
    partner_id: UUID | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    cuota: Decimal | None = None,
) -> AsignacionPlan:
    """Asigna el plan a una persona o a un partner."""
    if not usuario_id and not partner_id:
        raise ErrorValidacion(
            "Un plan se asigna a una persona o a un partner.",
            error_code="comisiones.sin_sujeto",
        )
    if usuario_id and partner_id:
        raise ErrorValidacion(
            "Una asignación es de una persona o de un partner, no de los dos: con los "
            "dos, la misma venta se pagaría dos veces.",
            error_code="comisiones.sujeto_ambiguo",
        )
    plan = uow.db.get(PlanComision, plan_id)
    if plan is None or plan.tenant_id != uow.tenant_id:
        raise NoEncontrado("El plan no existe", error_code="comisiones.plan_no_encontrado")
    fila = AsignacionPlan(
        tenant_id=uow.tenant_id,
        plan_id=plan_id,
        usuario_id=usuario_id,
        partner_id=partner_id,
        desde=desde or plan.desde,
        hasta=hasta,
        cuota=cuota,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


# ── Cálculo y simulación (CRM-03.02.03.02) ────────────────────────────────


def _aplica_condicion(regla: ReglaComision, operacion: dict[str, Any]) -> bool:
    if not regla.condiciones:
        return True
    from crmcore.authz.abac import Condicion

    ambito = {"operacion": operacion, **operacion}
    for cruda in regla.condiciones:
        try:
            condicion = Condicion(**cruda)
        except TypeError:
            # Una condición ilegible no se ignora: se considera no cumplida. Al
            # revés, un plan mal guardado pagaría de más a todo el mundo.
            logger.warning("comisiones.condicion_ilegible", regla=str(regla.id))
            return False
        if not condicion.evaluar(ambito):
            return False
    return True


def _en_ventana(regla: ReglaComision, cuando: date | None) -> bool:
    if cuando is None:
        return regla.vigente_desde is None and regla.vigente_hasta is None
    if regla.vigente_desde and cuando < regla.vigente_desde:
        return False
    return not (regla.vigente_hasta and cuando > regla.vigente_hasta)


def _valor_base(base: str, operacion: dict[str, Any]) -> Decimal | None:
    crudo = operacion.get(base)
    if crudo is None:
        return None
    return Decimal(str(crudo))


def calcular(
    db: Session,
    tenant_id: UUID,
    *,
    plan_id: UUID,
    operaciones: list[dict[str, Any]],
    cuota: Decimal | None = None,
) -> dict[str, Any]:
    """Calcula la comisión de un conjunto de operaciones, con su desglose.

    `operaciones` las trae quien llama: `{id, tipo, concepto, importe, margen,
    unidades, fecha, …}`. **No se leen de aquí** porque el negocio vive en
    oportunidades y pedidos, y recalcularlo produciría un segundo número del mismo
    negocio.

    Sirve igual para liquidar y para **simular**: es la misma función, y eso es
    deliberado. Una simulación calculada por otro camino acabaría no coincidiendo
    con la nómina, que es exactamente lo que nadie perdona.

    Se devuelve `sin_base`: las operaciones que no traían el dato sobre el que
    comisiona el plan. Tratarlas como cero las haría desaparecer del desglose, y
    entonces el que falta en la lista es siempre el que más protesta.
    """
    plan = db.get(PlanComision, plan_id)
    if plan is None or plan.tenant_id != tenant_id:
        raise NoEncontrado("El plan no existe", error_code="comisiones.plan_no_encontrado")
    reglas = (
        db.execute(
            select(ReglaComision)
            .where(ReglaComision.tenant_id == tenant_id, ReglaComision.plan_id == plan_id)
            .order_by(ReglaComision.orden, ReglaComision.desde_valor)
        )
        .scalars()
        .all()
    )

    lineas: list[dict[str, Any]] = []
    sin_base: list[dict[str, Any]] = []
    acumulado = Decimal(0)
    # Lo ya devengado por escalado. Se lleva aparte del total porque el modo
    # retroactivo tiene que restar lo pagado *por tramos*, no lo pagado por
    # SPIFF: mezclarlos descontaría el premio de una campaña del sueldo variable.
    devengado_escalado = Decimal(0)

    # Total de la base, que es lo que mueve los tramos y el acelerador.
    total_base = Decimal(0)
    for operacion in operaciones:
        valor = _valor_base(plan.base, operacion)
        if valor is None:
            sin_base.append({"id": str(operacion.get("id") or ""), "falta": plan.base})
            continue
        total_base += valor

    escalados = sorted(
        [r for r in reglas if r.tipo == "escalado"], key=lambda r: Decimal(r.desde_valor)
    )
    porcentajes = [r for r in reglas if r.tipo == "porcentaje"]
    spiffs = [r for r in reglas if r.tipo == "spiff"]
    aceleradores = [r for r in reglas if r.tipo == "acelerador"]

    for operacion in operaciones:
        valor = _valor_base(plan.base, operacion)
        if valor is None:
            continue
        fecha = operacion.get("fecha")
        cuando = date.fromisoformat(str(fecha)) if fecha else None
        concepto = str(operacion.get("concepto") or operacion.get("id") or "")

        # ── Escalado ─────────────────────────────────────────────────────
        # El tramo se decide por lo ACUMULADO en el periodo, no por el importe
        # de la operación suelta. Si se mirara operación a operación, un pedido
        # grande pagaría al tipo alto y diez pequeños al bajo por el mismo total,
        # y el comercial aprendería a agrupar pedidos en vez de a vender.
        aplicables = [r for r in escalados if _aplica_condicion(r, operacion)]
        if aplicables:
            hasta_total = acumulado + valor
            importe_linea = Decimal(0)
            explicaciones: list[str] = []
            regla_aplicada: ReglaComision | None = None

            retroactivos = [r for r in aplicables if r.modo_tramo == "retroactivo"]
            if retroactivos:
                # Manda el tramo más alto que alcanza lo acumulado, y su
                # porcentaje se aplica a TODO. Lo ya devengado por tramos se
                # resta: si no, la parte de abajo se pagaría dos veces.
                alcanzados = [r for r in retroactivos if hasta_total >= Decimal(r.desde_valor)]
                if alcanzados:
                    tramo = max(alcanzados, key=lambda r: Decimal(r.desde_valor))
                    nuevo_total = _redondear(hasta_total * Decimal(tramo.porcentaje) / 100)
                    importe_linea = nuevo_total - devengado_escalado
                    devengado_escalado = nuevo_total
                    regla_aplicada = tramo
                    explicaciones.append(
                        f"tramo retroactivo desde {tramo.desde_valor}: "
                        f"{tramo.porcentaje} % sobre los {hasta_total} acumulados"
                    )
            else:
                inicio = acumulado
                restante = valor
                for tramo in aplicables:
                    if restante <= 0:
                        break
                    tope = Decimal(tramo.hasta_valor) if tramo.hasta_valor is not None else None
                    trozo_desde = max(inicio, Decimal(tramo.desde_valor))
                    trozo_hasta = min(hasta_total, tope) if tope is not None else hasta_total
                    trozo = trozo_hasta - trozo_desde
                    if trozo <= 0:
                        continue
                    importe_linea += _redondear(trozo * Decimal(tramo.porcentaje) / 100)
                    explicaciones.append(
                        f"{trozo} al {tramo.porcentaje} % "
                        f"(tramo {tramo.desde_valor}–"
                        f"{tramo.hasta_valor if tramo.hasta_valor is not None else '∞'})"
                    )
                    regla_aplicada = tramo
                    inicio = trozo_hasta
                    restante = hasta_total - trozo_hasta
                devengado_escalado += importe_linea

            if explicaciones:
                lineas.append(
                    {
                        "origen": str(operacion.get("tipo") or "oportunidad"),
                        "origen_id": operacion.get("id"),
                        "concepto": concepto,
                        "base": str(valor),
                        "porcentaje": str(regla_aplicada.porcentaje) if regla_aplicada else "0",
                        "importe": str(_redondear(importe_linea)),
                        "regla_id": str(regla_aplicada.id) if regla_aplicada else None,
                        "explicacion": "; ".join(explicaciones),
                    }
                )

        # ── Porcentaje llano ─────────────────────────────────────────────
        for regla in porcentajes:
            if not _aplica_condicion(regla, operacion):
                continue
            if (regla.vigente_desde or regla.vigente_hasta) and not _en_ventana(regla, cuando):
                continue
            importe = _redondear(valor * Decimal(regla.porcentaje) / 100)
            lineas.append(
                {
                    "origen": str(operacion.get("tipo") or "oportunidad"),
                    "origen_id": operacion.get("id"),
                    "concepto": concepto,
                    "base": str(valor),
                    "porcentaje": str(regla.porcentaje),
                    "importe": str(importe),
                    "regla_id": str(regla.id),
                    "explicacion": f"{regla.nombre or 'comisión'}: {regla.porcentaje} % de {valor}",
                }
            )

        # ── SPIFF: premio por operación que cumple y cae en ventana ───────
        for regla in spiffs:
            if not _aplica_condicion(regla, operacion):
                continue
            if (regla.vigente_desde or regla.vigente_hasta) and not _en_ventana(regla, cuando):
                continue
            importe = Decimal(regla.importe_fijo) + _redondear(
                valor * Decimal(regla.porcentaje) / 100
            )
            if importe == 0:
                continue
            lineas.append(
                {
                    "origen": str(operacion.get("tipo") or "oportunidad"),
                    "origen_id": operacion.get("id"),
                    "concepto": concepto,
                    "base": str(valor),
                    "porcentaje": str(regla.porcentaje),
                    "importe": str(_redondear(importe)),
                    "regla_id": str(regla.id),
                    "explicacion": f"SPIFF «{regla.nombre or regla.id}»",
                }
            )

        acumulado += valor

    subtotal = _redondear(sum(Decimal(str(line["importe"])) for line in lineas) or Decimal(0))

    # Acelerador: multiplica lo devengado cuando se supera un grado de
    # consecución. Sin cuota no se aplica, y **se dice**: aplicarlo sobre una
    # cuota supuesta de cero lo dispararía siempre.
    acelerador_aplicado: dict[str, Any] | None = None
    consecucion_pct: float | None = None
    if aceleradores and cuota and Decimal(cuota) > 0:
        consecucion_pct = float(round(total_base / Decimal(cuota) * 100, 1))
        for regla in sorted(aceleradores, key=lambda r: -Decimal(r.desde_valor)):
            if Decimal(str(consecucion_pct)) >= Decimal(regla.desde_valor):
                extra = _redondear(subtotal * (Decimal(regla.multiplicador) - 1))
                if extra:
                    lineas.append(
                        {
                            "origen": "acelerador",
                            "origen_id": None,
                            "concepto": regla.nombre or "acelerador",
                            "base": str(subtotal),
                            "porcentaje": "0",
                            "importe": str(extra),
                            "regla_id": str(regla.id),
                            "explicacion": (
                                f"consecución {consecucion_pct} % ≥ {regla.desde_valor} %: "
                                f"×{regla.multiplicador} sobre {subtotal}"
                            ),
                        }
                    )
                acelerador_aplicado = {
                    "regla_id": str(regla.id),
                    "multiplicador": str(regla.multiplicador),
                }
                break

    total = _redondear(sum(Decimal(str(line["importe"])) for line in lineas) or Decimal(0))
    recortado = Decimal(0)
    if plan.tope_periodo is not None and total > Decimal(plan.tope_periodo):
        recortado = _redondear(total - Decimal(plan.tope_periodo))
        total = Decimal(plan.tope_periodo)

    return {
        "plan": plan.clave,
        "base": plan.base,
        "moneda": plan.moneda,
        "total_base": str(total_base),
        "lineas": lineas,
        "total": str(total),
        "recortado_por_tope": str(recortado),
        "tope_periodo": str(plan.tope_periodo) if plan.tope_periodo is not None else None,
        "acelerador": acelerador_aplicado,
        "consecucion_pct": consecucion_pct,
        # Con cuota sin pasar, el acelerador no se evalúa. Decirlo evita que
        # alguien dé por bueno un cálculo al que le faltaba la mitad del plan.
        "acelerador_evaluado": bool(aceleradores) and bool(cuota and Decimal(cuota) > 0),
        "sin_base": sin_base,
        "concluyente": not sin_base,
    }


def previsionar(
    db: Session,
    tenant_id: UUID,
    *,
    plan_id: UUID,
    cerradas: list[dict[str, Any]],
    pipeline: list[dict[str, Any]],
    cuota: Decimal | None = None,
) -> dict[str, Any]:
    """Qué comisión saldría si el pipeline se cerrara como está (CRM-03.02.03.02).

    El pipeline entra **ponderado por su probabilidad**, y se devuelven los dos
    números —lo devengado y lo previsto— por separado. Mezclarlos da una cifra que
    parece ganada y no lo está, y esa cifra se acaba gastando.
    """
    devengado = calcular(db, tenant_id, plan_id=plan_id, operaciones=cerradas, cuota=cuota)
    ponderadas = []
    for operacion in pipeline:
        prob = Decimal(str(operacion.get("probabilidad", 0))) / 100
        copia = dict(operacion)
        for campo in BASES:
            if copia.get(campo) is not None:
                copia[campo] = str(_redondear(Decimal(str(copia[campo])) * prob))
        copia["concepto"] = (
            f"{operacion.get('concepto') or ''} (ponderado {operacion.get('probabilidad', 0)} %)"
        )
        ponderadas.append(copia)
    total_previsto = calcular(
        db, tenant_id, plan_id=plan_id, operaciones=[*cerradas, *ponderadas], cuota=cuota
    )
    return {
        "devengado": devengado["total"],
        "previsto": total_previsto["total"],
        "solo_pipeline": str(
            _redondear(Decimal(total_previsto["total"]) - Decimal(devengado["total"]))
        ),
        "detalle_devengado": devengado,
        "detalle_previsto": total_previsto,
        "aviso": ("El pipeline entra ponderado por probabilidad: lo previsto no está ganado."),
    }


# ── Liquidación, aprobación, disputa y pago (CRM-03.02.03.03) ─────────────


def liquidar(
    uow: UnidadDeTrabajo,
    *,
    plan_id: UUID,
    desde: date,
    hasta: date,
    operaciones: list[dict[str, Any]],
    usuario_id: UUID | None = None,
    partner_id: UUID | None = None,
    cuota: Decimal | None = None,
) -> Liquidacion:
    """Calcula y **guarda** la liquidación de un periodo.

    Se guarda el plan aplicado con ella. Es la diferencia entre una liquidación y
    un informe: el informe se recalcula, la liquidación no. Quien cobró en marzo
    tiene derecho a que marzo siga diciendo lo mismo en junio.
    """
    plan = uow.db.get(PlanComision, plan_id)
    if plan is None or plan.tenant_id != uow.tenant_id:
        raise NoEncontrado("El plan no existe", error_code="comisiones.plan_no_encontrado")
    if plan.estado != "activo":
        raise Conflicto(
            "Un plan en borrador no liquida: se simula.",
            error_code="comisiones.plan_no_activo",
            detalle={"estado": plan.estado},
        )
    existente = uow.db.execute(
        select(Liquidacion).where(
            Liquidacion.tenant_id == uow.tenant_id,
            Liquidacion.plan_id == plan_id,
            Liquidacion.usuario_id == usuario_id,
            Liquidacion.partner_id == partner_id,
            Liquidacion.desde == desde,
        )
    ).scalar_one_or_none()
    if existente is not None:
        raise Conflicto(
            "Ese periodo ya está liquidado",
            error_code="comisiones.periodo_liquidado",
            detalle={"liquidacion_id": str(existente.id), "estado": existente.estado},
        )

    calculo = calcular(uow.db, uow.tenant_id, plan_id=plan_id, operaciones=operaciones, cuota=cuota)
    fila = Liquidacion(
        tenant_id=uow.tenant_id,
        plan_id=plan_id,
        usuario_id=usuario_id,
        partner_id=partner_id,
        desde=desde,
        hasta=hasta,
        total=Decimal(calculo["total"]),
        moneda=plan.moneda,
        recortado_por_tope=Decimal(calculo["recortado_por_tope"]),
        calculada_at=_ahora(),
        plan_aplicado={
            "clave": plan.clave,
            "base": plan.base,
            "devengo": plan.devengo,
            "tope_periodo": calculo["tope_periodo"],
            "acelerador": calculo["acelerador"],
            "consecucion_pct": calculo["consecucion_pct"],
            "sin_base": calculo["sin_base"],
        },
    )
    uow.db.add(fila)
    uow.db.flush()
    for linea in calculo["lineas"]:
        uow.db.add(
            LineaComision(
                tenant_id=uow.tenant_id,
                liquidacion_id=fila.id,
                origen=linea["origen"],
                origen_id=UUID(str(linea["origen_id"])) if linea.get("origen_id") else None,
                concepto=linea["concepto"][:300],
                base=Decimal(linea["base"]),
                porcentaje=Decimal(linea["porcentaje"]),
                importe=Decimal(linea["importe"]),
                regla_id=UUID(str(linea["regla_id"])) if linea.get("regla_id") else None,
                explicacion=linea["explicacion"],
            )
        )
    uow.db.flush()
    registrar(
        uow.db,
        accion="comision.liquidada",
        objeto="liquidacion_comision",
        objeto_id=fila.id,
        datos={"total": str(fila.total), "lineas": len(calculo["lineas"])},
        tenant_id=uow.tenant_id,
    )
    return fila


def enviar_a_aprobacion(uow: UnidadDeTrabajo, liquidacion_id: UUID) -> Liquidacion:
    """Pide la aprobación por el motor de siempre (CRM-03.02.03.03).

    No se monta aquí una segunda cadena de aprobación: el motor del orquestador
    ya sabe de etapas, quórum, delegación y escalado. Este servicio pide, y el que
    aprueba es el que aprueba todo lo demás.
    """
    fila = uow.db.get(Liquidacion, liquidacion_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado(
            "La liquidación no existe", error_code="comisiones.liquidacion_no_encontrada"
        )
    if fila.estado not in ("calculada", "disputada"):
        raise Conflicto(
            "Esa liquidación ya está en curso o pagada",
            error_code="comisiones.estado_no_valido",
            detalle={"estado": fila.estado},
        )
    fila.estado = "en_revision"
    uow.emitir(
        "commission.approval.needed",
        subject=("liquidacion_comision", fila.id),
        data={
            "liquidacion_id": str(fila.id),
            "total": str(fila.total),
            "moneda": fila.moneda,
            "usuario_id": str(fila.usuario_id) if fila.usuario_id else None,
            "partner_id": str(fila.partner_id) if fila.partner_id else None,
        },
    )
    return fila


def aprobar(uow: UnidadDeTrabajo, liquidacion_id: UUID, *, por: UUID | None = None) -> Liquidacion:
    """Aprueba la liquidación. **No con disputas abiertas.**"""
    fila = uow.db.get(Liquidacion, liquidacion_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado(
            "La liquidación no existe", error_code="comisiones.liquidacion_no_encontrada"
        )
    abiertas = (
        uow.db.execute(
            select(DisputaComision).where(
                DisputaComision.tenant_id == uow.tenant_id,
                DisputaComision.liquidacion_id == fila.id,
                DisputaComision.estado == "abierta",
            )
        )
        .scalars()
        .all()
    )
    if abiertas:
        raise Conflicto(
            "Hay disputas abiertas sobre esta liquidación",
            error_code="comisiones.disputa_abierta",
            detalle={"disputas": [str(d.id) for d in abiertas]},
        )
    fila.estado = "aprobada"
    fila.aprobada_por = por
    fila.aprobada_at = _ahora()
    registrar(
        uow.db,
        accion="comision.aprobada",
        objeto="liquidacion_comision",
        objeto_id=fila.id,
        datos={"total": str(fila.total)},
        tenant_id=uow.tenant_id,
    )
    return fila


def disputar(
    uow: UnidadDeTrabajo,
    liquidacion_id: UUID,
    *,
    motivo: str,
    abierta_por: UUID | None = None,
    linea_id: UUID | None = None,
    importe_reclamado: Decimal | None = None,
) -> DisputaComision:
    """Abre una disputa. Congela el pago mientras esté abierta.

    Hay **plazo**: pasado el plazo desde la liquidación, la disputa se registra
    igual pero se marca fuera de plazo. Ni se pierde —el dato es real— ni se
    acepta en silencio, que son las dos formas de que esto acabe en el comité de
    empresa.
    """
    fila = uow.db.get(Liquidacion, liquidacion_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado(
            "La liquidación no existe", error_code="comisiones.liquidacion_no_encontrada"
        )
    if not motivo.strip():
        raise ErrorValidacion(
            "Una disputa sin motivo no se puede resolver.",
            error_code="comisiones.motivo_obligatorio",
        )
    plazo = int(rt.efectivo("comision_dias_disputa", uow.db) or 30)
    limite = (fila.calculada_at or _ahora()) + timedelta(days=plazo)
    fuera_de_plazo = _ahora() > (limite if limite.tzinfo else limite.replace(tzinfo=timezone.utc))

    disputa = DisputaComision(
        tenant_id=uow.tenant_id,
        liquidacion_id=fila.id,
        linea_id=linea_id,
        abierta_por=abierta_por,
        motivo=motivo.strip(),
        importe_reclamado=importe_reclamado,
        resolucion="Fuera del plazo de reclamación" if fuera_de_plazo else "",
    )
    uow.db.add(disputa)
    if fila.estado in ("calculada", "en_revision"):
        fila.estado = "disputada"
    uow.db.flush()
    registrar(
        uow.db,
        accion="comision.disputa_abierta",
        objeto="liquidacion_comision",
        objeto_id=fila.id,
        datos={"motivo": motivo, "fuera_de_plazo": fuera_de_plazo, "plazo_dias": plazo},
        tenant_id=uow.tenant_id,
    )
    return disputa


def resolver_disputa(
    uow: UnidadDeTrabajo,
    disputa_id: UUID,
    *,
    aceptar: bool,
    resolucion: str,
    por: UUID | None = None,
    ajuste: Decimal | None = None,
) -> DisputaComision:
    """Resuelve la disputa. Si se acepta, el ajuste entra como **línea nueva**.

    Nunca se edita la línea original: la liquidación tiene que poder leerse como
    lo que se calculó y lo que se corrigió después, con su motivo. Corregir en
    sitio deja un número que ya no coincide con lo que se comunicó y sin nada que
    explique la diferencia.
    """
    disputa = uow.db.get(DisputaComision, disputa_id)
    if disputa is None or disputa.tenant_id != uow.tenant_id:
        raise NoEncontrado("La disputa no existe", error_code="comisiones.disputa_no_encontrada")
    if not resolucion.strip():
        raise ErrorValidacion(
            "Resolver una disputa exige explicar la resolución.",
            error_code="comisiones.resolucion_obligatoria",
        )
    liquidacion = uow.db.get(Liquidacion, disputa.liquidacion_id)
    assert liquidacion is not None

    disputa.estado = "aceptada" if aceptar else "rechazada"
    disputa.resolucion = resolucion.strip()
    disputa.resuelta_por = por
    disputa.resuelta_at = _ahora()

    if aceptar and ajuste:
        uow.db.add(
            LineaComision(
                tenant_id=uow.tenant_id,
                liquidacion_id=liquidacion.id,
                origen="ajuste",
                origen_id=None,
                concepto=f"Ajuste por disputa: {resolucion.strip()[:200]}",
                base=Decimal(0),
                porcentaje=Decimal(0),
                importe=Decimal(ajuste),
                explicacion=disputa.motivo,
            )
        )
        liquidacion.total = _redondear(Decimal(liquidacion.total) + Decimal(ajuste))

    quedan = (
        uow.db.execute(
            select(DisputaComision).where(
                DisputaComision.tenant_id == uow.tenant_id,
                DisputaComision.liquidacion_id == liquidacion.id,
                DisputaComision.estado == "abierta",
                DisputaComision.id != disputa.id,
            )
        )
        .scalars()
        .all()
    )
    if not quedan and liquidacion.estado == "disputada":
        liquidacion.estado = "calculada"
    uow.db.flush()
    registrar(
        uow.db,
        accion="comision.disputa_resuelta",
        objeto="liquidacion_comision",
        objeto_id=liquidacion.id,
        datos={
            "disputa_id": str(disputa.id),
            "aceptada": aceptar,
            "ajuste": str(ajuste) if ajuste else None,
            "resolucion": resolucion,
        },
        tenant_id=uow.tenant_id,
    )
    return disputa


def marcar_pagada(
    uow: UnidadDeTrabajo, liquidacion_id: UUID, *, referencia: str, fecha: date | None = None
) -> Liquidacion:
    """Marca la liquidación como pagada. **Exige referencia** (CRM-03.02.03.03).

    «Pagada» sin dónde mirarlo no se puede comprobar, y es lo primero que se
    pregunta cuando alguien dice que no lo ha cobrado.
    """
    fila = uow.db.get(Liquidacion, liquidacion_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado(
            "La liquidación no existe", error_code="comisiones.liquidacion_no_encontrada"
        )
    if fila.estado != "aprobada":
        raise Conflicto(
            "Solo se paga lo aprobado",
            error_code="comisiones.no_aprobada",
            detalle={"estado": fila.estado},
        )
    if not referencia.strip():
        raise ErrorValidacion(
            "Marcar pagada exige la referencia del pago (nómina, remesa o factura).",
            error_code="comisiones.referencia_obligatoria",
        )
    fila.estado = "pagada"
    fila.pago_referencia = referencia.strip()
    fila.pagada_at = (
        datetime.combine(fecha, datetime.min.time(), tzinfo=timezone.utc) if fecha else _ahora()
    )
    registrar(
        uow.db,
        accion="comision.pagada",
        objeto="liquidacion_comision",
        objeto_id=fila.id,
        datos={"referencia": fila.pago_referencia, "total": str(fila.total)},
        tenant_id=uow.tenant_id,
    )
    uow.emitir(
        "commission.paid",
        subject=("liquidacion_comision", fila.id),
        data={
            "liquidacion_id": str(fila.id),
            "total": str(fila.total),
            "referencia": fila.pago_referencia,
        },
    )
    return fila


def revertir(
    uow: UnidadDeTrabajo,
    liquidacion_id: UUID,
    *,
    linea_id: UUID,
    motivo: str,
) -> LineaComision:
    """Revierte una comisión ya devengada (el pedido se cayó, se devolvió…).

    Se hace con una **línea negativa que apunta a la original**, no borrando. Una
    reversión invisible es la forma más rápida de que alguien vea su nómina y no
    reconozca el número, y entonces ya no se fía del resto tampoco.
    """
    liquidacion = uow.db.get(Liquidacion, liquidacion_id)
    if liquidacion is None or liquidacion.tenant_id != uow.tenant_id:
        raise NoEncontrado(
            "La liquidación no existe", error_code="comisiones.liquidacion_no_encontrada"
        )
    if not motivo.strip():
        raise ErrorValidacion(
            "Revertir una comisión exige motivo.", error_code="comisiones.motivo_obligatorio"
        )
    original = uow.db.get(LineaComision, linea_id)
    if original is None or original.liquidacion_id != liquidacion.id:
        raise NoEncontrado("La línea no existe", error_code="comisiones.linea_no_encontrada")

    fila = LineaComision(
        tenant_id=uow.tenant_id,
        liquidacion_id=liquidacion.id,
        origen=original.origen,
        origen_id=original.origen_id,
        concepto=f"Reversión: {original.concepto}"[:300],
        base=original.base,
        porcentaje=original.porcentaje,
        importe=-Decimal(original.importe),
        regla_id=original.regla_id,
        explicacion=motivo.strip(),
        reversion_de=original.id,
    )
    uow.db.add(fila)
    liquidacion.total = _redondear(Decimal(liquidacion.total) - Decimal(original.importe))
    uow.db.flush()
    registrar(
        uow.db,
        accion="comision.revertida",
        objeto="liquidacion_comision",
        objeto_id=liquidacion.id,
        datos={"linea_id": str(original.id), "importe": str(original.importe), "motivo": motivo},
        tenant_id=uow.tenant_id,
    )
    return fila


def detalle(db: Session, tenant_id: UUID, liquidacion_id: UUID) -> dict[str, Any]:
    """La liquidación con su desglose y sus disputas, lista para enseñar."""
    fila = db.get(Liquidacion, liquidacion_id)
    if fila is None or fila.tenant_id != tenant_id:
        raise NoEncontrado(
            "La liquidación no existe", error_code="comisiones.liquidacion_no_encontrada"
        )
    lineas = (
        db.execute(
            select(LineaComision)
            .where(
                LineaComision.tenant_id == tenant_id,
                LineaComision.liquidacion_id == liquidacion_id,
            )
            .order_by(LineaComision.created_at)
        )
        .scalars()
        .all()
    )
    disputas = (
        db.execute(
            select(DisputaComision).where(
                DisputaComision.tenant_id == tenant_id,
                DisputaComision.liquidacion_id == liquidacion_id,
            )
        )
        .scalars()
        .all()
    )
    return {
        "id": str(fila.id),
        "estado": fila.estado,
        "desde": str(fila.desde),
        "hasta": str(fila.hasta),
        "total": str(fila.total),
        "moneda": fila.moneda,
        "recortado_por_tope": str(fila.recortado_por_tope),
        "plan_aplicado": fila.plan_aplicado,
        "pago_referencia": fila.pago_referencia,
        "pagada_at": fila.pagada_at.isoformat() if fila.pagada_at else None,
        "lineas": [
            {
                "id": str(line.id),
                "origen": line.origen,
                "origen_id": str(line.origen_id) if line.origen_id else None,
                "concepto": line.concepto,
                "base": str(line.base),
                "porcentaje": str(line.porcentaje),
                "importe": str(line.importe),
                "explicacion": line.explicacion,
                "reversion_de": str(line.reversion_de) if line.reversion_de else None,
            }
            for line in lineas
        ],
        "disputas": [
            {
                "id": str(d.id),
                "estado": d.estado,
                "motivo": d.motivo,
                "resolucion": d.resolucion,
                "importe_reclamado": str(d.importe_reclamado) if d.importe_reclamado else None,
            }
            for d in disputas
        ],
    }
