"""Catálogos de configuración del tenant: plantillas, calendarios y monedas.

Van en `tenancy` y no en cada servicio porque son **transversales**: la misma
plantilla de correo la usan ventas y soporte, el mismo calendario laboral decide
los relojes de SLA y las fechas de vencimiento de una tarea, y la misma tabla de
cambio convierte importes de oportunidades y de facturas. Repartirlos
garantizaría tres calendarios ligeramente distintos y una conversación sobre
cuál es el bueno.

Cubre CRM-07.01.01.04 (plantillas), CRM-07.01.01.05 (calendarios laborales,
festivos y husos) y CRM-07.01.01.06 (monedas y tipos de cambio con histórico).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    Date,
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


# ── Plantillas (CRM-07.01.01.04) ──────────────────────────────────────────


class Plantilla(Base, TimestampMixin):
    """Plantilla de correo, documento o notificación.

    Versionada y con **idioma**: un tenant que opera en tres países necesita la
    misma plantilla en tres idiomas, y tenerlas como tres plantillas distintas
    hace que se desincronicen en cuanto alguien cambia una.
    """

    __tablename__ = "plantillas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    clave: Mapped[str] = mapped_column(String(120), nullable=False)
    idioma: Mapped[str] = mapped_column(String(10), nullable=False, default="es")
    # correo | documento | notificacion | sms
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="correo")
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)

    asunto: Mapped[str | None] = mapped_column(String(300), nullable=True)
    cuerpo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Variables que la plantilla espera, declaradas. Sirven para dos cosas:
    # enseñar al editor qué puede usar, y avisar al guardar si la plantilla usa
    # una que no existe — que es como se manda un correo con «Hola {{nombre}}».
    variables: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Bloqueada: la marca el tenant para que nadie la edite sin pasar por
    # aprobación (cumplimiento por marca y país).
    bloqueada: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", "idioma", name="uq_plantilla_clave_idioma"),
        Index("ix_plantillas_tenant", "tenant_id", "tipo", "activa"),
    )


def render(plantilla: Plantilla, datos: dict[str, Any], *, db: Any = None) -> tuple[str, str]:
    """Sustituye `{{variable}}` en asunto y cuerpo, con los formatos del tenant.

    Las fechas y los importes se localizan ANTES de sustituir (CRM-00.01.04.07).
    Sin eso, un correo generado desde una plantilla enseña
    `2026-09-19 07:00:00+00:00` en mitad de una frase — que es la forma más
    rápida de que un cliente deje de confiar en los avisos automáticos. El
    idioma de la plantilla manda sobre el del contexto cuando lo declara: quien
    eligió la plantilla en portugués quiere las fechas en portugués.

    Sustitución de texto y **nada más**: sin condicionales, bucles ni expresiones.
    Una plantilla es dato del tenant, y un motor con lógica sería ejecutar código
    del cliente dentro del servidor de correo. Para lo que necesita lógica está
    la automatización, que sí está acotada y auditada.

    Lo que falta se deja **visible** (`{{variable}}`) en vez de vaciarse: un
    hueco vacío en un correo pasa desapercibido y se manda; un `{{nombre}}` en
    mitad del texto se ve y se corrige.
    """
    import re

    from crmcore import i18n

    loc = i18n.resolver(db)
    if plantilla.idioma and plantilla.idioma != loc.idioma:
        loc = i18n.Localizacion(
            idioma=plantilla.idioma,
            zona=str(loc.zona),
            formato_fecha=_clave_formato(loc),
            moneda=loc.moneda,
            primer_dia=loc.primer_dia,
        )
    datos = i18n.formatear_valores(datos, loc)

    def _sustituir(texto: str) -> str:
        def _uno(m: "re.Match[str]") -> str:
            clave = m.group(1).strip()
            valor = datos
            for parte in clave.split("."):
                if isinstance(valor, dict):
                    valor = valor.get(parte)
                else:
                    valor = getattr(valor, parte, None)
                if valor is None:
                    return m.group(0)
            return str(valor)

        return re.sub(r"\{\{\s*([\w.]+)\s*\}\}", _uno, texto)

    return _sustituir(plantilla.asunto or ""), _sustituir(plantilla.cuerpo or "")


def _clave_formato(loc: Any) -> str:
    """La clave de ajuste que corresponde al patrón ya resuelto.

    Se necesita para reconstruir una localización con otro idioma sin perder el
    formato de fecha que eligió el tenant: cambiar de idioma no debe cambiar
    cómo se escribe una fecha, que es una decisión aparte.
    """
    from crmcore.i18n import FORMATO_FECHA_POR_DEFECTO, FORMATOS_FECHA

    for clave, patron in FORMATOS_FECHA.items():
        if patron == loc.formato_fecha:
            return clave
    return FORMATO_FECHA_POR_DEFECTO


def variables_sin_resolver(texto: str, datos: dict[str, Any]) -> list[str]:
    """Variables que quedarían sin sustituir. Para avisar ANTES de enviar."""
    import re

    faltan: list[str] = []
    for coincidencia in re.finditer(r"\{\{\s*([\w.]+)\s*\}\}", texto or ""):
        clave = coincidencia.group(1).strip()
        valor: Any = datos
        for parte in clave.split("."):
            valor = valor.get(parte) if isinstance(valor, dict) else getattr(valor, parte, None)
            if valor is None:
                faltan.append(clave)
                break
    return sorted(set(faltan))


# ── Calendarios laborales (CRM-07.01.01.05) ───────────────────────────────


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


# ── Monedas y tipos de cambio (CRM-07.01.01.06) ───────────────────────────


class TipoCambio(Base):
    """Tipo de cambio con fecha (CRM-03.02.01.07: *dated exchange rates*).

    Con **histórico**, no solo el último: una oportunidad cerrada en marzo tiene
    que seguir valiendo lo que valía en marzo. Convertirla siempre al cambio de
    hoy hace que el histórico de ventas se mueva solo, y que dos informes del
    mismo trimestre den números distintos según cuándo se sacaron.
    """

    __tablename__ = "tipos_cambio"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    desde_moneda: Mapped[str] = mapped_column(String(3), nullable=False)
    hasta_moneda: Mapped[str] = mapped_column(String(3), nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    # Alta precisión: un cambio redondeado a cuatro decimales desvía miles de
    # euros en una conversión de varios millones.
    tasa: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    origen: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "desde_moneda", "hasta_moneda", "fecha", name="uq_tipo_cambio"
        ),
        Index("ix_tipos_cambio_busqueda", "tenant_id", "desde_moneda", "hasta_moneda", "fecha"),
    )


def convertir(
    db: Session,
    *,
    tenant_id: UUID,
    importe: Decimal,
    desde: str,
    hasta: str,
    en_fecha: date | None = None,
) -> Decimal:
    """Convierte un importe con el cambio vigente en una fecha.

    Usa el tipo **más reciente que no sea posterior** a la fecha pedida, no el
    más cercano: un cambio publicado el día después no existía cuando se cerró
    la operación, y usarlo sería reescribir el pasado con información futura.
    """
    from decimal import ROUND_HALF_UP

    desde, hasta = desde.upper(), hasta.upper()
    if desde == hasta:
        return importe

    # Volcado explícito antes de leer. Lo aprendió antes
    # `contecflow-PSA/app/services/exchange_rate_service.py`: con autoflush
    # desactivado —que es como corren varias pruebas y algún proceso por lotes—
    # un tipo de cambio cargado en esta misma transacción todavía no está en la
    # base, así que la conversión que viene justo detrás no lo encuentra y falla
    # con «no hay tipo de cambio» teniéndolo delante.
    db.flush()

    en_fecha = en_fecha or date.today()
    fila = db.execute(
        select(TipoCambio)
        .where(
            TipoCambio.tenant_id == tenant_id,
            TipoCambio.desde_moneda == desde,
            TipoCambio.hasta_moneda == hasta,
            TipoCambio.fecha <= en_fecha,
        )
        .order_by(TipoCambio.fecha.desc())
        .limit(1)
    ).scalar_one_or_none()

    if fila is None:
        # Se busca la inversa antes de rendirse: quien carga EUR→USD rara vez
        # carga también USD→EUR, y calcularla es exacto.
        inversa = db.execute(
            select(TipoCambio)
            .where(
                TipoCambio.tenant_id == tenant_id,
                TipoCambio.desde_moneda == hasta,
                TipoCambio.hasta_moneda == desde,
                TipoCambio.fecha <= en_fecha,
            )
            .order_by(TipoCambio.fecha.desc())
            .limit(1)
        ).scalar_one_or_none()
        if inversa is None or inversa.tasa == 0:
            raise NoEncontrado(
                f"No hay tipo de cambio de {desde} a {hasta} para el {en_fecha.isoformat()}",
                error_code="tenancy.sin_tipo_cambio",
                detalle={"desde": desde, "hasta": hasta, "fecha": en_fecha.isoformat()},
            )
        tasa = Decimal(1) / inversa.tasa
    else:
        tasa = fila.tasa

    return (importe * tasa).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def fijar_tipo_cambio(
    db: Session,
    *,
    tenant_id: UUID,
    desde: str,
    hasta: str,
    tasa: Decimal,
    en_fecha: date | None = None,
    origen: str = "manual",
) -> TipoCambio:
    """Registra un tipo de cambio para una fecha. Idempotente por (par, fecha)."""
    if tasa <= 0:
        raise ErrorValidacion(
            "El tipo de cambio tiene que ser mayor que cero",
            error_code="tenancy.tipo_cambio_invalido",
        )
    en_fecha = en_fecha or date.today()
    existente = db.execute(
        select(TipoCambio).where(
            TipoCambio.tenant_id == tenant_id,
            TipoCambio.desde_moneda == desde.upper(),
            TipoCambio.hasta_moneda == hasta.upper(),
            TipoCambio.fecha == en_fecha,
        )
    ).scalar_one_or_none()
    if existente is not None:
        # Se actualiza en vez de fallar: corregir un cambio mal cargado es una
        # operación normal, y obligar a borrar antes solo añade fricción.
        existente.tasa = tasa
        existente.origen = origen
        return existente

    fila = TipoCambio(
        tenant_id=tenant_id,
        desde_moneda=desde.upper(),
        hasta_moneda=hasta.upper(),
        fecha=en_fecha,
        tasa=tasa,
        origen=origen,
    )
    db.add(fila)
    return fila
