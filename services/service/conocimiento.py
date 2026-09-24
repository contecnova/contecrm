"""Base de conocimiento y su explotación
(CRM-04.03.01.01, .02, .03, .05, .06, .07).

Una base de conocimiento fracasa casi siempre por lo mismo, y no es por falta de
artículos: es porque **nadie sabe cuáles siguen siendo verdad**. A los dos años
hay ochocientos, la mitad describe una versión que ya no existe, y como nadie se
atreve a borrar nada, quien busca encuentra tres respuestas contradictorias y
deja de buscar.

De ahí las cuatro decisiones del módulo:

**Un artículo tiene versiones y estado, no solo texto.** Publicado, en revisión,
obsoleto. Editar directamente sobre lo publicado hace que un cambio a medias esté
en el portal del cliente mientras alguien lo escribe.

**La vigencia es obligatoria en lo que caduca.** Un artículo sobre una versión del
producto tiene fecha de caducidad aunque nadie quiera ponerla, y sin ella es el
que sigue apareciendo tres años después.

**La visibilidad es por audiencia y se declara.** Lo interno y lo que ve el cliente
no son lo mismo, y el fallo caro —publicar hacia fuera un procedimiento interno
con nombres de clientes dentro— ocurre siempre por omisión, no por decisión.

**Lo que no sirve se mide.** Un artículo con muchas visitas y pulgares abajo es
peor que no tenerlo: el cliente pierde el tiempo y **además** se queda sin llamar.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado, Prohibido
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    or_,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

if TYPE_CHECKING:  # pragma: no cover
    pass

# Audiencias, de más cerrada a más abierta. El orden importa: publicar hacia una
# audiencia más abierta que la declarada es lo que hay que impedir.
AUDIENCIAS = ("interno", "partner", "cliente", "publico")
ORDEN_AUDIENCIA = {a: i for i, a in enumerate(AUDIENCIAS)}

ESTADOS = ("borrador", "en_revision", "publicado", "obsoleto")


class Articulo(Base, TimestampMixin, SoftDeleteMixin):
    """Un artículo de conocimiento (CRM-04.03.01.01).

    El texto vive en `VersionArticulo`; aquí está lo que identifica al artículo y
    no cambia entre versiones. Separarlos es lo que permite publicar una versión
    mientras se escribe la siguiente, que es el caso normal en cuanto hay más de
    una persona.
    """

    __tablename__ = "articulos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(120), nullable=False)
    # Idioma original. Las traducciones cuelgan de él (CRM-04.03.01.03).
    idioma: Mapped[str] = mapped_column(String(10), nullable=False, default="es")
    original_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, index=True
    )

    categoria_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    etiquetas: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    # Audiencia máxima a la que puede llegar (CRM-04.03.01.02).
    audiencia: Mapped[str] = mapped_column(
        String(20), nullable=False, default="interno", info={"opciones": AUDIENCIAS}
    )
    # Canales donde puede aparecer: portal, chatbot, buscador público…
    canales: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="borrador", index=True)
    version_publicada: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Vigencia (CRM-04.03.01.01). `revisar_el` es lo que de verdad mantiene viva
    # una base de conocimiento: sin una fecha en la que alguien tiene que mirarlo,
    # un artículo correcto hoy sigue publicado tres años después describiendo una
    # versión que ya no existe.
    vigente_hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    revisar_el: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    autor_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    propietario_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # De qué caso salió, si nació de la resolución de uno (CRM-04.03.01.05).
    caso_origen_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    vistas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    utiles: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inutiles: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Veces que se enlazó a un caso: mide si sirve para trabajar, no solo si
    # gusta. Un artículo muy valorado que nadie usa en un caso es un artículo
    # bonito.
    usos_en_caso: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", "idioma", name="uq_articulo_clave"),
        Index("ix_articulos_publicados", "tenant_id", "estado", "audiencia"),
    )


class VersionArticulo(Base):
    """Una versión del texto. Append-only.

    No se edita: cada cambio es una versión nueva. Editar sobre lo publicado hace
    que un cambio a medias esté en el portal del cliente mientras alguien lo
    escribe, y deja sin forma de volver a lo que decía antes.
    """

    __tablename__ = "versiones_articulo"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    articulo_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("articulos.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    titulo: Mapped[str] = mapped_column(String(300), nullable=False)
    resumen: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cuerpo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    notas_cambio: Mapped[str] = mapped_column(Text, nullable=False, default="")
    autor_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    aprobada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    aprobada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("articulo_id", "version", name="uq_version_articulo"),
        Index("ix_versiones_articulo", "tenant_id", "articulo_id", "version"),
    )


class ValoracionArticulo(Base):
    """Un voto o un comentario sobre un artículo (CRM-04.03.01.06).

    Se guarda **de quién** viene aunque sea anónimo el contacto: sin eso, el mismo
    visitante puede votar cien veces y la métrica deja de significar nada. Y se
    guarda el comentario, que es lo único que dice **por qué** no sirve — el
    pulgar abajo solo dice que no.
    """

    __tablename__ = "valoraciones_articulo"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    articulo_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    util: Mapped[bool] = mapped_column(Boolean, nullable=False)
    comentario: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Identidad de quien vota: contacto, usuario o huella del visitante.
    votante: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    canal: Mapped[str] = mapped_column(String(20), nullable=False, default="portal")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("articulo_id", "votante", name="uq_valoracion_votante"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _articulo(db: Session, tenant_id: UUID, articulo_id: UUID) -> Articulo:
    fila = db.execute(
        select(Articulo).where(Articulo.id == articulo_id, Articulo.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("El artículo no existe", error_code="service.articulo_no_encontrado")
    return fila


# ── Alta, versiones y flujo de aprobación (CRM-04.03.01.01) ───────────────


def crear_articulo(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    titulo: str,
    cuerpo: str = "",
    resumen: str = "",
    idioma: str = "es",
    audiencia: str = "interno",
    **datos: Any,
) -> tuple[Articulo, VersionArticulo]:
    """Crea el artículo en borrador con su primera versión.

    Nace **en borrador y con audiencia interna**, y las dos cosas son
    deliberadas: el fallo caro de una base de conocimiento —publicar hacia fuera
    un procedimiento interno con nombres de clientes dentro— ocurre siempre por
    omisión, nunca por decisión.
    """
    if audiencia not in AUDIENCIAS:
        raise ErrorValidacion(
            f"Audiencia «{audiencia}» no válida.",
            error_code="service.audiencia_no_valida",
            detalle={"validas": list(AUDIENCIAS)},
        )
    tenant_id = uow.tenant_id
    if uow.db.execute(
        select(Articulo.id).where(
            Articulo.tenant_id == tenant_id,
            Articulo.clave == clave,
            Articulo.idioma == idioma,
        )
    ).first():
        raise Conflicto(
            "Ya existe un artículo con esa clave en ese idioma",
            error_code="service.articulo_duplicado",
        )

    articulo = Articulo(
        tenant_id=tenant_id,
        clave=clave,
        idioma=idioma,
        audiencia=audiencia,
        estado="borrador",
        **datos,
    )
    uow.db.add(articulo)
    uow.db.flush()

    version = VersionArticulo(
        tenant_id=tenant_id,
        articulo_id=articulo.id,
        version=1,
        titulo=titulo,
        resumen=resumen,
        cuerpo=cuerpo,
        autor_id=articulo.autor_id,
    )
    uow.db.add(version)
    uow.db.flush()
    return articulo, version


def nueva_version(
    uow: UnidadDeTrabajo,
    articulo_id: UUID,
    *,
    titulo: str,
    cuerpo: str,
    resumen: str = "",
    notas_cambio: str = "",
    autor_id: UUID | None = None,
) -> VersionArticulo:
    """Escribe una versión nueva sin tocar la publicada.

    Es lo que permite corregir un artículo que está en el portal sin que el
    cliente vea el texto a medias mientras se escribe.
    """
    articulo = _articulo(uow.db, uow.tenant_id, articulo_id)
    ultima = int(
        uow.db.execute(
            select(func.max(VersionArticulo.version)).where(
                VersionArticulo.articulo_id == articulo.id
            )
        ).scalar_one()
        or 0
    )
    fila = VersionArticulo(
        tenant_id=articulo.tenant_id,
        articulo_id=articulo.id,
        version=ultima + 1,
        titulo=titulo,
        resumen=resumen,
        cuerpo=cuerpo,
        notas_cambio=notas_cambio,
        autor_id=autor_id,
    )
    uow.db.add(fila)
    if articulo.estado == "publicado":
        # Vuelve a revisión, pero **la publicada sigue siendo la anterior**: el
        # cliente sigue viendo la versión buena mientras esta se revisa.
        articulo.estado = "en_revision"
    uow.db.flush()
    return fila


def publicar(
    uow: UnidadDeTrabajo,
    articulo_id: UUID,
    *,
    version: int | None = None,
    aprobada_por: UUID | None = None,
    audiencia: str | None = None,
) -> Articulo:
    """Publica una versión y la hace visible para su audiencia.

    Dos comprobaciones que no son formalismo:

    * **No se publica sin aprobación distinta del autor** cuando la audiencia
      sale de lo interno. Quien escribe un artículo no es quien mejor detecta que
      lleva dentro el nombre de un cliente.
    * **Un artículo sin fecha de revisión no llega al cliente.** Sin ella, nadie
      vuelve a mirarlo nunca, y es el que sigue apareciendo tres años después
      describiendo una versión que ya no existe.
    """
    articulo = _articulo(uow.db, uow.tenant_id, articulo_id)
    destino = audiencia or articulo.audiencia
    if destino not in AUDIENCIAS:
        raise ErrorValidacion(
            f"Audiencia «{destino}» no válida.", error_code="service.audiencia_no_valida"
        )

    fila = uow.db.execute(
        select(VersionArticulo)
        .where(
            VersionArticulo.articulo_id == articulo.id,
            *([VersionArticulo.version == version] if version else []),
        )
        .order_by(VersionArticulo.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("Esa versión no existe", error_code="service.version_no_encontrada")

    externo = ORDEN_AUDIENCIA[destino] >= ORDEN_AUDIENCIA["cliente"]
    if externo:
        if aprobada_por is None or aprobada_por == fila.autor_id:
            raise Prohibido(
                "Publicar hacia el cliente exige aprobación de alguien distinto "
                "del autor: quien escribe un artículo no es quien mejor detecta "
                "que lleva dentro el nombre de un cliente.",
                error_code="service.aprobacion_requerida",
            )
        if articulo.revisar_el is None:
            raise ErrorValidacion(
                "Un artículo publicado hacia fuera necesita fecha de revisión. "
                "Sin ella nadie vuelve a mirarlo, y es el que sigue apareciendo "
                "tres años después describiendo una versión que ya no existe.",
                error_code="service.sin_fecha_de_revision",
            )

    fila.aprobada_por = aprobada_por
    fila.aprobada_at = _ahora()
    articulo.estado = "publicado"
    articulo.version_publicada = fila.version
    articulo.audiencia = destino

    registrar(
        uow.db,
        accion="conocimiento.publicado",
        objeto="articulo",
        objeto_id=articulo.id,
        datos={
            "clave": articulo.clave,
            "version": fila.version,
            "audiencia": destino,
            "aprobada_por": str(aprobada_por) if aprobada_por else None,
        },
        tenant_id=articulo.tenant_id,
    )
    uow.emitir(
        "knowledge.published",
        subject=("articulo", articulo.id),
        data={
            "articulo_id": str(articulo.id),
            "clave": articulo.clave,
            "idioma": articulo.idioma,
            "version": fila.version,
            "audiencia": destino,
        },
    )
    return articulo


def marcar_obsoleto(
    uow: UnidadDeTrabajo, articulo_id: UUID, *, motivo: str, sustituye_a: UUID | None = None
) -> Articulo:
    """Retira un artículo sin borrarlo.

    Borrar rompe los enlaces que alguien pegó en un correo hace dos años, y quien
    los sigue recibe un «no existe» que parece un error del sistema. Marcado como
    obsoleto, se puede seguir abriendo con un aviso — y apuntando al que lo
    sustituye, que es lo que la persona buscaba de verdad.
    """
    if not (motivo or "").strip():
        raise ErrorValidacion(
            "Retirar un artículo exige decir por qué.",
            error_code="service.obsoleto_sin_motivo",
        )
    articulo = _articulo(uow.db, uow.tenant_id, articulo_id)
    articulo.estado = "obsoleto"
    articulo.etiquetas = [*(articulo.etiquetas or []), f"obsoleto:{motivo[:80]}"]
    if sustituye_a is not None:
        articulo.original_id = articulo.original_id or None
        articulo.etiquetas = [*articulo.etiquetas, f"sustituido_por:{sustituye_a}"]
    registrar(
        uow.db,
        accion="conocimiento.obsoleto",
        objeto="articulo",
        objeto_id=articulo.id,
        datos={"motivo": motivo, "sustituye_a": str(sustituye_a) if sustituye_a else None},
        tenant_id=articulo.tenant_id,
    )
    return articulo


# ── Traducciones (CRM-04.03.01.03) ────────────────────────────────────────


def traducir(
    uow: UnidadDeTrabajo,
    articulo_id: UUID,
    *,
    idioma: str,
    titulo: str,
    cuerpo: str,
    resumen: str = "",
) -> tuple[Articulo, VersionArticulo]:
    """Crea la traducción de un artículo, atada a su original.

    Se ata al original para poder decir después **si está sincronizada**: una
    traducción que se quedó en la versión 2 mientras el original va por la 5 es
    peor que no tenerla, porque el cliente que la lee cree que está leyendo lo
    vigente.
    """
    original = _articulo(uow.db, uow.tenant_id, articulo_id)
    if original.original_id is not None:
        raise ErrorValidacion(
            "No se traduce una traducción: cuelga del original.",
            error_code="service.traduccion_de_traduccion",
            detalle={"original": str(original.original_id)},
        )
    if idioma == original.idioma:
        raise ErrorValidacion(
            "El artículo ya está en ese idioma.", error_code="service.mismo_idioma"
        )

    traduccion, version = crear_articulo(
        uow,
        clave=original.clave,
        titulo=titulo,
        cuerpo=cuerpo,
        resumen=resumen,
        idioma=idioma,
        audiencia=original.audiencia,
        categoria_id=original.categoria_id,
        etiquetas=list(original.etiquetas or []),
        revisar_el=original.revisar_el,
        vigente_hasta=original.vigente_hasta,
    )
    traduccion.original_id = original.id
    # Se guarda contra qué versión del original se tradujo: es lo único que
    # permite decir después si se ha quedado atrás.
    traduccion.etiquetas = [
        *traduccion.etiquetas,
        f"traducido_de_v{original.version_publicada or 1}",
    ]
    uow.db.flush()
    return traduccion, version


_DE_VERSION = re.compile(r"traducido_de_v(\d+)")


def estado_de_traducciones(db: Session, tenant_id: UUID, articulo_id: UUID) -> dict[str, Any]:
    """Qué traducciones hay y cuáles se han quedado atrás.

    «Desincronizada» se dice explícitamente en vez de dejar que se note: una
    traducción vieja no falla, simplemente miente, y el cliente que la lee no
    tiene forma de saberlo.
    """
    original = _articulo(db, tenant_id, articulo_id)
    traducciones = (
        db.execute(select(Articulo).where(Articulo.original_id == original.id)).scalars().all()
    )
    actual = original.version_publicada or 0
    salida = []
    for fila in traducciones:
        marcas = [_DE_VERSION.match(str(e)) for e in (fila.etiquetas or [])]
        desde = next((int(m.group(1)) for m in marcas if m), 0)
        salida.append(
            {
                "idioma": fila.idioma,
                "articulo_id": str(fila.id),
                "estado": fila.estado,
                "traducido_de_version": desde,
                "sincronizada": desde >= actual,
                "versiones_por_detras": max(0, actual - desde),
            }
        )
    return {
        "articulo": str(original.id),
        "idioma_original": original.idioma,
        "version_publicada": actual,
        "traducciones": sorted(salida, key=lambda t: t["idioma"]),
        "desincronizadas": [t["idioma"] for t in salida if not t["sincronizada"]],
    }


# ── Knowledge-Centered Service (CRM-04.03.01.05) ──────────────────────────


def desde_caso(
    uow: UnidadDeTrabajo,
    caso_id: UUID,
    *,
    clave: str,
    titulo: str = "",
    cuerpo: str = "",
    audiencia: str = "interno",
) -> tuple[Articulo, VersionArticulo]:
    """Crea un artículo a partir de la resolución de un caso.

    El sitio y el momento importan: se escribe **cuando se resuelve**, con el
    problema fresco y por quien lo resolvió. Pedirlo después, en una sesión
    dedicada, es como no pedirlo — el conocimiento se pierde entre el caso
    cerrado y la reunión del viernes.

    Nace en **borrador e interno** aunque venga de un caso resuelto: el texto de
    una resolución lleva casi siempre el nombre del cliente, su configuración y a
    veces sus credenciales. Publicarlo directo hacia fuera sería la fuga más
    tonta posible.
    """
    from services.service import servicio as svc

    caso = svc.exigir_caso(uow.db, caso_id)
    if caso.estado not in ("resuelto", "cerrado"):
        raise Conflicto(
            "El caso todavía no está resuelto: el artículo saldría de una "
            "solución que aún no se sabe si funciona.",
            error_code="service.caso_no_resuelto",
        )

    articulo, version = crear_articulo(
        uow,
        clave=clave,
        titulo=titulo or caso.asunto,
        cuerpo=cuerpo or (caso.resolucion or ""),
        resumen=(caso.descripcion or "")[:500],
        audiencia="interno" if audiencia != "interno" else audiencia,
        categoria_id=caso.categoria_id,
        caso_origen_id=caso.id,
    )
    uow.db.add(
        __import__("services.service.modelos", fromlist=["EventoCaso"]).EventoCaso(
            tenant_id=caso.tenant_id,
            caso_id=caso.id,
            tipo="articulo_creado",
            detalle={"articulo_id": str(articulo.id), "clave": clave},
        )
    )
    return articulo, version


def enlazar_a_caso(uow: UnidadDeTrabajo, articulo_id: UUID, caso_id: UUID) -> Articulo:
    """Registra que este artículo se usó para resolver un caso.

    Es la métrica que de verdad dice si sirve: un artículo muy valorado que nadie
    usa en un caso es un artículo bonito. Y es lo que permite medir la deflexión
    —cuántos casos no se abrieron— comparando usos contra visitas en el portal.
    """
    from services.service import servicio as svc
    from services.service.modelos import EventoCaso

    articulo = _articulo(uow.db, uow.tenant_id, articulo_id)
    caso = svc.exigir_caso(uow.db, caso_id)
    articulo.usos_en_caso += 1
    uow.db.add(
        EventoCaso(
            tenant_id=caso.tenant_id,
            caso_id=caso.id,
            tipo="articulo_usado",
            detalle={"articulo_id": str(articulo.id), "clave": articulo.clave},
        )
    )
    return articulo


# ── Valoración y eficacia (CRM-04.03.01.06) ───────────────────────────────


def valorar(
    uow: UnidadDeTrabajo,
    articulo_id: UUID,
    *,
    util: bool,
    votante: str,
    comentario: str = "",
    canal: str = "portal",
) -> ValoracionArticulo:
    """Un voto por votante. Cambiar de opinión sustituye el voto anterior.

    Un voto por votante y no uno por pulsación: sin eso, el mismo visitante puede
    votar cien veces y la métrica deja de significar nada — y el primero que lo
    descubra decidirá qué artículos parecen buenos.
    """
    articulo = _articulo(uow.db, uow.tenant_id, articulo_id)
    if not (votante or "").strip():
        raise ErrorValidacion(
            "Hace falta saber quién vota, aunque sea de forma anónima.",
            error_code="service.voto_sin_votante",
        )

    fila = uow.db.execute(
        select(ValoracionArticulo).where(
            ValoracionArticulo.articulo_id == articulo.id,
            ValoracionArticulo.votante == votante,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = ValoracionArticulo(
            tenant_id=articulo.tenant_id,
            articulo_id=articulo.id,
            votante=votante,
            util=util,
            canal=canal,
        )
        uow.db.add(fila)
        articulo.utiles += 1 if util else 0
        articulo.inutiles += 0 if util else 1
    else:
        if fila.util != util:
            articulo.utiles += 1 if util else -1
            articulo.inutiles += -1 if util else 1
        fila.util = util
    fila.version = articulo.version_publicada
    fila.comentario = comentario or fila.comentario
    uow.db.flush()
    return fila


def eficacia(db: Session, tenant_id: UUID, *, minimo_vistas: int = 20) -> dict[str, Any]:
    """Qué artículos sirven, cuáles estorban y cuáles nadie usa.

    Las tres listas responden a tres decisiones distintas:

    * **Dañinos**: muchas visitas y pulgar abajo. Es **peor que no tenerlos**: el
      cliente pierde el tiempo y además se queda sin llamar.
    * **Huérfanos**: publicados y sin visitas. O no se encuentran, o no hacían
      falta; en los dos casos, ocupan sitio en los resultados de búsqueda.
    * **Caducados**: pasada su fecha de revisión. Son los que siguen describiendo
      una versión que ya no existe.

    El mínimo de visitas está para que un artículo con dos visitas y un voto
    negativo no salga como el peor de la base.
    """
    articulos = db.execute(select(Articulo).where(Articulo.tenant_id == tenant_id)).scalars().all()
    hoy = date.today()

    dañinos, huerfanos, caducados = [], [], []
    for a in articulos:
        votos = a.utiles + a.inutiles
        if a.vistas >= minimo_vistas and votos and a.inutiles > a.utiles:
            dañinos.append(
                {
                    "clave": a.clave,
                    "idioma": a.idioma,
                    "vistas": a.vistas,
                    "utiles": a.utiles,
                    "inutiles": a.inutiles,
                    "usos_en_caso": a.usos_en_caso,
                }
            )
        if a.estado == "publicado" and a.vistas == 0 and a.usos_en_caso == 0:
            huerfanos.append({"clave": a.clave, "idioma": a.idioma})
        if a.revisar_el is not None and a.revisar_el < hoy and a.estado == "publicado":
            caducados.append(
                {
                    "clave": a.clave,
                    "idioma": a.idioma,
                    "revisar_el": a.revisar_el.isoformat(),
                    "dias_vencido": (hoy - a.revisar_el).days,
                }
            )

    publicados = [a for a in articulos if a.estado == "publicado"]
    vistas = sum(a.vistas for a in publicados)
    usos = sum(a.usos_en_caso for a in publicados)
    return {
        "articulos": len(articulos),
        "publicados": len(publicados),
        "dañinos": sorted(dañinos, key=lambda a: -a["vistas"]),
        "huerfanos": huerfanos,
        "caducados": sorted(caducados, key=lambda a: -a["dias_vencido"]),
        "vistas": vistas,
        "usos_en_caso": usos,
        # Deflexión aproximada: visitas que NO acabaron en un caso. Se dice
        # «aproximada» a propósito — no se puede saber si quien leyó y no abrió
        # caso es porque le sirvió o porque se rindió, y presentarlo como exacto
        # sería inventarse un número que después alguien cita en una reunión.
        "deflexion_aproximada_pct": (
            round(100 * max(0, vistas - usos) / vistas, 1) if vistas else None
        ),
        "aviso_deflexion": (
            "Es una aproximación: no se puede distinguir a quien leyó y le sirvió "
            "de quien leyó y se rindió."
        ),
    }


# ── Búsqueda y API pública (CRM-04.03.01.02, .07) ─────────────────────────


def buscar(
    db: Session,
    tenant_id: UUID,
    *,
    texto: str = "",
    audiencia: str = "interno",
    canal: str = "",
    idioma: str = "",
    limite: int = 20,
) -> list[dict[str, Any]]:
    """Busca artículos **visibles para esa audiencia y no por encima**.

    El filtro por audiencia se aplica aquí y no en quien llama: si dependiera del
    llamante, bastaría una ruta nueva que se olvidara de pasarlo para que el
    portal público sirviera los procedimientos internos. Se pide la audiencia y se
    devuelve solo lo que llega hasta ella.
    """
    if audiencia not in AUDIENCIAS:
        raise ErrorValidacion(
            f"Audiencia «{audiencia}» no válida.", error_code="service.audiencia_no_valida"
        )
    tope = ORDEN_AUDIENCIA[audiencia]
    consulta = (
        select(Articulo, VersionArticulo)
        .join(
            VersionArticulo,
            (VersionArticulo.articulo_id == Articulo.id)
            & (VersionArticulo.version == Articulo.version_publicada),
        )
        .where(
            Articulo.tenant_id == tenant_id,
            Articulo.estado == "publicado",
            Articulo.audiencia.in_([a for a in AUDIENCIAS if ORDEN_AUDIENCIA[a] >= tope]),
        )
    )
    if idioma:
        consulta = consulta.where(Articulo.idioma == idioma)
    if canal:
        consulta = consulta.where(Articulo.canales.contains([canal]))
    if texto:
        patron = f"%{texto}%"
        consulta = consulta.where(
            or_(
                VersionArticulo.titulo.ilike(patron),
                VersionArticulo.resumen.ilike(patron),
                VersionArticulo.cuerpo.ilike(patron),
            )
        )

    hoy = date.today()
    filas = db.execute(consulta.limit(limite)).all()
    return [
        {
            "articulo_id": str(a.id),
            "clave": a.clave,
            "idioma": a.idioma,
            "titulo": v.titulo,
            "resumen": v.resumen,
            "version": v.version,
            "utiles": a.utiles,
            "inutiles": a.inutiles,
            # Se marca lo que ya debería haberse revisado en vez de esconderlo:
            # ocultarlo dejaría al cliente sin respuesta, y enseñarlo sin avisar
            # le daría una que puede estar vieja. Decirlo es lo único honesto.
            "pendiente_de_revision": bool(a.revisar_el and a.revisar_el < hoy),
        }
        for a, v in filas
    ]


def leer(
    db: Session, tenant_id: UUID, articulo_id: UUID, *, audiencia: str = "interno"
) -> dict[str, Any]:
    """Un artículo, comprobando que llega a esa audiencia."""
    articulo = _articulo(db, tenant_id, articulo_id)
    if ORDEN_AUDIENCIA[articulo.audiencia] < ORDEN_AUDIENCIA[audiencia]:
        # 404 y no 403: un 403 confirma que el artículo existe, y con eso se
        # puede recorrer el catálogo interno preguntando por identificadores.
        raise NoEncontrado("El artículo no existe", error_code="service.articulo_no_encontrado")
    if articulo.estado != "publicado" and ORDEN_AUDIENCIA[audiencia] >= ORDEN_AUDIENCIA["cliente"]:
        raise NoEncontrado("El artículo no existe", error_code="service.articulo_no_encontrado")

    version = db.execute(
        select(VersionArticulo).where(
            VersionArticulo.articulo_id == articulo.id,
            VersionArticulo.version == (articulo.version_publicada or 1),
        )
    ).scalar_one_or_none()
    hoy = date.today()
    return {
        "articulo_id": str(articulo.id),
        "clave": articulo.clave,
        "idioma": articulo.idioma,
        "estado": articulo.estado,
        "titulo": version.titulo if version else "",
        "cuerpo": version.cuerpo if version else "",
        "version": version.version if version else None,
        "utiles": articulo.utiles,
        "inutiles": articulo.inutiles,
        "obsoleto": articulo.estado == "obsoleto",
        "pendiente_de_revision": bool(articulo.revisar_el and articulo.revisar_el < hoy),
        "aviso": (
            "Este artículo está retirado y puede no ser correcto."
            if articulo.estado == "obsoleto"
            else ""
        ),
    }


def anotar_vista(db: Session, tenant_id: UUID, articulo_id: UUID) -> None:
    """Suma una visita. No falla nunca: perder una estadística es aceptable,
    que un portal de cliente devuelva error por contarla no lo es."""
    try:
        articulo = _articulo(db, tenant_id, articulo_id)
        articulo.vistas += 1
    except Exception:  # noqa: BLE001
        logger.warning("conocimiento.vista_no_anotada", articulo=str(articulo_id))
