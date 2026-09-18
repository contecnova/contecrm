"""Modelo de datos de leads, pipelines y oportunidades."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, EntidadBase, MetadatosMixin, SoftDeleteMixin, TimestampMixin
from crmcore.ids import nuevo_id
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column


class Lead(EntidadBase, SoftDeleteMixin, MetadatosMixin):
    """Una pista de negocio sin cualificar (CRM-01.01.03.01).

    Tiene ciclo de vida propio y **no** contamina el maestro de cuentas hasta
    que alguien lo cualifica. Cuando se convierte, la fila se conserva apuntando
    a lo que generó: es lo que permite responder a «¿de dónde salió este
    cliente?» y lo que hace posible la atribución.
    """

    __tablename__ = "leads"

    # Datos tal como llegaron, sin normalizar en exceso: un lead es información
    # cruda y limpiarla de más pierde señal (un cargo escrito raro puede decir
    # mucho de la fuente).
    nombre: Mapped[str | None] = mapped_column(String(150), nullable=True)
    apellidos: Mapped[str | None] = mapped_column(String(200), nullable=True)
    empresa: Mapped[str | None] = mapped_column(String(300), nullable=True)
    cargo: Mapped[str | None] = mapped_column(String(150), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    telefono: Mapped[str | None] = mapped_column(String(40), nullable=True)
    web: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pais: Mapped[str | None] = mapped_column(String(2), nullable=True)

    # nuevo | contactado | cualificado | convertido | descartado | reciclado
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="nuevo", index=True)
    # Motivo normalizado del descarte (CRM-01.01.03.05). Normalizado y no libre
    # porque lo que se quiere es contar: «sin presupuesto» frente a «no es
    # nuestro perfil» llevan a acciones distintas, y en texto libre no se puede
    # agrupar.
    motivo_descarte: Mapped[str | None] = mapped_column(String(80), nullable=True)
    nota_descarte: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Fecha a partir de la cual el lead descartado vuelve a la cola: un «ahora no
    # tenemos presupuesto» no es un no para siempre.
    reciclar_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    # ── Origen (CRM-01.01.03.06) ──────────────────────────────────────────
    # Los cinco parámetros UTM más el primer y último toque. Se guardan los dos
    # porque los modelos de atribución los necesitan: el primero explica cómo
    # llegó, el último qué lo cerró.
    origen: Mapped[str | None] = mapped_column(String(80), nullable=True)
    campana_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    utm: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    primer_toque: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    ultimo_toque: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    # ── Asignación y SLA (CRM-01.01.03.04, .07) ───────────────────────────
    owner_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    asignado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Cuándo vence el SLA de primera respuesta y cuándo se respondió de verdad.
    # Las dos fechas, no solo la diferencia: el incumplimiento hay que poder
    # demostrarlo y agregarlo por periodo.
    sla_primera_respuesta_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    primera_respuesta_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sla_incumplido: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Conversión ────────────────────────────────────────────────────────
    convertido_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    contacto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    oportunidad_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # Puntuación, cuando haya scoring. Se deja el hueco preparado para no migrar
    # la tabla entera en la fase 4.
    puntuacion: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_leads_tenant_estado", "tenant_id", "estado", "created_at"),
        Index("ix_leads_owner", "tenant_id", "owner_id", "estado"),
        Index(
            "ix_leads_sla_en_riesgo",
            "tenant_id",
            "sla_primera_respuesta_at",
            postgresql_where=text(
                "primera_respuesta_at IS NULL AND estado NOT IN ('convertido','descartado')"
            ),
        ),
    )


class Pipeline(Base, TimestampMixin):
    """Un embudo de ventas (CRM-03.01.01.02).

    Varios por tenant: la venta de proyecto no tiene las mismas etapas que la de
    mantenimiento, y forzar una sola hace que la mitad de las oportunidades estén
    siempre en una etapa que no significa nada para ellas.
    """

    __tablename__ = "pipelines"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    clave: Mapped[str] = mapped_column(String(60), nullable=False)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # A qué se aplica: línea de negocio, producto, canal o región. Informativo:
    # quién lo usa lo decide quien crea la oportunidad.
    ambito: Mapped[str | None] = mapped_column(String(80), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    por_defecto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_pipeline_clave"),
        Index("ix_pipelines_tenant", "tenant_id", "activo"),
        # Un solo pipeline por defecto y por tenant, garantizado por la base: si
        # hubiera dos, cuál se aplica dependería del orden de lectura.
        Index(
            "ix_pipelines_defecto",
            "tenant_id",
            unique=True,
            postgresql_where=text("por_defecto"),
        ),
    )


class Etapa(Base, TimestampMixin):
    """Una etapa de un pipeline, con sus criterios de salida (CRM-03.01.01.03).

    Los **criterios de salida** son lo que distingue un pipeline útil de una
    lista de colores: obligan a que una oportunidad no avance sin la información
    que esa etapa exige, y por tanto hacen que la previsión signifique algo.
    """

    __tablename__ = "etapas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    pipeline_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False
    )
    clave: Mapped[str] = mapped_column(String(60), nullable=False)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Probabilidad por defecto de la etapa. El comercial puede ajustarla por
    # oportunidad; esto es el punto de partida.
    probabilidad: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#6B7280")

    # Etapa final: ganada, perdida o cancelada. Se marcan las tres cosas por
    # separado porque «terminal» y «ganada» no son lo mismo y confundirlas
    # falsea cualquier ratio de conversión.
    terminal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ganada: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Campos obligatorios para SALIR de esta etapa, y checklist de tareas.
    criterios_salida: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    checklist: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Días tras los cuales una oportunidad en esta etapa se considera estancada
    # (CRM-03.01.01.12). Por etapa, no global: estar tres semanas en
    # «negociación» es normal y en «primer contacto» no.
    dias_estancamiento: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("pipeline_id", "clave", name="uq_etapa_clave"),
        Index("ix_etapas_pipeline", "tenant_id", "pipeline_id", "orden"),
    )


class Oportunidad(EntidadBase, SoftDeleteMixin, MetadatosMixin):
    """Una operación comercial en curso (CRM-03.01.01.01)."""

    __tablename__ = "oportunidades"

    nombre: Mapped[str] = mapped_column(String(300), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Código legible y correlativo, del tipo OPP-2026-00123. Lo pide todo el
    # mundo: es lo que se dice por teléfono y lo que se escribe en un correo.
    codigo: Mapped[str | None] = mapped_column(String(30), nullable=True)

    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    contacto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    pipeline_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("pipelines.id"), nullable=False
    )
    etapa_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("etapas.id"), nullable=False, index=True
    )

    # ── Importes ──────────────────────────────────────────────────────────
    # `Numeric` y nunca coma flotante: un importe en `float` acumula error y
    # acaba dando un total que no cuadra con la suma de sus líneas.
    importe: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    # Importe convertido a la moneda funcional del tenant, con el cambio del día
    # del cierre previsto. Se guarda calculado para poder sumar el pipeline sin
    # aplicar tipos de cambio en cada consulta.
    importe_funcional: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    probabilidad: Mapped[int] = mapped_column(Integer, nullable=False, default=50)

    fecha_cierre: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    fecha_cierre_real: Mapped[date | None] = mapped_column(Date, nullable=True)

    # ── Estado ────────────────────────────────────────────────────────────
    # abierta | ganada | perdida | cancelada
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="abierta", index=True)
    motivo_perdida: Mapped[str | None] = mapped_column(String(80), nullable=True)
    nota_perdida: Mapped[str | None] = mapped_column(Text, nullable=True)
    competidor_ganador: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # Bloqueo tras el cierre (CRM-03.01.01.14): una oportunidad cerrada no se
    # edita, porque sus números ya están en un informe que alguien ha mirado.
    # Reabrirla es un acto explícito y auditado.
    bloqueada: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reaperturas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    owner_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    business_unit_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # ── Seguimiento (CRM-03.01.01.12) ─────────────────────────────────────
    etapa_desde: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ultima_actividad_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # De dónde vino, si vino de un lead.
    lead_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (
        Index("ix_oportunidades_tenant_estado", "tenant_id", "estado", "fecha_cierre"),
        Index("ix_oportunidades_owner", "tenant_id", "owner_id", "estado"),
        Index("ix_oportunidades_pipeline", "tenant_id", "pipeline_id", "etapa_id"),
        UniqueConstraint("tenant_id", "codigo", name="uq_oportunidad_codigo"),
    )

    @property
    def importe_ponderado(self) -> Decimal:
        """Importe por probabilidad: lo que de verdad suma al pipeline."""
        return (self.importe or Decimal(0)) * Decimal(self.probabilidad) / Decimal(100)


class LineaOportunidad(Base, TimestampMixin):
    """Línea de producto o servicio (CRM-03.01.01.05)."""

    __tablename__ = "lineas_oportunidad"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    oportunidad_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("oportunidades.id", ondelete="CASCADE"), nullable=False
    )
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # El producto se referencia por id y **además** se copia su descripción y su
    # precio. No es duplicar por duplicar: si mañana sube el precio de catálogo,
    # esta oportunidad tiene que seguir diciendo lo que se ofreció.
    producto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    descripcion: Mapped[str] = mapped_column(String(300), nullable=False)
    cantidad: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=1)
    precio_unitario: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    descuento_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    # Total de la línea, calculado y guardado. Se guarda para poder sumar sin
    # recalcular y para que el histórico no cambie si cambia la fórmula.
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    # Coste, para el margen. Nullable porque no siempre se conoce, y un cero
    # fingido daría un margen del 100 % que nadie cuestionaría.
    coste_unitario: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    # puntual | recurrente — de aquí salen el ARR y el MRR en la fase 2.
    tipo_ingreso: Mapped[str] = mapped_column(String(20), nullable=False, default="puntual")
    periodicidad: Mapped[str | None] = mapped_column(String(20), nullable=True)

    __table_args__ = (Index("ix_lineas_oportunidad", "tenant_id", "oportunidad_id", "orden"),)


class CambioEtapa(Base):
    """Historial de paso por etapas (CRM-03.01.01.12, .13).

    De aquí salen la antigüedad por etapa, el estancamiento y el *waterfall* del
    pipeline. Se guardan también el importe y la fecha de cierre **en el momento
    del cambio**: sin eso no se puede medir el deslizamiento, que es el dato que
    explica por qué el trimestre no salió como se dijo.
    """

    __tablename__ = "cambios_etapa"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    oportunidad_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("oportunidades.id", ondelete="CASCADE"), nullable=False
    )
    etapa_desde_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    etapa_hasta_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    dias_en_etapa: Mapped[int | None] = mapped_column(Integer, nullable=True)
    importe_en_cambio: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    fecha_cierre_en_cambio: Mapped[date | None] = mapped_column(Date, nullable=True)
    motivo: Mapped[str | None] = mapped_column(Text, nullable=True)
    por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # `clock_timestamp()` y NO `now()`. En Postgres, `now()` devuelve la hora
    # de INICIO DE LA TRANSACCIÓN, así que dos cambios de etapa hechos en la
    # misma transacción —una conversión que crea la oportunidad y la mueve, o
    # una carga masiva— comparten fecha al milisegundo y el historial deja de
    # poder ordenarse. Lo destapó la prueba de la carga forzada, que leía el
    # apunte equivocado.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()"), nullable=False
    )

    __table_args__ = (
        Index("ix_cambios_etapa_oportunidad", "tenant_id", "oportunidad_id", "created_at"),
    )


class CompetidorEnOportunidad(Base, TimestampMixin):
    """Competidores presentes en una operación (CRM-03.01.01.09).

    Con su posicionamiento, no solo el nombre: saber que se perdió contra X es
    útil; saber que se perdió contra X **por precio** y no por producto es lo que
    cambia la estrategia.
    """

    __tablename__ = "competidores_oportunidad"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    oportunidad_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("oportunidades.id", ondelete="CASCADE"), nullable=False
    )
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    # cuenta_id cuando el competidor está además como cuenta en el CRM.
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    fortalezas: Mapped[str | None] = mapped_column(Text, nullable=True)
    debilidades: Mapped[str | None] = mapped_column(Text, nullable=True)
    ganador: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("oportunidad_id", "nombre", name="uq_competidor_oportunidad"),
        Index("ix_competidores_tenant", "tenant_id", "oportunidad_id"),
    )


# ── Tablas compartidas que viven en ESTE esquema ──────────────────────────
#
# Se importan aquí, y no solo donde se usan, porque `modelos.py` es lo que lee
# el generador de migraciones (`alembic/env.py`) y la fixture de pruebas para
# saber qué tablas tiene este servicio. Un modelo compartido que no aparezca
# aquí sencillamente **no se migra**: el código lo usa, la tabla no existe, y el
# fallo sale la primera vez que alguien lo ejerce en producción.
#
# Que la lista esté escrita a mano es deliberado: dice, en un sitio, qué tablas
# comunes guarda este servicio en su esquema. Descubrirlas automáticamente
# acabaría creando en todos los esquemas las tablas de todos.
from crmcore.datos.adjuntos import Adjunto, DescargaAdjunto  # noqa: E402
from crmcore.datos.papelera import EntradaPapelera  # noqa: E402

from services.sales.enrutamiento import RegistroEnrutamiento, ReglaEnrutamiento  # noqa: E402

__all__ = [
    "Adjunto",
    "CambioEtapa",
    "CompetidorEnOportunidad",
    "DescargaAdjunto",
    "EntradaPapelera",
    "Etapa",
    "Lead",
    "LineaOportunidad",
    "Oportunidad",
    "Pipeline",
    "RegistroEnrutamiento",
    "ReglaEnrutamiento",
]
