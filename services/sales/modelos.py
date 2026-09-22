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
    nombre: Mapped[str | None] = mapped_column(
        String(150), nullable=True, info={"sensibilidad": "personal"}
    )
    apellidos: Mapped[str | None] = mapped_column(
        String(200), nullable=True, info={"sensibilidad": "personal"}
    )
    empresa: Mapped[str | None] = mapped_column(String(300), nullable=True)
    cargo: Mapped[str | None] = mapped_column(String(150), nullable=True)
    email: Mapped[str | None] = mapped_column(
        String(320), nullable=True, index=True, info={"sensibilidad": "personal"}
    )
    telefono: Mapped[str | None] = mapped_column(
        String(40), nullable=True, info={"sensibilidad": "personal"}
    )
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
    # Si alguien la ha fijado a mano (CRM-03.01.01.04). Sin esta bandera, mover
    # la oportunidad de etapa pisa la probabilidad que el comercial ajustó
    # sabiendo algo que el sistema no sabe, y a la tercera vez deja de
    # ajustarla: el dato se convierte en decorativo.
    probabilidad_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Categoría de previsión (CRM-03.02.01.01). Texto y no clave foránea porque
    # la categoría es del tenant y borrarla no puede impedir leer una
    # oportunidad histórica; la integridad la impone el servicio al escribir.
    categoria_forecast: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)

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
    # Familia del producto, copiada igual que la descripción y por el mismo
    # motivo (CRM-03.02.01.08): si se leyera del catálogo al hacer el informe,
    # recategorizar un producto reescribiría la previsión de trimestres ya
    # cerrados, y dos informes del mismo periodo darían números distintos.
    familia: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
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


# ── Previsión de ventas (CRM-03.02.01) ────────────────────────────────────


class CategoriaForecast(Base, TimestampMixin):
    """Categoría de previsión: pipeline, best case, commit, cerrado
    (CRM-03.02.01.01).

    Son **datos y no una enumeración en el código**. La lista de cuatro es la
    habitual, pero hay organizaciones con «upside» entre best case y commit, y
    otras que llaman «compromiso» al commit. Con la lista a fuego, cada una de
    esas es una versión del producto; como tabla, es configuración del tenant.

    Lo que sí es del sistema es el **significado operativo** de cada una, y por
    eso hay dos banderas explícitas en vez de deducirlo del nombre: si cuenta
    para el número comprometido y si es terminal. Deducirlo de la palabra
    «commit» rompería en cuanto alguien la tradujera.
    """

    __tablename__ = "categorias_forecast"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(40), nullable=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Si suma al número que el comercial «se compromete» a cerrar. Es la
    # pregunta que hace el director, y la única que no admite interpretación.
    cuenta_como_compromiso: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Si es una categoría de cierre (ganado/perdido) y por tanto ya no se mueve.
    terminal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#6B7280")
    # Categoría a la que caen las oportunidades que no tienen ninguna asignada.
    por_defecto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (UniqueConstraint("tenant_id", "clave", name="uq_categoria_forecast"),)


class PeriodoForecast(Base, TimestampMixin):
    """Un periodo de previsión y su estado de cierre (CRM-03.02.01.09).

    Cerrar el periodo es lo que hace que un número signifique algo: mientras
    esté abierto, el «commit» del trimestre cambia cada vez que alguien toca una
    oportunidad, y comparar dos informes de fechas distintas es comparar dos
    cosas que no son la misma. Cerrado, el número queda y lo que pase después se
    ve como variación, que es la información útil.
    """

    __tablename__ = "periodos_forecast"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(40), nullable=False)  # 2026-Q1, 2026-03
    nombre: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    desde: Mapped[date] = mapped_column(Date, nullable=False)
    hasta: Mapped[date] = mapped_column(Date, nullable=False)
    cerrado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cerrado_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # Reabrir un periodo cerrado es un acto explícito y contado: si fuera
    # gratis, «cerrado» dejaría de significar nada.
    reaperturas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    motivo_reapertura: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "clave", name="uq_periodo_forecast"),)


class AjusteForecast(Base, TimestampMixin):
    """Ajuste de un responsable sobre el número de su equipo
    (CRM-03.02.01.03).

    Los managers ajustan siempre —saben cosas que no están en el CRM: que un
    cliente ha cambiado de director de compras, que el competidor ha bajado el
    precio—. El problema nunca ha sido que ajusten: es que el ajuste se hace en
    una hoja aparte y nadie sabe después **quién** quitó doscientos mil euros ni
    **por qué**.

    Aquí el ajuste es un registro, con autor, motivo obligatorio y el número
    original al lado. Se guarda el bruto junto al ajustado a propósito: sin él
    no se puede medir si los ajustes de alguien acertaron, que es la única forma
    de saber si conviene hacerle caso el trimestre que viene.
    """

    __tablename__ = "ajustes_forecast"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    periodo: Mapped[str] = mapped_column(String(40), nullable=False)
    # Sobre quién se ajusta: un comercial, un equipo entero o la compañía.
    ambito: Mapped[str] = mapped_column(String(20), nullable=False, default="usuario")
    ambito_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    categoria: Mapped[str] = mapped_column(String(40), nullable=False, default="commit")
    importe_bruto: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    importe_ajustado: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    # Obligatorio por contrato del servicio, no por la base: un ajuste sin
    # motivo es exactamente el problema que esto viene a resolver.
    motivo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "periodo", "ambito", "ambito_id", "categoria", name="uq_ajuste_forecast"
        ),
        Index("ix_ajustes_forecast_periodo", "tenant_id", "periodo"),
    )


class InstantaneaForecast(Base):
    """Foto de la previsión en un momento (CRM-03.02.01.04).

    Reutiliza la idea de `contecmind:app/services/graph_compare.py`. Sin fotos no
    hay *waterfall* posible: la pregunta «qué ha cambiado desde el lunes» no se
    puede contestar mirando solo el estado de hoy, y reconstruirla desde el
    historial de cambios es caro y frágil.

    Se guarda la foto entera aunque ocupe: el coste de almacenar unas cuantas
    filas por periodo es ridículo comparado con no poder explicar por qué el
    trimestre se cayó.
    """

    __tablename__ = "instantaneas_forecast"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    periodo: Mapped[str] = mapped_column(String(40), nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    tomada_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    tomada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    # Totales precalculados por categoría, para no recorrer las líneas cuando
    # solo se quiere comparar dos fotos.
    totales: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    oportunidades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (Index("ix_instantaneas_periodo", "tenant_id", "periodo", "tomada_at"),)


class LineaInstantanea(Base):
    """Una oportunidad dentro de una foto de previsión.

    Guarda el estado que tenía **entonces**, no una referencia: si apuntara a la
    oportunidad, la foto cambiaría con ella y dejaría de ser una foto. Ese es el
    fallo clásico de los «históricos» que se construyen con joins.
    """

    __tablename__ = "lineas_instantanea"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    instantanea_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("instantaneas_forecast.id", ondelete="CASCADE"),
        nullable=False,
    )
    oportunidad_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    categoria: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    etapa_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    owner_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    importe: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    importe_funcional: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    probabilidad: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fecha_cierre: Mapped[date | None] = mapped_column(Date, nullable=True)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="abierta")

    __table_args__ = (Index("ix_lineas_instantanea", "tenant_id", "instantanea_id"),)


class CambioPrevision(Base):
    """Cada cambio de importe o de fecha de cierre (CRM-03.01.01.13).

    `CambioEtapa` solo anota cuando la oportunidad se mueve de etapa, y el
    deslizamiento casi nunca va acompañado de un cambio de etapa: lo normal es
    que la fecha se empuje dos semanas sin tocar nada más. Sin esta tabla, el
    dato que explica por qué el trimestre no salió como se dijo no existe.

    Se guardan los dos valores, el de antes y el de después. Con solo el nuevo,
    reconstruir el anterior obliga a recorrer el historial hacia atrás y a
    acertar con el orden; con los dos delante, el deslizamiento es una resta.
    """

    __tablename__ = "cambios_prevision"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    oportunidad_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("oportunidades.id", ondelete="CASCADE"), nullable=False
    )
    campo: Mapped[str] = mapped_column(String(30), nullable=False)  # importe | fecha_cierre
    valor_anterior: Mapped[str | None] = mapped_column(String(60), nullable=True)
    valor_nuevo: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # Días que se ha movido la fecha. Denormalizado porque es LA consulta:
    # «cuánto se ha deslizado este trimestre» no puede obligar a parsear fechas
    # en cada fila de un histórico de cien mil apuntes.
    dias_deslizados: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delta_importe: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    motivo: Mapped[str | None] = mapped_column(Text, nullable=True)
    por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        # `clock_timestamp()` por el mismo motivo que en `CambioEtapa`: `now()`
        # da la hora de inicio de la transacción y dos cambios seguidos
        # compartirían instante, dejando el historial sin orden.
        DateTime(timezone=True),
        server_default=text("clock_timestamp()"),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_cambios_prevision_op", "tenant_id", "oportunidad_id", "created_at"),
        Index("ix_cambios_prevision_campo", "tenant_id", "campo", "created_at"),
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
from crmcore.authz.comparticion import ComparticionManual, ReglaComparticion  # noqa: E402
from crmcore.authz.politicas import PoliticaAbac, VersionPoliticaAbac  # noqa: E402
from crmcore.authz.proyeccion import PoliticaCampo  # noqa: E402
from crmcore.busqueda import DocumentoIndexado  # noqa: E402
from crmcore.datos.adjuntos import Adjunto, DescargaAdjunto  # noqa: E402
from crmcore.datos.cambio import TipoCambio  # noqa: E402
from crmcore.datos.comentarios import Comentario  # noqa: E402
from crmcore.datos.papelera import EntradaPapelera  # noqa: E402
from crmcore.datos.retencion import BloqueoLegal, PoliticaRetencion  # noqa: E402
from crmcore.datos.trabajos import Trabajo  # noqa: E402
from crmcore.documental.enlaces import DocumentoEnlazado, OrganizacionDocumental  # noqa: E402
from crmcore.metamodelo import EsquemaTenant, UsoCampo  # noqa: E402
from crmcore.runtime.versiones import VersionAjuste  # noqa: E402
from crmcore.security.byok import ClaveTenant  # noqa: E402

from services.sales.captura import CanalCaptura, RecepcionCaptura  # noqa: E402
from services.sales.enrutamiento import RegistroEnrutamiento, ReglaEnrutamiento  # noqa: E402
from services.sales.origen import Toque  # noqa: E402

__all__ = [
    "EsquemaTenant",
    "UsoCampo",
    "VersionAjuste",
    "TipoCambio",
    "AjusteForecast",
    "CambioPrevision",
    "CategoriaForecast",
    "InstantaneaForecast",
    "LineaInstantanea",
    "PeriodoForecast",
    "PoliticaAbac",
    "VersionPoliticaAbac",
    "DocumentoEnlazado",
    "OrganizacionDocumental",
    "CanalCaptura",
    "RecepcionCaptura",
    "ComparticionManual",
    "ReglaComparticion",
    "ClaveTenant",
    "Adjunto",
    "Comentario",
    "CambioEtapa",
    "CompetidorEnOportunidad",
    "DescargaAdjunto",
    "BloqueoLegal",
    "DocumentoIndexado",
    "EntradaPapelera",
    "PoliticaCampo",
    "PoliticaRetencion",
    "Etapa",
    "Lead",
    "LineaOportunidad",
    "Oportunidad",
    "Pipeline",
    "RegistroEnrutamiento",
    "ReglaEnrutamiento",
    "Toque",
    "Trabajo",
]

# El catálogo de productos y la cotización viven en sus propios módulos —cada uno
# con su lógica—, pero sus tablas son de este esquema y tienen que importarse
# aquí: `alembic` solo mira `modelos.py`, y una tabla que no se importe no se
# migra y falla en la primera consulta, lejos de donde se declaró.
# Las actividades de tratamiento de este servicio (CRM-07.03.01.04). Se importa
# al final y solo por su efecto: declararlas al cargar los modelos es lo que
# garantiza que el RAT y los objetos no puedan separarse.
from services.sales import tratamientos  # noqa: E402,F401
from services.sales.cadencias import (  # noqa: E402,F401
    Cadencia,
    DisponibilidadAgenda,
    EvaluacionMetodologia,
    Inscripcion,
    Metodologia,
    PlantillaCorreo,
    Playbook,
    ToqueCadencia,
)
from services.sales.catalogo import (  # noqa: E402,F401
    ListaPrecio,
    Producto,
    ReglaPrecio,
    RelacionProducto,
)
from services.sales.comisiones import (  # noqa: E402,F401
    AsignacionPlan,
    DisputaComision,
    LineaComision,
    Liquidacion,
    PlanComision,
    ReglaComision,
)
from services.sales.partners import (  # noqa: E402,F401
    AccesoPartner,
    AcuerdoCanal,
    CertificacionPartner,
    EnlaceAccesoPartner,
    NivelPartner,
    Partner,
    PlanConjunto,
    RegistroOportunidad,
)
from services.sales.presupuestos import (  # noqa: E402,F401
    CambioSuscripcion,
    Contrato,
    LineaPresupuesto,
    Pedido,
    Presupuesto,
    SuscripcionCliente,
)
from services.sales.territorios import (  # noqa: E402,F401
    AsignacionTerritorio,
    Cuota,
    ExcepcionTerritorio,
    MiembroTerritorio,
    Territorio,
)
