"""Archivar de verdad, por criterio, y leer lo archivado (CRM-07.03.01.02).

Hasta el 09-11-2026 la única ruta de archivo —`POST /{servicio}/volumen/archivar`—
planificaba sobre filas tecleadas en el cuerpo: no movía nada, y `archivar` y
`consultar` del núcleo no los llamaba nadie. O sea, el histórico no se archivaba
nunca, y lo que nunca se archiva no se puede consultar.

Lo que estas pruebas fijan:

- El criterio es **la antigüedad por clase**, como ajuste del tenant: la de la
  clase si la tiene, la general si no.
- Simular no mueve nada; archivar saca la fila de la tabla viva y la deja en el
  archivo **con su identificador**.
- Lo archivado se encuentra por el registro del que cuelga: «lo archivado de
  esta cuenta» es la pregunta que se hace desde su ficha.
"""

from __future__ import annotations

import importlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.datos import archivado as arch
from crmcore.runtime import settings as rt
from sqlalchemy import select
from starlette.testclient import TestClient

from services.party.modelos import Actividad

pytestmark = pytest.mark.db


def _actividad(db: Any, tenant_id: UUID, *, hace_dias: int, cuenta_id: UUID) -> Actividad:
    fila = Actividad(
        tenant_id=tenant_id,
        tipo="tarea",
        asunto="Llamar",
        cuenta_id=cuenta_id,
        completada_at=datetime.now(timezone.utc) - timedelta(days=hace_dias),
    )
    db.add(fila)
    db.flush()
    return fila


def test_el_criterio_es_la_antiguedad_de_la_clase_o_la_general(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    import services.party.retencion  # noqa: F401 — declara «actividades»

    rt.fijar(db, "archivado_dias_por_defecto", 400, ambito="tenant", ambito_id=str(tenant_id))
    assert arch.dias_de_antiguedad(db, "actividades") == 400
    rt.fijar(
        db,
        "archivado_antiguedad_por_clase",
        {"actividades": 90},
        ambito="tenant",
        ambito_id=str(tenant_id),
    )
    assert arch.dias_de_antiguedad(db, "actividades") == 90

    cuenta = uuid4()
    _actividad(db, tenant_id, hace_dias=200, cuenta_id=cuenta)
    _actividad(db, tenant_id, hace_dias=10, cuenta_id=cuenta)
    clases = {c["clase"]: c for c in arch.clases_archivables(db, tenant_id)}
    # Sólo la de hace doscientos días pasa el corte de noventa.
    assert clases["actividades"]["candidatas"] == 1
    assert clases["actividades"]["dias"] == 90


def test_simular_no_mueve_y_archivar_conserva_el_id_y_se_consulta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    import services.party.retencion  # noqa: F401

    rt.fijar(
        db,
        "archivado_antiguedad_por_clase",
        {"actividades": 30},
        ambito="tenant",
        ambito_id=str(tenant_id),
    )
    cuenta = uuid4()
    vieja = _actividad(db, tenant_id, hace_dias=100, cuenta_id=cuenta)
    reciente = _actividad(db, tenant_id, hace_dias=1, cuenta_id=cuenta)
    vieja_id, reciente_id = vieja.id, reciente.id

    simulado = arch.archivar_por_criterio(db, tenant_id=tenant_id, clase="actividades")
    assert simulado["simulado"] is True and simulado["candidatas"] == 1
    assert db.get(Actividad, vieja_id) is not None

    hecho = arch.archivar_por_criterio(db, tenant_id=tenant_id, clase="actividades", simular=False)
    assert hecho["archivadas"] == 1
    db.expire_all()
    assert db.execute(select(Actividad).where(Actividad.id == vieja_id)).first() is None
    assert db.get(Actividad, reciente_id) is not None

    por_id = arch.consultar(db, tenant_id, registro_id=vieja_id)
    assert [f["registro_id"] for f in por_id["filas"]] == [str(vieja_id)]
    # Lo archivado de la cuenta: la fila la nombra en `cuenta_id`.
    de_la_cuenta = arch.consultar(db, tenant_id, relacionado_con=cuenta)
    assert de_la_cuenta["cuantas"] == 1
    assert de_la_cuenta["filas"][0]["contenido"]["asunto"] == "Llamar"
    # Y una cuenta cualquiera no trae nada: el filtro mira el valor, no «algo».
    assert arch.consultar(db, tenant_id, relacionado_con=uuid4())["cuantas"] == 0


def test_lo_archivado_de_un_tenant_no_lo_ve_otro(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID
) -> None:
    import services.party.retencion  # noqa: F401

    rt.fijar(
        db,
        "archivado_antiguedad_por_clase",
        {"actividades": 30},
        ambito="tenant",
        ambito_id=str(tenant_id),
    )
    cuenta = uuid4()
    _actividad(db, tenant_id, hace_dias=100, cuenta_id=cuenta)
    arch.archivar_por_criterio(db, tenant_id=tenant_id, clase="actividades", simular=False)
    assert arch.consultar(db, otro_tenant_id, relacionado_con=cuenta)["cuantas"] == 0


# ── Por la ruta, que es como lo usa la pantalla ──────────────────────────


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


def test_por_http_se_fija_el_criterio_se_archiva_y_se_lee(
    db: Any, tenant_id: UUID, cliente: Any, cabeceras: dict[str, str]
) -> None:
    cuenta = uuid4()
    fila = Actividad(
        tenant_id=tenant_id,
        tipo="tarea",
        asunto="Revisar contrato",
        cuenta_id=cuenta,
        completada_at=datetime.now(timezone.utc) - timedelta(days=60),
    )
    db.add(fila)
    db.commit()
    base = "/api/v1/party/volumen/archivo"

    r = cliente.put(f"{base}/clases/actividades", json={"dias": 30}, headers=cabeceras)
    assert r.status_code == 200, r.text
    assert r.json()["dias"] == 30

    r = cliente.get(f"{base}/clases", headers=cabeceras)
    assert r.status_code == 200, r.text
    clases = {c["clase"]: c for c in r.json()["clases"]}
    assert r.json()["hay_archivo"] is True
    assert clases["actividades"]["candidatas"] == 1

    r = cliente.post(
        f"{base}/archivar", json={"clase": "actividades", "simular": False}, headers=cabeceras
    )
    assert r.status_code == 200, r.text
    assert r.json()["archivadas"] == 1

    r = cliente.get(base, params={"relacionado_con": str(cuenta)}, headers=cabeceras)
    assert r.status_code == 200, r.text
    assert r.json()["cuantas"] == 1
    assert r.json()["filas"][0]["registro_id"] == str(fila.id)

    r = cliente.get(f"{base}/resumen", headers=cabeceras)
    assert r.json()["total"] >= 1

    # Y vuelve: el archivo se consulta, pero lo que se trabaja vive en la tabla.
    r = cliente.post(f"/api/v1/party/volumen/desarchivar/{fila.id}", headers=cabeceras)
    assert r.status_code == 200, r.text
    r = cliente.get(base, params={"relacionado_con": str(cuenta)}, headers=cabeceras)
    assert r.json()["cuantas"] == 0
