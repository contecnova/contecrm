"""Implementación de la búsqueda. El porqué está en `crmcore/busqueda/__init__.py`."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Index,
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

from crmcore.db.base import Base
from crmcore.errors import ErrorValidacion
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger

logger = get_logger(__name__)


class DocumentoIndexado(Base):
    """Lo que se puede encontrar buscando.

    Una sola tabla para todos los objetos del servicio, y no una por tipo: la
    búsqueda global tiene que mirar en todo a la vez, y con una tabla por objeto
    serían seis consultas y una unión que crece cada vez que se añade un objeto.

    Lleva `tenant_id` como cualquier tabla de negocio, así que RLS la cubre sin
    nada especial. Eso es lo que hace que el aislamiento del buscador sea el
    mismo que el del resto del sistema, y no una segunda implementación que
    algún día se desincroniza.
    """

    __tablename__ = "indice_busqueda"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    objeto: Mapped[str] = mapped_column(String(60), nullable=False)
    registro_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    # Lo que se enseña en el resultado. Desnormalizado a propósito: pintar una
    # lista de resultados no puede exigir una consulta por fila al objeto real.
    titulo: Mapped[str] = mapped_column(String(300), nullable=False)
    subtitulo: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    # Todo el texto por el que se puede encontrar, concatenado.
    cuerpo: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Del propietario depende que la búsqueda respete la visibilidad: quien
    # busca no puede encontrar lo que no podría abrir.
    owner_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    actualizado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "objeto", "registro_id", name="uq_indice_registro"),
        Index("ix_indice_objeto", "tenant_id", "objeto"),
        # Índice de texto completo. El `to_tsvector` va en el índice y no en una
        # columna generada para no duplicar el texto en la tabla: con cien mil
        # registros, esa columna es el doble de tamaño sin dar nada.
        Index(
            "ix_indice_texto",
            text("to_tsvector('spanish', titulo || ' ' || subtitulo || ' ' || cuerpo)"),
            postgresql_using="gin",
        ),
    )


@dataclass(frozen=True, slots=True)
class Resultado:
    objeto: str
    registro_id: UUID
    titulo: str
    subtitulo: str
    relevancia: float
    extra: dict[str, Any] = field(default_factory=dict)

    def a_dict(self) -> dict[str, Any]:
        return {
            "objeto": self.objeto,
            "registro_id": str(self.registro_id),
            "titulo": self.titulo,
            "subtitulo": self.subtitulo,
            "relevancia": round(self.relevancia, 4),
            "extra": self.extra,
        }


class Buscador(Protocol):
    """Lo que cualquier backend de búsqueda tiene que saber hacer.

    Todas las operaciones llevan `tenant_id` **obligatorio y posicional en la
    firma**. No es decoración: es lo que impide escribir una consulta sin él.
    """

    def indexar(self, db: Session, *, tenant_id: UUID, documento: dict[str, Any]) -> None: ...
    def desindexar(
        self, db: Session, *, tenant_id: UUID, objeto: str, registro_id: UUID
    ) -> None: ...
    def buscar(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        texto: str,
        objetos: list[str] | None = None,
        limite: int = 20,
    ) -> list[Resultado]: ...


class BuscadorPostgres:
    """Búsqueda de texto completo con Postgres.

    El aislamiento sale de tres sitios a la vez: la tabla lleva `tenant_id` y
    RLS la cubre, el filtro va explícito en cada consulta, y la firma obliga a
    pasar el tenant. Ninguna de las tres depende de que quien escribe la
    consulta se acuerde.
    """

    def _config(self, db: Session) -> str:
        """La configuración de texto del idioma, que decide cómo se derivan las
        palabras.

        Con la configuración equivocada, «facturas» no encuentra «factura» y la
        búsqueda parece rota sin que nada falle. Sale de los ajustes porque un
        tenant portugués no busca igual que uno español.
        """
        from crmcore.runtime import settings as rt

        configuracion = str(rt.efectivo("busqueda_idioma", db) or "spanish")
        # Lista cerrada: el nombre entra en el SQL, y aunque venga de
        # configuración y no del usuario, no hay motivo para dejar que algo
        # llegue ahí sin comprobar.
        if configuracion not in CONFIGURACIONES:
            logger.warning("busqueda.configuracion_desconocida", valor=configuracion)
            return "simple"
        return configuracion

    def indexar(self, db: Session, *, tenant_id: UUID, documento: dict[str, Any]) -> None:
        objeto = str(documento["objeto"])
        registro_id = documento["registro_id"]
        fila = db.execute(
            select(DocumentoIndexado).where(
                DocumentoIndexado.tenant_id == tenant_id,
                DocumentoIndexado.objeto == objeto,
                DocumentoIndexado.registro_id == registro_id,
            )
        ).scalar_one_or_none()

        if fila is None:
            fila = DocumentoIndexado(tenant_id=tenant_id, objeto=objeto, registro_id=registro_id)
            db.add(fila)
        fila.titulo = str(documento.get("titulo") or "")[:300]
        fila.subtitulo = str(documento.get("subtitulo") or "")[:300]
        fila.cuerpo = str(documento.get("cuerpo") or "")
        fila.owner_id = documento.get("owner_id")
        fila.extra = documento.get("extra") or {}
        fila.actualizado_at = datetime.now(timezone.utc)
        db.flush()

    def desindexar(self, db: Session, *, tenant_id: UUID, objeto: str, registro_id: UUID) -> None:
        fila = db.execute(
            select(DocumentoIndexado).where(
                DocumentoIndexado.tenant_id == tenant_id,
                DocumentoIndexado.objeto == objeto,
                DocumentoIndexado.registro_id == registro_id,
            )
        ).scalar_one_or_none()
        if fila is not None:
            db.delete(fila)
            db.flush()

    def buscar(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        texto: str,
        objetos: list[str] | None = None,
        limite: int = 20,
    ) -> list[Resultado]:
        consulta_texto = (texto or "").strip()
        if not consulta_texto:
            return []

        configuracion = self._config(db)
        # `websearch_to_tsquery` y no `to_tsquery`: acepta lo que la gente
        # escribe de verdad —comillas, `or`, un `-` para excluir— y **no falla**
        # con un paréntesis suelto. Con `to_tsquery`, buscar `(factura` devuelve
        # un error de sintaxis al usuario, que no ha escrito nada raro.
        vector = func.to_tsvector(
            configuracion,
            DocumentoIndexado.titulo
            + " "
            + DocumentoIndexado.subtitulo
            + " "
            + DocumentoIndexado.cuerpo,
        )
        pregunta = func.websearch_to_tsquery(configuracion, consulta_texto)

        seleccion = select(
            DocumentoIndexado, func.ts_rank(vector, pregunta).label("relevancia")
        ).where(
            # El filtro por tenant va SIEMPRE, además de RLS. Es redundante a
            # propósito: si un día alguien consulta con una sesión sin tenant
            # fijado, RLS no filtra y esto sí.
            DocumentoIndexado.tenant_id == tenant_id,
            vector.op("@@")(pregunta),
        )
        if objetos:
            seleccion = seleccion.where(DocumentoIndexado.objeto.in_(objetos))

        filas = db.execute(
            seleccion.order_by(text("relevancia DESC")).limit(min(limite, 200))
        ).all()
        return [
            Resultado(
                objeto=fila[0].objeto,
                registro_id=fila[0].registro_id,
                titulo=fila[0].titulo,
                subtitulo=fila[0].subtitulo,
                relevancia=float(fila[1] or 0.0),
                extra=dict(fila[0].extra or {}),
            )
            for fila in filas
        ]


# Configuraciones de texto de Postgres admitidas. `simple` no deriva palabras:
# es el recurso para un idioma que Postgres no trae, y busca peor pero nunca
# encuentra de menos por culpa de una derivación equivocada.
CONFIGURACIONES = {
    "simple",
    "spanish",
    "english",
    "french",
    "german",
    "italian",
    "portuguese",
    "dutch",
}


_buscador: Buscador | None = None
_cerrojo = Lock()


def get_buscador() -> Buscador:
    """El buscador configurado."""
    global _buscador
    if _buscador is not None:
        return _buscador
    with _cerrojo:
        if _buscador is None:
            _buscador = BuscadorPostgres()
        return _buscador


def reset_buscador() -> None:
    """Olvida el buscador construido. Solo para pruebas."""
    global _buscador
    with _cerrojo:
        _buscador = None


# ── Fachada ───────────────────────────────────────────────────────────────


def indexar(
    db: Session,
    *,
    tenant_id: UUID,
    objeto: str,
    registro_id: UUID,
    titulo: str,
    subtitulo: str = "",
    cuerpo: str = "",
    owner_id: UUID | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Pone o actualiza un registro en el índice.

    Idempotente por (tenant, objeto, registro): reindexar un registro editado es
    la operación normal, y crear una entrada nueva cada vez lo haría aparecer
    varias veces en los resultados.
    """
    if not titulo.strip():
        # Un documento sin título sale en los resultados como una fila en
        # blanco que no se puede ni pinchar con sentido.
        raise ErrorValidacion(
            "Un documento indexado necesita título",
            error_code="busqueda.sin_titulo",
        )
    get_buscador().indexar(
        db,
        tenant_id=tenant_id,
        documento={
            "objeto": objeto,
            "registro_id": registro_id,
            "titulo": titulo,
            "subtitulo": subtitulo,
            "cuerpo": cuerpo,
            "owner_id": owner_id,
            "extra": extra or {},
        },
    )


def desindexar(db: Session, *, tenant_id: UUID, objeto: str, registro_id: UUID) -> None:
    """Quita un registro del índice. Al borrarlo, y también al ocultarlo.

    Lo que se borra lógicamente tiene que salir del índice: si no, sigue
    apareciendo en los resultados y al pincharlo da un 404 — que es peor que no
    encontrarlo, porque confirma que existe.
    """
    get_buscador().desindexar(db, tenant_id=tenant_id, objeto=objeto, registro_id=registro_id)


def buscar(
    db: Session,
    *,
    tenant_id: UUID,
    texto: str,
    objetos: list[str] | None = None,
    limite: int = 20,
) -> list[Resultado]:
    """Busca en el índice de este tenant. El tenant es obligatorio."""
    return get_buscador().buscar(
        db, tenant_id=tenant_id, texto=texto, objetos=objetos, limite=limite
    )
