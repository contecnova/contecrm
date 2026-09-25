"""Una respuesta en flujo sale por trozos y en cuanto hay el primero.

Esta prueba existe porque **ninguna respuesta en flujo de todo el CRM llegó
nunca a su destino**, y sin un solo error: `ETagMiddleware` retenía el
`http.response.start` hasta conocer el cuerpo entero para poder añadirle la
cabecera, y el cuerpo de un `text/event-stream` no termina nunca. El chat en
vivo se quedaba colgado, el `EventSource` del navegador no llegaba a abrirse y
el gateway daba la conexión por muerta a los diez segundos.

Se prueba contra la pila ASGI de verdad —la aplicación con sus middlewares
montados— y mirando el ORDEN de los mensajes, porque el fallo no era del cuerpo
sino del momento: el contenido acababa llegando entero al final, así que
cualquier prueba que solo comprobara «qué llega» lo habría dado por bueno.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
from crmcore.http.etag import ETagMiddleware
from crmcore.http.middleware import IdempotenciaMiddleware
from fastapi import FastAPI
from fastapi.responses import StreamingResponse


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/flujo")
    async def flujo() -> StreamingResponse:
        async def gotear() -> AsyncIterator[str]:
            yield ": abierto\n\n"
            for i in range(3):
                await asyncio.sleep(0.05)
                yield f"event: mensaje\ndata: {i}\n\n"

        return StreamingResponse(gotear(), media_type="text/event-stream")

    @app.get("/objeto")
    async def objeto() -> dict[str, int]:
        return {"version": 7}

    app.add_middleware(IdempotenciaMiddleware)
    app.add_middleware(ETagMiddleware)
    return app


async def _cliente() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=_app()), base_url="http://prueba")


@pytest.mark.asyncio
async def test_el_flujo_empieza_a_salir_antes_de_terminarse() -> None:
    """Lo que hace útil un flujo: que lo que pasa ahora se vea ahora.

    Se comprueba con un plazo, y a propósito: el fallo era que la respuesta no
    empezaba NUNCA, así que una prueba sin plazo se habría colgado en vez de
    fallar. Con él, la regresión se ve como un fallo con su nombre.
    """
    salidos: list[dict] = []
    abierto = asyncio.Event()

    peticion_entregada = False

    async def recibir() -> dict:
        # La petición una vez y luego silencio. Starlette escucha el `receive`
        # en paralelo esperando un `http.disconnect`, y devolverle `http.request`
        # sin parar lo mete en un bucle que no avanza.
        nonlocal peticion_entregada
        if not peticion_entregada:
            peticion_entregada = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.Event().wait()
        raise AssertionError("inalcanzable")

    async def enviar(mensaje: dict) -> None:
        salidos.append(mensaje)
        if mensaje["type"] == "http.response.body" and mensaje.get("body"):
            abierto.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": "GET",
        "path": "/flujo",
        "raw_path": b"/flujo",
        "query_string": b"",
        "headers": [],
        "root_path": "",
        "scheme": "http",
        "client": ("127.0.0.1", 1234),
        "server": ("prueba", 80),
    }
    app = _app()
    tarea = asyncio.create_task(app(scope, recibir, enviar))
    try:
        await asyncio.wait_for(abierto.wait(), timeout=2.0)
    except TimeoutError:  # pragma: no cover — es la regresión que se vigila
        tarea.cancel()
        raise AssertionError("el flujo no soltó un solo byte: la respuesta se retiene")

    # En ese momento el flujo AÚN NO ha terminado —le quedan los tres mensajes—
    # y sin embargo el inicio y el saludo ya han salido.
    assert salidos[0]["type"] == "http.response.start"
    assert salidos[0]["status"] == 200
    assert salidos[1]["body"] == b": abierto\n\n"
    assert not tarea.done()

    await asyncio.wait_for(tarea, timeout=5.0)
    todo = b"".join(m.get("body", b"") for m in salidos)
    assert b"data: 0" in todo and b"data: 2" in todo


@pytest.mark.asyncio
async def test_el_etag_de_una_respuesta_normal_se_sigue_poniendo() -> None:
    """El arreglo no puede llevarse por delante para lo que existe el middleware."""
    cliente = await _cliente()
    async with cliente:
        respuesta = await cliente.get("/objeto")
    assert respuesta.headers.get("etag") == 'W/"7"'
