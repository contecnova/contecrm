"""Modelo de datos del servicio de atención: casos, taxonomía y SLA.

Cubre CRM-04.01.01 (gestión de casos) y CRM-04.01.02 (entitlements y SLA).

Dos decisiones que se notan en todo lo demás:

**Prioridad y severidad son cosas distintas.** La severidad es del problema —qué
está roto y cuánto— y la prioridad es de la respuesta —en qué orden se atiende—.
Fundirlas en un solo campo, que es lo habitual, hace imposible decir «esto es
grave pero puede esperar a mañana» y «esto es menor pero es para el cliente que
renueva el viernes». En cuanto se funden, alguien empieza a marcar todo como
crítico y el campo deja de significar nada.

**El reloj de SLA vive en el caso y no se recalcula.** Guardar el vencimiento
—y no solo el plazo— es lo que permite que cambiar la definición del SLA no
reescriba el pasado: un contrato renegociado no puede convertir en incumplidos
casos que se atendieron a tiempo con las reglas de entonces.
"""

from __future__ import annotations

from datetime import date, datetime
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


class CategoriaCaso(Base, TimestampMixin):
    """Nodo del árbol de clasificación (CRM-04.01.01.02).

    Es un árbol y no dos campos fijos —categoría y subcategoría— porque cada
    línea de servicio clasifica a su profundidad: soporte de software llega a
    tres niveles y mantenimiento de instalaciones a cinco. Con dos campos, el
    tercer nivel acaba concatenado dentro del segundo y los informes dejan de
    poder agrupar.
    """

    __tablename__ = "categorias_caso"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    padre_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("categorias_caso.id", ondelete="CASCADE"), nullable=True
    )
    # Línea de servicio a la que pertenece el árbol. Permite que soporte y
    # mantenimiento tengan taxonomías distintas sin mezclarlas en el desplegable.
    linea: Mapped[str] = mapped_column(String(60), nullable=False, default="general")
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Solo las hojas se pueden elegir al clasificar un caso. Dejar elegir un nodo
    # intermedio convierte «software» en un cajón donde acaba la mitad de los
    # casos, y entonces la taxonomía no sirve para lo único que sirve: agrupar.
    seleccionable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Prioridad que se propone al elegir esta hoja. Propone, no impone: quien
    # atiende sabe cosas que la taxonomía no.
    prioridad_sugerida: Mapped[str | None] = mapped_column(String(20), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "linea", "clave", name="uq_categoria_caso"),
        Index("ix_categorias_caso_padre", "tenant_id", "padre_id", "orden"),
    )


class DefinicionSLA(Base, TimestampMixin):
    """Compromiso de tiempos por prioridad y tipo de cliente (CRM-04.01.02.02).

    Versionada: cambiar el SLA **no** reescribe el pasado. Un contrato
    renegociado no puede convertir en incumplidos casos que se atendieron a
    tiempo con las reglas de entonces, ni al revés — y esa es exactamente la
    trampa del SLA guardado como una sola fila que se edita.
    """

    __tablename__ = "definiciones_sla"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(60), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # A quién aplica. Vacío = a todos; con valores, gana el más específico.
    prioridad: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tier_cliente: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # Plazos en horas **laborables**. Que sean laborables es lo que hace que un
    # aviso entrado el viernes a las 18:00 no se incumpla el sábado a las 22:00.
    horas_primera_respuesta: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    horas_resolucion: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    horas_actualizacion: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    calendario: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    # Cuándo avisar de que se acerca el vencimiento, en porcentaje del plazo.
    aviso_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=80)

    vigente_desde: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.now())
    vigente_hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", "version", name="uq_sla_version"),
        Index("ix_sla_aplicables", "tenant_id", "activa", "prioridad"),
    )


class Caso(EntidadBase, SoftDeleteMixin, MetadatosMixin):
    """Una solicitud de servicio (CRM-04.01.01.01)."""

    __tablename__ = "casos"

    # Código legible: es lo que el cliente escribe en el asunto de un correo y lo
    # que se dice por teléfono. Sin él, la referencia acaba siendo un UUID que
    # nadie transcribe bien.
    codigo: Mapped[str | None] = mapped_column(String(30), nullable=True)
    asunto: Mapped[str] = mapped_column(String(300), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)

    tipo: Mapped[str] = mapped_column(String(40), nullable=False, default="incidencia")
    categoria_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, index=True
    )
    linea: Mapped[str] = mapped_column(String(60), nullable=False, default="general")

    # Severidad: qué está roto y cuánto. Prioridad: en qué orden se atiende. Son
    # dos campos y no uno porque «grave pero puede esperar» y «menor pero urgente
    # por el cliente» son casos reales que un solo campo no puede representar.
    severidad: Mapped[str] = mapped_column(String(20), nullable=False, default="media")
    prioridad: Mapped[str] = mapped_column(String(20), nullable=False, default="media", index=True)
    origen: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")

    # nuevo | asignado | en_curso | esperando_cliente | resuelto | cerrado
    estado: Mapped[str] = mapped_column(String(30), nullable=False, default="nuevo", index=True)

    # ── Con qué se relaciona (CRM-04.01.01.03) ────────────────────────────
    # Identificadores opacos y no claves foráneas: cuenta y contacto viven en
    # `party`, y ningún servicio lee el esquema de otro. La integridad se apoya
    # en el evento de borrado, no en la base.
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    contacto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    producto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    activo_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    contrato_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    pedido_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # ── Jerarquía (CRM-04.01.01.04) ───────────────────────────────────────
    padre_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    # Caso maestro de una incidencia masiva (CRM-04.01.01.11): cien casos que son
    # la misma caída se cuelgan de uno y se cierran juntos.
    maestro_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    # Duplicado de otro. Se marca en vez de borrarse porque el cliente que lo
    # abrió tiene derecho a ver su caso y su respuesta.
    duplicado_de_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    owner_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    equipo: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    business_unit_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # ── Reloj de SLA (CRM-04.01.02.03) ────────────────────────────────────
    # Se guardan los VENCIMIENTOS calculados, no solo el plazo. Recalcularlos al
    # consultar haría que cambiar la definición del SLA reescribiera el pasado.
    sla_clave: Mapped[str | None] = mapped_column(String(60), nullable=True)
    sla_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vence_primera_respuesta_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    vence_resolucion_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    primera_respuesta_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resuelto_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cerrado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Tiempo que el reloj ha estado parado esperando al cliente. Se acumula en
    # segundos porque el reloj se para y se reanuda varias veces, y guardar solo
    # el último tramo perdería los anteriores.
    pausa_acumulada_s: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pausado_desde: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Se marcan por separado: incumplir la primera respuesta y incumplir la
    # resolución son dos conversaciones distintas con el cliente.
    incumplio_primera_respuesta: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    incumplio_resolucion: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Cierre (CRM-04.01.01.09, .10) ─────────────────────────────────────
    motivo_cierre: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resolucion: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Cerrado por el agente pero pendiente de que el cliente lo dé por bueno.
    validacion_cliente: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reaperturas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("tenant_id", "codigo", name="uq_caso_codigo"),
        Index("ix_casos_cola", "tenant_id", "estado", "prioridad", "vence_resolucion_at"),
        Index("ix_casos_cuenta", "tenant_id", "cuenta_id", "estado"),
    )


class EventoCaso(Base):
    """Cada cambio relevante del caso, para la trazabilidad y los relojes.

    Va aparte del historial de campos porque aquí importa el **orden** y el
    instante exacto: de estas filas salen el tiempo de primera respuesta, las
    pausas y la reapertura, y reconstruirlos desde un diff genérico de campos es
    caro y frágil.
    """

    __tablename__ = "eventos_caso"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    caso_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("casos.id", ondelete="CASCADE"), nullable=False
    )
    tipo: Mapped[str] = mapped_column(String(40), nullable=False)
    detalle: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        # `clock_timestamp()` y no `now()`: dos eventos en la misma transacción
        # —abrir y asignar de golpe— compartirían instante con `now()` y el
        # historial dejaría de poder ordenarse.
        DateTime(timezone=True),
        server_default=text("clock_timestamp()"),
        nullable=False,
    )

    __table_args__ = (Index("ix_eventos_caso", "tenant_id", "caso_id", "created_at"),)


# ── Tablas compartidas que viven en ESTE esquema ──────────────────────────
#
# Igual que en los demás servicios: `modelos.py` es lo que lee el generador de
# migraciones y la fixture de pruebas, así que un modelo compartido que no
# aparezca aquí sencillamente no se migra.
from crmcore.authz.comparticion import ComparticionManual, ReglaComparticion  # noqa: E402
from crmcore.authz.politicas import PoliticaAbac, VersionPoliticaAbac  # noqa: E402
from crmcore.authz.proyeccion import PoliticaCampo  # noqa: E402
from crmcore.busqueda import DocumentoIndexado  # noqa: E402
from crmcore.datos.adjuntos import Adjunto, DescargaAdjunto  # noqa: E402
from crmcore.datos.calendario import CalendarioLaboral, Festivo  # noqa: E402
from crmcore.datos.cambio import TipoCambio  # noqa: E402
from crmcore.datos.comentarios import Comentario  # noqa: E402
from crmcore.datos.papelera import EntradaPapelera  # noqa: E402
from crmcore.datos.retencion import BloqueoLegal, PoliticaRetencion  # noqa: E402
from crmcore.datos.trabajos import Trabajo  # noqa: E402
from crmcore.documental.enlaces import DocumentoEnlazado, OrganizacionDocumental  # noqa: E402
from crmcore.metamodelo import EsquemaTenant, UsoCampo  # noqa: E402
from crmcore.runtime.versiones import VersionAjuste  # noqa: E402
from crmcore.security.byok import ClaveTenant  # noqa: E402

from services.service.conocimiento import (  # noqa: E402
    Articulo,
    ValoracionArticulo,
    VersionArticulo,
)
from services.service.entitlements import (  # noqa: E402
    ConsumoEntitlement,
    CreditoServicio,
    Encuesta,
    Entitlement,
)
from services.service.omnicanal import (  # noqa: E402
    CanalServicio,
    Conversacion,
    Macro,
    Mensaje,
)
from services.service.operacion import (  # noqa: E402
    AgenteServicio,
    ColaCasos,
    RegistroAsignacion,
    ReglaAsignacion,
    ReglaEscalada,
)

__all__ = [
    "AccesoPortal",
    "Articulo",
    "EnlaceAcceso",
    "HiloComunidad",
    "RespuestaComunidad",
    "ValoracionArticulo",
    "VersionArticulo",
    "CanalServicio",
    "Conversacion",
    "Macro",
    "Mensaje",
    "AgenteServicio",
    "ColaCasos",
    "ConsumoEntitlement",
    "CreditoServicio",
    "Encuesta",
    "Entitlement",
    "RegistroAsignacion",
    "ReglaAsignacion",
    "ReglaEscalada",
    "Adjunto",
    "BloqueoLegal",
    "CalendarioLaboral",
    "Caso",
    "CategoriaCaso",
    "ClaveTenant",
    "Comentario",
    "ComparticionManual",
    "DefinicionSLA",
    "DescargaAdjunto",
    "DocumentoEnlazado",
    "DocumentoIndexado",
    "EntradaPapelera",
    "EsquemaTenant",
    "EventoCaso",
    "Festivo",
    "OrganizacionDocumental",
    "PoliticaAbac",
    "PoliticaCampo",
    "PoliticaRetencion",
    "ReglaComparticion",
    "TipoCambio",
    "Trabajo",
    "UsoCampo",
    "VersionAjuste",
    "VersionPoliticaAbac",
]

# El servicio de campo y los activos instalados viven en sus propios módulos
# —cada uno con su lógica— pero sus tablas son de este esquema y tienen que
# importarse aquí: `alembic` solo mira `modelos.py`.
from services.service.activos import (  # noqa: E402,F401
    ActivoInstalado,
    EventoActivo,
    Garantia,
)
from services.service.campo import (  # noqa: E402,F401
    LineaOrden,
    MovimientoRepuesto,
    OperacionSincronizada,
    OrdenTrabajo,
    ParteTrabajo,
    PlanPreventivo,
    Repuesto,
    StockFurgoneta,
    Tecnico,
)
from services.service.portal import (  # noqa: E402
    AccesoPortal,
    EnlaceAcceso,
    HiloComunidad,
    RespuestaComunidad,
)
from services.service.postventa import (  # noqa: E402,F401
    Devolucion,
    Expediente,
    LineaDevolucion,
    Resolucion,
)
from services.service.problemas import (  # noqa: E402,F401
    CasoDeProblema,
    ComunicacionProblema,
    Problema,
)
