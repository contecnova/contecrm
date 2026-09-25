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

import asyncio
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
    """Reenvía la petición al servicio y devuelve su respuesta tal cual.

    **Quien decide si algo es un flujo es el SERVICIO, por lo que responde, no el
    cliente por lo que pide.** Parece un matiz y no lo es: la primera versión
    miraba el `Accept` de quien llamaba, y eso da las dos equivocaciones. Quien
    pedía un flujo en una ruta normal recibía una respuesta que nadie había
    leído, que salía como 500. Y quien llamaba a una ruta que transmite sin la
    cabecera —cualquier cliente que no sea un `EventSource`— se comía un 504 a
    los diez segundos en una ruta perfectamente sana.

    Así que se abre SIEMPRE en flujo y se decide al ver las cabeceras de la
    respuesta, que es cuando ya se sabe. Para lo que no transmite, abrir en flujo
    y leerlo entero a continuación es exactamente lo mismo que pedirlo entero.

    El plazo de lectura se pone con `wait_for` sobre esa lectura y no en el
    cliente HTTP: el plazo del cliente se fija al mandar la petición y ya no se
    puede quitar, y un flujo lo necesita quitado —el silencio entre dos eventos
    es lo normal y no una avería— mientras que una respuesta normal lo necesita
    puesto. Conectar sí lo lleva siempre, así que un servicio caído se sigue
    detectando igual de rápido.
    """
    destino = f"{url_base}{ruta}" + (f"?{query}" if query else "")
    limpias = {k: v for k, v in cabeceras.items() if k.lower() not in NO_REENVIAR}

    peticion = cliente.build_request(
        metodo,
        destino,
        content=cuerpo or None,
        headers={**limpias, **identidad},
        # `read=None` en la petición; el plazo de la lectura lo pone `wait_for`
        # más abajo, y solo cuando la respuesta no transmite.
        timeout=httpx.Timeout(timeout_s, read=None),
    )
    try:
        respuesta = await cliente.send(peticion, stream=True)
    except httpx.TimeoutException:
        logger.warning("gateway.timeout", destino=destino)
        raise TiempoAgotado("El servicio no ha respondido a tiempo", error_code="gateway.timeout")
    except httpx.HTTPError as exc:
        logger.error("gateway.servicio_inalcanzable", destino=destino, error=str(exc)[:200])
        raise NoDisponible(
            "El servicio no está disponible ahora mismo",
            error_code="gateway.servicio_caido",
        )

    if respuesta.headers.get("content-type", "").startswith("text/event-stream"):
        return respuesta

    try:
        await asyncio.wait_for(respuesta.aread(), timeout=timeout_s)
    except TimeoutError:
        await respuesta.aclose()
        logger.warning("gateway.timeout", destino=destino)
        raise TiempoAgotado("El servicio no ha respondido a tiempo", error_code="gateway.timeout")
    except httpx.HTTPError as exc:
        await respuesta.aclose()
        logger.error("gateway.servicio_inalcanzable", destino=destino, error=str(exc)[:200])
        raise NoDisponible(
            "El servicio no está disponible ahora mismo",
            error_code="gateway.servicio_caido",
        )
    return respuesta


def cabeceras_de_identidad(principal: Any, secreto: str) -> dict[str, str]:
    """Construye y firma las cabeceras de identidad interna."""
    from crmcore.http.deps import (
        H_ACTOR_REAL,
        H_PERMISOS,
        H_PLATAFORMA,
        H_ROLES,
        H_SCOPES,
        H_SESION,
        H_TENANT,
        H_TIPO,
        H_USER,
        firmar_cabeceras_internas,
    )

    valores = {
        H_TENANT: str(principal.tenant_id or ""),
        H_USER: str(principal.id or ""),
        # Persona o máquina. Los servicios de detrás deciden distinto: a una
        # credencial de máquina no se le aplica la compartición, porque
        # representa al tenant y no posee registros.
        H_TIPO: str(getattr(principal, "tipo", "") or ""),
        H_PERMISOS: ",".join(sorted(principal.permisos)),
        H_ROLES: ",".join(sorted(principal.roles)),
        H_SCOPES: ",".join(sorted(principal.scopes)),
        H_ACTOR_REAL: str(principal.actor_real_id or ""),
        H_PLATAFORMA: "1" if principal.es_admin_plataforma else "",
        H_SESION: str(principal.sesion_id or ""),
    }
    return firmar_cabeceras_internas(valores, secreto)
