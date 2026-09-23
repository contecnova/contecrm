"""API de eventos salientes: suscripciones, entregas, catálogo y replay."""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any
from uuid import UUID

from crmcore.audit.chain import registrar
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, exige_permiso
from crmcore.http.listados import montar_ficha  # noqa: E402
from crmcore.red import exigir
from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.eventing.modelos import Entrega, EventoArchivado, Suscripcion


class CrearSuscripcion(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=200)
    url: str = Field(
        ...,
        pattern=r"^https://.+",
        description=(
            "Solo HTTPS. Un webhook lleva datos de negocio firmados; por HTTP "
            "plano, cualquiera en el camino los lee. Además se comprueba que no "
            "apunte a la red interna ni a los metadatos del proveedor de nube: "
            "se rechaza al darlo de alta, para que el error salga delante de "
            "quien lo está configurando y no en un log a las tres de la mañana"
        ),
    )
    eventos: list[str] = Field(
        ...,
        min_length=1,
        description="Tipos de evento, con comodín por sufijo",
        examples=[["opportunity.won", "case.*"]],
    )
    condiciones: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Filtro sobre el contenido, para no recibir lo que no interesa",
        examples=[[{"atributo": "importe", "op": ">", "valor": 10000}]],
    )
    cabeceras: dict[str, str] = Field(default_factory=dict)


class SuscripcionCreada(BaseModel):
    id: UUID
    nombre: str
    url: str
    eventos: list[str]
    secreto: str = Field(
        ...,
        description=(
            "Secreto de firma. Se muestra **una sola vez**: guárdalo ahora. "
            "Con él se verifica la cabecera X-Contecrm-Firma"
        ),
    )


class SuscripcionOut(BaseModel):
    id: UUID
    nombre: str
    url: str
    eventos: list[str] = []
    condiciones: list[dict[str, Any]] = []
    activa: bool
    fallos_consecutivos: int
    ultimo_exito_at: datetime | None = None
    desactivada_at: datetime | None = None

    model_config = {"from_attributes": True}


class EntregaOut(BaseModel):
    id: UUID
    tipo: str
    evento_id: UUID
    intento: int
    resultado: str
    codigo_http: int | None = None
    error: str | None = None
    duracion_ms: int
    created_at: datetime

    model_config = {"from_attributes": True}


class PedirReplay(BaseModel):
    """Reproducir eventos pasados (CRM-00.02.02.09)."""

    desde: datetime = Field(..., description="Inicio de la ventana a reproducir")
    hasta: datetime | None = None
    tipos: list[str] = Field(
        default_factory=list, description="Vacío = los que ya cubre la suscripción"
    )


router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post(
    "",
    response_model=SuscripcionCreada,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("webhook:write"))],
    summary="Suscribir un endpoint a eventos",
)
def crear(datos: CrearSuscripcion, db: DbDep, principal: AutenticadoDep) -> Any:
    from crmcore.events.catalogo import todos

    conocidos = {t.tipo for t in todos()}
    desconocidos = [e for e in datos.eventos if not e.endswith("*") and e not in conocidos]
    if desconocidos:
        # Se rechaza en vez de aceptar en silencio: una suscripción a un evento
        # mal escrito no falla nunca, simplemente no llega nada, y el integrador
        # pierde días buscando el fallo en su lado.
        raise ErrorValidacion(
            "Hay tipos de evento que no existen",
            error_code="webhook.eventos_desconocidos",
            detalle={"desconocidos": desconocidos, "disponibles": sorted(conocidos)[:50]},
        )

    # Se comprueba ya al darla de alta, además de en cada entrega: así el error
    # sale delante de quien está configurando el webhook y no en un log de
    # entregas fallidas. En la entrega se vuelve a comprobar porque el DNS de un
    # dominio puede cambiar después.
    exigir(datos.url)

    secreto = secrets.token_urlsafe(32)
    suscripcion = Suscripcion(tenant_id=principal.tenant_id, secreto=secreto, **datos.model_dump())
    db.add(suscripcion)
    db.flush()
    registrar(
        db,
        accion="webhook.suscrito",
        objeto="suscripcion_webhook",
        objeto_id=suscripcion.id,
        datos={"url": datos.url, "eventos": datos.eventos},
    )
    return SuscripcionCreada(
        id=suscripcion.id,
        nombre=suscripcion.nombre,
        url=suscripcion.url,
        eventos=list(suscripcion.eventos),
        secreto=secreto,
    )


@router.get(
    "",
    response_model=list[SuscripcionOut],
    dependencies=[Depends(exige_permiso("webhook:read"))],
    summary="Suscripciones del tenant",
)
def listar(db: DbDep, principal: AutenticadoDep) -> Any:
    return list(
        db.execute(
            select(Suscripcion)
            .where(Suscripcion.tenant_id == principal.tenant_id)
            .order_by(Suscripcion.nombre)
        )
        .scalars()
        .all()
    )


@router.get(
    "/{suscripcion_id}/entregas",
    response_model=list[EntregaOut],
    dependencies=[Depends(exige_permiso("webhook:read"))],
    summary="Historial de entregas",
    description=(
        "Incluye cada intento con su código HTTP y la respuesta del receptor. "
        "Es lo que permite depurar con el integrador sin pedirle sus logs."
    ),
)
def entregas(
    suscripcion_id: UUID,
    db: DbDep,
    principal: AutenticadoDep,
    resultado: str = Query("", description="entregado, fallido, descartado"),
    limite: int = Query(50, ge=1, le=200),
) -> Any:
    consulta = select(Entrega).where(
        Entrega.suscripcion_id == suscripcion_id,
        Entrega.tenant_id == principal.tenant_id,
    )
    if resultado:
        consulta = consulta.where(Entrega.resultado == resultado)
    return list(
        db.execute(consulta.order_by(Entrega.created_at.desc()).limit(limite)).scalars().all()
    )


@router.post(
    "/{suscripcion_id}/reactivar",
    response_model=SuscripcionOut,
    dependencies=[Depends(exige_permiso("webhook:write"))],
    summary="Reactivar una suscripción desactivada por fallos",
)
def reactivar(suscripcion_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    suscripcion = db.get(Suscripcion, suscripcion_id)
    if suscripcion is None or suscripcion.tenant_id != principal.tenant_id:
        raise NoEncontrado("La suscripción no existe", error_code="webhook.no_encontrada")
    suscripcion.activa = True
    suscripcion.fallos_consecutivos = 0
    suscripcion.desactivada_at = None
    return suscripcion


@router.post(
    "/{suscripcion_id}/replay",
    response_model=dict,
    dependencies=[Depends(exige_permiso("webhook:write"))],
    summary="Reenviar eventos de una ventana de tiempo",
    description=(
        "Para cuando el sistema del integrador estuvo caído. Reencola los "
        "eventos archivados del periodo; la deduplicación por `dedup_key` evita "
        "que procese dos veces lo que sí recibió."
    ),
)
def replay(suscripcion_id: UUID, datos: PedirReplay, db: DbDep, principal: AutenticadoDep) -> Any:
    suscripcion = db.get(Suscripcion, suscripcion_id)
    if suscripcion is None or suscripcion.tenant_id != principal.tenant_id:
        raise NoEncontrado("La suscripción no existe", error_code="webhook.no_encontrada")
    if datos.hasta and datos.hasta <= datos.desde:
        raise ErrorValidacion(
            "La ventana de replay está al revés",
            error_code="webhook.ventana_invalida",
        )

    consulta = select(EventoArchivado).where(
        EventoArchivado.tenant_id == principal.tenant_id,
        EventoArchivado.occurred_at >= datos.desde,
    )
    if datos.hasta:
        consulta = consulta.where(EventoArchivado.occurred_at <= datos.hasta)
    if datos.tipos:
        consulta = consulta.where(EventoArchivado.tipo.in_(datos.tipos))

    # Tope de seguridad: un replay de un año entero a un endpoint lento es una
    # denegación de servicio autoinfligida, y además al integrador.
    archivados = list(
        db.execute(consulta.order_by(EventoArchivado.occurred_at).limit(5000)).scalars().all()
    )
    for archivado in archivados:
        db.add(
            Entrega(
                tenant_id=principal.tenant_id,
                suscripcion_id=suscripcion.id,
                evento_id=UUID(archivado.sobre["id"]),
                tipo=archivado.tipo,
                dedup_key=archivado.dedup_key,
                resultado="fallido",  # lo recoge el worker de reintentos
                proximo_intento_at=datetime.now(datos.desde.tzinfo),
                error="reencolado por replay",
            )
        )
    registrar(
        db,
        accion="webhook.replay",
        objeto="suscripcion_webhook",
        objeto_id=suscripcion.id,
        datos={"desde": datos.desde.isoformat(), "eventos": len(archivados)},
    )
    return {"reencolados": len(archivados), "tope": 5000}


# ── Catálogo de eventos ───────────────────────────────────────────────────

router_catalogo = APIRouter(prefix="/eventos", tags=["catálogo de eventos"])


@router_catalogo.get(
    "/catalogo",
    response_model=list[dict],
    summary="Eventos que puede recibir un integrador",
    description=(
        "Tipo, versión, servicio que lo publica y campos garantizados de `data`. "
        "La forma de `data` solo crece: añadir un campo es compatible, quitarlo "
        "exige una versión nueva."
    ),
)
def catalogo() -> Any:
    from crmcore.events.catalogo import publicos

    return [
        {
            "tipo": t.tipo,
            "version": t.version,
            "productor": t.productor,
            "descripcion": t.descripcion,
            "campos": list(t.campos),
        }
        for t in publicos()
    ]


@router_catalogo.get(
    "/asyncapi.json",
    summary="Especificación AsyncAPI de los eventos",
    description=(
        "Generada desde el registro de eventos del código, nunca a mano: una "
        "especificación mantenida a mano describe lo que alguien creía que el "
        "sistema publicaba el día que la escribió."
    ),
)
def asyncapi() -> Response:
    import json

    from crmcore.config import get_settings
    from crmcore.events.catalogo import a_asyncapi

    s = get_settings()
    documento = a_asyncapi(f"{s.app_name} — eventos de dominio", s.service_version)
    return Response(
        content=json.dumps(documento, ensure_ascii=False), media_type="application/json"
    )


@router_catalogo.get(
    "/archivo",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("event:read"))],
    summary="Eventos archivados del tenant",
)
def archivo(
    db: DbDep,
    principal: AutenticadoDep,
    tipo: str = Query(""),
    limite: int = Query(100, ge=1, le=1000),
) -> Any:
    consulta = select(EventoArchivado).where(EventoArchivado.tenant_id == principal.tenant_id)
    if tipo:
        consulta = consulta.where(EventoArchivado.tipo == tipo)
    filas = (
        db.execute(consulta.order_by(EventoArchivado.occurred_at.desc()).limit(limite))
        .scalars()
        .all()
    )
    return [f.sobre for f in filas]


# ── Cola de fallidos ──────────────────────────────────────────────────────

router_dlq = APIRouter(prefix="/eventos/fallidos", tags=["cola de fallidos"])


@router_dlq.get(
    "",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("event:read"))],
    summary="Eventos que agotaron sus reintentos",
)
def listar_fallidos(
    db: DbDep, principal: AutenticadoDep, limite: int = Query(50, ge=1, le=200)
) -> Any:
    from crmcore.bus.modelos import EventoFallido

    filas = (
        db.execute(
            select(EventoFallido)
            .where(EventoFallido.tenant_id == principal.tenant_id)
            .order_by(EventoFallido.created_at.desc())
            .limit(limite)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "origen": f.origen,
            "tipo": f.tipo,
            "intentos": f.intentos,
            "ultimo_error": f.ultimo_error,
            "reenviado_at": f.reenviado_at.isoformat() if f.reenviado_at else None,
            "created_at": f.created_at.isoformat(),
        }
        for f in filas
    ]


@router_dlq.post(
    "/{fallido_id}/reenviar",
    response_model=dict,
    dependencies=[Depends(exige_permiso("event:write"))],
    summary="Reenviar un evento de la cola de fallidos",
    description=(
        "Lo devuelve a la cola de salida en vez de publicarlo aquí: así el "
        "reenvío pasa por exactamente el mismo camino que el envío normal, sin "
        "un segundo camino que mantener."
    ),
)
def reenviar(fallido_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    from crmcore.bus.outbox import reenviar_fallido

    nuevo = reenviar_fallido(db, fallido_id, por=principal.id)
    registrar(
        db,
        accion="evento.reenviado",
        objeto="evento_fallido",
        objeto_id=fallido_id,
        datos={"tipo": nuevo.tipo},
    )
    return {"reencolado": True, "tipo": nuevo.tipo}


ROUTERS = [router, router_catalogo, router_dlq]


# ── La ficha del registro ─────────────────────────────────────────────────
# Sin ella, las acciones que cuelgan de un registro no se alcanzan desde
# ninguna pantalla: existen, se prueban y nadie las usa.
montar_ficha(
    router,
    modelo=Suscripcion,
    objeto="webhook",
    permiso_leer="webhook:read",
    permiso_escribir="webhook:write",
    nombre="Webhooks",
    parametro="webhook_id",
)


# ── La ficha del registro ─────────────────────────────────────────────────
# Sin ella, las acciones que cuelgan de un registro no se alcanzan desde
# ninguna pantalla: existen, se prueban y nadie las usa.
from crmcore.bus.modelos import EventoFallido as _EventoFallido  # noqa: E402

montar_ficha(
    # El router de fallidos ya lleva el prefijo entero, así que la ficha cuelga
    # de su raíz y no de una subruta.
    router_dlq,
    modelo=_EventoFallido,
    objeto="evento_fallido",
    permiso_leer="event:read",
    permiso_escribir="event:write",
    nombre="Eventos fallidos",
    parametro="fallido_id",
)
