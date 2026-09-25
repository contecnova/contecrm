"""El gateway reenvía un `text/event-stream` como flujo, no como respuesta.

Esta prueba existe porque el chat en vivo **nunca** funcionó por el gateway y
nadie se enteró: el reenvío leía la respuesta entera con un plazo de diez
segundos, que en un flujo abierto es un 504 garantizado. Y cuando se arregló,
el arreglo salía 500 en producción por un `TypeError` —`AsyncClient.send()` no
admite `timeout`— que ninguna prueba veía porque ninguna llamaba a la función.

Se prueba contra un `httpx.AsyncClient` de verdad con transporte simulado: el
fallo era precisamente de la firma del cliente HTTP, así que un doble de
`cliente` lo habría dejado pasar otra vez.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from services.gateway import proxy

SSE = b"data: uno\n\ndata: dos\n\n"


class _Flujo(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for trozo in _goteo():
            yield trozo


async def _goteo() -> AsyncIterator[bytes]:
    """Un flujo de verdad: los trozos salen de uno en uno, sin cuerpo completo."""
    for trozo in SSE.split(b"\n\n"):
        if trozo:
            yield trozo + b"\n\n"


def _cliente(recibidas: list[httpx.Request]) -> httpx.AsyncClient:
    def responder(peticion: httpx.Request) -> httpx.Response:
        recibidas.append(peticion)
        if peticion.url.path.endswith("/eventos"):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=_Flujo(),
            )
        return httpx.Response(200, json={"ok": True})

    return httpx.AsyncClient(transport=httpx.MockTransport(responder))


async def _reenviar(
    cliente: httpx.AsyncClient, accept: str, ruta: str = "/api/v1/chat/eventos"
) -> httpx.Response:
    return await proxy.reenviar(
        cliente,
        url_base="http://identity:8000",
        metodo="GET",
        ruta=ruta,
        query="",
        cabeceras={"accept": accept},
        cuerpo=b"",
        identidad={"x-crm-tenant": "t"},
        timeout_s=10.0,
    )


@pytest.mark.asyncio
async def test_un_sse_vuelve_abierto_y_se_lee_por_trozos() -> None:
    """Sin esto el chat en vivo da 504 o 500, que es lo que daba."""
    recibidas: list[httpx.Request] = []
    async with _cliente(recibidas) as cliente:
        respuesta = await _reenviar(cliente, "text/event-stream")

        assert respuesta.status_code == 200
        assert respuesta.headers["content-type"] == "text/event-stream"
        # Abierta: el cuerpo aún no se ha leído. Tocar `.content` ahora lanza.
        with pytest.raises(httpx.ResponseNotRead):
            _ = respuesta.content

        leido = b"".join([trozo async for trozo in respuesta.aiter_raw()])
        await respuesta.aclose()
    assert leido == SSE


@pytest.mark.asyncio
async def test_el_flujo_no_lleva_plazo_de_lectura() -> None:
    """El silencio entre dos eventos es lo normal en un flujo, no una avería.

    Conectar sí tiene plazo: un servicio caído se sigue detectando rápido.
    """
    recibidas: list[httpx.Request] = []
    async with _cliente(recibidas) as cliente:
        respuesta = await _reenviar(cliente, "text/event-stream")
        await respuesta.aclose()

    plazo = recibidas[-1].extensions.get("timeout") or {}
    assert plazo.get("read") is None
    assert plazo.get("connect") == 10.0


@pytest.mark.asyncio
async def test_lo_que_no_es_flujo_sigue_leyendose_entero() -> None:
    recibidas: list[httpx.Request] = []
    async with _cliente(recibidas) as cliente:
        respuesta = await _reenviar(cliente, "application/json", "/api/v1/chat/sin-leer")
        assert respuesta.json() == {"ok": True}


@pytest.mark.asyncio
async def test_pedir_flujo_donde_no_lo_hay_devuelve_la_respuesta_leida() -> None:
    """Pedirlo no obliga a darlo, y la respuesta normal hay que leerla.

    Si se deja abierta, quien la use después se encuentra un `ResponseNotRead`
    que sale como 500 — en CUALQUIER ruta llamada con ese `Accept`, no solo en
    las que transmiten. Y en las que transmiten también pasa: un error se
    devuelve en JSON aunque la ruta sea un flujo.
    """
    recibidas: list[httpx.Request] = []
    async with _cliente(recibidas) as cliente:
        # Quien decide si transmite es el SERVICIO, por su ruta, no el `Accept`
        # del cliente: aquí se pide un flujo en una ruta que responde JSON.
        respuesta = await _reenviar(
            cliente, "text/event-stream, application/json", "/api/v1/chat/sin-leer"
        )
        assert respuesta.json() == {"ok": True}
