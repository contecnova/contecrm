"""Bandeja de notificaciones y seguimiento de registros (CRM-06.02.01.02).

Vive en `identity` porque lo que guarda es **del usuario**: a qué registros se
suscribe, por qué canales quiere enterarse y qué ha leído ya. Ponerlo en cada
servicio repartiría la bandeja de una persona por cinco esquemas y haría
imposible la pregunta más básica, «¿qué tengo sin leer?».

**Los servicios no escriben aquí. Emiten eventos.** `party` no puede insertar en
el esquema de `identity` —el rol de base de datos no se lo permite, y es
deliberado—, así que la cadena es: el servicio dueño del objeto emite su evento
de dominio, y el consumidor de este módulo lo traduce en notificaciones para
quien siga ese objeto. Eso hace además que notificar no pueda tumbar la
operación que lo provocó: si esto falla, el evento se reintenta.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.datos.seguimiento import (
    CANALES,
    MOTIVOS,
    Notificacion,
    PreferenciaNotificacion,
    Seguimiento,
    bandeja,
    dejar_de_seguir,
    marcar_leidas,
    notificar,
    seguidores,
    seguir,
)
from crmcore.errors import ErrorValidacion
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep
from crmcore.logging import get_logger
from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

logger = get_logger(__name__)

# Qué evento produce qué aviso. **Es una tabla de datos, no una cadena de
# `if`**: añadir un aviso para un evento nuevo es una línea aquí, y la lista
# completa de lo que el sistema notifica se lee de un vistazo — que es justo lo
# que hay que poder auditar cuando alguien pregunta «¿por qué me llegó esto?».
#
# `objeto` dice de qué campo de `data` sale el identificador del registro
# seguido. Sin él no se sabe a quién avisar.
AVISOS: dict[str, dict[str, Any]] = {
    "account.merged": {
        "objeto_tipo": "cuenta",
        "campo_id": "superviviente_id",
        "titulo": "Se han fusionado dos cuentas",
        "prioridad": "alta",
    },
    "contact.consent.changed": {
        "objeto_tipo": "contacto",
        "campo_id": "contacto_id",
        "titulo": "Ha cambiado el consentimiento de un contacto",
        "prioridad": "alta",
    },
    "lead.assigned": {
        "objeto_tipo": "lead",
        "campo_id": "lead_id",
        "titulo": "Te han asignado un lead",
        "prioridad": "alta",
        # El asignado no tiene por qué seguirlo todavía: se le avisa igual y de
        # paso se le suscribe. Es el aviso que más importa de todos y sería
        # absurdo que dependiera de una suscripción que aún no existe.
        "destinatario_campo": "asignado_a",
        "suscribir_destinatario": True,
    },
    "record.commented": {
        # El objeto del comentario lo dice el propio evento, así que este aviso
        # no tiene un `objeto_tipo` fijo como los demás: se lee de `data`.
        "objeto_tipo": None,
        "campo_id": "objeto_id",
        "titulo": "Nuevo comentario",
        "cuerpo_campo": "extracto",
        # A quien mencionan se le avisa y se le suscribe, aunque no siguiera el
        # registro: nombrar a alguien para que se entere y que luego no se
        # entere de la respuesta sería absurdo.
        "destinatarios_campo": "menciones",
        "sumar_a_seguidores": True,
        "suscribir_destinatario": True,
    },
    "opportunity.stage.changed": {
        "objeto_tipo": "oportunidad",
        "campo_id": "oportunidad_id",
        "titulo": "Ha cambiado la etapa de una oportunidad",
    },
    "opportunity.closed": {
        "objeto_tipo": "oportunidad",
        "campo_id": "oportunidad_id",
        "titulo": "Se ha cerrado una oportunidad",
        "prioridad": "alta",
    },
    # Actividades (CRM-01.02.01.02). Los cuatro avisan al asignado, que es quien
    # tiene que hacer algo. El de vencida avisa ADEMÁS a quien la delegó: quien
    # delega sigue siendo responsable, y sin eso la tarea desaparece de su vista
    # en cuanto la pasa.
    "activity.assigned": {
        "objeto_tipo": "actividad",
        "campo_id": "actividad_id",
        "titulo": "Te han asignado una tarea",
        "cuerpo_campo": "asunto",
        "prioridad": "alta",
        "destinatario_campo": "asignada_a",
        "suscribir_destinatario": True,
    },
    "activity.delegated": {
        "objeto_tipo": "actividad",
        "campo_id": "actividad_id",
        "titulo": "Te han delegado una tarea",
        "cuerpo_campo": "asunto",
        "prioridad": "alta",
        "destinatario_campo": "asignada_a",
        "suscribir_destinatario": True,
    },
    "activity.reminder": {
        "objeto_tipo": "actividad",
        "campo_id": "actividad_id",
        "titulo": "Recordatorio",
        "cuerpo_campo": "asunto",
        "prioridad": "alta",
        "destinatario_campo": "asignada_a",
    },
    "activity.overdue": {
        "objeto_tipo": "actividad",
        "campo_id": "actividad_id",
        "titulo": "Tarea fuera de plazo",
        "cuerpo_campo": "asunto",
        "prioridad": "alta",
        "destinatarios_campos": ["asignada_a", "delegada_por"],
    },
    # El aviso que pide una automatización con las acciones `notificar` o
    # `enviar_correo` (CRM-00.03.03.03).
    #
    # **Este consumidor faltaba.** El ejecutor emitía el evento y su comentario
    # decía que «el consumidor de identidad ya sabe traducir esto»; no existía,
    # así que la acción `notificar` de una regla no producía ningún aviso. Se
    # guardaba, se validaba, se simulaba, se ejecutaba sin error y no pasaba
    # nada — el mismo modo de fallo por el que `enviar_correo` se había
    # retirado, solo que en este no se había visto.
    "automatizacion.aviso": {
        "objeto_tipo": None,
        "campo_id": "objeto_id",
        "titulo": "",
        "titulo_campo": "titulo",
        "cuerpo_campo": "cuerpo",
        "destinatarios_campo": "menciones",
        "sumar_a_seguidores": True,
        "canales_campo": "canales",
        # No se suscribe a quien se avisa: una regla puede avisar a un
        # responsable de un registro que no le interesa seguir, y suscribirle
        # por la fuerza le llenaría la bandeja con todo lo que pase después.
    },
}


def _destinatarios(regla: dict[str, Any], datos: dict[str, Any]) -> list[UUID]:
    """Quién recibe el aviso, cuando el evento lo dice explícitamente.

    Los identificadores mal formados se descartan con aviso en vez de tumbar el
    consumidor: un comentario con una mención corrupta no puede impedir que se
    avise a los demás, y el evento se reintentaría en bucle para siempre.
    """
    # Se admiten tres formas de declararlo, y las tres hacen falta: un campo con
    # una lista dentro (las menciones de un comentario), un campo con uno solo
    # (el asignado de una tarea) y VARIOS campos (una tarea vencida avisa al
    # asignado y a quien la delegó, que están en campos distintos).
    campos = regla.get("destinatarios_campos") or [
        regla.get("destinatarios_campo", ""),
        regla.get("destinatario_campo", ""),
    ]
    valores: list[Any] = []
    for campo in campos:
        if not campo:
            continue
        bruto = datos.get(campo)
        if not bruto:
            continue
        valores.extend(bruto if isinstance(bruto, list) else [bruto])
    if not valores:
        return []
    salida: list[UUID] = []
    for valor in valores:
        try:
            salida.append(UUID(str(valor)))
        except (ValueError, AttributeError, TypeError):
            logger.warning("notificacion.destinatario_invalido", valor=str(valor)[:80])
    return list(dict.fromkeys(salida))


def _activos(db: Any, usuarios: list[UUID], tenant_id: UUID) -> list[UUID]:
    """Descarta a quien ya no está, y deja escrito por qué.

    Portado de `contecmind/app/services/annotations.py`, que lo aprendió antes:
    mencionar a alguien de baja creaba un aviso que no iba a leer nadie, y quien
    escribió el comentario se quedaba esperando una respuesta que no iba a
    llegar. Y el motivo del descarte se registra porque «¿por qué no le llegó?»
    es la pregunta que viene detrás, siempre.

    Una sola consulta para todos los mencionados, no una por cada uno: el N+1
    de `db.get(Usuario)` dentro del bucle es el mismo fallo que allí se corrigió
    en una auditoría.
    """
    if not usuarios:
        return []
    from sqlalchemy import select as _select

    from services.identity.modelos import Membresia, Usuario

    filas = (
        db.execute(
            _select(Usuario.id)
            .join(Membresia, Membresia.usuario_id == Usuario.id)
            .where(
                Usuario.id.in_(usuarios),
                Usuario.activo.is_(True),
                Membresia.tenant_id == tenant_id,
                Membresia.activa.is_(True),
            )
        )
        .scalars()
        .all()
    )

    validos = set(filas)
    for descartado in (u for u in usuarios if u not in validos):
        logger.info(
            "notificacion.mencion_descartada",
            motivo="usuario_inactivo_o_sin_membresia",
            usuario=str(descartado),
        )
    # Se conserva el ORDEN de entrada: la lista se enseña, y reordenarla haría
    # que el mismo comentario se viera distinto en cada carga.
    return [u for u in usuarios if u in validos]


async def consumir_evento(mensaje: Any) -> None:
    """Traduce un evento de dominio en notificaciones.

    Un evento sin entrada en `AVISOS` se **ignora en silencio**, y es lo
    correcto: el bus lleva decenas de tipos y solo unos pocos merecen molestar a
    alguien. Registrar un aviso por cada uno que no notifica llenaría el log de
    ruido.
    """
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto

    tipo = getattr(mensaje, "tipo", None) or mensaje.get("tipo")
    regla = AVISOS.get(tipo or "")
    if regla is None:
        return

    datos = getattr(mensaje, "data", None) or mensaje.get("data") or {}
    tenant_bruto = getattr(mensaje, "tenant_id", None) or mensaje.get("tenant_id")
    if not tenant_bruto:
        logger.warning("notificacion.evento_sin_tenant", tipo=tipo)
        return
    tenant_id = UUID(str(tenant_bruto))

    bruto_id = datos.get(regla["campo_id"])
    if not bruto_id:
        logger.warning("notificacion.evento_sin_objeto", tipo=tipo, campo=regla["campo_id"])
        return
    objeto_id = UUID(str(bruto_id))

    # El título puede venir del evento —lo escribe quien configura la regla— o
    # ser fijo. Un aviso sin título no se puede leer, así que si no hay ninguno
    # de los dos se descarta en vez de mandar una línea en blanco.
    titulo = str(datos.get(regla["titulo_campo"], "")) if regla.get("titulo_campo") else ""
    titulo = titulo or regla["titulo"]
    if not titulo:
        logger.warning("notificacion.evento_sin_titulo", tipo=tipo)
        return

    # Quien provocó el cambio no se avisa a sí mismo.
    actor = datos.get("actor_id") or getattr(mensaje, "actor_id", None)
    excluir = [UUID(str(actor))] if actor else []

    # El tipo de objeto puede venir fijo en la regla o en el propio evento (un
    # comentario cuelga de lo que sea).
    objeto_tipo = regla["objeto_tipo"] or str(datos.get("objeto_tipo") or "")
    if not objeto_tipo:
        logger.warning("notificacion.evento_sin_tipo_objeto", tipo=tipo)
        return

    with con_contexto(tenant_id=tenant_id, origen="bus"), unidad_de_trabajo(tenant_id) as uow:
        explicitos: list[UUID] | None = None
        destinatarios = _activos(uow.db, _destinatarios(regla, datos), tenant_id)
        if destinatarios:
            explicitos = destinatarios
            if regla.get("suscribir_destinatario"):
                for quien in destinatarios:
                    seguir(
                        uow.db,
                        tenant_id=tenant_id,
                        usuario_id=quien,
                        objeto_tipo=objeto_tipo,
                        objeto_id=objeto_id,
                        motivo="mencion" if regla.get("sumar_a_seguidores") else "propietario",
                    )
            if regla.get("sumar_a_seguidores"):
                # Los mencionados se AÑADEN a quien ya seguía el registro, no lo
                # sustituyen: un comentario interesa a todo el hilo, y avisar
                # solo a los nombrados dejaría fuera al responsable del caso.
                explicitos = list(
                    dict.fromkeys(
                        destinatarios
                        + seguidores(
                            uow.db,
                            tenant_id=tenant_id,
                            objeto_tipo=objeto_tipo,
                            objeto_id=objeto_id,
                        )
                    )
                )

        notificar(
            uow.db,
            tenant_id=tenant_id,
            tipo=tipo or "",
            titulo=titulo,
            cuerpo=str(datos.get(regla["cuerpo_campo"], ""))
            if regla.get("cuerpo_campo")
            else regla.get("cuerpo", ""),
            objeto_tipo=objeto_tipo,
            objeto_id=objeto_id,
            prioridad=regla.get("prioridad", "normal"),
            datos=datos,
            usuarios=explicitos,
            excluir=excluir,
            # Los canales que pide el evento se AÑADEN a los del destinatario,
            # no los sustituyen. Solo lo usa `enviar_correo`, y es su razón de
            # ser: quien escribe esa regla quiere que salga un correo, no que
            # salga por donde el destinatario prefiera recibir los avisos de
            # movimiento. La franja de silencio se sigue respetando.
            canales_forzados=tuple(datos.get(regla["canales_campo"]) or ())
            if regla.get("canales_campo")
            else (),
        )


# ── API ───────────────────────────────────────────────────────────────────

router_seguimiento = APIRouter(prefix="/seguimientos", tags=["seguimiento"])
router_notificaciones = APIRouter(prefix="/notificaciones", tags=["notificaciones"])


class Seguir(BaseModel):
    objeto_tipo: str = Field(..., max_length=60)
    objeto_id: UUID
    motivo: str = "manual"


class SeguimientoOut(BaseModel):
    id: UUID
    objeto_tipo: str
    objeto_id: UUID
    motivo: str
    silenciado: bool

    model_config = {"from_attributes": True}


@router_seguimiento.get("", response_model=list[SeguimientoOut], summary="Lo que sigo")
def mis_seguimientos(
    db: DbDep,
    principal: AutenticadoDep,
    objeto_tipo: str | None = Query(None),
) -> Any:
    consulta = select(Seguimiento).where(Seguimiento.usuario_id == principal.id)
    if objeto_tipo:
        consulta = consulta.where(Seguimiento.objeto_tipo == objeto_tipo)
    return list(db.execute(consulta.order_by(Seguimiento.created_at.desc())).scalars().all())


@router_seguimiento.post(
    "",
    response_model=SeguimientoOut,
    status_code=status.HTTP_201_CREATED,
    summary="Seguir un registro",
)
def seguir_registro(datos: Seguir, uow: UowDep, principal: AutenticadoDep) -> Any:
    if datos.motivo not in MOTIVOS:
        raise ErrorValidacion(
            f"Motivo desconocido: «{datos.motivo}»",
            error_code="seguimiento.motivo_desconocido",
            detalle={"admitidos": sorted(MOTIVOS)},
        )
    return seguir(
        uow.db,
        tenant_id=principal.tenant_id,
        usuario_id=principal.id,
        objeto_tipo=datos.objeto_tipo,
        objeto_id=datos.objeto_id,
        motivo=datos.motivo,
    )


@router_seguimiento.delete(
    "/{objeto_tipo}/{objeto_id}",
    response_model=dict,
    summary="Dejar de seguir un registro",
    description=(
        "Al propietario se le **silencia** en vez de desuscribirle: no puede "
        "dejar de ser responsable de su registro, pero sí dejar de recibir "
        "avisos. Borrar la suscripción haría que volviera sola al siguiente "
        "cambio."
    ),
)
def dejar(objeto_tipo: str, objeto_id: UUID, uow: UowDep, principal: AutenticadoDep) -> Any:
    habia = dejar_de_seguir(
        uow.db,
        tenant_id=principal.tenant_id,
        usuario_id=principal.id,
        objeto_tipo=objeto_tipo,
        objeto_id=objeto_id,
    )
    return {"seguia": habia}


@router_seguimiento.get(
    "/{objeto_tipo}/{objeto_id}/seguidores",
    response_model=list[UUID],
    summary="Quién sigue este registro",
)
def quien_sigue(objeto_tipo: str, objeto_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return seguidores(
        db, tenant_id=principal.tenant_id, objeto_tipo=objeto_tipo, objeto_id=objeto_id
    )


class NotificacionOut(BaseModel):
    id: UUID
    tipo: str
    titulo: str
    cuerpo: str
    objeto_tipo: str | None
    objeto_id: UUID | None
    prioridad: str
    agrupadas: int
    leida: bool

    model_config = {"from_attributes": True}


def _salida(n: Notificacion) -> NotificacionOut:
    return NotificacionOut(
        id=n.id,
        tipo=n.tipo,
        titulo=n.titulo,
        cuerpo=n.cuerpo,
        objeto_tipo=n.objeto_tipo,
        objeto_id=n.objeto_id,
        prioridad=n.prioridad,
        agrupadas=n.agrupadas,
        leida=n.leida_at is not None,
    )


@router_notificaciones.get("", response_model=list[NotificacionOut], summary="Mi bandeja")
def mi_bandeja(
    db: DbDep,
    principal: AutenticadoDep,
    solo_no_leidas: bool = Query(False),
    limite: int = Query(50, ge=1, le=200),
) -> Any:
    filas = bandeja(
        db,
        tenant_id=principal.tenant_id,
        usuario_id=principal.id,
        solo_no_leidas=solo_no_leidas,
        limite=limite,
    )
    return [_salida(n) for n in filas]


class MarcarLeidas(BaseModel):
    ids: list[UUID] | None = None


@router_notificaciones.post("/leidas", response_model=dict, summary="Marcar como leídas")
def leidas(datos: MarcarLeidas, uow: UowDep, principal: AutenticadoDep) -> Any:
    n = marcar_leidas(
        uow.db,
        tenant_id=principal.tenant_id,
        usuario_id=principal.id,
        ids=datos.ids,
    )
    return {"marcadas": n}


class FijarPreferencia(BaseModel):
    tipo: str = Field("*", max_length=80, description="Tipo de evento, o «*» para todos")
    canales: list[str]
    agrupar_minutos: int = Field(0, ge=0, le=1440)
    silencio_desde: int | None = Field(None, ge=0, le=23)
    silencio_hasta: int | None = Field(None, ge=0, le=23)


class PreferenciaOut(BaseModel):
    tipo: str
    canales: list[Any]
    agrupar_minutos: int
    silencio_desde: int | None
    silencio_hasta: int | None

    model_config = {"from_attributes": True}


@router_notificaciones.get(
    "/preferencias", response_model=list[PreferenciaOut], summary="Mis preferencias"
)
def mis_preferencias(db: DbDep, principal: AutenticadoDep) -> Any:
    return list(
        db.execute(
            select(PreferenciaNotificacion).where(
                PreferenciaNotificacion.usuario_id == principal.id
            )
        )
        .scalars()
        .all()
    )


@router_notificaciones.put(
    "/preferencias",
    response_model=PreferenciaOut,
    summary="Fijar mis preferencias para un tipo de evento",
    description=(
        "La preferencia del tipo exacto gana sobre la genérica «*». Así se "
        "puede decir «nada de correo salvo los casos escalados», que es la "
        "petición habitual y con la genérica ganando sería inexpresable."
    ),
)
def fijar_preferencia(datos: FijarPreferencia, uow: UowDep, principal: AutenticadoDep) -> Any:
    malos = [c for c in datos.canales if c not in CANALES]
    if malos:
        raise ErrorValidacion(
            f"Canales desconocidos: {', '.join(malos)}",
            error_code="notificacion.canal_desconocido",
            detalle={"admitidos": list(CANALES)},
        )
    if (datos.silencio_desde is None) != (datos.silencio_hasta is None):
        raise ErrorValidacion(
            "La franja de silencio necesita las dos horas, o ninguna",
            error_code="notificacion.silencio_incompleto",
        )

    fila = uow.db.execute(
        select(PreferenciaNotificacion).where(
            PreferenciaNotificacion.usuario_id == principal.id,
            PreferenciaNotificacion.tipo == datos.tipo,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = PreferenciaNotificacion(
            tenant_id=principal.tenant_id,
            usuario_id=principal.id,
            tipo=datos.tipo,
        )
        uow.db.add(fila)
    fila.canales = datos.canales
    fila.agrupar_minutos = datos.agrupar_minutos
    fila.silencio_desde = datos.silencio_desde
    fila.silencio_hasta = datos.silencio_hasta
    uow.db.flush()
    return fila


@router_notificaciones.get(
    "/canales", response_model=dict, summary="Canales de entrega disponibles"
)
def canales() -> Any:
    return {"canales": list(CANALES), "motivos_seguimiento": MOTIVOS}


ROUTERS_NOTIFICACION = [router_seguimiento, router_notificaciones]
