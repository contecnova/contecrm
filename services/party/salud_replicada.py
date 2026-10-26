"""La salud de la cuenta, replicada para poder enseñarla en la ficha
(CRM-01.01.05.07).

La salud se calcula en `intelligence`, que es donde están las señales y los pesos.
Pero quien tiene al cliente delante abre **la ficha de la cuenta**, y un número que
solo existe en otro servicio no lo ve nadie — con lo cual no cambia ninguna
conversación, que era todo el objetivo.

Este servicio no lee el esquema de aquel, así que llega por evento y se guarda una
proyección local. Y de ahí salen las tres decisiones que importan:

**La proyección lleva su fecha y dice cuándo se midió.** Un 42 en rojo de hace tres
meses no es una alerta: es un recuerdo. Enseñarlo sin la fecha hace que alguien
llame a un cliente por algo que ya se resolvió.

**La fiabilidad viaja dentro y se respeta.** Una salud calculada con la mitad de
las señales no es un dato, y pintarla igual que una completa es lo que hace que la
lista de clientes en riesgo deje de mirarse.

**Y esto no es la verdad, es una copia.** Si alguien quiere el detalle, va al
servicio que lo calcula. Aquí está lo justo para que el gestor sepa que tiene que
mirarlo — nunca para decidir nada automático, porque una copia con retraso que
dispara acciones acaba mandando correos de retención a clientes que renovaron
ayer.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import Boolean, DateTime, Index, Numeric, String, Text, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)


def _dias_vigencia(db: Session) -> int:
    """A partir de cuántos días la medida deja de valer para actuar.

    No se borra: se marca. Un 42 en rojo de hace tres meses es un recuerdo, no
    una alerta.

    Era una constante de módulo —45— igual para todos. Un negocio con ciclos
    largos la quiere más alta, y uno de soporte diario más baja; mientras viva
    en el código, cambiarla es desplegar.

    Se lee aquí y **una sola vez por llamada**: `efectivo()` va a la base, y
    metido en un bucle sería una consulta por vuelta.
    """
    from crmcore.runtime import settings as rt

    from services.party.ajustes import ajustes

    return int(rt.efectivo("salud_dias_vigencia", db) or ajustes().salud_dias_vigencia)


class SaludCuentaReplicada(Base, TimestampMixin):
    """Copia local de la última salud medida. No es la verdad: es una copia."""

    __tablename__ = "salud_cuenta_replicada"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    cuenta_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    puntuacion: Mapped[Any] = mapped_column(Numeric(5, 2), nullable=False)
    nivel: Mapped[str] = mapped_column(String(20), nullable=False)
    # Viene dentro del evento a propósito: si se quedara en el otro servicio, aquí
    # se pintaría un 62 en rojo calculado con la mitad de las señales sin saberlo.
    fiable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    motivo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    medida_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "cuenta_id", name="uq_salud_replicada"),
        Index("ix_salud_replicada_nivel", "tenant_id", "nivel"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def proyectar(db: Session, *, tenant_id: UUID, datos: dict[str, Any]) -> SaludCuentaReplicada:
    """Guarda la última medida que ha llegado por el bus.

    Se queda **solo la última**: un histórico aquí sería una segunda copia del que
    ya tiene el servicio que la calcula, y dos históricos del mismo número acaban
    diciendo cosas distintas.

    Y **no se acepta una medida más vieja que la que hay**. Los eventos pueden
    llegar desordenados, y una reentrega antigua pisaría la buena sin que nadie lo
    notara: la ficha volvería a decir «en riesgo» un mes después de que se
    arreglara.
    """
    cuenta_id = UUID(str(datos["cuenta_id"]))
    medida = datos.get("medida_at")
    medida_at = datetime.fromisoformat(str(medida)) if not isinstance(medida, datetime) else medida
    if medida_at.tzinfo is None:
        medida_at = medida_at.replace(tzinfo=timezone.utc)

    fila = db.execute(
        select(SaludCuentaReplicada).where(
            SaludCuentaReplicada.tenant_id == tenant_id,
            SaludCuentaReplicada.cuenta_id == cuenta_id,
        )
    ).scalar_one_or_none()

    if fila is not None and fila.medida_at >= medida_at:
        logger.info(
            "salud.replicada_descartada_por_vieja",
            cuenta_id=str(cuenta_id),
            tenia=fila.medida_at.isoformat(),
            llego=medida_at.isoformat(),
        )
        return fila

    if fila is None:
        fila = SaludCuentaReplicada(tenant_id=tenant_id, cuenta_id=cuenta_id)
        db.add(fila)

    fila.puntuacion = datos["puntuacion"]
    fila.nivel = str(datos["nivel"])
    fila.fiable = bool(datos.get("fiable", True))
    fila.motivo = str(datos.get("motivo") or "")
    fila.medida_at = medida_at
    db.flush()
    return fila


def de_la_cuenta(
    db: Session, tenant_id: UUID, *, cuenta_id: UUID, ahora: datetime | None = None
) -> dict[str, Any]:
    """La salud que se enseña en la ficha, con todo lo que la matiza.

    Las tres respuestas son distintas y ninguna se redondea a otra: **hay medida
    fiable**, **hay medida pero no vale para actuar** y **no hay medida**. La
    tercera no es «va bien»: es que nadie lo ha calculado, normalmente porque
    faltan las señales.
    """
    momento = ahora or _ahora()
    fila = db.execute(
        select(SaludCuentaReplicada).where(
            SaludCuentaReplicada.tenant_id == tenant_id,
            SaludCuentaReplicada.cuenta_id == cuenta_id,
        )
    ).scalar_one_or_none()

    if fila is None:
        return {
            "hay": False,
            "porque": (
                "No se ha medido la salud de esta cuenta. Eso no es que vaya bien: "
                "normalmente es que faltan las señales con las que se calcula."
            ),
            "que_hacer": "Conectar las señales de uso, soporte y facturación.",
        }

    dias = (momento - fila.medida_at).days
    vigente = dias <= _dias_vigencia(db)
    return {
        "hay": True,
        "puntuacion": float(fila.puntuacion),
        "nivel": fila.nivel,
        "fiable": fila.fiable,
        "vigente": vigente,
        "medida_hace_dias": dias,
        "motivo": fila.motivo,
        "sirve_para_actuar": bool(fila.fiable and vigente),
        "aviso": (
            ""
            if fila.fiable and vigente
            else (
                f"La medida es de hace {dias} días. Un número en rojo de hace tres meses "
                "no es una alerta: es un recuerdo, y llamar por él molesta a un cliente "
                "cuyo problema ya se resolvió."
                if not vigente
                else "Esta salud se ha calculado con parte de las señales. Se enseña, "
                "pero no se presenta como un dato: pintarla igual que una completa es lo "
                "que hace que la lista de clientes en riesgo deje de mirarse."
            )
        ),
        "de_donde_sale": (
            "Es una copia de lo que calcula el servicio de inteligencia. Para el detalle "
            "señal a señal, ahí está — y ninguna acción automática se dispara desde esta "
            "copia: llegaría con retraso y mandaría correos de retención a quien renovó "
            "ayer."
        ),
    }


def en_riesgo(
    db: Session, tenant_id: UUID, *, ahora: datetime | None = None, limite: int = 50
) -> dict[str, Any]:
    """Las cuentas que hay que mirar, **sin las que no se pueden mirar**.

    Se dejan fuera las medidas poco fiables y las caducadas, y se cuentan aparte.
    Una lista de «clientes en riesgo» donde la mitad son falsos positivos por
    falta de datos se abre dos veces y no se abre más — y entonces se pierden
    también los que sí lo estaban.
    """
    momento = ahora or _ahora()
    corte = momento - timedelta(days=_dias_vigencia(db))
    filas = list(
        db.execute(
            select(SaludCuentaReplicada)
            .where(
                SaludCuentaReplicada.tenant_id == tenant_id,
                SaludCuentaReplicada.nivel.in_(["riesgo", "critica"]),
            )
            .order_by(SaludCuentaReplicada.puntuacion)
            .limit(limite * 3)
        )
        .scalars()
        .all()
    )

    accionables = [f for f in filas if f.fiable and f.medida_at >= corte]
    no_fiables = [f for f in filas if not f.fiable]
    caducadas = [f for f in filas if f.fiable and f.medida_at < corte]

    return {
        "cuentas": [
            {
                "cuenta_id": str(f.cuenta_id),
                "puntuacion": float(f.puntuacion),
                "nivel": f.nivel,
                "motivo": f.motivo,
                "medida_hace_dias": (momento - f.medida_at).days,
            }
            for f in accionables[:limite]
        ],
        "descartadas_por_poco_fiables": len(no_fiables),
        "descartadas_por_viejas": len(caducadas),
        "medible": bool(filas),
        "que_significa": (
            "No hay ninguna cuenta medida en riesgo. Eso puede ser bueno o puede ser que "
            "no se esté midiendo casi nada: mirar la cobertura antes de celebrarlo."
            if not filas
            else f"{len(accionables)} cuentas en riesgo con medida fiable y reciente. "
            f"Se han dejado fuera {len(no_fiables)} por poco fiables y {len(caducadas)} "
            "por viejas: una lista donde la mitad son falsos positivos se abre dos veces "
            "y no se abre más."
        ),
    }
