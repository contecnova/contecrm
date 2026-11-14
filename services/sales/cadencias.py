"""Cadencias, cola de trabajo y metodología de venta
(CRM-03.03.01.01 a CRM-03.03.01.07, CRM-03.01.02.01, CRM-03.01.02.02,
CRM-03.01.02.03).

Una cadencia es una secuencia de toques —correo, llamada, mensaje, tarea— con
esperas entre medias. Lo que decide si funciona no es el diseño de la secuencia:
es **qué pasa cuando el cliente contesta**, que es lo que la mayoría de las
herramientas resuelve mal y por eso la gente acaba mandando un quinto correo a
alguien que ya respondió que sí.

Cinco decisiones:

**Responder saca del recorrido, siempre.** Es la regla que hace que una cadencia
sea aceptable y no acoso. Se aplica a la persona **y a su cuenta** cuando así se
declara: en B2B contesta uno y se siguen persiguiendo sus tres compañeros, y el
que contestó lo ve.

**La cola es una, priorizada, y dice por qué.** Un comercial con tres listas
—tareas, cadencias, leads— trabaja la que tiene delante, no la que importa. Y una
prioridad sin explicación se ignora: si no se dice por qué algo está arriba, se
baja hasta encontrar lo conocido.

**Lo que se mide de una plantilla es la respuesta, no la apertura.** La apertura
la falsean los filtros de correo que cargan las imágenes, y optimizar por
aperturas lleva a asuntos que se abren y no se contestan.

**La metodología puntúa lo que falta, no lo que hay.** Un indicador que sube al
rellenar campos premia rellenar campos. El que sirve dice **qué falta para poder
cerrar**, que es una lista de cosas que hacer.

**Las reuniones se proponen sobre huecos reales.** Una disponibilidad calculada
sin mirar el calendario produce la reunión que hay que mover, y moverla cuesta
más que no haberla propuesto.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.fechas import hoy, zona_del_tenant
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
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

logger = get_logger(__name__)

# Canales de un paso de cadencia. Cerrado: cada uno tiene una forma distinta de
# ejecutarse y de medirse, y uno libre acabaría como una tarea manual sin decirlo.
CANALES = ("correo", "llamada", "mensaje", "social", "tarea")
# Por qué alguien sale de una cadencia. Se distinguen porque llevan a conclusiones
# distintas: «respondió» es un éxito y «rebotó» es un dato malo.
MOTIVOS_SALIDA = (
    "respondio",
    "reunion",
    "convertido",
    "rebote",
    "baja",
    "manual",
    "terminada",
    "otra_cadencia",
)
METODOLOGIAS = ("meddic", "bant", "spin", "challenger", "custom")


class Cadencia(Base, TimestampMixin, SoftDeleteMixin):
    """Una secuencia de toques (CRM-03.03.01.01)."""

    __tablename__ = "cadencias"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Los pasos, en orden: `{"canal": "correo", "espera_dias": 0,
    # "plantilla": "primer-contacto"}`.
    pasos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Salir también saca a los compañeros de la misma cuenta. En B2B contesta uno
    # y se siguen persiguiendo sus tres compañeros, y el que contestó lo ve.
    salida_por_cuenta: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Solo en horario laborable. Un correo automático a las tres de la mañana
    # dice «esto lo manda una máquina» más alto que cualquier firma.
    solo_laborable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "clave", name="uq_cadencia_clave"),)


class Inscripcion(Base, TimestampMixin):
    """Alguien recorriendo una cadencia."""

    __tablename__ = "inscripciones_cadencia"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    cadencia_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("cadencias.id", ondelete="CASCADE"), nullable=False
    )
    # A quién. Identificadores opacos: el contacto vive en `party`.
    contacto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    lead_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    email: Mapped[str] = mapped_column(
        String(320), nullable=False, default="", info={"sensibilidad": "personal"}
    )
    responsable_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, index=True
    )

    paso_actual: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # activa | pausada | terminada | salida
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="activa", index=True)
    proximo_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    motivo_salida: Mapped[str | None] = mapped_column(String(30), nullable=True)
    salida_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # Alguien no puede estar dos veces en la misma cadencia: dos hilos
        # paralelos de la misma secuencia es exactamente lo que se vive como
        # acoso, y ocurre solo con importar la lista dos veces.
        UniqueConstraint("tenant_id", "cadencia_id", "email", name="uq_inscripcion"),
        Index("ix_inscripciones_pendientes", "tenant_id", "estado", "proximo_at"),
    )


class ToqueCadencia(Base):
    """Cada paso ejecutado. Append-only."""

    __tablename__ = "toques_cadencia"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    inscripcion_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("inscripciones_cadencia.id", ondelete="CASCADE"),
        nullable=False,
    )
    paso: Mapped[int] = mapped_column(Integer, nullable=False)
    canal: Mapped[str] = mapped_column(String(20), nullable=False, info={"opciones": CANALES})
    plantilla: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # La actividad que se creó, si el paso era manual. Enlaza las dos mitades: lo
    # que la cadencia pidió y lo que la persona hizo.
    actividad_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    ejecutado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    abierto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    clicado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    respondido: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (Index("ix_toques_inscripcion", "tenant_id", "inscripcion_id", "paso"),)


class PlantillaCorreo(Base, TimestampMixin, SoftDeleteMixin):
    """Una plantilla con su rendimiento (CRM-03.03.01.03, CRM-03.03.01.06)."""

    __tablename__ = "plantillas_correo"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    asunto: Mapped[str] = mapped_column(String(300), nullable=False)
    cuerpo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Contadores acumulados. Se guardan y no se recalculan porque la serie de
    # toques se purga y el rendimiento histórico de una plantilla no debería
    # desaparecer con ella.
    enviados: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    abiertos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    clicados: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    respondidos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reuniones: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "clave", name="uq_plantilla_correo"),)


class DisponibilidadAgenda(Base, TimestampMixin):
    """Cuándo se puede reunir alguien (CRM-03.03.01.07)."""

    __tablename__ = "disponibilidad_agenda"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # Tramos por día de la semana: `{"1": [["09:00","13:00"],["15:00","18:00"]]}`.
    tramos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    duracion_min: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    # Margen antes y después de cada reunión. Sin él se encadenan reuniones sin
    # respirar y la tercera empieza tarde.
    margen_min: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    # Cuánta antelación mínima. Proponer un hueco dentro de diez minutos produce
    # la reunión a la que nadie llega.
    antelacion_horas: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Para el reparto round-robin entre un equipo.
    equipo: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    ultimo_asignado_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (UniqueConstraint("tenant_id", "usuario_id", name="uq_disponibilidad"),)


class Metodologia(Base, TimestampMixin, SoftDeleteMixin):
    """Qué hay que saber para poder cerrar (CRM-03.01.02.01)."""

    __tablename__ = "metodologias"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    familia: Mapped[str] = mapped_column(String(20), nullable=False, default="custom")
    # Los criterios, con su peso: `{"clave": "presupuesto", "etiqueta": "...",
    # "peso": 20, "desde_etapa": 2}`.
    criterios: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # A qué pipeline se aplica. Vacío = a todos.
    pipeline: Mapped[str | None] = mapped_column(String(80), nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "clave", name="uq_metodologia_clave"),)


class EvaluacionMetodologia(Base, TimestampMixin):
    """Lo que se sabe de una oportunidad concreta (CRM-03.01.02.02)."""

    __tablename__ = "evaluaciones_metodologia"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    metodologia_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    oportunidad_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # Qué criterios están cubiertos: `{"presupuesto": {"valor": "...", "por": ...}}`.
    respuestas: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
        info={"anonimizar_en_copias": True},
    )
    puntuacion: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    actualizada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "oportunidad_id", "metodologia_id", name="uq_evaluacion_oportunidad"
        ),
    )


class Playbook(Base, TimestampMixin):
    """Qué hacer en esta etapa y con este tipo de negocio (CRM-03.01.02.03)."""

    __tablename__ = "playbooks"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    # Cuándo aplica: etapa, segmento, tipo. Vacío en un campo = cualquiera.
    etapa: Mapped[str | None] = mapped_column(String(80), nullable=True)
    segmento: Mapped[str | None] = mapped_column(String(80), nullable=True)
    condiciones: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Qué hacer, en orden, con el contenido asociado a cada paso.
    pasos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_playbook_clave"),
        Index("ix_playbooks_etapa", "tenant_id", "etapa", "activo"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _con_tz(v: datetime | None) -> datetime | None:
    if v is None:
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


# ── Cadencias (CRM-03.03.01.01) ───────────────────────────────────────────


def validar_cadencia(pasos: list[dict[str, Any]]) -> list[str]:
    """Comprueba la secuencia. Lanza lo grave, avisa lo demás."""
    if not pasos:
        raise ErrorValidacion(
            "Una cadencia sin pasos no toca a nadie.", error_code="cadencia.sin_pasos"
        )
    avisos: list[str] = []
    for i, paso in enumerate(pasos):
        canal = str(paso.get("canal") or "")
        if canal not in CANALES:
            raise ErrorValidacion(
                f"Canal «{canal}» no válido en el paso {i + 1}.",
                error_code="cadencia.canal_no_valido",
                detalle={"validos": list(CANALES)},
            )
        if canal == "correo" and not paso.get("plantilla"):
            raise ErrorValidacion(
                f"El paso {i + 1} manda un correo y no dice con qué plantilla.",
                error_code="cadencia.correo_sin_plantilla",
            )
        espera = int(paso.get("espera_dias", 0))
        if espera < 0:
            raise ErrorValidacion(
                f"El paso {i + 1} tiene una espera negativa.",
                error_code="cadencia.espera_negativa",
            )
        if i > 0 and espera == 0:
            avisos.append(
                f"El paso {i + 1} va el mismo día que el anterior: dos toques en "
                "un día se viven como insistencia, no como seguimiento."
            )
    if len(pasos) > 12:
        avisos.append(
            f"La cadencia tiene {len(pasos)} pasos. Por encima de ocho o diez, lo "
            "que sube no es la respuesta: son las bajas."
        )
    correos = len([p for p in pasos if p.get("canal") == "correo"])
    if correos == len(pasos) and correos > 2:
        avisos.append(
            "Todos los pasos son correo. Una cadencia de un solo canal compite "
            "con la bandeja de entrada y pierde."
        )
    return avisos


def crear_cadencia(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    nombre: str,
    pasos: list[dict[str, Any]],
    descripcion: str = "",
    salida_por_cuenta: bool = True,
    solo_laborable: bool = True,
) -> tuple[Cadencia, list[str]]:
    avisos = validar_cadencia(pasos)
    fila = Cadencia(
        tenant_id=uow.tenant_id,
        clave=clave,
        nombre=nombre,
        descripcion=descripcion,
        pasos=pasos,
        salida_por_cuenta=salida_por_cuenta,
        solo_laborable=solo_laborable,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila, avisos


def inscribir(
    uow: UnidadDeTrabajo,
    cadencia_id: UUID,
    *,
    email: str,
    contacto_id: UUID | None = None,
    lead_id: UUID | None = None,
    cuenta_id: UUID | None = None,
    responsable_id: UUID | None = None,
) -> Inscripcion:
    """Mete a alguien en una cadencia.

    Si ya está en **otra** cadencia activa se dice y no se inscribe. Dos
    secuencias a la vez sobre la misma persona es la forma más rápida de que pida
    la baja, y ocurre sin querer: dos comerciales importan la misma lista.
    """
    tenant_id = uow.tenant_id
    cadencia = uow.db.get(Cadencia, cadencia_id)
    if cadencia is None or cadencia.tenant_id != tenant_id:
        raise NoEncontrado("La cadencia no existe", error_code="cadencia.no_encontrada")
    if not cadencia.activa:
        raise Conflicto("Esa cadencia está desactivada", error_code="cadencia.desactivada")

    otra = uow.db.execute(
        select(Inscripcion).where(
            Inscripcion.tenant_id == tenant_id,
            Inscripcion.email == email,
            Inscripcion.estado == "activa",
        )
    ).scalar_one_or_none()
    if otra is not None:
        raise Conflicto(
            "Esa persona ya está en una cadencia activa. Dos secuencias a la vez "
            "sobre la misma persona es la forma más rápida de que pida la baja.",
            error_code="cadencia.ya_inscrito",
            detalle={"cadencia_id": str(otra.cadencia_id)},
        )

    fila = Inscripcion(
        tenant_id=tenant_id,
        cadencia_id=cadencia_id,
        email=email,
        contacto_id=contacto_id,
        lead_id=lead_id,
        cuenta_id=cuenta_id,
        responsable_id=responsable_id,
        # El primer paso también respeta la ventana. Se programaba para «ya»
        # y `avanzar` lo mandaba en la siguiente pasada fuera de horario: una
        # inscripción de las once de la noche salía a las once y cinco, y la
        # del sábado, el sábado. Los siguientes pasos ya pasaban por aquí.
        proximo_at=_siguiente_laborable(_ahora(), cadencia.solo_laborable, ventana_envio(uow.db)),
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def salir(
    uow: UnidadDeTrabajo, inscripcion_id: UUID, *, motivo: str, propagar: bool = True
) -> dict[str, Any]:
    """Saca a alguien de la cadencia.

    **Responder saca del recorrido, siempre.** Es la regla que hace que una
    cadencia sea aceptable y no acoso.

    Y cuando la cadencia lo declara, saca **también a los compañeros de la misma
    cuenta**: en B2B contesta uno y se siguen persiguiendo sus tres compañeros, y
    el que contestó lo ve.
    """
    if motivo not in MOTIVOS_SALIDA:
        raise ErrorValidacion(
            f"Motivo «{motivo}» no válido.",
            error_code="cadencia.motivo_no_valido",
            detalle={"validos": list(MOTIVOS_SALIDA)},
        )
    tenant_id = uow.tenant_id
    fila = uow.db.get(Inscripcion, inscripcion_id)
    if fila is None or fila.tenant_id != tenant_id:
        raise NoEncontrado(
            "La inscripción no existe", error_code="cadencia.inscripcion_no_encontrada"
        )
    if fila.estado in ("salida", "terminada"):
        raise Conflicto(
            f"Esa inscripción ya está «{fila.estado}».", error_code="cadencia.ya_terminada"
        )

    fila.estado = "salida"
    fila.motivo_salida = motivo
    fila.salida_at = _ahora()
    fila.proximo_at = None
    companeros: list[str] = []

    cadencia = uow.db.get(Cadencia, fila.cadencia_id)
    if (
        propagar
        and cadencia is not None
        and cadencia.salida_por_cuenta
        and fila.cuenta_id is not None
        and motivo in ("respondio", "reunion", "convertido", "baja")
    ):
        otros = (
            uow.db.execute(
                select(Inscripcion).where(
                    Inscripcion.tenant_id == tenant_id,
                    Inscripcion.cuenta_id == fila.cuenta_id,
                    Inscripcion.estado == "activa",
                    Inscripcion.id != fila.id,
                )
            )
            .scalars()
            .all()
        )
        for otro in otros:
            otro.estado = "salida"
            otro.motivo_salida = "otra_cadencia"
            otro.salida_at = _ahora()
            otro.proximo_at = None
            companeros.append(otro.email)

    uow.db.flush()
    uow.emitir(
        "cadence.exited",
        subject=("inscripcion", fila.id),
        data={
            "inscripcion_id": str(fila.id),
            "cadencia_id": str(fila.cadencia_id),
            "email": fila.email,
            "motivo": motivo,
            "companeros_sacados": len(companeros),
        },
    )
    return {"inscripcion_id": str(fila.id), "motivo": motivo, "companeros_sacados": companeros}


def registrar_respuesta(
    uow: UnidadDeTrabajo, *, email: str, tipo: str = "respondio"
) -> dict[str, Any]:
    """Alguien ha contestado: se le saca de lo que esté recorriendo
    (CRM-03.03.01.04).

    Entra por aquí lo que detecte la respuesta —el buzón, el webhook del proveedor
    de correo, una llamada registrada— y es **una sola puerta** a propósito: con
    una por canal, el que se olvide de llamar deja a alguien recibiendo el
    siguiente correo después de haber contestado.
    """
    tenant_id = uow.tenant_id
    inscripciones = (
        uow.db.execute(
            select(Inscripcion).where(
                Inscripcion.tenant_id == tenant_id,
                Inscripcion.email == email,
                Inscripcion.estado == "activa",
            )
        )
        .scalars()
        .all()
    )
    if not inscripciones:
        return {"sacadas": 0, "companeros": 0}

    # El último toque de correo queda marcado como respondido: es lo que permite
    # medir la plantilla por lo que importa.
    sacadas = 0
    companeros = 0
    for inscripcion in inscripciones:
        ultimo = uow.db.execute(
            select(ToqueCadencia)
            .where(ToqueCadencia.inscripcion_id == inscripcion.id)
            .order_by(ToqueCadencia.paso.desc())
            .limit(1)
        ).scalar_one_or_none()
        if ultimo is not None and not ultimo.respondido:
            ultimo.respondido = True
            if ultimo.plantilla:
                plantilla = uow.db.execute(
                    select(PlantillaCorreo).where(
                        PlantillaCorreo.tenant_id == tenant_id,
                        PlantillaCorreo.clave == ultimo.plantilla,
                    )
                ).scalar_one_or_none()
                if plantilla is not None:
                    plantilla.respondidos += 1
        salida = salir(uow, inscripcion.id, motivo=tipo)
        sacadas += 1
        companeros += len(salida["companeros_sacados"])
    return {"sacadas": sacadas, "companeros": companeros}


@dataclass(frozen=True)
class VentanaEnvio:
    """Las horas en las que una cadencia toca a alguien, **en su reloj**.

    Eran tres números escritos en `_siguiente_laborable` (8, 9 y 19) y se
    comparaban con la hora UTC del instante: en Madrid la ventana iba de las 9 a
    las 20 en invierno y de las 10 a las 21 en verano, y en Nueva York un correo
    «de las nueve» salía a las cuatro o a las cinco de la mañana. Ahora la hora
    se mira en la zona del tenant y cada tramo es un ajuste.

    La del **destinatario** no se usa porque ventas no la tiene: la inscripción
    guarda un correo y, como mucho, el país del lead (que no da una zona: un
    país puede tener varias). La que sí existe —la del perfil de marketing— vive
    en otro servicio, y una cadencia no puede preguntarle en mitad del avance.
    """

    zona: tzinfo
    #: Antes de esta hora no se toca a nadie: se espera a `reprograma`.
    desde: int
    #: A partir de esta hora tampoco: pasa al día siguiente, a `reprograma`.
    hasta: int
    #: La hora a la que se recoloca lo que cae fuera.
    reprograma: int


def ventana_envio(db: Session | None = None) -> VentanaEnvio:
    """La ventana del tenant: su zona horaria y los tres tramos de sus ajustes."""
    from crmcore.fechas import zona_del_tenant
    from crmcore.runtime import settings as rt

    desde = int(rt.efectivo("cadencia_hora_desde", db))
    hasta = int(rt.efectivo("cadencia_hora_hasta", db))
    reprograma = int(rt.efectivo("cadencia_hora_reprograma", db))
    if not desde < hasta:
        # Una ventana vacía o al revés no deja enviar nunca, y todo se iría
        # empujando un día detrás de otro sin que nadie supiera por qué. Se
        # avisa y se usa la de fábrica.
        logger.warning("cadencias.ventana_invalida", desde=desde, hasta=hasta)
        from crmcore.config import Settings

        campos = Settings.model_fields
        desde = int(campos["cadencia_hora_desde"].default)
        hasta = int(campos["cadencia_hora_hasta"].default)
    if not desde <= reprograma < hasta:
        # Recolocar fuera de la ventana sería mover el toque a otra hora en la
        # que tampoco se puede: se recoloca al abrir.
        reprograma = desde
    return VentanaEnvio(zona=zona_del_tenant(db), desde=desde, hasta=hasta, reprograma=reprograma)


def _siguiente_laborable(
    momento: datetime, solo_laborable: bool, ventana: VentanaEnvio | None = None
) -> datetime:
    """Empuja el toque al siguiente día laborable si hace falta.

    Un correo automático a las tres de la mañana dice «esto lo manda una máquina»
    más alto que cualquier firma, y el sábado dice además «y no le importas».

    Las horas y el día de la semana se miran **en la zona de la ventana**, no en
    UTC; el resultado vuelve en UTC.
    """
    if not solo_laborable:
        return momento
    v = ventana or ventana_envio()
    local = momento.astimezone(v.zona)

    def a_la_hora(dia: datetime) -> datetime:
        # Con `combine` y la zona, y no `replace(hour=…)` sobre el instante: así
        # las 9 son las 9 del reloj de ese día, con el desfase que tenga ese
        # día —antes o después del cambio de hora—.
        return datetime.combine(dia.date(), time(v.reprograma), tzinfo=v.zona)

    while local.weekday() >= 5:
        local = a_la_hora(local + timedelta(days=1))
    if local.hour < v.desde:
        local = a_la_hora(local)
    elif local.hour >= v.hasta:
        local = a_la_hora(local + timedelta(days=1))
        while local.weekday() >= 5:
            local = a_la_hora(local + timedelta(days=1))
    return local.astimezone(timezone.utc)


def avanzar(uow: UnidadDeTrabajo, tenant_id: UUID, *, limite: int = 200) -> dict[str, Any]:
    """Ejecuta los pasos que tocan.

    Los pasos de **correo** se ejecutan solos; los de **llamada, mensaje o
    tarea** crean una actividad para que lo haga una persona. Mandar un correo no
    es lo mismo que llamar, y una herramienta que finge que sí acaba con cadencias
    de cinco correos que nadie llamó.
    """
    ahora = _ahora()
    pendientes = (
        uow.db.execute(
            select(Inscripcion)
            .where(
                Inscripcion.tenant_id == tenant_id,
                Inscripcion.estado == "activa",
                Inscripcion.proximo_at.isnot(None),
                Inscripcion.proximo_at <= ahora,
            )
            .limit(limite)
        )
        .scalars()
        .all()
    )
    ejecutados: list[dict[str, Any]] = []
    terminadas: list[str] = []
    # Una vez por pasada y no por inscripción: son tres ajustes y una zona, y
    # leerlos en el bucle sería una consulta por persona.
    ventana = ventana_envio(uow.db)

    for inscripcion in pendientes:
        cadencia = uow.db.get(Cadencia, inscripcion.cadencia_id)
        if cadencia is None:
            continue
        pasos = list(cadencia.pasos or [])
        if inscripcion.paso_actual >= len(pasos):
            inscripcion.estado = "terminada"
            inscripcion.motivo_salida = "terminada"
            inscripcion.proximo_at = None
            terminadas.append(inscripcion.email)
            continue

        paso = pasos[inscripcion.paso_actual]
        canal = str(paso.get("canal"))
        uow.db.add(
            ToqueCadencia(
                tenant_id=tenant_id,
                inscripcion_id=inscripcion.id,
                paso=inscripcion.paso_actual,
                canal=canal,
                plantilla=paso.get("plantilla"),
            )
        )
        if canal == "correo" and paso.get("plantilla"):
            plantilla = uow.db.execute(
                select(PlantillaCorreo).where(
                    PlantillaCorreo.tenant_id == tenant_id,
                    PlantillaCorreo.clave == str(paso["plantilla"]),
                )
            ).scalar_one_or_none()
            if plantilla is not None:
                plantilla.enviados += 1

        uow.emitir(
            "cadence.step.due",
            subject=("inscripcion", inscripcion.id),
            data={
                "inscripcion_id": str(inscripcion.id),
                "cadencia": cadencia.clave,
                "paso": inscripcion.paso_actual,
                "canal": canal,
                "plantilla": str(paso.get("plantilla") or ""),
                "email": inscripcion.email,
                "responsable_id": str(inscripcion.responsable_id)
                if inscripcion.responsable_id
                else "",
                # Lo que el paso pide hacer a una persona se marca: quien
                # consuma el evento tiene que saber si crea una tarea o manda un
                # correo, y adivinarlo por el canal es cómo se manda un correo
                # donde tocaba llamar.
                "manual": canal != "correo",
            },
        )

        inscripcion.paso_actual += 1
        if inscripcion.paso_actual >= len(pasos):
            inscripcion.estado = "terminada"
            inscripcion.motivo_salida = "terminada"
            inscripcion.proximo_at = None
            terminadas.append(inscripcion.email)
        else:
            siguiente = pasos[inscripcion.paso_actual]
            # Los días se suman en el reloj del tenant: «dentro de tres días»
            # que cruza el cambio de hora sigue siendo a la misma hora.
            inscripcion.proximo_at = _siguiente_laborable(
                ahora.astimezone(ventana.zona)
                + timedelta(days=int(siguiente.get("espera_dias", 1))),
                cadencia.solo_laborable,
                ventana,
            )
        ejecutados.append(
            {"email": inscripcion.email, "canal": canal, "paso": inscripcion.paso_actual - 1}
        )

    uow.db.flush()
    return {
        "pendientes": len(pendientes),
        "ejecutados": ejecutados,
        "terminadas": terminadas,
        "medible": bool(pendientes),
    }


# ── La cola de trabajo (CRM-03.03.01.02) ──────────────────────────────────


def cola_de_trabajo(
    db: Session, tenant_id: UUID, usuario_id: UUID, *, limite: int = 50
) -> dict[str, Any]:
    """Lo que le toca hacer hoy a un comercial, en una sola lista.

    **Una cola, no tres.** Un comercial con tres listas —tareas, cadencias,
    leads— trabaja la que tiene delante, no la que importa.

    Y cada entrada dice **por qué está ahí**. Una prioridad sin explicación se
    ignora: si no se dice por qué algo está arriba, la gente baja hasta encontrar
    lo que reconoce.
    """
    ahora = _ahora()
    filas: list[dict[str, Any]] = []

    pasos = (
        db.execute(
            select(Inscripcion)
            .where(
                Inscripcion.tenant_id == tenant_id,
                Inscripcion.responsable_id == usuario_id,
                Inscripcion.estado == "activa",
                Inscripcion.proximo_at.isnot(None),
                Inscripcion.proximo_at <= ahora,
            )
            .limit(limite)
        )
        .scalars()
        .all()
    )
    for inscripcion in pasos:
        cadencia = db.get(Cadencia, inscripcion.cadencia_id)
        lista = list(cadencia.pasos or []) if cadencia else []
        paso = lista[inscripcion.paso_actual] if inscripcion.paso_actual < len(lista) else {}
        atraso = (ahora - _con_tz(inscripcion.proximo_at)).days if inscripcion.proximo_at else 0
        filas.append(
            {
                "tipo": "cadencia",
                "id": str(inscripcion.id),
                "titulo": f"{paso.get('canal', 'toque')} · {inscripcion.email}",
                "canal": paso.get("canal"),
                "cuenta_id": str(inscripcion.cuenta_id) if inscripcion.cuenta_id else None,
                # El porqué, con nombre. No «prioridad 3».
                "por_que": (
                    f"Toca el paso {inscripcion.paso_actual + 1} de «{cadencia.nombre}»"
                    if cadencia
                    else "Toca un paso de cadencia"
                )
                + (f", con {atraso} días de retraso" if atraso > 0 else ""),
                "urgencia": 100 - min(atraso, 90),
                "atraso_dias": atraso,
            }
        )

    filas.extend(_leads_sin_responder(db, tenant_id, usuario_id, ahora, limite))
    filas.extend(_oportunidades_paradas(db, tenant_id, usuario_id))

    filas.sort(key=lambda f: f["urgencia"])
    return {
        "entradas": filas[:limite],
        "cuantas": len(filas),
        # Sin nada que hacer no se dice «al día»: se dice que no hay nada en la
        # cola, que es distinto de haberla vaciado.
        "vacia": not filas,
    }


def _leads_sin_responder(
    db: Session, tenant_id: UUID, usuario_id: UUID, ahora: datetime, limite: int
) -> list[dict[str, Any]]:
    """Los leads suyos que esperan la primera respuesta.

    La cola decía «una cola, no tres» y sólo miraba las cadencias: un comercial
    con leads nuevos sin contestar y oportunidades paradas veía «aquí no hay
    nada» (visto el 10-11-2026). Primero los que ya se pasaron del plazo.
    """
    from services.sales.modelos import Lead

    leads = (
        db.execute(
            select(Lead)
            .where(
                Lead.tenant_id == tenant_id,
                Lead.owner_id == usuario_id,
                Lead.estado == "nuevo",
                Lead.primera_respuesta_at.is_(None),
                Lead.convertido_at.is_(None),
            )
            .order_by(Lead.sla_primera_respuesta_at.asc().nulls_last())
            .limit(limite)
        )
        .scalars()
        .all()
    )
    salida = []
    for lead in leads:
        vence = _con_tz(lead.sla_primera_respuesta_at)
        horas_fuera = int((ahora - vence).total_seconds() // 3600) if vence else 0
        nombre = " ".join(x for x in (lead.nombre, lead.apellidos) if x) or lead.empresa or ""
        salida.append(
            {
                "tipo": "lead",
                "id": str(lead.id),
                "lead_id": str(lead.id),
                "titulo": nombre,
                "por_que": (
                    f"Lead nuevo sin primera respuesta, fuera de plazo desde hace {horas_fuera} h"
                    if horas_fuera > 0
                    else "Lead nuevo sin primera respuesta"
                ),
                # Fuera de plazo va antes que cualquier paso de cadencia.
                "urgencia": 0 if horas_fuera > 0 else 50,
                "atraso_dias": max(horas_fuera // 24, 0),
            }
        )
    return salida


def _oportunidades_paradas(db: Session, tenant_id: UUID, usuario_id: UUID) -> list[dict[str, Any]]:
    """Las oportunidades suyas que pasan del umbral de su etapa (CRM-03.01.01.12).

    El aviso de estancamiento va donde el comercial trabaja. En la pestaña
    «Estancadas» de Previsiones lo ve el jefe; el dueño no se enteraba.
    """
    from services.sales.servicio import oportunidades_estancadas

    salida = []
    for o in oportunidades_estancadas(db, tenant_id):
        if str(o.get("owner_id")) != str(usuario_id):
            continue
        exceso = int(o["dias_en_etapa"]) - int(o["limite"])
        salida.append(
            {
                "tipo": "oportunidad",
                "id": o["id"],
                "oportunidad_id": o["id"],
                "titulo": o["nombre"],
                "por_que": (
                    f"Lleva {o['dias_en_etapa']} días en «{o['etapa']}», "
                    f"y en esa etapa se considera parada a los {o['limite']}"
                ),
                "urgencia": 100 - min(exceso, 90),
                "atraso_dias": exceso,
            }
        )
    return salida


# ── Rendimiento de plantillas (CRM-03.03.01.06) ───────────────────────────


def rendimiento_plantillas(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Qué plantillas funcionan.

    **Lo que se mide es la respuesta, no la apertura.** La apertura la falsean
    los filtros de correo que cargan las imágenes por su cuenta, y optimizar por
    aperturas lleva a asuntos que se abren y no se contestan — que es el peor
    sitio al que llegar, porque parece que va bien.

    Con menos de treinta envíos **no se da una tasa**: con cinco envíos y una
    respuesta, el 20 % que saldría no describe nada y se usa para descartar una
    plantilla que nunca se probó.
    """
    filas = (
        db.execute(
            select(PlantillaCorreo)
            .where(PlantillaCorreo.tenant_id == tenant_id)
            .order_by(PlantillaCorreo.nombre)
        )
        .scalars()
        .all()
    )
    # Era un `MINIMO = 30` escrito aquí dentro. Local o de módulo, un
    # umbral es un umbral: sale del `.env`.
    from crmcore.config import get_settings

    MINIMO = get_settings().cadencia_minimo_dias
    salida = []
    for p in filas:
        suficiente = p.enviados >= MINIMO
        salida.append(
            {
                "clave": p.clave,
                "nombre": p.nombre,
                "enviados": p.enviados,
                "respondidos": p.respondidos,
                "reuniones": p.reuniones,
                "tasa_respuesta": (
                    round(100 * p.respondidos / p.enviados, 1) if suficiente else None
                ),
                "tasa_reunion": (round(100 * p.reuniones / p.enviados, 1) if suficiente else None),
                # La apertura se da como dato crudo y SIN tasa, con su advertencia:
                # darle un porcentaje al lado del de respuesta invita a compararlos.
                "abiertos": p.abiertos,
                "aviso_apertura": (
                    "La apertura la falsean los filtros que cargan las imágenes: "
                    "sirve para detectar un problema de entrega, no para elegir "
                    "plantilla."
                ),
                "concluyente": suficiente,
                "aviso": ""
                if suficiente
                else f"Solo {p.enviados} envíos: hacen falta {MINIMO} para dar una tasa.",
            }
        )
    return {"plantillas": salida, "medible": bool(filas)}


# ── Reuniones (CRM-03.03.01.07) ───────────────────────────────────────────


def huecos(
    db: Session,
    tenant_id: UUID,
    usuario_id: UUID,
    *,
    desde: date | None = None,
    dias: int = 5,
    ocupado: list[tuple[datetime, datetime]] | None = None,
) -> list[dict[str, Any]]:
    """Los huecos reales de alguien.

    `ocupado` lo trae quien llama desde el calendario sincronizado. **No se
    inventa**: una disponibilidad calculada sin mirar el calendario produce la
    reunión que hay que mover, y moverla cuesta más que no haberla propuesto. Sin
    calendario, lo que se devuelve son los tramos declarados y se dice que no se
    ha contrastado.
    """
    fila = db.execute(
        select(DisponibilidadAgenda).where(
            DisponibilidadAgenda.tenant_id == tenant_id,
            DisponibilidadAgenda.usuario_id == usuario_id,
        )
    ).scalar_one_or_none()
    if fila is None or not fila.activa:
        return []

    inicio = desde or hoy(db)
    ocupado = list(ocupado or [])
    minimo = _ahora() + timedelta(hours=fila.antelacion_horas)
    salida: list[dict[str, Any]] = []
    # Los tramos («09:00-14:00») son hora LOCAL de la empresa. Se construían en
    # UTC: en Madrid se proponían huecos de 10:00 a 15:00, y de 11:00 a 16:00 en
    # verano (auditoría 13-11-2026, FUN-B-19). Se devuelven en UTC, como el resto
    # de la API; quien los pinta los pasa a la hora de quien mira.
    zona = zona_del_tenant(db)

    for d in range(dias):
        dia = inicio + timedelta(days=d)
        tramos = (fila.tramos or {}).get(str(dia.weekday())) or []
        for tramo in tramos:
            desde_h = time.fromisoformat(str(tramo[0]))
            hasta_h = time.fromisoformat(str(tramo[1]))
            actual = datetime.combine(dia, desde_h, tzinfo=zona).astimezone(timezone.utc)
            fin = datetime.combine(dia, hasta_h, tzinfo=zona).astimezone(timezone.utc)
            while actual + timedelta(minutes=fila.duracion_min) <= fin:
                termina = actual + timedelta(minutes=fila.duracion_min)
                # La antelación mínima: proponer un hueco dentro de diez minutos
                # produce la reunión a la que nadie llega.
                if actual < minimo:
                    actual = termina + timedelta(minutes=fila.margen_min)
                    continue
                choca = any(
                    actual < ocupado_fin and termina > ocupado_inicio
                    for ocupado_inicio, ocupado_fin in ocupado
                )
                if not choca:
                    salida.append(
                        {
                            "desde": actual.isoformat(),
                            "hasta": termina.isoformat(),
                            # Se dice si se contrastó con el calendario: un hueco
                            # sin contrastar es una propuesta, no una promesa.
                            "contrastado": bool(ocupado),
                        }
                    )
                actual = termina + timedelta(minutes=fila.margen_min)
    return salida


def siguiente_del_equipo(db: Session, tenant_id: UUID, equipo: str) -> UUID | None:
    """A quién le toca la próxima reunión del equipo (round-robin).

    Por **quién lleva más tiempo sin recibir una**, no por orden alfabético ni por
    identificador: los dos dan siempre la misma persona primero, y el reparto deja
    de repartir.
    """
    filas = (
        db.execute(
            select(DisponibilidadAgenda)
            .where(
                DisponibilidadAgenda.tenant_id == tenant_id,
                DisponibilidadAgenda.equipo == equipo,
                DisponibilidadAgenda.activa.is_(True),
            )
            .order_by(DisponibilidadAgenda.ultimo_asignado_at.asc().nulls_first())
        )
        .scalars()
        .all()
    )
    if not filas:
        return None
    elegido = filas[0]
    elegido.ultimo_asignado_at = _ahora()
    db.flush()
    return elegido.usuario_id


# ── Metodología (CRM-03.01.02.01, .02, .03) ───────────────────────────────

# Los criterios de las metodologías conocidas. Se traen de serie porque un tenant
# que elige MEDDIC espera MEDDIC, no una pantalla en blanco donde teclearlo.
CRITERIOS_DE_SERIE: dict[str, list[dict[str, Any]]] = {
    "meddic": [
        {"clave": "metricas", "etiqueta": "Métricas: qué gana medido en números", "peso": 15},
        {"clave": "comprador_economico", "etiqueta": "Quién firma el cheque", "peso": 20},
        {"clave": "criterios_decision", "etiqueta": "Con qué nos van a comparar", "peso": 15},
        {"clave": "proceso_decision", "etiqueta": "Qué pasos hay hasta la firma", "peso": 15},
        {"clave": "dolor", "etiqueta": "Qué les duele hoy", "peso": 20},
        {"clave": "campeon", "etiqueta": "Quién nos defiende dentro", "peso": 15},
    ],
    "bant": [
        {"clave": "presupuesto", "etiqueta": "Hay presupuesto", "peso": 25},
        {"clave": "autoridad", "etiqueta": "Hablamos con quien decide", "peso": 25},
        {"clave": "necesidad", "etiqueta": "Hay una necesidad real", "peso": 25},
        {"clave": "plazo", "etiqueta": "Hay una fecha", "peso": 25},
    ],
    # SPIN y Challenger se ofrecían como familias y salían vacías: quien las
    # elegía se encontraba la pantalla en blanco que esto existe para evitar.
    "spin": [
        {"clave": "situacion", "etiqueta": "Conocemos su situación actual", "peso": 20},
        {"clave": "problema", "etiqueta": "Sabemos qué problema tienen", "peso": 25},
        {"clave": "implicacion", "etiqueta": "Saben lo que les cuesta no resolverlo", "peso": 30},
        {
            "clave": "necesidad_beneficio",
            "etiqueta": "Ellos mismos dicen qué ganarían",
            "peso": 25,
        },
    ],
    "challenger": [
        {"clave": "ensenar", "etiqueta": "Les hemos enseñado algo que no sabían", "peso": 30},
        {"clave": "adaptar", "etiqueta": "Lo hemos adaptado a cada decisor", "peso": 25},
        {"clave": "tomar_control", "etiqueta": "Llevamos nosotros el proceso", "peso": 25},
        {"clave": "movilizador", "etiqueta": "Hay alguien dentro que empuja", "peso": 20},
    ],
}


def criterios_de(metodologia: Metodologia) -> list[dict[str, Any]]:
    """Los criterios de una metodología, en una sola forma.

    Se han escrito de dos maneras —`etiqueta` y `peso`, o `nombre` y
    `pregunta` sin peso—, y el motor sólo leía la primera: una metodología
    sembrada de la segunda salía con los criterios sin nombre y puntuando cero
    aunque se marcaran todos. La etiqueta es la pregunta, si la hay; y sin pesos
    declarados, todos pesan lo mismo.
    """
    crudos = list(metodologia.criterios or []) or CRITERIOS_DE_SERIE.get(metodologia.familia, [])
    sin_peso = not any(c.get("peso") for c in crudos if isinstance(c, dict))
    reparto = round(100 / len(crudos)) if crudos and sin_peso else 0
    return [
        {
            **c,
            "etiqueta": c.get("etiqueta") or c.get("pregunta") or c.get("nombre") or c.get("clave"),
            "peso": reparto if sin_peso else int(c.get("peso") or 0),
        }
        for c in crudos
        if isinstance(c, dict) and c.get("clave")
    ]


def metodologia_de(db: Session, tenant_id: UUID, oportunidad: Any) -> Metodologia | None:
    """La metodología que se aplica a esta oportunidad: la de su embudo.

    Una que nombra el embudo manda sobre la general (sin embudo): cada embudo
    puede tener la suya —la venta de proyecto con MEDDIC, la renovación con
    BANT— y una general cubre los que no tienen.
    """
    from services.sales.modelos import Pipeline

    pipeline = db.get(Pipeline, oportunidad.pipeline_id) if oportunidad.pipeline_id else None
    filas = list(
        db.execute(
            select(Metodologia).where(
                Metodologia.tenant_id == tenant_id,
                Metodologia.activa.is_(True),
                Metodologia.deleted_at.is_(None),
            )
        ).scalars()
    )
    propia = [m for m in filas if pipeline is not None and m.pipeline == pipeline.clave]
    general = [m for m in filas if not m.pipeline]
    return (propia or general or [None])[0]


def responder(
    db: Session,
    tenant_id: UUID,
    metodologia_id: UUID,
    oportunidad_id: UUID,
    respuestas: dict[str, Any],
    *,
    por: UUID | None,
) -> dict[str, Any]:
    """Apunta qué criterios están cubiertos y con qué, y recalcula.

    Se mezcla con lo que había: contestar un criterio no borra los demás. Un
    criterio que no es de la metodología se rechaza —una errata no puede
    quedarse guardada como si cubriera algo—.
    """
    metodologia = db.get(Metodologia, metodologia_id)
    if metodologia is None or metodologia.tenant_id != tenant_id:
        raise NoEncontrado("La metodología no existe", error_code="metodologia.no_encontrada")
    criterios = criterios_de(metodologia)
    validas = {str(c.get("clave")) for c in criterios}
    desconocidas = sorted(set(respuestas) - validas)
    if desconocidas:
        raise ErrorValidacion(
            f"Criterios que no son de esta metodología: {', '.join(desconocidas)}",
            error_code="metodologia.criterio_desconocido",
            detalle={"validos": sorted(validas)},
        )
    fila = db.execute(
        select(EvaluacionMetodologia).where(
            EvaluacionMetodologia.tenant_id == tenant_id,
            EvaluacionMetodologia.oportunidad_id == oportunidad_id,
            EvaluacionMetodologia.metodologia_id == metodologia_id,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = EvaluacionMetodologia(
            tenant_id=tenant_id, oportunidad_id=oportunidad_id, metodologia_id=metodologia_id
        )
        db.add(fila)
    actuales = dict(fila.respuestas or {})
    for clave, valor in respuestas.items():
        cubierto = bool(valor.get("cubierto")) if isinstance(valor, dict) else bool(valor)
        if cubierto:
            nota = str(valor.get("nota") or "") if isinstance(valor, dict) else ""
            actuales[clave] = {"cubierto": True, "nota": nota, "por": str(por) if por else None}
        else:
            actuales.pop(clave, None)
    fila.respuestas = actuales
    db.flush()
    resultado = evaluar(db, tenant_id, metodologia_id, oportunidad_id)
    fila.puntuacion = Decimal(str(resultado["puntuacion"]))
    fila.actualizada_at = _ahora()
    db.flush()
    return resultado


def evaluar(
    db: Session, tenant_id: UUID, metodologia_id: UUID, oportunidad_id: UUID
) -> dict[str, Any]:
    """Qué falta para poder cerrar esta oportunidad.

    **Se dice lo que falta, no lo que hay.** Un indicador que sube al rellenar
    campos premia rellenar campos; el que sirve devuelve una lista de cosas que
    hacer, y por eso `lo_que_falta` va antes que la puntuación.

    La puntuación existe para ordenar un pipeline, no para felicitar a nadie.
    """
    metodologia = db.get(Metodologia, metodologia_id)
    if metodologia is None or metodologia.tenant_id != tenant_id:
        raise NoEncontrado("La metodología no existe", error_code="metodologia.no_encontrada")

    evaluacion = db.execute(
        select(EvaluacionMetodologia).where(
            EvaluacionMetodologia.tenant_id == tenant_id,
            EvaluacionMetodologia.oportunidad_id == oportunidad_id,
            EvaluacionMetodologia.metodologia_id == metodologia_id,
        )
    ).scalar_one_or_none()
    respuestas = (evaluacion.respuestas if evaluacion else {}) or {}

    from crmcore.runtime import settings as rt

    minimo_pct = int(rt.efectivo("metodologia_minimo_cualificada_pct", db) or 50)
    criterios = criterios_de(metodologia)
    total = sum(int(c.get("peso", 0)) for c in criterios) or 100
    logrado = 0
    falta: list[dict[str, Any]] = []
    for criterio in criterios:
        clave = str(criterio.get("clave"))
        if respuestas.get(clave):
            logrado += int(criterio.get("peso", 0))
        else:
            falta.append(
                {
                    "clave": clave,
                    "etiqueta": criterio.get("etiqueta", clave),
                    "peso": criterio.get("peso", 0),
                }
            )

    # Lo que falta, ordenado por peso: lo primero de la lista es lo que más mueve
    # la aguja, que es la única forma de que una lista de seis cosas se empiece.
    falta.sort(key=lambda c: -int(c.get("peso", 0)))
    return {
        "lo_que_falta": falta,
        "siguiente_paso": falta[0]["etiqueta"] if falta else None,
        "puntuacion": round(100 * logrado / total, 1),
        "criterios": len(criterios),
        "cubiertos": len(criterios) - len(falta),
        # Con demasiado sin contestar, la puntuación no dice si el negocio va
        # bien: dice que no se ha cualificado. Cuánto es «demasiado» lo decide
        # la empresa (`metodologia_minimo_cualificada_pct`); era la mitad,
        # escrito aquí.
        "cualificada": bool(criterios)
        and 100 * (len(criterios) - len(falta)) >= minimo_pct * len(criterios),
        "minimo_cualificada_pct": minimo_pct,
        # Todos, cubiertos y no, con lo que se apuntó: es lo que deja marcarlos
        # desde la ficha. Sin esto sólo se veía lo que faltaba y no había forma
        # de decir que ya se tenía.
        "detalle": [
            {
                "clave": str(c.get("clave")),
                "etiqueta": c.get("etiqueta", c.get("clave")),
                "peso": c.get("peso", 0),
                "desde_etapa": c.get("desde_etapa"),
                "cubierto": bool(respuestas.get(str(c.get("clave")))),
                "nota": (respuestas.get(str(c.get("clave"))) or {}).get("nota", "")
                if isinstance(respuestas.get(str(c.get("clave"))), dict)
                else "",
            }
            for c in criterios
        ],
        "metodologia": {"id": str(metodologia.id), "nombre": metodologia.nombre},
    }


def _normal(texto: str) -> str:
    import re
    import unicodedata

    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", texto or "") if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", "_", sin_tildes.lower()).strip("_")


def playbook_para(
    db: Session,
    tenant_id: UUID,
    *,
    etapa: str = "",
    segmento: str = "",
    contexto: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """El playbook que toca aquí y ahora (CRM-03.01.02.03).

    Gana el **más específico**: uno que nombra etapa y segmento manda sobre uno
    que solo nombra la etapa. Con el orden al revés, el playbook genérico taparía
    siempre al que alguien escribió para su caso.
    """
    from crmcore.authz.abac import Condicion

    filas = (
        db.execute(
            select(Playbook).where(Playbook.tenant_id == tenant_id, Playbook.activo.is_(True))
        )
        .scalars()
        .all()
    )
    ambito = {"oportunidad": contexto or {}}
    candidatos: list[tuple[int, Playbook]] = []
    for fila in filas:
        # La etapa se compara normalizada: unos guardan la clave
        # («cualificacion») y otros piden por el nombre («Cualificación»). Sin
        # esto, los pasos guardados desde Administrar no salían en la ficha.
        if fila.etapa and _normal(fila.etapa) != _normal(etapa):
            continue
        if fila.segmento and fila.segmento != segmento:
            continue
        condiciones = [
            Condicion(
                atributo=str(c.get("atributo", "")),
                operador=str(c.get("operador", "=")),
                valor=c.get("valor"),
            )
            for c in (fila.condiciones or [])
            if isinstance(c, dict)
        ]
        if not all(c.evaluar(ambito) for c in condiciones):
            continue
        especificidad = (
            (1 if fila.etapa else 0) + (1 if fila.segmento else 0) + len(fila.condiciones or [])
        )
        candidatos.append((especificidad, fila))

    if not candidatos:
        return None
    candidatos.sort(key=lambda c: -c[0])
    elegido = candidatos[0][1]
    return {
        "clave": elegido.clave,
        "titulo": elegido.titulo,
        "pasos": list(elegido.pasos or []),
        # Se dice por qué se eligió este: un playbook que aparece sin explicación
        # se cierra sin leerlo.
        "por_que": (
            f"Aplica a la etapa «{elegido.etapa}»" if elegido.etapa else "Aplica a cualquier etapa"
        )
        + (f" y al segmento «{elegido.segmento}»" if elegido.segmento else ""),
    }
