"""El organigrama se fija desde Administrar › Organigrama (CRM-00.03.05.07).

Medido el 10-11-2026: nada escribía el superior de nadie —SCIM ignoraba el
`manager`, el SSO no lo trae y no había pantalla—, y además el evento que lo
replica llevaba una clave de deduplicación fija por persona, así que los
consumidores aplicaban el primer cambio de cada una y descartaban el resto.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterator
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


@pytest.fixture
def identidad(db: Any) -> Iterator[Any]:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        with TestClient(importlib.import_module("services.identity.main").app) as cli:
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


def _alta(identidad: Any, cabeceras: dict[str, str], nombre: str) -> str:
    r = identidad.post(
        "/api/v1/usuarios",
        headers=cabeceras,
        json={"email": f"{nombre}-{uuid4().hex[:6]}@example.com", "nombre": nombre},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _superior(identidad: Any, cabeceras: dict[str, str], quien: str, de: str | None) -> Any:
    return identidad.put(
        f"/api/v1/organigrama/{quien}/superior", headers=cabeceras, json={"superior_id": de}
    )


def test_fijar_el_superior_lo_publica_cada_vez_crm_00_03_05_07(
    db: Any, identidad: Any, cabeceras: dict[str, str], tenant_id: UUID
) -> None:
    from crmcore.bus.modelos import EventoSaliente
    from sqlalchemy import select

    jefa, otra, ana = (_alta(identidad, cabeceras, n) for n in ("jefa", "otra", "ana"))

    r = _superior(identidad, cabeceras, ana, jefa)
    assert r.status_code == 200, r.text
    assert r.json()["superior_id"] == jefa and r.json()["origen"] == "manual"
    assert _superior(identidad, cabeceras, ana, otra).status_code == 200

    arbol = identidad.get("/api/v1/organigrama", headers=cabeceras).json()
    suya = next(p for p in arbol["personas"] if p["usuario_id"] == ana)
    assert suya["superior_id"] == otra and suya["origen"] == "manual"

    # Cada cambio es un hecho distinto para el bus: con la clave fija de antes,
    # el segundo se descartaba en el consumidor y el ascenso no llegaba.
    eventos = [
        e
        for e in db.execute(
            select(EventoSaliente).where(
                EventoSaliente.tenant_id == tenant_id,
                EventoSaliente.tipo == "user.org.changed",
                EventoSaliente.subject_id == ana,
            )
        ).scalars()
    ]
    superiores = [e.sobre["data"]["superior_id"] for e in eventos]
    assert jefa in superiores and otra in superiores, superiores
    assert len({e.dedup_key for e in eventos}) == len(eventos), "claves repetidas"
    # Y el superior también consta: la cadena replicada se corta en quien no.
    assert db.execute(
        select(EventoSaliente).where(
            EventoSaliente.tipo == "user.org.changed", EventoSaliente.subject_id == otra
        )
    ).first()


def test_un_circulo_no_se_puede_cerrar_ni_moviendo_el_equipo_crm_00_03_05_07(
    identidad: Any, cabeceras: dict[str, str]
) -> None:
    jefa, mando, ana, nadie = (
        _alta(identidad, cabeceras, n) for n in ("jefa", "mando", "ana", "nadie")
    )
    assert _superior(identidad, cabeceras, mando, jefa).status_code == 200
    assert _superior(identidad, cabeceras, ana, mando).status_code == 200

    r = _superior(identidad, cabeceras, jefa, ana)
    assert r.status_code == 409 and r.json()["error_code"] == "organigrama.ciclo", r.text

    # Pasar el equipo de la jefa a alguien de dentro de ese equipo: no se mueve nadie.
    r = identidad.post(f"/api/v1/organigrama/{jefa}/equipo", headers=cabeceras, json={"a_id": ana})
    assert r.status_code == 409, r.text
    arbol = identidad.get("/api/v1/organigrama", headers=cabeceras).json()["personas"]
    assert next(p for p in arbol if p["usuario_id"] == mando)["superior_id"] == jefa

    r = identidad.post(
        f"/api/v1/organigrama/{jefa}/equipo", headers=cabeceras, json={"a_id": nadie}
    )
    assert r.status_code == 200 and r.json()["movidas"] == 1, r.text
    arbol = identidad.get("/api/v1/organigrama", headers=cabeceras).json()["personas"]
    assert next(p for p in arbol if p["usuario_id"] == mando)["superior_id"] == nadie


def test_el_manager_del_directorio_y_lo_ajustado_a_mano_crm_00_03_05_07(
    db: Any,
    identidad: Any,
    cabeceras: dict[str, str],
    tenant_id: UUID,
    contexto_tenant: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from crmcore.db.uow import unidad_de_trabajo

    from services.identity import organigrama, scim

    jefa, otra, ana = (_alta(identidad, cabeceras, n) for n in ("jefa", "otra", "ana"))
    camino = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User:manager"

    def patch(valor: Any) -> Any:
        with unidad_de_trabajo(tenant_id) as uow:
            _, m = scim.aplicar_patch(
                uow,
                UUID(ana),
                tenant_id,
                {"Operations": [{"op": "replace", "path": camino, "value": valor}]},
            )
            return m.superior_id, m.superior_origen

    assert patch(jefa) == (UUID(jefa), "scim")

    # Ajustado a mano con el directorio mandando: el siguiente envío lo pisa.
    assert _superior(identidad, cabeceras, ana, otra).status_code == 200
    assert patch({"value": jefa}) == (UUID(jefa), "scim")

    # Con «lo de a mano manda», el directorio ya no lo cambia.
    assert _superior(identidad, cabeceras, ana, otra).status_code == 200
    monkeypatch.setattr(
        organigrama,
        "_ajuste",
        lambda clave, db: False if clave == "organigrama_externo_manda" else 5000,
    )
    assert patch(jefa) == (UUID(otra), "manual")
