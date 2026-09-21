"""API SCIM 2.0 (CRM-00.05.01.05, RFC 7644).

Dos cosas separan esta API del resto del servicio, y las dos son requisito del
RFC, no gusto:

1. **El sobre de error es distinto.** Un cliente SCIM —Okta, Entra ID— espera
   `{"schemas": [...:Error], "status": "409", "scimType": "uniqueness"}`. Si se
   le devuelve el problema+json del resto del sistema, lo registra como fallo
   opaco, reintenta el mismo ciclo cada hora y nadie se entera de por qué la
   sincronización no avanza. Por eso el router lleva su propia clase de ruta que
   traduce los errores del dominio al formato SCIM.
2. **El tipo de contenido es `application/scim+json`.** Hay clientes que
   rechazan la respuesta si llega como `application/json`.

El tenant sale de la clave de API, nunca del cuerpo ni de la URL: es lo que hace
imposible que un cliente SCIM de un cliente toque los usuarios de otro.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.errors import CrmError
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from services.identity import scim

TIPO = "application/scim+json"

# `scimType` del RFC 7644 §3.12. No es decorativo: el cliente lo usa para
# decidir si reintenta, si reconcilia o si para. Un 409 sin `uniqueness` hace
# que Okta reintente el alta en bucle en vez de leer el recurso existente.
_SCIM_TYPE = {
    "scim.usuario_duplicado": "uniqueness",
    "scim.filtro_no_soportado": "invalidFilter",
    "scim.atributo_no_filtrable": "invalidFilter",
    "scim.active_ilegible": "invalidValue",
    "scim.patch_vacio": "invalidSyntax",
    "scim.patch_sin_destino": "invalidPath",
    "scim.patch_sin_efecto": "invalidPath",
    "scim.op_no_soportada": "invalidSyntax",
    "scim.sin_identificador": "invalidValue",
}


def respuesta_error(exc: CrmError) -> JSONResponse:
    cuerpo: dict[str, Any] = {
        "schemas": [scim.ESQUEMA_ERROR],
        "status": str(exc.status_code),
        "detail": str(exc),
    }
    tipo = _SCIM_TYPE.get(exc.error_code or "")
    if tipo:
        cuerpo["scimType"] = tipo
    # El código propio se conserva aparte del `scimType`: el RFC solo admite un
    # vocabulario cerrado, y perder el código fino dejaría el soporte a ciegas.
    cuerpo["errorCode"] = exc.error_code
    if exc.detalle:
        cuerpo["detalle"] = exc.detalle
    return JSONResponse(cuerpo, status_code=exc.status_code, media_type=TIPO)


class RutaScim(APIRoute):
    """Ruta que traduce los errores del dominio al sobre de error de SCIM."""

    def get_route_handler(self) -> Any:
        original = super().get_route_handler()

        async def manejar(request: Request) -> Response:
            try:
                return await original(request)
            except CrmError as exc:
                return respuesta_error(exc)

        return manejar


router_scim = APIRouter(prefix="/scim/v2", tags=["SCIM"], route_class=RutaScim)


def _base(request: Request) -> str:
    """La URL pública de esta API, que es la que va en `meta.location`.

    Se compone de lo que llega en la petición porque el servicio está detrás del
    gateway: escribir aquí la dirección interna haría que el IdP siguiera un
    enlace que no resuelve desde fuera.
    """
    return str(request.url).split("/scim/v2")[0].rstrip("/") + "/scim/v2"


def _json(cuerpo: Any, codigo: int = 200) -> JSONResponse:
    return JSONResponse(cuerpo, status_code=codigo, media_type=TIPO)


# ── Descubrimiento (sin permiso: no revela datos) ─────────────────────────


@router_scim.get(
    "/ServiceProviderConfig",
    summary="Qué soporta este servidor SCIM",
    description=(
        "Declara solo lo que está implementado de verdad. Declarar `bulk` o "
        "`sort` sin tenerlos haría que el IdP los intentara y se llevara un "
        "error a mitad de un ciclo de sincronización."
    ),
)
def configuracion(request: Request, principal: AutenticadoDep) -> Any:
    return _json(scim.configuracion_del_proveedor(_base(request)))


@router_scim.get("/ResourceTypes", summary="Tipos de recurso publicados")
def tipos(request: Request, principal: AutenticadoDep) -> Any:
    base = _base(request)
    recursos = scim.tipos_de_recurso(base)
    return _json(scim.lista(recursos, len(recursos), 1, len(recursos)))


@router_scim.get("/Schemas", summary="Esquemas de los recursos publicados")
def lista_esquemas(request: Request, principal: AutenticadoDep) -> Any:
    base = _base(request)
    recursos = scim.esquemas(base)
    return _json(scim.lista(recursos, len(recursos), 1, len(recursos)))


# ── Usuarios ──────────────────────────────────────────────────────────────


@router_scim.get(
    "/Users",
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Buscar usuarios",
    description=(
        'El filtro admite `atributo op "valor"` con eq, ne, co y sw sobre '
        "`userName`. Es lo único que mandan los IdP en la práctica —comprobar "
        "si el recurso ya existe antes de crearlo—, y un filtro que no se "
        "entiende se rechaza en vez de devolver una lista incorrecta."
    ),
)
def buscar_usuarios(
    request: Request,
    db: DbDep,
    principal: AutenticadoDep,
    filter: str = Query("", description='Ej.: userName eq "ana@ejemplo.com"'),
    startIndex: int = Query(1, ge=1),
    count: int = Query(100, ge=1),
) -> Any:
    base = _base(request)
    filas, total = scim.buscar_usuarios(
        db, principal.tenant_id, filtro=filter, inicio=startIndex, por_pagina=count
    )
    recursos = [scim.usuario_a_scim(u, m, base) for u, m in filas]
    return _json(scim.lista(recursos, total, startIndex, count))


@router_scim.get(
    "/Users/{usuario_id}",
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Leer un usuario",
)
def leer_usuario(request: Request, usuario_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    usuario, membresia = scim.leer_usuario(db, usuario_id, principal.tenant_id)
    return _json(scim.usuario_a_scim(usuario, membresia, _base(request)))


@router_scim.post(
    "/Users",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("user:write"))],
    summary="Alta de usuario",
    description=(
        "Crea el usuario sin contraseña local: entra por el proveedor de "
        "identidad. Sin contraseña no hay forma de saltarse el IdP corporativo, "
        "que es justo lo que se quiere de un alta automática."
    ),
)
def alta(request: Request, cuerpo: dict[str, Any], uow: UowDep, principal: AutenticadoDep) -> Any:
    usuario, membresia = scim.crear_usuario(uow, principal.tenant_id, cuerpo)
    uow.db.flush()
    return _json(scim.usuario_a_scim(usuario, membresia, _base(request)), 201)


@router_scim.put(
    "/Users/{usuario_id}",
    dependencies=[Depends(exige_permiso("user:write"))],
    summary="Reemplazar un usuario",
)
def reemplazar(
    request: Request,
    usuario_id: UUID,
    cuerpo: dict[str, Any],
    uow: UowDep,
    principal: AutenticadoDep,
) -> Any:
    usuario, membresia = scim.actualizar_usuario(uow, usuario_id, principal.tenant_id, cuerpo)
    uow.db.flush()
    return _json(scim.usuario_a_scim(usuario, membresia, _base(request)))


@router_scim.patch(
    "/Users/{usuario_id}",
    dependencies=[Depends(exige_permiso("user:write"))],
    summary="Modificar un usuario (por aquí llega la baja)",
    description=(
        "Se aceptan las dos formas que mandan los proveedores mayoritarios: con "
        "`path` explícito y con el atributo dentro de `value`. Y `active` se lee "
        'tanto booleano como en texto, porque Entra ID manda `"False"`: leído '
        "como booleano de Python eso es cierto, y la baja se convertiría en "
        "«sigue activo»."
    ),
)
def modificar(
    request: Request,
    usuario_id: UUID,
    cuerpo: dict[str, Any],
    uow: UowDep,
    principal: AutenticadoDep,
) -> Any:
    usuario, membresia = scim.aplicar_patch(uow, usuario_id, principal.tenant_id, cuerpo)
    uow.db.flush()
    return _json(scim.usuario_a_scim(usuario, membresia, _base(request)))


@router_scim.delete(
    "/Users/{usuario_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(exige_permiso("user:write"))],
    summary="Baja de usuario",
    description=(
        "**No borra.** Desactiva la membresía en este tenant y corta sus "
        "sesiones en el acto. Borrar dejaría huérfano todo lo que creó y el "
        "historial pasaría a referirse a un identificador inexistente; cortar "
        "las sesiones es lo que hace que la baja surta efecto ya y no cuando "
        "caduque el token."
    ),
)
def baja(usuario_id: UUID, uow: UowDep, principal: AutenticadoDep) -> Response:
    scim.desactivar(uow, usuario_id, principal.tenant_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Grupos ────────────────────────────────────────────────────────────────


@router_scim.get(
    "/Groups",
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Buscar grupos",
    description="Un grupo SCIM es un rol del tenant; sus miembros, las membresías activas con ese rol.",
)
def buscar_grupos(
    request: Request,
    db: DbDep,
    principal: AutenticadoDep,
    filter: str = Query(""),
    startIndex: int = Query(1, ge=1),
    count: int = Query(100, ge=1),
) -> Any:
    base = _base(request)
    filas, total = scim.buscar_grupos(
        db, principal.tenant_id, filtro=filter, inicio=startIndex, por_pagina=count
    )
    recursos = [scim.grupo_a_scim(r, m, base) for r, m in filas]
    return _json(scim.lista(recursos, total, startIndex, count))


@router_scim.get(
    "/Groups/{grupo_id}",
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Leer un grupo",
)
def leer_grupo(request: Request, grupo_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    rol, miembros = scim.leer_grupo(db, grupo_id, principal.tenant_id)
    return _json(scim.grupo_a_scim(rol, miembros, _base(request)))


@router_scim.patch(
    "/Groups/{grupo_id}",
    dependencies=[Depends(exige_permiso("user:write"))],
    summary="Añadir o quitar miembros de un grupo",
    description=(
        "Un grupo que llega del directorio solo concede permisos si su nombre "
        "coincide con un rol que existe aquí. Aceptarlo por el nombre dejaría la "
        "matriz de permisos en manos de quien administre el directorio."
    ),
)
def modificar_grupo(
    request: Request,
    grupo_id: UUID,
    cuerpo: dict[str, Any],
    uow: UowDep,
    principal: AutenticadoDep,
) -> Any:
    rol, miembros = scim.patch_grupo(uow, grupo_id, principal.tenant_id, cuerpo)
    uow.db.flush()
    return _json(scim.grupo_a_scim(rol, miembros, _base(request)))


ROUTERS_SCIM = [router_scim]
