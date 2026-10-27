"""Registrar una solicitud de derechos por su ruta (CRM-02.04.02).

`_solicitud_out` devolvía ocho campos y el contrato declara catorce. Uno de
los que faltaban, `created_at`, es **obligatorio**, así que el alta respondía
500 siempre —con la fila ya escrita en la base—: el interesado quedaba
registrado y quien lo registró veía un error del sistema. A la tercera se deja
de usar la pantalla y las solicitudes se llevan por correo, que es justo lo que
esto existe para evitar.

Los otros cinco no reventaban porque tienen valor por defecto, y por eso
llevaban meses saliendo vacíos: de quién es la solicitud, quién la lleva, por
dónde entró y —lo que pide el regulador— qué se resolvió y con qué prueba.

Lo descubrió el sembrador de una empresa de demostración: cinco altas seguidas,
las cinco en 500. Ninguna prueba en rojo, porque todas las que había llamaban a
la **función** del servicio y no a la ruta.
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


def test_una_solicitud_se_registra_y_vuelve_entera(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    r = cliente.post(
        "/api/v1/data-subject-requests",
        json={
            "tipo": "acceso",
            "email_solicitante": "ana@example.com",
            "canal_entrada": "portal",
        },
        headers=cabeceras,
    )
    assert r.status_code == 201, r.text[:400]
    cuerpo = r.json()

    # Campo a campo, con el nombre que declara el contrato: que falte uno es
    # exactamente el fallo que esto existe para cazar, y el que faltaba era
    # obligatorio.
    for campo in (
        "id",
        "email_solicitante",
        "tipo",
        "estado",
        "recibida_at",
        "vence_at",
        "resuelta_at",
        "dias_restantes",
        "contacto_id",
        "responsable_id",
        "canal_entrada",
        "resolucion",
        "evidencia",
        "created_at",
    ):
        assert campo in cuerpo, f"el contrato declara «{campo}» y la ruta no lo manda"

    assert cuerpo["estado"] == "recibida"
    assert cuerpo["canal_entrada"] == "portal"
    # El plazo legal corre desde que llega, no desde que alguien la tramita.
    assert cuerpo["dias_restantes"] > 0


def test_la_solicitud_recuerda_de_quien_es(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sin el contacto, la lista de solicitudes no se puede atar a nadie."""
    from services.party.modelos import Contacto

    contacto = Contacto(
        tenant_id=tenant_id,
        nombre="Ana",
        apellidos="Ruiz",
        nombre_completo="Ana Ruiz",
        clave_canonica="ana ruiz",
    )
    db.add(contacto)
    db.commit()

    r = cliente.post(
        "/api/v1/data-subject-requests",
        json={
            "tipo": "supresion",
            "email_solicitante": "ana@example.com",
            "contacto_id": str(contacto.id),
        },
        headers=cabeceras,
    )
    assert r.status_code == 201, r.text[:400]
    assert r.json()["contacto_id"] == str(contacto.id)


def test_y_el_listado_pasa_por_el_mismo_mapeador(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """Si el mapeador se queda corto no revienta sólo el alta: deja de poder
    verse ninguna, que es cómo una pantalla entera se queda en blanco."""
    cliente.post(
        "/api/v1/data-subject-requests",
        json={"tipo": "portabilidad", "email_solicitante": "luis@example.com"},
        headers=cabeceras,
    )
    r = cliente.get("/api/v1/data-subject-requests", headers=cabeceras)
    assert r.status_code == 200, r.text[:400]
    filas = r.json()["items"]
    assert filas, "se ha registrado una solicitud y el listado sale vacío"
    assert "created_at" in filas[0]
