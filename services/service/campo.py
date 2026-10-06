"""Servicio de campo: órdenes, rutas, repuestos, preventivo y partes
(CRM-04.04.01.01 a CRM-04.04.01.06).

El trabajo de campo tiene una particularidad que lo cambia todo: **quien ejecuta
no está delante de un ordenador, está subido a una máquina, a veces sin
cobertura, y el cliente le está mirando**. Un sistema que le estorbe no se usa: se
apunta en una libreta y se pasa el viernes, y entonces el CRM no tiene nada.

De ahí las decisiones que se repiten en todo el módulo:

**Al técnico no se le bloquea, se le marca.** Consumir una pieza que el sistema
dice que no está en la furgoneta se registra igual y se señala: la pieza se ha
usado de verdad, y lo que está mal es el stock. Rechazarlo hace que la pieza se
monte y no se apunte, con lo que se pierden las dos cosas.

**Lo que se planifica se explica.** Una ruta que asigna sin decir por qué se
rehace a mano en cuanto una asignación chirría, y a partir de ahí el planificador
deja de usarse.

**Lo que no se puede medir se dice.** Sin coordenadas no hay optimización de ruta:
se devuelve el orden que se pueda y se declara que no está optimizado, en vez de
presentar como óptimo lo que es el orden de la lista.

**El móvil trabaja sin red y sincroniza después.** Eso obliga a tres cosas que no
son opcionales: identificadores generados en el dispositivo para que reenviar no
duplique, el reloj del móvil guardado aparte del del servidor —el del móvil miente
y aun así es el que dice cuándo se hizo el trabajo—, y los conflictos **se
devuelven, no se resuelven solos**.

**El preventivo va por fecha y por uso.** Un plan que solo sabe de fechas revisa
una máquina parada y deja pasar la que trabaja a tres turnos.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from crmcore.runtime import settings as rt
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
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from services.service import activos as act

logger = get_logger(__name__)

CENTIMO = Decimal("0.01")
RADIO_TIERRA_M = 6_371_000.0

# Estados de una orden de trabajo.
#
#   borrador     se está preparando; no sale en ninguna ruta
#   planificada  tiene fecha, no tiene técnico
#   asignada     tiene técnico y cita
#   en_curso     el técnico ha empezado
#   pausada      interrumpida, con motivo
#   completada   trabajo hecho, pendiente de revisar y facturar
#   cerrada      revisada; ya no se toca
#   cancelada    no se hará, con motivo
ESTADOS = (
    "borrador",
    "planificada",
    "asignada",
    "en_curso",
    "pausada",
    "completada",
    "cerrada",
    "cancelada",
)

# Qué se apunta en una línea de la orden. Cerrada porque cada tipo se factura y
# se cubre distinto, y un tipo nuevo escrito a mano se quedaría fuera de los dos
# cálculos sin que nadie lo note.
TIPOS_LINEA = ("material", "tiempo", "desplazamiento", "otro")

# Movimientos del almacén móvil, con el mismo vocabulario que el inventario de
# contecpos: reinventarlo daría dos formas de decir lo mismo cuando haya que
# cuadrar con el almacén central.
TIPOS_MOVIMIENTO = ("carga", "consumo", "devolucion", "ajuste", "merma")


class Tecnico(Base, TimestampMixin, SoftDeleteMixin):
    """Quién puede ir, con qué sabe hacer y por dónde se mueve
    (CRM-04.04.01.02).

    Las competencias se guardan con **nivel**, no como etiquetas: «sabe de
    frigorífico» y «está certificado en gas fluorado» no son lo mismo, y mandar al
    primero a un trabajo que exige lo segundo es un viaje perdido y, a veces, una
    sanción.
    """

    __tablename__ = "tecnicos_campo"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Zonas que cubre. Vacío = cualquiera: un técnico sin zona no se excluye de
    # todo, se considera disponible en todas — al revés, un dato que falta dejaría
    # a alguien sin trabajo asignado y nadie sabría por qué.
    zonas: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    competencias: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Punto de salida: de dónde arranca la ruta. Sin él, la primera visita del día
    # sale gratis en el cálculo y la ruta parece media hora más corta de lo que es.
    base_latitud: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    base_longitud: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    minutos_jornada: Mapped[int] = mapped_column(Integer, nullable=False, default=480)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "usuario_id", name="uq_tecnico_usuario"),
        Index("ix_tecnicos_activos", "tenant_id", "activo"),
    )


class OrdenTrabajo(Base, TimestampMixin, SoftDeleteMixin):
    """Un trabajo que hay que hacer en casa del cliente (CRM-04.04.01.01)."""

    __tablename__ = "ordenes_trabajo"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    codigo: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # correctivo | preventivo | instalacion | retirada | inspeccion
    tipo: Mapped[str] = mapped_column(String(30), nullable=False, default="correctivo")
    titulo: Mapped[str] = mapped_column(String(300), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    caso_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    activo_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    # El plan de mantenimiento del que sale esta orden.
    plan_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, info={"referencia": "plan_preventivo"}
    )

    direccion: Mapped[str] = mapped_column(
        String(300), nullable=False, default="", info={"sensibilidad": "personal"}
    )
    latitud: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitud: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    zona: Mapped[str | None] = mapped_column(String(80), nullable=True)

    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="borrador", index=True)
    prioridad: Mapped[str] = mapped_column(String(20), nullable=False, default="media")
    competencias: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    duracion_estimada_min: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    # Ventana comprometida con el cliente. Es distinta de la cita: la ventana es
    # lo que se le prometió y la cita es lo que se planificó dentro de ella.
    ventana_desde: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ventana_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tecnico_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    cita_desde: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cita_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Por qué se le asignó a este y no a otro. Una asignación sin explicación se
    # rehace a mano en cuanto chirría, y el planificador deja de usarse.
    motivo_asignacion: Mapped[str] = mapped_column(Text, nullable=False, default="")

    iniciada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cerrada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motivo_estado: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Firma del cliente. Se guarda **qué** firmó —el parte y su huella—, no solo
    # que firmó: una conformidad que no dice sobre qué no sirve para nada si
    # después se discute lo que se hizo.
    firmado_por: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    firma_documento_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    firma_huella: Mapped[str | None] = mapped_column(String(64), nullable=True)
    firmado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    conforme: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    motivo_no_conforme: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("tenant_id", "codigo", name="uq_orden_codigo"),
        Index("ix_ordenes_agenda", "tenant_id", "tecnico_id", "cita_desde"),
        Index("ix_ordenes_pendientes", "tenant_id", "estado", "prioridad"),
    )


class LineaOrden(Base, TimestampMixin):
    """Material, horas y desplazamiento de una orden (CRM-04.04.01.01)."""

    __tablename__ = "lineas_orden_trabajo"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    orden_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("ordenes_trabajo.id", ondelete="CASCADE"), nullable=False
    )
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="material")
    repuesto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    concepto: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    cantidad: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, default=0)
    unidad: Mapped[str] = mapped_column(String(20), nullable=False, default="ud")
    precio: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    tecnico_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    desde: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Facturable y cubierto son cosas distintas: una línea puede ser facturable y
    # estar cubierta por garantía —entonces la paga el fabricante, no el cliente—.
    # Con un solo campo, la reclamación al fabricante no se puede sacar.
    facturable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cubierto_garantia: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    garantia_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    nota_cobertura: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (Index("ix_lineas_orden", "tenant_id", "orden_id", "tipo"),)


class ParteTrabajo(Base, TimestampMixin):
    """Lo que se hizo, con checklist y evidencias (CRM-04.04.01.06).

    Las fotos se guardan como **referencias** al gestor documental, no como
    binarios en esta tabla: cinco fotos por visita y veinte visitas diarias
    convierten el esquema del servicio en un almacén de imágenes sin retención ni
    antivirus.
    """

    __tablename__ = "partes_trabajo"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    orden_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("ordenes_trabajo.id", ondelete="CASCADE"), nullable=False
    )
    resumen: Mapped[str] = mapped_column(Text, nullable=False, default="")
    diagnostico: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Cada ítem: {clave, texto, obligatorio, resultado: ok|ko|na, nota}
    checklist: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    evidencias: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Huella del contenido en el momento de firmar. Es lo que permite demostrar
    # que lo firmado es esto y no lo que se editó después.
    huella: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bloqueado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (Index("ix_partes_orden", "tenant_id", "orden_id"),)


class Repuesto(Base, TimestampMixin, SoftDeleteMixin):
    """Una pieza que se lleva en la furgoneta (CRM-04.04.01.04)."""

    __tablename__ = "repuestos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    unidad: Mapped[str] = mapped_column(String(20), nullable=False, default="ud")
    producto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    coste: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "sku", name="uq_repuesto_sku"),)


class StockFurgoneta(Base, TimestampMixin):
    """Lo que hay —o debería haber— en el almacén móvil de cada técnico."""

    __tablename__ = "stock_furgoneta"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    tecnico_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tecnicos_campo.id", ondelete="CASCADE"), nullable=False
    )
    repuesto_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("repuestos.id", ondelete="CASCADE"), nullable=False
    )
    cantidad: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, default=0)
    # Mínimo de reposición: por debajo, hay que cargar. Es lo que convierte el
    # stock de furgoneta en algo accionable en vez de en un inventario que se mira
    # el día que falta una pieza.
    minimo: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("tenant_id", "tecnico_id", "repuesto_id", name="uq_stock_furgoneta"),
        Index("ix_stock_furgoneta", "tenant_id", "tecnico_id"),
    )


class MovimientoRepuesto(Base):
    """Cada entrada y salida del almacén móvil, con su porqué."""

    __tablename__ = "movimientos_repuesto"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    tecnico_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    repuesto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    cantidad: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    orden_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    motivo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Se apunta si el movimiento dejó el stock en negativo. No se impide: la pieza
    # se ha usado de verdad y lo que está mal es el stock.
    dejo_negativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_movimientos_repuesto", "tenant_id", "tecnico_id", "created_at"),)


class PlanPreventivo(Base, TimestampMixin):
    """Mantenimiento planificado por tiempo y por uso (CRM-04.04.01.05)."""

    __tablename__ = "planes_preventivos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    activo_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("activos_instalados.id", ondelete="CASCADE"),
        nullable=False,
    )
    cada_dias: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # …o cada tantas unidades de uso. Los dos a la vez: lo que antes llegue.
    cada_contador: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    duracion_min: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    competencias: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    checklist: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Cuántos días antes se puede generar la orden. Sin antelación, la orden nace
    # el día que vence y ya se llega tarde a planificarla.
    antelacion_dias: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    ultima_ejecucion: Mapped[date | None] = mapped_column(Date, nullable=True)
    ultimo_contador: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    proxima_fecha: Mapped[date | None] = mapped_column(Date, nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (Index("ix_planes_preventivos", "tenant_id", "activo", "proxima_fecha"),)


class OperacionSincronizada(Base):
    """Lo que ya se aplicó desde un dispositivo (CRM-04.04.01.03).

    Es la tabla que hace idempotente la sincronización: el móvil genera el
    identificador, y reenviar el mismo lote —porque se cortó la red a mitad— no
    duplica nada. Sin esto, el técnico que sincroniza dos veces consume la pieza
    dos veces.
    """

    __tablename__ = "operaciones_sincronizadas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # Identificador generado en el dispositivo, antes de haber red.
    id_cliente: Mapped[str] = mapped_column(String(80), nullable=False)
    dispositivo: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    tipo: Mapped[str] = mapped_column(String(40), nullable=False)
    orden_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    resultado: Mapped[str] = mapped_column(String(20), nullable=False, default="aplicada")
    detalle: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # El reloj del móvil y el del servidor, por separado. El del móvil miente
    # —zona horaria mal, hora cambiada a mano— y aun así es el único que sabe
    # cuándo se hizo el trabajo. Guardar solo uno pierde información en los dos
    # sentidos.
    capturado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recibido_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "id_cliente", name="uq_operacion_sincronizada"),
        Index("ix_operaciones_sync", "tenant_id", "orden_id", "recibido_at"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _dia_del_cliente(momento: datetime, db: Any = None) -> date:
    """De qué día es este instante **donde está el cliente**.

    No es lo mismo que `momento.date()`: eso lo resuelve en la zona que traiga
    el instante, y lo que vuelve de un `timestamptz` viene en la de la conexión.
    Un instante es absoluto; de qué día forma parte, no.
    """
    from crmcore.fechas import zona_del_tenant

    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(zona_del_tenant(db)).date()


def _hoy(db: Any = None) -> date:
    """El día de hoy **donde está el cliente**, si hay sesión con la que saberlo.

    Sin sesión cae a UTC, que es lo que hacía antes: no empeora nada y deja
    claro dónde falta el dato. Quien la tenga a mano está obligado a pasarla —
    hay un gate que lo mira—, porque entre medianoche y las dos de la mañana en
    Madrid la respuesta sin sesión es **la de ayer**.
    """
    from crmcore.fechas import hoy as _hoy_del_cliente

    return _hoy_del_cliente(db)


def _redondear(valor: Decimal) -> Decimal:
    return Decimal(valor).quantize(CENTIMO, rounding=ROUND_HALF_UP)


def _huella(datos: Any) -> str:
    import hashlib
    import json

    return hashlib.sha256(
        json.dumps(datos, sort_keys=True, default=str, ensure_ascii=False).encode()
    ).hexdigest()


def distancia_m(
    lat1: Decimal | float | None,
    lon1: Decimal | float | None,
    lat2: Decimal | float | None,
    lon2: Decimal | float | None,
) -> float | None:
    """Distancia en línea recta entre dos puntos, en metros.

    **En línea recta, y se dice.** No es la distancia por carretera: sin un
    servicio de rutas, presentarla como tal daría estimaciones cortas justo donde
    más duelen —montaña, río de por medio, polígono con una sola entrada—. Aquí
    sirve para **ordenar** visitas, que es para lo que vale sin mentir.
    """
    if None in (lat1, lon1, lat2, lon2):
        return None
    f1, g1, f2, g2 = (math.radians(float(v)) for v in (lat1, lon1, lat2, lon2))  # type: ignore[arg-type]
    a = math.sin((f2 - f1) / 2) ** 2 + math.cos(f1) * math.cos(f2) * math.sin((g2 - g1) / 2) ** 2
    return 2 * RADIO_TIERRA_M * math.asin(min(1.0, math.sqrt(a)))


def _orden(db: Session, tenant_id: UUID, orden_id: UUID) -> OrdenTrabajo:
    fila = db.get(OrdenTrabajo, orden_id)
    if fila is None or fila.tenant_id != tenant_id:
        raise NoEncontrado("La orden no existe", error_code="campo.orden_no_encontrada")
    return fila


def _tecnico(db: Session, tenant_id: UUID, tecnico_id: UUID) -> Tecnico:
    fila = db.get(Tecnico, tecnico_id)
    if fila is None or fila.tenant_id != tenant_id:
        raise NoEncontrado("El técnico no existe", error_code="campo.tecnico_no_encontrado")
    return fila


# ── Órdenes de trabajo (CRM-04.04.01.01) ──────────────────────────────────


def crear_orden(
    uow: UnidadDeTrabajo,
    *,
    titulo: str,
    tipo: str = "correctivo",
    descripcion: str = "",
    caso_id: UUID | None = None,
    activo_id: UUID | None = None,
    cuenta_id: UUID | None = None,
    direccion: str = "",
    latitud: Decimal | None = None,
    longitud: Decimal | None = None,
    zona: str | None = None,
    prioridad: str = "media",
    competencias: list[str] | None = None,
    duracion_estimada_min: int = 60,
    ventana_desde: datetime | None = None,
    ventana_hasta: datetime | None = None,
    plan_id: UUID | None = None,
) -> tuple[OrdenTrabajo, list[str]]:
    """Crea una orden. Nace en borrador y devuelve lo que no se podrá hacer.

    Los avisos no son decorativos: sin coordenadas la orden no entra en la
    optimización de ruta, y sin competencias declaradas puede ir cualquiera —que
    a veces está bien y a veces es un viaje perdido—.
    """
    avisos: list[str] = []
    if latitud is None or longitud is None:
        avisos.append(
            "Sin coordenadas: esta orden no se podrá ordenar por cercanía y saldrá "
            "al final de la ruta."
        )
    if not (competencias or []):
        avisos.append(
            "Sin competencias declaradas: le puede tocar a cualquiera, incluido "
            "alguien que no pueda ejecutarla."
        )
    if activo_id is not None:
        activo = act.obtener(uow.db, uow.tenant_id, activo_id)
        if cuenta_id is None:
            cuenta_id = activo.cuenta_id
        if not direccion:
            direccion = activo.ubicacion
        if latitud is None and activo.latitud is not None:
            latitud, longitud = activo.latitud, activo.longitud

    fila = OrdenTrabajo(
        tenant_id=uow.tenant_id,
        titulo=titulo.strip(),
        tipo=tipo,
        descripcion=descripcion,
        caso_id=caso_id,
        activo_id=activo_id,
        cuenta_id=cuenta_id,
        plan_id=plan_id,
        direccion=direccion,
        latitud=latitud,
        longitud=longitud,
        zona=zona,
        prioridad=prioridad,
        competencias=list(competencias or []),
        duracion_estimada_min=duracion_estimada_min,
        ventana_desde=ventana_desde,
        ventana_hasta=ventana_hasta,
    )
    uow.db.add(fila)
    uow.db.flush()
    uow.emitir(
        "workorder.created",
        subject=("orden_trabajo", fila.id),
        data={
            "orden_id": str(fila.id),
            "tipo": fila.tipo,
            "activo_id": str(activo_id) if activo_id else None,
        },
    )
    return fila, avisos


def _competencias_de(tecnico: Tecnico) -> dict[str, int]:
    salida: dict[str, int] = {}
    for c in tecnico.competencias or []:
        if isinstance(c, dict) and c.get("clave"):
            try:
                salida[str(c["clave"])] = int(c.get("nivel", 1))
            except (TypeError, ValueError):
                salida[str(c["clave"])] = 1
        elif isinstance(c, str):
            salida[c] = 1
    return salida


def candidatos(db: Session, tenant_id: UUID, orden_id: UUID) -> dict[str, Any]:
    """Quién puede hacer esta orden, y **por qué no puede el resto**.

    La lista de descartados es la mitad del valor: cuando el planificador dice
    «nadie disponible», lo que hace falta saber es si es por competencia, por zona
    o porque están todos de baja — y son tres decisiones distintas.
    """
    orden = _orden(db, tenant_id, orden_id)
    requeridas = {str(c) for c in (orden.competencias or [])}
    tecnicos = db.execute(select(Tecnico).where(Tecnico.tenant_id == tenant_id)).scalars().all()
    aptos: list[dict[str, Any]] = []
    descartados: list[dict[str, Any]] = []
    for tecnico in tecnicos:
        if not tecnico.activo:
            descartados.append({"tecnico_id": str(tecnico.id), "porque": "no está activo"})
            continue
        tiene = _competencias_de(tecnico)
        faltan = sorted(requeridas - set(tiene))
        if faltan:
            descartados.append(
                {
                    "tecnico_id": str(tecnico.id),
                    "porque": f"le faltan competencias: {', '.join(faltan)}",
                }
            )
            continue
        # Un técnico sin zonas cubre todas: un dato que falta no puede dejar a
        # alguien sin trabajo sin que nadie sepa por qué.
        zonas = [str(z) for z in (tecnico.zonas or [])]
        if orden.zona and zonas and orden.zona not in zonas:
            descartados.append(
                {"tecnico_id": str(tecnico.id), "porque": f"no cubre la zona {orden.zona}"}
            )
            continue
        distancia = distancia_m(
            tecnico.base_latitud, tecnico.base_longitud, orden.latitud, orden.longitud
        )
        aptos.append(
            {
                "tecnico_id": str(tecnico.id),
                "nombre": tecnico.nombre,
                "distancia_m": round(distancia) if distancia is not None else None,
                "cubre_zona": bool(not zonas or (orden.zona and orden.zona in zonas)),
            }
        )
    aptos.sort(key=lambda t: (t["distancia_m"] is None, t["distancia_m"] or 0))
    return {
        "orden_id": str(orden.id),
        "competencias_requeridas": sorted(requeridas),
        "aptos": aptos,
        "descartados": descartados,
        # Distinguir «no hay nadie» de «no se ha podido medir» evita que alguien
        # concluya que falta plantilla cuando lo que falta son competencias
        # declaradas.
        "hay_candidatos": bool(aptos),
    }


def asignar(
    uow: UnidadDeTrabajo,
    orden_id: UUID,
    *,
    tecnico_id: UUID,
    cita_desde: datetime | None = None,
    cita_hasta: datetime | None = None,
    forzar: bool = False,
    motivo: str = "",
) -> tuple[OrdenTrabajo, list[str]]:
    """Asigna la orden a un técnico y le pone cita.

    Si al técnico le faltan competencias **se avisa y se puede forzar con
    motivo**, no se bloquea: en un día malo, mandar al que casi puede es mejor que
    no mandar a nadie, pero tiene que quedar escrito que se hizo a sabiendas.
    """
    orden = _orden(uow.db, uow.tenant_id, orden_id)
    tecnico = _tecnico(uow.db, uow.tenant_id, tecnico_id)
    if orden.estado in ("cerrada", "cancelada"):
        raise Conflicto(
            "Esa orden ya está cerrada o cancelada",
            error_code="campo.orden_cerrada",
            detalle={"estado": orden.estado},
        )

    avisos: list[str] = []
    faltan = sorted({str(c) for c in (orden.competencias or [])} - set(_competencias_de(tecnico)))
    if faltan:
        if not forzar:
            raise Conflicto(
                "A ese técnico le faltan competencias para esta orden",
                error_code="campo.competencias_insuficientes",
                detalle={"faltan": faltan},
            )
        if not motivo.strip():
            raise ErrorValidacion(
                "Forzar una asignación sin competencias exige motivo.",
                error_code="campo.motivo_obligatorio",
            )
        avisos.append(f"Asignado sin las competencias {', '.join(faltan)}: {motivo.strip()}")

    if cita_desde and orden.ventana_desde and cita_desde < orden.ventana_desde:
        avisos.append("La cita cae antes de la ventana comprometida con el cliente.")
    if cita_hasta and orden.ventana_hasta and cita_hasta > orden.ventana_hasta:
        avisos.append("La cita se sale de la ventana comprometida con el cliente.")

    if cita_desde and cita_hasta:
        solapes = (
            uow.db.execute(
                select(OrdenTrabajo).where(
                    OrdenTrabajo.tenant_id == uow.tenant_id,
                    OrdenTrabajo.tecnico_id == tecnico_id,
                    OrdenTrabajo.id != orden.id,
                    OrdenTrabajo.estado.in_(("asignada", "en_curso", "pausada")),
                    OrdenTrabajo.cita_desde < cita_hasta,
                    OrdenTrabajo.cita_hasta > cita_desde,
                )
            )
            .scalars()
            .all()
        )
        if solapes:
            # Se avisa y se asigna: en campo, dos citas solapadas a veces son un
            # trabajo de diez minutos metido entre dos. Bloquearlo obliga a
            # planificar fuera del sistema.
            avisos.append(f"Se solapa con {len(solapes)} cita(s) ya asignadas a ese técnico.")

    orden.tecnico_id = tecnico_id
    orden.cita_desde = cita_desde
    orden.cita_hasta = cita_hasta
    orden.estado = "asignada" if cita_desde else "planificada"
    orden.motivo_asignacion = motivo.strip() or orden.motivo_asignacion
    uow.db.flush()
    registrar(
        uow.db,
        accion="campo.orden_asignada",
        objeto="orden_trabajo",
        objeto_id=orden.id,
        datos={"tecnico_id": str(tecnico_id), "avisos": avisos, "forzado": bool(faltan)},
        tenant_id=uow.tenant_id,
    )
    uow.emitir(
        "workorder.assigned",
        subject=("orden_trabajo", orden.id),
        data={"orden_id": str(orden.id), "tecnico_id": str(tecnico_id)},
    )
    return orden, avisos


def anotar_linea(
    uow: UnidadDeTrabajo,
    orden_id: UUID,
    *,
    tipo: str,
    concepto: str = "",
    cantidad: Decimal = Decimal(1),
    unidad: str = "ud",
    repuesto_id: UUID | None = None,
    precio: Decimal | None = None,
    tecnico_id: UUID | None = None,
    desde: datetime | None = None,
    hasta: datetime | None = None,
    facturable: bool = True,
    consumir_stock: bool = True,
) -> tuple[LineaOrden, list[str]]:
    """Apunta material, tiempo o desplazamiento en la orden.

    Cuando es material y hay técnico, **descuenta de la furgoneta**: si el
    consumo no toca el stock, el stock no significa nada a los dos días.

    Y se calcula la **cobertura de garantía** en el momento de apuntar, no al
    facturar: el técnico tiene que poder decirle al cliente ahí mismo si eso lo
    paga él.
    """
    if tipo not in TIPOS_LINEA:
        raise ErrorValidacion(
            f"Tipo de línea «{tipo}» no válido.",
            error_code="campo.tipo_linea_no_valido",
            detalle={"validos": list(TIPOS_LINEA)},
        )
    orden = _orden(uow.db, uow.tenant_id, orden_id)
    if orden.estado in ("cerrada", "cancelada"):
        raise Conflicto(
            "No se apunta trabajo en una orden cerrada",
            error_code="campo.orden_cerrada",
            detalle={"estado": orden.estado},
        )
    avisos: list[str] = []

    if tipo == "tiempo" and desde and hasta and hasta <= desde:
        raise ErrorValidacion(
            "El tramo de tiempo acaba antes de empezar.", error_code="campo.tramo_invalido"
        )

    cubierto: bool | None = None
    garantia_id: UUID | None = None
    nota = ""
    if orden.activo_id:
        concepto_garantia = {
            "material": "piezas",
            "tiempo": "mano_obra",
            "desplazamiento": "desplazamiento",
        }.get(tipo)
        if concepto_garantia:
            estado = act.cobertura_de(
                uow.db, uow.tenant_id, orden.activo_id, concepto=concepto_garantia
            )
            nota = str(estado.get("motivo") or "")
            if estado.get("concluyente"):
                cubierto = bool(estado.get("cubierto"))
                garantia_id = (
                    UUID(str(estado["garantia_id"])) if estado.get("garantia_id") else None
                )
            else:
                # Sin garantías registradas no se decide: se avisa. Marcarlo como
                # no cubierto factura al cliente que sí lo estaba.
                avisos.append(nota)

    fila = LineaOrden(
        tenant_id=uow.tenant_id,
        orden_id=orden.id,
        tipo=tipo,
        concepto=concepto.strip(),
        cantidad=Decimal(cantidad),
        unidad=unidad,
        repuesto_id=repuesto_id,
        precio=precio,
        tecnico_id=tecnico_id or orden.tecnico_id,
        desde=desde,
        hasta=hasta,
        facturable=facturable,
        cubierto_garantia=cubierto,
        garantia_id=garantia_id,
        nota_cobertura=nota,
    )
    uow.db.add(fila)
    uow.db.flush()

    if tipo == "material" and repuesto_id and consumir_stock and (tecnico_id or orden.tecnico_id):
        movimiento = mover_repuesto(
            uow,
            tecnico_id=tecnico_id or orden.tecnico_id,  # type: ignore[arg-type]
            repuesto_id=repuesto_id,
            tipo="consumo",
            cantidad=Decimal(cantidad),
            orden_id=orden.id,
            motivo=concepto,
        )
        if movimiento["dejo_negativo"]:
            avisos.append(movimiento["aviso"])
    return fila, avisos


def iniciar(
    uow: UnidadDeTrabajo, orden_id: UUID, *, cuando: datetime | None = None
) -> OrdenTrabajo:
    orden = _orden(uow.db, uow.tenant_id, orden_id)
    if orden.tecnico_id is None:
        raise Conflicto(
            "Una orden sin técnico no la empieza nadie",
            error_code="campo.sin_tecnico",
        )
    orden.estado = "en_curso"
    orden.iniciada_at = cuando or _ahora()
    return orden


def pausar(uow: UnidadDeTrabajo, orden_id: UUID, *, motivo: str) -> OrdenTrabajo:
    """Pausa la orden. **Con motivo**: «esperando pieza» y «el cliente no estaba»
    son problemas distintos y se corrigen distinto."""
    if not motivo.strip():
        raise ErrorValidacion(
            "Pausar exige motivo: sin él, una orden parada tres semanas no dice si "
            "falta una pieza, falta el cliente o falta alguien que la retome.",
            error_code="campo.motivo_obligatorio",
        )
    orden = _orden(uow.db, uow.tenant_id, orden_id)
    orden.estado = "pausada"
    orden.motivo_estado = motivo.strip()
    return orden


def completar(
    uow: UnidadDeTrabajo,
    orden_id: UUID,
    *,
    resumen: str = "",
    diagnostico: str = "",
    checklist: list[dict[str, Any]] | None = None,
    evidencias: list[dict[str, Any]] | None = None,
    cuando: datetime | None = None,
    forzar: bool = False,
) -> tuple[OrdenTrabajo, dict[str, Any]]:
    """Cierra el trabajo y deja el parte (CRM-04.04.01.06).

    Un checklist con ítems **obligatorios sin responder** no cierra, salvo que se
    fuerce: un checklist que se puede dejar a medias es un checklist que se deja a
    medias, y entonces no vale ni como control ni como prueba.

    Al completar se escribe el historial del activo — en el momento, no
    reconstruido después (CRM-04.04.02.04).
    """
    orden = _orden(uow.db, uow.tenant_id, orden_id)
    if orden.estado in ("cerrada", "cancelada"):
        raise Conflicto(
            "Esa orden ya está cerrada",
            error_code="campo.orden_cerrada",
            detalle={"estado": orden.estado},
        )
    items = list(checklist or [])
    sin_responder = [
        str(i.get("clave") or i.get("texto") or "?")
        for i in items
        if i.get("obligatorio") and not i.get("resultado")
    ]
    if sin_responder and not forzar:
        raise Conflicto(
            "Quedan comprobaciones obligatorias sin responder",
            error_code="campo.checklist_incompleto",
            detalle={"sin_responder": sin_responder},
        )

    parte = uow.db.execute(
        select(ParteTrabajo).where(
            ParteTrabajo.tenant_id == uow.tenant_id, ParteTrabajo.orden_id == orden.id
        )
    ).scalar_one_or_none()
    if parte is None:
        parte = ParteTrabajo(tenant_id=uow.tenant_id, orden_id=orden.id)
        uow.db.add(parte)
    if parte.bloqueado:
        raise Conflicto(
            "El parte ya está firmado y no se modifica: lo que se firmó tiene que "
            "seguir diciendo lo mismo. Para corregir, se abre una orden nueva.",
            error_code="campo.parte_bloqueado",
        )
    parte.resumen = resumen
    parte.diagnostico = diagnostico
    parte.checklist = items
    parte.evidencias = list(evidencias or [])

    orden.estado = "completada"
    orden.completada_at = cuando or _ahora()
    uow.db.flush()

    ko = [i for i in items if i.get("resultado") == "ko"]
    if orden.activo_id:
        act.anotar(
            uow.db,
            tenant_id=uow.tenant_id,
            activo_id=orden.activo_id,
            tipo="intervencion",
            descripcion=resumen or orden.titulo,
            origen="orden_trabajo",
            origen_id=orden.id,
            usuario_id=orden.tecnico_id,
            datos={
                "tipo": orden.tipo,
                "diagnostico": diagnostico,
                "comprobaciones_ko": len(ko),
            },
            ocurrido_at=orden.completada_at,
        )
    uow.emitir(
        "workorder.completed",
        subject=("orden_trabajo", orden.id),
        data={
            "orden_id": str(orden.id),
            "activo_id": str(orden.activo_id) if orden.activo_id else None,
            "tipo": orden.tipo,
        },
    )
    return orden, {
        "sin_responder": sin_responder,
        "forzado": bool(sin_responder and forzar),
        "comprobaciones_ko": [str(i.get("clave") or i.get("texto") or "?") for i in ko],
        "sin_evidencias": not parte.evidencias,
    }


def firmar(
    uow: UnidadDeTrabajo,
    orden_id: UUID,
    *,
    firmado_por: str,
    conforme: bool = True,
    motivo_no_conforme: str = "",
    documento_id: UUID | None = None,
) -> dict[str, Any]:
    """Recoge la firma del cliente sobre el parte (CRM-04.04.01.01).

    Se guarda la **huella del parte firmado**. Una conformidad que no dice sobre
    qué se dio no sirve de nada el día que se discute lo que se hizo, y el parte
    se puede editar después; con la huella, editarlo se nota.

    Se admite firmar **no conforme**, con motivo: obligar a que el cliente firme
    conforme para poder cerrar hace que el técnico firme por él, y entonces
    ninguna firma vale nada.
    """
    orden = _orden(uow.db, uow.tenant_id, orden_id)
    if orden.estado not in ("completada", "en_curso"):
        raise Conflicto(
            "Se firma un trabajo hecho",
            error_code="campo.orden_no_completada",
            detalle={"estado": orden.estado},
        )
    if not conforme and not motivo_no_conforme.strip():
        raise ErrorValidacion(
            "Una no conformidad sin motivo no se puede resolver.",
            error_code="campo.motivo_obligatorio",
        )
    parte = uow.db.execute(
        select(ParteTrabajo).where(
            ParteTrabajo.tenant_id == uow.tenant_id, ParteTrabajo.orden_id == orden.id
        )
    ).scalar_one_or_none()
    if parte is None:
        raise Conflicto(
            "No hay parte que firmar: primero se completa el trabajo",
            error_code="campo.sin_parte",
        )

    huella = _huella(
        {
            "resumen": parte.resumen,
            "diagnostico": parte.diagnostico,
            "checklist": parte.checklist,
            "evidencias": parte.evidencias,
        }
    )
    parte.huella = huella
    parte.bloqueado = True
    orden.firmado_por = firmado_por.strip()
    orden.firma_documento_id = documento_id
    orden.firma_huella = huella
    orden.firmado_at = _ahora()
    orden.conforme = conforme
    orden.motivo_no_conforme = motivo_no_conforme.strip()
    uow.db.flush()
    registrar(
        uow.db,
        accion="campo.parte_firmado",
        objeto="orden_trabajo",
        objeto_id=orden.id,
        datos={"firmado_por": orden.firmado_por, "conforme": conforme, "huella": huella},
        tenant_id=uow.tenant_id,
    )
    return {
        "orden_id": str(orden.id),
        "huella": huella,
        "conforme": conforme,
        "firmado_at": orden.firmado_at.isoformat(),
    }


def cerrar(uow: UnidadDeTrabajo, orden_id: UUID, *, forzar: bool = False) -> OrdenTrabajo:
    """Cierra la orden tras revisarla. Sin firma solo se cierra forzando."""
    orden = _orden(uow.db, uow.tenant_id, orden_id)
    if orden.estado != "completada":
        raise Conflicto(
            "Solo se cierra lo completado",
            error_code="campo.orden_no_completada",
            detalle={"estado": orden.estado},
        )
    if orden.firmado_at is None and not forzar:
        raise Conflicto(
            "Falta la firma del cliente",
            error_code="campo.sin_firma",
        )
    orden.estado = "cerrada"
    orden.cerrada_at = _ahora()
    return orden


def resumen_orden(db: Session, tenant_id: UUID, orden_id: UUID) -> dict[str, Any]:
    """La orden con sus líneas, su reparto de cobertura y su parte."""
    orden = _orden(db, tenant_id, orden_id)
    lineas = (
        db.execute(
            select(LineaOrden).where(
                LineaOrden.tenant_id == tenant_id, LineaOrden.orden_id == orden_id
            )
        )
        .scalars()
        .all()
    )
    parte = db.execute(
        select(ParteTrabajo).where(
            ParteTrabajo.tenant_id == tenant_id, ParteTrabajo.orden_id == orden_id
        )
    ).scalar_one_or_none()

    minutos = 0
    for linea in lineas:
        if linea.tipo == "tiempo" and linea.desde and linea.hasta:
            minutos += int((linea.hasta - linea.desde).total_seconds() // 60)
    return {
        "id": str(orden.id),
        "codigo": orden.codigo,
        "titulo": orden.titulo,
        "tipo": orden.tipo,
        "estado": orden.estado,
        "tecnico_id": str(orden.tecnico_id) if orden.tecnico_id else None,
        "activo_id": str(orden.activo_id) if orden.activo_id else None,
        "cita_desde": orden.cita_desde.isoformat() if orden.cita_desde else None,
        "minutos_trabajados": minutos,
        "lineas": [
            {
                "id": str(f.id),
                "tipo": f.tipo,
                "concepto": f.concepto,
                "cantidad": str(f.cantidad),
                "unidad": f.unidad,
                "facturable": f.facturable,
                "cubierto_garantia": f.cubierto_garantia,
                "nota_cobertura": f.nota_cobertura,
            }
            for f in lineas
        ],
        # Las tres cestas por separado: lo que paga el cliente, lo que reclama al
        # fabricante y lo que **no se sabe**. Fundir la tercera con cualquiera de
        # las otras dos es facturar mal o perder una reclamación.
        "a_facturar": len([f for f in lineas if f.facturable and f.cubierto_garantia is False]),
        "a_garantia": len([f for f in lineas if f.cubierto_garantia is True]),
        "sin_determinar": len([f for f in lineas if f.cubierto_garantia is None]),
        "parte": (
            {
                "resumen": parte.resumen,
                "diagnostico": parte.diagnostico,
                "checklist": parte.checklist,
                "evidencias": parte.evidencias,
                "firmado": bool(orden.firmado_at),
                "conforme": orden.conforme,
                "huella": parte.huella,
                # Si la huella ya no cuadra, el parte se tocó después de firmar.
                "alterado_tras_firmar": bool(
                    parte.huella
                    and parte.huella
                    != _huella(
                        {
                            "resumen": parte.resumen,
                            "diagnostico": parte.diagnostico,
                            "checklist": parte.checklist,
                            "evidencias": parte.evidencias,
                        }
                    )
                ),
            }
            if parte is not None
            else None
        ),
    }


# ── Rutas (CRM-04.04.01.02) ───────────────────────────────────────────────


def planificar_ruta(
    db: Session,
    tenant_id: UUID,
    *,
    tecnico_id: UUID,
    dia: date,
    velocidad_kmh: Decimal | None = None,
) -> dict[str, Any]:
    """Ordena las visitas del día y estima el recorrido.

    **Heurística del más cercano**, arrancando en la base del técnico. No es el
    óptimo del viajante y no se presenta como tal: para una jornada de seis u ocho
    visitas la diferencia es pequeña, y una heurística que se explica en una frase
    se puede corregir a mano, que es lo que va a pasar igualmente.

    Las órdenes **sin coordenadas van al final** y se dicen: colocarlas donde caiga
    daría una ruta que parece calculada y no lo está.

    El tiempo de viaje sale de la **distancia en línea recta** y una velocidad
    media configurable. Se declara así (`estimacion: "linea_recta"`) para que nadie
    lo confunda con una ruta real.
    """
    tecnico = _tecnico(db, tenant_id, tecnico_id)
    desde = datetime.combine(dia, datetime.min.time(), tzinfo=timezone.utc)
    hasta = desde + timedelta(days=1)
    ordenes = (
        db.execute(
            select(OrdenTrabajo).where(
                OrdenTrabajo.tenant_id == tenant_id,
                OrdenTrabajo.tecnico_id == tecnico_id,
                OrdenTrabajo.estado.in_(("asignada", "planificada", "en_curso", "pausada")),
                OrdenTrabajo.cita_desde >= desde,
                OrdenTrabajo.cita_desde < hasta,
            )
        )
        .scalars()
        .all()
    )
    velocidad = Decimal(
        velocidad_kmh
        if velocidad_kmh is not None
        else (rt.efectivo("campo_velocidad_media_kmh", db) or 35)
    )

    con_coords = [o for o in ordenes if o.latitud is not None and o.longitud is not None]
    sin_coords = [o for o in ordenes if o.latitud is None or o.longitud is None]

    ruta: list[dict[str, Any]] = []
    metros = 0.0
    lat, lon = tecnico.base_latitud, tecnico.base_longitud
    pendientes = list(con_coords)
    while pendientes:
        if lat is None or lon is None:
            siguiente = pendientes[0]
            salto = None
        else:
            siguiente = min(
                pendientes,
                key=lambda o: distancia_m(lat, lon, o.latitud, o.longitud) or float("inf"),
            )
            salto = distancia_m(lat, lon, siguiente.latitud, siguiente.longitud)
        pendientes.remove(siguiente)
        if salto is not None:
            metros += salto
        ruta.append(
            {
                "orden_id": str(siguiente.id),
                "titulo": siguiente.titulo,
                "direccion": siguiente.direccion,
                "duracion_min": siguiente.duracion_estimada_min,
                "salto_m": round(salto) if salto is not None else None,
                "viaje_min": (
                    round(salto / 1000 / float(velocidad) * 60) if salto is not None else None
                ),
            }
        )
        lat, lon = siguiente.latitud, siguiente.longitud

    for orden in sin_coords:
        ruta.append(
            {
                "orden_id": str(orden.id),
                "titulo": orden.titulo,
                "direccion": orden.direccion,
                "duracion_min": orden.duracion_estimada_min,
                "salto_m": None,
                "viaje_min": None,
                "sin_coordenadas": True,
            }
        )

    minutos_trabajo = sum(o.duracion_estimada_min for o in ordenes)
    minutos_viaje = sum(p["viaje_min"] or 0 for p in ruta)
    total = minutos_trabajo + minutos_viaje
    return {
        "tecnico_id": str(tecnico.id),
        "dia": str(dia),
        "ruta": ruta,
        "km_estimados": round(metros / 1000, 1),
        "minutos_trabajo": minutos_trabajo,
        "minutos_viaje": minutos_viaje,
        "minutos_totales": total,
        "minutos_jornada": tecnico.minutos_jornada,
        "cabe_en_jornada": total <= tecnico.minutos_jornada,
        "exceso_min": max(0, total - tecnico.minutos_jornada),
        "velocidad_media_kmh": str(velocidad),
        "estimacion": "linea_recta",
        # Sin base del técnico, el primer viaje del día no se cuenta y la jornada
        # parece media hora más corta. Se dice en vez de disimularlo.
        "base_conocida": tecnico.base_latitud is not None,
        "optimizada": bool(con_coords) and tecnico.base_latitud is not None,
        "sin_coordenadas": [str(o.id) for o in sin_coords],
        "aviso": (
            ""
            if not sin_coords
            else f"{len(sin_coords)} orden(es) sin coordenadas van al final: la ruta "
            "no está completa."
        ),
    }


# ── Repuestos y almacén móvil (CRM-04.04.01.04) ───────────────────────────


def mover_repuesto(
    uow: UnidadDeTrabajo,
    *,
    tecnico_id: UUID,
    repuesto_id: UUID,
    tipo: str,
    cantidad: Decimal,
    orden_id: UUID | None = None,
    motivo: str = "",
) -> dict[str, Any]:
    """Carga, consume, devuelve o ajusta stock de la furgoneta.

    **No se bloquea por falta de stock.** Si el técnico dice que ha montado la
    pieza, la pieza está montada: lo que está mal es el stock. Se registra el
    consumo, el saldo queda en negativo y se marca `dejo_negativo`, que es
    exactamente la lista que hay que revisar. Impedirlo hace que la pieza se monte
    y no se apunte, y entonces se pierden el stock **y** el histórico.
    """
    if tipo not in TIPOS_MOVIMIENTO:
        raise ErrorValidacion(
            f"Movimiento «{tipo}» no válido.",
            error_code="campo.movimiento_no_valido",
            detalle={"validos": list(TIPOS_MOVIMIENTO)},
        )
    if Decimal(cantidad) <= 0:
        raise ErrorValidacion(
            "Un movimiento de cero no mueve nada.", error_code="campo.cantidad_invalida"
        )
    if tipo in ("ajuste", "merma") and not motivo.strip():
        raise ErrorValidacion(
            "Un ajuste o una merma sin motivo convierten el inventario en una " "opinión.",
            error_code="campo.motivo_obligatorio",
        )
    _tecnico(uow.db, uow.tenant_id, tecnico_id)

    fila = uow.db.execute(
        select(StockFurgoneta).where(
            StockFurgoneta.tenant_id == uow.tenant_id,
            StockFurgoneta.tecnico_id == tecnico_id,
            StockFurgoneta.repuesto_id == repuesto_id,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = StockFurgoneta(
            tenant_id=uow.tenant_id,
            tecnico_id=tecnico_id,
            repuesto_id=repuesto_id,
            cantidad=Decimal(0),
        )
        uow.db.add(fila)
        uow.db.flush()

    signo = Decimal(1) if tipo in ("carga", "devolucion") else Decimal(-1)
    if tipo == "ajuste":
        # El ajuste fija el saldo, no lo suma: es lo que se hace al recontar la
        # furgoneta, y sumarlo obligaría a calcular la diferencia a mano.
        anterior = Decimal(fila.cantidad)
        fila.cantidad = Decimal(cantidad)
        delta = Decimal(cantidad) - anterior
    else:
        delta = signo * Decimal(cantidad)
        fila.cantidad = Decimal(fila.cantidad) + delta

    negativo = Decimal(fila.cantidad) < 0
    movimiento = MovimientoRepuesto(
        tenant_id=uow.tenant_id,
        tecnico_id=tecnico_id,
        repuesto_id=repuesto_id,
        tipo=tipo,
        cantidad=Decimal(cantidad),
        orden_id=orden_id,
        motivo=motivo.strip(),
        dejo_negativo=negativo,
    )
    uow.db.add(movimiento)
    uow.db.flush()
    if negativo:
        logger.info(
            "campo.stock_negativo",
            tecnico=str(tecnico_id),
            repuesto=str(repuesto_id),
            saldo=str(fila.cantidad),
        )
    return {
        "movimiento_id": str(movimiento.id),
        "saldo": str(fila.cantidad),
        "delta": str(delta),
        "dejo_negativo": negativo,
        "aviso": (
            "El consumo deja la furgoneta en negativo: la pieza se ha usado, lo que "
            "está mal es el stock. Hay que recontar."
            if negativo
            else ""
        ),
    }


def reposicion(db: Session, tenant_id: UUID, *, tecnico_id: UUID | None = None) -> dict[str, Any]:
    """Qué hay que cargar: lo que está por debajo del mínimo o en negativo."""
    consulta = select(StockFurgoneta).where(StockFurgoneta.tenant_id == tenant_id)
    if tecnico_id:
        consulta = consulta.where(StockFurgoneta.tecnico_id == tecnico_id)
    filas = db.execute(consulta).scalars().all()
    faltan = []
    for fila in filas:
        if Decimal(fila.cantidad) < Decimal(fila.minimo) or Decimal(fila.cantidad) < 0:
            faltan.append(
                {
                    "tecnico_id": str(fila.tecnico_id),
                    "repuesto_id": str(fila.repuesto_id),
                    "cantidad": str(fila.cantidad),
                    "minimo": str(fila.minimo),
                    "reponer": str(_redondear(Decimal(fila.minimo) - Decimal(fila.cantidad))),
                    "en_negativo": Decimal(fila.cantidad) < 0,
                }
            )
    return {
        "lineas": faltan,
        # Un mínimo a cero nunca pide reposición: la lista sale vacía y parece que
        # todo está bien. Se dice cuántas referencias no tienen mínimo puesto.
        "sin_minimo": len([f for f in filas if Decimal(f.minimo) == 0]),
        "medible": bool(filas),
    }


# ── Mantenimiento preventivo (CRM-04.04.01.05) ────────────────────────────


def crear_plan(
    uow: UnidadDeTrabajo,
    *,
    nombre: str,
    activo_id: UUID,
    cada_dias: int | None = None,
    cada_contador: Decimal | None = None,
    duracion_min: int = 60,
    competencias: list[str] | None = None,
    checklist: list[dict[str, Any]] | None = None,
    antelacion_dias: int = 15,
    desde: date | None = None,
) -> PlanPreventivo:
    """Crea un plan preventivo. Hace falta periodicidad por tiempo **o** por uso."""
    if not cada_dias and not cada_contador:
        raise ErrorValidacion(
            "Un plan preventivo necesita cada cuántos días o cada cuántas unidades "
            "de uso toca: sin ninguna de las dos no se dispara nunca.",
            error_code="campo.plan_sin_periodicidad",
        )
    activo = act.obtener(uow.db, uow.tenant_id, activo_id)
    fila = PlanPreventivo(
        tenant_id=uow.tenant_id,
        nombre=nombre.strip(),
        activo_id=activo_id,
        cada_dias=cada_dias,
        cada_contador=cada_contador,
        duracion_min=duracion_min,
        competencias=list(competencias or []),
        checklist=list(checklist or []),
        antelacion_dias=antelacion_dias,
        ultima_ejecucion=desde or _hoy(uow.db),
        ultimo_contador=activo.contador,
        proxima_fecha=((desde or _hoy(uow.db)) + timedelta(days=cada_dias)) if cada_dias else None,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def vencimientos(db: Session, tenant_id: UUID, *, en_fecha: date | None = None) -> dict[str, Any]:
    """Qué toca revisar, por fecha o por uso, y **por cuál de las dos**.

    Saber si vence por calendario o por horas cambia la conversación con el
    cliente: una es «toca la revisión anual» y la otra es «esta máquina ha
    trabajado el doble de lo previsto».
    """
    hoy = en_fecha or _hoy(db)
    planes = (
        db.execute(
            select(PlanPreventivo).where(
                PlanPreventivo.tenant_id == tenant_id, PlanPreventivo.activo.is_(True)
            )
        )
        .scalars()
        .all()
    )
    salida = []
    for plan in planes:
        activo = db.get(act.ActivoInstalado, plan.activo_id)
        if activo is None or activo.estado == "retirado":
            continue
        motivos: list[str] = []
        vence_el: date | None = None
        if plan.cada_dias and plan.proxima_fecha:
            vence_el = plan.proxima_fecha
            if plan.proxima_fecha <= hoy + timedelta(days=plan.antelacion_dias):
                motivos.append(f"por calendario (tocaba el {plan.proxima_fecha})")
        por_uso = False
        if plan.cada_contador and activo.contador is not None:
            base = Decimal(plan.ultimo_contador or 0)
            if Decimal(activo.contador) - base >= Decimal(plan.cada_contador):
                motivos.append(
                    f"por uso ({Decimal(activo.contador) - base} "
                    f"{activo.unidad_contador or 'unidades'} desde la última)"
                )
                por_uso = True
        if not motivos:
            continue
        salida.append(
            {
                "plan_id": str(plan.id),
                "nombre": plan.nombre,
                "activo_id": str(plan.activo_id),
                "vence_el": str(vence_el) if vence_el else None,
                "por_uso": por_uso,
                "vencido": bool(vence_el and vence_el < hoy),
                "porque": " y ".join(motivos),
            }
        )
    # Los planes que miden por uso y cuyo activo no tiene lectura no se pueden
    # evaluar. Callarlo haría creer que están al día.
    sin_lectura = [
        str(p.id)
        for p in planes
        if p.cada_contador
        and ((a := db.get(act.ActivoInstalado, p.activo_id)) is None or a.contador is None)
    ]
    return {
        "en_fecha": str(hoy),
        "vencimientos": salida,
        "planes_sin_lectura_de_contador": sin_lectura,
        "concluyente": not sin_lectura,
    }


def generar_preventivas(uow: UnidadDeTrabajo, *, en_fecha: date | None = None) -> dict[str, Any]:
    """Crea las órdenes preventivas que tocan.

    **Una por plan a la vez.** Si el plan ya tiene una orden abierta, no se crea
    otra: un plan mensual desatendido seis meses generaría seis órdenes idénticas,
    y lo que se hace entonces es cerrarlas todas sin mirar.
    """
    hoy = en_fecha or _hoy(uow.db)
    estado = vencimientos(uow.db, uow.tenant_id, en_fecha=hoy)
    creadas: list[str] = []
    saltadas: list[dict[str, Any]] = []
    for vencimiento in estado["vencimientos"]:
        plan = uow.db.get(PlanPreventivo, UUID(vencimiento["plan_id"]))
        if plan is None:
            continue
        abierta = uow.db.execute(
            select(OrdenTrabajo).where(
                OrdenTrabajo.tenant_id == uow.tenant_id,
                OrdenTrabajo.plan_id == plan.id,
                OrdenTrabajo.estado.notin_(("cerrada", "cancelada")),
            )
        ).scalar_one_or_none()
        if abierta is not None:
            saltadas.append(
                {
                    "plan_id": str(plan.id),
                    "porque": "ya tiene una orden abierta",
                    "orden_id": str(abierta.id),
                }
            )
            continue
        orden, _ = crear_orden(
            uow,
            titulo=plan.nombre,
            tipo="preventivo",
            activo_id=plan.activo_id,
            competencias=[str(c) for c in (plan.competencias or [])],
            duracion_estimada_min=plan.duracion_min,
            plan_id=plan.id,
            descripcion=f"Preventivo {vencimiento['porque']}",
        )
        orden.estado = "planificada"
        creadas.append(str(orden.id))
    uow.db.flush()
    return {
        "en_fecha": str(hoy),
        "creadas": creadas,
        "saltadas": saltadas,
        "concluyente": estado["concluyente"],
        "planes_sin_lectura_de_contador": estado["planes_sin_lectura_de_contador"],
    }


def registrar_preventivo_hecho(uow: UnidadDeTrabajo, orden_id: UUID) -> PlanPreventivo | None:
    """Reprograma el plan al cerrar su orden.

    Se cuenta **desde que se hizo**, no desde que tocaba: una revisión que se
    hizo con un mes de retraso mueve el calendario, porque si no, la siguiente
    nace vencida y el plan arrastra el retraso para siempre.
    """
    orden = _orden(uow.db, uow.tenant_id, orden_id)
    if orden.plan_id is None:
        return None
    plan = uow.db.get(PlanPreventivo, orden.plan_id)
    if plan is None or plan.tenant_id != uow.tenant_id:
        return None
    # EL DÍA EN LA ZONA DEL CLIENTE, no el que salga del instante tal cual.
    # `completada_at` es un `timestamptz`: el instante es correcto, pero `.date()`
    # lo toma en la zona que devuelva la conexión —ni UTC ni la del tenant: la
    # del servidor—, que es un tercer reloj. Medido el 07-10-2026 a las 02:20:
    # una revisión completada daba la siguiente un día corrida.
    #
    # Para un plan de mantenimiento «el día en que se hizo» es el del cliente: es
    # el que ve el técnico en el parte y el que el cliente cuenta para el
    # siguiente aviso.
    hecho = _dia_del_cliente(orden.completada_at or _ahora(), uow.db)
    plan.ultima_ejecucion = hecho
    if plan.cada_dias:
        plan.proxima_fecha = hecho + timedelta(days=plan.cada_dias)
    activo = uow.db.get(act.ActivoInstalado, plan.activo_id)
    if activo is not None and activo.contador is not None:
        plan.ultimo_contador = activo.contador
    return plan


# ── Sincronización del móvil (CRM-04.04.01.03) ────────────────────────────


def sincronizar(
    uow: UnidadDeTrabajo,
    *,
    dispositivo: str,
    cambios: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aplica un lote de cambios traído de un móvil que estuvo sin red.

    Tres reglas, y ninguna es opcional:

    **Idempotencia por identificador de cliente.** El móvil genera el `id_cliente`
    antes de tener red. Reenviar el lote —porque se cortó a mitad— no vuelve a
    aplicar nada. Sin esto, sincronizar dos veces consume la pieza dos veces.

    **El reloj del móvil se guarda, pero no manda.** Va mal: zona horaria
    equivocada, hora cambiada a mano. Se guarda `capturado_at` tal cual, junto al
    `recibido_at` del servidor, porque aun mintiendo es el único que sabe cuándo
    se hizo el trabajo.

    **Los conflictos se devuelven, no se resuelven.** Si alguien tocó la orden en
    el servidor mientras el técnico trabajaba sin red, ni se pisa lo del servidor
    ni se tira lo del técnico: se devuelve el conflicto y lo decide una persona.
    Elegir automáticamente significa perder trabajo de alguien en silencio, y en
    campo eso es media jornada.
    """
    resultados: list[dict[str, Any]] = []
    for cambio in cambios:
        id_cliente = str(cambio.get("id_cliente") or "").strip()
        if not id_cliente:
            resultados.append(
                {
                    "id_cliente": None,
                    "resultado": "rechazada",
                    "porque": "sin id_cliente: no se puede garantizar que no se duplique",
                }
            )
            continue

        ya = uow.db.execute(
            select(OperacionSincronizada).where(
                OperacionSincronizada.tenant_id == uow.tenant_id,
                OperacionSincronizada.id_cliente == id_cliente,
            )
        ).scalar_one_or_none()
        if ya is not None:
            resultados.append(
                {
                    "id_cliente": id_cliente,
                    "resultado": "duplicada",
                    "porque": "ya se aplicó en una sincronización anterior",
                    "aplicada_at": ya.recibido_at.isoformat(),
                }
            )
            continue

        tipo = str(cambio.get("tipo") or "")
        capturado = cambio.get("capturado_at")
        capturado_at = datetime.fromisoformat(str(capturado)) if capturado else None
        orden_id = UUID(str(cambio["orden_id"])) if cambio.get("orden_id") else None
        detalle: dict[str, Any] = {}
        resultado = "aplicada"
        porque = ""

        try:
            if orden_id is not None:
                orden = _orden(uow.db, uow.tenant_id, orden_id)
                # Conflicto: el móvil salió con una versión y el servidor tiene
                # otra. No se decide aquí.
                visto = cambio.get("visto_en_estado")
                if visto and str(visto) != orden.estado:
                    resultados.append(
                        {
                            "id_cliente": id_cliente,
                            "resultado": "conflicto",
                            "porque": (
                                f"el técnico salió con la orden en «{visto}» y ahora "
                                f"está en «{orden.estado}»: lo decide una persona"
                            ),
                            "orden_id": str(orden_id),
                        }
                    )
                    uow.db.add(
                        OperacionSincronizada(
                            tenant_id=uow.tenant_id,
                            id_cliente=id_cliente,
                            dispositivo=dispositivo,
                            tipo=tipo,
                            orden_id=orden_id,
                            resultado="conflicto",
                            detalle={"visto": str(visto), "actual": orden.estado},
                            capturado_at=capturado_at,
                        )
                    )
                    continue

            if tipo == "linea":
                if orden_id is None:
                    raise ErrorValidacion("Falta la orden.", error_code="campo.sync_sin_orden")
                linea, avisos = anotar_linea(
                    uow,
                    orden_id,
                    tipo=str(cambio.get("linea_tipo") or "material"),
                    concepto=str(cambio.get("concepto") or ""),
                    cantidad=Decimal(str(cambio.get("cantidad") or 1)),
                    unidad=str(cambio.get("unidad") or "ud"),
                    repuesto_id=(
                        UUID(str(cambio["repuesto_id"])) if cambio.get("repuesto_id") else None
                    ),
                    desde=(
                        datetime.fromisoformat(str(cambio["desde"]))
                        if cambio.get("desde")
                        else None
                    ),
                    hasta=(
                        datetime.fromisoformat(str(cambio["hasta"]))
                        if cambio.get("hasta")
                        else None
                    ),
                )
                detalle = {"linea_id": str(linea.id), "avisos": avisos}
            elif tipo == "completar":
                if orden_id is None:
                    raise ErrorValidacion("Falta la orden.", error_code="campo.sync_sin_orden")
                _, informe = completar(
                    uow,
                    orden_id,
                    resumen=str(cambio.get("resumen") or ""),
                    diagnostico=str(cambio.get("diagnostico") or ""),
                    checklist=list(cambio.get("checklist") or []),
                    evidencias=list(cambio.get("evidencias") or []),
                    cuando=capturado_at,
                    forzar=bool(cambio.get("forzar")),
                )
                detalle = informe
            elif tipo == "firma":
                if orden_id is None:
                    raise ErrorValidacion("Falta la orden.", error_code="campo.sync_sin_orden")
                detalle = firmar(
                    uow,
                    orden_id,
                    firmado_por=str(cambio.get("firmado_por") or ""),
                    conforme=bool(cambio.get("conforme", True)),
                    motivo_no_conforme=str(cambio.get("motivo_no_conforme") or ""),
                )
            elif tipo == "contador":
                detalle = act.leer_contador(
                    uow,
                    UUID(str(cambio["activo_id"])),
                    valor=Decimal(str(cambio.get("valor") or 0)),
                )
            else:
                resultado = "rechazada"
                porque = f"tipo de cambio «{tipo}» desconocido"
        except (ErrorValidacion, Conflicto, NoEncontrado) as error:
            # Un cambio que no se puede aplicar **no tumba el lote**: el técnico
            # trajo seis horas de trabajo y perder las cinco buenas por una mala
            # es exactamente lo que hace que se deje de sincronizar.
            resultado = "rechazada"
            porque = str(getattr(error, "mensaje", None) or error)

        uow.db.add(
            OperacionSincronizada(
                tenant_id=uow.tenant_id,
                id_cliente=id_cliente,
                dispositivo=dispositivo,
                tipo=tipo,
                orden_id=orden_id,
                resultado=resultado,
                detalle=detalle if resultado == "aplicada" else {"porque": porque},
                capturado_at=capturado_at,
            )
        )
        uow.db.flush()
        resultados.append(
            {
                "id_cliente": id_cliente,
                "resultado": resultado,
                "porque": porque,
                "orden_id": str(orden_id) if orden_id else None,
                **({"detalle": detalle} if detalle else {}),
            }
        )

    por_resultado = {
        clave: len([r for r in resultados if r["resultado"] == clave])
        for clave in ("aplicada", "duplicada", "conflicto", "rechazada")
    }
    return {
        "dispositivo": dispositivo,
        "recibidos": len(cambios),
        "resultados": resultados,
        "resumen": por_resultado,
        # Que el lote «vaya bien» no es que no falle: es que no quede nada sin
        # aplicar. Los conflictos y los rechazos son trabajo real de alguien.
        "todo_aplicado": por_resultado["conflicto"] == 0 and por_resultado["rechazada"] == 0,
    }
