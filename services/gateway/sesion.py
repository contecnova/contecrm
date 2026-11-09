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


def _nombre_refresco_suplantacion() -> str:
    """El refresco de la sesión de soporte (CRM-00.01.02.06).

    Va **aparte** del propio y en la misma ruta: el refresco propio no se toca
    mientras se está dentro como otra persona —es lo que permite volver sin
    escribir la contraseña— y el de la suplantación es lo que la mantiene viva
    más allá de los quince minutos del token de acceso. Si fuera el mismo, o
    volver costaría la contraseña o entrar como otro borraría la sesión propia.
    """
    return f"{get_settings().sesion_cookie_nombre}_suplantacion_refresco"


def poner_refresco_suplantacion(respuesta: Response, token: str, *, segundos: int) -> None:
    s = get_settings()
    respuesta.set_cookie(
        _nombre_refresco_suplantacion(),
        token,
        max_age=segundos,
        httponly=True,
        secure=s.sesion_cookie_secure,
        samesite=s.sesion_cookie_samesite,
        path=RUTA_REFRESCO,
    )


def quitar_refresco_suplantacion(respuesta: Response) -> None:
    s = get_settings()
    respuesta.delete_cookie(
        _nombre_refresco_suplantacion(),
        path=RUTA_REFRESCO,
        httponly=True,
        secure=s.sesion_cookie_secure,
        samesite=s.sesion_cookie_samesite,
    )


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
    """Borra las cookies de sesión. Dejar la de refresco sería no cerrar la
    sesión, y dejar la de soporte haría que la siguiente renovación volviera a
    meter a quien sale dentro de la cuenta de otra persona."""
    s = get_settings()
    for nombre, camino in (
        (s.sesion_cookie_nombre, "/api"),
        (_nombre_refresco(), RUTA_REFRESCO),
        (_nombre_refresco_suplantacion(), RUTA_REFRESCO),
    ):
        respuesta.delete_cookie(
            nombre,
            path=camino,
            httponly=True,
            secure=s.sesion_cookie_secure,
            samesite=s.sesion_cookie_samesite,
        )


async def _renovar_suplantacion(
    cliente: Any, destinos: dict[str, Any], timeout_s: float, refresco: str, respuesta: Response
) -> dict[str, Any] | None:
    """Renueva la sesión de soporte. `None` si ya no se puede (caducó o se
    revocó): entonces se vuelve a la propia."""
    s = get_settings()
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
        return None
    cuerpo = salida.json()
    nuevo = str(cuerpo.get("access_token") or "")
    if not nuevo:
        return None
    poner_cookie(respuesta, nuevo, segundos=s.access_token_minutos * 60)
    rotado = str(cuerpo.get("refresh_token") or "")
    if rotado:
        poner_refresco_suplantacion(respuesta, rotado, segundos=s.access_token_minutos * 60 * 8)
    return {"caduca_en_s": s.access_token_minutos * 60, "suplantando": True}


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
        # **Si hay una sesión de soporte abierta, se renueva ÉSA** y no la
        # propia (CRM-00.01.02.06). Renovar la propia sacaría a quien está
        # dentro como otra persona sin decírselo, a mitad de lo que estuviera
        # mirando, y la de soporte se quedaría viva sin nadie usándola.
        de_soporte = request.cookies.get(_nombre_refresco_suplantacion())
        if de_soporte:
            renovada = await _renovar_suplantacion(
                cliente, destinos, timeout_s, de_soporte, respuesta
            )
            if renovada is not None:
                return renovada
            # Caducada o revocada: se vuelve a la sesión propia, que es lo que
            # tiene que pasar al acabarse el tiempo de soporte, y se dice.
            quitar_refresco_suplantacion(respuesta)
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
        return {
            "caduca_en_s": s.access_token_minutos * 60,
            # Para que la interfaz recargue: la franja de soporte ya no es
            # verdad y lo que hay en pantalla es de la otra persona.
            "suplantacion_terminada": bool(de_soporte),
        }

    @router_sesion.post(
        "/suplantar",
        response_model=dict,
        summary="Entrar como otra persona, por soporte (CRM-00.01.02.06)",
        description=(
            "El navegador no puede quedarse los tokens de la suplantación —es "
            "la misma razón por la que no se queda los propios—, así que el "
            "gateway los pide a identidad y los pone en la cookie. **El "
            "refresco propio no se toca**: es lo que permite volver a la "
            "sesión de uno sin escribir la contraseña.\n\n"
            "Identidad decide si se puede: sólo personal de plataforma, con "
            "motivo escrito y reverificado hace poco. La empresa es la que se "
            "está mirando (`X-CRM-Tenant-Mirado`)."
        ),
    )
    async def suplantar(datos: dict[str, Any], request: Request, respuesta: Response) -> Any:
        from crmcore.http.deps import H_TENANT_MIRADO

        s = get_settings()
        cliente, destinos, timeout_s = obtener()
        propio = request.cookies.get(s.sesion_cookie_nombre)
        if not propio:
            raise NoAutenticado("No hay sesión abierta", error_code="gateway.sin_sesion")
        cabeceras = {"Authorization": f"Bearer {propio}"}
        mirado = request.headers.get(H_TENANT_MIRADO)
        if mirado:
            cabeceras[H_TENANT_MIRADO] = mirado
        try:
            salida = await cliente.post(
                f"{_identidad(destinos)}/api/v1/sesiones/suplantar",
                json={"usuario_id": datos.get("usuario_id"), "motivo": datos.get("motivo")},
                headers=cabeceras,
                timeout=timeout_s,
            )
        except httpx.HTTPError as exc:
            raise NoDisponible(
                "No se ha podido contactar con el servicio de identidad",
                error_code="gateway.identidad_no_responde",
            ) from exc
        if salida.status_code != 200:
            # Lo que diga identidad, tal cual: «vuelve a verificarte», «falta
            # el motivo», «esa persona no está en esta empresa».
            return Response(
                content=salida.content,
                status_code=salida.status_code,
                media_type=salida.headers.get("content-type", "application/json"),
            )
        cuerpo = salida.json()
        token = str(cuerpo.get("access_token") or "")
        if not token:
            raise NoAutenticado(
                "Identidad no ha devuelto un token de acceso", error_code="gateway.sin_token"
            )
        poner_cookie(respuesta, token, segundos=s.access_token_minutos * 60)
        refresco = str(cuerpo.get("refresh_token") or "")
        if refresco:
            # Vive lo que la sesión de soporte y no catorce días: identidad la
            # corta antes, y una cookie que dura más que la sesión que guarda
            # sólo sirve para intentar renovar algo que ya no existe.
            poner_refresco_suplantacion(
                respuesta, refresco, segundos=s.access_token_minutos * 60 * 8
            )
        logger.warning("gateway.suplantacion_abierta")
        return {"caduca_en_s": s.access_token_minutos * 60}

    @router_sesion.post(
        "/volver",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Salir de la suplantación y volver a la sesión propia",
        description=(
            "Cierra en identidad la sesión de soporte —no basta con olvidarla: "
            "seguiría viva hasta caducar— y borra sus cookies. La sesión propia "
            "se recupera con `/sesion/renovar`, que es la única ruta a la que "
            "el navegador manda el refresco propio."
        ),
    )
    async def volver(request: Request) -> Response:
        s = get_settings()
        cliente, destinos, timeout_s = obtener()
        token = request.cookies.get(s.sesion_cookie_nombre)
        if not token:
            # Sin sesión no hay de qué volver, y contestar 204 a quien no ha
            # entrado le diría que ha hecho algo.
            raise NoAutenticado("No hay sesión abierta", error_code="gateway.sin_sesion")
        try:
            yo = await cliente.get(
                f"{_identidad(destinos)}/api/v1/auth/me",
                headers={"Authorization": f"Bearer {token}"},
                timeout=timeout_s,
            )
            # Sólo se cierra si ES una suplantación. Sin esto, «volver»
            # pulsado por error en la sesión propia la cerraría.
            if yo.status_code == 200 and yo.json().get("suplantado_por"):
                await cliente.post(
                    f"{_identidad(destinos)}/api/v1/auth/logout",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=timeout_s,
                )
            elif yo.status_code == 200:
                from crmcore.errors import Conflicto

                raise Conflicto(
                    "No estás dentro como otra persona",
                    error_code="gateway.sin_suplantacion",
                )
        except httpx.HTTPError:
            # La cookie se borra igual: quedarse dentro como otra persona
            # porque identidad no responde es el peor resultado posible.
            logger.error("gateway.volver_sin_identidad")
        salida = Response(status_code=status.HTTP_204_NO_CONTENT)
        salida.delete_cookie(
            s.sesion_cookie_nombre,
            path="/api",
            httponly=True,
            secure=s.sesion_cookie_secure,
            samesite=s.sesion_cookie_samesite,
        )
        quitar_refresco_suplantacion(salida)
        logger.info("gateway.suplantacion_cerrada")
        return salida

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
