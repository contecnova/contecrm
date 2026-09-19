"""Modelo de datos del servicio de tenancy."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.ids import nuevo_id
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column


class Tenant(Base, TimestampMixin):
    """Una organización cliente.

    Es la única tabla del sistema donde `tenant_id` no aplica: esta tabla ES el
    registro de tenants. Por eso está exenta del guard ORM (ver
    `crmcore.tenancy.guard.MODELOS_EXENTOS`) y su acceso está restringido a la
    plataforma y al propio tenant sobre su fila.
    """

    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    # Identificador legible y estable: va en subdominios, en correos y en las
    # URLs de los webhooks. No se puede cambiar una vez creado, porque cambiarlo
    # rompería integraciones ajenas que ya lo tienen escrito.
    slug: Mapped[str] = mapped_column(String(63), nullable=False, unique=True)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)

    # activo | suspendido | solo_lectura | en_baja | archivado
    #
    # `solo_lectura` (CRM-00.01.03.04) es el estado más útil de los cuatro: un
    # impago o una migración no deberían cortar el acceso a los datos del
    # cliente, solo impedir que los cambie. Cortar del todo convierte un asunto
    # administrativo en una incidencia de servicio.
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="activo")
    motivo_estado: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Aislamiento y residencia ──────────────────────────────────────────
    # pool | schema | silo (CRM-00.01.01). Es propiedad DEL TENANT, no del
    # despliegue: eso es lo que permite el modelo híbrido por tiers, donde los
    # clientes grandes están en silo y el resto comparte.
    aislamiento: Mapped[str] = mapped_column(String(20), nullable=False, default="pool")
    # Cuando el aislamiento no es `pool`, dónde vive: esquema o URL de conexión.
    # La URL se guarda cifrada porque lleva credenciales.
    aislamiento_destino: Mapped[str | None] = mapped_column(Text, nullable=True)
    region: Mapped[str] = mapped_column(String(20), nullable=False, default="eu")
    # Residencia diferenciada por tipo de dato (CRM-00.01.05.02): puede ser que
    # lo transaccional esté en la UE y lo analítico en otra región.
    residencia: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    # ── Comercial ─────────────────────────────────────────────────────────
    plan: Mapped[str] = mapped_column(String(60), nullable=False, default="base")
    tier: Mapped[str] = mapped_column(String(40), nullable=False, default="estandar")

    # ── Jerarquía (CRM-00.01.03.07) ───────────────────────────────────────
    # Matriz–filial, franquiciador–franquiciado, holding. El padre puede ver
    # agregados de sus hijos si la configuración lo permite; NUNCA sus datos
    # fila a fila por defecto, porque una filial puede tener obligaciones de
    # confidencialidad frente a su matriz.
    tenant_padre_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True, index=True
    )

    # ── Localización y marca ──────────────────────────────────────────────
    idioma: Mapped[str] = mapped_column(String(10), nullable=False, default="es")
    zona_horaria: Mapped[str] = mapped_column(String(60), nullable=False, default="Europe/Madrid")
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    # Marca blanca (CRM-00.01.04.06): logo, paleta, dominio propio, remitente.
    marca: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    # ── Fechas del ciclo de vida ──────────────────────────────────────────
    provisionado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspendido_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    baja_solicitada_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Cuándo se pueden destruir los datos. Existe para que la baja no sea
    # instantánea: un offboarding por error necesita ventana de recuperación, y
    # un contrato normalmente obliga a conservar durante un plazo.
    datos_borrables_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_tenants_estado", "estado"),
        Index("ix_tenants_plan", "plan", "tier"),
    )

    @property
    def puede_escribir(self) -> bool:
        return self.estado == "activo"

    @property
    def puede_leer(self) -> bool:
        return self.estado in ("activo", "solo_lectura")


class UnidadNegocio(Base, TimestampMixin):
    """Sub-tenant dentro de un tenant (CRM-00.01.03.08).

    Divide un tenant en unidades con visibilidad acotada —delegaciones, marcas,
    países— sin la complejidad de dar de alta tenants separados: comparten
    usuarios, configuración heredable y catálogos.

    La diferencia con un tenant hijo es importante y se pregunta siempre: dos
    tenants **no** comparten nada y su aislamiento es duro; dos unidades de
    negocio comparten configuración y catálogos, y su separación es una regla de
    visibilidad, no una frontera de seguridad.
    """

    __tablename__ = "unidades_negocio"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    padre_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("unidades_negocio.id"), nullable=True
    )
    codigo: Mapped[str] = mapped_column(String(60), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "codigo", name="uq_unidad_codigo"),)


class Plan(Base, TimestampMixin):
    """Plan comercial: qué capacidades activa y con qué topes.

    Las capacidades se declaran aquí, en datos, y no con condicionales en el
    código (CRM-00.01.04.05). La diferencia se nota cuando comercial inventa un
    plan nuevo un viernes: con datos es una fila, con condicionales es un
    despliegue.
    """

    __tablename__ = "planes"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    codigo: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Capacidades activas: {"ia_generativa": true, "portal_cliente": false}
    capacidades: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Topes que sobrescriben los del entorno: {"quota_registros": 500000}
    cuotas: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class FeatureFlag(Base, TimestampMixin):
    """Interruptor de funcionalidad por tenant, usuario o porcentaje (CRM-00.01.04.04).

    Distinto de una capacidad de plan, aunque se parezcan: la capacidad es
    **comercial** (lo que el cliente ha contratado) y el flag es **técnico** (si
    esa funcionalidad está lista para él). Mezclarlos lleva a activar algo a un
    cliente porque ha pagado, estando a medio terminar.
    """

    __tablename__ = "feature_flags"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    clave: Mapped[str] = mapped_column(String(120), nullable=False)
    # NULL = alcance global (todos los tenants).
    tenant_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Despliegue progresivo: 0-100. El reparto se hace por hash del tenant o del
    # usuario, no al azar, para que a un mismo usuario le toque siempre lo mismo
    # — si no, la funcionalidad le aparece y desaparece entre peticiones.
    porcentaje: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("clave", "tenant_id", "user_id", name="uq_flag_ambito"),)


class Consumo(Base):
    """Medición de consumo por tenant y periodo (CRM-00.01.06.07).

    Se guarda agregado por periodo, no evento a evento: un contador por llamada
    de API sería una tabla más grande que el propio CRM. Lo que se pierde es el
    detalle temporal fino; lo que se gana es que la medición no cueste más que
    lo medido.
    """

    __tablename__ = "consumo"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    metrica: Mapped[str] = mapped_column(String(80), nullable=False)
    # Periodo en el formato de su granularidad: `2026-09`, `2026-09-18`.
    periodo: Mapped[str] = mapped_column(String(20), nullable=False)
    valor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "metrica", "periodo", name="uq_consumo_periodo"),
        Index("ix_consumo_metrica", "tenant_id", "metrica", "periodo"),
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
from crmcore.datos.papelera import EntradaPapelera  # noqa: E402
from crmcore.datos.retencion import BloqueoLegal, PoliticaRetencion  # noqa: E402
from crmcore.security.byok import ClaveTenant  # noqa: E402

from services.tenancy.baja import CertificadoDestruccion, Exportacion  # noqa: E402
from services.tenancy.catalogos import (  # noqa: E402
    CalendarioLaboral,
    Festivo,
    Plantilla,
    TipoCambio,
)

__all__ = [
    "ClaveTenant",
    "CalendarioLaboral",
    "CertificadoDestruccion",
    "Consumo",
    "BloqueoLegal",
    "EntradaPapelera",
    "PoliticaRetencion",
    "Exportacion",
    "FeatureFlag",
    "Festivo",
    "Plan",
    "Plantilla",
    "Tenant",
    "TipoCambio",
    "UnidadNegocio",
]
