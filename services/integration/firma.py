"""Firma electrónica: sobres, firmantes y evidencia (CRM-06.01.02).

Un sobre de firma es un objeto con una vida larga y un final legal. Lo que decide
si sirve no es mandarlo: es poder demostrar, dos años después y ante quien lo
discuta, **qué se firmó, quién lo firmó y cuándo**.

Cinco decisiones gobiernan el módulo:

**El proveedor es configuración, no código.** Sobre el transporte declarativo que
ya existe (`conector.py`). Un conector por producto —DocuSign, Signaturit,
Viafirma— convierte cada cliente con otro proveedor en una versión del producto, y
la lista de proveedores en el código convierte cada alta en un despliegue.

**Varios proveedores a la vez, elegidos por regla.** Un grupo con filial
portuguesa firma allí con otro proveedor, y un contrato de cien mil no va por el
mismo sitio que un albarán. Un solo proveedor por tenant obliga a elegir el peor
denominador común.

**La evidencia se guarda aquí aunque la tenga el proveedor.** El hash de lo que se
mandó, el de lo que volvió, cada acceso de cada firmante y el certificado final.
Si la evidencia vive solo en el proveedor, el día que se cambia de proveedor —o
que cierra— se pierde la prueba de todo lo firmado con él.

**El nivel eIDAS decide la identificación, no al revés.** Pedir «avanzada» y
verificar por correo es decir que es avanzada sin serlo, y eso solo se descubre
cuando alguien impugna la firma.

**Un sobre que no avanza no se da por bueno.** Es el mismo silencio del encargo
mudo y del pedido en el ERP: el fallo caro de una integración no es el error, es
que no pase nada y parezca que va bien.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
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

# Niveles del reglamento eIDAS. Cerrados: son los que existen, y dejarlos libres
# haría que cada tenant escribiera «avanzada+» y ningún informe pudiera agrupar.
NIVELES = ("simple", "avanzada", "cualificada")

# Cómo se identifica al firmante (CRM-06.01.02.08). Lo que cada nivel admite está
# declarado abajo: es lo que impide prometer una firma avanzada verificando por
# correo, que es decir que es avanzada sin serlo.
IDENTIFICACIONES = ("correo", "sms", "video", "certificado", "dni_electronico")
ADMITIDAS_POR_NIVEL: dict[str, tuple[str, ...]] = {
    "simple": ("correo", "sms", "video", "certificado", "dni_electronico"),
    # La avanzada exige un vínculo con el firmante más fuerte que un correo: el
    # correo demuestra acceso a un buzón, no identidad.
    "avanzada": ("sms", "video", "certificado", "dni_electronico"),
    # La cualificada exige certificado cualificado. Sin él no es cualificada,
    # por mucho que el proveedor lo llame así en su folleto.
    "cualificada": ("certificado", "dni_electronico"),
}

ESTADOS_SOBRE = (
    "borrador",
    "enviado",
    "en_curso",
    "completado",
    "rechazado",
    "caducado",
    "cancelado",
    "error",
)
ESTADOS_FIRMANTE = ("pendiente", "abierto", "firmado", "rechazado", "delegado", "caducado")
TERMINALES = ("completado", "rechazado", "caducado", "cancelado")


class ProveedorFirma(Base, TimestampMixin):
    """Un proveedor de firma configurado (CRM-06.01.02.02)."""

    __tablename__ = "proveedores_firma"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(60), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    # La conexión declarativa por la que se le llama. El transporte es el mismo
    # que el de cualquier otra API: dirección, credencial y mapeo.
    conexion_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # Qué niveles sabe hacer. Se declara porque no todos hacen cualificada, y
    # mandarle un contrato que exige cualificada a quien no la hace produce una
    # firma que parece válida y no lo es.
    niveles: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[\"simple\"]'::jsonb")
    )
    identificaciones: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[\"correo\"]'::jsonb")
    )
    # Traducción de sus estados a los del sistema, igual que en el seguimiento de
    # encargos y por el mismo motivo: cada proveedor llama a lo mismo de otra
    # manera, y traducirlo en el código significa tocar el producto por cada uno.
    mapa_estados: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Coste por sobre, para conciliar su factura.
    coste_sobre: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Se deja de mandar por él pero sus sobres en vuelo siguen terminando con él
    # (CRM-06.01.02.13). No es lo mismo que desactivarlo del todo.
    solo_en_curso: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    probado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    prueba_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    prueba_detalle: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "clave", name="uq_proveedor_firma"),)


class ReglaProveedorFirma(Base, TimestampMixin):
    """Qué proveedor le toca a cada documento (CRM-06.01.02.12)."""

    __tablename__ = "reglas_proveedor_firma"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    prioridad: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Gramática de condiciones del producto, la misma de siempre.
    condiciones: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    proveedor: Mapped[str] = mapped_column(String(60), nullable=False)
    # Nivel mínimo que impone esta regla. Un contrato de cien mil no se firma con
    # un clic aunque quien lo mande no lo piense.
    nivel_minimo: Mapped[str | None] = mapped_column(String(20), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "nombre", name="uq_regla_proveedor_firma"),
        Index("ix_reglas_firma_orden", "tenant_id", "activa", "prioridad"),
    )


class PlantillaFirma(Base, TimestampMixin):
    """Dónde se firma y qué rellena cada uno (CRM-06.01.02.06)."""

    __tablename__ = "plantillas_firma"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    tipo_documento: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    nivel: Mapped[str] = mapped_column(String(20), nullable=False, default="simple")
    # Campos y firmas, con su sitio. Dos formas de decir dónde: por página y
    # coordenadas, o por **anclaje de texto** —«/firma_cliente/»—. El anclaje
    # existe porque las coordenadas se rompen en cuanto el contrato gana un
    # párrafo, y eso pasa siempre.
    campos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    dias_validez: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    orden_estricto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "clave", name="uq_plantilla_firma"),)


class Sobre(Base, TimestampMixin):
    """Lo que se manda a firmar (CRM-06.01.02.01)."""

    __tablename__ = "sobres_firma"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    referencia: Mapped[str] = mapped_column(String(60), nullable=False)
    proveedor: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    # El identificador del sobre en el proveedor. Llega al mandarlo, no antes.
    referencia_externa: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # De qué registro cuelga. Identificadores opacos: el presupuesto vive en
    # `sales` y el caso en `service`, y ningún servicio lee el esquema de otro.
    objeto_origen: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    objeto_origen_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)

    asunto: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    mensaje: Mapped[str] = mapped_column(Text, nullable=False, default="")
    nivel: Mapped[str] = mapped_column(String(20), nullable=False, default="simple")
    plantilla: Mapped[str | None] = mapped_column(String(80), nullable=True)
    orden_estricto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="borrador")
    # El documento del corpus que se manda, y el firmado que vuelve
    # (CRM-06.01.02.07). Son dos: el firmado es otro documento, no una versión
    # del mismo, porque el original tiene que seguir existiendo tal como salió.
    documento_id: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    documento_firmado_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Huella de lo que se mandó y de lo que volvió (CRM-06.01.02.04). Son la
    # prueba de que el documento firmado es el que se envió: sin ellas, «esto no
    # es lo que yo firmé» no se puede contestar.
    hash_enviado: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hash_firmado: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # El certificado de finalización del proveedor, archivado también en el
    # corpus. Es el documento que se lleva a un juzgado.
    certificado_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sello_tiempo: Mapped[str | None] = mapped_column(Text, nullable=True)

    enviado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    caduca_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    ultima_novedad_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ultimo_recordatorio_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Lo que decide la elección de proveedor y el nivel; sirve para explicarla.
    contexto: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "referencia", name="uq_sobre_referencia"),
        Index("ix_sobres_estado", "tenant_id", "estado", "caduca_at"),
        Index("ix_sobres_origen", "tenant_id", "objeto_origen", "objeto_origen_id"),
        Index("ix_sobres_externa", "tenant_id", "proveedor", "referencia_externa"),
    )


class Firmante(Base, TimestampMixin):
    """Quién tiene que firmar, en qué orden y cómo se le identifica."""

    __tablename__ = "firmantes"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    sobre_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("sobres_firma.id", ondelete="CASCADE"), nullable=False
    )
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    telefono: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # firmante | aprobador | copia. La copia no firma: recibe el resultado.
    papel: Mapped[str] = mapped_column(String(20), nullable=False, default="firmante")
    identificacion: Mapped[str] = mapped_column(String(30), nullable=False, default="correo")
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    firmado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motivo_rechazo: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Identificador del firmante en el proveedor, para cruzar sus avisos.
    referencia_externa: Mapped[str | None] = mapped_column(String(200), nullable=True)

    __table_args__ = (
        UniqueConstraint("sobre_id", "orden", name="uq_firmante_orden"),
        Index("ix_firmantes_sobre", "tenant_id", "sobre_id", "orden"),
    )


class EvidenciaFirma(Base):
    """Cada cosa que pasó, append-only (CRM-06.01.02.04).

    Es la cadena de custodia. Se guarda **aquí** y no solo en el proveedor: el día
    que se cambia de proveedor —o que cierra— se perdería la prueba de todo lo
    firmado con él, y eso se descubre justo cuando hace falta.
    """

    __tablename__ = "evidencias_firma"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    sobre_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("sobres_firma.id", ondelete="CASCADE"), nullable=False
    )
    firmante_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # creado | enviado | entregado | abierto | firmado | rechazado | recordado |
    # cancelado | completado | error
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agente: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Cuándo lo dice el proveedor y cuándo nos enteramos: la diferencia es la
    # latencia de la integración, y sin las dos no se puede defender una fecha.
    ocurrio_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    registrado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Identificador del evento en el proveedor: es lo que hace idempotente la
    # ingesta, igual que en el seguimiento de encargos.
    id_externo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    crudo: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "sobre_id", "id_externo", name="uq_evidencia_externa"),
        Index("ix_evidencias_sobre", "tenant_id", "sobre_id", "ocurrio_at"),
    )


class LlamadaProveedorFirma(Base):
    """Petición, respuesta y coste de cada llamada (CRM-06.01.02.15, parcial).

    Se guarda para conciliar la factura del proveedor y para depurar un sobre
    atascado. **Sin cuerpos completos**: un contrato entero repetido en una tabla
    de registro es una copia del documento fuera del corpus, que es justo donde no
    tiene que estar.
    """

    __tablename__ = "llamadas_proveedor_firma"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    proveedor: Mapped[str] = mapped_column(String(60), nullable=False)
    sobre_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    operacion: Mapped[str] = mapped_column(String(60), nullable=False)
    codigo: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    duracion_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coste: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_llamadas_firma", "tenant_id", "proveedor", "created_at"),)


# ── Utilidades ────────────────────────────────────────────────────────────


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _con_tz(v: datetime | None) -> datetime | None:
    if v is None:
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def huella(contenido: bytes) -> str:
    """SHA-256 de lo que se manda o de lo que vuelve.

    Es lo que permite contestar «esto no es lo que yo firmé»: sin las dos
    huellas, la respuesta es la palabra de uno contra la del otro.
    """
    return hashlib.sha256(contenido).hexdigest()


def _proveedor(db: Session, tenant_id: UUID, clave: str) -> ProveedorFirma:
    fila = db.execute(
        select(ProveedorFirma).where(
            ProveedorFirma.tenant_id == tenant_id, ProveedorFirma.clave == clave
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado(
            f"No hay ningún proveedor de firma «{clave}» configurado",
            error_code="firma.proveedor_no_encontrado",
        )
    return fila


def _sobre(db: Session, tenant_id: UUID, sobre_id: UUID) -> Sobre:
    fila = db.execute(
        select(Sobre).where(Sobre.id == sobre_id, Sobre.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("El sobre no existe", error_code="firma.sobre_no_encontrado")
    return fila


def _anotar(
    db: Session,
    sobre: Sobre,
    tipo: str,
    *,
    firmante_id: UUID | None = None,
    descripcion: str = "",
    ocurrio_at: datetime | None = None,
    id_externo: str = "",
    ip: str = "",
    agente: str = "",
    crudo: dict[str, Any] | None = None,
) -> EvidenciaFirma:
    fila = EvidenciaFirma(
        tenant_id=sobre.tenant_id,
        sobre_id=sobre.id,
        firmante_id=firmante_id,
        tipo=tipo,
        descripcion=descripcion,
        ocurrio_at=_con_tz(ocurrio_at) or _ahora(),
        id_externo=id_externo or None,
        ip=ip or None,
        agente=agente[:300] if agente else None,
        crudo=crudo or {},
    )
    db.add(fila)
    db.flush()
    return fila


# ── Nivel eIDAS e identificación (CRM-06.01.02.05, .08) ───────────────────


def comprobar_identificacion(nivel: str, identificacion: str) -> None:
    """El nivel decide la identificación, no al revés.

    Pedir «avanzada» y verificar por correo es decir que es avanzada sin serlo, y
    eso solo se descubre cuando alguien impugna la firma — que es el único momento
    en que la firma importaba.
    """
    if nivel not in NIVELES:
        raise ErrorValidacion(
            f"Nivel «{nivel}» no válido.",
            error_code="firma.nivel_no_valido",
            detalle={"validos": list(NIVELES)},
        )
    if identificacion not in IDENTIFICACIONES:
        raise ErrorValidacion(
            f"Identificación «{identificacion}» no válida.",
            error_code="firma.identificacion_no_valida",
            detalle={"validas": list(IDENTIFICACIONES)},
        )
    admitidas = ADMITIDAS_POR_NIVEL[nivel]
    if identificacion not in admitidas:
        raise ErrorValidacion(
            f"Una firma {nivel} no se puede identificar por «{identificacion}». "
            f"Admite: {', '.join(admitidas)}.",
            error_code="firma.identificacion_insuficiente",
            detalle={"nivel": nivel, "admitidas": list(admitidas)},
        )


# ── Elección de proveedor (CRM-06.01.02.12) ───────────────────────────────


def elegir_proveedor(
    db: Session, tenant_id: UUID, contexto: dict[str, Any], *, nivel: str = "simple"
) -> tuple[str, str, str]:
    """Qué proveedor y qué nivel le tocan a este documento.

    Devuelve `(proveedor, nivel, regla)`. La regla se devuelve porque una
    elección que no se puede explicar no se puede corregir, y aquí decide con qué
    validez legal sale un contrato.

    Una regla puede **subir** el nivel pedido, nunca bajarlo: un contrato de cien
    mil no se firma con un clic aunque quien lo mande no lo piense, y dejar que
    una regla rebaje el nivel convierte la política en una sugerencia.
    """
    from crmcore.authz.abac import Condicion

    reglas = (
        db.execute(
            select(ReglaProveedorFirma)
            .where(
                ReglaProveedorFirma.tenant_id == tenant_id,
                ReglaProveedorFirma.activa.is_(True),
            )
            .order_by(ReglaProveedorFirma.prioridad, ReglaProveedorFirma.nombre)
        )
        .scalars()
        .all()
    )
    ambito = {"documento": contexto}
    for regla in reglas:
        condiciones = [
            Condicion(
                atributo=str(c.get("atributo", "")),
                operador=str(c.get("operador", "=")),
                valor=c.get("valor"),
            )
            for c in (regla.condiciones or [])
            if isinstance(c, dict)
        ]
        if all(c.evaluar(ambito) for c in condiciones):
            elegido = regla.nivel_minimo or nivel
            if NIVELES.index(elegido) < NIVELES.index(nivel):
                elegido = nivel
            return regla.proveedor, elegido, regla.nombre

    activos = (
        db.execute(
            select(ProveedorFirma)
            .where(
                ProveedorFirma.tenant_id == tenant_id,
                ProveedorFirma.activo.is_(True),
                ProveedorFirma.solo_en_curso.is_(False),
            )
            .order_by(ProveedorFirma.clave)
        )
        .scalars()
        .all()
    )
    if not activos:
        raise ErrorValidacion(
            "No hay ningún proveedor de firma configurado ni regla que elija uno.",
            error_code="firma.sin_proveedor",
        )
    return activos[0].clave, nivel, "(sin regla: primer proveedor activo)"


# ── Crear y mandar (CRM-06.01.02.01) ──────────────────────────────────────


def _siguiente_referencia(db: Session, tenant_id: UUID) -> str:
    cuantos = int(
        db.execute(
            select(func.count()).select_from(Sobre).where(Sobre.tenant_id == tenant_id)
        ).scalar_one()
        or 0
    )
    return f"SOB-{date.today().year}-{cuantos + 1:05d}"


def crear(
    uow: UnidadDeTrabajo,
    *,
    documento_id: str,
    firmantes: list[dict[str, Any]],
    objeto_origen: str = "",
    objeto_origen_id: UUID | None = None,
    cuenta_id: UUID | None = None,
    asunto: str = "",
    mensaje: str = "",
    nivel: str = "simple",
    proveedor: str = "",
    plantilla: str = "",
    dias_validez: int | None = None,
    orden_estricto: bool = False,
    contexto: dict[str, Any] | None = None,
    contenido: bytes | None = None,
) -> Sobre:
    """Prepara un sobre. **No lo manda todavía.**

    Separar crear de mandar es a propósito: mandar un contrato a firmar es
    irreversible de cara al cliente —le llega un correo— y el error más caro que
    puede cometer quien lo maneja es pulsar creyendo que aún estaba montándolo.
    """
    tenant_id = uow.tenant_id
    if not documento_id:
        raise ErrorValidacion(
            "Un sobre sin documento no manda nada a firmar.",
            error_code="firma.sin_documento",
        )
    if not firmantes:
        raise ErrorValidacion(
            "Un sobre sin firmantes no lo firma nadie.", error_code="firma.sin_firmantes"
        )

    contexto = dict(contexto or {})
    regla = ""
    if proveedor:
        nivel_final = nivel
    else:
        proveedor, nivel_final, regla = elegir_proveedor(uow.db, tenant_id, contexto, nivel=nivel)

    ficha = _proveedor(uow.db, tenant_id, proveedor)
    if not ficha.activo:
        raise Conflicto(
            f"El proveedor «{proveedor}» está desactivado.",
            error_code="firma.proveedor_inactivo",
        )
    if nivel_final not in (ficha.niveles or []):
        # Mandarle un contrato que exige cualificada a quien no la hace produce
        # una firma que parece válida y no lo es. Se para aquí, no en el juzgado.
        raise Conflicto(
            f"«{proveedor}» no hace firma {nivel_final}. Hace: "
            f"{', '.join(ficha.niveles or []) or 'ninguno declarado'}.",
            error_code="firma.nivel_no_soportado",
            detalle={"proveedor": proveedor, "nivel": nivel_final},
        )

    validez = dias_validez
    campos: list[Any] = []
    if plantilla:
        ficha_plantilla = uow.db.execute(
            select(PlantillaFirma).where(
                PlantillaFirma.tenant_id == tenant_id, PlantillaFirma.clave == plantilla
            )
        ).scalar_one_or_none()
        if ficha_plantilla is None:
            raise NoEncontrado(
                "La plantilla de firma no existe", error_code="firma.plantilla_no_encontrada"
            )
        validez = validez or ficha_plantilla.dias_validez
        orden_estricto = orden_estricto or ficha_plantilla.orden_estricto
        campos = list(ficha_plantilla.campos or [])
        if NIVELES.index(ficha_plantilla.nivel) > NIVELES.index(nivel_final):
            # La plantilla puede subir el nivel, como las reglas, y por lo mismo.
            nivel_final = ficha_plantilla.nivel

    sobre = Sobre(
        tenant_id=tenant_id,
        referencia=_siguiente_referencia(uow.db, tenant_id),
        proveedor=proveedor,
        objeto_origen=objeto_origen,
        objeto_origen_id=objeto_origen_id,
        cuenta_id=cuenta_id,
        asunto=asunto,
        mensaje=mensaje,
        nivel=nivel_final,
        plantilla=plantilla or None,
        orden_estricto=orden_estricto,
        documento_id=documento_id,
        caduca_at=_ahora() + timedelta(days=validez or 30),
        contexto={**contexto, "regla_de_eleccion": regla, "campos": campos},
    )
    if contenido is not None:
        sobre.hash_enviado = huella(contenido)
    uow.db.add(sobre)
    uow.db.flush()

    for i, entrada in enumerate(firmantes):
        identificacion = str(entrada.get("identificacion") or "correo")
        papel = str(entrada.get("papel") or "firmante")
        if papel != "copia":
            comprobar_identificacion(nivel_final, identificacion)
            if identificacion not in (ficha.identificaciones or []):
                raise Conflicto(
                    f"«{proveedor}» no identifica por «{identificacion}».",
                    error_code="firma.identificacion_no_soportada",
                    detalle={"admite": list(ficha.identificaciones or [])},
                )
        uow.db.add(
            Firmante(
                tenant_id=tenant_id,
                sobre_id=sobre.id,
                orden=int(entrada.get("orden", i)),
                nombre=str(entrada.get("nombre") or ""),
                email=str(entrada.get("email") or ""),
                telefono=entrada.get("telefono"),
                papel=papel,
                identificacion=identificacion,
            )
        )
    uow.db.flush()
    _anotar(
        uow.db,
        sobre,
        "creado",
        descripcion=f"Sobre preparado para «{proveedor}», nivel {nivel_final}",
    )
    return sobre


def enviar(uow: UnidadDeTrabajo, sobre_id: UUID) -> dict[str, Any]:
    """Manda el sobre al proveedor y lo deja esperando.

    La llamada la hace el conector declarativo; aquí se marca enviado y se emite
    el evento. **No se da por firmado porque la llamada no diera error**: el
    proveedor acepta el sobre y el firmante puede tardar una semana o no abrirlo
    nunca.
    """
    tenant_id = uow.tenant_id
    sobre = _sobre(uow.db, tenant_id, sobre_id)
    if sobre.estado != "borrador":
        raise Conflicto(
            f"Ese sobre ya está «{sobre.estado}».", error_code="firma.sobre_no_enviable"
        )
    firmantes = _firmantes(uow.db, sobre)
    if not [f for f in firmantes if f.papel != "copia"]:
        raise Conflicto(
            "Ese sobre solo tiene copias: nadie lo firmaría.",
            error_code="firma.sin_firmantes_reales",
        )

    sobre.estado = "enviado"
    sobre.enviado_at = _ahora()
    sobre.ultima_novedad_at = _ahora()
    uow.db.flush()
    _anotar(uow.db, sobre, "enviado", descripcion=f"Enviado a {len(firmantes)} destinatarios")

    uow.emitir(
        "signature.envelope.sent",
        subject=("sobre", sobre.id),
        data={
            "sobre_id": str(sobre.id),
            "referencia": sobre.referencia,
            "proveedor": sobre.proveedor,
            "nivel": sobre.nivel,
            "objeto_origen": sobre.objeto_origen,
            "objeto_origen_id": str(sobre.objeto_origen_id) if sobre.objeto_origen_id else "",
            "firmantes": [f.email for f in firmantes if f.papel != "copia"],
        },
    )
    return {
        "sobre_id": str(sobre.id),
        "estado": sobre.estado,
        "caduca_at": sobre.caduca_at.isoformat(),
    }


def _firmantes(db: Session, sobre: Sobre) -> list[Firmante]:
    return list(
        db.execute(select(Firmante).where(Firmante.sobre_id == sobre.id).order_by(Firmante.orden))
        .scalars()
        .all()
    )


def a_quien_le_toca(db: Session, sobre: Sobre) -> list[Firmante]:
    """A quién le toca firmar ahora.

    Con orden estricto, solo al siguiente que falta: es lo que hace que un
    contrato lo firme el cliente **después** de que lo firme el nuestro, que es
    justo el orden que pide la gente que redacta contratos. Sin orden estricto,
    a todos a la vez.
    """
    firmantes = [f for f in _firmantes(db, sobre) if f.papel != "copia"]
    pendientes = [f for f in firmantes if f.estado in ("pendiente", "abierto")]
    if not sobre.orden_estricto:
        return pendientes
    return pendientes[:1]


# ── Ingesta de lo que dice el proveedor (CRM-06.01.02.03, .04) ────────────


def traducir_estado(proveedor: ProveedorFirma, crudo: str) -> tuple[str | None, str]:
    """Traduce el estado del proveedor al del sistema.

    Un estado desconocido **no se adivina**: suponer que «completed» de un
    proveedor nuevo significa firmado haría dar por firmado un sobre que fue
    rechazado, y con eso se factura.
    """
    mapa = {str(k).strip().lower(): str(v) for k, v in (proveedor.mapa_estados or {}).items()}
    destino = mapa.get(str(crudo).strip().lower())
    if destino is None:
        return None, (
            f"«{crudo}» no está en el mapa de estados de «{proveedor.clave}». "
            "Añádelo para que el seguimiento de la firma lo entienda."
        )
    if destino not in (*ESTADOS_SOBRE, *ESTADOS_FIRMANTE):
        return None, (
            f"El mapa de «{proveedor.clave}» traduce «{crudo}» a «{destino}», que "
            "no es un estado del sistema."
        )
    return destino, ""


def ingerir(
    uow: UnidadDeTrabajo,
    *,
    proveedor: str,
    referencia_externa: str = "",
    referencia: str = "",
    estado_proveedor: str = "",
    email_firmante: str = "",
    ocurrio_at: datetime | None = None,
    id_externo: str = "",
    ip: str = "",
    agente: str = "",
    motivo: str = "",
    crudo: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aplica un aviso del proveedor, venga de webhook o de sondeo.

    **Idempotente** por el identificador del evento: las pasarelas reintentan, y
    sin esto la cadena de custodia tendría el mismo acceso dos veces, que es
    exactamente lo que un perito mira para decidir si la evidencia es fiable.
    """
    tenant_id = uow.tenant_id
    ficha = _proveedor(uow.db, tenant_id, proveedor)

    consulta = select(Sobre).where(Sobre.tenant_id == tenant_id, Sobre.proveedor == proveedor)
    if referencia:
        consulta = consulta.where(Sobre.referencia == referencia)
    elif referencia_externa:
        consulta = consulta.where(Sobre.referencia_externa == referencia_externa)
    else:
        raise ErrorValidacion(
            "Hace falta una referencia para saber de qué sobre se habla.",
            error_code="firma.evento_sin_referencia",
        )
    sobre = uow.db.execute(consulta).scalar_one_or_none()
    if sobre is None:
        raise NoEncontrado(
            "No hay ningún sobre con esa referencia para ese proveedor",
            error_code="firma.sobre_no_encontrado",
        )

    if id_externo:
        ya = uow.db.execute(
            select(EvidenciaFirma).where(
                EvidenciaFirma.tenant_id == tenant_id,
                EvidenciaFirma.sobre_id == sobre.id,
                EvidenciaFirma.id_externo == id_externo,
            )
        ).scalar_one_or_none()
        if ya is not None:
            return {"aplicado": False, "duplicado": True, "estado": sobre.estado}

    destino, aviso = traducir_estado(ficha, estado_proveedor)
    firmante = None
    if email_firmante:
        firmante = uow.db.execute(
            select(Firmante).where(Firmante.sobre_id == sobre.id, Firmante.email == email_firmante)
        ).scalar_one_or_none()

    # La evidencia se guarda SIEMPRE, se entienda o no el estado. Es la cadena de
    # custodia: perder un acceso porque no supimos traducir su nombre deja un
    # hueco que después no se puede rellenar.
    _anotar(
        uow.db,
        sobre,
        destino if destino in ("abierto", "firmado", "rechazado", "entregado") else "error",
        firmante_id=firmante.id if firmante else None,
        descripcion=aviso or f"{proveedor}: {estado_proveedor}",
        ocurrio_at=ocurrio_at,
        id_externo=id_externo,
        ip=ip,
        agente=agente,
        crudo=crudo or {},
    )
    sobre.ultima_novedad_at = _ahora()

    if destino is None:
        logger.warning(
            "firma.estado_sin_mapear",
            proveedor=proveedor,
            estado=estado_proveedor,
            sobre=str(sobre.id),
        )
        uow.db.flush()
        return {"aplicado": False, "duplicado": False, "estado": sobre.estado, "aviso": aviso}

    if firmante is not None and destino in ESTADOS_FIRMANTE:
        firmante.estado = destino
        if destino == "firmado":
            firmante.firmado_at = _con_tz(ocurrio_at) or _ahora()
        if destino == "rechazado":
            firmante.motivo_rechazo = motivo or "Sin motivo declarado"

    resultado = _recalcular(uow, sobre)
    uow.db.flush()
    return {"aplicado": True, "duplicado": False, **resultado}


def _recalcular(uow: UnidadDeTrabajo, sobre: Sobre) -> dict[str, Any]:
    """Recalcula el estado del sobre a partir del de sus firmantes."""
    if sobre.estado in TERMINALES:
        return {"estado": sobre.estado}

    firmantes = [f for f in _firmantes(uow.db, sobre) if f.papel != "copia"]
    if any(f.estado == "rechazado" for f in firmantes):
        # Un solo rechazo cierra el sobre. No se sigue pidiendo firmas: el
        # documento ya no se puede completar, y seguir mandando recordatorios a
        # los demás es hacerles perder el tiempo con algo muerto.
        sobre.estado = "rechazado"
        sobre.completado_at = _ahora()
        _anotar(uow.db, sobre, "rechazado", descripcion="Un firmante ha rechazado")
        uow.emitir(
            "signature.envelope.rejected",
            subject=("sobre", sobre.id),
            data={
                "sobre_id": str(sobre.id),
                "referencia": sobre.referencia,
                "objeto_origen": sobre.objeto_origen,
                "objeto_origen_id": str(sobre.objeto_origen_id) if sobre.objeto_origen_id else "",
                "motivo": next(
                    (f.motivo_rechazo for f in firmantes if f.estado == "rechazado"), ""
                ),
            },
        )
        return {"estado": sobre.estado}

    if firmantes and all(f.estado == "firmado" for f in firmantes):
        sobre.estado = "completado"
        sobre.completado_at = _ahora()
        _anotar(uow.db, sobre, "completado", descripcion="Todos han firmado")
        uow.emitir(
            "signature.envelope.completed",
            subject=("sobre", sobre.id),
            data={
                "sobre_id": str(sobre.id),
                "referencia": sobre.referencia,
                "objeto_origen": sobre.objeto_origen,
                "objeto_origen_id": str(sobre.objeto_origen_id) if sobre.objeto_origen_id else "",
                "firmantes": len(firmantes),
            },
        )
        return {"estado": sobre.estado}

    if any(f.estado in ("firmado", "abierto") for f in firmantes):
        sobre.estado = "en_curso"
    return {"estado": sobre.estado}


# ── El documento firmado vuelve (CRM-06.01.02.07) ─────────────────────────


def archivar_firmado(
    uow: UnidadDeTrabajo,
    sobre_id: UUID,
    *,
    documento_firmado_id: str,
    contenido: bytes | None = None,
    certificado_id: str = "",
    sello_tiempo: str = "",
) -> dict[str, Any]:
    """Archiva el documento firmado y su certificado, y los enlaza al origen.

    El firmado es **otro documento**, no una versión del original: el original
    tiene que seguir existiendo tal como salió, porque es la mitad de la prueba de
    que lo firmado es lo que se mandó.

    Se comprueba que el sobre esté completado. Archivar un «firmado» de un sobre
    que sigue abierto es cómo se acaba con un contrato a medio firmar en el
    expediente, con toda la apariencia de estar cerrado.
    """
    from crmcore.documental.enlaces import enlazar

    tenant_id = uow.tenant_id
    sobre = _sobre(uow.db, tenant_id, sobre_id)
    if sobre.estado != "completado":
        raise Conflicto(
            f"Ese sobre está «{sobre.estado}», no completado: lo que vuelva no es "
            "el documento firmado por todos.",
            error_code="firma.sobre_no_completado",
        )

    sobre.documento_firmado_id = documento_firmado_id
    sobre.certificado_id = certificado_id or None
    sobre.sello_tiempo = sello_tiempo or None
    if contenido is not None:
        sobre.hash_firmado = huella(contenido)
    uow.db.flush()

    enlazados = []
    if sobre.objeto_origen and sobre.objeto_origen_id:
        enlazados.append(
            enlazar(
                uow.db,
                tenant_id=tenant_id,
                objeto_tipo=sobre.objeto_origen,
                objeto_id=sobre.objeto_origen_id,
                documento_id=documento_firmado_id,
                titulo=sobre.asunto or sobre.referencia,
                tipo="firmado",
                rol="documento_firmado",
            ).id
        )
        if certificado_id:
            # El certificado se enlaza aparte y con su propio rol: es el
            # documento que se lleva a un juzgado, y mezclarlo con el contrato
            # hace que nadie lo encuentre cuando hace falta.
            enlazados.append(
                enlazar(
                    uow.db,
                    tenant_id=tenant_id,
                    objeto_tipo=sobre.objeto_origen,
                    objeto_id=sobre.objeto_origen_id,
                    documento_id=certificado_id,
                    titulo=f"Certificado de firma {sobre.referencia}",
                    tipo="certificado",
                    rol="certificado_firma",
                ).id
            )

    _anotar(
        uow.db,
        sobre,
        "completado",
        descripcion=f"Documento firmado archivado ({documento_firmado_id})",
    )
    registrar(
        uow.db,
        accion="firma.archivado",
        objeto="sobre",
        objeto_id=sobre.id,
        datos={
            "documento_firmado": documento_firmado_id,
            "certificado": certificado_id,
            "hash": sobre.hash_firmado,
        },
        tenant_id=tenant_id,
    )
    return {
        "sobre_id": str(sobre.id),
        "documento_firmado_id": documento_firmado_id,
        "certificado_id": certificado_id or None,
        "enlazados": [str(e) for e in enlazados],
        # Se dice si el sobre quedó SIN enlazar a nada: un firmado que no cuelga
        # de ningún registro existe en el corpus y no aparece en ninguna ficha.
        "sin_origen": not (sobre.objeto_origen and sobre.objeto_origen_id),
    }


def evidencia(db: Session, tenant_id: UUID, sobre_id: UUID) -> dict[str, Any]:
    """La cadena de custodia completa del sobre (CRM-06.01.02.04)."""
    sobre = _sobre(db, tenant_id, sobre_id)
    filas = (
        db.execute(
            select(EvidenciaFirma)
            .where(EvidenciaFirma.tenant_id == tenant_id, EvidenciaFirma.sobre_id == sobre.id)
            .order_by(EvidenciaFirma.ocurrio_at, EvidenciaFirma.registrado_at)
        )
        .scalars()
        .all()
    )
    firmantes = {f.id: f for f in _firmantes(db, sobre)}
    return {
        "referencia": sobre.referencia,
        "proveedor": sobre.proveedor,
        "nivel": sobre.nivel,
        "estado": sobre.estado,
        "documento_id": sobre.documento_id,
        "documento_firmado_id": sobre.documento_firmado_id,
        "certificado_id": sobre.certificado_id,
        "sello_tiempo": sobre.sello_tiempo,
        "hash_enviado": sobre.hash_enviado,
        "hash_firmado": sobre.hash_firmado,
        # Que las dos huellas existan es lo que hace verificable el expediente.
        # Se dice explícitamente en vez de dejar que quien lo lea lo deduzca.
        "verificable": bool(sobre.hash_enviado and sobre.hash_firmado),
        "firmantes": [
            {
                "nombre": f.nombre,
                "email": f.email,
                "papel": f.papel,
                "identificacion": f.identificacion,
                "estado": f.estado,
                "firmado_at": _con_tz(f.firmado_at).isoformat() if f.firmado_at else None,
                "motivo_rechazo": f.motivo_rechazo,
            }
            for f in firmantes.values()
        ],
        "eventos": [
            {
                "tipo": e.tipo,
                "descripcion": e.descripcion,
                "firmante": firmantes[e.firmante_id].email if e.firmante_id in firmantes else None,
                "ocurrio_at": _con_tz(e.ocurrio_at).isoformat(),
                "registrado_at": _con_tz(e.registrado_at).isoformat(),
                "ip": e.ip,
            }
            for e in filas
        ],
    }


# ── Recordatorios, cancelación y caducidad (CRM-06.01.02.03) ──────────────


def recordar(uow: UnidadDeTrabajo, sobre_id: UUID, *, minimo_horas: int = 24) -> dict[str, Any]:
    """Recuerda a quien le toca firmar.

    Con un mínimo entre recordatorios. Sin él, un botón pulsado tres veces manda
    tres correos al cliente en un minuto, y el resultado no es que firme antes:
    es que marque el remitente como no deseado y deje de recibir los siguientes.
    """
    tenant_id = uow.tenant_id
    sobre = _sobre(uow.db, tenant_id, sobre_id)
    if sobre.estado in TERMINALES:
        raise Conflicto(
            f"Ese sobre está «{sobre.estado}»: no hay a quién recordar.",
            error_code="firma.sobre_terminado",
        )
    ultimo = _con_tz(sobre.ultimo_recordatorio_at)
    if ultimo and (_ahora() - ultimo) < timedelta(hours=minimo_horas):
        raise Conflicto(
            f"Ya se recordó hace menos de {minimo_horas} horas.",
            error_code="firma.recordatorio_demasiado_pronto",
            detalle={"ultimo": ultimo.isoformat()},
        )

    destinatarios = a_quien_le_toca(uow.db, sobre)
    if not destinatarios:
        return {"recordados": [], "medible": False}

    sobre.ultimo_recordatorio_at = _ahora()
    for firmante in destinatarios:
        _anotar(
            uow.db,
            sobre,
            "recordado",
            firmante_id=firmante.id,
            descripcion=f"Recordatorio a {firmante.email}",
        )
    uow.db.flush()
    uow.emitir(
        "signature.reminder.sent",
        subject=("sobre", sobre.id),
        data={
            "sobre_id": str(sobre.id),
            "referencia": sobre.referencia,
            "destinatarios": [f.email for f in destinatarios],
        },
    )
    return {"recordados": [f.email for f in destinatarios], "medible": True}


def cancelar(uow: UnidadDeTrabajo, sobre_id: UUID, *, motivo: str = "") -> dict[str, Any]:
    """Cancela el sobre. Se exige motivo.

    Un sobre cancelado sin motivo deja al cliente con un correo que ya no
    funciona y a nadie que sepa por qué, y la pregunta llega por teléfono.
    """
    if not motivo.strip():
        raise ErrorValidacion(
            "Cancelar un sobre exige decir por qué: al cliente le llegó un correo "
            "que va a dejar de funcionar.",
            error_code="firma.cancelacion_sin_motivo",
        )
    tenant_id = uow.tenant_id
    sobre = _sobre(uow.db, tenant_id, sobre_id)
    if sobre.estado in TERMINALES:
        raise Conflicto(f"Ese sobre ya está «{sobre.estado}».", error_code="firma.sobre_terminado")
    sobre.estado = "cancelado"
    sobre.completado_at = _ahora()
    _anotar(uow.db, sobre, "cancelado", descripcion=motivo)
    uow.db.flush()
    uow.emitir(
        "signature.envelope.cancelled",
        subject=("sobre", sobre.id),
        data={
            "sobre_id": str(sobre.id),
            "referencia": sobre.referencia,
            "objeto_origen": sobre.objeto_origen,
            "objeto_origen_id": str(sobre.objeto_origen_id) if sobre.objeto_origen_id else "",
            "motivo": motivo,
        },
    )
    return {"sobre_id": str(sobre.id), "estado": sobre.estado}


def caducar_vencidos(uow: UnidadDeTrabajo, tenant_id: UUID) -> dict[str, Any]:
    """Marca caducados los sobres que pasaron su plazo.

    Hace falta como paso explícito: un sobre que sigue diciendo «en curso» tres
    meses después aparece en el panel como negocio vivo esperando una firma que
    ya no va a llegar.
    """
    ahora = _ahora()
    abiertos = (
        uow.db.execute(
            select(Sobre).where(
                Sobre.tenant_id == tenant_id,
                Sobre.estado.not_in(TERMINALES),
                Sobre.caduca_at.isnot(None),
            )
        )
        .scalars()
        .all()
    )
    caducados = []
    for sobre in abiertos:
        if _con_tz(sobre.caduca_at) < ahora:
            sobre.estado = "caducado"
            _anotar(uow.db, sobre, "caducado", descripcion="Pasó su plazo sin completarse")
            caducados.append(sobre.referencia)
            uow.emitir(
                "signature.envelope.expired",
                subject=("sobre", sobre.id),
                data={
                    "sobre_id": str(sobre.id),
                    "referencia": sobre.referencia,
                    "objeto_origen": sobre.objeto_origen,
                    "objeto_origen_id": str(sobre.objeto_origen_id)
                    if sobre.objeto_origen_id
                    else "",
                },
                dedup_key=f"caducado:{sobre.id}",
            )
    uow.db.flush()
    return {"revisados": len(abiertos), "caducados": caducados, "medible": bool(abiertos)}


# ── El panel (CRM-06.01.02.10) ────────────────────────────────────────────


def panel(db: Session, tenant_id: UUID, *, limite: int = 100) -> dict[str, Any]:
    """Lo que está esperando una firma, con su antigüedad y a quién frena.

    Ordenado por **antigüedad y no por fecha de creación**: lo que lleva más
    esperando es lo que hay que empujar, y una lista por fecha entierra lo viejo
    debajo de lo nuevo, que es justo al revés de lo que hace falta.

    Se dice **qué está bloqueando** cada sobre: sin el nombre de quien tiene que
    firmar, el panel dice que algo está parado y no qué hacer al respecto.
    """
    ahora = _ahora()
    abiertos = (
        db.execute(
            select(Sobre)
            .where(Sobre.tenant_id == tenant_id, Sobre.estado.not_in(TERMINALES))
            .order_by(Sobre.enviado_at.nulls_last())
            .limit(limite)
        )
        .scalars()
        .all()
    )
    filas = []
    for sobre in abiertos:
        pendientes = a_quien_le_toca(db, sobre)
        desde = _con_tz(sobre.enviado_at) or _con_tz(sobre.created_at) or ahora
        caduca = _con_tz(sobre.caduca_at)
        firmados = len([f for f in _firmantes(db, sobre) if f.estado == "firmado"])
        total = len([f for f in _firmantes(db, sobre) if f.papel != "copia"])
        filas.append(
            {
                "sobre_id": str(sobre.id),
                "referencia": sobre.referencia,
                "asunto": sobre.asunto,
                "estado": sobre.estado,
                "nivel": sobre.nivel,
                "proveedor": sobre.proveedor,
                "objeto_origen": sobre.objeto_origen,
                "objeto_origen_id": str(sobre.objeto_origen_id) if sobre.objeto_origen_id else None,
                "dias_esperando": (ahora - desde).days,
                "firmados": firmados,
                "total": total,
                "esperando_a": [f.email for f in pendientes],
                "caduca_en_dias": (caduca - ahora).days if caduca else None,
                # Un sobre que nadie ha abierto es distinto de uno abierto y no
                # firmado: el primero es un correo que no llegó, el segundo es
                # una decisión que no se toma, y se persiguen de forma distinta.
                "nadie_lo_ha_abierto": firmados == 0
                and not any(f.estado == "abierto" for f in _firmantes(db, sobre)),
            }
        )
    filas.sort(key=lambda f: -f["dias_esperando"])
    return {
        "sobres": filas,
        "cuantos": len(filas),
        # Sin sobres abiertos no se dice «todo firmado»: es que no hay nada
        # esperando, y un verde vacío se lee igual que uno ganado.
        "medible": bool(filas),
    }
