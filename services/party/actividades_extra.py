"""Plantillas de actividad, visitas con check-in y recurrencia
(CRM-01.02.01.07, CRM-01.02.01.08, CRM-01.02.01.09).

Tres cosas pequeñas que cambian el día a día de quien usa el CRM de verdad:

**Una plantilla de actividades es lo que convierte «hay que hacer una implantación»
en catorce tareas con fechas.** Sin ellas, cada persona inventa su lista y la mitad
se olvida de lo mismo.

**Un check-in demuestra que se estuvo, no que se dijo que se iba.** La diferencia
importa cuando el cliente dice que nadie fue, y por eso la distancia al sitio se
calcula y se guarda en vez de creerse.

**Una tarea recurrente que no se reprograma sola se convierte en una lista de
tareas vencidas.** Y una lista de vencidas es una lista que se deja de mirar.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    DateTime,
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
from sqlalchemy.orm import Mapped, mapped_column

logger = get_logger(__name__)

# Cada cuánto se repite. Cerrado: cada uno tiene su forma de calcular la
# siguiente, y uno libre acabaría como «cada 30 días» mal etiquetado.
RECURRENCIAS = ("diaria", "semanal", "mensual", "anual", "dias_laborables")


class PlantillaActividades(Base, TimestampMixin, SoftDeleteMixin):
    """Una secuencia de actividades que se crea de golpe (CRM-01.02.01.07)."""

    __tablename__ = "plantillas_actividades"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # A qué se aplica: implantación, renovación, incorporación.
    proceso: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    # Las actividades, con su desfase en días desde el arranque y a quién van.
    actividades: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_plantilla_actividades"),
        Index("ix_plantillas_actividades_proceso", "tenant_id", "proceso", "activa"),
    )


class Visita(Base, TimestampMixin, SoftDeleteMixin):
    """Una visita comercial con su check-in (CRM-01.02.01.08)."""

    __tablename__ = "visitas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    actividad_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)

    # Dónde debería estar y dónde estaba. Se guardan las dos: la distancia es lo
    # que hace del check-in una prueba en vez de un botón.
    lat_esperada: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    lon_esperada: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    lat: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    lon: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    precision_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distancia_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Se marca cuando la distancia pasa del tope. No bloquea: hay polígonos donde
    # el GPS falla cien metros y direcciones mal geocodificadas, y rechazar el
    # check-in deja sin registrar una visita que sí ocurrió.
    fuera_de_sitio: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    entrada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    salida_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notas: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (Index("ix_visitas_usuario", "tenant_id", "usuario_id", "entrada_at"),)


class Recurrencia(Base, TimestampMixin, SoftDeleteMixin):
    """Una actividad que vuelve (CRM-01.02.01.09)."""

    __tablename__ = "recurrencias_actividad"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # La plantilla del apunte que se repite.
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="tarea")
    asunto: Mapped[str] = mapped_column(String(300), nullable=False)
    cuerpo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    objeto: Mapped[str | None] = mapped_column(String(60), nullable=True)
    objeto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    asignada_a: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)

    patron: Mapped[str] = mapped_column(
        String(20), nullable=False, default="mensual", info={"opciones": RECURRENCIAS}
    )
    cada: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    desde: Mapped[date] = mapped_column(DateTime(timezone=True), nullable=False)
    hasta: Mapped[date | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Cuántas quedan por crear. Nulo = sin límite. Existe porque «cada semana
    # durante un año» es más fácil de entender que una fecha de fin calculada.
    repeticiones: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creadas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # La siguiente NO se crea hasta que se cierra la anterior. Crear las 52 de
    # golpe llena la bandeja de tareas de dentro de un año, y lo que hace la gente
    # es dejar de mirar la bandeja.
    una_a_una: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    proxima_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    ultima_creada_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (Index("ix_recurrencias_pendientes", "tenant_id", "activa", "proxima_at"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _con_tz(v: datetime | None) -> datetime | None:
    if v is None:
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


# ── Plantillas de actividad (CRM-01.02.01.07) ─────────────────────────────


def validar_plantilla(actividades: list[dict[str, Any]]) -> list[str]:
    """Comprueba la secuencia antes de guardarla."""
    if not actividades:
        raise ErrorValidacion(
            "Una plantilla sin actividades no crea nada.",
            error_code="plantilla_actividades.vacia",
        )
    avisos: list[str] = []
    for i, actividad in enumerate(actividades):
        if not str(actividad.get("asunto") or "").strip():
            raise ErrorValidacion(
                f"La actividad {i + 1} no tiene asunto: nadie sabría qué hacer.",
                error_code="plantilla_actividades.sin_asunto",
            )
        dias = int(actividad.get("dias", 0))
        if dias < 0:
            raise ErrorValidacion(
                f"La actividad {i + 1} vence antes de empezar.",
                error_code="plantilla_actividades.dias_negativos",
            )
    sin_dueno = [
        a.get("asunto") for a in actividades if not a.get("asignada_a") and not a.get("rol")
    ]
    if sin_dueno:
        avisos.append(
            f"{len(sin_dueno)} actividades no dicen de quién son: se asignarán a "
            "quien lance la plantilla, y eso convierte una implantación en la "
            "lista de tareas de una sola persona."
        )
    if len(actividades) > 25:
        avisos.append(
            f"{len(actividades)} actividades de golpe. Una lista tan larga se "
            "cierra en bloque sin hacerla, que es peor que no tenerla."
        )
    return avisos


def aplicar_plantilla(
    uow: UnidadDeTrabajo,
    clave: str,
    *,
    objeto: str,
    objeto_id: UUID,
    cuenta_id: UUID | None = None,
    desde: date | None = None,
    por: UUID | None = None,
    asignaciones: dict[str, UUID] | None = None,
) -> dict[str, Any]:
    """Crea de golpe las actividades de una plantilla.

    Los desfases se cuentan **desde la fecha de arranque**, no desde hoy: una
    implantación que empieza el mes que viene tiene sus catorce tareas colgando de
    esa fecha, y calcularlas desde hoy las pone todas vencidas antes de empezar.

    Las actividades que declaran un **rol** se asignan con el mapa que se pasa. Las
    que no dicen nada van a quien lanza la plantilla, y se cuenta cuántas son: eso
    convierte una implantación en la lista de tareas de una sola persona, y quien
    la lanza tiene que verlo.
    """
    from services.party.modelos import Actividad

    tenant_id = uow.tenant_id
    plantilla = uow.db.execute(
        select(PlantillaActividades).where(
            PlantillaActividades.tenant_id == tenant_id,
            PlantillaActividades.clave == clave,
        )
    ).scalar_one_or_none()
    if plantilla is None:
        raise NoEncontrado(
            "La plantilla no existe", error_code="plantilla_actividades.no_encontrada"
        )
    if not plantilla.activa:
        raise Conflicto(
            "Esa plantilla está desactivada", error_code="plantilla_actividades.desactivada"
        )

    arranque = desde or date.today()
    asignaciones = asignaciones or {}
    creadas: list[str] = []
    a_quien_lanza = 0

    for actividad in plantilla.actividades or []:
        rol = str(actividad.get("rol") or "")
        asignada = actividad.get("asignada_a") or asignaciones.get(rol) or por
        if not actividad.get("asignada_a") and rol not in asignaciones:
            a_quien_lanza += 1
        vence = datetime.combine(
            arranque + timedelta(days=int(actividad.get("dias", 0))),
            datetime.min.time(),
            tzinfo=timezone.utc,
        ).replace(hour=9)
        fila = Actividad(
            tenant_id=tenant_id,
            tipo=str(actividad.get("tipo") or "tarea"),
            asunto=str(actividad["asunto"]),
            cuerpo=actividad.get("cuerpo"),
            objeto=objeto,
            objeto_id=objeto_id,
            cuenta_id=cuenta_id,
            asignada_a=UUID(str(asignada)) if asignada else None,
            vence_at=vence,
        )
        uow.db.add(fila)
        creadas.append(str(actividad["asunto"]))
    uow.db.flush()

    return {
        "plantilla": plantilla.clave,
        "creadas": len(creadas),
        "actividades": creadas,
        "desde": str(arranque),
        # Cuántas cayeron en quien la lanzó por no decir de quién eran. Sin este
        # número, una plantilla mal repartida parece bien repartida.
        "sin_dueno_declarado": a_quien_lanza,
    }


# ── Visitas y check-in (CRM-01.02.01.08) ──────────────────────────────────


def distancia_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Distancia entre dos puntos, en metros (haversine).

    Se calcula aquí y no se pide al cliente: un check-in cuya distancia la manda
    el propio móvil es un check-in que se puede falsificar cambiando un número.
    """
    radio = 6_371_000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return int(round(2 * radio * math.asin(math.sqrt(a))))


def check_in(
    uow: UnidadDeTrabajo,
    *,
    usuario_id: UUID,
    lat: float,
    lon: float,
    cuenta_id: UUID | None = None,
    actividad_id: UUID | None = None,
    lat_esperada: float | None = None,
    lon_esperada: float | None = None,
    precision_m: int | None = None,
    tope_m: int = 500,
    notas: str = "",
) -> dict[str, Any]:
    """Registra que alguien llegó a una visita.

    **La distancia se calcula en el servidor.** Un check-in cuya distancia la manda
    el móvil se falsifica cambiando un número.

    Estar lejos **no bloquea el check-in**: se marca. Hay polígonos donde el GPS
    falla cien metros y direcciones mal geocodificadas, y rechazarlo deja sin
    registrar una visita que sí ocurrió — que es peor que registrarla con un aviso.

    Y si la **precisión** que informa el dispositivo es peor que el tope, se dice:
    una distancia de 300 m con una precisión de ±800 m no significa nada.
    """
    distancia = None
    fuera = False
    if lat_esperada is not None and lon_esperada is not None:
        distancia = distancia_m(lat, lon, lat_esperada, lon_esperada)
        fuera = distancia > tope_m

    fila = Visita(
        tenant_id=uow.tenant_id,
        usuario_id=usuario_id,
        cuenta_id=cuenta_id,
        actividad_id=actividad_id,
        lat=lat,
        lon=lon,
        lat_esperada=lat_esperada,
        lon_esperada=lon_esperada,
        precision_m=precision_m,
        distancia_m=distancia,
        fuera_de_sitio=fuera,
        entrada_at=_ahora(),
        notas=notas,
    )
    uow.db.add(fila)
    uow.db.flush()

    aviso = ""
    if precision_m is not None and distancia is not None and precision_m > tope_m:
        aviso = (
            f"El dispositivo informa una precisión de ±{precision_m} m, peor que el "
            f"tope de {tope_m} m: la distancia calculada no dice gran cosa."
        )
    return {
        "visita_id": str(fila.id),
        "distancia_m": distancia,
        "fuera_de_sitio": fuera,
        # Sin punto esperado no se puede decir nada de dónde estaba: se registra
        # igual y se dice, en vez de dar por buena una visita sin comprobar.
        "comprobada": distancia is not None,
        "aviso": aviso,
    }


def check_out(uow: UnidadDeTrabajo, visita_id: UUID, *, notas: str = "") -> dict[str, Any]:
    """Cierra la visita y calcula cuánto duró."""
    fila = uow.db.get(Visita, visita_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("La visita no existe", error_code="visita.no_encontrada")
    if fila.salida_at is not None:
        raise Conflicto("Esa visita ya estaba cerrada", error_code="visita.ya_cerrada")
    fila.salida_at = _ahora()
    if notas:
        fila.notas = (fila.notas + "\n" + notas).strip()
    uow.db.flush()
    minutos = int((_con_tz(fila.salida_at) - _con_tz(fila.entrada_at)).total_seconds() // 60)
    return {
        "visita_id": str(fila.id),
        "minutos": minutos,
        # Una visita de dos minutos no se rechaza, se señala: puede ser un error
        # al pulsar y puede ser que no le recibieran, y son cosas distintas.
        "sospechosamente_corta": minutos < 5,
    }


# ── Recurrencia (CRM-01.02.01.09) ─────────────────────────────────────────


def _siguiente(patron: str, desde: datetime, cada: int) -> datetime:
    """La siguiente fecha según el patrón.

    Los meses se suman como meses, no como treinta días: una revisión mensual el
    día 31 tiene que caer el último día del mes siguiente, no el 3 del otro.
    """
    if patron == "diaria":
        return desde + timedelta(days=cada)
    if patron == "semanal":
        return desde + timedelta(weeks=cada)
    if patron == "dias_laborables":
        siguiente = desde
        for _ in range(cada):
            siguiente += timedelta(days=1)
            while siguiente.weekday() >= 5:
                siguiente += timedelta(days=1)
        return siguiente
    if patron == "anual":
        try:
            return desde.replace(year=desde.year + cada)
        except ValueError:
            # 29 de febrero en un año no bisiesto.
            return desde.replace(year=desde.year + cada, day=28)
    import calendar

    mes = desde.month - 1 + cada
    anio = desde.year + mes // 12
    mes = mes % 12 + 1
    dia = min(desde.day, calendar.monthrange(anio, mes)[1])
    return desde.replace(year=anio, month=mes, day=dia)


def crear_recurrencia(
    uow: UnidadDeTrabajo,
    *,
    asunto: str,
    desde: datetime,
    patron: str = "mensual",
    cada: int = 1,
    tipo: str = "tarea",
    cuerpo: str = "",
    objeto: str | None = None,
    objeto_id: UUID | None = None,
    cuenta_id: UUID | None = None,
    asignada_a: UUID | None = None,
    hasta: datetime | None = None,
    repeticiones: int | None = None,
    una_a_una: bool = True,
) -> Recurrencia:
    """Declara una actividad que se repite.

    Hace falta **un final**: fecha o número de repeticiones. Una recurrencia sin
    fin sigue creando tareas cuando el proyecto lleva dos años cerrado, y quien la
    recibe no sabe ni por qué.
    """
    if patron not in RECURRENCIAS:
        raise ErrorValidacion(
            f"Patrón «{patron}» no válido.",
            error_code="recurrencia.patron_no_valido",
            detalle={"validos": list(RECURRENCIAS)},
        )
    if cada < 1:
        raise ErrorValidacion(
            "La repetición tiene que ser de al menos uno.",
            error_code="recurrencia.cada_invalido",
        )
    if hasta is None and repeticiones is None:
        raise ErrorValidacion(
            "Una recurrencia sin fin sigue creando tareas cuando el proyecto lleva "
            "dos años cerrado. Pon una fecha de fin o un número de repeticiones.",
            error_code="recurrencia.sin_fin",
        )
    fila = Recurrencia(
        tenant_id=uow.tenant_id,
        tipo=tipo,
        asunto=asunto,
        cuerpo=cuerpo,
        objeto=objeto,
        objeto_id=objeto_id,
        cuenta_id=cuenta_id,
        asignada_a=asignada_a,
        patron=patron,
        cada=cada,
        desde=desde,
        hasta=hasta,
        repeticiones=repeticiones,
        una_a_una=una_a_una,
        proxima_at=desde,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def generar_pendientes(uow: UnidadDeTrabajo, tenant_id: UUID) -> dict[str, Any]:
    """Crea las actividades recurrentes que tocan.

    Con `una_a_una`, **la siguiente no se crea hasta que se cierra la anterior**.
    Crear las 52 de golpe llena la bandeja de tareas de dentro de un año, y lo que
    hace la gente entonces es dejar de mirar la bandeja.

    Y una recurrente que venció sin cerrarse **se reprograma, no se acumula**: una
    lista de vencidas es una lista que se deja de mirar.
    """
    from services.party.modelos import Actividad

    ahora = _ahora()
    pendientes = (
        uow.db.execute(
            select(Recurrencia).where(
                Recurrencia.tenant_id == tenant_id,
                Recurrencia.activa.is_(True),
                Recurrencia.proxima_at.isnot(None),
                Recurrencia.proxima_at <= ahora,
            )
        )
        .scalars()
        .all()
    )
    creadas: list[str] = []
    esperando: list[str] = []
    terminadas: list[str] = []

    for recurrencia in pendientes:
        if recurrencia.hasta and _con_tz(recurrencia.hasta) < ahora:
            recurrencia.activa = False
            recurrencia.proxima_at = None
            terminadas.append(recurrencia.asunto)
            continue
        if recurrencia.repeticiones is not None and recurrencia.creadas >= recurrencia.repeticiones:
            recurrencia.activa = False
            recurrencia.proxima_at = None
            terminadas.append(recurrencia.asunto)
            continue

        if recurrencia.una_a_una and recurrencia.ultima_creada_id is not None:
            anterior = uow.db.get(Actividad, recurrencia.ultima_creada_id)
            if anterior is not None and anterior.estado not in ("completada", "cancelada"):
                # Se reprograma en vez de acumular: la anterior sigue abierta y
                # crear otra igual encima solo hace la lista más larga.
                recurrencia.proxima_at = _siguiente(recurrencia.patron, ahora, recurrencia.cada)
                esperando.append(recurrencia.asunto)
                continue

        fila = Actividad(
            tenant_id=tenant_id,
            tipo=recurrencia.tipo,
            asunto=recurrencia.asunto,
            cuerpo=recurrencia.cuerpo or None,
            objeto=recurrencia.objeto,
            objeto_id=recurrencia.objeto_id,
            cuenta_id=recurrencia.cuenta_id,
            asignada_a=recurrencia.asignada_a,
            vence_at=_con_tz(recurrencia.proxima_at),
        )
        uow.db.add(fila)
        uow.db.flush()
        recurrencia.ultima_creada_id = fila.id
        recurrencia.creadas += 1
        recurrencia.proxima_at = _siguiente(
            recurrencia.patron, _con_tz(recurrencia.proxima_at) or ahora, recurrencia.cada
        )
        creadas.append(recurrencia.asunto)

    uow.db.flush()
    return {
        "revisadas": len(pendientes),
        "creadas": creadas,
        # Las que esperan a que se cierre la anterior salen aparte: no son un
        # fallo, y confundirlas con uno lleva a apagar el `una_a_una`.
        "esperando_a_la_anterior": esperando,
        "terminadas": terminadas,
        "medible": bool(pendientes),
    }
