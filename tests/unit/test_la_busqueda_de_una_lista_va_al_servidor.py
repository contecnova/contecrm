"""Buscar en una lista es buscar en TODAS sus filas, no en las cargadas.

El buscador de cada lista y el selector de un campo que apunta a otro registro
filtraban en el navegador las filas ya traídas —cincuenta, o doscientas—. Con
más clientes que eso, el que se buscaba no salía y la pantalla decía «nada con
eso» de un registro que existe. Medido el 10-11-2026.

Ahora `?buscar=` lo aplica el servidor, en los campos que nombran el registro,
para todo listado que pasa por `aplicar_filtros_de_la_url`. Aquí se prueba
sobre los leads —escritos a mano, con sus filtros propios— y sobre las
visitas, que no tienen ningún campo de nombre y tienen que decirlo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


def _cliente(modulo_main: str) -> Any:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        with TestClient(importlib.import_module(modulo_main).app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


@pytest.fixture
def ventas(db: Any) -> Any:
    yield from _cliente("services.sales.main")


@pytest.fixture
def clientes(db: Any) -> Any:
    yield from _cliente("services.party.main")


@pytest.fixture
def cabeceras(tenant_id: UUID) -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import H_PERMISOS, H_ROLES, H_TENANT, H_USER, firmar_cabeceras_internas

    return firmar_cabeceras_internas(
        {H_TENANT: str(tenant_id), H_USER: str(uuid4()), H_PERMISOS: "*:*", H_ROLES: "admin"},
        get_settings().secret_key.get_secret_value(),
    )


@pytest.fixture
def muchos_leads(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Sesenta leads, y el que se busca es el MÁS ANTIGUO: con la lista
    ordenada por fecha de alta, queda fuera de la primera página de cincuenta."""
    from services.sales.modelos import Lead

    base = datetime(2026, 11, 1, tzinfo=timezone.utc)
    db.add(
        Lead(
            tenant_id=tenant_id,
            nombre="Zacarías",
            apellidos="Quintana Ruiz",
            empresa="Talleres 50% Norte",
            created_at=base,
        )
    )
    for i in range(60):
        db.add(
            Lead(
                tenant_id=tenant_id,
                nombre=f"Persona {i}",
                empresa=f"Empresa {i}",
                created_at=base + timedelta(minutes=i + 1),
            )
        )
    db.flush()


def _nombres(r: Any) -> list[str]:
    assert r.status_code == 200, r.text
    return [f"{f.get('nombre')} {f.get('apellidos') or ''}".strip() for f in r.json()["items"]]


def test_encuentra_lo_que_no_esta_en_la_primera_pagina(
    ventas: Any, cabeceras: dict[str, str], muchos_leads: None
) -> None:
    # La comprobación que hace honesta a la de abajo: sin buscar, no sale.
    primera = _nombres(ventas.get("/api/v1/leads?limite=50", headers=cabeceras))
    assert len(primera) == 50
    assert "Zacarías Quintana Ruiz" not in primera

    r = ventas.get("/api/v1/leads?buscar=quintana", headers=cabeceras)
    assert _nombres(r) == ["Zacarías Quintana Ruiz"]


def test_cada_palabra_puede_estar_en_un_campo_distinto(
    ventas: Any, cabeceras: dict[str, str], muchos_leads: None
) -> None:
    """«zacarías quintana»: el nombre en una columna y el apellido en otra."""
    r = ventas.get(f"/api/v1/leads?buscar={quote('ZACARÍAS quintana')}", headers=cabeceras)
    assert _nombres(r) == ["Zacarías Quintana Ruiz"]
    # Y las dos tienen que estar: no es un «o».
    assert _nombres(ventas.get("/api/v1/leads?buscar=zacarias%20persona", headers=cabeceras)) == []


def test_el_tanto_por_ciento_no_es_un_comodin(
    ventas: Any, cabeceras: dict[str, str], muchos_leads: None
) -> None:
    """«50%» busca eso, no «50 y cualquier cosa»: sin escapar, `Empresa 50`
    —que no lleva el símbolo— también saldría."""
    r = ventas.get(f"/api/v1/leads?buscar={quote('50%')}", headers=cabeceras)
    assert _nombres(r) == ["Zacarías Quintana Ruiz"]


def test_un_listado_sin_campos_de_nombre_lo_dice(clientes: Any, cabeceras: dict[str, str]) -> None:
    """Las visitas no tienen nada que se teclee para encontrarlas. Contestar
    con todas las filas parecería haber encontrado; se dice, y la pantalla
    busca en lo cargado."""
    r = clientes.get("/api/v1/visitas?buscar=algo", headers=cabeceras)
    assert r.status_code == 422, r.text
    assert r.json()["error_code"] == "listado.sin_busqueda"
