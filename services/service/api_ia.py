"""La IA desde la ficha del caso y de la conversación.

`intelligence` resumía, sugería respuestas, leía la intención y traducía, pero
había que darle el texto: no se podía ofrecer en ninguna ficha. Aquí el servicio
dueño del caso y de la conversación reúne lo que tiene y se lo pide, con la
identidad de quien pulsa (`crmcore.ia_ficha`).

Todo lo que vuelve es **propuesta**: nada se escribe en el caso ni se manda al
cliente desde aquí.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from crmcore import ia_ficha
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, exige_permiso
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

router_ia_casos = APIRouter(prefix="/casos", tags=["casos"])
router_ia_conversaciones = APIRouter(prefix="/conversaciones", tags=["omnicanal"])


def _fragmento(texto: str, *, fuente: str, id_: Any, permiso: str) -> dict[str, Any]:
    # Con su permiso declarado: sin él, el guardarraíl lo descarta.
    return {
        "texto": texto,
        "fuente": fuente,
        "id": str(id_),
        "permiso": permiso,
        "sensibilidad": "interno",
    }


def _caso(caso_id: UUID, principal: Any) -> dict[str, Any]:
    """El caso como lo ve quien pide, con la máscara de campos de su rol."""
    return dict(ia_ficha.leer(f"/api/v1/casos/{caso_id}", principal))


@router_ia_casos.post(
    "/{caso_id}/resumen-ia",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Resumir este caso con IA: qué pide, qué se ha hecho y qué queda",
    description=(
        "Con el caso tal como tú lo ves —descripción, clasificación e historial—. "
        "Lo pendiente sale en una lista aparte. Queda **propuesto**: no se escribe "
        "en el caso."
    ),
)
def resumen_ia_de_caso(caso_id: UUID, principal: AutenticadoDep) -> Any:
    caso = _caso(caso_id, principal)
    contexto = {
        k: caso.get(k)
        for k in ("asunto", "descripcion", "estado", "prioridad", "clasificacion", "historial")
    }
    return ia_ficha.pedir(
        "/api/v1/ia/generar",
        {
            "plantilla": "resumen_caso",
            "datos": {"asunto": caso.get("asunto") or ""},
            "contexto": [
                _fragmento(
                    json.dumps(contexto, ensure_ascii=False, default=str),
                    fuente="caso",
                    id_=caso_id,
                    permiso="case:read",
                )
            ],
            "objeto": "caso",
            "objeto_id": str(caso_id),
        },
        principal,
    )


@router_ia_casos.post(
    "/{caso_id}/respuesta-sugerida",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Sugerir una respuesta para este caso, con los artículos en que se apoya",
    description=(
        "Busca en la base de conocimiento **interna** lo que se parece al caso y "
        "pide una respuesta que cite esos artículos. Si no hay ninguno con el que "
        "contestar, no se inventa: lo dice. La respuesta no se manda sola."
    ),
)
def respuesta_sugerida(caso_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    from services.service import conocimiento

    caso = _caso(caso_id, principal)
    pregunta = "\n".join(str(caso.get(k) or "") for k in ("asunto", "descripcion")).strip()
    if not pregunta:
        raise ErrorValidacion(
            "El caso no tiene asunto ni descripción: no hay qué contestar.",
            error_code="ia.caso_sin_texto",
        )
    from crmcore.config import get_settings

    articulos = conocimiento.buscar(
        db,
        principal.tenant_id,
        texto=str(caso.get("asunto") or ""),
        audiencia="interno",
        limite=get_settings().ia_articulos_por_sugerencia,
    )
    fragmentos = [
        _fragmento(
            f"{a.get('titulo') or ''}\n\n{a.get('resumen') or ''}",
            fuente=f"articulo:{a.get('clave') or a.get('articulo_id')}",
            id_=a.get("articulo_id"),
            permiso="case:read",
        )
        for a in articulos
    ]
    return ia_ficha.pedir(
        "/api/v1/ia/asistencia/respuesta-soporte",
        {"caso_id": str(caso_id), "pregunta": pregunta, "fragmentos": fragmentos},
        principal,
    )


# ── Conversaciones ────────────────────────────────────────────────────────


def _mensajes(db: Any, conversacion_id: UUID) -> tuple[list[dict[str, Any]], int]:
    """Los últimos mensajes de la conversación y cuántos tiene en total.

    Se leen de la base y no por una ruta porque no hay ruta de «una
    conversación»: sale del historial del contacto. La sesión es la de quien
    pide, así que el aislamiento por tenant está; y el guardarraíl de
    `intelligence` vuelve a mirar el permiso con su identidad.
    """
    from crmcore.config import get_settings
    from sqlalchemy import func

    from services.service.omnicanal import SALIENTE, Conversacion, Mensaje

    conversacion = db.get(Conversacion, conversacion_id)
    if conversacion is None or conversacion.deleted_at is not None:
        raise NoEncontrado("Esa conversación no existe", error_code="conversacion.no_encontrada")
    total = int(
        db.execute(
            select(func.count())
            .select_from(Mensaje)
            .where(Mensaje.conversacion_id == conversacion_id)
        ).scalar()
        or 0
    )
    filas = (
        db.execute(
            select(Mensaje)
            .where(Mensaje.conversacion_id == conversacion_id)
            # Con el identificador detrás: dos mensajes de la misma transacción
            # comparten `created_at` —es la hora de la transacción— y sin él su
            # orden queda al azar. Es UUID7, así que crece con el tiempo.
            .order_by(Mensaje.created_at.desc(), Mensaje.id.desc())
            .limit(get_settings().ia_mensajes_para_resumen)
        )
        .scalars()
        .all()
    )
    mensajes = [
        {
            "quien": "agente" if m.direccion == SALIENTE else "cliente",
            "canal": m.canal,
            "interno": m.interno,
            "texto": m.cuerpo,
            "cuando": m.created_at.isoformat() if m.created_at else None,
        }
        for m in reversed(filas)
    ]
    if not mensajes:
        raise ErrorValidacion(
            "La conversación no tiene mensajes: no hay nada que leer.",
            error_code="ia.conversacion_vacia",
        )
    return mensajes, total


class MomentoIn(BaseModel):
    momento: str = Field("cierre", description="«cierre» o «transferencia»")


@router_ia_conversaciones.post(
    "/{conversacion_id}/resumen-ia",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Resumir esta conversación al cerrarla o al pasarla a otro",
    description=(
        "Con sus últimos mensajes, y diciendo de cuántos salió y cuántos había: un "
        "resumen hecho con el final de una conversación larga no es el de toda. Lo "
        "pendiente va aparte, que es lo primero que lee quien la recoge."
    ),
)
def resumen_ia_de_conversacion(
    conversacion_id: UUID, datos: MomentoIn, db: DbDep, principal: AutenticadoDep
) -> Any:
    mensajes, total = _mensajes(db, conversacion_id)
    return ia_ficha.pedir(
        "/api/v1/ia/conversacion/resumen",
        {
            "conversacion_id": str(conversacion_id),
            "mensajes": mensajes,
            "momento": datos.momento,
            "mensajes_totales": total,
        },
        principal,
    )


@router_ia_conversaciones.post(
    "/{conversacion_id}/intencion",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Qué quiere el cliente y cómo está, en el último mensaje",
    description=(
        "Intención y sentimiento del último mensaje del cliente, con la confianza: "
        "por debajo del umbral se dice que no se sabe, y si pide hablar con una "
        "persona o está muy molesto, se propone escalar."
    ),
)
def intencion_de_conversacion(conversacion_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    mensajes, _ = _mensajes(db, conversacion_id)
    del_cliente = [m for m in mensajes if m["quien"] == "cliente" and not m["interno"]]
    if not del_cliente:
        raise ErrorValidacion(
            "No hay ningún mensaje del cliente que leer.", error_code="ia.sin_mensaje_cliente"
        )
    return ia_ficha.pedir(
        "/api/v1/ia/conversacion/senal",
        {"conversacion_id": str(conversacion_id), "texto": del_cliente[-1]["texto"]},
        principal,
    )


class TraducirIn(BaseModel):
    idioma: str = Field(..., min_length=2, max_length=10, description="A qué idioma: es, en, fr…")


@router_ia_conversaciones.post(
    "/{conversacion_id}/traducir",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Traducir el último mensaje del cliente",
    description=(
        "Para el agente que no habla el idioma del cliente. La traducción es una "
        "propuesta: el original sigue siendo lo que el cliente escribió."
    ),
)
def traducir_conversacion(
    conversacion_id: UUID, datos: TraducirIn, db: DbDep, principal: AutenticadoDep
) -> Any:
    mensajes, _ = _mensajes(db, conversacion_id)
    del_cliente = [m for m in mensajes if m["quien"] == "cliente" and not m["interno"]]
    if not del_cliente:
        raise ErrorValidacion(
            "No hay ningún mensaje del cliente que traducir.", error_code="ia.sin_mensaje_cliente"
        )
    return ia_ficha.pedir(
        "/api/v1/ia/generar",
        {
            "plantilla": "traducir",
            "datos": {"idioma_destino": datos.idioma, "texto": del_cliente[-1]["texto"]},
            "objeto": "conversacion",
            "objeto_id": str(conversacion_id),
            "idioma": datos.idioma,
        },
        principal,
    )


ROUTERS_IA = [router_ia_casos, router_ia_conversaciones]
