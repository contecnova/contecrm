"""Las rutas nuevas de marketing, por la puerta de verdad (CRM-02.01.01.09,
CRM-02.02.02.01, CRM-02.02.02.04, CRM-02.02.02.05).

Las pantallas del recorrido y de la audiencia declaran la forma de estas
respuestas; aquí se piden por HTTP para que, si el servidor deja de mandar un
campo, se vea en rojo y no en una pantalla vacía.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


@pytest.fixture
def cliente(db: Any) -> Any:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        modulo = importlib.import_module("services.marketing.main")
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
    from crmcore.http.deps import H_PERMISOS, H_ROLES, H_TENANT, H_USER, firmar_cabeceras_internas

    return firmar_cabeceras_internas(
        {H_TENANT: str(tenant_id), H_USER: str(uuid4()), H_PERMISOS: "*:*", H_ROLES: "admin"},
        get_settings().secret_key.get_secret_value(),
    )


def test_el_lienzo_su_prueba_y_sus_inscritos_por_http(
    cliente: TestClient, cabeceras: dict[str, str]
) -> None:
    nodos = {
        "ab": {
            "tipo": "prueba",
            "variantes": [
                {"clave": "a", "peso": 50, "siguiente": "fin"},
                {"clave": "b", "peso": 50, "siguiente": "fin"},
            ],
        },
        "fin": {"tipo": "fin"},
    }
    r = cliente.post(
        "/api/v1/recorridos",
        json={"clave": f"r{uuid4().hex[:6]}", "nombre": "R", "nodos": nodos, "inicio": "ab"},
        headers=cabeceras,
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]

    lienzo = cliente.get(f"/api/v1/recorridos/{rid}/lienzo", headers=cabeceras).json()
    assert {
        "nodos",
        "inicio",
        "por_cuenta",
        "estado",
        "version",
        "inscritos",
        "comportamientos",
    } <= set(lienzo)

    nodos["ab"]["pos"] = {"x": 10, "y": 10}
    r = cliente.put(
        f"/api/v1/recorridos/{rid}/lienzo",
        json={"nodos": nodos, "inicio": "ab", "por_cuenta": True},
        headers=cabeceras,
    )
    assert r.status_code == 200, r.text
    assert cliente.get(f"/api/v1/recorridos/{rid}/lienzo", headers=cabeceras).json()["por_cuenta"]

    prueba = cliente.get(f"/api/v1/recorridos/{rid}/prueba/ab", headers=cabeceras).json()
    assert {
        "variantes",
        "ganadora",
        "significativa",
        "p_valor",
        "alfa",
        "minimo",
        "ganadora_aplicada",
        "aviso",
    } <= set(prueba)
    assert cliente.get(f"/api/v1/recorridos/{rid}/inscritos", headers=cabeceras).json() == []


def test_la_audiencia_por_http_con_su_historial(
    cliente: TestClient, cabeceras: dict[str, str]
) -> None:
    seg = cliente.post(
        "/api/v1/segmentos",
        json={
            "clave": f"s{uuid4().hex[:6]}",
            "nombre": "S",
            "objeto": "contacto",
            "definicion": {"atributo": "contacto.pais", "operador": "=", "valor": "ES"},
        },
        headers=cabeceras,
    )
    assert seg.status_code == 201, seg.text
    r = cliente.post(
        "/api/v1/audiencias-publicitarias",
        json={"nombre": "A", "segmento_id": seg.json()["id"], "conexion_id": str(uuid4())},
        headers=cabeceras,
    )
    assert r.status_code == 201, r.text
    ficha = cliente.get(
        f"/api/v1/audiencias-publicitarias/{r.json()['id']}", headers=cabeceras
    ).json()
    assert {"estado", "miembros", "id_externo", "historial", "minimo", "finalidad_exigida"} <= set(
        ficha
    )
    # Un segmento vacío no llama a nadie: se queda pequeña y lo dice.
    s = cliente.post(
        f"/api/v1/audiencias-publicitarias/{r.json()['id']}/sincronizar", headers=cabeceras
    ).json()
    assert s["estado"] == "pequena" and s["porque"]


def test_los_envios_y_la_salida_por_http(cliente: TestClient, cabeceras: dict[str, str]) -> None:
    lista = cliente.get(
        f"/api/v1/envios-programados?origen=campana&origen_id={uuid4()}", headers=cabeceras
    ).json()
    assert {"envios", "programados", "a_la_hora_general", "que_significa"} <= set(lista)
    salida = cliente.get("/api/v1/correo/salida", headers=cabeceras).json()
    assert {"promocional", "transaccional", "separados", "mismo_flujo", "aviso"} <= set(salida)
    assert "_config" not in salida["promocional"]
