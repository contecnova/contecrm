"""Reenvío de peticiones al servicio que toca, con la identidad propagada.

La identidad va en cabeceras **firmadas** (`crmcore.http.deps`), no en el token
original. Dos razones:

  * El servicio no tiene que volver a validar el JWT ni conocer la clave de
    firma de sesiones, lo que reduce la superficie: solo el gateway y el
    servicio de identidad manejan esa clave.
  * Los permisos ya vienen resueltos, así que un servicio no necesita consultar
    al de identidad en cada petición — y por tanto una caída de identidad no
    tumba al resto.

La contrapartida, dicha claramente: si un servicio interno fuera alcanzable
desde fuera, cualquiera podría mandarle esas cabeceras. La firma lo impide sin
el secreto, pero el despliegue **debe** mantener los servicios en red interna.
Está en el manual de operación y no es opcional.
"""

from __future__ import annotations

from typing import Any

import httpx
from crmcore.errors import NoDisponible, TiempoAgotado
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Cabeceras que NO se reenvían. `host` porque lo reescribe el cliente HTTP;
# `content-length` porque lo recalcula; las de identidad propias porque las
# generamos nosotros firmadas y aceptar las entrantes sería el agujero que la
# firma viene a cerrar.
NO_REENVIAR = frozenset(
    {
        "host",
        "content-length",
        "connection",
        "keep-alive",
        "transfer-encoding",
        "upgrade",
        "x-crm-tenant",
        "x-crm-user",
        "x-crm-permisos",
        "x-crm-roles",
        "x-crm-scopes",
        "x-crm-actor-real",
        "x-crm-plataforma",
        "x-crm-firma",
        "x-crm-momento",
    }
)


async def reenviar(
    cliente: httpx.AsyncClient,
    *,
    url_base: str,
    metodo: str,
    ruta: str,
    query: str,
    cabeceras: dict[str, str],
    cuerpo: bytes,
    identidad: dict[str, str],
    timeout_s: float,
) -> httpx.Response:
    """Reenvía la petición al servicio y devuelve su respuesta tal cual."""
    destino = f"{url_base}{ruta}" + (f"?{query}" if query else "")
    limpias = {k: v for k, v in cabeceras.items() if k.lower() not in NO_REENVIAR}

    try:
        return await cliente.request(
            metodo,
            destino,
            content=cuerpo or None,
            headers={**limpias, **identidad},
            timeout=timeout_s,
        )
    except httpx.TimeoutException:
        logger.warning("gateway.timeout", destino=destino)
        raise TiempoAgotado("El servicio no ha respondido a tiempo", error_code="gateway.timeout")
    except httpx.HTTPError as exc:
        logger.error("gateway.servicio_inalcanzable", destino=destino, error=str(exc)[:200])
        raise NoDisponible(
            "El servicio no está disponible ahora mismo",
            error_code="gateway.servicio_caido",
        )


def cabeceras_de_identidad(principal: Any, secreto: str) -> dict[str, str]:
    """Construye y firma las cabeceras de identidad interna."""
    from crmcore.http.deps import (
        H_ACTOR_REAL,
        H_PERMISOS,
        H_PLATAFORMA,
        H_ROLES,
        H_SCOPES,
        H_TENANT,
        H_USER,
        firmar_cabeceras_internas,
    )

    valores = {
        H_TENANT: str(principal.tenant_id or ""),
        H_USER: str(principal.id or ""),
        H_PERMISOS: ",".join(sorted(principal.permisos)),
        H_ROLES: ",".join(sorted(principal.roles)),
        H_SCOPES: ",".join(sorted(principal.scopes)),
        H_ACTOR_REAL: str(principal.actor_real_id or ""),
        H_PLATAFORMA: "1" if principal.es_admin_plataforma else "",
    }
    return firmar_cabeceras_internas(valores, secreto)
