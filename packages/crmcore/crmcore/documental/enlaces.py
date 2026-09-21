"""Qué documento del corpus está enlazado a qué registro (RT-5).

La tabla vive en el esquema de **cada servicio**, como adjuntos y comentarios:
el enlace es del registro, y el registro es de su servicio. Un índice central
obligaría a que `party` escribiera en el esquema de otro, que es justo lo que
los permisos de base de datos impiden.

Lo que se guarda aquí es **el enlace y el contexto**, nunca una copia del
documento: duplicar el contenido crearía dos verdades que divergen en cuanto
alguien publique una versión nueva allí, y la del CRM sería la vieja sin decirlo.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Index, String, UniqueConstraint, func, select
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.db.base import Base
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger

logger = get_logger(__name__)


class DocumentoEnlazado(Base):
    """Un documento del corpus, visto desde un registro del CRM."""

    __tablename__ = "documentos_enlazados"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    objeto_tipo: Mapped[str] = mapped_column(String(60), nullable=False)
    objeto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    # Identificador del documento EN EL GESTOR. Texto y no UUID: el gestor puede
    # ser contecmind hoy y otro mañana, y forzar un formato aquí ataría la tabla
    # a la implementación de un tercero.
    documento_id: Mapped[str] = mapped_column(String(120), nullable=False)
    # Qué gestor lo tiene. Con uno solo parece redundante; con dos —una
    # migración, una adquisición— es lo único que distingue un identificador de
    # otro.
    sistema: Mapped[str] = mapped_column(String(60), nullable=False, default="contecmind")

    # Copia **mínima** para poder listar sin llamar al gestor en cada pantalla.
    # Solo lo que no cambia el sentido si se queda viejo: el título y el tipo.
    # Nada de versión ni de estado de aprobación — eso se pregunta, porque un
    # «aprobado» caducado en una pantalla es peor que no enseñarlo.
    titulo: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    tipo: Mapped[str] = mapped_column(String(60), nullable=False, default="")

    # Para qué está enlazado: «contrato marco», «certificado ISO». Es del CRM y
    # no del gestor: el mismo documento puede ser el contrato de una cuenta y el
    # anexo de otra.
    rol: Mapped[str] = mapped_column(String(80), nullable=False, default="")

    enlazado_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_docenlazados_objeto", "tenant_id", "objeto_tipo", "objeto_id"),
        UniqueConstraint(
            "tenant_id",
            "objeto_tipo",
            "objeto_id",
            "sistema",
            "documento_id",
            "rol",
            name="uq_documento_enlazado",
        ),
    )


def enlazar(
    db: Session,
    *,
    tenant_id: UUID,
    objeto_tipo: str,
    objeto_id: UUID,
    documento_id: str,
    titulo: str = "",
    tipo: str = "",
    rol: str = "",
    sistema: str = "contecmind",
    por: UUID | None = None,
) -> DocumentoEnlazado:
    """Enlaza un documento del corpus con un registro."""
    if not documento_id:
        raise ErrorValidacion(
            "Hace falta el identificador del documento en el gestor",
            error_code="documental.sin_documento",
        )

    existente = (
        db.execute(
            select(DocumentoEnlazado).where(
                DocumentoEnlazado.objeto_tipo == objeto_tipo,
                DocumentoEnlazado.objeto_id == objeto_id,
                DocumentoEnlazado.sistema == sistema,
                DocumentoEnlazado.documento_id == documento_id,
                DocumentoEnlazado.rol == rol,
            )
        )
        .scalars()
        .first()
    )
    if existente is not None:
        # Enlazar dos veces lo mismo con el mismo rol no es un error, pero
        # tampoco crea una fila nueva: la ficha enseñaría el documento repetido.
        existente.titulo = titulo or existente.titulo
        db.flush()
        return existente

    enlace = DocumentoEnlazado(
        tenant_id=tenant_id,
        objeto_tipo=objeto_tipo,
        objeto_id=objeto_id,
        documento_id=documento_id,
        sistema=sistema,
        titulo=titulo[:300],
        tipo=tipo[:60],
        rol=rol[:80],
        enlazado_por=por,
    )
    db.add(enlace)
    db.flush()
    return enlace


def documentos_de(db: Session, *, objeto_tipo: str, objeto_id: UUID) -> list[dict[str, Any]]:
    """Los documentos enlazados a un registro.

    Devuelve lo guardado **sin llamar al gestor**: una pantalla de ficha que
    depende de un servicio externo para pintar una lista es una pantalla que
    tarda lo que tarde ese servicio. El estado real —versión publicada, si está
    obsoleto— se pide al abrir el documento, que es cuando importa.
    """
    filas = (
        db.execute(
            select(DocumentoEnlazado)
            .where(
                DocumentoEnlazado.objeto_tipo == objeto_tipo,
                DocumentoEnlazado.objeto_id == objeto_id,
            )
            .order_by(DocumentoEnlazado.created_at)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "documento_id": f.documento_id,
            "sistema": f.sistema,
            "titulo": f.titulo,
            "tipo": f.tipo,
            "rol": f.rol,
            "created_at": f.created_at.isoformat() if f.created_at else None,
            # Se dice explícitamente que esto es una copia para listar y que el
            # estado vive fuera. Sin esta marca, alguien acabará construyendo un
            # informe sobre `titulo` creyendo que está al día.
            "estado_en": f.sistema,
        }
        for f in filas
    ]


def quitar_enlace(db: Session, enlace_id: UUID, *, objeto_id: UUID) -> None:
    """Quita el enlace. **No borra el documento**: el CRM no es su dueño.

    Borrarlo allí desde aquí sería que un usuario del CRM destruyera el contrato
    que otro departamento guardó en el gestor, sin pasar por las reglas de ese
    gestor —aprobación, obsolescencia, retención propia—.
    """
    enlace = db.get(DocumentoEnlazado, enlace_id)
    if enlace is None or enlace.objeto_id != objeto_id:
        raise NoEncontrado(
            "Ese documento no está enlazado a este registro",
            error_code="documental.enlace_no_existe",
        )
    _exigir_sin_bloqueo(db, enlace)
    db.delete(enlace)
    db.flush()


def _exigir_sin_bloqueo(db: Session, enlace: DocumentoEnlazado) -> None:
    """Un bloqueo legal sobre el registro alcanza a sus documentos enlazados.

    Es una de las dos obligaciones que cruzan la frontera. Un bloqueo que
    permite desenlazar la prueba y luego decir «aquí no consta» no es un
    bloqueo: deja el documento fuera del alcance de quien lo pidió sin borrar
    nada, que es peor que borrarlo porque no queda rastro del intento.
    """
    from crmcore.datos.retencion import bajo_bloqueo

    bloqueo = bajo_bloqueo(
        db,
        tenant_id=enlace.tenant_id,
        objeto=enlace.objeto_tipo,
        objeto_id=enlace.objeto_id,
    )
    if bloqueo is not None:
        raise Conflicto(
            f"«{enlace.objeto_tipo}» está bajo bloqueo legal: no se pueden quitar "
            f"sus documentos. Motivo: {bloqueo.motivo}",
            error_code="documental.bajo_bloqueo_legal",
            detalle={"referencia": bloqueo.referencia or ""},
        )


def inventario_para_certificado(db: Session, tenant_id: UUID) -> list[dict[str, Any]]:
    """Qué documentos tenía este tenant enlazados fuera, para el certificado.

    La otra obligación que cruza la frontera. Al dar de baja un tenant, el
    certificado de destrucción tiene que decir **qué había fuera** — porque
    contecrm no lo puede destruir: lo destruye quien lo guarda.

    Callarlo sería certificar una destrucción que no se ha hecho entera, que es
    peor que no certificar nada: el cliente se queda creyendo que sus documentos
    ya no existen.
    """
    filas = (
        db.execute(select(DocumentoEnlazado).where(DocumentoEnlazado.tenant_id == tenant_id))
        .scalars()
        .all()
    )
    if not filas:
        return []
    logger.info("documental.inventario_certificado", tenant=str(tenant_id), documentos=len(filas))
    return [
        {
            "sistema": f.sistema,
            "documento_id": f.documento_id,
            "titulo": f.titulo,
            "objeto": f"{f.objeto_tipo}:{f.objeto_id}",
            "aviso": (
                "Este documento vive fuera de contecrm. Su destrucción la "
                "ejecuta el gestor que lo guarda, no este certificado."
            ),
        }
        for f in filas
    ]


# ── Multitenancy: a qué organización del gestor corresponde cada tenant ────


class OrganizacionDocumental(Base):
    """El tenant de contecrm, visto desde el gestor documental.

    Se guarda y **no se deduce del identificador del tenant**, por la misma
    razón que con contecintelligence: el gestor solo acepta nombrar
    organizaciones que tenga mapeadas, y ese es justo el control que impide que
    un token diga pertenecer a un cliente cualquiera. Reconstruirlo cada vez a
    partir del identificador convertiría el control en una convención, y una
    convención no para a nadie.

    Sin mapeo **no se llama al gestor**. Es la diferencia entre un CRM
    multitenant de verdad y uno que confía en que el de enfrente filtre bien.
    """

    __tablename__ = "organizaciones_documentales"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    organizacion: Mapped[str] = mapped_column(String(120), nullable=False)
    # pendiente | activa | error
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    ultimo_error: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    verificada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Índice único y no `UniqueConstraint`: el efecto en Postgres es el mismo
    # —un tenant, un mapeo— pero además queda como índice por `tenant_id`, que
    # es por donde entra RLS en cada lectura de esta tabla.
    __table_args__ = (Index("ix_orgdoc_tenant", "tenant_id", unique=True),)


def organizacion_de(db: Session, tenant_id: UUID) -> str:
    """La organización del gestor para este tenant, o vacío si no hay mapeo.

    Devuelve vacío en vez de lanzar: quien llame decide si eso es un error
    —intentar buscar— o una respuesta normal —pintar una ficha sin corpus—.
    """
    fila = (
        db.execute(
            select(OrganizacionDocumental).where(
                OrganizacionDocumental.tenant_id == tenant_id,
                OrganizacionDocumental.estado == "activa",
            )
        )
        .scalars()
        .first()
    )
    return fila.organizacion if fila else ""


def mapear_organizacion(
    db: Session, *, tenant_id: UUID, organizacion: str
) -> OrganizacionDocumental:
    """Declara a qué organización del gestor corresponde este tenant."""
    if not organizacion.strip():
        raise ErrorValidacion(
            "Hace falta el nombre de la organización en el gestor documental",
            error_code="documental.sin_organizacion",
        )
    fila = (
        db.execute(
            select(OrganizacionDocumental).where(OrganizacionDocumental.tenant_id == tenant_id)
        )
        .scalars()
        .first()
    )
    if fila is None:
        fila = OrganizacionDocumental(tenant_id=tenant_id)
        db.add(fila)
    fila.organizacion = organizacion.strip()
    fila.estado = "activa"
    fila.ultimo_error = ""
    db.flush()
    _propagar_organizacion(db, tenant_id=tenant_id, organizacion=fila.organizacion)
    return fila


ORGANIZACION_CAMBIADA = "documental.organizacion_cambiada"


def declarar_evento_organizacion() -> None:
    """Declara el evento del mapeo, una sola vez.

    Productor «core» y no un servicio: el mapeo se puede fijar desde cualquiera
    de los que enlazan documentos, y darle dueño a uno sería mentir.
    """
    from crmcore.events.catalogo import TipoEvento, obtener, registrar

    if obtener(ORGANIZACION_CAMBIADA) is not None:
        return
    registrar(
        TipoEvento(
            tipo=ORGANIZACION_CAMBIADA,
            version=1,
            productor="core",
            descripcion=(
                "Un tenant se ha mapeado a una organización del gestor documental. "
                "Lo consumen TODOS los servicios para replicarlo en su esquema"
            ),
            campos=("tenant_id", "organizacion"),
        )
    )


def _propagar_organizacion(db: Session, *, tenant_id: UUID, organizacion: str) -> None:
    """Replica el mapeo al resto de servicios.

    `organizaciones_documentales` vive en el esquema de CADA servicio y ninguno
    lee el de otro, exactamente igual que `ajustes_runtime` y las claves BYOK.
    Sin esto, mapear desde `party` dejaba a `sales` sin mapeo, y como **sin
    mapeo no se llama al gestor**, el corpus de las oportunidades habría quedado
    invisible mientras el de las cuentas funcionaba — con el administrador
    viendo su mapeo guardado y correcto.

    Va por la tabla de salida, en la misma transacción que la escritura.
    """
    from crmcore.bus.outbox import encolar

    declarar_evento_organizacion()
    encolar(
        db,
        tenant_id=tenant_id,
        tipo=ORGANIZACION_CAMBIADA,
        subject_tipo="tenant",
        subject_id=tenant_id,
        data={"tenant_id": str(tenant_id), "organizacion": organizacion},
        # El hecho es «este tenant apunta a esta organización». Fijarlo dos
        # veces al mismo valor es el mismo hecho.
        dedup_key=f"orgdoc:{tenant_id}:{organizacion}"[:64],
    )


async def consumir_organizacion(mensaje: Any) -> None:
    """Aplica en ESTE servicio el mapeo fijado en otro.

    Idempotente: escribe el valor tal cual. La entrega es at-least-once y
    recibirlo dos veces tiene que dejar el mismo estado.
    """
    from crmcore.db.uow import unidad_de_trabajo

    if isinstance(mensaje, dict):
        datos = mensaje.get("data") if isinstance(mensaje.get("data"), dict) else mensaje
    else:
        datos = getattr(mensaje, "data", None) or {}
    try:
        tenant_id = UUID(str(datos.get("tenant_id")))
    except (TypeError, ValueError):
        logger.error("documental.organizacion_sin_tenant", datos=str(datos)[:200])
        return
    organizacion = str(datos.get("organizacion") or "").strip()
    if not organizacion:
        return

    with unidad_de_trabajo(sistema=True) as uow:
        fila = (
            uow.db.execute(
                select(OrganizacionDocumental).where(OrganizacionDocumental.tenant_id == tenant_id)
            )
            .scalars()
            .first()
        )
        if fila is None:
            fila = OrganizacionDocumental(tenant_id=tenant_id)
            uow.db.add(fila)
        # NO se vuelve a llamar a `mapear_organizacion`: reemitiría el evento
        # al aplicarlo y el bus entraría en un bucle que crece con el número de
        # servicios. Es el mismo motivo por el que `_aplicar_local` está
        # separado de `fijar` en los ajustes.
        fila.organizacion = organizacion
        fila.estado = "activa"
        fila.ultimo_error = ""
    logger.info(
        "documental.organizacion_replicada",
        tenant=str(tenant_id),
        organizacion=organizacion,
    )


from crmcore.contratos import Consumo, declarar_consumo  # noqa: E402

# El evento se declara también al importar, y no solo la primera vez que alguien
# lo emite. Con la declaración perezosa, el gate de contratos podía correr sin
# que el productor existiera todavía y acusar al consumidor de esperar un evento
# que nadie publica. Las declaraciones son idempotentes, así que no cuesta nada.
declarar_evento_organizacion()


# Contrato dirigido por el consumidor (CRM-00.03.01.03): lo que este
# consumidor lee de verdad, para que el productor no lo quite creyendo que
# no lo usa nadie. El daño de quitarlo no se ve en el productor.
declarar_consumo(
    Consumo(
        consumidor="todos-los-servicios",
        evento=ORGANIZACION_CAMBIADA,
        campos=("tenant_id", "organizacion"),
        motivo=(
            "Rehacer la ruta de archivo de los documentos del tenant; sin "
            "`organizacion` quedan colgando del árbol anterior"
        ),
    )
)
