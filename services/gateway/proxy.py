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

    # Un FLUJO no se puede acumular ni cronometrar como una respuesta normal.
    #
    # `chat/eventos` es `text/event-stream`: se queda abierto mandando lo que va
    # pasando, por definición. Reenviarlo como todo lo demás —leer la respuesta
    # entera con un plazo de diez segundos— da **504 siempre**, y el
    # `EventSource` del chat nunca ha recibido un solo mensaje por esta vía.
    #
    # Se reconoce por lo que PIDE el cliente y no por la ruta: una lista de
    # rutas que transmiten se queda corta con la siguiente que se añada, y el
    # `Accept` lo manda el navegador precisamente para esto.
    if "text/event-stream" in (limpias.get("accept") or limpias.get("Accept") or ""):
        return await _reenviar_flujo(cliente, destino, metodo, limpias, identidad, cuerpo)

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


async def _reenviar_flujo(
    cliente: httpx.AsyncClient,
    destino: str,
    metodo: str,
    cabeceras: dict[str, str],
    identidad: dict[str, str],
    cuerpo: bytes,
) -> Any:
    """Abre el flujo y lo deja abierto, sin plazo de lectura.

    `timeout=None` solo para la LECTURA: conectar sigue teniendo su plazo, así
    que un servicio caído se detecta igual de rápido. Lo que no se cronometra es
    el silencio entre dos eventos, que en un flujo es lo normal y no una avería.
    """
    # El plazo va en la PETICIÓN, no en `send()`: `AsyncClient.send()` no admite
    # `timeout` y lo rechaza con un `TypeError` que sale como 500. Es
    # `build_request` quien lo guarda en la petición.
    peticion = cliente.build_request(
        metodo,
        destino,
        content=cuerpo or None,
        headers={**cabeceras, **identidad},
        timeout=httpx.Timeout(10.0, read=None),
    )
    try:
        respuesta = await cliente.send(peticion, stream=True)
    except httpx.HTTPError as exc:
        logger.error("gateway.flujo_inalcanzable", destino=destino, error=str(exc)[:200])
        raise NoDisponible(
            "El servicio no está disponible ahora mismo", error_code="gateway.servicio_caido"
        ) from exc

    # Pedir un flujo no obliga al servicio a darlo. Un `Accept:
    # text/event-stream` en una ruta normal —o en un error, que sale en JSON
    # aunque la ruta transmita— devuelve una respuesta corriente, y esa hay que
    # LEERLA: dejarla abierta hacía que quien la usara luego se encontrara un
    # `ResponseNotRead`, que salía como 500. Pasaba en cualquier ruta llamada con
    # ese `Accept`, no solo en las que transmiten.
    if not respuesta.headers.get("content-type", "").startswith("text/event-stream"):
        await respuesta.aread()
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
