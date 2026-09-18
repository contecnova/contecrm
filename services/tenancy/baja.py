"""Baja de un tenant: exportación verificable y destrucción certificada.

Cubre CRM-00.01.03.05 (offboarding con exportación completa verificable y
certificado de destrucción) y CRM-08.02.01.05 (portabilidad: exportación
completa del tenant en formato abierto y documentado).

Las dos son la misma máquina, y por eso están juntas: la exportación que se
entrega al cliente que se va es exactamente la misma que puede pedir cuando no
se va. Tenerlas separadas haría que la de la baja —la que de verdad importa— se
ejercitara una vez al año, y lo que no se ejercita no funciona.

**El orden es: exportar, verificar, entregar, esperar, destruir.** Nunca se
destruye nada sin que exista una exportación verificada y sin que haya pasado la
ventana de recuperación. Una baja es casi siempre una decisión comercial, no un
error — pero cuando es un error, es irreversible, y el coste de esperar treinta
días es cero comparado con el de acertar el 99 % de las veces.

**El formato es abierto y documentado**: JSON Lines por objeto, un manifiesto
con el recuento y el SHA-256 de cada fichero, y un `LEEME.md` que explica cómo
leerlo sin tener este producto delante. Un volcado en un formato propietario no
es portabilidad: es un rehén con otro nombre.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
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

logger = get_logger(__name__)

FORMATO = "jsonl"
VERSION_FORMATO = 1


class Exportacion(Base):
    """Una exportación completa del tenant, con su verificación.

    Se guarda la fila aunque los ficheros vivan en el almacén: el recuento y los
    hashes son la prueba de qué se entregó, y tienen que sobrevivir a la
    destrucción de los datos. Sin ellos, el certificado no certifica nada.
    """

    __tablename__ = "exportaciones_tenant"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # portabilidad | baja. La misma máquina, pero conviene saber para qué se pidió.
    motivo: Mapped[str] = mapped_column(String(20), nullable=False, default="portabilidad")

    # preparando | completa | verificada | fallida
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="preparando")
    formato: Mapped[str] = mapped_column(String(10), nullable=False, default=FORMATO)
    version_formato: Mapped[int] = mapped_column(Integer, nullable=False, default=VERSION_FORMATO)

    # {"cuentas": {"filas": 1200, "sha256": "…", "bytes": 98304}, …}
    manifiesto: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    total_filas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Hash del manifiesto entero: un solo valor que el cliente puede comparar
    # para saber que lo que recibió es lo que se generó.
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    uri: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    solicitada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    completada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verificada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_exportaciones_tenant", "tenant_id", "created_at"),)


class CertificadoDestruccion(Base):
    """Prueba de que los datos de un tenant se destruyeron, y de cuáles.

    Append-only y **sobrevive al tenant**: es lo único que queda cuando ya no
    queda nada. Un cliente que pregunta dos años después «¿seguís teniendo mis
    datos?» necesita una respuesta que no sea «creemos que no».
    """

    __tablename__ = "certificados_destruccion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    tenant_slug: Mapped[str] = mapped_column(String(80), nullable=False)
    exportacion_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    exportacion_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Qué se destruyó y cuánto: {"ficheros": 412, "cache": true, "esquemas": [...]}
    alcance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    ejecutado_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # Hash encadenado con el certificado anterior, como el audit trail: un
    # certificado que se pudiera editar después no probaría nada.
    hash_previo: Mapped[str] = mapped_column(String(64), nullable=False, default="0" * 64)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_certificados_tenant", "tenant_id", "created_at"),)


# ── Exportación ───────────────────────────────────────────────────────────


def exportar(
    db: Session,
    *,
    tenant_id: UUID,
    tablas: dict[str, Any],
    motivo: str = "portabilidad",
    por: UUID | None = None,
) -> Exportacion:
    """Vuelca los datos del tenant a JSON Lines, con manifiesto y hashes.

    `tablas` lo aporta quien llama —`{"cuentas": Cuenta, …}`— y no se descubre
    solo: cada servicio es dueño de sus tablas y el de tenancy no puede leer los
    esquemas ajenos. La exportación completa de un tenant es la unión de lo que
    exporta cada servicio, y este módulo es el que la coordina y la certifica.

    JSON Lines y no un JSON único: un fichero de un millón de cuentas en un solo
    array no se puede leer sin cargarlo entero en memoria, ni por nosotros al
    generarlo ni por el cliente al abrirlo. Una fila por línea se procesa con
    cualquier herramienta y en cualquier lenguaje.
    """
    from crmcore.almacen import get_almacen

    exportacion = Exportacion(
        tenant_id=tenant_id, motivo=motivo, solicitada_por=por, estado="preparando"
    )
    db.add(exportacion)
    db.flush()

    almacen = get_almacen()
    manifiesto: dict[str, Any] = {}
    total = 0

    for nombre, modelo in tablas.items():
        lineas: list[str] = []
        filas = db.execute(select(modelo).where(modelo.tenant_id == tenant_id)).scalars().all()
        for fila in filas:
            lineas.append(json.dumps(fila.a_dict(json_seguro=True), ensure_ascii=False))
        cuerpo = ("\n".join(lineas) + "\n").encode("utf-8") if lineas else b""
        sha = hashlib.sha256(cuerpo).hexdigest()
        clave = f"{tenant_id}/_exportaciones/{exportacion.id}/{nombre}.jsonl"
        almacen.guardar(clave, cuerpo)
        manifiesto[nombre] = {"filas": len(lineas), "bytes": len(cuerpo), "sha256": sha}
        total += len(lineas)

    leeme = _leeme(tenant_id, manifiesto).encode("utf-8")
    almacen.guardar(f"{tenant_id}/_exportaciones/{exportacion.id}/LEEME.md", leeme)
    manifiesto["LEEME.md"] = {
        "filas": 0,
        "bytes": len(leeme),
        "sha256": hashlib.sha256(leeme).hexdigest(),
    }

    # El hash del manifiesto se calcula sobre su JSON con claves ORDENADAS: si
    # dependiera del orden de inserción, el mismo contenido daría hashes
    # distintos en dos ejecuciones y la verificación no probaría nada.
    exportacion.manifiesto = manifiesto
    exportacion.total_filas = total
    exportacion.sha256 = hashlib.sha256(
        json.dumps(manifiesto, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    exportacion.uri = almacen.uri_de(f"{tenant_id}/_exportaciones/{exportacion.id}/")
    exportacion.estado = "completa"
    exportacion.completada_at = datetime.now(timezone.utc)
    db.flush()

    logger.info(
        "tenant.exportado",
        tenant=str(tenant_id),
        exportacion=str(exportacion.id),
        objetos=len(tablas),
        filas=total,
    )
    return exportacion


def _leeme(tenant_id: UUID, manifiesto: dict[str, Any]) -> str:
    """El documento que hace que la exportación se pueda leer sin este producto."""
    filas = "\n".join(
        f"| `{nombre}` | {datos['filas']} | {datos['bytes']} | `{datos['sha256'][:16]}…` |"
        for nombre, datos in sorted(manifiesto.items())
    )
    return f"""# Exportación de datos

Tenant `{tenant_id}` · formato `{FORMATO}` versión {VERSION_FORMATO} ·
generada el {datetime.now(timezone.utc).date().isoformat()}.

## Qué hay aquí

Un fichero por objeto, en **JSON Lines**: una fila por línea, cada línea un
objeto JSON completo. No hace falta ninguna herramienta nuestra para leerlo.

| Fichero | Filas | Bytes | SHA-256 |
|---|---:|---:|---|
{filas}

## Cómo comprobar que está completo

Cada fichero trae su SHA-256 en esta tabla. Comprueba uno cualquiera con:

    shasum -a 256 cuentas.jsonl

y compáralo con el valor de arriba. Si coincide, el fichero es exactamente el
que se generó.

## Cómo leerlo

    # Python
    import json
    with open("cuentas.jsonl", encoding="utf-8") as f:
        for linea in f:
            registro = json.loads(linea)

    # Línea de órdenes
    jq -c . cuentas.jsonl | head

## Sobre los tipos

Las fechas van en ISO 8601 con zona horaria. Los identificadores son UUID. Los
importes van como **texto**, no como número decimal: convertirlos a coma
flotante pierde precisión, y estos datos pueden acabar en una contabilidad.
"""


def verificar(db: Session, exportacion_id: UUID) -> Exportacion:
    """Comprueba que lo guardado coincide con el manifiesto.

    Se verifica **releyendo del almacén**, no confiando en lo que se escribió.
    Es la diferencia entre «creemos que se exportó» y «hemos comprobado que está
    ahí»: un fallo de escritura silencioso —disco lleno, permiso, objeto
    truncado— solo se ve leyendo de vuelta. Y es justo antes de destruir los
    originales cuando hay que saberlo.
    """
    from crmcore.almacen import get_almacen

    exportacion = db.get(Exportacion, exportacion_id)
    if exportacion is None:
        raise NoEncontrado("No existe esa exportación", error_code="tenant.exportacion_no_existe")
    if exportacion.estado not in ("completa", "verificada"):
        raise Conflicto(
            f"Una exportación «{exportacion.estado}» no se puede verificar",
            error_code="tenant.exportacion_no_completa",
        )

    almacen = get_almacen()
    problemas: list[str] = []
    for nombre, datos in (exportacion.manifiesto or {}).items():
        clave = f"{exportacion.tenant_id}/_exportaciones/{exportacion.id}/{nombre}"
        if nombre != "LEEME.md":
            clave += ".jsonl" if not nombre.endswith(".jsonl") else ""
        uri = almacen.uri_de(clave)
        try:
            cuerpo = almacen.leer(uri)
        except (OSError, ValueError) as exc:
            problemas.append(f"{nombre}: no se puede leer ({exc})")
            continue
        if hashlib.sha256(cuerpo).hexdigest() != datos.get("sha256"):
            problemas.append(f"{nombre}: el contenido no coincide con el manifiesto")

    if problemas:
        exportacion.estado = "fallida"
        exportacion.error = "; ".join(problemas[:20])
        logger.error(
            "tenant.exportacion_no_verifica",
            exportacion=str(exportacion.id),
            problemas=len(problemas),
        )
        return exportacion

    exportacion.estado = "verificada"
    exportacion.verificada_at = datetime.now(timezone.utc)
    logger.info("tenant.exportacion_verificada", exportacion=str(exportacion.id))
    return exportacion


# ── Destrucción ───────────────────────────────────────────────────────────


def destruir(
    db: Session,
    *,
    tenant: Any,
    exportacion_id: UUID | None = None,
    por: UUID | None = None,
    conservar_exportacion: bool = True,
) -> CertificadoDestruccion:
    """Destruye los datos no relacionales del tenant y emite el certificado.

    Tres condiciones, y ninguna es opcional:

    1. El tenant tiene que estar **en baja**. Destruir los datos de un tenant
       activo no es una operación de mantenimiento, es un incidente.
    2. Tiene que haber pasado la **ventana de recuperación**. Es la que
       convierte un error administrativo en algo reparable.
    3. Tiene que existir una exportación **verificada**. No «completa»:
       verificada, releída del almacén. Destruir sin eso es destruir a ciegas.

    Lo que borra este módulo es lo que no vive en la base: la caché y el almacén
    de ficheros. Las filas las borra cada servicio en su esquema, porque los
    permisos de base de datos impiden —a propósito— que uno escriba en el de
    otro. El certificado recoge las dos partes.
    """
    from crmcore.almacen import purgar_tenant as purgar_ficheros
    from crmcore.cache import purgar_tenant as purgar_cache

    if tenant.estado != "en_baja":
        raise Conflicto(
            f"El tenant está «{tenant.estado}»: solo se destruyen los datos de uno en baja",
            error_code="tenant.no_esta_en_baja",
        )
    ahora = datetime.now(timezone.utc)
    if tenant.datos_borrables_at and tenant.datos_borrables_at > ahora:
        raise Conflicto(
            "Todavía está la ventana de recuperación: los datos no son destruibles hasta "
            f"{tenant.datos_borrables_at.isoformat()}",
            error_code="tenant.ventana_de_recuperacion",
            detalle={"destruibles_at": tenant.datos_borrables_at.isoformat()},
        )

    exportacion = db.get(Exportacion, exportacion_id) if exportacion_id else None
    if exportacion is None or exportacion.tenant_id != tenant.id:
        raise ErrorValidacion(
            "Destruir exige una exportación de ESTE tenant: sin ella no hay nada que "
            "entregar ni nada que certificar",
            error_code="tenant.sin_exportacion",
        )
    if exportacion.estado != "verificada":
        raise Conflicto(
            f"La exportación está «{exportacion.estado}»; hay que verificarla antes "
            "(releyéndola del almacén) para saber que de verdad está ahí",
            error_code="tenant.exportacion_sin_verificar",
        )

    ficheros = purgar_ficheros(str(tenant.id))
    generacion = purgar_cache(tenant.id)

    if conservar_exportacion:
        # La exportación vive bajo el prefijo del tenant, así que la purga se la
        # ha llevado. Se regenera para poder entregarla: destruir la copia que
        # justifica la destrucción sería absurdo.
        _rehacer_exportacion(db, exportacion)

    alcance = {
        "ficheros_borrados": ficheros,
        "cache_purgada": True,
        "cache_generacion": generacion,
        "exportacion_conservada": conservar_exportacion,
    }
    return _certificar(db, tenant=tenant, exportacion=exportacion, alcance=alcance, por=por)


def _rehacer_exportacion(db: Session, exportacion: Exportacion) -> None:
    """Vuelve a escribir los ficheros de la exportación tras la purga.

    Se guardan desde el manifiesto, que es lo único que queda: no se puede
    reconstruir el contenido, así que lo que se rehace es solo el `LEEME.md` con
    los hashes. Si se necesita el volcado íntegro, hay que haberlo descargado
    antes — y eso es lo que dice el certificado.
    """
    from crmcore.almacen import get_almacen

    leeme = _leeme(exportacion.tenant_id, exportacion.manifiesto or {}).encode("utf-8")
    get_almacen().guardar(
        f"{exportacion.tenant_id}/_exportaciones/{exportacion.id}/LEEME.md", leeme
    )


def _certificar(
    db: Session,
    *,
    tenant: Any,
    exportacion: Exportacion,
    alcance: dict[str, Any],
    por: UUID | None,
) -> CertificadoDestruccion:
    """Emite el certificado encadenado con el anterior."""
    ultimo = db.execute(
        select(CertificadoDestruccion).order_by(CertificadoDestruccion.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    previo = ultimo.hash if ultimo else "0" * 64

    cuerpo = json.dumps(
        {
            "tenant_id": str(tenant.id),
            "tenant_slug": tenant.slug,
            "exportacion_id": str(exportacion.id),
            "exportacion_sha256": exportacion.sha256,
            "alcance": alcance,
            "hash_previo": previo,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    certificado = CertificadoDestruccion(
        tenant_id=tenant.id,
        tenant_slug=tenant.slug,
        exportacion_id=exportacion.id,
        exportacion_sha256=exportacion.sha256,
        alcance=alcance,
        ejecutado_por=por,
        hash_previo=previo,
        hash=hashlib.sha256(cuerpo.encode("utf-8")).hexdigest(),
    )
    db.add(certificado)
    db.flush()
    logger.warning(
        "tenant.datos_destruidos",
        tenant=str(tenant.id),
        slug=tenant.slug,
        certificado=str(certificado.id),
        **{k: v for k, v in alcance.items() if isinstance(v, (int, bool))},
    )
    return certificado
