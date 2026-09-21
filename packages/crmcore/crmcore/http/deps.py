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
from typing import Annotated, Any, Callable
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
# Los roles viajan ADEMÁS de los permisos, y no son redundantes: hay decisiones
# que se toman por rol y no por permiso —una tarea humana asignada a
# «responsable_ventas» la coge quien tenga ese rol—. Sin propagarlos, esa
# bandeja sale vacía aunque el usuario tenga el rol: se descubrió probando el
# ciclo completo de una aprobación.
H_ROLES = "x-crm-roles"
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
        for h in (H_TENANT, H_USER, H_PERMISOS, H_ROLES, H_SCOPES, H_ACTOR_REAL, H_PLATAFORMA)
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
        roles=frozenset(r for r in request.headers.get(H_ROLES, "").split(",") if r),
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
        raise NoAutenticado("Esta operación exige autenticación", error_code="auth.requerida")
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


def proyectar_para(
    principal: Principal, db: Any, *, objeto: str, modelo: type
) -> Callable[[Any], dict[str, Any]]:
    """Devuelve la función que serializa un registro **ya filtrado**.

    Se usa así en un endpoint:

        proyecta = proyectar_para(principal, db, objeto="cuenta", modelo=Cuenta)
        return [proyecta(c) for c in cuentas]

    Es una llamada explícita y no magia en la serialización, y es deliberado:
    enmascarar el campo equivocado en silencio es peor que una llamada que
    falta, porque una llamada que falta la caza el gate
    (`test_contratos_arquitectura.py`) y un enmascarado equivocado no lo caza
    nadie hasta que un cliente enseña una pantalla con puntos donde debería
    haber un teléfono.

    La política se resuelve **una vez** y se cierra sobre el resultado: hacerlo
    por fila consultaría las excepciones una vez por registro, y un listado de
    doscientas cuentas haría doscientas consultas para aplicar la misma regla.
    """
    from crmcore.authz.proyeccion import (
        _excepciones,
        _nivel_del_campo,
        _politica_por_rol,
        anotar_retenidos,
        enmascarable,
    )
    from crmcore.config import get_settings
    from crmcore.security.cifrado import enmascarar

    activo = bool(get_settings().masking_enabled)
    politica = _politica_por_rol(db) if activo else {}
    excepciones = _excepciones(db, principal.tenant_id, objeto) if activo else {}
    roles = frozenset(principal.roles) | (
        {"admin"} if principal.es_admin_plataforma else frozenset()
    )

    def _proyecta(fila: Any) -> dict[str, Any]:
        datos = fila.a_dict() if hasattr(fila, "a_dict") else dict(fila)
        # Las políticas ABAC de alcance «campos» (CRM-00.05.02.20) se evalúan
        # POR REGISTRO, no una vez: dependen de la fila —«el margen de las
        # oportunidades de otra unidad de negocio»—, así que no se pueden
        # resolver fuera del bucle como la política por sensibilidad.
        #
        # Se hace aunque el enmascarado global esté apagado: `MASKING_ENABLED`
        # gobierna la proyección por sensibilidad, que es una decisión de
        # despliegue; una política la ha escrito el cliente y apagarla desde el
        # `.env` sería saltarse su configuración desde la nuestra.
        por_politica = _ocultos_de_politica(db, objeto, datos)
        if not activo:
            return (
                {k: v for k, v in datos.items() if k not in por_politica} if por_politica else datos
            )
        salida: dict[str, Any] = {}
        retenidos: set[str] = set(por_politica)
        for campo, valor in datos.items():
            if campo in por_politica:
                continue
            nivel = _nivel_del_campo(campo, modelo, roles, politica, excepciones)
            if nivel == "claro" or valor is None:
                salida[campo] = valor
            elif nivel == "enmascarado":
                # Solo se enmascara lo que se puede enmascarar sin cambiar de
                # tipo. Ver `crmcore.authz.proyeccion.enmascarable`: hacerlo
                # sobre un número o una lista producía una cadena que rompía el
                # contrato y devolvía un 500.
                salida[campo] = enmascarar(valor) if enmascarable(modelo, campo, valor) else valor
            else:
                # Se anota para anunciarlo en la cabecera `X-Campos-Retenidos`.
                # Sin ese anuncio, el cliente no puede distinguir «este campo
                # está vacío» de «este campo no te lo doy», y esa diferencia
                # cambia lo que hace con él: rellenarlo o pedir permiso.
                retenidos.add(campo)
        anotar_retenidos(retenidos)
        return salida

    return _proyecta


def _ocultos_de_politica(db: Any, objeto: str, datos: dict[str, Any]) -> set[str]:
    """Campos que una política ABAC esconde en este registro concreto.

    Si evaluar falla **se esconde**, no se enseña: un error resolviendo una
    política que restringe no se puede resolver enseñando el campo. Como no se
    sabe cuáles tocaba esconder, se esconden todos los que alguna política
    controla para ese objeto — acotado, y sin enseñar nada que se estuviera
    negando. Es la regla contraria a la de compartición, y está razonada en
    `crmcore.authz.decision`.
    """
    from crmcore.authz.decision import campos_ocultos
    from crmcore.logging import get_logger

    try:
        return campos_ocultos(db, objeto=objeto, registro=datos)
    except Exception as exc:  # noqa: BLE001 — ante la duda, no se enseña
        get_logger(__name__).error("abac.fallo_al_ocultar", objeto=objeto, error=str(exc)[:300])
        try:
            from crmcore.authz.politicas import campos_gobernados
            from crmcore.tenancy.context import contexto_actual

            tid = contexto_actual().tenant_id
            return campos_gobernados(db, tid, objeto) if tid else set()
        except Exception:  # noqa: BLE001 — si ni eso se puede, no se sirve la ficha
            raise exc from None
