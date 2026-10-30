"""El gateway reenvía un `text/event-stream` como flujo, no como respuesta.

Esta prueba existe porque el chat en vivo **nunca** funcionó por el gateway y
nadie se enteró: el reenvío leía la respuesta entera con un plazo de diez
segundos, que en un flujo abierto es un 504 garantizado. Y cuando se arregló,
el arreglo salía 500 en producción por un `TypeError` —`AsyncClient.send()` no
admite `timeout`— que ninguna prueba veía porque ninguna llamaba a la función.

Lo que se fija aquí es **quién decide que algo es un flujo**: el servicio, por lo
que responde, y no el cliente por lo que pide. Mirar el `Accept` de quien llama
daba las dos equivocaciones a la vez —500 al pedir un flujo donde no lo hay, y
504 al llamar sin la cabecera a una ruta que sí transmite—.

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
async def test_una_ruta_que_transmite_transmite_aunque_no_se_pida() -> None:
    """Sin la cabecera, esa ruta daba 504 en diez segundos estando sana.

    Le pasaba a cualquier cliente que no sea un `EventSource` — incluido el
    barrido que abre todas las rutas para ver cuál falla.
    """
    recibidas: list[httpx.Request] = []
    async with _cliente(recibidas) as cliente:
        respuesta = await _reenviar(cliente, "application/json")
        assert respuesta.headers["content-type"] == "text/event-stream"
        with pytest.raises(httpx.ResponseNotRead):
            _ = respuesta.content
        await respuesta.aclose()


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


# ── El proxy no puede declarar lo que no conoce (CRM-00.02.04.01) ────────


def test_el_gateway_no_rechaza_los_parametros_de_las_rutas_de_detras() -> None:
    """**El tablero de ventas salía entero en rojo, y lo contó quien lo usaba.**

    La comprobación de parámetros desconocidos es una dependencia GLOBAL de
    cada aplicación, y eso incluye el catch-all del gateway. Como ahí el único
    parámetro declarado es el camino, cualquier `?limite=200` que pasara por el
    gateway —y por el gateway pasa todo— se rechazaba con «esta operación no
    mira «limite»» y una lista de admitidos de tres elementos.

    No se quita la comprobación: la hace el servicio de destino, que es el
    único que sabe qué mira cada una de sus rutas. Aquí sería imposible por
    construcción —tendría que conocer las dos mil quinientas operaciones de los
    trece servicios— y fingir que la hace es peor que no hacerla.
    """
    import importlib

    from crmcore.http import superficie as sup
    from crmcore.http.parametros import motivo_de_apertura

    app = importlib.import_module("services.gateway.main").app
    proxies = [
        r
        for prefijo, r in sup._rutas_planas(app)
        if "{ruta:path}" in f"{prefijo}{getattr(r, 'path', '')}"
    ]
    assert proxies, "no se ha encontrado el proxy: esta prueba no está mirando nada"
    for ruta in proxies:
        motivo = motivo_de_apertura(getattr(ruta, "endpoint", None))
        assert motivo, (
            "el proxy del gateway tiene que estar marcado como de parámetros "
            "abiertos: si no, rechaza cualquier filtro, orden o página de "
            "cualquier pantalla del producto"
        )
        # Y con un motivo de verdad: una marca sin motivo se copia a la
        # siguiente ruta que dé guerra, y la comprobación deja de comprobar.
        assert len(motivo) > 40, motivo


def test_las_rutas_propias_del_gateway_si_declaran_lo_que_miran() -> None:
    """La exención es SOLO del proxy.

    Si valiera para todo el gateway, sus propias rutas —la superficie, el
    registro de servicios— volverían a tragarse en silencio un parámetro mal
    escrito, que es lo que convierte un filtro en «todas las filas».
    """
    import importlib

    from crmcore.http import superficie as sup
    from crmcore.http.parametros import motivo_de_apertura

    app = importlib.import_module("services.gateway.main").app
    abiertas = [
        f"{prefijo}{getattr(r, 'path', '')}"
        for prefijo, r in sup._rutas_planas(app)
        if motivo_de_apertura(getattr(r, "endpoint", None))
    ]
    assert abiertas == ["/api/{ruta:path}"], abiertas


# ── Quién está frenado ahora mismo (CRM-00.01.06.05) ────────────────────
#
# El freno adaptativo se aplicaba y NO se podía ver: `anotar`, `evaluar` y
# `frenar` corren en el proxy de cada petición, y no había ninguna ruta que
# dijera a quién le han bajado la cuota. Un cliente podía llevar horas a un
# cuarto de la suya, con sus integraciones reintentando más fuerte porque les
# llega un 429, y para averiguarlo había que leer los registros.


def test_los_frenados_se_pueden_ver_y_dicen_por_que() -> None:
    from services.gateway import anomalias

    anomalias.reiniciar()
    try:
        # Un tenant tranquilo y otro que se dispara.
        for _ in range(anomalias.MINIMO_VENTANAS):
            anomalias.anotar("aaa-tranquilo", 10)
            anomalias.anotar("zzz-disparado", 10)
        anomalias.anotar("zzz-disparado", 10_000)
        veredicto = anomalias.evaluar("zzz-disparado")
        anomalias.frenar("zzz-disparado", motivo=veredicto["porque"])

        salida = anomalias.frenados()
        porId = {f["tenant_id"]: f for f in salida["observados"]}
        assert porId["zzz-disparado"]["frenado"] is True
        # El factor es lo que de verdad le han bajado: sin él, «frenado» no
        # dice si está al 75 % o al 25 %.
        assert porId["zzz-disparado"]["factor_de_cuota"] < 1.0
        assert porId["zzz-disparado"]["motivo"], "un freno sin motivo hace reintentar más fuerte"
        assert porId["aaa-tranquilo"]["frenado"] is False
        assert salida["frenados"] == 1
        # Y el frenado va PRIMERO, aunque alfabéticamente fuera el último:
        # con los nombres al revés esta comprobación pasaba sin mirar nada.
        assert salida["observados"][0]["tenant_id"] == "zzz-disparado"
    finally:
        anomalias.reiniciar()


def test_dice_cuantas_ventanas_lleva_observadas_cada_uno() -> None:
    """Por debajo del mínimo no se evalúa a nadie, así que uno disparado puede
    no salir frenado todavía — y eso, sin decirlo, parece un fallo del freno."""
    from services.gateway import anomalias

    anomalias.reiniciar()
    try:
        anomalias.anotar("nuevo", 10_000)
        salida = anomalias.frenados()
        fila = salida["observados"][0]
        assert fila["frenado"] is False
        assert fila["ventanas_observadas"] == 1
        assert salida["minimo_ventanas"] == anomalias.MINIMO_VENTANAS
    finally:
        anomalias.reiniciar()


def test_dice_que_es_lo_que_ve_este_proceso() -> None:
    """Lo observado vive en memoria: con varias réplicas cada una ve su parte,
    y una lista corta se leería como «no hay nadie frenado»."""
    from services.gateway import anomalias

    anomalias.reiniciar()
    salida = anomalias.frenados()
    assert salida["observados"] == []
    assert salida["porque_solo_estos"], "no avisa de que es la vista de un proceso"
