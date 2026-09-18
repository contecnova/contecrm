"""Comentarios, hilos y menciones sobre registros (CRM-06.02.01.01).

La conversación sobre un cliente ocurre igualmente: en el correo, en el chat o
de viva voz. La diferencia es que si ocurre fuera del CRM, se pierde — y con
ella el motivo por el que se hizo el descuento, quién dijo que llamaría y qué
respondió el cliente. Traerla dentro es lo que convierte la ficha en algo que
explica el caso y no solo en un formulario.

Tres decisiones:

**Las menciones se extraen del texto, no se aceptan como lista aparte.** El
cuerpo lleva `@[Nombre](identificador)` y el servidor deriva de ahí a quién se
menciona. Con una lista separada habría dos fuentes de verdad y, en cuanto
alguien edite el texto quitando una mención, seguiría notificando a quien ya no
aparece. El formato es explícito a propósito: resolver `@ana` contra un
directorio de usuarios obliga a consultar identidad en cada guardado y falla en
cuanto hay dos Anas.

**Mencionar a alguien lo suscribe.** Es lo que espera quien escribe: nombrar a
un compañero para que se entere y que luego no se entere de la respuesta sería
absurdo. Se suscribe, y desde ahí puede silenciarlo como cualquier otro
seguimiento.

**Un comentario no se borra: se marca.** Es un hecho de la conversación y suele
ser justo lo que alguien quiere borrar cuando el caso se tuerce. Se conserva el
autor y la fecha, y quien lo lea ve que hubo algo y que se retiró.
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
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.db.base import Base
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado, Prohibido
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger

logger = get_logger(__name__)

# `@[Nombre visible](uuid)`. El nombre es para leerlo; el identificador es lo
# que vale. Guardar solo el nombre haría que renombrar a alguien rompiera las
# menciones antiguas; guardar solo el identificador haría el texto ilegible en
# cualquier sitio que no resuelva nombres.
RE_MENCION = re.compile(r"@\[([^\]]{1,120})\]\(([0-9a-fA-F-]{36})\)")


class Comentario(Base):
    """Un mensaje sobre un registro, opcionalmente dentro de un hilo."""

    __tablename__ = "comentarios"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    objeto_tipo: Mapped[str] = mapped_column(String(60), nullable=False)
    objeto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    # Raíz del hilo. Un comentario de primer nivel se apunta a sí mismo, así que
    # «dame el hilo entero» es una consulta por `hilo_id` sin recorrer punteros
    # ni limitar la profundidad con un CTE recursivo.
    hilo_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # Respuesta directa a otro comentario, para poder pintar el anidamiento.
    padre_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    cuerpo: Mapped[str] = mapped_column(Text, nullable=False)
    # Derivadas del cuerpo, nunca recibidas de fuera. Se guardan resueltas para
    # poder responder «¿dónde me han mencionado?» sin recorrer todos los textos.
    menciones: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    autor_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # `interno` es el que no debe salir nunca hacia el cliente: ni al portal, ni
    # en un correo automático, ni en una exportación para el interesado. Es la
    # diferencia entre una nota de trabajo y algo que se comparte.
    interno: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    editado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ediciones: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    borrado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    borrado_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # Solo en la raíz del hilo: un hilo se da por cerrado cuando la pregunta que
    # lo abrió tiene respuesta. Sirve para que la ficha no acumule conversaciones
    # abiertas que ya nadie va a contestar.
    resuelto_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resuelto_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_comentarios_objeto", "tenant_id", "objeto_tipo", "objeto_id", "created_at"),
        Index("ix_comentarios_hilo", "tenant_id", "hilo_id", "created_at"),
        Index("ix_comentarios_autor", "tenant_id", "autor_id", "created_at"),
    )


def extraer_menciones(cuerpo: str) -> list[str]:
    """Identificadores mencionados en el texto, sin repetir y en orden.

    Sin repetir porque mencionar a alguien dos veces en el mismo comentario no
    son dos avisos; en orden porque el resultado se enseña y un orden aleatorio
    haría que el mismo comentario se viera distinto en cada carga.
    """
    vistos: list[str] = []
    for _, identificador in RE_MENCION.findall(cuerpo or ""):
        clave = identificador.lower()
        if clave not in vistos:
            vistos.append(clave)
    return vistos


def crear(
    db: Session,
    *,
    tenant_id: UUID,
    objeto_tipo: str,
    objeto_id: UUID,
    cuerpo: str,
    autor_id: UUID | None = None,
    padre_id: UUID | None = None,
    interno: bool = True,
) -> Comentario:
    """Escribe un comentario, o una respuesta si se pasa `padre_id`."""
    from crmcore.runtime import settings as rt

    cuerpo = (cuerpo or "").strip()
    if not cuerpo:
        raise ErrorValidacion(
            "Un comentario vacío no es un comentario", error_code="comentario.vacio"
        )
    tope = int(rt.efectivo("comentario_max_caracteres", db) or 10_000)
    if len(cuerpo) > tope:
        raise ErrorValidacion(
            f"El comentario ocupa {len(cuerpo)} caracteres y el máximo son {tope}",
            error_code="comentario.demasiado_largo",
            detalle={"longitud": len(cuerpo), "maximo": tope},
        )

    hilo_id: UUID
    if padre_id is not None:
        padre = db.get(Comentario, padre_id)
        if padre is None or padre.tenant_id != tenant_id:
            raise NoEncontrado(
                "No existe el comentario al que respondes",
                error_code="comentario.padre_no_existe",
            )
        if padre.objeto_id != objeto_id or padre.objeto_tipo != objeto_tipo:
            # Responder a un comentario de otro registro partiría el hilo en dos
            # fichas y dejaría media conversación invisible desde cada una.
            raise Conflicto(
                "No se puede responder a un comentario de otro registro",
                error_code="comentario.padre_de_otro_objeto",
            )
        hilo_id = padre.hilo_id
    else:
        hilo_id = nuevo_id()

    menciones = extraer_menciones(cuerpo)
    tope_menciones = int(rt.efectivo("comentario_max_menciones", db) or 20)
    if len(menciones) > tope_menciones:
        # Sin tope, un solo comentario genera un aviso para toda la empresa — y
        # el que lo recibe deja de leer los avisos para siempre.
        raise ErrorValidacion(
            f"El comentario menciona a {len(menciones)} personas y el máximo son "
            f"{tope_menciones}",
            error_code="comentario.demasiadas_menciones",
            detalle={"menciones": len(menciones), "maximo": tope_menciones},
        )

    comentario = Comentario(
        tenant_id=tenant_id,
        objeto_tipo=objeto_tipo,
        objeto_id=objeto_id,
        hilo_id=hilo_id,
        padre_id=padre_id,
        cuerpo=cuerpo,
        menciones=menciones,
        autor_id=autor_id,
        interno=interno,
    )
    db.add(comentario)
    db.flush()
    # El primero del hilo es su propia raíz: así el hilo se consulta por
    # `hilo_id` sin casos especiales.
    if padre_id is None:
        comentario.hilo_id = comentario.id
        db.flush()

    logger.info(
        "comentario.creado",
        comentario=str(comentario.id),
        objeto=f"{objeto_tipo}:{objeto_id}",
        menciones=len(comentario.menciones),
    )
    return comentario


def editar(db: Session, comentario_id: UUID, *, cuerpo: str, por: UUID | None = None) -> Comentario:
    """Cambia el texto. Solo el autor, y queda marcado como editado.

    Que se marque no es un detalle estético: alguien contestó a lo que ponía
    antes, y sin la marca esa respuesta parece no venir a cuento.
    """
    comentario = _traer(db, comentario_id)
    if comentario.autor_id is not None and por is not None and comentario.autor_id != por:
        raise Prohibido(
            "Solo el autor puede editar su comentario",
            error_code="comentario.no_es_tuyo",
        )
    cuerpo = (cuerpo or "").strip()
    if not cuerpo:
        raise ErrorValidacion(
            "Un comentario vacío no es un comentario", error_code="comentario.vacio"
        )

    comentario.cuerpo = cuerpo
    comentario.menciones = extraer_menciones(cuerpo)
    comentario.editado_at = datetime.now(timezone.utc)
    comentario.ediciones += 1
    return comentario


def borrar(db: Session, comentario_id: UUID, *, por: UUID | None = None) -> Comentario:
    """Marca el comentario como borrado. No lo quita.

    Se conservan autor y fecha: quien lea el hilo ve que hubo algo y que se
    retiró. Borrarlo de verdad dejaría las respuestas colgando de la nada.
    """
    comentario = _traer(db, comentario_id)
    comentario.borrado_at = datetime.now(timezone.utc)
    comentario.borrado_por = por
    return comentario


def resolver(
    db: Session, hilo_id: UUID, *, por: UUID | None = None, resuelto: bool = True
) -> Comentario:
    """Marca (o desmarca) un hilo como resuelto. Solo sobre su raíz."""
    raiz = db.get(Comentario, hilo_id)
    if raiz is None or raiz.hilo_id != raiz.id:
        raise NoEncontrado("No existe ese hilo", error_code="comentario.hilo_no_existe")
    raiz.resuelto_at = datetime.now(timezone.utc) if resuelto else None
    raiz.resuelto_por = por if resuelto else None
    return raiz


def _traer(db: Session, comentario_id: UUID) -> Comentario:
    comentario = db.get(Comentario, comentario_id)
    if comentario is None or comentario.borrado_at is not None:
        raise NoEncontrado("Comentario no encontrado", error_code="comentario.no_existe")
    return comentario


def de_registro(
    db: Session,
    *,
    tenant_id: UUID,
    objeto_tipo: str,
    objeto_id: UUID,
    incluir_internos: bool = True,
    solo_sin_resolver: bool = False,
    limite: int = 200,
) -> list[dict[str, Any]]:
    """Los hilos de un registro, cada uno con sus respuestas.

    Agrupado por hilo y no como lista plana: una conversación leída como una
    lista de mensajes sueltos ordenados por fecha no se entiende en cuanto hay
    dos temas a la vez, que es siempre.

    `incluir_internos=False` es lo que se usa para un portal de cliente. Está
    aquí y no en quien llama a propósito: la decisión de qué ve un externo no
    puede depender de que cada sitio se acuerde de filtrar.
    """
    consulta = select(Comentario).where(
        Comentario.tenant_id == tenant_id,
        Comentario.objeto_tipo == objeto_tipo,
        Comentario.objeto_id == objeto_id,
    )
    if not incluir_internos:
        consulta = consulta.where(Comentario.interno.is_(False))

    filas = list(db.execute(consulta.order_by(Comentario.created_at).limit(limite)).scalars().all())

    hilos: dict[UUID, dict[str, Any]] = {}
    for fila in filas:
        hilo = hilos.setdefault(
            fila.hilo_id,
            {"hilo_id": str(fila.hilo_id), "resuelto": False, "resuelto_at": None, "mensajes": []},
        )
        if fila.id == fila.hilo_id:
            hilo["resuelto"] = fila.resuelto_at is not None
            hilo["resuelto_at"] = fila.resuelto_at.isoformat() if fila.resuelto_at else None
        hilo["mensajes"].append(_salida(fila))

    salida = list(hilos.values())
    if solo_sin_resolver:
        salida = [h for h in salida if not h["resuelto"]]
    return salida


def _salida(c: Comentario) -> dict[str, Any]:
    borrado = c.borrado_at is not None
    return {
        "id": str(c.id),
        "padre_id": str(c.padre_id) if c.padre_id else None,
        # El cuerpo de un borrado NO se devuelve. Marcarlo y seguir mandando el
        # texto sería un borrado de mentira: cualquiera que mire la respuesta de
        # la API lo lee igual.
        "cuerpo": "" if borrado else c.cuerpo,
        "borrado": borrado,
        "menciones": [] if borrado else (c.menciones or []),
        "autor_id": str(c.autor_id) if c.autor_id else None,
        "interno": c.interno,
        "editado": c.editado_at is not None,
        "ediciones": c.ediciones,
        "cuando": c.created_at.isoformat() if c.created_at else None,
    }


def donde_me_mencionan(
    db: Session, *, tenant_id: UUID, usuario_id: UUID, limite: int = 50
) -> list[dict[str, Any]]:
    """Comentarios que mencionan a alguien, del más reciente atrás.

    Con `contains` sobre el JSONB —no con un `LIKE` sobre el texto—: buscar el
    identificador dentro del cuerpo encontraría también el comentario donde
    alguien lo pegó como referencia, sin mencionar a nadie.
    """
    filas = (
        db.execute(
            select(Comentario)
            .where(
                Comentario.tenant_id == tenant_id,
                Comentario.borrado_at.is_(None),
                Comentario.menciones.contains([str(usuario_id).lower()]),
            )
            .order_by(Comentario.created_at.desc())
            .limit(limite)
        )
        .scalars()
        .all()
    )
    return [
        {**_salida(f), "objeto_tipo": f.objeto_tipo, "objeto_id": str(f.objeto_id)} for f in filas
    ]
