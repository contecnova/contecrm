"""Calendarios laborales y festivos, replicados a todos los servicios
(CRM-07.01.01.05, CRM-04.01.02.04).

Estaban en `tenancy`, que es donde se administran. Se movieron al montar los
relojes de SLA: **`service` no puede leer el esquema de `tenancy`** —lo impide el
gate de arquitectura— y un reloj de SLA que preguntara por HTTP cada vez que
avanza pondría el vencimiento de un caso a depender de que otro servicio esté en
pie, además de multiplicar la latencia por cada paso del cálculo.

Se replica por evento, igual que los ajustes en caliente, las claves de tenant y
los tipos de cambio. Se administran en un sitio y se leen en todos.

Es lo que hace que un SLA de «4 horas» signifique cuatro horas **laborables** y no
que un aviso entrado el viernes a las 18:00 se incumpla el sábado a las 22:00,
cuando no había nadie.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Index,
    String,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.db.base import Base, TimestampMixin
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger

logger = get_logger(__name__)

CALENDARIO_CAMBIADO = "catalogos.calendario_cambiado"


class CalendarioLaboral(Base, TimestampMixin):
    """Horario y festivos de una sede o país.

    Es lo que hace que un SLA de «4 horas» signifique cuatro horas **laborables**
    y no que un aviso entrado el viernes a las 18:00 se incumpla el sábado a las
    22:00, cuando no había nadie.
    """

    __tablename__ = "calendarios_laborales"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    clave: Mapped[str] = mapped_column(String(60), nullable=False)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    zona_horaria: Mapped[str] = mapped_column(String(60), nullable=False, default="Europe/Madrid")
    pais: Mapped[str] = mapped_column(String(2), nullable=False, default="ES")

    # Horario por día de la semana (0 = lunes): [{"desde":"09:00","hasta":"18:00"}].
    # Una lista por día porque la jornada partida existe y es lo normal en varios
    # sectores: con un solo intervalo, la hora de comer cuenta como laborable.
    horario: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    por_defecto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_calendario_clave"),
        Index(
            "ix_calendarios_defecto",
            "tenant_id",
            unique=True,
            postgresql_where=text("por_defecto"),
        ),
    )


class Festivo(Base):
    """Un día no laborable de un calendario."""

    __tablename__ = "festivos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    calendario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    # Si se repite cada año en la misma fecha (Navidad sí, Semana Santa no).
    anual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("calendario_id", "fecha", name="uq_festivo_fecha"),
        Index("ix_festivos_calendario", "tenant_id", "calendario_id", "fecha"),
    )


def es_laborable(db: Session, calendario: CalendarioLaboral, momento: datetime) -> bool:
    """Si ese instante cae en horario laborable del calendario."""
    dia = str(momento.weekday())
    tramos = (calendario.horario or {}).get(dia) or []
    if not tramos:
        return False
    if _es_festivo(db, calendario, momento.date()):
        return False
    hora = momento.time()
    return any(
        _hora(t.get("desde", "00:00")) <= hora < _hora(t.get("hasta", "23:59")) for t in tramos
    )


def _hora(texto: str) -> time:
    try:
        h, m = texto.split(":")[:2]
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        return time(0, 0)


def _es_festivo(db: Session, calendario: CalendarioLaboral, dia: date) -> bool:
    filas = db.execute(
        select(Festivo).where(
            Festivo.calendario_id == calendario.id,
            Festivo.fecha == dia,
        )
    ).scalar_one_or_none()
    if filas is not None:
        return True
    # Los anuales se comparan por día y mes, sin el año.
    anuales = (
        db.execute(
            select(Festivo).where(Festivo.calendario_id == calendario.id, Festivo.anual.is_(True))
        )
        .scalars()
        .all()
    )
    return any(f.fecha.month == dia.month and f.fecha.day == dia.day for f in anuales)


def sumar_horas_laborables(
    db: Session, calendario: CalendarioLaboral, desde: datetime, horas: float
) -> datetime:
    """Suma horas **laborables** a un instante.

    Es la función que calcula cuándo vence un SLA de verdad. Avanza en pasos de
    quince minutos: es suficiente resolución para un plazo de horas y evita el
    bucle minuto a minuto, que con un plazo de 40 horas serían 2.400 vueltas.

    Tiene un tope de 365 días para no colgarse si el calendario está vacío —un
    calendario sin ningún tramo laborable haría que este bucle no terminara
    nunca, y el síntoma sería una petición que no responde.
    """
    restantes = timedelta(hours=horas)
    paso = timedelta(minutes=15)
    actual = desde
    limite = desde + timedelta(days=365)

    while restantes > timedelta(0) and actual < limite:
        if es_laborable(db, calendario, actual):
            restantes -= paso
        actual += paso

    if actual >= limite:
        logger.warning(
            "calendario.sin_horario_laborable",
            calendario=calendario.clave,
            aviso="no se alcanzó el plazo en 365 días; revisa el horario",
        )
    return actual


# ── Réplica a todos los servicios ─────────────────────────────────────────


def declarar_evento() -> None:
    """Declara el evento de cambio de calendario, una sola vez."""
    from crmcore.events.catalogo import TipoEvento, obtener, registrar

    if obtener(CALENDARIO_CAMBIADO) is not None:
        return
    registrar(
        TipoEvento(
            tipo=CALENDARIO_CAMBIADO,
            version=1,
            productor="core",
            descripcion=(
                "Un calendario laboral o sus festivos han cambiado. Lo consumen "
                "TODOS los servicios para replicarlo y poder calcular plazos"
            ),
            # Va el calendario ENTERO con sus festivos, no el delta: un delta
            # obliga a que el consumidor tenga el estado anterior correcto, y con
            # entrega at-least-once sin orden garantizado eso no se puede
            # afirmar. Un evento perdido dejaría a un servicio calculando
            # vencimientos con los festivos del año pasado.
            campos=("clave", "nombre", "zona_horaria", "pais", "horario", "festivos"),
            publico=False,
        )
    )


def propagar(db: Session, calendario: "CalendarioLaboral") -> None:
    """Emite el calendario para que el resto de servicios lo repliquen."""
    from crmcore.db.uow import UnidadDeTrabajo

    festivos = [
        {"fecha": f.fecha.isoformat(), "nombre": f.nombre, "anual": f.anual}
        for f in db.execute(select(Festivo).where(Festivo.calendario_id == calendario.id)).scalars()
    ]
    uow = UnidadDeTrabajo(db=db, tenant_id=calendario.tenant_id)
    uow.emitir(
        CALENDARIO_CAMBIADO,
        subject=("calendario", calendario.id),
        data={
            "calendario_id": str(calendario.id),
            "clave": calendario.clave,
            "nombre": calendario.nombre,
            "zona_horaria": calendario.zona_horaria,
            "pais": calendario.pais,
            "horario": dict(calendario.horario or {}),
            "por_defecto": calendario.por_defecto,
            "festivos": festivos,
        },
    )
    uow.volcar()


async def consumir_calendario(mensaje: Any) -> None:
    """Aplica en ESTE servicio un calendario cambiado en otro.

    Un servicio que no lo replicara calcularía los vencimientos con el horario
    de fábrica mientras el resto usa el del cliente, y el incumplimiento de SLA
    que reportara no coincidiría con el que ve el cliente — la divergencia más
    cara de explicar que puede tener un servicio de soporte.
    """
    if isinstance(mensaje, dict):
        datos = mensaje.get("data") if isinstance(mensaje.get("data"), dict) else mensaje
        tenant = mensaje.get("tenant_id") or (datos or {}).get("tenant_id")
    else:
        datos = getattr(mensaje, "data", None) or {}
        tenant = getattr(mensaje, "tenant_id", None)
    if not tenant or not datos or not datos.get("clave"):
        return

    from crmcore.db.uow import unidad_de_trabajo

    with unidad_de_trabajo(sistema=True) as uow:
        aplicar_local(uow.db, tenant_id=UUID(str(tenant)), datos=dict(datos))


def aplicar_local(db: Session, *, tenant_id: UUID, datos: dict[str, Any]) -> CalendarioLaboral:
    """Escribe el calendario en el esquema local **sin volver a emitirlo**.

    Sin este camino aparte, aplicar la réplica emitiría otro evento y el sistema
    se realimentaría: un calendario cargado una vez daría la vuelta por todos los
    servicios para siempre.
    """
    clave = str(datos.get("clave"))
    fila = db.execute(
        select(CalendarioLaboral).where(
            CalendarioLaboral.tenant_id == tenant_id, CalendarioLaboral.clave == clave
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = CalendarioLaboral(tenant_id=tenant_id, clave=clave)
        db.add(fila)
    fila.nombre = str(datos.get("nombre") or clave)
    fila.zona_horaria = str(datos.get("zona_horaria") or "Europe/Madrid")
    fila.pais = str(datos.get("pais") or "ES")
    fila.horario = dict(datos.get("horario") or {})
    fila.por_defecto = bool(datos.get("por_defecto"))
    db.flush()

    # Los festivos se reemplazan enteros, no se fusionan: llega la lista
    # completa, y fusionar dejaría para siempre un festivo que el cliente quitó.
    for viejo in db.execute(select(Festivo).where(Festivo.calendario_id == fila.id)).scalars():
        db.delete(viejo)
    for entrada in datos.get("festivos") or []:
        if not isinstance(entrada, dict) or not entrada.get("fecha"):
            continue
        db.add(
            Festivo(
                tenant_id=tenant_id,
                calendario_id=fila.id,
                fecha=date.fromisoformat(str(entrada["fecha"])),
                nombre=str(entrada.get("nombre") or ""),
                anual=bool(entrada.get("anual")),
            )
        )
    db.flush()
    return fila


declarar_evento()

from crmcore.contratos import Consumo, declarar_consumo  # noqa: E402

declarar_consumo(
    Consumo(
        consumidor="todos-los-servicios",
        evento=CALENDARIO_CAMBIADO,
        campos=("clave", "horario", "festivos"),
        motivo=(
            "Calcular plazos de SLA en horas laborables sin llamar a otro "
            "servicio; sin `festivos` un plazo vencería en Navidad"
        ),
    )
)
