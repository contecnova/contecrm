"""La sesión del navegador: cookie `HttpOnly` en vez de token en el cliente.

`identity` devuelve los tokens en el cuerpo, que es lo correcto para una
integración: un servicio que llama a la API guarda su token donde quiera. Para
un **navegador** no lo es. Si el token llega al cliente, la aplicación tiene que
guardarlo en algún sitio, y todos los sitios que sobreviven a una recarga los
puede leer un script inyectado. Un XSS deja entonces de ser un susto y pasa a
ser una sesión robada.

Así que el gateway —lo único con lo que habla un navegador— hace de puente:
recibe las credenciales, pide los tokens a `identity`, y devuelve una **cookie**
`HttpOnly` que ningún script lee. El cuerpo de la respuesta **no lleva los
tokens**: devolverlos «por comodidad» anularía todo esto, porque alguien los
guardaría.

Esto no le quita nada a nadie: una integración sigue llamando a
`/api/v1/auth/login` a través del proxy normal con su `Authorization`, y recibe
sus tokens como siempre. Lo que cambia es solo el camino del navegador.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from crmcore.config import get_settings
from crmcore.errors import NoAutenticado, NoDisponible
from crmcore.logging import get_logger
from fastapi import APIRouter, Request, Response, status

logger = get_logger(__name__)

router_sesion = APIRouter(prefix="/sesion", tags=["gateway"])


def _identidad(destinos: dict[str, Any]) -> str:
    destino = destinos.get("identity")
    if destino is None:
        raise NoDisponible(
            "El servicio de identidad no está desplegado en esta instalación",
            error_code="gateway.servicio_no_desplegado",
            detalle={"servicio": "identity"},
        )
    return destino.url_base


# Camino de la cookie de refresco. Solo se manda a la ruta que la usa: una
# cookie de refresco que viaja en cada petición de la API multiplica por mil las
# ocasiones de que se filtre, y solo hace falta en una.
RUTA_REFRESCO = "/api/v1/sesion/renovar"


def _nombre_refresco() -> str:
    return f"{get_settings().sesion_cookie_nombre}_refresco"


def poner_refresco(respuesta: Response, token: str, *, segundos: int) -> None:
    """Guarda el token de refresco, acotado a la ruta que lo canjea."""
    s = get_settings()
    respuesta.set_cookie(
        _nombre_refresco(),
        token,
        max_age=segundos,
        httponly=True,
        secure=s.sesion_cookie_secure,
        samesite=s.sesion_cookie_samesite,
        path=RUTA_REFRESCO,
    )


def poner_cookie(respuesta: Response, token: str, *, segundos: int) -> None:
    """Deja la sesión en una cookie que el navegador no puede leer.

    Las cuatro propiedades juntas, y ninguna es decorativa: `HttpOnly` la
    esconde de los scripts, `Secure` impide que viaje en claro, `SameSite` corta
    el envío en peticiones cruzadas de escritura y `Path` la acota a la API.
    Quitar cualquiera deshace una parte distinta de la protección.
    """
    s = get_settings()
    respuesta.set_cookie(
        s.sesion_cookie_nombre,
        token,
        max_age=segundos,
        httponly=True,
        secure=s.sesion_cookie_secure,
        samesite=s.sesion_cookie_samesite,
        path="/api",
    )


def quitar_cookie(respuesta: Response) -> None:
    """Borra las DOS cookies. Dejar la de refresco sería no cerrar la sesión."""
    s = get_settings()
    for nombre, camino in ((s.sesion_cookie_nombre, "/api"), (_nombre_refresco(), RUTA_REFRESCO)):
        respuesta.delete_cookie(
            nombre,
            path=camino,
            httponly=True,
            secure=s.sesion_cookie_secure,
            samesite=s.sesion_cookie_samesite,
        )


def crear_router_sesion(obtener: Callable[[], tuple[Any, dict[str, Any], float]]) -> APIRouter:
    """Router de sesión de navegador.

    Recibe un **accesor** y no el cliente: el cliente HTTP y la tabla de
    destinos se crean en el arranque, después de que los routers se monten.
    Pasarlos aquí capturaría los valores de antes de arrancar —`None` y un
    diccionario vacío— y todas las llamadas fallarían con «el gateway aún no ha
    arrancado».
    """

    @router_sesion.post(
        "/entrar",
        response_model=dict,
        summary="Entrar desde un navegador",
        description=(
            "Pide los tokens a identidad y los devuelve en una cookie "
            "`HttpOnly`. **La respuesta no lleva el token**: devolverlo por "
            "comodidad haría que alguien lo guardara donde un script lo lee, "
            "que es exactamente lo que esta ruta existe para evitar.\n\n"
            "Una integración no usa esto: llama a `/api/v1/auth/login` y recibe "
            "sus tokens como siempre."
        ),
    )
    async def entrar(datos: dict[str, Any], respuesta: Response) -> Any:
        s = get_settings()
        cliente, destinos, timeout_s = obtener()
        # Con passkey se entra por otra puerta, y la cookie la pone la misma:
        # el navegador no puede quedarse el token por su cuenta, y tener dos
        # sitios que abren sesión acabaría con uno de los dos haciéndolo mal.
        con_llave = bool(datos.get("passkey"))
        destino = "/api/v1/auth/passkeys/entrar/confirmar" if con_llave else "/api/v1/auth/login"
        cuerpo = (
            {"tenant": datos.get("tenant", ""), "respuesta": datos.get("passkey")}
            if con_llave
            else datos
        )
        try:
            salida = await cliente.post(
                f"{_identidad(destinos)}{destino}",
                json=cuerpo,
                timeout=timeout_s,
            )
        except httpx.HTTPError as exc:
            raise NoDisponible(
                "No se ha podido contactar con el servicio de identidad",
                error_code="gateway.identidad_no_responde",
            ) from exc

        if salida.status_code != 200:
            # Se devuelve tal cual lo que diga identidad: inventar aquí un
            # mensaje propio haría que el front enseñara una cosa por la API y
            # otra por el navegador para el mismo fallo.
            return Response(
                content=salida.content,
                status_code=salida.status_code,
                media_type=salida.headers.get("content-type", "application/json"),
            )

        cuerpo = salida.json()
        token = str(cuerpo.get("access_token") or "")
        if not token:
            raise NoAutenticado(
                "Identidad no ha devuelto un token de acceso",
                error_code="gateway.sin_token",
            )
        poner_cookie(respuesta, token, segundos=s.access_token_minutos * 60)
        refresco = str(cuerpo.get("refresh_token") or "")
        if refresco:
            # Sin esto, la sesión del navegador dura lo que dure el token de
            # acceso —quince minutos— y no hay forma de renovarla sin volver a
            # pedir la contraseña.
            poner_refresco(respuesta, refresco, segundos=s.refresh_token_dias * 86400)
        logger.info("gateway.sesion_abierta")
        # Se devuelve cuándo caduca para que la interfaz pueda renovar ANTES de
        # que expire, en vez de descubrirlo con un 401 en mitad de un formulario.
        return {"caduca_en_s": s.access_token_minutos * 60}

    @router_sesion.post(
        "/renovar",
        response_model=dict,
        summary="Renovar la sesión antes de que caduque",
        description=(
            "El token de acceso dura poco a propósito: su tiempo de vida **es** "
            "la ventana de exposición si alguien lo copia. Esto lo cambia por "
            "uno nuevo sin que la persona vuelva a escribir la contraseña.\n\n"
            "Se llama **antes** de que caduque, no después: descubrirlo con un "
            "401 en mitad de un formulario pierde lo que se estaba escribiendo."
        ),
    )
    async def renovar(request: Request, respuesta: Response) -> Any:
        s = get_settings()
        cliente, destinos, timeout_s = obtener()
        refresco = request.cookies.get(_nombre_refresco())
        if not refresco:
            raise NoAutenticado(
                "No hay sesión de navegador que renovar",
                error_code="gateway.sin_sesion",
            )
        try:
            salida = await cliente.post(
                f"{_identidad(destinos)}/api/v1/auth/refresh",
                json={"refresh_token": refresco},
                timeout=timeout_s,
            )
        except httpx.HTTPError as exc:
            raise NoDisponible(
                "No se ha podido contactar con el servicio de identidad",
                error_code="gateway.identidad_no_responde",
            ) from exc

        if salida.status_code != 200:
            # Una sesión que no se puede renovar se cierra: dejar la cookie
            # vieja haría que la interfaz siguiera creyéndose dentro hasta el
            # siguiente 401, y ese 401 llega en mitad de lo que se esté haciendo.
            fuera = Response(content=salida.content, status_code=salida.status_code)
            quitar_cookie(fuera)
            return fuera

        cuerpo = salida.json()
        nuevo = str(cuerpo.get("access_token") or "")
        if not nuevo:
            raise NoAutenticado(
                "Identidad no ha devuelto un token nuevo", error_code="gateway.sin_token"
            )
        poner_cookie(respuesta, nuevo, segundos=s.access_token_minutos * 60)
        # El refresco ROTA en cada uso: identidad devuelve uno nuevo y el
        # anterior queda quemado. Guardar el viejo haría que el siguiente
        # intento revocara todas las sesiones del usuario, que es lo que pasa al
        # presentar un refresco ya rotado.
        rotado = str(cuerpo.get("refresh_token") or "")
        if rotado:
            poner_refresco(respuesta, rotado, segundos=s.refresh_token_dias * 86400)
        return {"caduca_en_s": s.access_token_minutos * 60}

    @router_sesion.post(
        "/salir",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Cerrar la sesión del navegador",
        description=(
            "Borra la cookie y revoca la sesión en identidad. Borrar solo la "
            "cookie dejaría el token vivo hasta que caducara: quien lo hubiera "
            "copiado seguiría dentro."
        ),
    )
    async def salir(request: Request) -> Response:
        s = get_settings()
        cliente, destinos, timeout_s = obtener()
        token = request.cookies.get(s.sesion_cookie_nombre)
        if token:
            try:
                await cliente.post(
                    f"{_identidad(destinos)}/api/v1/auth/logout",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=timeout_s,
                )
            except httpx.HTTPError:
                # La cookie se borra igual: dejar al usuario dentro porque
                # identidad no responde es el peor resultado posible de pulsar
                # «cerrar sesión».
                logger.error("gateway.logout_sin_identidad")
        salida = Response(status_code=status.HTTP_204_NO_CONTENT)
        quitar_cookie(salida)
        return salida

    return router_sesion
