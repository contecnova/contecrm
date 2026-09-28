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
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.db.base import Base, EntidadBase, SoftDeleteMixin, TimestampMixin
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

    # Carpeta del expediente en la que está (CRM-06.01.01.05). Nulo = en la
    # raíz del registro, que es donde cae todo mientras nadie organice nada —y
    # así tiene que ser: obligar a elegir carpeta al subir haría que la gente
    # dejara de adjuntar.
    carpeta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # ── Documento que vive fuera (CRM-06.01.01.05) ────────────────────────
    # Cuando el cliente guarda sus documentos en SharePoint, Drive o su gestor
    # documental, aquí se guarda **la referencia y el contexto**, no los bytes.
    #
    # No hay conector por proveedor y no lo va a haber: `externo_sistema` es una
    # etiqueta libre y `uri` un enlace. Escribir un conector de SharePoint sería
    # mantener su API, sus permisos y su autenticación para que el CRM enseñe un
    # enlace que el navegador del usuario ya sabe abrir — y el día que el cliente
    # use otro gestor, otra vez.
    #
    # El precio, dicho: el CRM NO controla el acceso a ese documento. Quien
    # tenga el enlace y permiso en el sistema de origen lo abre; quien no lo
    # tenga, no. Es correcto —cada sistema manda en lo suyo— y hay que saberlo
    # antes de guardar ahí un contrato.
    # `server_default` además del `default` de Python: la columna llegó a una
    # tabla que ya tenía filas, y un NOT NULL sin valor por defecto no se
    # puede añadir en una base con datos.
    externo_sistema: Mapped[str] = mapped_column(
        String(60), nullable=False, default="", server_default=""
    )

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
    ip: Mapped[str] = mapped_column(
        String(45), nullable=False, default="", info={"sensibilidad": "personal"}
    )
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


def espacio_ocupado(db: Session, tenant_id: UUID) -> int:
    """Bytes que este tenant ocupa aquí, sumados de las propias filas.

    **Sin contador.** El tamaño ya está en cada adjunto, así que sumarlo es la
    verdad por construcción: un contador aparte se desincroniza el primer día
    que alguien borre una fila por otra vía, y entonces el cliente paga por
    espacio que no ocupa o se le deja pasar del tope.
    """
    total = db.execute(
        select(func.coalesce(func.sum(Adjunto.tamano), 0)).where(Adjunto.tenant_id == tenant_id)
    ).scalar_one()
    return int(total)


def exigir_espacio(db: Session, tenant_id: UUID, entrantes: int) -> None:
    """Corta si el fichero no cabe en lo que le queda al tenant.

    **Sin tope declarado se deja pasar**, y es deliberado: un despliegue que no
    ha configurado cuotas no puede quedarse sin poder subir nada porque a
    alguien se le olvidara declararlas. La omisión abre, nunca cierra.

    El tope es de este módulo, no de toda la suite: cada servicio guarda lo suyo
    en su esquema y cuenta lo suyo. Así el mensaje puede decir **qué** se ha
    agotado, que con un tope global no se puede, y el alta no depende de una
    lectura entre servicios.
    """
    from crmcore.runtime import settings as rt
    from crmcore.tenancy.context import con_contexto, contexto_actual

    # EL TOPE ES DEL TENANT QUE SE PASA, no del contexto ambiente. `efectivo`
    # resuelve por contexto, y casi siempre coinciden —quien sube es quien está
    # dentro—, pero no siempre: un trabajo de sistema que sube en nombre de otro
    # leería la cuota equivocada, y eso es dejar pasar a quien había que cortar
    # o al revés. Lo cazó la prueba de que lo de un tenant no cuenta contra otro.
    if contexto_actual().tenant_id == tenant_id:
        max_mb = int(rt.efectivo("cuota_almacenamiento_mb", db) or 0)
    else:
        with con_contexto(tenant_id=tenant_id, origen="cuota"):
            max_mb = int(rt.efectivo("cuota_almacenamiento_mb", db) or 0)
    if max_mb <= 0:
        return

    ocupado = espacio_ocupado(db, tenant_id)
    tope = max_mb * 1024 * 1024
    if ocupado + entrantes > tope:
        raise CuotaAgotada(
            f"No cabe: ocupas {ocupado / 1024 / 1024:.0f} MB de {max_mb} MB y el "
            f"fichero son {entrantes / 1024 / 1024:.1f} MB",
            error_code="cuota.almacenamiento",
            detalle={
                "ocupado_mb": round(ocupado / 1024 / 1024, 1),
                "max_mb": max_mb,
                "fichero_mb": round(entrantes / 1024 / 1024, 1),
            },
        )


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
    carpeta_id: UUID | None = None,
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
    exigir_espacio(db, tenant_id, len(datos))
    if carpeta_id is not None:
        _exigir_carpeta_del_objeto(db, carpeta_id, objeto_tipo, objeto_id)
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
        carpeta_id=carpeta_id,
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
    from crmcore.datos.guard_borrados import con_borrados

    # Aquí hay que ver las dos mitades: los adjuntos vivos y los borrados. El
    # guard esconde los segundos, y sin ellos la lista de bytes huérfanos sale
    # vacía y el almacén no se limpia nunca.
    with con_borrados(db):
        return _limpiar(db, tenant_id)


def _limpiar(db: Session, tenant_id: UUID) -> int:
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


# ── Carpetas (CRM-06.01.01.05) ────────────────────────────────────────────


class CarpetaDocumental(Base, TimestampMixin):
    """Una carpeta dentro del expediente de un registro.

    Cuelga de un objeto —una cuenta, un caso— y no del tenant: un árbol global
    de carpetas obliga a inventar una convención de nombres para saber de quién
    es cada cosa, y a los seis meses hay «ACME», «ACME 2024» y «Acme S.L.»
    conviviendo. Con el árbol por registro, la pregunta «¿qué documentos tengo
    de este cliente?» no depende de que alguien nombrara bien la carpeta.

    Se guarda además la **ruta** completa: sin ella, enseñar el camino de un
    documento exige subir por los padres consultando uno a uno, y un listado de
    cincuenta documentos hace doscientas consultas para pintar una columna.
    """

    __tablename__ = "carpetas_documentales"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    objeto_tipo: Mapped[str] = mapped_column(String(60), nullable=False)
    objeto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    padre_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # Ruta legible, recalculada al mover. Es dato derivado y se dice: la verdad
    # está en `padre_id`, y si las dos discrepan manda el padre.
    ruta: Mapped[str] = mapped_column(String(1000), nullable=False, default="")

    __table_args__ = (
        Index("ix_carpetas_objeto", "tenant_id", "objeto_tipo", "objeto_id"),
        UniqueConstraint(
            "tenant_id",
            "objeto_tipo",
            "objeto_id",
            "padre_id",
            "nombre",
            name="uq_carpeta_hermana",
        ),
        # La restricción de arriba NO cubre las carpetas de raíz: en Postgres
        # dos `NULL` nunca son iguales, así que `padre_id IS NULL` deja pasar
        # dos raíces con el mismo nombre —y la ruta de las dos sería idéntica,
        # que es justo lo que la ruta existe para evitar. Este índice parcial
        # las cubre.
        Index(
            "uq_carpeta_raiz",
            "tenant_id",
            "objeto_tipo",
            "objeto_id",
            "nombre",
            unique=True,
            postgresql_where=text("padre_id IS NULL"),
            sqlite_where=text("padre_id IS NULL"),
        ),
    )


# Profundidad máxima del árbol. Ocho niveles son más de lo que nadie navega, y
# el tope existe porque sin él una carpeta movida mal puede generar una ruta que
# no cabe en la columna.
MAX_PROFUNDIDAD_CARPETA = 8


def crear_carpeta(
    db: Session,
    *,
    tenant_id: UUID,
    objeto_tipo: str,
    objeto_id: UUID,
    nombre: str,
    padre_id: UUID | None = None,
) -> CarpetaDocumental:
    """Crea una carpeta en el expediente de un registro."""
    nombre = (nombre or "").strip()
    if not nombre:
        raise ErrorValidacion("La carpeta necesita un nombre", error_code="carpeta.sin_nombre")
    if "/" in nombre:
        # La barra parte la ruta y haría que una carpeta llamada «2026/Q1»
        # pareciera dos. Se rechaza en vez de escaparla: escaparla produce rutas
        # que se leen mal en cualquier sitio que las enseñe.
        raise ErrorValidacion(
            "El nombre de una carpeta no puede llevar «/»",
            error_code="carpeta.nombre_con_barra",
        )

    padre = None
    if padre_id is not None:
        padre = db.get(CarpetaDocumental, padre_id)
        if padre is None or padre.objeto_id != objeto_id:
            raise NoEncontrado(
                "La carpeta padre no existe en este registro",
                error_code="carpeta.padre_no_existe",
            )
        if padre.ruta.count("/") + 1 >= MAX_PROFUNDIDAD_CARPETA:
            raise ErrorValidacion(
                f"No se pueden anidar más de {MAX_PROFUNDIDAD_CARPETA} niveles",
                error_code="carpeta.demasiado_profunda",
            )

    _exigir_nombre_libre(
        db,
        tenant_id=tenant_id,
        objeto_tipo=objeto_tipo,
        objeto_id=objeto_id,
        padre_id=padre_id,
        nombre=nombre,
    )

    carpeta = CarpetaDocumental(
        tenant_id=tenant_id,
        objeto_tipo=objeto_tipo,
        objeto_id=objeto_id,
        nombre=nombre,
        padre_id=padre_id,
        ruta=f"{padre.ruta}/{nombre}" if padre else nombre,
    )
    db.add(carpeta)
    db.flush()
    return carpeta


def mover_carpeta(
    db: Session, carpeta_id: UUID, *, nuevo_padre_id: UUID | None
) -> CarpetaDocumental:
    """Cambia una carpeta de sitio y **recalcula las rutas de su rama**.

    Sin recalcular, los documentos de dentro seguirían enseñando el camino
    viejo: la carpeta estaría en un sitio y su contenido diría que está en otro.
    """
    from crmcore.datos.jerarquia import comprobar_ciclo

    carpeta = db.get(CarpetaDocumental, carpeta_id)
    if carpeta is None:
        raise NoEncontrado("La carpeta no existe", error_code="carpeta.no_existe")

    if nuevo_padre_id is not None:
        padre = db.get(CarpetaDocumental, nuevo_padre_id)
        if padre is None or padre.objeto_id != carpeta.objeto_id:
            raise NoEncontrado(
                "La carpeta destino no existe en este registro",
                error_code="carpeta.padre_no_existe",
            )

        # Meter una carpeta dentro de su propia rama la desconecta del árbol:
        # deja de verse desde la raíz y sus documentos se vuelven inalcanzables.
        def _padre_de(cid: UUID) -> UUID | None:
            fila = db.get(CarpetaDocumental, cid)
            return fila.padre_id if fila is not None else None

        comprobar_ciclo(_padre_de, hijo=carpeta_id, nuevo_padre=nuevo_padre_id)
        carpeta.ruta = f"{padre.ruta}/{carpeta.nombre}"
    else:
        carpeta.ruta = carpeta.nombre
    _exigir_nombre_libre(
        db,
        tenant_id=carpeta.tenant_id,
        objeto_tipo=carpeta.objeto_tipo,
        objeto_id=carpeta.objeto_id,
        padre_id=nuevo_padre_id,
        nombre=carpeta.nombre,
        excepto=carpeta.id,
    )
    carpeta.padre_id = nuevo_padre_id
    db.flush()
    _recalcular_rutas(db, carpeta)
    return carpeta


def _recalcular_rutas(db: Session, carpeta: CarpetaDocumental) -> None:
    for hija in db.execute(
        select(CarpetaDocumental).where(CarpetaDocumental.padre_id == carpeta.id)
    ).scalars():
        hija.ruta = f"{carpeta.ruta}/{hija.nombre}"
        db.flush()
        _recalcular_rutas(db, hija)


def arbol_carpetas(db: Session, *, objeto_tipo: str, objeto_id: UUID) -> list[dict[str, Any]]:
    """Las carpetas del expediente, ordenadas por ruta.

    Plano y no anidado: quien pinta un árbol lo anida en un bucle, y devolverlo
    anidado obliga a recorrerlo entero para buscar una carpeta concreta.
    """
    filas = (
        db.execute(
            select(CarpetaDocumental)
            .where(
                CarpetaDocumental.objeto_tipo == objeto_tipo,
                CarpetaDocumental.objeto_id == objeto_id,
            )
            .order_by(CarpetaDocumental.ruta)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "nombre": f.nombre,
            "padre_id": str(f.padre_id) if f.padre_id else None,
            "ruta": f.ruta,
            "nivel": f.ruta.count("/"),
        }
        for f in filas
    ]


def borrar_carpeta(db: Session, carpeta_id: UUID, *, mover_a: UUID | None = None) -> int:
    """Borra una carpeta. Su contenido **no se borra**: se mueve.

    Borrar en cascada los documentos de una carpeta es la operación que más
    veces se lamenta: quien borra una carpeta está ordenando, no destruyendo.
    Lo de dentro sube a la raíz —o a donde se diga— y se cuenta cuántos se
    movieron, para que quien lo hizo sepa qué acaba de pasar.
    """
    carpeta = db.get(CarpetaDocumental, carpeta_id)
    if carpeta is None:
        raise NoEncontrado("La carpeta no existe", error_code="carpeta.no_existe")

    if mover_a is not None:
        destino = db.get(CarpetaDocumental, mover_a)
        if destino is None or destino.objeto_id != carpeta.objeto_id:
            raise NoEncontrado(
                "La carpeta destino no existe en este registro",
                error_code="carpeta.padre_no_existe",
            )
        # Mandar el contenido a una carpeta de dentro de la que se está
        # borrando lo tira con ella: al desaparecer el padre, la rama entera
        # queda colgando de un identificador que ya no existe.
        if destino.id == carpeta_id or destino.ruta.startswith(f"{carpeta.ruta}/"):
            raise ErrorValidacion(
                "No se puede mover el contenido a una carpeta de dentro de la que se borra",
                error_code="carpeta.destino_dentro",
            )

    movidos = 0
    for adjunto in db.execute(select(Adjunto).where(Adjunto.carpeta_id == carpeta_id)).scalars():
        adjunto.carpeta_id = mover_a
        movidos += 1
    # Las hijas se mueven con `mover_carpeta` y no a mano: cambiar `padre_id`
    # sin recalcular dejaba la ruta de toda la rama apuntando a una carpeta
    # borrada, y la ruta es lo que se enseña.
    hijas = list(
        db.execute(
            select(CarpetaDocumental).where(CarpetaDocumental.padre_id == carpeta_id)
        ).scalars()
    )
    db.flush()
    for hija in hijas:
        hija.padre_id = None  # se saca de la rama antes de comprobar ciclos
        db.flush()
        mover_carpeta(db, hija.id, nuevo_padre_id=mover_a)
    db.delete(carpeta)
    db.flush()
    return movidos


def _exigir_nombre_libre(
    db: Session,
    *,
    tenant_id: UUID,
    objeto_tipo: str,
    objeto_id: UUID,
    padre_id: UUID | None,
    nombre: str,
    excepto: UUID | None = None,
) -> None:
    """Dos hermanas con el mismo nombre tendrían la misma ruta.

    El índice lo impide en base de datos, pero dejarlo solo ahí devuelve un
    error de integridad en crudo: quien lo ve no sabe qué carpeta chocó.
    """
    consulta = select(CarpetaDocumental).where(
        CarpetaDocumental.tenant_id == tenant_id,
        CarpetaDocumental.objeto_tipo == objeto_tipo,
        CarpetaDocumental.objeto_id == objeto_id,
        CarpetaDocumental.nombre == nombre,
    )
    consulta = (
        consulta.where(CarpetaDocumental.padre_id.is_(None))
        if padre_id is None
        else consulta.where(CarpetaDocumental.padre_id == padre_id)
    )
    if excepto is not None:
        consulta = consulta.where(CarpetaDocumental.id != excepto)
    if db.execute(consulta.limit(1)).scalar_one_or_none() is not None:
        raise ErrorValidacion(
            f"Ya hay una carpeta «{nombre}» en ese mismo sitio",
            error_code="carpeta.nombre_repetido",
        )


def _exigir_carpeta_del_objeto(
    db: Session, carpeta_id: UUID, objeto_tipo: str, objeto_id: UUID
) -> CarpetaDocumental:
    """La carpeta tiene que ser del expediente del propio registro.

    Sin esta comprobación se podría archivar el contrato de una cuenta en el
    expediente de otra pasando su identificador de carpeta, y el documento
    desaparecería del sitio donde alguien lo va a buscar.
    """
    carpeta = db.get(CarpetaDocumental, carpeta_id)
    if carpeta is None or carpeta.objeto_tipo != objeto_tipo or carpeta.objeto_id != objeto_id:
        raise NoEncontrado(
            "La carpeta no existe en este registro",
            error_code="carpeta.no_existe",
        )
    return carpeta


def mover_adjunto(db: Session, adjunto_id: UUID, *, carpeta_id: UUID | None) -> Adjunto:
    """Archiva un adjunto en una carpeta, o lo devuelve a la raíz.

    Mueve **todas las versiones del documento**: una carpeta es dónde está el
    documento, no dónde está una de sus versiones, y dejar la v1 en un sitio y
    la v2 en otro convierte el historial en dos documentos distintos.
    """
    fila = db.get(Adjunto, adjunto_id)
    if fila is None or fila.deleted_at is not None:
        raise NoEncontrado("Adjunto no encontrado", error_code="adjunto.no_existe")
    if carpeta_id is not None:
        _exigir_carpeta_del_objeto(db, carpeta_id, fila.objeto_tipo, fila.objeto_id)
    for version in db.execute(
        select(Adjunto).where(
            Adjunto.tenant_id == fila.tenant_id, Adjunto.documento_id == fila.documento_id
        )
    ).scalars():
        version.carpeta_id = carpeta_id
    db.flush()
    logger.info(
        "adjunto.movido",
        documento=str(fila.documento_id),
        carpeta=str(carpeta_id) if carpeta_id else "",
    )
    return fila
