"""El índice de conocimiento: vectores en Postgres (CRM-04.03.01.04, 05.02.02.03).

La búsqueda «semántica» de casos y la respuesta con citación existían como
filtros sobre resultados que «llegan ya buscados», y nadie buscaba: no había
índice. Aquí está, con pgvector —decidido el 05-11-2026—, por una razón que
pesa más que las demás: **los vectores van en una tabla con `tenant_id`, así
que el RLS los aísla igual que al resto**. Un almacén aparte habría que aislarlo
a mano, y ahí es donde se cuela un cliente en las sugerencias de otro.

Lo que se indexa:

- **artículos** de la base de conocimiento, al publicarse (`knowledge.published`);
- **casos cerrados**, con su resolución (`case.closed`): son la otra mitad de
  «esto ya pasó y se arregló así».

El texto se lee del servicio de soporte por su ruta, con una identidad interna
del tenant; el evento sólo trae el identificador. Los vectores los calcula el
proveedor declarado para el uso `embeddings` del enrutador, con las mismas
garantías de región y opt-out que cualquier otra llamada.

Y no se vuelve a pagar por lo mismo: cada fragmento guarda la huella de su
texto y el modelo con que se calculó; si no ha cambiado ninguno, no se recalcula.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

FUENTES = ("articulo", "caso_resuelto")
# El permiso que hace falta para ver lo que se recupera de cada fuente. Se
# comprueba contra quien pregunta antes de mandárselo al modelo.
PERMISO_DE = {"articulo": "knowledge:read", "caso_resuelto": "case:read"}

_incrustador: Callable[..., list[list[float]]] | None = None


def registrar_incrustador(fn: Callable[..., list[list[float]]]) -> None:
    global _incrustador
    _incrustador = fn


class FragmentoIndice(Base, TimestampMixin):
    """Un texto indexado con su vector."""

    __tablename__ = "indice_conocimiento"
    __table_args__ = (UniqueConstraint("tenant_id", "fuente", "referencia"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    fuente: Mapped[str] = mapped_column(String(30), nullable=False)
    referencia: Mapped[str] = mapped_column(String(80), nullable=False)
    titulo: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    texto: Mapped[str] = mapped_column(Text, nullable=False, info={"anonimizar_en_copias": True})
    # Si el texto se recortó al indexarlo: lo que no entró no se encuentra.
    recortado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    permiso: Mapped[str] = mapped_column(String(80), nullable=False)
    huella: Mapped[str] = mapped_column(String(64), nullable=False)
    modelo: Mapped[str] = mapped_column(String(120), nullable=False)
    dimensiones: Mapped[int] = mapped_column(Integer, nullable=False)
    # Sin dimensión fija en la columna: la pone el modelo, y cambiar de modelo
    # no exige migrar. Se compara sólo con vectores del mismo modelo.
    vector: Mapped[list[float]] = mapped_column(Vector(), nullable=False)
    indexado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


def _modelo(db: Session, tenant_id: UUID) -> dict[str, Any]:
    from services.intelligence import enrutador

    return dict(enrutador.exigir_disponible(db, tenant_id, uso="embeddings"))


def _vectores(db: Session, tenant_id: UUID, textos: list[str]) -> tuple[list[list[float]], str]:
    from services.intelligence.ajustes import ajustes

    if _incrustador is None:
        raise Conflicto(
            "No hay ningún proveedor conectado que calcule vectores: el índice no se "
            "puede llenar ni consultar.",
            error_code="indice.sin_incrustador",
        )
    elegido = _modelo(db, tenant_id)
    vectores = _incrustador(
        proveedor=elegido["elegido"],
        modelo=elegido.get("modelo", ""),
        textos=textos,
        dimensiones=ajustes().ia_dimensiones_vector,
    )
    return vectores, f"{elegido['elegido']}/{elegido.get('modelo', '')}"


def indexar(
    uow: UnidadDeTrabajo,
    *,
    fuente: str,
    referencia: str,
    titulo: str,
    texto: str,
) -> dict[str, Any]:
    """Indexa o actualiza un texto. Si nada ha cambiado, no se paga otra vez."""
    from services.intelligence.ajustes import ajustes

    if fuente not in FUENTES:
        raise Conflicto(f"Fuente «{fuente}» desconocida", error_code="indice.fuente")
    tope = ajustes().ia_caracteres_por_fragmento
    completo = f"{titulo}\n\n{texto}".strip()
    recortado = len(completo) > tope
    completo = completo[:tope]
    huella = hashlib.sha256(completo.encode()).hexdigest()
    fila = uow.db.execute(
        select(FragmentoIndice).where(
            FragmentoIndice.tenant_id == uow.tenant_id,
            FragmentoIndice.fuente == fuente,
            FragmentoIndice.referencia == referencia,
        )
    ).scalar_one_or_none()
    modelo_actual = _modelo(uow.db, uow.tenant_id)
    nombre_modelo = f"{modelo_actual['elegido']}/{modelo_actual.get('modelo', '')}"
    if fila is not None and fila.huella == huella and fila.modelo == nombre_modelo:
        return {"referencia": referencia, "indexado": False, "porque": "sin cambios"}
    (vector,), modelo = _vectores(uow.db, uow.tenant_id, [completo])
    if fila is None:
        fila = FragmentoIndice(tenant_id=uow.tenant_id, fuente=fuente, referencia=referencia)
        uow.db.add(fila)
    fila.titulo = titulo[:300]
    fila.texto = completo
    fila.recortado = recortado
    fila.permiso = PERMISO_DE[fuente]
    fila.huella = huella
    fila.modelo = modelo
    fila.dimensiones = len(vector)
    fila.vector = vector
    fila.indexado_at = func.now()
    uow.db.flush()
    return {"referencia": referencia, "indexado": True, "recortado": recortado}


def buscar(
    db: Session,
    tenant_id: UUID,
    *,
    texto: str,
    fuentes: tuple[str, ...] = FUENTES,
    tope: int | None = None,
    excluir: str = "",
) -> list[dict[str, Any]]:
    """Lo más parecido a `texto`, con su parecido entre 0 y 1.

    Sólo contra vectores del modelo con el que se calcula la pregunta: comparar
    vectores de dos modelos distintos da números que no significan nada.
    """
    from services.intelligence.ajustes import ajustes

    tope = tope or ajustes().ia_resultados_indice
    (consulta,), modelo = _vectores(db, tenant_id, [texto])
    distancia = FragmentoIndice.vector.cosine_distance(consulta)
    filas = db.execute(
        select(FragmentoIndice, distancia.label("distancia"))
        .where(
            FragmentoIndice.tenant_id == tenant_id,
            FragmentoIndice.modelo == modelo,
            FragmentoIndice.fuente.in_(fuentes),
            FragmentoIndice.referencia != excluir,
        )
        .order_by(distancia)
        .limit(tope)
    ).all()
    return [
        {
            "fuente": f.fuente,
            "referencia": f.referencia,
            "titulo": f.titulo,
            "texto": f.texto,
            "permiso": f.permiso,
            "parecido": round(1 - float(d), 4),
            "resuelto": f.fuente == "caso_resuelto",
            "cita": f.texto[:400],
            "recortado": f.recortado,
        }
        for f, d in filas
    ]


def estado(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Qué hay indexado, por fuente y por modelo."""
    filas = db.execute(
        select(FragmentoIndice.fuente, FragmentoIndice.modelo, func.count())
        .where(FragmentoIndice.tenant_id == tenant_id)
        .group_by(FragmentoIndice.fuente, FragmentoIndice.modelo)
    ).all()
    return {
        "por_fuente": [{"fuente": f, "modelo": m, "fragmentos": n} for f, m, n in filas],
        "total": sum(n for _, _, n in filas),
    }


# ── Lo que llega por el bus ───────────────────────────────────────────────


def _texto_de(fuente: str, referencia: str, tenant_id: UUID) -> tuple[str, str] | None:
    """El título y el texto, leídos del servicio de soporte por su ruta."""
    from crmcore.http.interno import invocar

    if fuente == "articulo":
        r = invocar(
            metodo="GET",
            ruta=f"/api/v1/conocimiento/{referencia}",
            tenant_id=tenant_id,
            principal_id=tenant_id,
            permisos=["knowledge:read"],
        )
        datos = r.get("datos") or {}
        if int(r.get("estado") or 0) != 200 or not isinstance(datos, dict):
            return None
        if datos.get("obsoleto"):
            # Un artículo obsoleto no se sugiere: es la respuesta de antes.
            return None
        return str(datos.get("titulo") or ""), str(datos.get("cuerpo") or "")
    r = invocar(
        metodo="GET",
        ruta=f"/api/v1/casos/{referencia}",
        tenant_id=tenant_id,
        principal_id=tenant_id,
        permisos=["case:read"],
    )
    datos = r.get("datos") or {}
    if int(r.get("estado") or 0) != 200 or not isinstance(datos, dict):
        return None
    cierre = datos.get("cierre") or {}
    resolucion = cierre.get("resolucion") if isinstance(cierre, dict) else cierre
    if not resolucion:
        # Un caso cerrado sin resolución escrita no enseña cómo se arregló nada.
        return None
    return str(datos.get("asunto") or ""), (
        f"{datos.get('descripcion') or ''}\n\nResolución: {resolucion}"
    )


def _al_evento(mensaje: Any, fuente: str, campo: str) -> None:
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto

    datos = dict(getattr(mensaje, "data", None) or {})
    bruto = getattr(mensaje, "tenant_id", None)
    referencia = str(datos.get(campo) or "")
    if not bruto or not referencia:
        return
    tenant_id = UUID(str(bruto))
    with con_contexto(tenant_id=tenant_id, origen="bus"):
        leido = _texto_de(fuente, referencia, tenant_id)
        if leido is None:
            return
        try:
            with unidad_de_trabajo(tenant_id) as uow:
                indexar(uow, fuente=fuente, referencia=referencia, titulo=leido[0], texto=leido[1])
        except Conflicto as exc:
            # Sin proveedor de vectores no se puede indexar; se dice y se sigue.
            # Reindexar después lo recoge.
            logger.warning("indice.no_indexado", referencia=referencia, motivo=exc.error_code)


async def consumir_publicado(mensaje: Any) -> None:
    _al_evento(mensaje, "articulo", "articulo_id")


async def consumir_cerrado(mensaje: Any) -> None:
    _al_evento(mensaje, "caso_resuelto", "caso_id")
