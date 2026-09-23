"""Salud de cuenta, riesgo y churn (CRM-05.02.01.04).

Un número de salud que nadie sabe de dónde sale no cambia ninguna conversación.
Lo que hace que un gestor llame a un cliente es «llevan cinco semanas sin abrir un
ticket **y antes abrían uno por semana**», no un 42 en rojo.

Cuatro decisiones:

**La salud se compone de señales con nombre.** Cada una aporta, cada una se
enseña, y el peso de cada una es configurable por tenant — en una empresa de
suscripción el uso del producto manda, y en una de proyectos manda el margen.

**Una señal sin dato no puntúa cero: no puntúa.** Contar «sin datos de uso» como
uso nulo hunde a todos los clientes de quien todavía no ha conectado la telemetría.
Se reparte el peso entre las que sí hay y se dice cuántas faltaban.

**La tendencia pesa más que el nivel.** Un cliente en 60 bajando es un problema y
uno en 45 subiendo es una recuperación; la foto fija los confunde.

**Riesgo no es churn confirmado.** Esto señala a quién mirar, no a quién dar por
perdido; el texto que se devuelve lo dice con esas palabras para que nadie use la
lista como una baja anticipada.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
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

logger = get_logger(__name__)

CENTESIMA = Decimal("0.01")

# Señales cerradas: si alguien quiere una nueva, se añade aquí y se documenta qué
# significa. Una lista abierta acaba con quince señales que miden lo mismo.
SENALES = (
    "uso",  # cuánto usan lo que compraron
    "soporte",  # incidencias abiertas y reabiertas
    "relacion",  # contactos vivos, reuniones, respuesta
    "pago",  # puntualidad de cobro
    "valor",  # importe y evolución de la cuenta
    "patrocinador",  # si sigue estando quien firmó
)

# Pesos de partida. Son ajustables por tenant: en suscripción manda el uso, en
# proyectos manda el valor. Ninguno está en el código como verdad.
PESOS_POR_DEFECTO = {
    "uso": 30,
    "soporte": 20,
    "relacion": 20,
    "pago": 10,
    "valor": 10,
    "patrocinador": 10,
}

NIVELES = ("sana", "vigilar", "riesgo", "critica")


class SaludCuenta(Base, TimestampMixin):
    """La última foto de salud de una cuenta, con sus porqués."""

    __tablename__ = "salud_cuentas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    cuenta_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    puntuacion: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    anterior: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    nivel: Mapped[str] = mapped_column(String(20), nullable=False, default="vigilar")
    # [{senal, valor, peso, aporta, tendencia}] — lo que sostiene el número.
    detalle: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    senales_ausentes: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Con menos de la mitad del peso cubierto, el número se guarda pero se marca
    # como poco fiable: es la diferencia entre «está mal» y «no sé cómo está».
    fiable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    motivo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    medida_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "cuenta_id", "medida_at", name="uq_salud_cuenta_momento"),
        Index("ix_salud_cuentas", "tenant_id", "cuenta_id"),
        Index("ix_salud_cuentas_nivel", "tenant_id", "nivel"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _redondear(valor: Decimal | float) -> Decimal:
    return Decimal(str(valor)).quantize(CENTESIMA, rounding=ROUND_HALF_UP)


def _nivel(puntuacion: Decimal, umbrales: dict[str, int]) -> str:
    valor = float(puntuacion)
    if valor >= umbrales["sana"]:
        return "sana"
    if valor >= umbrales["vigilar"]:
        return "vigilar"
    if valor >= umbrales["riesgo"]:
        return "riesgo"
    return "critica"


def medir(
    uow: UnidadDeTrabajo,
    *,
    cuenta_id: UUID,
    senales: dict[str, Any],
    pesos: dict[str, int] | None = None,
    umbrales: dict[str, int] | None = None,
) -> SaludCuenta:
    """Calcula la salud de una cuenta a partir de señales con nombre.

    Cada señal llega como un 0–100 (y, si se sabe, su valor de hace un periodo).
    Las que no llegan **no puntúan cero**: se reparte su peso entre las que sí
    hay. Contar «sin datos de uso» como uso nulo hundiría a todos los clientes de
    quien aún no ha conectado la telemetría, y esa lista de críticos no la mira
    nadie dos veces.
    """
    pesos_efectivos = {**PESOS_POR_DEFECTO, **(pesos or {})}
    desconocidas = set(pesos_efectivos) - set(SENALES)
    if desconocidas:
        raise ErrorValidacion(
            f"Señales de salud no reconocidas: {sorted(desconocidas)}. Las válidas "
            f"son {list(SENALES)}; añadir una nueva pasa por documentar qué mide.",
            error_code="salud.senal_desconocida",
        )
    limites = {"sana": 75, "vigilar": 55, "riesgo": 35, **(umbrales or {})}

    detalle: list[dict[str, Any]] = []
    ausentes: list[str] = []
    peso_cubierto = 0
    acumulado = 0.0

    for senal in SENALES:
        peso = int(pesos_efectivos.get(senal, 0))
        if peso <= 0:
            continue
        dato = senales.get(senal)
        if dato is None:
            ausentes.append(senal)
            continue
        if isinstance(dato, dict):
            actual = float(dato.get("valor", 0))
            previo = dato.get("anterior")
        else:
            actual = float(dato)
            previo = None
        actual = max(0.0, min(100.0, actual))
        peso_cubierto += peso
        acumulado += actual * peso
        tendencia = None
        if previo is not None:
            delta = actual - float(previo)
            tendencia = "sube" if delta > 2 else ("baja" if delta < -2 else "estable")
        detalle.append(
            {
                "senal": senal,
                "valor": round(actual, 2),
                "peso": peso,
                "aporta": round(actual * peso / 100, 2),
                "tendencia": tendencia,
            }
        )

    if peso_cubierto == 0:
        raise ErrorValidacion(
            "No ha llegado ninguna señal con peso: sin datos no se inventa una "
            "salud, porque un 50 por defecto se lee como «regular» y no como "
            "«no lo sabemos».",
            error_code="salud.sin_senales",
        )

    # Se normaliza sobre el peso que sí ha llegado: si falta el 40 % del peso, el
    # número sale del 60 % restante y se avisa, en vez de salir hundido.
    puntuacion = _redondear(acumulado / peso_cubierto)
    total = sum(int(p) for p in pesos_efectivos.values() if int(p) > 0)
    cobertura = round(100 * peso_cubierto / total, 1) if total else 0.0
    fiable = cobertura >= 50

    previa = (
        uow.db.execute(
            select(SaludCuenta)
            .where(SaludCuenta.tenant_id == uow.tenant_id, SaludCuenta.cuenta_id == cuenta_id)
            .order_by(SaludCuenta.medida_at.desc())
        )
        .scalars()
        .first()
    )

    # La tendencia pesa más que el nivel: un 60 bajando es un problema y un 45
    # subiendo es una recuperación. Se dice en el motivo, no se toca el número.
    bajadas = [d["senal"] for d in detalle if d["tendencia"] == "baja"]
    trozos = [
        f"{d['senal']} {d['valor']:.0f}" for d in sorted(detalle, key=lambda d: -d["aporta"])[:3]
    ]
    motivo = "Pesa sobre todo: " + ", ".join(trozos) + "."
    if bajadas:
        motivo += f" Bajando: {', '.join(bajadas)}."
    if ausentes:
        motivo += f" Sin datos de: {', '.join(ausentes)} ({100 - cobertura:.0f}% del peso)."
    if previa is not None:
        delta = float(puntuacion) - float(previa.puntuacion)
        if abs(delta) >= 5:
            motivo += f" {'Sube' if delta > 0 else 'Baja'} {abs(delta):.0f} puntos desde la última medida."

    fila = SaludCuenta(
        tenant_id=uow.tenant_id,
        cuenta_id=cuenta_id,
        puntuacion=puntuacion,
        anterior=previa.puntuacion if previa is not None else None,
        nivel=_nivel(puntuacion, limites),
        detalle=sorted(detalle, key=lambda d: -d["aporta"]),
        senales_ausentes=ausentes,
        fiable=fiable,
        motivo=motivo,
        medida_at=_ahora(),
    )
    uow.db.add(fila)
    uow.db.flush()

    # Se publica para que `party` lo pueda enseñar en la ficha de la cuenta
    # (CRM-01.01.05.07). Por evento y no por lectura directa: ningún servicio lee
    # el esquema de otro, y una salud que solo existe aquí no la ve quien tiene
    # al cliente delante.
    uow.emitir(
        "account.health.scored",
        subject=("cuenta", str(cuenta_id)),
        data={
            "cuenta_id": str(cuenta_id),
            "puntuacion": float(puntuacion),
            "nivel": fila.nivel,
            # La fiabilidad viaja DENTRO del evento: si se quedara aquí, el que
            # lo pinta enseñaría un 62 en rojo calculado con la mitad de las
            # señales sin saberlo.
            "fiable": fiable,
            "motivo": motivo,
            "medida_at": fila.medida_at.isoformat(),
        },
        dedup_key=f"salud:{uow.tenant_id}:{cuenta_id}:{fila.medida_at.isoformat()}",
    )

    logger.info(
        "salud.medida",
        cuenta_id=str(cuenta_id),
        puntuacion=float(puntuacion),
        nivel=fila.nivel,
        cobertura=cobertura,
    )
    return fila


def en_riesgo(
    db: Session,
    tenant_id: UUID,
    *,
    dias: int = 60,
    incluir_no_fiables: bool = False,
    ahora: datetime | None = None,
) -> dict[str, Any]:
    """Las cuentas a las que hay que llamar — y por qué a cada una.

    **Riesgo no es churn confirmado.** Esto señala a quién mirar; el texto lo dice
    con esas palabras a propósito, para que la lista no acabe usándose como una
    baja anticipada en una reunión de dirección.

    Las medidas poco fiables quedan fuera por defecto y **se cuentan aparte**: si
    desaparecieran sin más, una instalación a la que le falta la mitad de las
    señales vería una lista corta y creería que va bien.
    """
    momento = ahora or _ahora()
    desde = momento - timedelta(days=dias)
    filas = (
        db.execute(
            select(SaludCuenta)
            .where(SaludCuenta.tenant_id == tenant_id, SaludCuenta.medida_at >= desde)
            .order_by(SaludCuenta.cuenta_id, SaludCuenta.medida_at.desc())
        )
        .scalars()
        .all()
    )
    ultima: dict[UUID, SaludCuenta] = {}
    for fila in filas:
        ultima.setdefault(fila.cuenta_id, fila)

    riesgo = []
    ocultas = 0
    for fila in ultima.values():
        if fila.nivel not in ("riesgo", "critica"):
            continue
        if not fila.fiable and not incluir_no_fiables:
            ocultas += 1
            continue
        riesgo.append(
            {
                "cuenta_id": str(fila.cuenta_id),
                "puntuacion": float(fila.puntuacion),
                "nivel": fila.nivel,
                "fiable": fila.fiable,
                "porque": fila.motivo,
                "peor_senal": fila.detalle[-1]["senal"] if fila.detalle else None,
                "medida_at": fila.medida_at.isoformat(),
            }
        )

    return {
        "cuentas": sorted(riesgo, key=lambda c: c["puntuacion"]),
        "medidas_en_ventana": len(ultima),
        "ocultas_por_poco_fiables": ocultas,
        "que_significa": (
            "Cuentas que conviene mirar, no cuentas perdidas: la puntuación dice "
            "dónde mirar primero, no qué dar por hecho."
        ),
        "aviso": (
            ""
            if not ocultas
            else f"{ocultas} cuentas en riesgo no salen porque su medida cubre menos "
            "de la mitad de las señales. No son cuentas sanas: son cuentas sin medir."
        ),
    }


def historia(
    db: Session, tenant_id: UUID, cuenta_id: UUID, *, limite: int = 12
) -> list[dict[str, Any]]:
    """La evolución de una cuenta. Sin ella, la salud es una foto y el churn se ve
    venir por la tendencia, no por el nivel."""
    filas = (
        db.execute(
            select(SaludCuenta)
            .where(SaludCuenta.tenant_id == tenant_id, SaludCuenta.cuenta_id == cuenta_id)
            .order_by(SaludCuenta.medida_at.desc())
            .limit(max(1, limite))
        )
        .scalars()
        .all()
    )
    return [
        {
            "puntuacion": float(f.puntuacion),
            "nivel": f.nivel,
            "fiable": f.fiable,
            "porque": f.motivo,
            "medida_at": f.medida_at.isoformat(),
        }
        for f in filas
    ]
