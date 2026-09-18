"""Dependencias de FastAPI compartidas por todos los servicios.

Aquí está la autenticación de las peticiones que llegan a un servicio. Hay dos
casos y conviene no mezclarlos:

  * **Petición del gateway.** El gateway ya autenticó al usuario y pasa la
    identidad en cabeceras internas firmadas. El servicio no vuelve a validar el
    token del usuario final: no lo tiene y no debería tenerlo.
  * **Petición directa.** Contra un servicio, en desarrollo o desde otro
    servicio. Lleva token propio y se valida aquí.

Que el gateway pase la identidad por cabecera **solo funciona si esas cabeceras
no pueden falsificarse desde fuera**. Dos condiciones, las dos necesarias:
la red interna no es alcanzable desde fuera, y las cabeceras van firmadas con un
secreto compartido. La segunda está implementada; la primera es del despliegue y
está dicha en el manual de operación, porque un servicio publicado por error en
Internet con esta confianza activada es un salto de autenticación directo.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Iterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from crmcore.authz.principal import ANONIMO, Principal
from crmcore.errors import NoAutenticado, Prohibido
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Cabeceras con las que el gateway propaga la identidad ya verificada.
H_TENANT = "x-crm-tenant"
H_USER = "x-crm-user"
H_PERMISOS = "x-crm-permisos"
H_SCOPES = "x-crm-scopes"
H_ACTOR_REAL = "x-crm-actor-real"
H_PLATAFORMA = "x-crm-plataforma"
H_FIRMA = "x-crm-firma"
H_MOMENTO = "x-crm-momento"

# Ventana en la que se acepta la firma interna. Corta: estas peticiones viajan
# por la red interna y tardan milisegundos, así que una ventana amplia solo
# amplía el margen para reutilizar una petición capturada.
VENTANA_FIRMA_S = 30


def firmar_cabeceras_internas(valores: dict[str, str], secreto: str) -> dict[str, str]:
    """Firma las cabeceras de identidad. Lo usa el gateway al reenviar."""
    momento = str(int(time.time()))
    material = _material(valores, momento)
    firma = hmac.new(secreto.encode(), material.encode(), hashlib.sha256).hexdigest()
    return {**valores, H_MOMENTO: momento, H_FIRMA: firma}


def _material(valores: dict[str, str], momento: str) -> str:
    """Cadena que se firma: las cabeceras ordenadas más el instante.

    Ordenadas para que emisor y verificador construyan la misma cadena
    independientemente del orden en que se hayan compuesto los valores.
    """
    partes = [f"{k.lower()}={v}" for k, v in sorted(valores.items()) if v]
    return "|".join([*partes, momento])


def _verificar_firma(request: Request, secreto: str) -> bool:
    firma = request.headers.get(H_FIRMA, "")
    momento = request.headers.get(H_MOMENTO, "")
    if not firma or not momento.isdigit():
        return False
    if abs(time.time() - int(momento)) > VENTANA_FIRMA_S:
        logger.warning("deps.firma_caducada")
        return False
    valores = {
        h: request.headers.get(h, "")
        for h in (H_TENANT, H_USER, H_PERMISOS, H_SCOPES, H_ACTOR_REAL, H_PLATAFORMA)
    }
    esperada = hmac.new(
        secreto.encode(), _material(valores, momento).encode(), hashlib.sha256
    ).hexdigest()
    # Comparación en tiempo constante: comparar con `==` filtra por el tiempo de
    # ejecución cuántos caracteres iniciales ha acertado quien lo intenta.
    return hmac.compare_digest(firma, esperada)


async def contexto_autenticado(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    """Resuelve el principal de la petición y lo deja en el contexto.

    Es la dependencia que usan casi todos los endpoints. No decide permisos: eso
    es de `exige_permiso`. Solo establece quién es.
    """
    from dataclasses import replace

    from crmcore.config import get_settings
    from crmcore.tenancy.context import contexto_actual, fijar_contexto

    s = get_settings()
    secreto = s.secret_key.get_secret_value()

    principal: Principal
    if request.headers.get(H_FIRMA):
        if not _verificar_firma(request, secreto):
            raise NoAutenticado(
                "La identidad propagada no es válida",
                error_code="auth.firma_interna_invalida",
            )
        principal = _principal_de_cabeceras(request)
    elif authorization and authorization.lower().startswith("bearer "):
        principal = _principal_de_token(authorization[7:], secreto)
    else:
        principal = ANONIMO

    ctx = contexto_actual()
    fijar_contexto(
        replace(
            ctx,
            tenant_id=principal.tenant_id,
            user_id=principal.id,
            business_unit_id=principal.business_unit_id,
            scopes=principal.scopes,
            es_admin_plataforma=principal.es_admin_plataforma,
            actor_real_id=principal.actor_real_id,
            extra={**ctx.extra, "principal": principal, "ip": _ip(request)},
        )
    )
    return principal


def _ip(request: Request) -> str:
    from crmcore.config import get_settings

    if get_settings().trust_proxy_headers:
        reenviada = request.headers.get("x-forwarded-for", "")
        if reenviada:
            return reenviada.split(",")[0].strip()
    return request.client.host if request.client else ""


def _principal_de_cabeceras(request: Request) -> Principal:
    def _uuid(nombre: str) -> UUID | None:
        valor = request.headers.get(nombre, "")
        try:
            return UUID(valor) if valor else None
        except ValueError:
            return None

    return Principal(
        id=_uuid(H_USER),
        tenant_id=_uuid(H_TENANT),
        actor_real_id=_uuid(H_ACTOR_REAL),
        permisos=frozenset(p for p in request.headers.get(H_PERMISOS, "").split(",") if p),
        scopes=frozenset(p for p in request.headers.get(H_SCOPES, "").split(",") if p),
        es_admin_plataforma=request.headers.get(H_PLATAFORMA, "") == "1",
    )


def _principal_de_token(token: str, secreto: str) -> Principal:
    import jwt

    from crmcore.config import get_settings

    try:
        datos: dict[str, Any] = jwt.decode(
            token, secreto, algorithms=[get_settings().jwt_algorithm]
        )
    except jwt.ExpiredSignatureError:
        # Código propio y distinto del genérico: un cliente que sabe que el
        # token caducó renueva y reintenta solo; uno que recibe «no autenticado»
        # manda al usuario a la pantalla de inicio de sesión sin necesidad.
        raise NoAutenticado("El token ha caducado", error_code="auth.token_caducado")
    except jwt.InvalidTokenError:
        raise NoAutenticado("El token no es válido", error_code="auth.token_invalido")

    try:
        return Principal(
            id=UUID(datos["sub"]) if datos.get("sub") else None,
            tenant_id=UUID(datos["tenant"]) if datos.get("tenant") else None,
            tipo=datos.get("tipo", "usuario"),
            permisos=frozenset(datos.get("permisos", [])),
            roles=frozenset(datos.get("roles", [])),
            scopes=frozenset(datos.get("scopes", [])),
            es_admin_plataforma=bool(datos.get("plataforma")),
            actor_real_id=UUID(datos["actor_real"]) if datos.get("actor_real") else None,
        )
    except (ValueError, KeyError):
        raise NoAutenticado(
            "El token no tiene la forma esperada", error_code="auth.token_malformado"
        )


PrincipalDep = Annotated[Principal, Depends(contexto_autenticado)]


def exige_autenticacion(principal: PrincipalDep) -> Principal:
    """Endpoint que exige identidad, sea del tipo que sea."""
    if principal.es_anonimo:
        raise NoAutenticado(
            "Esta operación exige autenticación", error_code="auth.requerida"
        )
    return principal


AutenticadoDep = Annotated[Principal, Depends(exige_autenticacion)]


def exige_permiso(permiso: str) -> Any:
    """Fábrica de dependencia que exige un permiso concreto.

        @router.post("/accounts", dependencies=[Depends(exige_permiso("account:write"))])

    Se declara en la ruta y no dentro del cuerpo a propósito: así el gate
    `test_auth_gate_contract.py` puede recorrer las rutas y comprobar que
    ninguna escribe sin exigir permiso. Una comprobación escondida dentro de la
    función no se puede auditar sin ejecutarla.
    """

    def _dep(principal: AutenticadoDep) -> Principal:
        principal.exigir(permiso)
        return principal

    return _dep


def exige_plataforma(principal: AutenticadoDep) -> Principal:
    """Solo personal de la plataforma (alta de tenants, operación)."""
    if not principal.es_admin_plataforma:
        raise Prohibido(
            "Esta operación es de administración de la plataforma",
            error_code="authz.solo_plataforma",
        )
    return principal


PlataformaDep = Annotated[Principal, Depends(exige_plataforma)]


def get_db(principal: PrincipalDep) -> Iterator[Session]:
    """Sesión de base de datos atada al tenant de la petición.

    Atarla aquí, y no en cada endpoint, es lo que hace que el aislamiento no
    dependa de que nadie se despiste: la sesión nace con el tenant, y de ahí
    salen el GUC de RLS y el guard ORM.
    """
    from crmcore.db.session import nueva_sesion

    db = nueva_sesion(principal.tenant_id, sistema=principal.es_admin_plataforma)
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


DbDep = Annotated[Session, Depends(get_db)]


def get_uow(principal: PrincipalDep) -> Iterator[Any]:
    """Unidad de trabajo: transacción más los eventos que produce.

    Se usa en las escrituras que emiten eventos de dominio, que son casi todas.
    """
    from crmcore.bus.outbox import despertar_relevo
    from crmcore.db.session import nueva_sesion
    from crmcore.db.uow import UnidadDeTrabajo

    db = nueva_sesion(principal.tenant_id, sistema=principal.es_admin_plataforma)
    uow = UnidadDeTrabajo(db=db, tenant_id=db.info.get("tenant_id"))
    try:
        yield uow
        uow._volcar_eventos()
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    despertar_relevo()


UowDep = Annotated[Any, Depends(get_uow)]
