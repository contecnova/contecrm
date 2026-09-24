"""Ingresos recurrentes, calendario de ingreso y reparto entre comerciales
(CRM-03.01.01.06, .07, .08, .10, .11 · CRM-01.01.02.04).

Una oportunidad con un importe y una fecha vale para un negocio de venta puntual.
En cuanto hay suscripciones, servicios recurrentes o entregas por fases, ese
número **deja de significar nada**: 120.000 puede ser un pedido que se factura el
mes que viene o un contrato de tres años, y sumarlos en el mismo forecast produce
una previsión que nadie cumple y que nadie sabe por qué no cumple.

Las decisiones:

**Lo recurrente y lo puntual se separan siempre.** Y el ARR no es el importe
dividido por los años: un contrato de dos años con implantación cobrada aparte
tiene un ARR que no se parece a su valor total. Mezclarlos infla la métrica con la
que se valora la empresa.

**El calendario de ingreso es el que manda para la previsión.** Una oportunidad
grande que se cobra en doce meses no es un mes bueno: son doce meses decentes, y
la diferencia decide si alguien contrata a un comercial más.

**El reparto entre comerciales suma 100 o no se guarda.** Es la regla más tonta y
la que más se salta: con repartos al 60/60 las comisiones cuadran hacia arriba y
el descuadre lo encuentra finanzas tres meses después.

**El grupo de compra no es una lista de contactos.** Lo que hace falta es quién
decide, quién paga, quién usa y quién puede bloquear — y sobre todo **con quién no
se ha hablado**, que es lo único que un mapa aporta que el comercial no supiera.

**Y una oportunidad relacionada dice de qué tipo es la relación.** Una renovación
que sustituye a un contrato no suma ingreso nuevo: contarla como tal duplica el
crecimiento en el informe del trimestre.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import Date, Index, Numeric, String, Text, UniqueConstraint, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Qué tipo de ingreso trae una línea. Cerrada porque de esto salen el ARR y el
# MRR, y una etiqueta nueva sin decidir cómo entra en la métrica la rompe en
# silencio.
TIPOS_INGRESO = ("puntual", "recurrente", "consumo", "implantacion")

# Periodicidades admitidas para lo recurrente.
PERIODOS = {"mensual": 12, "trimestral": 4, "semestral": 2, "anual": 1}

# Papeles en la decisión de compra. Cerrada: son los que cambian lo que hay que
# hacer. Con texto libre, «interlocutor» acaba siendo el 80 % de los contactos y
# no dice nada.
ROLES_COMPRA = (
    "decisor",  # firma
    "economico",  # aprueba el gasto
    "prescriptor",  # recomienda técnicamente
    "usuario",  # lo va a usar
    "guardian",  # controla el acceso a los demás
    "campeon",  # empuja por dentro
)

# Cómo se relaciona una oportunidad con otra. Importa para el informe: una
# renovación que sustituye a un contrato no es ingreso nuevo.
RELACIONES = ("renovacion", "upsell", "cross_sell", "sustitucion", "ampliacion")

# Si una relación suma ingreso nuevo al crecimiento o no.
SUMA_INGRESO_NUEVO = {
    "renovacion": False,
    "sustitucion": False,
    "upsell": True,
    "cross_sell": True,
    "ampliacion": True,
}


class LineaIngreso(Base, TimestampMixin):
    """Cuándo se va a ingresar cada parte de una oportunidad."""

    __tablename__ = "lineas_ingreso"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    oportunidad_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    periodo: Mapped[date] = mapped_column(Date, nullable=False)
    importe: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="puntual")
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")

    __table_args__ = (
        Index("ix_lineas_ingreso_periodo", "tenant_id", "periodo"),
        Index("ix_lineas_ingreso_op", "tenant_id", "oportunidad_id"),
    )


class ParticipacionComercial(Base, TimestampMixin):
    """Quién se lleva qué parte de una oportunidad."""

    __tablename__ = "participaciones_comerciales"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    oportunidad_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # `credito` reparte la comisión; `overlay` es apoyo que no resta al titular.
    # Se distinguen porque un overlay al 100 % no descuadra nada y un crédito sí.
    papel: Mapped[str] = mapped_column(String(20), nullable=False, default="credito")
    porcentaje: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    motivo: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "oportunidad_id", "usuario_id", "papel", name="uq_participacion"
        ),
    )


class RolCompra(Base, TimestampMixin):
    """Qué papel tiene cada contacto en la decisión (CRM-01.01.02.04)."""

    __tablename__ = "roles_compra"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    oportunidad_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    contacto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    rol: Mapped[str] = mapped_column(String(20), nullable=False, info={"opciones": ROLES_COMPRA})
    # Cómo de a favor está, de -2 a 2. Es una valoración y por eso lleva motivo.
    postura: Mapped[int] = mapped_column(Numeric(2, 0), nullable=False, default=0)
    motivo: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("tenant_id", "oportunidad_id", "contacto_id", "rol", name="uq_rol_compra"),
    )


class RelacionOportunidad(Base, TimestampMixin):
    """De qué viene esta oportunidad y qué es de lo anterior."""

    __tablename__ = "relaciones_oportunidad"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    origen_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    destino_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    datos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "origen_id", "destino_id", "tipo", name="uq_relacion_op"),
    )


def _hoy() -> date:
    return datetime.now(timezone.utc).date()


# ── Recurrente frente a puntual (CRM-03.01.01.06) ─────────────────────────


def metricas_de_ingreso(*, lineas: list[dict[str, Any]]) -> dict[str, Any]:
    """ARR, MRR, TCV y ACV, **separando lo recurrente de lo que no lo es**.

    El error clásico es dividir el valor total por los años: un contrato de dos
    años con la implantación cobrada aparte tiene un ARR que no se parece a eso, y
    la métrica con la que se valora la empresa sale inflada.

    Aquí cada línea dice de qué tipo es, y lo que no es recurrente **no entra en
    el ARR** por mucho que se repita todos los años.
    """
    desconocidos = sorted(
        {str(x.get("tipo")) for x in lineas if str(x.get("tipo")) not in TIPOS_INGRESO}
    )
    if desconocidos:
        raise ErrorValidacion(
            f"Tipos de ingreso desconocidos: {', '.join(desconocidos)}",
            error_code="ingresos.tipo_invalido",
            detalle={"admitidos": list(TIPOS_INGRESO)},
        )

    recurrentes = [x for x in lineas if x.get("tipo") == "recurrente"]
    puntuales = [x for x in lineas if x.get("tipo") != "recurrente"]

    arr = Decimal(0)
    for linea in recurrentes:
        periodo = str(linea.get("periodo") or "anual")
        if periodo not in PERIODOS:
            raise ErrorValidacion(
                f"Periodicidad «{periodo}» desconocida",
                error_code="ingresos.periodo_invalido",
                detalle={"admitidas": sorted(PERIODOS)},
            )
        arr += Decimal(str(linea.get("importe") or 0)) * PERIODOS[periodo]

    tcv = sum(
        (Decimal(str(x.get("valor_total") or x.get("importe") or 0)) for x in lineas), Decimal(0)
    )
    meses = max(1, int(lineas[0].get("meses_de_contrato") or 12)) if lineas else 12

    return {
        "arr": str(arr.quantize(Decimal("0.01"))),
        "mrr": str((arr / 12).quantize(Decimal("0.01"))),
        "tcv": str(tcv.quantize(Decimal("0.01"))),
        "acv": str((tcv / Decimal(meses) * 12).quantize(Decimal("0.01"))),
        "puntual": str(sum((Decimal(str(x.get("importe") or 0)) for x in puntuales), Decimal(0))),
        "hay_recurrente": bool(recurrentes),
        "porque": (
            "El ARR sale solo de lo recurrente. Dividir el valor total por los años "
            "mete la implantación dentro y la métrica con la que se valora la empresa "
            "sale inflada."
        ),
        "lo_que_no_cuenta_como_arr": sorted({str(x.get("tipo")) for x in puntuales}),
    }


# ── Calendario de ingreso (CRM-03.01.01.07) ───────────────────────────────


def planificar_ingresos(
    uow: UnidadDeTrabajo,
    *,
    oportunidad_id: UUID,
    importe_total: Decimal,
    desde: date,
    meses: int,
    tipo: str = "recurrente",
    moneda: str = "EUR",
) -> dict[str, Any]:
    """Reparte el importe por periodos, **que es lo que usa la previsión**.

    Una oportunidad grande que se cobra en doce meses no es un mes bueno: son doce
    meses decentes. La diferencia no es cosmética — decide si alguien contrata a
    un comercial más o si se para una inversión.

    El **redondeo se ajusta en el último periodo**. Repartir 100 entre 3 y dejar
    que sobre un céntimo hace que la suma del calendario no cuadre con el importe
    de la oportunidad, y ese descuadre aparece en un informe seis meses después
    sin que nadie sepa de dónde sale.
    """
    if meses <= 0:
        raise ErrorValidacion(
            "Un calendario de cero periodos no reparte nada",
            error_code="ingresos.periodos_invalidos",
        )
    if tipo not in TIPOS_INGRESO:
        raise ErrorValidacion(
            f"Tipo de ingreso «{tipo}» desconocido", error_code="ingresos.tipo_invalido"
        )

    total = Decimal(str(importe_total))
    por_periodo = (total / meses).quantize(Decimal("0.01"))
    lineas: list[LineaIngreso] = []
    acumulado = Decimal(0)

    for i in range(meses):
        anyo = desde.year + (desde.month - 1 + i) // 12
        mes = (desde.month - 1 + i) % 12 + 1
        importe = por_periodo if i < meses - 1 else (total - acumulado)
        acumulado += importe
        fila = LineaIngreso(
            tenant_id=uow.tenant_id,
            oportunidad_id=oportunidad_id,
            periodo=date(anyo, mes, 1),
            importe=importe,
            tipo=tipo,
            moneda=moneda,
        )
        uow.db.add(fila)
        lineas.append(fila)

    uow.db.flush()
    return {
        "periodos": len(lineas),
        "desde": lineas[0].periodo.isoformat(),
        "hasta": lineas[-1].periodo.isoformat(),
        "suma": str(acumulado),
        "cuadra": acumulado == total,
        "porque": (
            "El redondeo se ajusta en el último periodo: si sobrara un céntimo, la suma "
            "del calendario no cuadraría con el importe y el descuadre saldría en un "
            "informe seis meses después sin que nadie supiera de dónde viene."
        ),
    }


def previsto_por_periodo(
    db: Session, tenant_id: UUID, *, desde: date, hasta: date
) -> dict[str, Any]:
    """Lo que se espera ingresar por mes, según los calendarios.

    Es distinto del forecast por fecha de cierre, y las dos cosas hacen falta: una
    dice cuándo se firma y otra cuándo entra el dinero. Confundirlas es lo que
    hace que un trimestre «excelente» no se note en caja hasta el siguiente.
    """
    filas = list(
        db.execute(
            select(LineaIngreso).where(
                LineaIngreso.tenant_id == tenant_id,
                LineaIngreso.periodo >= desde,
                LineaIngreso.periodo <= hasta,
            )
        )
        .scalars()
        .all()
    )
    por_periodo: dict[str, Decimal] = {}
    for fila in filas:
        clave = fila.periodo.isoformat()
        por_periodo[clave] = por_periodo.get(clave, Decimal(0)) + Decimal(fila.importe)

    return {
        "periodos": {k: str(v) for k, v in sorted(por_periodo.items())},
        "total": str(sum(por_periodo.values(), Decimal(0))),
        "medible": bool(filas),
        "que_es": (
            "Cuándo entra el dinero, que no es lo mismo que cuándo se firma. "
            "Confundirlos hace que un trimestre «excelente» no se note en caja hasta el "
            "siguiente."
        ),
    }


# ── Reparto entre comerciales (CRM-03.01.01.08) ───────────────────────────


def repartir_credito(
    uow: UnidadDeTrabajo, *, oportunidad_id: UUID, participaciones: list[dict[str, Any]]
) -> dict[str, Any]:
    """Guarda el reparto, **exigiendo que el crédito sume 100**.

    Es la regla más tonta y la que más se salta. Con repartos al 60/60 las
    comisiones cuadran hacia arriba y el descuadre lo encuentra finanzas tres
    meses después, cuando ya se ha pagado.

    El **overlay no resta**: es apoyo que se reconoce sin quitarle nada al
    titular, y por eso puede sumar lo que sea. Mezclarlo con el crédito es lo que
    hace que la gente invente porcentajes para que cuadre.
    """
    creditos = [p for p in participaciones if str(p.get("papel", "credito")) == "credito"]
    suma = sum(Decimal(str(p.get("porcentaje") or 0)) for p in creditos)
    if creditos and suma != Decimal(100):
        raise ErrorValidacion(
            f"El crédito suma {suma} y tiene que sumar 100. Con repartos al 60/60 las "
            "comisiones cuadran hacia arriba y el descuadre lo encuentra finanzas tres "
            "meses después, cuando ya se ha pagado.",
            error_code="ingresos.credito_descuadrado",
            detalle={"suma": str(suma)},
        )

    uow.db.execute(
        select(ParticipacionComercial).where(
            ParticipacionComercial.tenant_id == uow.tenant_id,
            ParticipacionComercial.oportunidad_id == oportunidad_id,
        )
    )
    guardadas = []
    for p in participaciones:
        fila = ParticipacionComercial(
            tenant_id=uow.tenant_id,
            oportunidad_id=oportunidad_id,
            usuario_id=UUID(str(p["usuario_id"])),
            papel=str(p.get("papel", "credito")),
            porcentaje=Decimal(str(p.get("porcentaje") or 0)),
            motivo=str(p.get("motivo") or ""),
        )
        uow.db.add(fila)
        guardadas.append(fila)
    uow.db.flush()

    return {
        "participaciones": len(guardadas),
        "credito_suma": str(suma),
        "overlay": [
            {"usuario_id": str(f.usuario_id), "porcentaje": str(f.porcentaje)}
            for f in guardadas
            if f.papel == "overlay"
        ],
        "porque_el_overlay_no_resta": (
            "Es apoyo que se reconoce sin quitarle nada al titular. Mezclarlo con el "
            "crédito es lo que hace que la gente invente porcentajes para que cuadre."
        ),
    }


# ── Grupo de compra (CRM-03.01.01.10, CRM-01.01.02.04) ────────────────────


def anotar_rol(
    uow: UnidadDeTrabajo,
    *,
    oportunidad_id: UUID,
    contacto_id: UUID,
    rol: str,
    postura: int = 0,
    motivo: str = "",
) -> RolCompra:
    """Anota qué papel tiene alguien en esta decisión.

    Y **la postura exige motivo cuando es negativa**: decir que alguien está en
    contra sin explicar por qué es una etiqueta que otro comercial leerá dentro de
    seis meses y aplicará sin poder contrastarla — y encima es una valoración
    sobre una persona identificada.
    """
    if rol not in ROLES_COMPRA:
        raise ErrorValidacion(
            f"Rol de compra «{rol}» desconocido",
            error_code="compra.rol_invalido",
            detalle={"admitidos": list(ROLES_COMPRA)},
        )
    if postura < 0 and not motivo.strip():
        raise ErrorValidacion(
            "Decir que alguien está en contra sin explicar por qué es una etiqueta que "
            "otro leerá en seis meses y aplicará sin poder contrastarla.",
            error_code="compra.postura_sin_motivo",
        )

    fila = uow.db.execute(
        select(RolCompra).where(
            RolCompra.tenant_id == uow.tenant_id,
            RolCompra.oportunidad_id == oportunidad_id,
            RolCompra.contacto_id == contacto_id,
            RolCompra.rol == rol,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = RolCompra(
            tenant_id=uow.tenant_id,
            oportunidad_id=oportunidad_id,
            contacto_id=contacto_id,
            rol=rol,
        )
        uow.db.add(fila)
    fila.postura = max(-2, min(2, postura))
    fila.motivo = motivo.strip()
    uow.db.flush()
    return fila


def grupo_de_compra(
    db: Session, tenant_id: UUID, *, oportunidad_id: UUID, contactados: set[str] | None = None
) -> dict[str, Any]:
    """El mapa de la decisión: quién manda, quién ayuda y **a quién no se ha visto**.

    Lo que hace útil esto no es la lista: es lo que falta. Una oportunidad sin
    decisor identificado no es una oportunidad avanzada por mucho que el
    presupuesto esté mandado, y un económico con el que nadie ha hablado es la
    razón más habitual de que un cierre «seguro» se caiga en la última semana.
    """
    filas = list(
        db.execute(
            select(RolCompra).where(
                RolCompra.tenant_id == tenant_id,
                RolCompra.oportunidad_id == oportunidad_id,
            )
        )
        .scalars()
        .all()
    )
    vistos = contactados or set()
    por_rol: dict[str, list[dict[str, Any]]] = {}
    for fila in filas:
        por_rol.setdefault(fila.rol, []).append(
            {
                "contacto_id": str(fila.contacto_id),
                "postura": int(fila.postura),
                "motivo": fila.motivo,
                "hablado": str(fila.contacto_id) in vistos,
            }
        )

    faltan_roles = [r for r in ("decisor", "economico") if r not in por_rol]
    sin_hablar = [
        c["contacto_id"]
        for rol in ("decisor", "economico")
        for c in por_rol.get(rol, [])
        if not c["hablado"]
    ]
    detractores = [c for lista in por_rol.values() for c in lista if c["postura"] < 0]

    return {
        "roles": por_rol,
        "faltan_por_identificar": faltan_roles,
        "clave_sin_hablar": sin_hablar,
        "en_contra": len(detractores),
        "completo": not faltan_roles and not sin_hablar,
        "que_mirar": (
            "El mapa está cubierto y se ha hablado con quien decide."
            if not faltan_roles and not sin_hablar
            else " ".join(
                filter(
                    None,
                    [
                        f"Sin identificar: {', '.join(faltan_roles)}." if faltan_roles else "",
                        f"{len(sin_hablar)} personas que deciden o pagan con las que "
                        "nadie ha hablado: es la razón más habitual de que un cierre "
                        "«seguro» se caiga en la última semana."
                        if sin_hablar
                        else "",
                    ],
                )
            )
        ),
    }


# ── Oportunidades relacionadas (CRM-03.01.01.11) ──────────────────────────


def relacionar(
    uow: UnidadDeTrabajo, *, origen_id: UUID, destino_id: UUID, tipo: str
) -> dict[str, Any]:
    """Enlaza dos oportunidades diciendo **qué tipo de relación es**.

    Importa para el informe: una renovación que sustituye a un contrato **no es
    ingreso nuevo**, y contarla como tal duplica el crecimiento del trimestre. Es
    de los errores que más tarda en descubrirse, porque el número sale bien.
    """
    if tipo not in RELACIONES:
        raise ErrorValidacion(
            f"Relación «{tipo}» desconocida",
            error_code="oportunidad.relacion_invalida",
            detalle={"admitidas": list(RELACIONES)},
        )
    if origen_id == destino_id:
        raise ErrorValidacion(
            "Una oportunidad no se relaciona consigo misma",
            error_code="oportunidad.relacion_circular",
        )
    fila = uow.db.execute(
        select(RelacionOportunidad).where(
            RelacionOportunidad.tenant_id == uow.tenant_id,
            RelacionOportunidad.origen_id == origen_id,
            RelacionOportunidad.destino_id == destino_id,
            RelacionOportunidad.tipo == tipo,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = RelacionOportunidad(
            tenant_id=uow.tenant_id, origen_id=origen_id, destino_id=destino_id, tipo=tipo
        )
        uow.db.add(fila)
        uow.db.flush()

    return {
        "tipo": tipo,
        "suma_ingreso_nuevo": SUMA_INGRESO_NUEVO[tipo],
        "porque": (
            "Una renovación o una sustitución mantienen ingreso, no lo añaden. Contarlas "
            "como nuevo duplica el crecimiento del trimestre, y es de los errores que "
            "más tarda en descubrirse porque el número sale bien."
            if not SUMA_INGRESO_NUEVO[tipo]
            else "Esto sí añade ingreso sobre lo que ya había."
        ),
    }


def crecimiento_real(*, cerradas: list[dict[str, Any]]) -> dict[str, Any]:
    """Cuánto ha crecido de verdad, descontando lo que solo se mantiene.

    Es la cifra que se enseña en el comité y la que más se infla sin querer:
    sumar renovaciones al crecimiento hace que un año plano parezca bueno, y la
    corrección llega cuando alguien cruza con facturación.
    """
    nuevo = Decimal(0)
    mantenido = Decimal(0)
    for op in cerradas:
        importe = Decimal(str(op.get("importe") or 0))
        tipo = str(op.get("relacion") or "")
        if tipo and not SUMA_INGRESO_NUEVO.get(tipo, True):
            mantenido += importe
        else:
            nuevo += importe

    return {
        "ingreso_nuevo": str(nuevo),
        "ingreso_mantenido": str(mantenido),
        "total_cerrado": str(nuevo + mantenido),
        "pct_que_es_crecimiento": (
            round(float(nuevo / (nuevo + mantenido) * 100), 1) if (nuevo + mantenido) else 0.0
        ),
        "porque": (
            "Las renovaciones y las sustituciones mantienen ingreso; no lo añaden. "
            "Sumarlas al crecimiento hace que un año plano parezca bueno hasta que "
            "alguien cruza con facturación."
        ),
    }
