"""Crear una automatización por su ruta, que es como la crea todo el mundo.

El motor estaba probado a conciencia —ramas, bucles, topes de anidamiento, que
las variables no se escapen— llamando a las funciones. La **ruta** no: y entre
la función y quien la llama está el contrato de la respuesta, que es donde
estaba el fallo.

`AutomatizacionOut.programacion` estaba declarada `dict` y la columna es una
expresión cron, `String(120)` que admite nulo. Así que crear una automatización
**sin horario** —el caso normal, porque la mayoría se disparan por evento—
respondía 500 al serializar, con la fila ya escrita en la base. Se descubrió
sembrando una empresa de demostración: cinco altas seguidas, las cinco en 500,
y ninguna prueba en rojo, porque todas las que había le ponían horario.
"""

from __future__ import annotations

import importlib
import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


@pytest.fixture
def cliente(db: Any) -> Any:
    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        modulo = importlib.import_module("services.automation.main")
        with TestClient(modulo.app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


@pytest.fixture
def cabeceras(tenant_id: UUID) -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import (
        H_FACTOR_FUERTE,
        H_PERMISOS,
        H_ROLES,
        H_TENANT,
        H_USER,
        firmar_cabeceras_internas,
    )

    return firmar_cabeceras_internas(
        {
            H_TENANT: str(tenant_id),
            H_USER: str(uuid4()),
            H_PERMISOS: "*:*",
            H_ROLES: "admin",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


def _regla(**extra: Any) -> dict[str, Any]:
    return {
        "nombre": "Aviso cuando una oportunidad grande cambia de etapa",
        "disparador": "modificacion",
        "objetivo": "oportunidad",
        "campos_vigilados": ["etapa"],
        "acciones": [{"tipo": "notificar", "a": "owner"}],
        **extra,
    }


def test_una_automatizacion_sin_horario_se_crea(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """Es el caso normal: la mayoría se disparan por evento, no por reloj."""
    r = cliente.post("/api/v1/automatizaciones", json=_regla(), headers=cabeceras)
    assert r.status_code == 201, r.text[:400]
    cuerpo = r.json()
    # Sin horario es `null`, no `{}`: un objeto vacío se lee como «tiene
    # programación y está sin rellenar», que es otra cosa.
    assert cuerpo["programacion"] is None
    # Y nace apagada, que es lo que dice su propia descripción: una regla que
    # se enciende al crearse actúa sobre datos reales antes de probarla.
    assert cuerpo["activa"] is False


def test_una_programada_devuelve_su_cron_tal_cual(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """Y el horario vuelve como se mandó: una cadena, no un objeto."""
    r = cliente.post(
        "/api/v1/automatizaciones",
        json=_regla(
            nombre="Resumen de los lunes", disparador="programada", programacion="0 8 * * 1"
        ),
        headers=cabeceras,
    )
    assert r.status_code == 201, r.text[:400]
    assert r.json()["programacion"] == "0 8 * * 1"


def test_y_se_listan_las_dos(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """El listado pasa por el mismo contrato: si la respuesta no serializa, no
    revienta sólo el alta — deja de poder verse ninguna."""
    cliente.post("/api/v1/automatizaciones", json=_regla(), headers=cabeceras)
    cliente.post(
        "/api/v1/automatizaciones",
        json=_regla(
            nombre="Resumen de los lunes", disparador="programada", programacion="0 8 * * 1"
        ),
        headers=cabeceras,
    )
    r = cliente.get("/api/v1/automatizaciones", headers=cabeceras)
    assert r.status_code == 200, r.text[:400]
    # El listado viene paginado: `items` y su cursor, que es el contrato que
    # declara `PaginaDeListado`.
    cuerpo = r.json()
    programaciones = {f["programacion"] for f in cuerpo["items"]}
    assert programaciones == {None, "0 8 * * 1"}, programaciones
