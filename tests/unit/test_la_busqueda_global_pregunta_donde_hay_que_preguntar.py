"""La búsqueda global devolvía cero resultados siempre (CRM-00.02.01).

El gateway compone la búsqueda preguntando a cada servicio por su índice. Le
preguntaba a `…/api/v1/buscar`, y cada servicio publica la suya en
`…/api/v1/{servicio}/buscar` —como la papelera y la retención, porque varios
publican la misma ruta y sin ese tramo no habría a cuál mandarla—.

Resultado, medido el 27-10-2026 contra la pila viva: los dos servicios con
índice contestaban **404**, los dos se contaban como caídos, y
`GET /api/v1/buscar?q=…` devolvía `{"total": 0, "resultados": []}` **siempre**.
No fallaba: el propio diseño dice que un servicio que no responde no tumba la
búsqueda, así que el fallo salía como «no hay resultados» con un aviso en el
registro que no mira nadie. Y el manual de usuario promete que la búsqueda mira
a la vez en cuentas, contactos, oportunidades, casos y documentos.

Por qué no lo cazaba nada: la ruta existe, contesta 200 y devuelve la forma
correcta. Lo único que distingue «no hay nada» de «no he sabido preguntar» es
a QUÉ se pregunta, y eso sólo se ve mirando la petición que sale.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest


class _Peticion:
    """La petición que llega del navegador: con su cookie y sin `authorization`."""

    headers: dict[str, str] = {"cookie": "sesion=loquesea"}


def _quien_llama() -> Any:
    """Quien pregunta, como lo monta el gateway tras validar la sesión."""
    from uuid import uuid4

    from crmcore.http.deps import Principal

    return Principal(
        id=uuid4(),
        tenant_id=uuid4(),
        tipo="usuario",
        roles=frozenset({"admin"}),
        permisos=frozenset({"*"}),
    )


def _gateway(preguntadas: list[str], sin_identidad: list[str] | None = None) -> Any:
    """Un gateway con dos servicios de mentira que sí tienen índice.

    **El doble EXIGE identidad**, como el servicio de verdad. Sin eso esta
    prueba no veía el segundo fallo de esta misma ruta: el gateway construía
    las cabeceras colando las `x-*` de la petición entrante, y la sesión del
    navegador es una **cookie** —no hay nada que colar—, así que los dos
    servicios contestaban 401 y el buscador global devolvía cero resultados
    siempre. Un doble que contesta a cualquiera da verde a eso.
    """
    from crmcore.rutas_de_api import Destino

    import services.gateway.api as api

    def responder(peticion: httpx.Request) -> httpx.Response:
        preguntadas.append(peticion.url.path)
        # Como el servicio de verdad: sin identidad firmada, 401.
        if "x-crm-tenant" not in {k.lower() for k in peticion.headers}:
            if sin_identidad is not None:
                sin_identidad.append(peticion.url.path)
            return httpx.Response(401, json={"detail": "Autenticación requerida"})
        # Como el servicio de verdad: sólo contesta en SU ruta.
        servicio = peticion.url.path.split("/")[3] if len(peticion.url.path.split("/")) > 3 else ""
        if not peticion.url.path.endswith(f"/{servicio}/buscar"):
            return httpx.Response(404, json={"detail": "Not Found"})
        return httpx.Response(
            200,
            json={
                "resultados": [
                    {"id": f"{servicio}-1", "titulo": f"Acme de {servicio}", "relevancia": 0.9}
                ]
            },
        )

    api._cliente = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    api._destinos = {
        "party": Destino(servicio="party", url_base="http://party:8000"),
        "sales": Destino(servicio="sales", url_base="http://sales:8000"),
    }
    return api


@pytest.mark.asyncio
async def test_se_pregunta_a_la_ruta_de_cada_servicio() -> None:
    """Y no a `/api/v1/buscar`, que en un servicio es un 404."""
    preguntadas: list[str] = []
    api = _gateway(preguntadas)

    salida = await api.buscar_global(_Peticion(), principal=_quien_llama(), q="acme", limite=20)

    assert sorted(preguntadas) == ["/api/v1/party/buscar", "/api/v1/sales/buscar"], preguntadas
    # Y lo que importa de verdad: que vuelvan resultados.
    assert salida["total"] == 2, salida
    assert (
        salida["servicios_sin_responder"] == []
    ), "un servicio que contesta no puede contarse como caído"


@pytest.mark.asyncio
async def test_lo_que_no_contesta_se_dice_en_vez_de_contarse_como_vacio() -> None:
    """La distinción que hace útil esta respuesta.

    «No hay resultados» y «no hemos podido preguntar» llevan a sitios
    distintos: lo primero se acepta, lo segundo se mira. Confundirlos es lo que
    dejó esto roto un año sin que nadie lo notara.
    """
    preguntadas: list[str] = []
    api = _gateway(preguntadas)
    # `sales` deja de estar desplegado: ni se le pregunta ni se le da por vacío.
    api._destinos.pop("sales")

    salida = await api.buscar_global(_Peticion(), principal=_quien_llama(), q="acme", limite=20)
    assert preguntadas == ["/api/v1/party/buscar"]
    assert salida["total"] == 1
    # No está desplegado, así que no es un caído: no se inventa un fallo.
    assert salida["servicios_sin_responder"] == []


@pytest.mark.asyncio
async def test_la_identidad_viaja_firmada_y_no_copiada_de_la_peticion() -> None:
    """El segundo fallo de esta misma ruta, y el que la dejó inservible.

    Las cabeceras se construían colando las `x-*` y `authorization` de la
    petición entrante. La sesión del navegador es una **cookie**: no hay
    `authorization` que copiar, así que `party` y `sales` recibían la consulta
    sin identidad, contestaban **401**, el gateway los contaba como caídos y el
    buscador —el `⌘K` de la barra de todas las pantallas— devolvía cero
    resultados siempre.

    Medido el 03-11-2026 haciendo el trabajo de verdad: dar de alta un cliente
    y buscarlo por su nombre. `/api/v1/accounts?buscar=` lo encontraba y
    `/api/v1/buscar` no.
    """
    preguntadas: list[str] = []
    sin_identidad: list[str] = []
    api = _gateway(preguntadas, sin_identidad)

    salida = await api.buscar_global(_Peticion(), principal=_quien_llama(), q="acme", limite=20)

    # Que se ha preguntado a los dos: si no, esto daría verde sin mirar.
    assert len(preguntadas) == 2, preguntadas
    assert sin_identidad == [], f"preguntó sin identidad a: {sin_identidad}"
    assert salida["total"] == 2, salida
    assert salida["servicios_sin_responder"] == []


@pytest.mark.asyncio
async def test_lo_que_se_llama_exactamente_asi_va_primero() -> None:
    """Buscar «Componentes Delta» llevaba con Intro a «Suministro de
    componentes plegables — Componentes Delta», una oportunidad: tenía más
    relevancia que el propio cliente. Medido el 10-11-2026 (tarea T01)."""
    from crmcore.rutas_de_api import Destino

    import services.gateway.api as api

    def responder(peticion: httpx.Request) -> httpx.Response:
        servicio = peticion.url.path.split("/")[3]
        filas = {
            "party": [{"objeto": "cuenta", "titulo": "Componentes Delta", "relevancia": 0.34}],
            "sales": [
                {
                    "objeto": "oportunidad",
                    "titulo": "Suministro de componentes plegables — Componentes Delta",
                    "relevancia": 0.39,
                },
                {
                    "objeto": "oportunidad",
                    "titulo": "Componentes delta, ampliación",
                    "relevancia": 0.2,
                },
            ],
        }[servicio]
        return httpx.Response(200, json={"resultados": filas})

    api._cliente = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    api._destinos = {
        "party": Destino(servicio="party", url_base="http://party:8000"),
        "sales": Destino(servicio="sales", url_base="http://sales:8000"),
    }
    salida = await api.buscar_global(
        _Peticion(), principal=_quien_llama(), q="componentes delta", limite=20
    )
    assert [r["titulo"] for r in salida["resultados"]] == [
        "Componentes Delta",
        "Componentes delta, ampliación",
        "Suministro de componentes plegables — Componentes Delta",
    ]
