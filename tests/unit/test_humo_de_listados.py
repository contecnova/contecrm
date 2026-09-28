"""Ninguna ruta de listado revienta al abrirla (barrido de humo).

POR QUÉ. Hoy han salido cuatro cosas marcadas «hecho» que no funcionaban, y las
cuatro pasaban todos los gates: descargar un informe en CSV era un 500, los
informes programados fallaban cada noche, ocho rutas estaban publicadas sin
responder y el comentario de cada aprobación se perdía. El criterio de «hecho»
exige código, prueba y manual, y **ninguna de las tres cosas comprueba que la
vía real devuelva algo**.

Esta prueba es esa comprobación que faltaba, en su forma más barata: se abre
cada listado sin parámetros, como lo abre una pantalla al entrar, y se exige que
no conteste 500. No mira que el dato sea el correcto —eso es de cada prueba de
dominio— sino que la ruta exista, se resuelva y devuelva algo. Es exactamente el
fallo que ninguna prueba de función caza, porque la función está bien y lo que
está mal es el camino.

Un 500 aquí es una pantalla en blanco para alguien. No hay excepciones: si una
ruta no puede contestar sin datos, contesta vacío, no revienta.

HASTA DÓNDE SE HA COMPROBADO, a día 28-09-2026: **`party`, `sales` y `service`
en verde. Los otros diez servicios NO se han llegado a correr enteros.** La
tanda completa pasa de diez minutos y se cortó tres veces por tiempo y por
carga de la máquina. Así que de esos diez no se sabe si hay listados rotos —no
es que estén bien: es que no se han mirado—, y queda dicho aquí y no sólo en la
cabeza de quien lo escribió.
"""

from __future__ import annotations

import importlib
import os
from typing import Any
from uuid import UUID

import pytest

SERVICIOS = [
    "tenancy",
    "identity",
    "metadata",
    "orchestrator",
    "automation",
    "integration",
    "eventing",
    "party",
    "sales",
    "analytics",
    "intelligence",
    "service",
    "marketing",
]


@pytest.fixture(autouse=True)
def _devolver_el_servicio() -> Any:
    from crmcore.config import limpiar_cache_settings

    previo = os.environ.get("SERVICE_NAME")
    try:
        yield
    finally:
        if previo is None:
            os.environ.pop("SERVICE_NAME", None)
        else:
            os.environ["SERVICE_NAME"] = previo
        limpiar_cache_settings()


def _cabeceras(tenant_id: UUID) -> dict[str, str]:
    """Identidad firmada de administrador del tenant.

    Con `*:*`: un 403 por falta de permiso taparía el 500 que se busca, y la
    prueba pasaría por el motivo equivocado.
    """
    from uuid import uuid4

    from crmcore.config import get_settings
    from crmcore.http.deps import H_PERMISOS, H_TENANT, H_USER, firmar_cabeceras_internas

    return firmar_cabeceras_internas(
        {H_TENANT: str(tenant_id), H_USER: str(uuid4()), H_PERMISOS: "*:*"},
        get_settings().secret_key.get_secret_value(),
    )


def _listados_de(app: Any) -> list[str]:
    """Las rutas que se abren solas: GET, sin parámetros y sin datos exigidos."""
    caminos = []
    for camino, ops in (app.openapi().get("paths") or {}).items():
        if "{" in camino or not camino.startswith("/api/v1/"):
            continue
        get = ops.get("get")
        if get is None:
            continue
        # Las que exigen algo por la URL contestan 422, no 500, y ese no es el
        # fallo que se busca aquí: se saltan para que el resultado sea legible.
        if any(p.get("required") for p in get.get("parameters") or []):
            continue
        # LOS FLUJOS DE EVENTOS NO SE ABREN AQUÍ, y no es una excepción cómoda:
        # un `text/event-stream` se queda abierto a propósito mandando lo que
        # pasa, así que pedirlo y esperar a que termine es esperar para siempre.
        # Colgó este barrido diez minutos en `identity` —`/chat/eventos`— y es
        # el mismo tropiezo que ya tuvo el registro de fuentes, que lo resolvió
        # con un plazo corto. Aquí no hace falta plazo: se reconoce por lo que
        # el propio contrato declara que devuelve.
        respuestas = (get.get("responses") or {}).get("200") or {}
        if "text/event-stream" in (respuestas.get("content") or {}):
            continue
        caminos.append(camino)
    return sorted(caminos)


@pytest.mark.parametrize("servicio", SERVICIOS)
def test_ningun_listado_revienta_al_abrirlo(servicio: str, db: Any, tenant_id: UUID) -> None:
    from crmcore.config import limpiar_cache_settings
    from fastapi.testclient import TestClient

    os.environ["SERVICE_NAME"] = servicio
    limpiar_cache_settings()
    modulo = importlib.import_module(f"services.{servicio}.main")
    app = modulo.app

    cliente = TestClient(app, raise_server_exceptions=False)
    cabeceras = _cabeceras(tenant_id)
    rotas: list[str] = []
    for camino in _listados_de(app):
        respuesta = cliente.get(camino, headers=cabeceras)
        if respuesta.status_code >= 500:
            detalle = ""
            try:
                detalle = str(respuesta.json())[:160]
            except Exception:  # noqa: BLE001
                detalle = respuesta.text[:160]
            rotas.append(f"{respuesta.status_code} GET {camino} → {detalle}")

    assert not rotas, (
        f"En «{servicio}» hay listados que revientan al abrirlos:\n  "
        + "\n  ".join(rotas)
        + "\n\nUn 500 al abrir una pantalla es una pantalla en blanco. Si la ruta "
        "no puede contestar sin datos, que conteste vacío."
    )
