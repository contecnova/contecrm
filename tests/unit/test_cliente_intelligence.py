"""El canje de token contra contecintelligence, paso a paso (CRM-05.01.04.01).

Esta prueba existe porque el cliente **no funcionaba** y nadie se enteró. Se
escribió contra un contrato imaginado: un solo paso, credencial por
autenticación básica, ruta `/api/v1/tokens/exchange` y campo `ttl`. Lo que
contecintelligence publica son dos pasos, token de aplicación por cabecera, rutas
sin `/v1` y campo `ttl_s`. Levantado el vecino de verdad, el canje daba 401.

Sobrevivió porque no había ninguna prueba que ejerciera el camino completo: la
única que tocaba `canjear_token` comprobaba que sin organización se niega, que
no llega a hablar con nadie. Una integración sin prueba de su contrato es una
integración que se descubre rota el día del despliegue.

Lo que se fija aquí es exactamente lo que se rompió: **las dos rutas, el orden
de los dos pasos, cómo viaja cada credencial y los nombres de los campos**.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pytest


@pytest.fixture
def ci_activo() -> Any:
    from crmcore.config import limpiar_cache_settings

    previo = {
        k: os.environ.get(k)
        for k in ("CI_ENABLED", "CI_BASE_URL", "CI_CLIENT_ID", "CI_CLIENT_SECRET")
    }
    os.environ.update(
        CI_ENABLED="true",
        CI_BASE_URL="https://ci.ejemplo.test",
        CI_CLIENT_ID="ci_de_prueba",
        CI_CLIENT_SECRET="secreto",
    )
    limpiar_cache_settings()
    yield
    for clave, valor in previo.items():
        if valor is None:
            os.environ.pop(clave, None)
        else:
            os.environ[clave] = valor
    limpiar_cache_settings()


@pytest.fixture
def sin_cache() -> Any:
    """El token de aplicación se guarda entre llamadas; cada prueba parte de cero."""
    from services.analytics import cliente

    cliente._aplicacion.update({"token": "", "expira_at": 0.0})
    yield
    cliente._aplicacion.update({"token": "", "expira_at": 0.0})


def _fingir(monkeypatch: pytest.MonkeyPatch, manejar: Any) -> list[httpx.Request]:
    """Sustituye el cliente HTTP por uno que responde en memoria y apunta lo que sale."""
    vistas: list[httpx.Request] = []

    def _manejador(peticion: httpx.Request) -> httpx.Response:
        vistas.append(peticion)
        return manejar(peticion)

    def _cliente_falso(**kwargs: Any) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(_manejador))

    from crmcore import red

    monkeypatch.setattr(red, "cliente_seguro", _cliente_falso)
    return vistas


def test_el_canje_son_dos_pasos_y_en_este_orden(
    ci_activo: Any, sin_cache: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Credencial → token de aplicación → token de usuario. Nunca un solo salto.

    El orden no es un detalle de implementación: la credencial de aplicación
    puede representar a TODOS los tenants, y el token del segundo paso nombra
    uno solo. Saltarse el primero es lo que hacía el cliente, y contecintelligence
    lo rechaza con un 401.
    """
    import json

    def manejar(p: httpx.Request) -> httpx.Response:
        if p.url.path == "/api/oauth/token":
            return httpx.Response(
                200, json={"access_token": "tok_app", "expires_in": 300, "scope": "chat:ask"}
            )
        if p.url.path == "/api/tokens/exchange":
            return httpx.Response(
                200,
                json={
                    "access_token": "tok_usuario",
                    "expires_in": 600,
                    "scope": "chat:ask sources:read",
                    "tenant": "demo",
                },
            )
        return httpx.Response(404)

    vistas = _fingir(monkeypatch, manejar)
    from services.analytics.cliente import canjear_token

    token = canjear_token(organizacion="demo", sujeto="alguien@ejemplo.test", rol="viewer")

    assert [p.url.path for p in vistas] == [
        "/api/oauth/token",
        "/api/tokens/exchange",
    ], "el canje tiene que ser los dos pasos que publica contecintelligence, en ese orden"
    # Paso 1: la credencial va en el CUERPO, que es como lo declara su `CredencialIn`.
    credencial = json.loads(vistas[0].content)
    assert credencial == {
        "client_id": "ci_de_prueba",
        "client_secret": "secreto",
        "grant_type": "client_credentials",
    }
    # Paso 2: la credencial NO se repite; va el token de aplicación por cabecera.
    assert vistas[1].headers["authorization"] == "Bearer tok_app"
    assert "authorization" not in {k.lower() for k in vistas[0].headers} or not vistas[
        0
    ].headers.get("authorization", "").startswith("Basic ")
    assert token.token == "tok_usuario"
    assert token.organizacion == "demo"


def test_el_canje_manda_los_nombres_de_campo_que_el_otro_lado_declara(
    ci_activo: Any, sin_cache: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ttl_s`, no `ttl`.

    Con el nombre mal, pydantic lo ignora en silencio y el token sale con la
    duración por defecto del otro lado en vez de con la configurada aquí. No hay
    error, no hay aviso, y el token dura lo que no se pidió.
    """
    import json

    def manejar(p: httpx.Request) -> httpx.Response:
        if p.url.path == "/api/oauth/token":
            return httpx.Response(200, json={"access_token": "tok_app", "expires_in": 300})
        return httpx.Response(
            200, json={"access_token": "t", "expires_in": 600, "scope": "", "tenant": "demo"}
        )

    vistas = _fingir(monkeypatch, manejar)
    from services.analytics.cliente import canjear_token

    canjear_token(organizacion="demo", sujeto="alguien@ejemplo.test", rol="viewer")

    cuerpo = json.loads(vistas[1].content)
    assert set(cuerpo) == {
        "tenant",
        "subject",
        "role",
        "scopes",
        "ttl_s",
    }, "los nombres son los de `CanjeIn` de contecintelligence; uno de más se ignora en silencio"
    assert isinstance(cuerpo["ttl_s"], int)


def test_el_token_de_aplicacion_no_se_pide_dos_veces(
    ci_activo: Any, sin_cache: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Se guarda mientras dure: si no, cada pantalla añade una ida y vuelta."""

    def manejar(p: httpx.Request) -> httpx.Response:
        if p.url.path == "/api/oauth/token":
            return httpx.Response(200, json={"access_token": "tok_app", "expires_in": 300})
        return httpx.Response(
            200, json={"access_token": "t", "expires_in": 600, "scope": "", "tenant": "demo"}
        )

    vistas = _fingir(monkeypatch, manejar)
    from services.analytics.cliente import canjear_token

    canjear_token(organizacion="demo", sujeto="a@b.test", rol="viewer")
    canjear_token(organizacion="demo", sujeto="a@b.test", rol="viewer")

    assert [p.url.path for p in vistas].count("/api/oauth/token") == 1


def test_una_credencial_rechazada_se_distingue_de_un_canje_rechazado(
    ci_activo: Any, sin_cache: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Son dos averías distintas y quien las lee tiene que poder separarlas.

    Credencial mala se arregla en el `.env`; canje rechazado, mapeando el tenant
    en contecintelligence. Con un solo código de error, el que mira el registro no
    sabe a cuál de las dos ir.
    """
    from crmcore.errors import ErrorDependencia

    _fingir(
        monkeypatch,
        lambda p: httpx.Response(401, json={"detail": "credencial de aplicación inválida"}),
    )
    from services.analytics.cliente import canjear_token

    with pytest.raises(ErrorDependencia) as fallo:
        canjear_token(organizacion="demo", sujeto="a@b.test", rol="viewer")
    assert fallo.value.error_code == "analytics.credencial_rechazada"
