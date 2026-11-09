"""Las rutas de `party` que usan las pantallas nuevas, recorridas por HTTP
(CRM-07.01.01.08, CRM-00.04.03.08, CRM-07.01.01.07, CRM-00.02.01.11,
CRM-01.01.03.03).

Importar con su mapeo y su reversión, traspasar la cartera, el lote junto a la
colección que usa el listado y la búsqueda de contactos parecidos que pregunta
`sales` al capturar un lead.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


@pytest.fixture
def cliente(monkeypatch: Any) -> Any:
    import importlib
    import os

    from crmcore.config import get_settings
    from crmcore.tareas import RelevoDeTareas

    async def _no_correr(self: Any) -> None:
        return None

    monkeypatch.setattr(RelevoDeTareas, "correr", _no_correr)
    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        modulo = importlib.import_module("services.party.main")
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


def test_importar_simular_importar_y_revertir(
    cliente: Any, cabeceras: dict[str, str], db: Any
) -> None:
    campos = cliente.get(
        "/api/v1/party-admin/importaciones/campos?objeto=contacto", headers=cabeceras
    )
    assert campos.status_code == 200, campos.text
    assert {"nombre", "email"} <= {c["nombre"] for c in campos.json()["campos"]}

    cuerpo = {
        "objeto": "contacto",
        "filas": [{"nombre": "Ana", "email": "ana@http.test"}, {"email": "x@http.test"}],
        "fichero": "contactos.csv",
    }
    simulado = cliente.post("/api/v1/party-admin/importaciones", headers=cabeceras, json=cuerpo)
    assert simulado.status_code == 200, simulado.text
    assert simulado.json()["previsualizacion"] == [{"fila": 1, "accion": "crear"}]
    assert simulado.json()["errores"][0]["fila"] == 2

    hecho = cliente.post(
        "/api/v1/party-admin/importaciones",
        headers=cabeceras,
        json={**cuerpo, "simular": False},
    )
    assert hecho.status_code == 200, hecho.text
    importacion = hecho.json()["importacion"]
    assert importacion["creados"] == 1

    historial = cliente.get("/api/v1/party-admin/importaciones", headers=cabeceras)
    assert historial.status_code == 200
    assert historial.json()[0]["id"] == importacion["id"]

    ruta = f"/api/v1/party-admin/importaciones/{importacion['id']}/revertir"
    plan = cliente.post(ruta, headers=cabeceras, json={"simular": True})
    assert plan.status_code == 200, plan.text
    assert plan.json()["borrados"] == 1
    revertida = cliente.post(
        ruta, headers=cabeceras, json={"simular": False, "motivo": "fichero equivocado"}
    )
    assert revertida.status_code == 200, revertida.text
    otra_vez = cliente.post(ruta, headers=cabeceras, json={"simular": False, "motivo": "x"})
    assert otra_vez.status_code == 409


def test_traspasar_simula_y_exige_motivo(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    from services.party.modelos import Cuenta

    de, a = uuid4(), uuid4()
    db.add(Cuenta(tenant_id=tenant_id, nombre="Iota", clave_canonica="iota", owner_id=de))
    db.flush()
    ruta = "/api/v1/party-admin/transferir-propiedad"

    simulado = cliente.post(
        ruta, headers=cabeceras, json={"de_usuario": str(de), "a_usuario": str(a)}
    )
    assert simulado.status_code == 200, simulado.text
    assert simulado.json() == {"simulado": True, "movidos": {"cuentas": 1}, "total": 1}

    sin_motivo = cliente.post(
        ruta,
        headers=cabeceras,
        json={"de_usuario": str(de), "a_usuario": str(a), "simular": False},
    )
    assert sin_motivo.status_code == 422
    misma = cliente.post(
        ruta, headers=cabeceras, json={"de_usuario": str(de), "a_usuario": str(de)}
    )
    assert misma.status_code == 422

    hecho = cliente.post(
        ruta,
        headers=cabeceras,
        json={
            "de_usuario": str(de),
            "a_usuario": str(a),
            "simular": False,
            "motivo": "baja de la persona",
        },
    )
    assert hecho.status_code == 200, hecho.text
    assert db.query(Cuenta).one().owner_id == a


def test_el_lote_vive_junto_a_la_coleccion_y_publica_lo_que_admite(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """El front sólo conoce `/accounts`; el lote estaba en `/cuentas/masivo` y
    no lo llamaba nunca."""
    from services.party.modelos import Contacto

    contrato = cliente.app.openapi()
    esquema = contrato["paths"]["/api/v1/contacts/masivo"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]["$ref"].split("/")[-1]
    operaciones = contrato["components"]["schemas"][esquema]["properties"]["operacion"]["enum"]
    assert set(operaciones) == {"crear", "actualizar", "borrar"}

    a = Contacto(tenant_id=tenant_id, nombre="A", nombre_completo="A", clave_canonica="a")
    b = Contacto(tenant_id=tenant_id, nombre="B", nombre_completo="B", clave_canonica="b")
    db.add_all([a, b])
    db.flush()

    actualizado = cliente.post(
        "/api/v1/contacts/masivo",
        headers=cabeceras,
        json={
            "operacion": "actualizar",
            "elementos": [
                {"id": str(a.id), "cargo": "Compras"},
                {"id": str(uuid4()), "cargo": "X"},
            ],
        },
    )
    assert actualizado.status_code == 207, actualizado.text
    informe = actualizado.json()
    assert (informe["actualizados"], informe["fallidos"]) == (1, 1)
    assert informe["errores"][0]["fila"] == 2
    db.refresh(a)
    assert a.cargo == "Compras"

    borrado = cliente.post(
        "/api/v1/contacts/masivo",
        headers=cabeceras,
        json={"operacion": "borrar", "elementos": [{"id": str(b.id)}]},
    )
    assert borrado.status_code == 207, borrado.text
    assert borrado.json()["borrados"] == 1
    db.refresh(b)
    assert b.deleted_at is not None

    cuentas = cliente.post(
        "/api/v1/accounts/masivo",
        headers=cabeceras,
        json={"operacion": "crear", "elementos": [{"nombre": "Kappa S.L."}]},
    )
    assert cuentas.status_code == 207, cuentas.text
    assert cuentas.json()["creados"] == 1


def test_contactos_parecidos_para_el_lead(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    from services.party.modelos import Contacto

    db.add(
        Contacto(
            tenant_id=tenant_id,
            nombre="Lola",
            nombre_completo="Lola",
            clave_canonica="lola",
            email="lola@http.test",
        )
    )
    db.flush()
    r = cliente.get(
        "/api/v1/data-quality/contacts/duplicates?email=LOLA@http.test", headers=cabeceras
    )
    assert r.status_code == 200, r.text
    assert r.json()[0]["senales"] == ["email"]
    assert r.json()[0]["concluyente"] is True
