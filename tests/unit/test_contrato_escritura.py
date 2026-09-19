"""Idempotencia (CRM-00.02.01.08) y concurrencia optimista (CRM-00.02.01.09).

Las dos estaban escritas y sin enganchar, que es la peor situación posible: el
módulo existe, la documentación las promete, y en la práctica funcionan en las
rutas donde alguien se acordó. Un contrato de API que vale «en casi todas
partes» no es un contrato — el integrador descubre cuáles son reintentando un
cobro.

Ahora las aplica un middleware, así que valen para **toda** ruta de escritura sin
que nadie tenga que acordarse.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from crmcore.http.etag import ETagMiddleware, _version_del_cuerpo
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

# ── ETag automático ───────────────────────────────────────────────────────


def _app_con_etag(cuerpo: Any, status: int = 200) -> TestClient:
    async def responder(_peticion: Any) -> JSONResponse:
        return JSONResponse(cuerpo, status_code=status)

    app = Starlette(routes=[Route("/r", responder, methods=["GET", "POST", "PATCH"])])
    app.add_middleware(ETagMiddleware)
    return TestClient(app)


def test_una_respuesta_con_version_lleva_etag() -> None:
    respuesta = _app_con_etag({"id": "x", "version": 7}).get("/r")
    assert respuesta.headers["etag"] == 'W/"7"'


def test_una_respuesta_sin_version_no_lleva_etag() -> None:
    """No se inventa: un recurso sin versión no admite concurrencia optimista, y
    darle un ETag haría creer al cliente que sí."""
    assert "etag" not in _app_con_etag({"id": "x"}).get("/r").headers


def test_una_lista_no_lleva_etag() -> None:
    """Una lista no tiene una versión: la de cada elemento no identifica al
    conjunto, y un If-Match contra ella no significaría nada."""
    assert "etag" not in _app_con_etag([{"id": "x", "version": 3}]).get("/r").headers


def test_la_version_de_un_objeto_anidado_no_cuenta() -> None:
    """Sacar el ETag de un objeto anidado identificaría a OTRO recurso, y el
    cliente lo usaría para actualizar el que no es."""
    assert _version_del_cuerpo(json.dumps({"cuenta": {"version": 9}}).encode()) is None


def test_el_cuerpo_llega_intacto() -> None:
    """El middleware retiene la respuesta para añadirle la cabecera; si se le
    perdiera un trozo por el camino, el fallo sería silencioso y aleatorio."""
    cuerpo = {"id": "x", "version": 2, "texto": "á" * 5_000}
    respuesta = _app_con_etag(cuerpo).get("/r")
    assert respuesta.json() == cuerpo


def test_una_respuesta_que_no_es_json_pasa_tal_cual() -> None:
    from starlette.responses import PlainTextResponse

    async def responder(_p: Any) -> PlainTextResponse:
        return PlainTextResponse("hola")

    app = Starlette(routes=[Route("/r", responder)])
    app.add_middleware(ETagMiddleware)
    respuesta = TestClient(app).get("/r")
    assert respuesta.text == "hola"
    assert "etag" not in respuesta.headers


def test_un_cuerpo_enorme_no_se_parsea() -> None:
    """Deserializar varios megas en cada respuesta cuesta mucho más de lo que
    aporta una cabecera."""
    assert _version_del_cuerpo(b'{"version": 1, "x": "' + b"a" * 2_100_000 + b'"}') is None


# ── If-Match ──────────────────────────────────────────────────────────────


class _Versionado:
    def __init__(self, version: int) -> None:
        self.version = version


def test_if_match_correcto_pasa() -> None:
    from crmcore.http.etag import comprobar_if_match

    comprobar_if_match(_Versionado(4), 'W/"4"')
    comprobar_if_match(_Versionado(4), '"4"')


def test_if_match_desfasado_se_rechaza() -> None:
    """Es el caso que esto existe para cazar: dos personas editan la misma ficha
    y la segunda pisaría el cambio de la primera sin enterarse."""
    from crmcore.errors import ConflictoDeVersion
    from crmcore.http.etag import comprobar_if_match

    with pytest.raises(ConflictoDeVersion):
        comprobar_if_match(_Versionado(5), 'W/"4"')


def test_if_match_asterisco_vale_si_existe() -> None:
    from crmcore.http.etag import comprobar_if_match

    comprobar_if_match(_Versionado(9), "*")


def test_sin_if_match_se_puede_exigir() -> None:
    from crmcore.errors import ErrorValidacion
    from crmcore.http.etag import comprobar_if_match

    comprobar_if_match(_Versionado(1), None)  # opcional por defecto
    with pytest.raises(ErrorValidacion):
        comprobar_if_match(_Versionado(1), None, obligatorio=True)


# ── Idempotencia, de extremo a extremo ────────────────────────────────────
#
# Contra Postgres de verdad: la reserva depende de un `ON CONFLICT DO NOTHING`
# y de dos transacciones separadas, y eso no se puede simular sin mentir.


@pytest.fixture
def app_idempotente(db: Any, tenant_id: Any) -> Any:
    """Una aplicación construida con la **factoría real**.

    No un montaje de juguete con los middlewares sueltos: lo que hay que
    comprobar es el arreglo de producción completo —dependencia global que
    reserva, middleware que captura, manejador que devuelve la repetida—, y un
    montaje parcial pasaría las pruebas sin que el sistema funcionara. La
    primera versión de esta prueba hacía justo eso y no reservaba nada.

    El tenant va en su cabecera y no fijado alrededor de la llamada, porque
    `TestClient` ejecuta la aplicación en otro hilo: un contextvar puesto fuera
    no llega dentro.
    """
    from uuid import uuid4

    from crmcore.http.deps import H_TENANT, H_USER
    from crmcore.service import crear_servicio
    from fastapi import APIRouter

    usuario = uuid4()
    llamadas = {"n": 0}
    router = APIRouter()

    @router.post("/crear", status_code=201)
    def crear() -> dict[str, Any]:
        llamadas["n"] += 1
        return {"id": f"creado-{llamadas['n']}", "version": 1}

    @router.post("/fallar")
    def fallar() -> dict[str, Any]:
        from crmcore.errors import ErrorValidacion

        llamadas["n"] += 1
        raise ErrorValidacion("no", error_code="prueba.no")

    app = crear_servicio(
        nombre="pruebas",
        descripcion="Servicio de prueba del contrato de escritura",
        routers=[router],
        necesita_bus=False,
        necesita_db=False,
    )

    class _Contexto:
        def __init__(self) -> None:
            self.llamadas = llamadas
            self.cliente = TestClient(app)

        def post(self, ruta: str, clave: str | None = None, **kwargs: Any) -> Any:
            # Las cabeceras de identidad van FIRMADAS, igual que las manda el
            # gateway. Sin firma, el servicio las ignora y trata la petición
            # como anónima —que es correcto y es lo que impide que cualquiera
            # se declare de otro tenant—, así que una prueba sin firmar no
            # estaría probando nada.
            from crmcore.config import get_settings
            from crmcore.http.deps import firmar_cabeceras_internas

            cabeceras = firmar_cabeceras_internas(
                {H_TENANT: str(tenant_id), H_USER: str(usuario)},
                get_settings().secret_key.get_secret_value(),
            )
            if clave:
                cabeceras["Idempotency-Key"] = clave
            return self.cliente.post(f"/api/v1{ruta}", headers=cabeceras, **kwargs)

    return _Contexto()


@pytest.mark.db
def test_sin_clave_no_hay_idempotencia(app_idempotente: Any) -> None:
    """Exigirla siempre rompería a todo cliente que hoy funciona, y decidir si
    una operación se puede reintentar es de quien la llama."""
    app_idempotente.post("/crear", json={"a": 1})
    app_idempotente.post("/crear", json={"a": 1})
    assert app_idempotente.llamadas["n"] == 2


@pytest.mark.db
def test_la_misma_clave_no_repite_el_trabajo(app_idempotente: Any) -> None:
    primera = app_idempotente.post("/crear", clave="k-1", json={"a": 1})
    segunda = app_idempotente.post("/crear", clave="k-1", json={"a": 1})

    assert app_idempotente.llamadas["n"] == 1
    assert primera.json() == segunda.json()
    assert primera.status_code == segunda.status_code == 201


@pytest.mark.db
def test_el_reintento_se_marca_como_tal(app_idempotente: Any) -> None:
    """Sin esta marca, un cliente no puede distinguir «se ha hecho ahora» de «ya
    estaba hecho», y esa diferencia importa al conciliar."""
    app_idempotente.post("/crear", clave="k-2", json={"a": 1})
    repetida = app_idempotente.post("/crear", clave="k-2", json={"a": 1})

    assert repetida.headers.get("idempotency-replayed") == "true"


@pytest.mark.db
def test_la_misma_clave_con_otro_cuerpo_se_rechaza(app_idempotente: Any) -> None:
    """Es casi siempre un error del cliente: reutilizar la clave de una
    operación para otra distinta. Aceptarlo devolvería la respuesta equivocada."""
    app_idempotente.post("/crear", clave="k-3", json={"a": 1})
    respuesta = app_idempotente.post("/crear", clave="k-3", json={"a": 2})

    assert respuesta.status_code == 409
    assert "idempotencia.cuerpo_distinto" in respuesta.text


@pytest.mark.db
def test_una_operacion_fallida_libera_la_clave(app_idempotente: Any) -> None:
    """Si se guardara el error, el cliente que reintenta tras arreglar su
    problema recibiría para siempre el fallo de la primera vez."""
    app_idempotente.post("/fallar", clave="k-4", json={"a": 1})
    app_idempotente.post("/fallar", clave="k-4", json={"a": 1})

    assert app_idempotente.llamadas["n"] == 2


@pytest.mark.db
def test_claves_distintas_son_operaciones_distintas(app_idempotente: Any) -> None:
    app_idempotente.post("/crear", clave="k-5", json={"a": 1})
    app_idempotente.post("/crear", clave="k-6", json={"a": 1})
    assert app_idempotente.llamadas["n"] == 2
