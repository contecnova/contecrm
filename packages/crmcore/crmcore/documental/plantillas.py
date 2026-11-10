"""Generación documental desde plantillas: propuesta, contrato, acta
(CRM-06.01.01.06).

El documento que se le manda a un cliente se hace casi siempre copiando el del
cliente anterior. Eso funciona hasta que alguien no borra un nombre, o hasta que
la cláusula que cambió legal el mes pasado sigue viva en veinte copias.

Las decisiones:

**Lo que no se puede rellenar se dice antes de generar, no después.** Un
documento con `{{importe}}` sin sustituir llega al cliente igual que uno bueno:
nadie relee un contrato de doce páginas antes de mandarlo.

**Las cláusulas bloqueadas no se editan.** Si fuese un aviso, se saltaría el día
que hay prisa — que es el día en que se manda sin la cláusula que la obliga.

**El documento generado se guarda como adjunto del registro** (10-11-2026).
Antes se decía que su sitio era el corpus de contecmind y que aquí no se
guardaba; con contecmind caído, eso era lo mismo que no guardarlo en ninguna
parte. El adjunto sí tiene política de borrado, análisis y retención —son los
del registro— y no depende de nadie. Si el corpus está disponible se archiva
además allí y se enlaza; si no, se dice y no falla nada.

**Y queda dicho de qué versión de plantilla salió.** Cuando una cláusula resulta
estar mal, la pregunta no es cuál está mal: es **a quién se le mandó**, y sin la
versión no hay forma de saberlo.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import (
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

from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger

logger = get_logger(__name__)

RE_MARCADOR = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")

# Para qué sirve cada plantilla. Lista cerrada porque el tipo decide qué se
# exige: un contrato sin cláusulas obligatorias es un problema distinto de un
# acta sin ellas.
TIPOS = ("propuesta", "contrato", "acta", "carta", "informe")


class PlantillaDocumento(Base, TimestampMixin, SoftDeleteMixin):
    """Una plantilla con sus marcadores y sus cláusulas bloqueadas."""

    __tablename__ = "plantillas_documento"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="propuesta")
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    idioma: Mapped[str] = mapped_column(String(10), nullable=False, default="es")
    cuerpo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Cada cambio es una versión nueva. Sin versiones, cuando una cláusula
    # resulta estar mal no hay forma de saber a quién se le mandó la mala.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Fragmentos que no se pueden tocar al generar: la mención legal, la
    # protección de datos, la cláusula de jurisdicción.
    clausulas_bloqueadas: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    vigente: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # La marca con la que sale el PDF. Vacía, la del tenant. Va en la plantilla
    # y no en el registro porque un grupo con tres marcas tiene una oferta por
    # marca, y quien genera no tiene que acordarse de cuál toca.
    marca: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    # De qué registros se puede generar. Vacía, de cualquiera.
    objetos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # De dónde sale cada marcador cuando se genera desde un registro:
    # `{"contacto": "contacto.nombre_completo", "importe": {"campo":
    # "registro.importe", "formato": "importe"}}`. Lo que no está aquí se busca
    # por su propio nombre en el registro y sus relacionados.
    mapeo: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Si el PDF lleva la tabla de líneas del registro cuando las tiene.
    con_lineas: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", "version", name="uq_plantilla_doc"),
        Index("ix_plantillas_doc", "tenant_id", "clave", "vigente"),
    )


class DocumentoGenerado(Base):
    """Qué se generó, de qué plantilla y con qué datos."""

    __tablename__ = "documentos_generados"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    plantilla_clave: Mapped[str] = mapped_column(String(80), nullable=False)
    plantilla_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    objeto: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    objeto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # El identificador en el corpus, si se archivó allí. Vacío si no.
    documento_id: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # El adjunto del registro donde quedó guardado, si se guardó.
    adjunto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    formato: Mapped[str] = mapped_column(
        String(10), nullable=False, default="texto", server_default="texto"
    )
    generado_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_documentos_generados", "tenant_id", "plantilla_clave", "created_at"),
    )


def guardar_plantilla(
    db: Session,
    *,
    tenant_id: UUID,
    clave: str,
    cuerpo: str,
    tipo: str = "propuesta",
    nombre: str = "",
    idioma: str = "es",
    clausulas_bloqueadas: list[str] | None = None,
    marca: str = "",
    objetos: list[str] | None = None,
    mapeo: dict[str, Any] | None = None,
    con_lineas: bool = True,
) -> PlantillaDocumento:
    """Guarda una versión NUEVA de la plantilla.

    Nueva y no una actualización: cuando una cláusula resulta estar mal, la
    pregunta no es cuál está mal, es a quién se le mandó. Sin versiones, la
    respuesta es «no consta».
    """
    if tipo not in TIPOS:
        raise ErrorValidacion(
            f"Tipo de documento desconocido: «{tipo}»",
            error_code="plantilla.tipo_desconocido",
            detalle={"admitidos": list(TIPOS)},
        )
    if not cuerpo.strip():
        raise ErrorValidacion(
            "Una plantilla vacía genera documentos vacíos", error_code="plantilla.vacia"
        )
    validar_mapeo(mapeo or {})

    anteriores = (
        db.execute(
            select(PlantillaDocumento).where(
                PlantillaDocumento.tenant_id == tenant_id, PlantillaDocumento.clave == clave
            )
        )
        .scalars()
        .all()
    )
    for fila in anteriores:
        fila.vigente = False

    nueva = PlantillaDocumento(
        tenant_id=tenant_id,
        clave=clave,
        tipo=tipo,
        nombre=nombre or clave,
        idioma=idioma,
        cuerpo=cuerpo,
        version=max((f.version for f in anteriores), default=0) + 1,
        clausulas_bloqueadas=list(clausulas_bloqueadas or []),
        vigente=True,
        marca=marca,
        objetos=list(objetos or []),
        mapeo=dict(mapeo or {}),
        con_lineas=con_lineas,
    )
    db.add(nueva)
    db.flush()
    return nueva


# `auto` decide por el dato: una fecha ISO sale como fecha y un importe que
# lleva su moneda al lado sale como importe. `texto` lo deja tal cual.
FORMATOS_MARCADOR = ("auto", "texto", "importe", "numero", "fecha")


def validar_mapeo(mapeo: dict[str, Any]) -> None:
    """Un mapeo mal escrito se rechaza al guardar, no al generar delante del cliente."""
    for marcador, origen in mapeo.items():
        if isinstance(origen, str):
            campo, formato = origen, "auto"
        elif isinstance(origen, dict):
            campo, formato = str(origen.get("campo") or ""), str(origen.get("formato") or "auto")
        else:
            campo, formato = "", ""
        if not campo.strip() or not re.fullmatch(r"[\w.]+", campo):
            raise ErrorValidacion(
                f"El marcador «{marcador}» no dice de qué campo sale",
                error_code="plantilla.mapeo_sin_campo",
                detalle={"marcador": marcador},
            )
        if formato not in FORMATOS_MARCADOR:
            raise ErrorValidacion(
                f"Formato «{formato}» desconocido en el marcador «{marcador}»",
                error_code="plantilla.mapeo_formato",
                detalle={"admitidos": list(FORMATOS_MARCADOR)},
            )


def vigente(db: Session, tenant_id: UUID, clave: str) -> PlantillaDocumento:
    """La versión vigente de una plantilla, o `NoEncontrado`."""
    return _vigente(db, tenant_id, clave)


def marcadores(cuerpo: str) -> list[str]:
    """Qué datos pide la plantilla."""
    return sorted(set(RE_MARCADOR.findall(cuerpo)))


def comprobar(db: Session, tenant_id: UUID, *, clave: str, datos: dict[str, Any]) -> dict[str, Any]:
    """Qué faltaría si se generase ahora, **sin generar nada**.

    Existe porque un documento con `{{importe}}` sin sustituir llega al cliente
    igual que uno bueno: nadie relee un contrato de doce páginas antes de
    mandarlo.
    """
    plantilla = _vigente(db, tenant_id, clave)
    pedidos = marcadores(plantilla.cuerpo)
    faltan = [m for m in pedidos if _leer(datos, m) in (None, "")]
    return {
        "plantilla": clave,
        "version": plantilla.version,
        "pide": pedidos,
        "faltan": faltan,
        "se_puede_generar": not faltan,
        "porque": (
            "Todos los datos están."
            if not faltan
            else f"Faltan {len(faltan)}: un documento con marcadores sin sustituir "
            "llega al cliente igual que uno bueno."
        ),
    }


def generar(
    db: Session,
    *,
    tenant_id: UUID,
    clave: str,
    datos: dict[str, Any],
    objeto: str = "",
    objeto_id: UUID | None = None,
    por: UUID | None = None,
    permitir_incompleto: bool = False,
    documento_id: str = "",
) -> dict[str, Any]:
    """Compone el documento y deja constancia de con qué se hizo.

    **No genera si falta algo**, salvo que se diga expresamente. Y esa excepción
    existe porque hay borradores que se completan a mano; lo que no puede pasar
    es que sea el comportamiento por defecto.

    Devuelve el texto. Guardarlo —como adjunto del registro y, si se puede, en el
    corpus— es de quien genera desde la ficha (`services.integration.documento_registro`).
    """
    plantilla = _vigente(db, tenant_id, clave)
    pedidos = marcadores(plantilla.cuerpo)
    faltan = [m for m in pedidos if _leer(datos, m) in (None, "")]
    if faltan and not permitir_incompleto:
        raise Conflicto(
            f"Faltan {len(faltan)} datos de la plantilla «{clave}»: {faltan[:5]}",
            error_code="plantilla.datos_incompletos",
            detalle={"faltan": faltan},
        )

    texto = plantilla.cuerpo
    for marcador in pedidos:
        valor = _leer(datos, marcador)
        texto = texto.replace("{{" + marcador + "}}", "" if valor is None else str(valor))
        texto = re.sub(
            r"\{\{\s*" + re.escape(marcador) + r"\s*\}\}",
            "" if valor is None else str(valor),
            texto,
        )

    # Las cláusulas bloqueadas tienen que seguir estando, palabra por palabra.
    # Comprobarlo después de sustituir y no antes es lo que pilla el caso real:
    # un marcador dentro de la cláusula que se sustituye por algo que la rompe.
    perdidas = [c for c in (plantilla.clausulas_bloqueadas or []) if str(c) not in texto]
    if perdidas:
        raise Conflicto(
            "El documento generado ha perdido cláusulas que no se pueden quitar: "
            f"{perdidas[:3]}",
            error_code="plantilla.clausula_perdida",
            detalle={"perdidas": perdidas},
        )

    # **Y aquí se deja la constancia**, que es la mitad que faltaba. Esta función
    # decía en su primera línea que la dejaba y no la dejaba: `anotar_generado`
    # era la única que escribe en esa tabla y no la llamaba nadie, así que la
    # tabla estaba siempre vacía — y `quien_recibio`, que es LA pregunta que se
    # hace cuando una cláusula resulta estar mal, contestaba «a nadie» con toda
    # tranquilidad. Un registro vacío no da error: contesta lo mismo que si de
    # verdad no se hubiera mandado a nadie.
    #
    # Se apunta al generar y no al subirlo al corpus: hay documentos que se
    # generan y acaban en un correo sin pasar por el gestor, y ésos son
    # exactamente los que después nadie puede rastrear. `documento_id` va vacío
    # mientras no esté archivado, y eso es un dato, no un hueco.
    constancia = anotar_generado(
        db,
        tenant_id=tenant_id,
        clave=clave,
        version=plantilla.version,
        documento_id=documento_id,
        objeto=objeto,
        objeto_id=objeto_id,
        por=por,
    )

    logger.info("documental.generado", plantilla=clave, version=plantilla.version, objeto=objeto)
    return {
        "texto": texto,
        "plantilla": clave,
        # La versión va siempre, y es lo que permite contestar «¿a quién le
        # mandamos la cláusula mala?» cuando alguien la encuentra.
        "version": plantilla.version,
        "tipo": plantilla.tipo,
        "incompleto": bool(faltan),
        "faltaban": faltan,
        "aviso": (
            ""
            if not faltan
            else f"Generado con {len(faltan)} marcadores sin dato, a petición "
            "expresa. Hay que completarlo a mano antes de mandarlo."
        ),
        "donde_se_guarda": (
            "Generado desde la ficha del registro, el PDF queda como adjunto suyo "
            "y, si el corpus documental está disponible, archivado también allí."
        ),
        "generado_at": datetime.now(timezone.utc).isoformat(),
        "constancia_id": str(constancia.id),
    }


def anotar_generado(
    db: Session,
    *,
    tenant_id: UUID,
    clave: str,
    version: int,
    documento_id: str,
    objeto: str = "",
    objeto_id: UUID | None = None,
    por: UUID | None = None,
) -> DocumentoGenerado:
    """Deja constancia de que este documento salió de esta versión de plantilla."""
    fila = DocumentoGenerado(
        tenant_id=tenant_id,
        plantilla_clave=clave,
        plantilla_version=version,
        objeto=objeto,
        objeto_id=objeto_id,
        documento_id=documento_id,
        generado_por=por,
    )
    db.add(fila)
    db.flush()
    return fila


def quien_recibio(db: Session, tenant_id: UUID, *, clave: str, version: int) -> dict[str, Any]:
    """A quién se le mandó una versión concreta de la plantilla.

    Es la pregunta que se hace cuando una cláusula resulta estar mal, y la que no
    se puede contestar si las plantillas se editan en sitio.
    """
    filas = (
        db.execute(
            select(DocumentoGenerado).where(
                DocumentoGenerado.tenant_id == tenant_id,
                DocumentoGenerado.plantilla_clave == clave,
                DocumentoGenerado.plantilla_version == version,
            )
        )
        .scalars()
        .all()
    )
    return {
        "plantilla": clave,
        "version": version,
        "documentos": [
            {
                "documento_id": f.documento_id,
                "adjunto_id": str(f.adjunto_id) if f.adjunto_id else None,
                "formato": f.formato,
                "objeto": f.objeto,
                "objeto_id": str(f.objeto_id) if f.objeto_id else None,
                "generado_at": f.created_at.isoformat(),
            }
            for f in filas
        ],
        "cuantos": len(filas),
    }


def _vigente(db: Session, tenant_id: UUID, clave: str) -> PlantillaDocumento:
    fila = (
        db.execute(
            select(PlantillaDocumento)
            .where(
                PlantillaDocumento.tenant_id == tenant_id,
                PlantillaDocumento.clave == clave,
                PlantillaDocumento.vigente.is_(True),
            )
            .order_by(PlantillaDocumento.version.desc())
        )
        .scalars()
        .first()
    )
    if fila is None:
        raise NoEncontrado(
            f"No hay ninguna plantilla vigente con la clave «{clave}»",
            error_code="plantilla.no_encontrada",
        )
    return fila


def _leer(datos: dict[str, Any], camino: str) -> Any:
    """Lee `cliente.nombre` de un diccionario anidado."""
    actual: Any = datos
    for parte in camino.split("."):
        if not isinstance(actual, dict):
            return None
        actual = actual.get(parte)
    return actual
