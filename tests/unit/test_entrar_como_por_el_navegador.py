"""«Entrar como» de soporte desde el navegador (CRM-00.01.02.06).

Identidad devolvía los tokens de la suplantación en el cuerpo, y el navegador no
puede quedárselos: la sesión vive en una cookie `HttpOnly`. El gateway hace de
puente, y lo que se fija aquí es lo que hace que sirva y que se pueda volver:

- la cookie de acceso pasa a ser la de soporte y **el refresco propio no se
  toca**, que es lo que deja volver sin la contraseña;
- mientras se está dentro, renovar renueva la de soporte —no la propia, que
  sacaría a la persona sin decírselo—, y cuando la de soporte ya no se puede
  renovar se vuelve a la propia y se dice;
- «volver» cierra en identidad la sesión de soporte, y sólo si lo es.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from starlette.testclient import TestClient


class _Identidad:
    """Un identity de mentira que apunta qué le piden."""

    def __init__(self) -> None:
        self.llamadas: list[tuple[str, str, dict[str, Any]]] = []
        self.refresco_soporte_vale = True

    def __call__(self, peticion: httpx.Request) -> httpx.Response:
        ruta = peticion.url.path
        cuerpo = json.loads(peticion.content or b"{}") if peticion.content else {}
        self.llamadas.append((ruta, peticion.headers.get("authorization", ""), cuerpo))
        if ruta == "/api/v1/sesiones/suplantar":
            return httpx.Response(
                200, json={"access_token": "acceso-soporte", "refresh_token": "refresco-soporte"}
            )
        if ruta == "/api/v1/auth/refresh":
            if cuerpo.get("refresh_token") == "refresco-soporte":
                if not self.refresco_soporte_vale:
                    return httpx.Response(401, json={"error_code": "auth.sesion_caducada"})
                return httpx.Response(
                    200,
                    json={
                        "access_token": "acceso-soporte-2",
                        "refresh_token": "refresco-soporte-2",
                    },
                )
            return httpx.Response(
                200, json={"access_token": "acceso-propio-2", "refresh_token": "refresco-propio-2"}
            )
        if ruta == "/api/v1/auth/me":
            soporte = peticion.headers.get("authorization", "").endswith("soporte")
            return httpx.Response(200, json={"suplantado_por": "x" if soporte else None})
        if ruta == "/api/v1/auth/logout":
            return httpx.Response(204)
        return httpx.Response(404)


@pytest.fixture
def montaje(monkeypatch: Any) -> Any:
    from crmcore.config import get_settings
    from crmcore.http.problems import registrar_manejadores

    from services.gateway import sesion

    # Un router nuevo: el del módulo ya puede llevar las rutas atadas al
    # gateway de verdad si otra prueba lo importó antes.
    monkeypatch.setattr(sesion, "router_sesion", APIRouter(prefix="/sesion"))
    identidad = _Identidad()
    cliente_http = httpx.AsyncClient(transport=httpx.MockTransport(identidad))
    destinos = {"identity": SimpleNamespace(url_base="http://identidad")}
    app = FastAPI()
    registrar_manejadores(app)
    app.include_router(sesion.crear_router_sesion(lambda: (cliente_http, destinos, 5.0)))
    nombre = get_settings().sesion_cookie_nombre
    with TestClient(app) as cli:
        yield cli, identidad, nombre


def _cookies_puestas(respuesta: Any) -> dict[str, str]:
    salida = {}
    for linea in respuesta.headers.get_list("set-cookie"):
        nombre, _, resto = linea.partition("=")
        salida[nombre] = resto.split(";")[0]
    return salida


def test_entrar_cambia_el_acceso_y_no_toca_el_refresco_propio(montaje: Any) -> None:
    cli, identidad, nombre = montaje
    cli.cookies.set(nombre, "acceso-propio")
    r = cli.post(
        "/sesion/suplantar",
        json={"usuario_id": "u", "motivo": "Ticket 1: no ve sus tareas"},
        headers={"X-CRM-Tenant-Mirado": "cliente-1"},
    )
    assert r.status_code == 200, r.text
    puestas = _cookies_puestas(r)
    assert puestas[nombre] == "acceso-soporte"
    assert puestas[f"{nombre}_suplantacion_refresco"] == "refresco-soporte"
    # El refresco propio no se toca: es lo que deja volver sin contraseña.
    assert f"{nombre}_refresco" not in puestas
    ruta, autorizacion, _ = identidad.llamadas[0]
    assert ruta == "/api/v1/sesiones/suplantar"
    assert autorizacion == "Bearer acceso-propio"


def test_dentro_se_renueva_la_de_soporte_y_al_caducar_se_vuelve(montaje: Any) -> None:
    cli, identidad, nombre = montaje
    cli.cookies.set(f"{nombre}_refresco", "refresco-propio", path="/sesion/renovar")
    cli.cookies.set(f"{nombre}_suplantacion_refresco", "refresco-soporte", path="/sesion/renovar")
    r = cli.post("/sesion/renovar")
    assert r.status_code == 200, r.text
    assert r.json().get("suplantando") is True
    assert _cookies_puestas(r)[nombre] == "acceso-soporte-2"

    identidad.refresco_soporte_vale = False
    cli.cookies.set(f"{nombre}_suplantacion_refresco", "refresco-soporte", path="/sesion/renovar")
    r = cli.post("/sesion/renovar")
    assert r.status_code == 200, r.text
    assert r.json()["suplantacion_terminada"] is True
    assert _cookies_puestas(r)[nombre] == "acceso-propio-2"


def test_volver_cierra_la_de_soporte_y_solo_si_lo_es(montaje: Any) -> None:
    cli, identidad, nombre = montaje
    cli.cookies.set(nombre, "acceso-soporte")
    r = cli.post("/sesion/volver")
    assert r.status_code == 204, r.text
    assert ("/api/v1/auth/logout", "Bearer acceso-soporte", {}) in identidad.llamadas

    identidad.llamadas.clear()
    cli.cookies.set(nombre, "acceso-propio")
    r = cli.post("/sesion/volver")
    assert r.status_code == 409
    assert not any(ruta == "/api/v1/auth/logout" for ruta, _, _ in identidad.llamadas)
