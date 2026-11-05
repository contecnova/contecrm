"""El código del tenant, con datos (CRM-00.04.02.01, .04, .05, .06, .07).

Lo que había eran cálculos sueltos —si un consumo se pasa, si una firma vale,
cómo va una extensión con las ejecuciones que le mandara quien preguntaba— y
ninguna ejecución. Aquí está lo que les faltaba:

- **Extensiones con versiones que no se pisan** (`.05`). Publicar crea la
  versión siguiente, inmutable; lo que se ejecuta es la ACTIVA, y volver atrás
  es activar la anterior entera, no deshacer cambios.
- **Ejecución aislada y con cuota** (`.01`): en el motor de `motor_js`, con los
  topes de `EXTENSIONES_*`, y con la cuota mensual `cuota_extensiones_mes`. La
  función no escribe: **devuelve las acciones** que quiere y la plataforma las
  hace con los permisos que la extensión declaró —nunca más que los de quien la
  dio de alta— y hasta `EXTENSIONES_ACCIONES_MAX`.
- **Cada ejecución queda apuntada** (`.06`): cuándo, cuánto tardó, cuánto
  combustible, si falló o se cortó y por qué, sus `console.log`, la entrada y lo
  que cuesta. La observabilidad sale de esas filas.
- **Las de terceros se firman y se revisan** (`.07`). La firma es Ed25519 sobre
  la huella del código, con la clave pública de un firmante que el tenant ha
  dado por bueno; y además la revisa una persona que **no** es quien la
  publicó. Sin las dos cosas no se puede activar.
- **Endpoints propios** (`.04`): un método y una ruta del tenant, servidos por
  el gateway en `/api/v1/propios/...`, que ejecutan una extensión con lo que
  llega y contestan lo que ella devuelve.
"""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.audit.chain import registrar
from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado, Prohibido
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    delete,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from services.automation import motor_js

logger = get_logger(__name__)

RE_CLAVE = re.compile(r"^[a-z][a-z0-9_-]{1,79}$")
RE_RUTA = re.compile(r"^[a-z0-9][a-z0-9_-]*(/[a-z0-9][a-z0-9_-]*){0,7}$")
METODOS_ENDPOINT = ("GET", "POST", "PUT", "PATCH", "DELETE")
METODOS_ACCION = ("POST", "PUT", "PATCH", "DELETE")
# Lo que una acción no puede tocar: el propio código del tenant. Una extensión
# que publica o activa extensiones, o que llama a un endpoint que la ejecuta a
# ella, es un bucle que ningún tope de una ejecución sola ve.
RUTAS_VEDADAS = ("/api/v1/extensiones", "/api/v1/propios")


class Extension(Base, TimestampMixin, SoftDeleteMixin):
    """Una función del tenant, con su versión activa."""

    __tablename__ = "extensiones"
    __table_args__ = (
        Index(
            "uq_extensiones_tenant_clave",
            "tenant_id",
            "clave",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    # `propia` la escribe el tenant; `tercero` viene de fuera y exige firma y
    # revisión antes de poder activarse.
    origen: Mapped[str] = mapped_column(String(20), nullable=False, default="propia")
    # Con qué permisos se hacen las acciones que devuelve. Nunca más que los de
    # quien la dio de alta: se comprueba al crearla.
    permisos: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    version_activa: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)


class FirmanteExtension(Base, TimestampMixin, SoftDeleteMixin):
    """Alguien cuyas extensiones firmadas este tenant acepta revisar."""

    __tablename__ = "firmantes_extension"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    # La clave pública Ed25519, 32 bytes en base64. Es lo único que hace falta
    # para comprobar una firma, y no sirve para firmar.
    clave_publica: Mapped[str] = mapped_column(String(64), nullable=False)
    huella_clave: Mapped[str] = mapped_column(String(64), nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class VersionExtension(Base, TimestampMixin):
    """Una versión publicada. No se edita nunca: se publica otra."""

    __tablename__ = "versiones_extension"
    __table_args__ = (UniqueConstraint("extension_id", "version"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    extension_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("extensiones.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    codigo: Mapped[str] = mapped_column(Text, nullable=False)
    huella: Mapped[str] = mapped_column(String(64), nullable=False)
    # Con qué motor se publicó. Si el motor cambia, se sabe con cuál se probó.
    motor_version: Mapped[str] = mapped_column(String(30), nullable=False)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    publicada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    firmante_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("firmantes_extension.id"), nullable=True
    )
    firma: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # `lista` (propia), `pendiente_revision` (de tercero, firma válida),
    # `revisada` o `rechazada`.
    estado: Mapped[str] = mapped_column(String(30), nullable=False, default="lista")
    revisada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    revisada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    nota_revision: Mapped[str | None] = mapped_column(Text, nullable=True)


class EjecucionExtension(Base):
    """Lo que queda de cada ejecución. Se purga a los `EXTENSIONES_EJECUCIONES_DIAS`."""

    __tablename__ = "ejecuciones_extension"
    __table_args__ = (
        Index("ix_ejecuciones_extension_cuando", "tenant_id", "extension_id", "cuando"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    extension_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("extensiones.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # `prueba` (desde su ficha, sin hacer las acciones) o `endpoint`.
    origen: Mapped[str] = mapped_column(String(20), nullable=False)
    cuando: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    quien: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    combustible: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    cortada_por: Mapped[str | None] = mapped_column(String(20), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    logs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    # Con qué se ejecutó: una extensión que falla con un registro concreto y no
    # guarda cuál obliga a reproducirlo a ciegas. La salida NO se guarda.
    entrada: Mapped[Any] = mapped_column(JSONB, nullable=True, info={"anonimizar_en_copias": True})
    acciones: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    acciones_fallidas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coste: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False, default=0)


class EndpointPropio(Base, TimestampMixin, SoftDeleteMixin):
    """Un método y una ruta del tenant que ejecutan una extensión."""

    __tablename__ = "endpoints_propios"
    __table_args__ = (
        Index(
            "uq_endpoints_propios_ruta",
            "tenant_id",
            "metodo",
            "ruta",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    metodo: Mapped[str] = mapped_column(String(10), nullable=False)
    ruta: Mapped[str] = mapped_column(String(200), nullable=False)
    extension_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("extensiones.id"), nullable=False
    )
    # El permiso que tiene que tener quien llama. Vacío: basta con entrar.
    permiso: Mapped[str | None] = mapped_column(String(80), nullable=True)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


# ── Extensiones y versiones ───────────────────────────────────────────────


def extension(db: Session, extension_id: UUID) -> Extension:
    fila = db.get(Extension, extension_id)
    if fila is None or fila.deleted_at is not None:
        raise NoEncontrado("Esa extensión no existe", error_code="extension.no_encontrada")
    return fila


def crear_extension(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    nombre: str,
    descripcion: str = "",
    origen: str = "propia",
    permisos: list[str],
    por: UUID | None,
    puede: Callable[[str], bool],
) -> Extension:
    clave = clave.strip().lower()
    if not RE_CLAVE.match(clave):
        raise ErrorValidacion(
            "La clave va en minúsculas, empieza por letra y lleva sólo letras, "
            "números, guiones o guiones bajos (2 a 80).",
            error_code="extension.clave_invalida",
        )
    if origen not in ("propia", "tercero"):
        raise ErrorValidacion("El origen es «propia» o «tercero»", error_code="extension.origen")
    pedidos = sorted({p.strip() for p in permisos if p.strip()})
    de_mas = [p for p in pedidos if not puede(p)]
    if de_mas:
        # Una extensión que actúa con más permisos que quien la creó es una
        # forma de darse permisos a uno mismo.
        raise Prohibido(
            f"La extensión no puede tener permisos que tú no tienes: {', '.join(de_mas)}",
            error_code="extension.permisos_de_mas",
            detalle={"de_mas": de_mas},
        )
    existe = uow.db.execute(
        select(Extension.id).where(
            Extension.tenant_id == uow.tenant_id,
            Extension.clave == clave,
            Extension.deleted_at.is_(None),
        )
    ).first()
    if existe:
        raise Conflicto(f"Ya hay una extensión «{clave}»", error_code="extension.ya_existe")
    fila = Extension(
        tenant_id=uow.tenant_id,
        clave=clave,
        nombre=nombre.strip(),
        descripcion=descripcion.strip() or None,
        origen=origen,
        permisos=pedidos,
        creada_por=por,
    )
    uow.db.add(fila)
    uow.db.flush()
    registrar(
        uow.db,
        accion="extension.creada",
        objeto="extension",
        objeto_id=fila.id,
        datos={"clave": clave, "origen": origen, "permisos": pedidos},
    )
    return fila


def _verificar_firma(firmante: FirmanteExtension, huella: str, firma: str) -> None:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        publica = Ed25519PublicKey.from_public_bytes(base64.b64decode(firmante.clave_publica))
        publica.verify(base64.b64decode(firma), huella.encode())
    except (InvalidSignature, ValueError) as exc:
        raise ErrorValidacion(
            "La firma no corresponde a este código con la clave de ese firmante. "
            "Puede ser una manipulación o un empaquetado distinto; en los dos "
            "casos, lo que se instalaría no es lo que se firmó.",
            error_code="extension.firma_invalida",
        ) from exc


def publicar_version(
    uow: UnidadDeTrabajo,
    extension_id: UUID,
    *,
    codigo: str,
    notas: str = "",
    firmante_id: UUID | None = None,
    firma: str = "",
    por: UUID | None,
) -> VersionExtension:
    """Publica la versión siguiente. No pisa ninguna, y no se activa sola."""
    ext = extension(uow.db, extension_id)
    if not codigo.strip():
        raise ErrorValidacion("El código está vacío", error_code="extension.codigo_vacio")
    huella = hashlib.sha256(codigo.encode()).hexdigest()
    estado = "lista"
    firmante = None
    if ext.origen == "tercero":
        if not firmante_id or not firma:
            raise ErrorValidacion(
                "Una extensión de terceros se publica con su firma y su firmante: "
                "sin firma, instalarla es ejecutar código de un desconocido.",
                error_code="extension.sin_firma",
            )
        firmante = uow.db.get(FirmanteExtension, firmante_id)
        if (
            firmante is None
            or firmante.tenant_id != uow.tenant_id
            or firmante.deleted_at is not None
            or not firmante.activo
        ):
            raise ErrorValidacion(
                "Ese firmante no está entre los de confianza de este tenant.",
                error_code="extension.firmante_desconocido",
            )
        _verificar_firma(firmante, huella, firma)
        estado = "pendiente_revision"
    ultima = uow.db.execute(
        select(func.max(VersionExtension.version)).where(VersionExtension.extension_id == ext.id)
    ).scalar()
    fila = VersionExtension(
        tenant_id=uow.tenant_id,
        extension_id=ext.id,
        version=int(ultima or 0) + 1,
        codigo=codigo,
        huella=huella,
        motor_version=motor_js.candado()["version"],
        notas=notas.strip() or None,
        publicada_por=por,
        firmante_id=firmante.id if firmante else None,
        firma=firma or None,
        estado=estado,
    )
    uow.db.add(fila)
    uow.db.flush()
    registrar(
        uow.db,
        accion="extension.version_publicada",
        objeto="extension",
        objeto_id=ext.id,
        datos={"version": fila.version, "huella": huella, "estado": estado},
    )
    return fila


def _version(db: Session, ext: Extension, version: int) -> VersionExtension:
    fila = db.execute(
        select(VersionExtension).where(
            VersionExtension.extension_id == ext.id, VersionExtension.version == version
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado(
            f"La extensión no tiene versión {version}", error_code="extension.version_no_existe"
        )
    return fila


def revisar_version(
    uow: UnidadDeTrabajo,
    extension_id: UUID,
    version: int,
    *,
    aprobar: bool,
    nota: str,
    por: UUID | None,
) -> VersionExtension:
    """La revisión de una persona, que no puede ser quien la publicó."""
    ext = extension(uow.db, extension_id)
    fila = _version(uow.db, ext, version)
    if fila.estado != "pendiente_revision":
        raise Conflicto(
            f"La versión {version} no está pendiente de revisión (está «{fila.estado}»).",
            error_code="extension.no_pendiente",
        )
    if por is not None and fila.publicada_por == por:
        raise Prohibido(
            "Quien la publicó no puede revisarla: la revisión es otro par de ojos.",
            error_code="extension.revision_propia",
        )
    if not nota.strip():
        raise ErrorValidacion(
            "La revisión lleva una nota: qué se ha mirado.",
            error_code="extension.revision_sin_nota",
        )
    fila.estado = "revisada" if aprobar else "rechazada"
    fila.revisada_por = por
    fila.revisada_at = datetime.now(timezone.utc)
    fila.nota_revision = nota.strip()
    uow.db.flush()
    registrar(
        uow.db,
        accion="extension.version_revisada",
        objeto="extension",
        objeto_id=ext.id,
        datos={"version": version, "aprobada": aprobar},
        motivo=nota.strip(),
    )
    return fila


def activar(
    uow: UnidadDeTrabajo, extension_id: UUID, version: int, *, motivo: str = ""
) -> Extension:
    ext = extension(uow.db, extension_id)
    fila = _version(uow.db, ext, version)
    if fila.estado not in ("lista", "revisada"):
        raise Conflicto(
            f"La versión {version} no se puede activar: está «{fila.estado}». Una de "
            "terceros necesita firma válida y revisión aprobada.",
            error_code="extension.no_activable",
        )
    anterior = ext.version_activa
    ext.version_activa = version
    uow.db.flush()
    registrar(
        uow.db,
        accion="extension.activada",
        objeto="extension",
        objeto_id=ext.id,
        datos={"desde": anterior, "hasta": version},
        motivo=motivo.strip() or None,
    )
    return ext


def volver_atras(uow: UnidadDeTrabajo, extension_id: UUID, *, motivo: str) -> Extension:
    """Activa la versión activable anterior a la activa, entera."""
    ext = extension(uow.db, extension_id)
    if ext.version_activa is None:
        raise Conflicto("No hay ninguna versión activa", error_code="extension.sin_activa")
    if not motivo.strip():
        raise ErrorValidacion(
            "Volver atrás lleva motivo: qué falló en la que se quita.",
            error_code="extension.sin_motivo",
        )
    anterior = uow.db.execute(
        select(VersionExtension.version)
        .where(
            VersionExtension.extension_id == ext.id,
            VersionExtension.version < ext.version_activa,
            VersionExtension.estado.in_(("lista", "revisada")),
        )
        .order_by(VersionExtension.version.desc())
        .limit(1)
    ).scalar()
    if anterior is None:
        raise Conflicto(
            "No hay una versión anterior que se pueda activar.",
            error_code="extension.sin_anterior",
        )
    return activar(uow, extension_id, int(anterior), motivo=motivo)


# ── Ejecutar ──────────────────────────────────────────────────────────────


def _ejecuciones_del_mes(db: Session, tenant_id: UUID) -> int:
    from crmcore.cuotas import inicio_del_periodo

    return int(
        db.execute(
            select(func.count())
            .select_from(EjecucionExtension)
            .where(
                EjecucionExtension.tenant_id == tenant_id,
                EjecucionExtension.cuando >= inicio_del_periodo(),
            )
        ).scalar()
        or 0
    )


def _acciones_validas(resultado: Any) -> tuple[list[dict[str, Any]], str]:
    """Las acciones que pide el resultado, o por qué no valen."""
    from crmcore.config import get_settings

    if not isinstance(resultado, dict) or "acciones" not in resultado:
        return [], ""
    pedidas = resultado.get("acciones")
    if not isinstance(pedidas, list):
        return [], "`acciones` tiene que ser una lista."
    maximo = get_settings().extensiones_acciones_max
    if len(pedidas) > maximo:
        return [], f"Pide {len(pedidas)} acciones y el tope por ejecución es {maximo}."
    salida = []
    for i, accion in enumerate(pedidas, start=1):
        if not isinstance(accion, dict):
            return [], f"La acción {i} no es un objeto."
        metodo = str(accion.get("metodo") or "").upper()
        ruta = str(accion.get("ruta") or "")
        if metodo not in METODOS_ACCION:
            return [], f"La acción {i} tiene método «{metodo}»: vale {', '.join(METODOS_ACCION)}."
        if not ruta.startswith("/api/v1/") or ".." in ruta:
            return [], f"La acción {i} no apunta a la API (`/api/v1/...`)."
        if ruta.startswith(RUTAS_VEDADAS):
            return [], (
                f"La acción {i} toca el código del tenant: una extensión que publica, "
                "activa o se llama a sí misma es un bucle que ningún tope ve."
            )
        cuerpo = accion.get("cuerpo")
        if cuerpo is not None and not isinstance(cuerpo, dict):
            return [], f"El cuerpo de la acción {i} tiene que ser un objeto."
        salida.append({"metodo": metodo, "ruta": ruta, "cuerpo": cuerpo})
    return salida, ""


def ejecutar(
    db: Session,
    ext: Extension,
    *,
    entrada: Any,
    origen: str,
    quien: UUID | None,
    version: int | None = None,
    hacer_acciones: bool = True,
) -> dict[str, Any]:
    """Ejecuta la versión activa —o la pedida, en una prueba— y lo apunta."""
    from crmcore import cuotas
    from crmcore.config import get_settings

    numero = version or ext.version_activa
    if numero is None:
        raise Conflicto(
            "La extensión no tiene ninguna versión activa.", error_code="extension.sin_activa"
        )
    fila_version = _version(db, ext, numero)
    if version is None and fila_version.estado not in ("lista", "revisada"):
        raise Conflicto(
            "La versión activa no se puede ejecutar", error_code="extension.no_activable"
        )
    if fila_version.estado == "rechazada":
        raise Conflicto("Esa versión está rechazada", error_code="extension.rechazada")

    cuotas.exigir(
        db,
        ext.tenant_id,
        clave="cuota_extensiones_mes",
        metrica="extensiones",
        contar=lambda: _ejecuciones_del_mes(db, ext.tenant_id),
        unidad="ejecuciones",
    )

    s = get_settings()
    resultado = motor_js.ejecutar(fila_version.codigo, entrada)
    acciones, por_que_no = (
        _acciones_validas(resultado.get("resultado")) if resultado["ok"] else ([], "")
    )
    if por_que_no:
        resultado = {**resultado, "ok": False, "error": por_que_no}
    hechas: list[dict[str, Any]] = []
    fallidas = 0
    if resultado["ok"] and acciones:
        if hacer_acciones:
            from crmcore.http.interno import invocar

            for accion in acciones:
                respuesta = invocar(
                    metodo=accion["metodo"],
                    ruta=accion["ruta"],
                    cuerpo=accion["cuerpo"],
                    tenant_id=ext.tenant_id,
                    principal_id=quien or ext.creada_por or ext.tenant_id,
                    permisos=list(ext.permisos),
                )
                estado = int(respuesta.get("estado") or 0)
                if estado >= 400:
                    fallidas += 1
                hechas.append({**accion, "estado": estado})
        else:
            hechas = [{**a, "estado": None} for a in acciones]

    coste = Decimal(str(round(resultado["ms"] / 1000 * s.extensiones_coste_por_segundo, 6)))
    db.add(
        EjecucionExtension(
            tenant_id=ext.tenant_id,
            extension_id=ext.id,
            version=numero,
            origen=origen,
            quien=quien,
            ms=resultado["ms"],
            combustible=resultado["combustible"],
            ok=bool(resultado["ok"]) and not fallidas,
            cortada_por=resultado.get("cortada_por"),
            error=(resultado.get("error") or None),
            logs=resultado.get("logs") or [],
            entrada=entrada,
            acciones=len(hechas) if hacer_acciones else 0,
            acciones_fallidas=fallidas,
            coste=coste,
        )
    )
    # La purga va con cada apunte: una tabla de ejecuciones que sólo crece es
    # la que acaba llenando el disco de un cliente que llama mucho.
    db.execute(
        delete(EjecucionExtension).where(
            EjecucionExtension.tenant_id == ext.tenant_id,
            EjecucionExtension.cuando
            < datetime.now(timezone.utc) - timedelta(days=s.extensiones_ejecuciones_dias),
        )
    )
    db.flush()
    return {
        "extension": ext.clave,
        "version": numero,
        "ok": bool(resultado["ok"]) and not fallidas,
        "resultado": resultado.get("resultado") if resultado["ok"] else None,
        "error": resultado.get("error") or "",
        "pila": resultado.get("pila") or "",
        "cortada_por": resultado.get("cortada_por"),
        "logs": resultado.get("logs") or [],
        "ms": resultado["ms"],
        "combustible": resultado["combustible"],
        "acciones": hechas,
        "acciones_hechas": hacer_acciones,
        "coste": float(coste),
    }


def observabilidad(db: Session, ext: Extension) -> dict[str, Any]:
    """Cómo va, con las ejecuciones guardadas. El cálculo es el de siempre."""
    from crmcore.config import get_settings

    from services.automation import extensiones as calculo

    filas = (
        db.execute(
            select(EjecucionExtension)
            .where(EjecucionExtension.extension_id == ext.id)
            .order_by(EjecucionExtension.cuando.desc())
        )
        .scalars()
        .all()
    )
    s = get_settings()
    salida = calculo.observabilidad(
        clave=ext.clave,
        ejecuciones=[
            {
                "cuando": f.cuando.isoformat() if f.cuando else None,
                "milisegundos": f.ms,
                "ok": f.ok,
                "cortada_por_limite": bool(f.cortada_por),
                "entrada": f.entrada,
            }
            for f in filas
        ],
        coste_por_segundo=s.extensiones_coste_por_segundo,
    )
    salida["dias"] = s.extensiones_ejecuciones_dias
    salida["version_activa"] = ext.version_activa
    salida["por_version"] = [
        {"version": v, "ejecuciones": n, "fallidas": m}
        for v, n, m in db.execute(
            select(
                EjecucionExtension.version,
                func.count(),
                func.count().filter(EjecucionExtension.ok.is_(False)),
            )
            .where(EjecucionExtension.extension_id == ext.id)
            .group_by(EjecucionExtension.version)
            .order_by(EjecucionExtension.version.desc())
        ).all()
    ]
    return salida


# ── Firmantes y endpoints ─────────────────────────────────────────────────


def alta_firmante(uow: UnidadDeTrabajo, *, nombre: str, clave_publica: str) -> FirmanteExtension:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        crudo = base64.b64decode(clave_publica.strip(), validate=True)
        Ed25519PublicKey.from_public_bytes(crudo)
    except ValueError as exc:
        raise ErrorValidacion(
            "La clave pública tiene que ser una Ed25519: 32 bytes en base64.",
            error_code="extension.clave_publica_invalida",
        ) from exc
    fila = FirmanteExtension(
        tenant_id=uow.tenant_id,
        nombre=nombre.strip(),
        clave_publica=base64.b64encode(crudo).decode(),
        huella_clave=hashlib.sha256(crudo).hexdigest(),
    )
    uow.db.add(fila)
    uow.db.flush()
    registrar(
        uow.db,
        accion="extension.firmante_dado_de_alta",
        objeto="firmante_extension",
        objeto_id=fila.id,
        datos={"nombre": fila.nombre, "huella_clave": fila.huella_clave},
    )
    return fila


def crear_endpoint(
    uow: UnidadDeTrabajo,
    *,
    metodo: str,
    ruta: str,
    extension_id: UUID,
    permiso: str = "",
    descripcion: str = "",
) -> EndpointPropio:
    metodo = metodo.strip().upper()
    ruta = ruta.strip().strip("/").lower()
    if metodo not in METODOS_ENDPOINT:
        raise ErrorValidacion(
            f"El método es uno de {', '.join(METODOS_ENDPOINT)}", error_code="endpoint.metodo"
        )
    if not RE_RUTA.match(ruta):
        raise ErrorValidacion(
            "La ruta va en minúsculas, por tramos de letras, números y guiones "
            "separados por «/» (hasta ocho).",
            error_code="endpoint.ruta_invalida",
        )
    extension(uow.db, extension_id)
    repetido = uow.db.execute(
        select(EndpointPropio.id).where(
            EndpointPropio.tenant_id == uow.tenant_id,
            EndpointPropio.metodo == metodo,
            EndpointPropio.ruta == ruta,
            EndpointPropio.deleted_at.is_(None),
        )
    ).first()
    if repetido:
        raise Conflicto(f"Ya hay un {metodo} /{ruta}", error_code="endpoint.ya_existe")
    fila = EndpointPropio(
        tenant_id=uow.tenant_id,
        metodo=metodo,
        ruta=ruta,
        extension_id=extension_id,
        permiso=permiso.strip() or None,
        descripcion=descripcion.strip() or None,
    )
    uow.db.add(fila)
    uow.db.flush()
    registrar(
        uow.db,
        accion="endpoint_propio.creado",
        objeto="endpoint_propio",
        objeto_id=fila.id,
        datos={"metodo": metodo, "ruta": ruta, "permiso": fila.permiso},
    )
    return fila


def resolver_endpoint(db: Session, tenant_id: UUID, metodo: str, ruta: str) -> EndpointPropio:
    fila = db.execute(
        select(EndpointPropio).where(
            EndpointPropio.tenant_id == tenant_id,
            EndpointPropio.metodo == metodo.upper(),
            EndpointPropio.ruta == ruta.strip("/").lower(),
            EndpointPropio.deleted_at.is_(None),
            EndpointPropio.activo.is_(True),
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado(
            f"No hay ningún {metodo.upper()} /{ruta.strip('/')} propio",
            error_code="endpoint.no_encontrado",
        )
    return fila
