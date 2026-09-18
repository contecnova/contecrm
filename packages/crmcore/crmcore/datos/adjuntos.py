"""Gestión documental: adjuntos de cualquier objeto (CRM-06.01.01.05).

Un adjunto cuelga de **cualquier** registro —una cuenta, un caso, una
oportunidad— y por eso vive en el núcleo: repetir la tabla en cada servicio
significaría repetir también el versionado, el control de tipos, la
deduplicación y los enlaces firmados, con cinco variantes ligeramente
distintas de cada cosa.

Tres decisiones que conviene entender:

**El fichero no se guarda en la base.** En la base va el metadato; los bytes van
al almacén (`crmcore.almacen`). Un `bytea` de 25 MB por adjunto infla los
backups, satura la caché de Postgres y convierte cada `pg_dump` en una hora.

**Se versiona, no se pisa.** Subir un fichero con el mismo nombre crea una
versión nueva y la anterior sigue accesible. En un CRM el «contrato_final_v2»
existe precisamente porque el sistema no versionaba.

**La deduplicación es por contenido (SHA-256), y es exacta.** A diferencia de la
deduplicación de cuentas —donde la clave canónica es un *candidato* y nunca una
prueba—, aquí dos ficheros con el mismo hash son el mismo fichero. Se guarda una
copia y las dos fichas apuntan a ella; borrar una no borra los bytes mientras
otra los referencie.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.db.base import Base, EntidadBase, SoftDeleteMixin
from crmcore.errors import CuotaAgotada, ErrorValidacion, NoEncontrado, Prohibido
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger

logger = get_logger(__name__)


class Adjunto(EntidadBase, SoftDeleteMixin):
    """Un documento asociado a un registro.

    `objeto_tipo` + `objeto_id` en vez de una clave ajena: el adjunto tiene que
    poder colgar de objetos que viven en otros servicios y otros esquemas, donde
    una clave ajena no se puede declarar. El precio es que la integridad la
    mantiene el borrado en cascada de la papelera, no el motor.
    """

    __tablename__ = "adjuntos"

    objeto_tipo: Mapped[str] = mapped_column(String(60), nullable=False)
    objeto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    nombre: Mapped[str] = mapped_column(String(300), nullable=False)
    extension: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    # Lo que DECLARA el cliente. No se usa para decidir nada de seguridad: se
    # puede poner lo que sea. La extensión, que sí se valida contra la lista
    # blanca, es la que manda.
    tipo_mime: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    tamano: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    uri: Mapped[str] = mapped_column(String(1000), nullable=False)

    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    # Cabeza de la cadena de versiones. La versión 1 se apunta a sí misma, así
    # que «dame todas las versiones» es una sola consulta por `documento_id` sin
    # recorrer punteros.
    documento_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False, default=nuevo_id
    )
    es_actual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    etiquetas: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    # pendiente | limpio | infectado | omitido
    analisis: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    analisis_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    analisis_detalle: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        Index("ix_adjuntos_objeto", "tenant_id", "objeto_tipo", "objeto_id", "es_actual"),
        Index("ix_adjuntos_documento", "tenant_id", "documento_id", "version"),
        Index("ix_adjuntos_hash", "tenant_id", "sha256"),
    )


class DescargaAdjunto(Base):
    """Quién se descargó qué y cuándo (CRM-07.03.01.04).

    Es lo primero que pide una investigación de fuga de datos, y no se puede
    reconstruir a posteriori: o se registró entonces, o no existe.
    """

    __tablename__ = "descargas_adjunto"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    adjunto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    usuario_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    ip: Mapped[str] = mapped_column(String(45), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_descargas_adjunto", "tenant_id", "adjunto_id", "created_at"),)


def _extension_de(nombre: str) -> str:
    return nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""


def validar(nombre: str, datos: bytes, db: Session | None = None) -> None:
    """Comprueba extensión y tamaño ANTES de tocar el almacén.

    Primero la extensión y luego el tamaño: rechazar un `.exe` de 3 KB por
    extensión es más informativo que rechazarlo por tamaño, y al revés no
    aporta nada.
    """
    from crmcore.runtime import settings as rt

    extension = _extension_de(nombre)
    permitidas = rt.efectivo("adjunto_extensiones", db) or []
    if extension not in {str(e).lower().lstrip(".") for e in permitidas}:
        raise ErrorValidacion(
            f"No se admiten ficheros «.{extension}»",
            error_code="adjunto.extension_no_admitida",
            detalle={"extension": extension, "admitidas": sorted(permitidas)},
        )

    max_mb = int(rt.efectivo("adjunto_max_mb", db) or 25)
    if len(datos) > max_mb * 1024 * 1024:
        raise CuotaAgotada(
            f"El fichero ocupa {len(datos) / 1024 / 1024:.1f} MB y el máximo son {max_mb} MB",
            error_code="adjunto.demasiado_grande",
            detalle={"tamano_mb": round(len(datos) / 1024 / 1024, 1), "max_mb": max_mb},
        )
    if not datos:
        raise ErrorValidacion("El fichero está vacío", error_code="adjunto.fichero_vacio")


def subir(
    db: Session,
    *,
    tenant_id: UUID,
    objeto_tipo: str,
    objeto_id: UUID,
    nombre: str,
    datos: bytes,
    tipo_mime: str = "",
    descripcion: str = "",
    etiquetas: list[str] | None = None,
    usuario_id: UUID | None = None,
    documento_id: UUID | None = None,
) -> Adjunto:
    """Sube un fichero y lo asocia a un registro.

    Con `documento_id` crea una **versión nueva** del documento existente y
    marca la anterior como no actual. Sin él, un documento nuevo.

    La clave en el almacén lleva el tenant delante (`<tenant>/<hash[:2]>/<hash>`)
    por dos motivos: separa los ficheros de cada cliente en el almacén —lo que
    permite borrarlos de golpe al darlo de baja— y el troceado por los dos
    primeros caracteres del hash evita el directorio con cien mil entradas que
    hace lento a cualquier sistema de ficheros.
    """
    from crmcore.almacen import get_almacen
    from crmcore.runtime import settings as rt

    validar(nombre, datos, db)
    sha = hashlib.sha256(datos).hexdigest()

    uri: str | None = None
    if bool(rt.efectivo("adjunto_deduplicar", db)):
        gemelo = db.execute(
            select(Adjunto).where(Adjunto.tenant_id == tenant_id, Adjunto.sha256 == sha).limit(1)
        ).scalar_one_or_none()
        if gemelo is not None:
            # Mismos bytes: se reutiliza la URI y no se escribe nada. La
            # deduplicación **no cruza tenants**, aunque el hash coincida:
            # compartir el objeto entre clientes haría que el borrado de uno
            # afectara al otro, y que el almacén de uno contuviera dato del otro.
            uri = gemelo.uri
            logger.info("adjunto.deduplicado", sha256=sha[:12], tenant=str(tenant_id))

    if uri is None:
        clave = f"{tenant_id}/{sha[:2]}/{sha}"
        uri = get_almacen().guardar(clave, datos)

    version = 1
    doc_id = documento_id or nuevo_id()
    if documento_id is not None:
        anteriores = (
            db.execute(
                select(Adjunto).where(
                    Adjunto.tenant_id == tenant_id, Adjunto.documento_id == documento_id
                )
            )
            .scalars()
            .all()
        )
        if not anteriores:
            raise NoEncontrado(
                "No existe ese documento para versionarlo",
                error_code="adjunto.documento_no_existe",
            )
        version = max(a.version for a in anteriores) + 1
        for a in anteriores:
            a.es_actual = False

    fila = Adjunto(
        tenant_id=tenant_id,
        objeto_tipo=objeto_tipo,
        objeto_id=objeto_id,
        nombre=nombre,
        extension=_extension_de(nombre),
        tipo_mime=tipo_mime,
        tamano=len(datos),
        sha256=sha,
        uri=uri,
        version=version,
        documento_id=doc_id,
        es_actual=True,
        descripcion=descripcion,
        etiquetas=etiquetas or [],
        analisis="pendiente" if rt.efectivo("adjunto_analizador_url", db) else "omitido",
        created_by=usuario_id,
    )
    db.add(fila)
    db.flush()

    _podar_versiones(db, tenant_id, doc_id)
    logger.info(
        "adjunto.subido",
        adjunto=str(fila.id),
        objeto=f"{objeto_tipo}:{objeto_id}",
        tamano=len(datos),
        version=version,
    )
    return fila


def _podar_versiones(db: Session, tenant_id: UUID, documento_id: UUID) -> None:
    """Borra las versiones más viejas que excedan el tope configurado.

    Borrado **lógico**: lo que sobra deja de listarse, pero los bytes siguen ahí
    hasta que la purga los recoja. Un tope de versiones no es una orden de
    destrucción inmediata, y si alguien lo baja de 50 a 5 por error tiene que
    poder deshacerlo.
    """
    from crmcore.runtime import settings as rt

    tope = int(rt.efectivo("adjunto_max_versiones", db) or 0)
    if tope <= 0:
        return
    versiones = (
        db.execute(
            select(Adjunto)
            .where(
                Adjunto.tenant_id == tenant_id,
                Adjunto.documento_id == documento_id,
                Adjunto.deleted_at.is_(None),
            )
            .order_by(Adjunto.version.desc())
        )
        .scalars()
        .all()
    )
    ahora = datetime.now(timezone.utc)
    for sobrante in versiones[tope:]:
        sobrante.deleted_at = ahora
        logger.info("adjunto.version_podada", adjunto=str(sobrante.id), version=sobrante.version)


def leer(db: Session, adjunto_id: UUID, *, usuario_id: UUID | None = None, ip: str = "") -> bytes:
    """Devuelve los bytes y registra la descarga.

    Si el análisis está activo y el fichero no ha pasado por él, **no se
    entrega**: entregar lo no analizado convierte el CRM en el sitio desde el
    que se distribuye el fichero a toda la empresa.
    """
    from crmcore.almacen import get_almacen
    from crmcore.runtime import settings as rt

    fila = db.get(Adjunto, adjunto_id)
    if fila is None or fila.deleted_at is not None:
        raise NoEncontrado("Adjunto no encontrado", error_code="adjunto.no_existe")

    if fila.analisis == "infectado":
        raise Prohibido(
            "El antivirus marcó este fichero como infectado",
            error_code="adjunto.infectado",
        )
    if bool(rt.efectivo("adjunto_exigir_analisis", db)) and fila.analisis not in ("limpio",):
        raise Prohibido(
            "El fichero todavía no ha pasado el análisis antivirus",
            error_code="adjunto.analisis_pendiente",
        )

    db.add(
        DescargaAdjunto(tenant_id=fila.tenant_id, adjunto_id=fila.id, usuario_id=usuario_id, ip=ip)
    )
    return get_almacen().leer(fila.uri)


def borrar(db: Session, adjunto_id: UUID, *, usuario_id: UUID | None = None) -> Adjunto:
    """Borrado lógico. Los bytes se quedan hasta la purga.

    No se borra del almacén aquí, y no es pereza: el mismo objeto puede estar
    referenciado por otros adjuntos por deduplicación. Quitar los bytes mientras
    otra ficha los apunta convierte esa ficha en un enlace roto silencioso.
    """
    fila = db.get(Adjunto, adjunto_id)
    if fila is None or fila.deleted_at is not None:
        raise NoEncontrado("Adjunto no encontrado", error_code="adjunto.no_existe")
    fila.deleted_at = datetime.now(timezone.utc)
    fila.deleted_by = usuario_id
    fila.es_actual = False
    return fila


def purgar_huerfanos(db: Session, tenant_id: UUID) -> int:
    """Borra del almacén los bytes que ya no referencia ningún adjunto vivo.

    Se ejecuta aparte del borrado —y no en él— exactamente por la deduplicación:
    solo mirando **todas** las filas se puede saber si un objeto quedó sin
    dueño. Hacerlo en el borrado exigiría contar referencias en caliente.
    """
    from crmcore.almacen import get_almacen

    vivos = set(
        db.execute(
            select(Adjunto.uri).where(Adjunto.tenant_id == tenant_id, Adjunto.deleted_at.is_(None))
        )
        .scalars()
        .all()
    )
    muertos = set(
        db.execute(
            select(Adjunto.uri).where(
                Adjunto.tenant_id == tenant_id, Adjunto.deleted_at.is_not(None)
            )
        )
        .scalars()
        .all()
    )
    almacen = get_almacen()
    borrados = 0
    for uri in muertos - vivos:
        try:
            almacen.borrar(uri)
            borrados += 1
        except (OSError, ValueError) as exc:
            # Un fallo al borrar un objeto no puede abortar la purga entera: el
            # resto de huérfanos seguiría ocupando espacio por culpa de uno.
            logger.warning("adjunto.purga_fallida", uri=uri, error=str(exc))
    logger.info("adjunto.purga", tenant=str(tenant_id), borrados=borrados)
    return borrados


def firmar_enlace(
    adjunto_id: UUID, *, usuario_id: UUID | None = None, db: Session | None = None
) -> str:
    """Token firmado y caducable para descargar sin cabecera de autorización.

    Hace falta para los `<img src>` y para los enlaces de un correo, donde no se
    pueden poner cabeceras. Lleva **el usuario dentro**: un enlace reenviado
    sigue atribuyendo la descarga a quien lo pidió, así que el registro de
    descargas no se vuelve inútil en cuanto alguien comparte una URL.
    """
    import hmac

    from crmcore.config import get_settings
    from crmcore.runtime import settings as rt

    s = get_settings()
    ttl = int(rt.efectivo("adjunto_enlace_ttl_s", db) or 300)
    caduca = int((datetime.now(timezone.utc) + timedelta(seconds=ttl)).timestamp())
    payload = f"{adjunto_id}:{usuario_id or ''}:{caduca}"
    firma = hmac.new(
        s.secret_key.get_secret_value().encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return f"{payload}:{firma}"


def verificar_enlace(token: str) -> tuple[UUID, UUID | None]:
    """Valida un enlace firmado y devuelve (adjunto, usuario).

    Compara con `compare_digest`: una comparación normal tarda distinto según
    cuántos caracteres coinciden, y eso basta para reconstruir la firma byte a
    byte con suficientes intentos.
    """
    import hmac

    from crmcore.config import get_settings

    partes = token.split(":")
    if len(partes) != 4:
        raise Prohibido("Enlace mal formado", error_code="adjunto.enlace_invalido")
    adjunto, usuario, caduca, firma = partes

    s = get_settings()
    esperada = hmac.new(
        s.secret_key.get_secret_value().encode(),
        f"{adjunto}:{usuario}:{caduca}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(firma, esperada):
        raise Prohibido("Enlace no válido", error_code="adjunto.enlace_invalido")
    if int(caduca) < int(datetime.now(timezone.utc).timestamp()):
        raise Prohibido("El enlace ha caducado", error_code="adjunto.enlace_caducado")

    return UUID(adjunto), UUID(usuario) if usuario else None
