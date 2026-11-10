"""Lo que se llama desde la web de otro entra por su puerta, y sólo por ella.

Medido el 10-11-2026: la captura de leads desde la web no funcionaba por
ninguna vía. El formulario público contestaba 404 desde fuera —el gateway sólo
reenviaba `/api/*`— y los cuatro componentes incrustables contestaban 401,
porque un token de componente no lleva `id` y `AutenticadoDep` lo daba por
anónimo.

Lo que no se podía hacer es «quitarle el anónimo»: ese token vive en el HTML de
una página pública, y entraría en toda ruta que sólo pide estar autenticado. Así
que aquí se prueban **las dos mitades**: entra donde debe y no entra en ninguna
otra parte —tampoco en las que sólo piden una sesión de base de datos, que con
un principal sin `id` pero con tenant se abrían igual—.
"""

from __future__ import annotations

import importlib
import json
from typing import Annotated, Any
from uuid import UUID, uuid4

import httpx
import pytest
from crmcore import embebido
from crmcore.config import get_settings
from crmcore.errors import CrmError
from crmcore.http.deps import (
    AccesoComponente,
    AutenticadoDep,
    PrincipalDep,
    exige_componente,
)
from crmcore.http.portal_deps import PortalDep
from crmcore.http.problems import manejar_error_dominio
from fastapi import Depends, FastAPI
from starlette.testclient import TestClient


def _token(componente: str, objeto_id: UUID, tenant: UUID) -> str:
    return str(
        embebido.emitir(
            componente=componente,
            objeto=embebido.OBJETO_DE_COMPONENTE[componente],
            objeto_id=objeto_id,
            tenant_id=tenant,
            permisos=embebido.PERMISOS_DE_COMPONENTE[componente],
            minutos=5,
        )["token"]
    )


# ── En el servicio: la dependencia ─────────────────────────────────────────


def _servicio() -> TestClient:
    """Un servicio mínimo con lo que importa del de verdad.

    La dependencia global que pide el principal en TODA ruta —en los servicios
    es la de idempotencia— y tres rutas: la del componente, una que sólo pide
    estar autenticado y una que sólo pide el principal, que es la forma de las
    que no piden más que `DbDep`.
    """

    def _global(_: PrincipalDep) -> None:
        return None

    app = FastAPI(dependencies=[Depends(_global)])
    app.add_exception_handler(CrmError, manejar_error_dominio)  # type: ignore[arg-type]

    @app.get("/api/v1/embebido/ficha-cuenta")
    def ficha(
        acceso: Annotated[AccesoComponente, Depends(exige_componente("ficha-cuenta"))],
    ) -> Any:
        return {"objeto_id": str(acceso.objeto_id), "tenant": str(acceso.tenant_id)}

    @app.get("/api/v1/autenticado")
    def autenticado(_: AutenticadoDep) -> Any:
        return {"ok": True}

    @app.get("/api/v1/solo-principal")
    def solo_principal(_: PrincipalDep) -> Any:
        return {"ok": True}

    return TestClient(app)


def test_el_token_de_componente_entra_en_su_ruta_y_en_ninguna_otra() -> None:
    cuenta, tenant = uuid4(), uuid4()
    cliente = _servicio()
    con_token = {"Authorization": f"Bearer {_token('ficha-cuenta', cuenta, tenant)}"}

    r = cliente.get("/api/v1/embebido/ficha-cuenta", headers=con_token)
    assert r.status_code == 200, r.text
    assert r.json() == {"objeto_id": str(cuenta), "tenant": str(tenant)}

    for ruta in ("/api/v1/autenticado", "/api/v1/solo-principal"):
        r = cliente.get(ruta, headers=con_token)
        assert r.status_code == 401, (ruta, r.text)
        assert r.json()["error_code"] == "embebido.ruta_no_admite_componente", ruta


def test_la_ruta_del_componente_no_atiende_otra_cosa() -> None:
    """Ni el token de OTRO componente ni una sesión del CRM."""
    import jwt

    cliente = _servicio()
    de_otro = _token("lista-casos", uuid4(), uuid4())
    r = cliente.get("/api/v1/embebido/ficha-cuenta", headers={"Authorization": f"Bearer {de_otro}"})
    assert r.status_code == 403, r.text

    s = get_settings()
    sesion = jwt.encode(
        {"sub": str(uuid4()), "tenant": str(uuid4()), "permisos": ["*:*"]},
        s.secret_key.get_secret_value(),
        algorithm=s.jwt_algorithm,
    )
    r = cliente.get("/api/v1/embebido/ficha-cuenta", headers={"Authorization": f"Bearer {sesion}"})
    assert r.status_code == 401, r.text
    assert r.json()["error_code"] == "embebido.token_no_es_de_componente"


# ── En el gateway: las dos puertas ─────────────────────────────────────────


@pytest.fixture
def gateway(monkeypatch: Any) -> Any:
    """El gateway de verdad, con los servicios de detrás simulados."""
    from services.gateway import api as gw
    from services.gateway import operatividad

    recibidas: list[httpx.Request] = []

    def responder(peticion: httpx.Request) -> httpx.Response:
        if peticion.url.path.endswith("/operatividad"):
            return httpx.Response(200, json={"puede_leer": True, "puede_escribir": True})
        recibidas.append(peticion)
        return httpx.Response(200, json={"recibido": True})

    operatividad.limpiar_cache()
    app = importlib.import_module("services.gateway.main").app
    with TestClient(app) as cliente:
        monkeypatch.setattr(
            gw, "_cliente", httpx.AsyncClient(transport=httpx.MockTransport(responder))
        )
        monkeypatch.setattr(
            gw,
            "_destinos",
            {
                n: type("D", (), {"url_base": f"http://{n}"})()
                for n in ("tenancy", "party", "sales", "service")
            },
        )
        yield cliente, recibidas
    operatividad.limpiar_cache()


def test_el_gateway_deja_el_token_de_componente_sólo_en_su_componente(gateway: Any) -> None:
    cliente, recibidas = gateway
    cuenta, tenant = uuid4(), uuid4()
    con_token = {"Authorization": f"Bearer {_token('ficha-cuenta', cuenta, tenant)}"}

    r = cliente.get("/api/v1/embebido/ficha-cuenta", headers=con_token)
    assert r.status_code == 200, r.text
    assert len(recibidas) == 1
    llega = recibidas[0]
    assert (llega.url.host, llega.url.path) == ("party", "/api/v1/embebido/ficha-cuenta")
    assert llega.headers["x-crm-embebido"] == f"ficha-cuenta|cuenta|{cuenta}"

    # Ni el proxy general, ni una ruta propia del gateway, ni otro componente.
    for metodo, ruta, codigo in (
        ("GET", "/api/v1/accounts", 401),
        ("GET", "/api/v1/sdk/componentes", 401),
        ("GET", "/api/v1/embebido/lista-casos", 403),
    ):
        r = cliente.request(metodo, ruta, headers=con_token)
        assert r.status_code == codigo, (ruta, r.text)
    assert len(recibidas) == 1, [str(p.url) for p in recibidas]


def test_la_captura_publica_se_reenvia_sin_identidad_y_con_sus_topes(
    gateway: Any, monkeypatch: Any
) -> None:
    cliente, recibidas = gateway
    tenant = uuid4()
    ruta = f"/captura/{tenant}/web"

    r = cliente.post(
        ruta,
        json={"email": "ana@ejemplo.example"},
        headers={
            "X-Captura-Secreto": "s3",
            "Cookie": "otra=1",
            "Origin": "https://cliente.example",
        },
    )
    assert r.status_code == 200, r.text
    llega = recibidas[-1]
    assert (llega.url.host, llega.url.path) == ("sales", ruta)
    assert llega.headers["x-captura-secreto"] == "s3"
    assert json.loads(llega.content) == {"email": "ana@ejemplo.example"}
    # Ninguna identidad propagada ni nada que no esté en la lista.
    assert not [k for k in llega.headers if k.startswith("x-crm-") or k == "cookie"]
    # El navegador de la web del cliente puede leer la respuesta, sin cookie.
    assert r.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in r.headers

    # La pregunta previa del navegador la contesta esta puerta, no el CORS
    # general, que con un origen que no es la consola la tumbaba.
    r = cliente.options(
        ruta,
        headers={
            "Origin": "https://cliente.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-captura-secreto",
        },
    )
    assert r.status_code == 204, r.text
    assert "x-captura-secreto" in r.headers["access-control-allow-headers"].lower()

    s = get_settings()
    antes = len(recibidas)
    monkeypatch.setattr(s, "captura_publica_max_bytes", 1_024)
    r = cliente.post(
        ruta, content=b"{" + b" " * 2_000 + b"}", headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 413, r.text

    monkeypatch.setattr(s, "incrustable_origenes", "https://cliente.example")
    r = cliente.post(ruta, json={}, headers={"Origin": "https://otra.example"})
    assert r.status_code == 403, r.text
    assert len(recibidas) == antes


# ── El token de portal: la misma regla, su propia puerta ───────────────────
#
# Lleva `sub` (el acceso) y `tenant`, así que `contexto_autenticado` lo
# convertía en un principal con `id`: pasaba `AutenticadoDep` en toda ruta que
# no pide un permiso concreto. Medido el 10-11-2026 con estas pruebas antes de
# cerrarlo: 200 en las dos rutas de servicio y en `/api/v1/superficie` del
# gateway.


def _token_portal(tenant: UUID) -> str:
    from crmcore.http.portal_deps import emitir_token_portal

    token, _ = emitir_token_portal(
        acceso_id=uuid4(), tenant_id=tenant, nivel="lectura", secciones=["casos"]
    )
    return token


def test_el_token_de_portal_entra_en_el_portal_y_en_ninguna_otra_ruta() -> None:
    cliente = _servicio()

    @cliente.app.get("/api/v1/portal/mi/casos")  # type: ignore[attr-defined]
    def mis_casos(sesion: PortalDep) -> Any:
        return {"acceso": str(sesion.acceso_id)}

    tenant = uuid4()
    con_token = {"Authorization": f"Bearer {_token_portal(tenant)}"}
    r = cliente.get("/api/v1/portal/mi/casos", headers=con_token)
    assert r.status_code == 200, r.text

    for ruta in ("/api/v1/autenticado", "/api/v1/solo-principal"):
        r = cliente.get(ruta, headers=con_token)
        assert r.status_code == 401, (ruta, r.text)
        assert r.json()["error_code"] == "portal.ruta_no_admite_portal", ruta


def test_el_gateway_deja_el_token_de_portal_sólo_en_el_portal(gateway: Any) -> None:
    cliente, recibidas = gateway
    con_token = {"Authorization": f"Bearer {_token_portal(uuid4())}"}

    r = cliente.get("/api/v1/portal/mi/casos", headers=con_token)
    assert r.status_code == 200, r.text
    assert len(recibidas) == 1
    assert (recibidas[0].url.host, recibidas[0].url.path) == ("service", "/api/v1/portal/mi/casos")
    # El token sigue viajando: es con lo que el servicio sabe qué acceso es.
    assert recibidas[0].headers["authorization"] == con_token["Authorization"]

    # Ni el proxy general ni las rutas propias del gateway que sólo piden
    # estar autenticado.
    codigos = {
        ruta: cliente.get(ruta, headers=con_token).status_code
        for ruta in ("/api/v1/accounts", "/api/v1/superficie", "/api/v1/sdk/componentes")
    }
    assert set(codigos.values()) == {401}, codigos
    assert len(recibidas) == 1, [str(p.url) for p in recibidas]


# ── Emitir el token: quien lo pide tiene que poder ver ESE registro ────────


def test_el_token_sólo_se_emite_para_un_registro_que_quien_lo_pide_ve(
    gateway: Any, monkeypatch: Any
) -> None:
    """Antes bastaba con el permiso: se emitía para cualquier cuenta del tenant."""
    import jwt

    from services.gateway import api as gw

    cliente, _ = gateway
    visible, ajena = uuid4(), uuid4()
    preguntas: list[httpx.Request] = []

    def responder(peticion: httpx.Request) -> httpx.Response:
        if peticion.url.path.endswith("/operatividad"):
            return httpx.Response(200, json={"puede_leer": True, "puede_escribir": True})
        preguntas.append(peticion)
        if peticion.url.path == f"/api/v1/accounts/{visible}":
            return httpx.Response(200, json={"id": str(visible)})
        return httpx.Response(404, json={"error_code": "no_encontrado"})

    monkeypatch.setattr(gw, "_cliente", httpx.AsyncClient(transport=httpx.MockTransport(responder)))

    s = get_settings()
    usuario = uuid4()
    sesion = jwt.encode(
        {
            "sub": str(usuario),
            "tenant": str(uuid4()),
            "permisos": ["integracion:write", "party:read"],
        },
        s.secret_key.get_secret_value(),
        algorithm=s.jwt_algorithm,
    )
    cabeceras = {"Authorization": f"Bearer {sesion}"}

    def pedir(cuenta: UUID) -> httpx.Response:
        return cliente.post(
            "/api/v1/sdk/componentes/token",
            json={"componente": "ficha-cuenta", "objeto": "cuenta", "objeto_id": str(cuenta)},
            headers=cabeceras,
        )

    r = pedir(visible)
    assert r.status_code == 200, r.text
    assert r.json()["objeto_id"] == str(visible)
    # Se preguntó al dueño de la cuenta, y con la identidad de quien lo pide.
    assert (preguntas[-1].url.host, preguntas[-1].headers["x-crm-user"]) == ("party", str(usuario))

    r = pedir(ajena)
    assert r.status_code == 403, r.text
    assert r.json()["error_code"] == "embebido.registro_no_visible"
    assert "token" not in r.json()
