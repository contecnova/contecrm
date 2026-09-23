"""Las métricas del cliente dentro de su ficha (CRM-01.01.05.06).

Facturación, margen, pedidos, incidencias, NPS y morosidad. Ninguna es del CRM:
viven en el ERP, en el sistema de soporte y en la herramienta de encuestas. Y
precisamente por eso hay que traerlas — un gestor que para preparar una reunión
tiene que abrir tres sistemas acaba preparándola con lo que recuerda.

Las decisiones, todas sobre lo mismo: **una copia con retraso puede hacer más daño
que no tener el dato**.

**Cada métrica lleva de cuándo es y de dónde viene.** Un margen sin fecha se lee
como el de hoy. Si es de hace un trimestre y el gestor negocia con él, negocia con
un número que ya no existe.

**Lo que no ha llegado no vale cero.** «Cero incidencias» y «no tenemos el dato de
incidencias» se pintan igual en un panel y significan lo contrario: uno es un
cliente tranquilo y el otro es una integración caída.

**Y no se calcula nada encima.** Sumar el margen de dos fuentes distintas o
derivar un ratio produce un número que no existe en ningún sistema y que nadie
puede cuadrar: cuando finanzas pregunte de dónde sale, la respuesta será «lo
calcula el CRM», que es la peor respuesta posible.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.errors import ErrorValidacion
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import DateTime, Index, Numeric, String, Text, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Las métricas que se pueden embeber. Cerrada porque cada una tiene su fuente, su
# frescura aceptable y su forma de leerse mal: «cero» significa una cosa en
# incidencias y otra en morosidad.
METRICAS = {
    "facturacion_12m": {"unidad": "moneda", "frescura_dias": 7},
    "margen_12m": {"unidad": "moneda", "frescura_dias": 7},
    "pedidos_12m": {"unidad": "numero", "frescura_dias": 7},
    "incidencias_abiertas": {"unidad": "numero", "frescura_dias": 1},
    "nps": {"unidad": "puntos", "frescura_dias": 180},
    "deuda_vencida": {"unidad": "moneda", "frescura_dias": 1},
    "dias_medios_de_pago": {"unidad": "numero", "frescura_dias": 30},
}


class MetricaCuenta(Base, TimestampMixin):
    """Una métrica traída de fuera, con su fecha y su origen."""

    __tablename__ = "metricas_cuenta"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    cuenta_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    clave: Mapped[str] = mapped_column(String(40), nullable=False)
    valor: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, info={"sensibilidad": "confidencial"}
    )
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    # De cuándo es el dato en el sistema de origen, no cuándo llegó aquí.
    vigente_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    origen: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    nota: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("tenant_id", "cuenta_id", "clave", name="uq_metrica_cuenta"),
        Index("ix_metricas_cuenta", "tenant_id", "cuenta_id"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def registrar(
    db: Session,
    *,
    tenant_id: UUID,
    cuenta_id: UUID,
    clave: str,
    valor: Decimal,
    vigente_at: datetime,
    origen: str,
    moneda: str = "EUR",
) -> MetricaCuenta:
    """Guarda una métrica traída de otro sistema.

    Se exige **origen y fecha de vigencia**. Sin el origen, el día que alguien
    pregunte de dónde sale el margen la respuesta será «del CRM», que es la peor
    posible; sin la fecha, el número se lee como el de hoy aunque sea de hace un
    trimestre.
    """
    if clave not in METRICAS:
        raise ErrorValidacion(
            f"Métrica «{clave}» desconocida",
            error_code="metricas.clave_invalida",
            detalle={"admitidas": sorted(METRICAS)},
        )
    if not origen.strip():
        raise ErrorValidacion(
            "Una métrica sin origen no se puede cuadrar con nada: el día que finanzas "
            "pregunte de dónde sale, la respuesta sería «la calcula el CRM».",
            error_code="metricas.sin_origen",
        )

    fila = db.execute(
        select(MetricaCuenta).where(
            MetricaCuenta.tenant_id == tenant_id,
            MetricaCuenta.cuenta_id == cuenta_id,
            MetricaCuenta.clave == clave,
        )
    ).scalar_one_or_none()
    if fila is not None and fila.vigente_at > vigente_at:
        # Un dato más viejo no pisa al bueno: los eventos llegan desordenados y
        # una reentrega antigua dejaría la ficha diciendo algo que ya no es.
        return fila
    if fila is None:
        fila = MetricaCuenta(tenant_id=tenant_id, cuenta_id=cuenta_id, clave=clave)
        db.add(fila)
    fila.valor = valor
    fila.vigente_at = vigente_at
    fila.origen = origen.strip()
    fila.moneda = moneda
    db.flush()
    return fila


def panel_de_la_cuenta(
    db: Session, tenant_id: UUID, *, cuenta_id: UUID, ahora: datetime | None = None
) -> dict[str, Any]:
    """Las métricas de la ficha, **con lo que falta dicho aparte**.

    «Cero incidencias» y «no tenemos el dato de incidencias» se pintan igual en un
    panel y significan lo contrario: uno es un cliente tranquilo y el otro es una
    integración caída. Aquí se distinguen, y lo que está viejo se marca en vez de
    enseñarse como si acabara de llegar.
    """
    momento = ahora or _ahora()
    filas = list(
        db.execute(
            select(MetricaCuenta).where(
                MetricaCuenta.tenant_id == tenant_id, MetricaCuenta.cuenta_id == cuenta_id
            )
        )
        .scalars()
        .all()
    )
    por_clave = {f.clave: f for f in filas}

    metricas: list[dict[str, Any]] = []
    caducadas: list[str] = []
    for clave, definicion in METRICAS.items():
        fila = por_clave.get(clave)
        if fila is None:
            continue
        dias = (momento - fila.vigente_at).days
        fresca = dias <= int(definicion["frescura_dias"])
        if not fresca:
            caducadas.append(clave)
        metricas.append(
            {
                "clave": clave,
                "valor": str(fila.valor),
                "unidad": definicion["unidad"],
                "moneda": fila.moneda if definicion["unidad"] == "moneda" else None,
                "de_hace_dias": dias,
                "fresca": fresca,
                "origen": fila.origen,
            }
        )

    sin_dato = sorted(set(METRICAS) - set(por_clave))
    return {
        "metricas": metricas,
        "sin_dato": sin_dato,
        "caducadas": caducadas,
        "completo": not sin_dato,
        "que_significa": (
            "Todas las métricas están y están frescas."
            if not sin_dato and not caducadas
            else " ".join(
                filter(
                    None,
                    [
                        f"No hay dato de: {', '.join(sin_dato)}. Eso NO es cero: «cero "
                        "incidencias» y «no tenemos el dato» se pintan igual y "
                        "significan lo contrario."
                        if sin_dato
                        else "",
                        f"Están viejas: {', '.join(caducadas)}. Se enseñan con su fecha "
                        "para que nadie negocie con un número que ya no existe."
                        if caducadas
                        else "",
                    ],
                )
            )
        ),
        "no_se_calcula_nada_encima": (
            "Estas cifras son las de sus sistemas, tal cual. Sumar o derivar aquí "
            "produciría un número que no existe en ningún sitio y que nadie puede "
            "cuadrar."
        ),
    }


def salud_de_la_integracion(
    db: Session, tenant_id: UUID, *, ahora: datetime | None = None
) -> dict[str, Any]:
    """Si las métricas están llegando, o si hace semanas que no.

    Existe porque el fallo aquí es silencioso: la integración se cae, los paneles
    siguen enseñando los últimos números y nadie lo nota hasta que alguien
    comenta que un cliente «lleva mucho sin facturar».
    """
    momento = ahora or _ahora()
    filas = list(
        db.execute(select(MetricaCuenta).where(MetricaCuenta.tenant_id == tenant_id))
        .scalars()
        .all()
    )
    if not filas:
        return {
            "medible": False,
            "porque": (
                "No ha llegado ninguna métrica. No es que los clientes no tengan "
                "actividad: es que no hay nada conectado."
            ),
        }

    por_clave: dict[str, datetime] = {}
    for fila in filas:
        actual = por_clave.get(fila.clave)
        if actual is None or fila.vigente_at > actual:
            por_clave[fila.clave] = fila.vigente_at

    paradas = [
        {
            "clave": clave,
            "ultima": ultima.isoformat(),
            "dias": (momento - ultima).days,
        }
        for clave, ultima in por_clave.items()
        if (momento - ultima) > timedelta(days=int(METRICAS[clave]["frescura_dias"]) * 3)
    ]

    return {
        "medible": True,
        "metricas_que_llegan": sorted(por_clave),
        "paradas": paradas,
        "todo_bien": not paradas,
        "que_significa": (
            "Todas las métricas conectadas están llegando."
            if not paradas
            else f"{len(paradas)} métricas llevan sin actualizarse mucho más de lo "
            "normal. El fallo aquí es silencioso: los paneles siguen enseñando los "
            "últimos números y nadie lo nota hasta que alguien comenta que un cliente "
            "«lleva mucho sin facturar»."
        ),
    }
