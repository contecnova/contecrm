"""De qué empresas es esta persona (CRM-01.01.02.02).

La relación contacto–cuenta es N:M: una persona puede serlo de varias
empresas, con papel distinto en cada una. Se podía **crear** el vínculo y se
podía **cerrar**, y no se podía **leer**: no existía ningún `GET`.

Una relación que no se consulta no existe para nadie. Dos consecuencias, y la
segunda no la vio nadie durante meses:

  · nadie podía contestar «¿de qué empresas es esta persona?», que es la
    pregunta por la que la relación se guarda;
  · y la ficha del contacto no pintaba su panel de cuentas, porque los paneles
    se construyen a partir de los `GET` que devuelven lista. No había ninguno,
    así que no había panel — y eso se lee como «esta persona no está en ninguna
    cuenta», que es lo contrario de lo que pasa.

Lo descubrió el sembrador de una empresa de demostración: seis peticiones
seguidas, las seis con `405 Method Not Allowed`.
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


def _cuenta(db: Any, tenant_id: UUID, nombre: str) -> UUID:
    from services.party.modelos import Cuenta

    fila = Cuenta(tenant_id=tenant_id, nombre=nombre, clave_canonica=nombre.lower())
    db.add(fila)
    db.flush()
    return fila.id


def _contacto(db: Any, tenant_id: UUID) -> UUID:
    from services.party.modelos import Contacto

    # `nombre_completo` y `clave_canonica` los compone el servicio al dar de
    # alta; creando el modelo a pelo hay que ponerlos, porque la tabla los
    # exige —y los exige a propósito: un contacto sin nombre compuesto no se
    # encuentra buscando.
    fila = Contacto(
        tenant_id=tenant_id,
        nombre="Ana",
        apellidos="Ruiz",
        nombre_completo="Ana Ruiz",
        clave_canonica="ana ruiz",
    )
    db.add(fila)
    db.flush()
    return fila.id


def test_salen_las_cuentas_con_el_papel_en_cada_una(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    contacto_id = _contacto(db, tenant_id)
    una = _cuenta(db, tenant_id, "Ferrosa")
    otra = _cuenta(db, tenant_id, "Austral")
    db.commit()

    cliente.post(
        f"/api/v1/contacts/{contacto_id}/cuentas",
        json={"cuenta_id": str(una), "rol": "decisor", "cargo": "Directora", "principal": True},
        headers=cabeceras,
    )
    cliente.post(
        f"/api/v1/contacts/{contacto_id}/cuentas",
        json={"cuenta_id": str(otra), "rol": "prescriptor"},
        headers=cabeceras,
    )

    r = cliente.get(f"/api/v1/contacts/{contacto_id}/cuentas", headers=cabeceras)
    assert r.status_code == 200, r.text[:400]
    filas = r.json()
    assert len(filas) == 2, filas
    # El principal primero: quien mira esta lista busca a quién llamar, no un
    # inventario.
    assert filas[0]["principal"] is True
    assert filas[0]["rol"] == "decisor"
    # El NOMBRE de la cuenta, no sólo su identificador: una lista de UUID no
    # contesta de qué empresas es esta persona.
    assert {f["cuenta"] for f in filas} == {"Ferrosa", "Austral"}
    assert all(f["vigente"] for f in filas)


def test_el_vinculo_cerrado_sigue_saliendo_y_se_distingue(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """«Ya no trabaja ahí» es justo lo que hay que saber antes de llamar.

    Esconderlo deja además el histórico de la cuenta sin sentido: las
    actividades de esa persona siguen colgando de ella.
    """
    contacto_id = _contacto(db, tenant_id)
    cuenta_id = _cuenta(db, tenant_id, "Ferrosa")
    db.commit()

    cliente.post(
        f"/api/v1/contacts/{contacto_id}/cuentas",
        json={"cuenta_id": str(cuenta_id), "rol": "decisor"},
        headers=cabeceras,
    )
    cliente.delete(
        f"/api/v1/contacts/{contacto_id}/cuentas/{cuenta_id}?motivo=cambio+de+empresa",
        headers=cabeceras,
    )

    filas = cliente.get(f"/api/v1/contacts/{contacto_id}/cuentas", headers=cabeceras).json()
    assert len(filas) == 1, filas
    assert filas[0]["vigente"] is False
    assert filas[0]["hasta"], "se ha cerrado el vínculo y no dice desde cuándo"


def test_un_contacto_que_no_existe_no_devuelve_una_lista_vacia(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """Vacío y «no existe» se leen igual y significan lo contrario."""
    r = cliente.get(f"/api/v1/contacts/{uuid4()}/cuentas", headers=cabeceras)
    assert r.status_code == 404, r.text[:300]
