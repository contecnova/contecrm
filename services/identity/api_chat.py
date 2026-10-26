"""API del chat interno (CRM-06.02.02).

**La entrega en vivo va por cursor contra la base, no por una cola en memoria.**
El gateway tiene una cola en proceso para su empuje de eventos y aquí no sirve:
con dos réplicas de `identity`, un mensaje escrito en la primera nunca llegaría
a quien escucha en la segunda, y el fallo aparecería solo al escalar —con dos
personas hablando y una que no recibe nada—. Leer por cursor cuesta una consulta
cada pocos segundos y funciona con las réplicas que haga falta, sin bus y sin
estado compartido.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from uuid import UUID

from crmcore.datos.guard_borrados import con_borrados
from crmcore.errors import NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.identity import chat

router_chat = APIRouter(prefix="/chat", tags=["chat interno"])


# ── Contratos ─────────────────────────────────────────────────────────────


class CrearConversacion(BaseModel):
    """Una conversación nueva: canal, grupo o directo."""

    tipo: str = Field("canal", description=" | ".join(chat.TIPOS))
    clave: str = Field("", max_length=80, description="Solo en canales: `#ventas`")
    nombre: str = Field("", max_length=200)
    proposito: str = Field("", max_length=500, description="Para qué es esta conversación")
    privada: bool = False
    objeto_tipo: str | None = Field(
        None,
        description=(
            "Registro del que cuelga: `oportunidad`, `caso`… Es lo que hace que "
            "la conversación se abra desde su ficha, con el contexto al lado"
        ),
    )
    objeto_id: UUID | None = None
    miembros: list[UUID] = Field(default_factory=list)


class EnviarMensaje(BaseModel):
    cuerpo: str = Field("", max_length=8000)
    responde_a_id: UUID | None = Field(None, description="Para responder en hilo")
    menciones: list[UUID] = Field(default_factory=list)
    adjuntos: list[dict[str, Any]] = Field(default_factory=list)


class EditarMensaje(BaseModel):
    cuerpo: str = Field(..., min_length=1, max_length=8000)


class Reaccion(BaseModel):
    emoji: str = Field(..., description=" ".join(chat.REACCIONES))


class NuevoMiembro(BaseModel):
    usuario_id: UUID


class EstadoPresencia(BaseModel):
    estado: str = Field("disponible", description=" | ".join(chat.PRESENCIAS))
    mensaje: str = Field(
        "",
        max_length=140,
        description="«En un cliente hasta las 5»: responde a si esperar o llamar",
    )


# ── Conversaciones ────────────────────────────────────────────────────────


def _conversacion_out(fila: chat.ConversacionChat, sin_leer: int = 0) -> dict[str, Any]:
    return {
        "id": str(fila.id),
        "tipo": fila.tipo,
        "clave": fila.clave,
        "nombre": fila.nombre,
        "proposito": fila.proposito,
        "privada": fila.privada,
        "objeto_tipo": fila.objeto_tipo,
        "objeto_id": str(fila.objeto_id) if fila.objeto_id else None,
        "ultimo_mensaje_at": (
            fila.ultimo_mensaje_at.isoformat() if fila.ultimo_mensaje_at else None
        ),
        "sin_leer": sin_leer,
    }


@router_chat.get(
    "/conversaciones",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Mis conversaciones",
    description=(
        "Solo las mías. Un listado de todas las conversaciones del tenant "
        "enseñaría los nombres de los canales privados, y el nombre de un canal "
        "—«due-diligence», «salida-de-javier»— ya es información."
    ),
)
def listar_conversaciones(db: DbDep, principal: AutenticadoDep) -> Any:
    pendientes = chat.sin_leer(db, tenant_id=principal.tenant_id, usuario_id=principal.id)
    mias = (
        db.execute(
            select(chat.ConversacionChat)
            .join(
                chat.MiembroConversacion,
                chat.MiembroConversacion.conversacion_id == chat.ConversacionChat.id,
            )
            .where(chat.MiembroConversacion.usuario_id == principal.id)
            .order_by(chat.ConversacionChat.ultimo_mensaje_at.desc().nullslast())
        )
        .scalars()
        .all()
    )
    return [_conversacion_out(c, pendientes.get(str(c.id), 0)) for c in mias]


@router_chat.get(
    "/sin-leer",
    response_model=dict,
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Cuántos mensajes tengo sin leer",
    description=(
        "Para el aviso de la barra superior, que se pide a menudo y desde "
        "todas las pantallas. Aparte del listado de conversaciones a propósito: "
        "pintar un número no puede costar traerse los nombres de todos los "
        "canales privados en los que está la persona."
    ),
)
def cuantos_sin_leer(db: DbDep, principal: AutenticadoDep) -> Any:
    pendientes = chat.sin_leer(db, tenant_id=principal.tenant_id, usuario_id=principal.id)
    return {
        "mensajes": sum(pendientes.values()),
        "conversaciones": len([c for c, n in pendientes.items() if n > 0]),
    }


@router_chat.post(
    "/conversaciones",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Abrir una conversación",
    description=(
        "Un directo con alguien con quien ya se habló **devuelve el que hay**: "
        "abrir uno nuevo al lado del que tiene el histórico es cómo se acaban "
        "teniendo tres conversaciones con la misma persona."
    ),
)
def crear_conversacion(datos: CrearConversacion, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = chat.crear_conversacion(
        uow.db,
        tenant_id=principal.tenant_id,
        creada_por=principal.id,
        tipo=datos.tipo,
        clave=datos.clave,
        nombre=datos.nombre,
        proposito=datos.proposito,
        privada=datos.privada,
        objeto_tipo=datos.objeto_tipo,
        objeto_id=datos.objeto_id,
        miembros=datos.miembros,
    )
    return _conversacion_out(fila)


@router_chat.get(
    "/conversaciones/de/{objeto_tipo}/{objeto_id}",
    response_model=dict,
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="La conversación de este registro, abriéndola si no existe",
    description=(
        "Es lo que distingue este chat de uno cualquiera: se habla de ESTA "
        "oportunidad desde su ficha, sin pegar enlaces y sin cambiar de "
        "aplicación, que es justo donde se pierde el contexto."
    ),
)
def conversacion_del_registro(
    objeto_tipo: str, objeto_id: UUID, uow: UowDep, principal: AutenticadoDep
) -> Any:
    fila = chat.crear_conversacion(
        uow.db,
        tenant_id=principal.tenant_id,
        creada_por=principal.id,
        tipo="grupo",
        nombre=f"{objeto_tipo} · conversación",
        objeto_tipo=objeto_tipo,
        objeto_id=objeto_id,
    )
    # Quien abre la conversación de un registro entra en ella: si no, la abriría
    # y no podría leerla, que es el fallo más tonto posible.
    chat.añadir_miembro(
        uow.db,
        conversacion_id=fila.id,
        usuario_id=principal.id,
        tenant_id=principal.tenant_id,
    )
    return _conversacion_out(fila)


@router_chat.get(
    "/conversaciones/{conversacion_id}",
    response_model=dict,
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Ver una conversación",
)
def ver_conversacion(conversacion_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    chat.exigir_miembro(db, conversacion_id, principal.id)
    fila = chat.conversacion(db, conversacion_id)
    pendientes = chat.sin_leer(db, tenant_id=principal.tenant_id, usuario_id=principal.id)
    return {
        **_conversacion_out(fila, pendientes.get(str(fila.id), 0)),
        "miembros": [
            {"usuario_id": str(m.usuario_id), "rol": m.rol, "silenciada": m.silenciada}
            for m in db.execute(
                select(chat.MiembroConversacion).where(
                    chat.MiembroConversacion.conversacion_id == conversacion_id
                )
            ).scalars()
        ],
    }


@router_chat.post(
    "/conversaciones/{conversacion_id}/miembros",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Meter a alguien en la conversación",
)
def añadir_miembro(
    conversacion_id: UUID, datos: NuevoMiembro, uow: UowDep, principal: AutenticadoDep
) -> Any:
    chat.exigir_miembro(uow.db, conversacion_id, principal.id)
    miembro = chat.añadir_miembro(
        uow.db,
        conversacion_id=conversacion_id,
        usuario_id=datos.usuario_id,
        tenant_id=principal.tenant_id,
    )
    return {"usuario_id": str(miembro.usuario_id), "rol": miembro.rol}


@router_chat.post(
    "/conversaciones/{conversacion_id}/leido",
    response_model=dict,
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Marcar hasta aquí como leído",
)
def marcar_leido(conversacion_id: UUID, uow: UowDep, principal: AutenticadoDep) -> Any:
    hasta = chat.marcar_leido(uow.db, conversacion_id=conversacion_id, usuario_id=principal.id)
    return {"leido_hasta": hasta.isoformat()}


# ── Mensajes ──────────────────────────────────────────────────────────────


def _mensaje_out(db: Any, fila: chat.MensajeChat) -> dict[str, Any]:
    reacciones: dict[str, list[str]] = {}
    for r in db.execute(
        select(chat.ReaccionMensaje).where(chat.ReaccionMensaje.mensaje_id == fila.id)
    ).scalars():
        reacciones.setdefault(r.emoji, []).append(str(r.usuario_id))
    # Un mensaje borrado **sigue en el hilo**, sin cuerpo y sin adjuntos
    # (CRM-06.02.02.09). Que se esfume deja las respuestas colgando de nada y
    # quien lee la conversacion una semana despues no entiende el hilo ni sabe
    # que falta algo. Lo que se quita es lo que se queria quitar.
    borrado = fila.deleted_at is not None
    return {
        "id": str(fila.id),
        "conversacion_id": str(fila.conversacion_id),
        "autor_id": str(fila.autor_id),
        "cuerpo": "" if borrado else fila.cuerpo,
        "borrado": borrado,
        "borrado_at": fila.deleted_at.isoformat() if fila.deleted_at else None,
        "responde_a_id": str(fila.responde_a_id) if fila.responde_a_id else None,
        "menciones": fila.menciones,
        "adjuntos": [] if borrado else fila.adjuntos,
        "editado_at": fila.editado_at.isoformat() if fila.editado_at else None,
        # Cuántas veces se corrigió, no el texto anterior: el histórico está
        # guardado y se enseña a quien abre la edición, no a todo el mundo en
        # cada mensaje.
        "ediciones": len(fila.versiones or []),
        "reacciones": reacciones,
        "created_at": fila.created_at.isoformat(),
    }


@router_chat.get(
    "/conversaciones/{conversacion_id}/mensajes",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Los mensajes de una conversación",
    description=(
        "`desde` devuelve solo lo posterior a esa marca de tiempo, que es como "
        "el cliente se pone al día tras una desconexión sin recargarlo todo."
    ),
)
def listar_mensajes(
    conversacion_id: UUID,
    db: DbDep,
    principal: AutenticadoDep,
    desde: datetime | None = Query(None),
    limite: int = Query(100, ge=1, le=500),
) -> Any:
    chat.exigir_miembro(db, conversacion_id, principal.id)
    consulta = select(chat.MensajeChat).where(chat.MensajeChat.conversacion_id == conversacion_id)
    if desde is not None:
        consulta = consulta.where(chat.MensajeChat.created_at > desde)
    # **Mirando la papelera a propósito** (CRM-06.02.02.09). El guard de
    # borrados esconde por construcción lo que tiene `deleted_at`, y aquí hace
    # falta lo contrario: un mensaje borrado deja su hueco en el hilo, sin
    # cuerpo. Si desapareciera, su respuesta se quedaría sin padre y el front la
    # subiría al nivel de arriba en silencio — una conversación que se lee mal y
    # no dice que falta nada.
    #
    # El cuerpo y los adjuntos los vacía `_mensaje_out`, así que mirar dentro no
    # enseña lo que se quiso quitar.
    with con_borrados(db) as sesion:
        filas = (
            sesion.execute(consulta.order_by(chat.MensajeChat.created_at).limit(limite))
            .scalars()
            .all()
        )
    return [_mensaje_out(db, f) for f in filas]


@router_chat.post(
    "/conversaciones/{conversacion_id}/mensajes",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Escribir en una conversación",
)
def enviar_mensaje(
    conversacion_id: UUID, datos: EnviarMensaje, uow: UowDep, principal: AutenticadoDep
) -> Any:
    fila = chat.enviar(
        uow.db,
        tenant_id=principal.tenant_id,
        conversacion_id=conversacion_id,
        autor_id=principal.id,
        cuerpo=datos.cuerpo,
        responde_a_id=datos.responde_a_id,
        menciones=datos.menciones,
        adjuntos=datos.adjuntos,
    )
    return _mensaje_out(uow.db, fila)


@router_chat.patch(
    "/mensajes/{mensaje_id}",
    response_model=dict,
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Corregir un mensaje",
    description=(
        "Guarda lo que decía antes. En una conversación donde se decide algo, "
        "saber qué decía es justo lo que hace falta cuando alguien lo discute."
    ),
)
def editar_mensaje(
    mensaje_id: UUID, datos: EditarMensaje, uow: UowDep, principal: AutenticadoDep
) -> Any:
    fila = chat.editar(uow.db, mensaje_id=mensaje_id, autor_id=principal.id, cuerpo=datos.cuerpo)
    return _mensaje_out(uow.db, fila)


@router_chat.delete(
    "/mensajes/{mensaje_id}",
    response_model=dict,
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Mandar un mensaje a la papelera",
    description=(
        "Lo borra quien lo escribió **o quien administra la conversación**: el "
        "caso que justifica esto es que alguien pegue en un canal algo que no "
        "debía estar ahí, y entonces no se puede esperar a que el autor se "
        "conecte.\n\n"
        "No desaparece del hilo: queda la marca y se van el cuerpo y los "
        "adjuntos. Un mensaje que se esfuma deja las respuestas colgando de "
        "nada.\n\n"
        "Y es recuperable mientras la retención no lo haya purgado, que es la "
        "diferencia entre una papelera y un borrado."
    ),
)
def borrar_mensaje(mensaje_id: UUID, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = chat.borrar(uow.db, mensaje_id=mensaje_id, por=principal.id)
    return _mensaje_out(uow.db, fila)


@router_chat.post(
    "/mensajes/{mensaje_id}/recuperar",
    response_model=dict,
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Sacarlo de la papelera",
    description=(
        "Mientras la retención no lo haya purgado. Un borrado por error se "
        "deshace; uno a propósito acaba siendo definitivo solo cuando pasa el "
        "plazo que fijó la empresa."
    ),
)
def recuperar_mensaje(mensaje_id: UUID, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = chat.recuperar(uow.db, mensaje_id=mensaje_id, por=principal.id)
    return _mensaje_out(uow.db, fila)


@router_chat.get(
    "/mensajes/{mensaje_id}/versiones",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Qué decía antes este mensaje",
)
def versiones(mensaje_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    # Se busca también en la papelera para que la comprobación de abajo esté
    # VIVA: dependiendo del guard, sería código muerto hoy y una fuga el día que
    # alguien abriera esta ruta a lo borrado.
    with con_borrados(db) as sesion:
        fila = sesion.get(chat.MensajeChat, mensaje_id)
    if fila is None:
        raise NoEncontrado("Ese mensaje no existe", error_code="chat.mensaje_no_existe")
    chat.exigir_miembro(db, fila.conversacion_id, principal.id)
    if fila.deleted_at is not None:
        # Si no, borrar un mensaje lo quitaria de la conversacion y dejaria su
        # texto anterior a un clic de distancia: la papelera no serviria de nada
        # justo en el caso que la justifica, que es haber pegado algo que no
        # debia estar ahi.
        return []
    return list(fila.versiones or [])


@router_chat.post(
    "/mensajes/{mensaje_id}/reacciones",
    response_model=dict,
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Reaccionar, o quitar la reacción",
    description="Es un interruptor: pulsar dos veces el mismo emoji lo quita.",
)
def reaccionar(mensaje_id: UUID, datos: Reaccion, uow: UowDep, principal: AutenticadoDep) -> Any:
    puesta = chat.reaccionar(
        uow.db,
        tenant_id=principal.tenant_id,
        mensaje_id=mensaje_id,
        usuario_id=principal.id,
        emoji=datos.emoji,
    )
    return {"emoji": datos.emoji, "puesta": puesta}


@router_chat.get(
    "/buscar",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Buscar en mis conversaciones",  # CRM-06.02.02.08
    description=(
        "Solo en las mías. Buscar en todas encontraría texto de canales en los "
        "que no se está, que es una fuga por la puerta de atrás."
    ),
)
def buscar(
    db: DbDep,
    principal: AutenticadoDep,
    texto: str = Query(..., min_length=2),
    limite: int = Query(30, ge=1, le=100),
) -> Any:
    mias = (
        db.execute(
            select(chat.MiembroConversacion.conversacion_id).where(
                chat.MiembroConversacion.usuario_id == principal.id
            )
        )
        .scalars()
        .all()
    )
    if not mias:
        return []
    filas = (
        db.execute(
            select(chat.MensajeChat)
            .where(
                chat.MensajeChat.conversacion_id.in_(mias),
                chat.MensajeChat.cuerpo.ilike(f"%{texto}%"),
                # Lo borrado no se busca: encontrarlo por su texto devolveria el
                # cuerpo que se queria quitar, por la puerta de atras.
                chat.MensajeChat.deleted_at.is_(None),
            )
            .order_by(chat.MensajeChat.created_at.desc())
            .limit(limite)
        )
        .scalars()
        .all()
    )
    return [_mensaje_out(db, f) for f in filas]


# ── Presencia ─────────────────────────────────────────────────────────────


@router_chat.get(
    "/presencia",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Quién está y desde cuándo no se le ve",
)
def listar_presencia(db: DbDep, principal: AutenticadoDep) -> Any:
    filas = (
        db.execute(select(chat.Presencia).where(chat.Presencia.tenant_id == principal.tenant_id))
        .scalars()
        .all()
    )
    return [
        {
            "usuario_id": str(f.usuario_id),
            "estado": f.estado,
            "mensaje": f.mensaje,
            "visto_at": f.visto_at.isoformat() if f.visto_at else None,
        }
        for f in filas
    ]


@router_chat.put(
    "/presencia",
    response_model=dict,
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Decir si estoy y hasta cuándo",
)
def fijar_presencia(datos: EstadoPresencia, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = chat.fijar_presencia(
        uow.db,
        tenant_id=principal.tenant_id,
        usuario_id=principal.id,
        estado=datos.estado,
        mensaje=datos.mensaje,
    )
    return {"estado": fila.estado, "mensaje": fila.mensaje}


# ── Entrega en vivo ───────────────────────────────────────────────────────


@router_chat.get(
    "/eventos",
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Lo que va llegando, en vivo",  # CRM-06.02.02.07
    description=(
        "SSE (`text/event-stream`). Lee **por cursor contra la base** y no de "
        "una cola en memoria: con dos réplicas del servicio, un mensaje escrito "
        "en una nunca llegaría a quien escucha en la otra, y ese fallo solo "
        "aparece al escalar —con dos personas hablando y una que no recibe—.\n\n"
        "Lleva latido: un flujo sin datos durante minutos lo cierra cualquier "
        "intermediario, y el cliente cree que el servidor se ha caído."
    ),
    # EL CONTRATO TIENE QUE DECIR QUE ESTO ES UN FLUJO, y hasta ahora solo lo
    # decía la descripción en prosa. El contrato publicado anunciaba una
    # respuesta JSON corriente, así que cualquiera que lo lea —un cliente
    # generado, un catálogo de API, una herramienta que recorra rutas— la pide
    # como una más y se queda esperando para siempre a que termine algo que no
    # termina por diseño. Ha pasado dos veces aquí: colgó el registro de
    # fuentes, que lo tapó con un plazo corto, y colgó diez minutos el barrido
    # de listados. Las dos veces el síntoma fue el mismo y no decía nada: cero
    # por ciento de CPU, sin error y sin avanzar.
    responses={200: {"content": {"text/event-stream": {}}, "description": "Flujo de eventos"}},
)
async def eventos(
    db: DbDep,
    principal: AutenticadoDep,
    desde: datetime | None = Query(None),
    espera_s: float | None = Query(
        None,
        ge=0.5,
        le=30.0,
        description="Cada cuánto se mira si hay algo nuevo. Por defecto, lo configurado",
    ),
) -> StreamingResponse:
    from crmcore.config import get_settings

    s = get_settings()
    espera = espera_s if espera_s is not None else s.chat_sse_espera_s
    latido_cada = s.chat_sse_latido_s
    usuario_id = principal.id
    corte = desde or datetime.now(timezone.utc)

    async def flujo() -> AsyncIterator[str]:
        nonlocal corte
        # SALUDO INMEDIATO, antes de la primera consulta.
        #
        # Para el cliente, un flujo no existe hasta su primer byte: uvicorn no
        # manda las cabeceras hasta el primer trozo del cuerpo. Este flujo
        # callaba hasta dieciocho segundos si no había mensajes —que es el caso
        # normal al abrir el chat—, así que el navegador veía una petición que
        # no contestaba, el `EventSource` no llegaba a abrirse nunca y el
        # gateway daba la conexión por muerta. Un comentario SSE (`:`) no es un
        # evento para ningún cliente, pero abre la respuesta.
        yield f"retry: {s.chat_sse_reintento_ms}\n\n"
        yield ": abierto\n\n"
        ultimo_latido = asyncio.get_running_loop().time()
        while True:
            mias = (
                db.execute(
                    select(chat.MiembroConversacion.conversacion_id).where(
                        chat.MiembroConversacion.usuario_id == usuario_id
                    )
                )
                .scalars()
                .all()
            )
            nuevos = (
                db.execute(
                    select(chat.MensajeChat)
                    .where(
                        # Sin conversaciones no hay mensajes que traer, y se
                        # dice con `IN ()` vacío y no con un apaño. Aquí ponía
                        # `mias or [chat.MensajeChat.id]` —una COLUMNA dentro de
                        # la lista— que SQLAlchemy rechaza: «IN expression list,
                        # SELECT construct, or bound parameter object expected».
                        # O sea que el flujo del chat daba 500 a cualquiera que
                        # todavía no estuviera en ninguna conversación, que es
                        # justo el estado de quien acaba de entrar.
                        chat.MensajeChat.conversacion_id.in_(mias),
                        chat.MensajeChat.created_at > corte,
                        chat.MensajeChat.autor_id != usuario_id,
                    )
                    .order_by(chat.MensajeChat.created_at)
                    .limit(50)
                )
                .scalars()
                .all()
            )
            for mensaje in nuevos:
                corte = max(corte, mensaje.created_at)
                yield (
                    "event: mensaje\n"
                    f"data: {json.dumps(_mensaje_out(db, mensaje), ensure_ascii=False)}\n\n"
                )
            ahora = asyncio.get_running_loop().time()
            if nuevos:
                ultimo_latido = ahora
            elif ahora - ultimo_latido >= latido_cada:
                yield ": latido\n\n"
                ultimo_latido = ahora
            # La sesión se cierra entre vueltas: mantenerla abierta reservaría
            # una conexión de Postgres por persona conectada, y con cincuenta
            # personas con el chat abierto eso agota el pool sin que nadie esté
            # haciendo nada.
            db.rollback()
            await asyncio.sleep(espera)

    return StreamingResponse(
        flujo(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


ROUTERS_CHAT = [router_chat]
