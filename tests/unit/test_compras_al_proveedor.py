"""Compras al proveedor, de punta a punta por HTTP.

Once cálculos de coste y de proveedor estaban escritos y no tenían datos: cada
ruta recibía del que llamaba las ofertas, la capacidad o las entregas. Aquí se
comprueba que, con los hechos guardados donde nacen, cada cálculo los lee:

  petición → respuestas → quién no ha contestado → comparación (con la
  homologación y los papeles de verdad) → adjudicación (que compromete
  capacidad y fija la fecha) → entrega e incidencia → evaluación medida, rappel
  con lo comprado, contrato con lo comprometido, riesgo de dependencia y baja.

Y lo que no debe pasar: responder quien no fue invitado, adjudicar a quien no
está homologado, comprometer por encima de la capacidad sin decir por qué.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.fechas import hoy
from starlette.testclient import TestClient

from tests.unit.test_reverificacion_y_mfa_adaptativa import _cabeceras

pytestmark = pytest.mark.db


@pytest.fixture
def party(monkeypatch: Any, db: Any) -> Any:
    import importlib

    from crmcore.config import get_settings
    from crmcore.tareas import RelevoDeTareas

    async def _no_correr(self: Any) -> None:
        return None

    monkeypatch.setattr(RelevoDeTareas, "correr", _no_correr)
    monkeypatch.setenv("OUTBOX_ENABLED", "false")
    get_settings.cache_clear()
    try:
        with TestClient(importlib.import_module("services.party.main").app) as cli:
            yield cli
    finally:
        get_settings.cache_clear()


def _proveedor(cli: Any, cab: dict[str, str], nombre: str, *, homologar: str = "") -> str:
    alta = cli.post("/api/v1/proveedores", headers=cab, json={"nombre": nombre})
    assert alta.status_code == 201, alta.text
    cuenta = alta.json()["id"]
    if homologar:
        h = cli.post(
            f"/api/v1/proveedores/{cuenta}/homologacion",
            headers=cab,
            json={"categoria": homologar, "valida_hasta": str(hoy() + timedelta(days=365))},
        )
        assert h.status_code in (200, 201), h.text
    return str(cuenta)


def test_de_la_peticion_a_la_evaluacion_con_hechos(party: Any, tenant_id: UUID) -> None:
    cli, cab = party, _cabeceras(tenant_id)
    bueno = _proveedor(cli, cab, "Laboratorio Norte", homologar="ensayos")
    barato = _proveedor(cli, cab, "Ensayos Baratos")  # sin homologar
    callado = _proveedor(cli, cab, "Laboratorio Callado", homologar="ensayos")

    peticion = cli.post(
        "/api/v1/compras/peticiones",
        headers=cab,
        json={
            "categoria": "ensayos",
            "proveedores": [bueno, barato, callado],
            "fecha_limite": str(hoy() + timedelta(days=7)),
            "descripcion": "Ensayo de vibración",
            "cantidad": "10",
            "oportunidad_id": str(uuid4()),
        },
    )
    assert peticion.status_code == 201, peticion.text
    pid = peticion.json()["id"]

    # A quien no se le pidió no contesta.
    intruso = _proveedor(cli, cab, "Intruso", homologar="ensayos")
    assert (
        cli.post(
            f"/api/v1/compras/peticiones/{pid}/respuestas",
            headers=cab,
            json={"proveedor_id": intruso, "coste_unitario": "10"},
        ).status_code
        == 422
    )

    r_bueno = cli.post(
        f"/api/v1/compras/peticiones/{pid}/respuestas",
        headers=cab,
        json={"proveedor_id": bueno, "coste_unitario": "120", "plazo_dias": 5},
    ).json()["id"]
    cli.post(
        f"/api/v1/compras/peticiones/{pid}/respuestas",
        headers=cab,
        json={"proveedor_id": barato, "coste_unitario": "80", "plazo_dias": 3},
    )

    contestado = cli.post(
        f"/api/v1/compras/peticiones/{pid}/quien-ha-contestado", headers=cab
    ).json()
    assert [p["nombre"] for p in contestado["sin_contestar"]] == ["Laboratorio Callado"]

    # La más barata no está homologada: se dice, y la elegida es la otra.
    comparacion = cli.post(f"/api/v1/compras/peticiones/{pid}/comparar", headers=cab).json()
    assert comparacion["elegida"]["nombre"] == "Laboratorio Norte"
    assert "Ensayos Baratos" in comparacion["aviso"]

    # Adjudicar a quien no está homologado se niega.
    respuestas = cli.get(f"/api/v1/compras/peticiones/{pid}/respuestas", headers=cab).json()
    r_barato = next(r["id"] for r in respuestas["items"] if r["proveedor_id"] == barato)
    assert (
        cli.post(
            f"/api/v1/compras/respuestas/{r_barato}/adjudicar", headers=cab, json={}
        ).status_code
        == 409
    )

    # Capacidad: 12 contratadas; adjudicar 10 deja 2, y pedir 5 más sin forzar se niega.
    capacidad = cli.post(
        "/api/v1/compras/capacidades",
        headers=cab,
        json={
            "proveedor_id": bueno,
            "categoria": "ensayos",
            "desde": str(hoy() - timedelta(days=1)),
            "hasta": str(hoy() + timedelta(days=90)),
            "contratada": "12",
        },
    ).json()["id"]
    adjudicada = cli.post(f"/api/v1/compras/respuestas/{r_bueno}/adjudicar", headers=cab, json={})
    assert adjudicada.status_code == 200, adjudicada.text
    assert adjudicada.json()["fecha_comprometida"]
    libre = cli.post(f"/api/v1/compras/capacidades/{capacidad}/disponible", headers=cab).json()
    assert Decimal(libre["libre"]) == Decimal("2")
    assert (
        cli.post(
            f"/api/v1/compras/capacidades/{capacidad}/reservar",
            headers=cab,
            json={"cantidad": "5"},
        ).status_code
        == 409
    )

    # Contrato: lo comprometido sin entregar es lo que manda.
    contrato = cli.post(
        "/api/v1/compras/contratos",
        headers=cab,
        json={"proveedor_id": bueno, "vigente_hasta": str(hoy() + timedelta(days=2))},
    ).json()["id"]
    estado = cli.post(f"/api/v1/compras/contratos/{contrato}/estado", headers=cab)
    assert estado.status_code == 200, estado.text
    assert "Ensayo de vibración" in str(estado.json())

    # Baja: no, tiene trabajo comprometido.
    baja = cli.post(f"/api/v1/proveedores/{bueno}/baja-con-lo-comprometido", headers=cab).json()
    assert baja["puede"] is False

    # Entrega tarde y más cara, con una incidencia grave: la evaluación lo mide.
    entrega = cli.post(
        f"/api/v1/compras/respuestas/{r_bueno}/entrega",
        headers=cab,
        json={"entregada_el": str(hoy() + timedelta(days=60)), "coste_final": "130"},
    )
    assert entrega.status_code == 200, entrega.text
    cli.post(
        f"/api/v1/compras/respuestas/{r_bueno}/incidencia",
        headers=cab,
        json={"gravedad": "alta", "descripcion": "Informe incompleto"},
    )
    evaluacion = cli.post(f"/api/v1/proveedores/{bueno}/evaluacion-medida", headers=cab).json()
    assert evaluacion["medible"] is True
    assert evaluacion["pct_en_plazo"] == 0.0
    assert evaluacion["incidencias_graves"] == 1
    assert Decimal(evaluacion["desvio_coste_medio"]) == Decimal("10")

    # Rappel con lo comprado de verdad: 10 × 130 al coste final.
    rappel = cli.post(
        "/api/v1/compras/rappels",
        headers=cab,
        json={
            "proveedor_id": bueno,
            "desde": str(hoy() - timedelta(days=30)),
            "hasta": str(hoy() + timedelta(days=30)),
            "tramos": [{"desde": 1000, "pct": 2}],
        },
    ).json()["id"]
    estimado = cli.post(f"/api/v1/compras/rappels/{rappel}/estimado", headers=cab).json()
    assert Decimal(estimado["compra_acumulada"]) == Decimal("1300")

    # Riesgo: todo lo comprado es de uno, y hay alternativa homologada (el callado).
    riesgo = cli.post("/api/v1/proveedores/riesgo-medido", headers=cab).json()
    assert riesgo["medible"] is True
    fila = riesgo["proveedores"][0]
    assert fila["nombre"] == "Laboratorio Norte"
    assert fila["pct_del_volumen"] == 100.0
    assert fila["alternativas_homologadas"] >= 1


def test_el_alcance_se_declara_y_responde_por_que_no(party: Any, tenant_id: UUID) -> None:
    cli, cab = party, _cabeceras(tenant_id)
    proveedor = _proveedor(cli, cab, "Instalaciones Sur")
    alcance = cli.post(
        "/api/v1/compras/alcances",
        headers=cab,
        json={
            "proveedor_id": proveedor,
            "alcance": {"categoria": ["climatizacion"], "geografia": ["sevilla"]},
        },
    )
    assert alcance.status_code == 201, alcance.text
    aid = alcance.json()["id"]
    no = cli.post(
        f"/api/v1/compras/alcances/{aid}/puede-servir",
        headers=cab,
        json={"categoria": "climatizacion", "geografia": "madrid"},
    ).json()
    assert no["puede"] is False
    si = cli.post(
        f"/api/v1/compras/alcances/{aid}/puede-servir",
        headers=cab,
        json={"categoria": "climatizacion", "geografia": "sevilla"},
    ).json()
    assert si["puede"] is True


def test_lo_de_compras_de_un_tenant_no_lo_ve_otro(party: Any, tenant_id: UUID) -> None:
    cli, cab = party, _cabeceras(tenant_id)
    proveedor = _proveedor(cli, cab, "Propio", homologar="ensayos")
    pid = cli.post(
        "/api/v1/compras/peticiones",
        headers=cab,
        json={
            "categoria": "ensayos",
            "proveedores": [proveedor],
            "fecha_limite": str(hoy() + timedelta(days=3)),
        },
    ).json()["id"]
    ajeno = _cabeceras(uuid4())
    assert cli.get(f"/api/v1/compras/peticiones/{pid}", headers=ajeno).status_code == 404
    assert cli.post(f"/api/v1/compras/peticiones/{pid}/comparar", headers=ajeno).status_code == 404
