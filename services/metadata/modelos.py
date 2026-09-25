"""Modelo de datos del servicio de metadatos."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.ids import nuevo_id
from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column


class ObjetoDefinido(Base, TimestampMixin, SoftDeleteMixin):
    """Un objeto del modelo: estándar (extendido) o propio del tenant.

    Los estándar (`account`, `opportunity`) existen en el código y aquí solo se
    guardan sus extensiones. Los propios los crea el tenant enteros. Se guardan
    en la misma tabla a propósito: para un frontend headless no hay diferencia,
    y esa uniformidad es lo que hace que un objeto propio sea ciudadano de
    primera y no un apaño.
    """

    __tablename__ = "objetos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # Nombre de API: `account`, `proyecto_obra`. Inmutable una vez creado — es
    # lo que aparece en las URLs y en las integraciones de terceros.
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(200), nullable=False)
    etiqueta_plural: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # `estandar` = viene con el producto; `propio` = lo creó el tenant.
    origen: Mapped[str] = mapped_column(String(20), nullable=False, default="propio")
    icono: Mapped[str] = mapped_column(String(60), nullable=False, default="")

    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Si sus registros van a la papelera al borrarlos.
    papelera: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Máquina de estados del objeto (CRM-00.04.01.07): estados y transiciones
    # permitidas. Vacío = sin máquina.
    estados: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (UniqueConstraint("tenant_id", "nombre", name="uq_objeto_nombre"),)


class CampoDefinido(Base, TimestampMixin):
    """Un campo de un objeto (CRM-00.04.01.02)."""

    __tablename__ = "campos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    objeto_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("objetos.id", ondelete="CASCADE"), nullable=False
    )
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(200), nullable=False)
    ayuda: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # texto, texto_largo, numero, moneda, porcentaje, fecha, fecha_hora,
    # booleano, lista, lista_multiple, formula, lookup, geolocalizacion, json,
    # fichero, cifrado, email, telefono, url
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    obligatorio: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    unico: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Solo lectura desde la API: campos calculados o rellenados por el sistema.
    solo_lectura: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    valor_defecto: Mapped[Any] = mapped_column(JSONB, nullable=True)

    # Restricciones por tipo: longitudes, rangos, patrón, decimales, opciones de
    # lista, objeto destino de un lookup. En JSONB porque cada tipo tiene las
    # suyas y una columna por restricción daría una tabla con treinta columnas
    # nulas.
    restricciones: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Clasificación de sensibilidad (CRM-07.03.01.05): publico | interno |
    # confidencial | personal | especial. De aquí salen el enmascaramiento por
    # rol y el mapa de datos personales.
    sensibilidad: Mapped[str] = mapped_column(String(20), nullable=False, default="interno")
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Un campo deprecado sigue leyéndose pero no se ofrece para escribir: es lo
    # que permite retirar un campo sin romper integraciones que aún lo mandan.
    deprecado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("objeto_id", "nombre", name="uq_campo_nombre"),
        Index("ix_campos_objeto", "tenant_id", "objeto_id", "activo"),
    )


class ReglaValidacion(Base, TimestampMixin):
    """Validación declarativa a nivel de registro o de transición.

    Las de campo (obligatorio, rango, patrón) van en el propio campo. Aquí van
    las que cruzan campos —«la fecha de cierre no puede ser anterior a la de
    alta»— y las de transición de estado.
    """

    __tablename__ = "reglas_validacion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    objeto_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("objetos.id", ondelete="CASCADE"), nullable=False
    )
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    # El mensaje que ve quien la incumple. Es obligatorio y se escribe al crear
    # la regla: un «validación 14 fallida» obliga a llamar a soporte.
    mensaje: Mapped[str] = mapped_column(Text, nullable=False)
    condiciones: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    combinacion: Mapped[str] = mapped_column(String(10), nullable=False, default="todas")
    # Cuándo se evalúa: siempre | crear | actualizar | transicion
    momento: Mapped[str] = mapped_column(String(20), nullable=False, default="siempre")
    # Para las de transición: desde qué estado a cuál.
    estado_desde: Mapped[str | None] = mapped_column(String(60), nullable=True)
    estado_hasta: Mapped[str | None] = mapped_column(String(60), nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("objeto_id", "nombre", name="uq_regla_nombre"),)


class Layout(Base, TimestampMixin):
    """Disposición de campos para un objeto y un perfil (CRM-00.02.03.06).

    Vive en el backend y no en cada frontend a propósito: es lo que permite que
    la web, el móvil y el portal enseñen lo mismo sin coordinarse, y que
    cambiar un formulario sea configuración y no un despliegue de tres clientes.
    """

    __tablename__ = "layouts"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    objeto_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("objetos.id", ondelete="CASCADE"), nullable=False
    )
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    # A qué perfil se aplica. Vacío = a todos.
    rol: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Secciones con sus campos y su disposición.
    secciones: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    es_defecto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (UniqueConstraint("objeto_id", "nombre", name="uq_layout_nombre"),)


class ValorLista(Base, TimestampMixin):
    """Valor de una lista maestra, compartida entre objetos (CRM-07.01.01.03).

    Las listas globales (sectores, países, motivos de pérdida) se definen una
    vez y las usan varios campos. Sin esto, cada campo de tipo lista guardaría
    sus opciones y cambiar «motivo de pérdida» obligaría a tocarlas todas.
    """

    __tablename__ = "valores_lista"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    lista: Mapped[str] = mapped_column(String(80), nullable=False)
    valor: Mapped[str] = mapped_column(String(120), nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(200), nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Valores extra por valor (color, si es terminal, a qué mapea en el ERP).
    extra: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "lista", "valor", name="uq_valor_lista"),
        Index("ix_valores_lista", "tenant_id", "lista", "activo"),
    )


# ── Tablas declaradas en otro módulo de este mismo servicio ───────────────
#
# `modelos.py` es lo que leen el generador de migraciones y la fixture de
# pruebas. Un modelo que no aparezca aquí sencillamente no se migra.
from crmcore.authz.politicas import PoliticaAbac, VersionPoliticaAbac  # noqa: E402

# La papelera de este servicio. Su router se monta —`/<servicio>/papelera`— y sin
# la tabla la pantalla devolvía 500: `relation "papelera" does not exist`. El
# borrado es lógico y cada servicio guarda la suya en su esquema, que es lo que
# impide que uno lea las tablas de otro.
from crmcore.datos.papelera import EntradaPapelera  # noqa: E402,F401
from crmcore.metamodelo import EsquemaTenant, UsoCampo  # noqa: E402
from crmcore.runtime.versiones import VersionAjuste  # noqa: E402
from crmcore.security.byok import ClaveTenant  # noqa: E402

from services.metadata.modulos import (  # noqa: E402
    ElementoModulo,
    ModuloInstalado,
    ModuloPublicado,
)
from services.metadata.publicacion import PublicacionEsquema  # noqa: E402
from services.metadata.relaciones import RelacionDefinida  # noqa: E402

__all__ = [
    "ElementoModulo",
    "ModuloInstalado",
    "ModuloPublicado",
    "PublicacionEsquema",
    "UsoCampo",
    "EsquemaTenant",
    "VersionAjuste",
    "CambioEsquema",
    "TipoRegistro",
    "PoliticaAbac",
    "VersionPoliticaAbac",
    "ClaveTenant",
    "CampoDefinido",
    "Layout",
    "ObjetoDefinido",
    "RelacionDefinida",
    "ReglaValidacion",
    "ValorLista",
]

# Empaquetado, promoción entre entornos y drift (CRM-07.02.01.03, .04, .06, .07).
# Números de campo del contrato protobuf (CRM-00.02.01.03).
from services.metadata.contrato_rpc import ContratoRpc  # noqa: E402,F401
from services.metadata.entornos import (  # noqa: E402,F401
    DespliegueConfiguracion,
    PaqueteConfiguracion,
)
from services.metadata.gobierno import CambioEsquema, TipoRegistro  # noqa: E402
