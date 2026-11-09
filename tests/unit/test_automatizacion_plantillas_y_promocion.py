"""Plantillas que se instalan y promoción que guarda (CRM-00.03.03.09, .08).

Las dos devolvían un JSON y no hacían nada: `instalar` contestaba «instaladas»
sin crear ninguna —y había que teclear la plantilla en JSON—, y `promocionar`
devolvía la definición limpia sin guardarla en ningún sitio. Lo que se prueba:

  · cada plantilla de la biblioteca **valida con el motor** y se engancha a lo
    que de verdad existe: un evento del catálogo, una acción con quien la
    atienda;
  · instalar **crea la automatización, apagada**, y no pisa la que ya hay;
  · promover desde un sandbox **crea o actualiza de verdad**, primero en seco,
    llega apagado y deja su apunte en la auditoría.
"""

from __future__ import annotations

import importlib
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

from services.automation.plantillas import CLAVES

pytestmark = pytest.mark.db


# ── La biblioteca ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("clave", CLAVES)
def test_cada_plantilla_valida_con_el_motor(clave: str) -> None:
    """Una plantilla que se instala bien y falla la primera vez que se dispara
    es peor que no tenerla."""
    from crmcore.bus.comandos import MANEJADORES

    import services.party.comandos  # noqa: F401 — registran quién atiende cada acción
    import services.sales.comandos  # noqa: F401
    import services.service.comandos  # noqa: F401
    from services.automation import plantillas, validacion

    plantilla = plantillas.POR_CLAVE[clave]
    definicion = plantillas.definicion(plantilla, responsable=str(uuid4()))
    assert validacion.problemas_de(definicion, estricta=True) == []
    assert definicion["activa"] is False

    # Lo que escribe en otro servicio tiene quien lo atienda: un comando sin
    # manejador se guarda, se valida y no hace nada.
    verbos = {"crear_registro": "crear", "asignar": "asignar", "actualizar_registro": "actualizar"}
    for accion in definicion["acciones"]:
        verbo = verbos.get(accion["tipo"])
        if verbo:
            objeto = accion["parametros"]["objeto"]
            manejador = MANEJADORES.get(f"{objeto}.{verbo}")
            assert manejador is not None, f"{clave}: nadie atiende {verbo} {objeto}"
            # Y con campos que el dueño acepta.
            campos = set(accion["parametros"]) - {"objeto", "registro_id", "usuario_id"}
            permitidos = manejador.campos_permitidos
            assert campos <= set(permitidos), f"{clave}: {campos - set(permitidos)}"


def test_las_que_reparten_trabajo_piden_a_quien() -> None:
    from crmcore.errors import ErrorValidacion

    from services.automation import plantillas, validacion

    plantilla = plantillas.POR_CLAVE["lead_nuevo_al_responsable"]
    definicion = plantillas.definicion(plantilla, responsable=None)
    with pytest.raises(ErrorValidacion):
        validacion.exigir(definicion, estricta=True)


@pytest.fixture
def cliente(db: Any) -> Any:
    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        with TestClient(importlib.import_module("services.automation.main").app) as cli:
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


def test_instalar_crea_la_automatizacion_apagada_y_no_pisa(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    lista = cliente.get("/api/v1/automatizaciones/plantillas", headers=cabeceras)
    assert lista.status_code == 200, lista.text[:300]
    items = lista.json()["items"]
    assert len(items) >= 4 and not any(i["instalada"] for i in items)

    r = cliente.post(
        "/api/v1/automatizaciones/plantillas/instalar",
        json={"clave": "contrato_a_punto_de_vencer"},
        headers=cabeceras,
    )
    assert r.status_code == 200, r.text[:300]
    instalada = r.json()
    ficha = cliente.get(
        f"/api/v1/automatizaciones/{instalada['automatizacion_id']}", headers=cabeceras
    ).json()
    assert ficha["activa"] is False
    assert (ficha["disparador"], ficha["objetivo"]) == ("evento", "contract.renewal.due")

    # Otra vez, con el mismo nombre: no se pisa.
    r = cliente.post(
        "/api/v1/automatizaciones/plantillas/instalar",
        json={"clave": "contrato_a_punto_de_vencer"},
        headers=cabeceras,
    )
    assert r.status_code == 409, r.text[:300]
    # Con otro, sí.
    r = cliente.post(
        "/api/v1/automatizaciones/plantillas/instalar",
        json={"clave": "contrato_a_punto_de_vencer", "nombre": "Contratos, la segunda"},
        headers=cabeceras,
    )
    assert r.status_code == 200, r.text[:300]

    # La que reparte trabajo exige a quién; con alguien, se instala.
    r = cliente.post(
        "/api/v1/automatizaciones/plantillas/instalar",
        json={"clave": "lead_nuevo_al_responsable"},
        headers=cabeceras,
    )
    assert r.status_code == 422, r.text[:300]
    responsable = str(uuid4())
    r = cliente.post(
        "/api/v1/automatizaciones/plantillas/instalar",
        json={"clave": "lead_nuevo_al_responsable", "responsable_id": responsable},
        headers=cabeceras,
    )
    assert r.status_code == 200, r.text[:300]
    ficha = cliente.get(
        f"/api/v1/automatizaciones/{r.json()['automatizacion_id']}", headers=cabeceras
    ).json()
    assert ficha["acciones"][0]["parametros"]["usuario_id"] == responsable

    marcadas = {
        i["clave"]
        for i in cliente.get("/api/v1/automatizaciones/plantillas", headers=cabeceras).json()[
            "items"
        ]
        if i["instalada"]
    }
    assert marcadas == {"contrato_a_punto_de_vencer", "lead_nuevo_al_responsable"}

    # Una clave que no está en la biblioteca no es una opción.
    r = cliente.post(
        "/api/v1/automatizaciones/plantillas/instalar",
        json={"clave": "inventada"},
        headers=cabeceras,
    )
    assert r.status_code == 422


# ── Promover desde un sandbox ─────────────────────────────────────────────


def _guardar(db: Any, tenant: UUID, nombre: str, **extra: Any) -> Any:
    from services.automation.modelos import Automatizacion

    fila = Automatizacion(
        tenant_id=tenant,
        nombre=nombre,
        disparador="creacion",
        objetivo="cuenta",
        acciones=[{"tipo": "fijar", "nombre": "visto", "valor": 1}],
        **extra,
    )
    db.add(fila)
    db.flush()
    return fila


def test_promover_crea_y_actualiza_de_verdad_primero_en_seco(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    from crmcore.audit.modelos import ApunteAuditoria
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.errors import Conflicto
    from sqlalchemy import select

    from services.automation import entornos_auto
    from services.automation.modelos import Automatizacion

    sandbox_id = uuid4()
    # El sandbox lo contesta `tenancy` por HTTP; aquí, con lo que contestaría.
    monkeypatch.setattr(
        entornos_auto,
        "_sandbox",
        lambda _p, sid: {
            "tenant_sandbox_id": str(otro_tenant_id),
            "nombre": "Pruebas de otoño",
            "estado": "listo",
        }
        if sid == sandbox_id
        else pytest.fail("sandbox equivocado"),
    )
    # En el sandbox: una nueva y otra que en producción está distinta y encendida.
    _guardar(db, otro_tenant_id, "Nueva del sandbox", prioridad=7)
    _guardar(db, otro_tenant_id, "Ya existe", prioridad=1, ejecuciones=40)
    _guardar(db, otro_tenant_id, "Igual en los dos")
    produccion = _guardar(db, tenant_id, "Ya existe", prioridad=50, activa=True, ejecuciones=3)
    _guardar(db, tenant_id, "Igual en los dos")

    principal = SimpleNamespace(tenant_id=tenant_id, id=uuid4(), permisos=set(), roles=set())
    with unidad_de_trabajo(tenant_id) as uow:
        seco = entornos_auto.promover(uow, principal, sandbox_id=sandbox_id, nombres=[], huella="")
    assert seco["en_seco"] is True
    plan = {p["nombre"]: p for p in seco["plan"]}
    assert plan["Nueva del sandbox"]["accion"] == "crear"
    assert plan["Ya existe"]["accion"] == "actualizar"
    assert plan["Ya existe"]["cambios"] == ["prioridad"]
    assert plan["Ya existe"]["se_apagara"] is True
    assert plan["Igual en los dos"]["accion"] == "sin_cambios"
    # En seco no se ha tocado nada.
    db.expire_all()
    assert db.get(Automatizacion, produccion.id).prioridad == 50

    # Una huella que no es la del plan no aplica nada.
    with pytest.raises(Conflicto), unidad_de_trabajo(tenant_id) as uow:
        entornos_auto.promover(uow, principal, sandbox_id=sandbox_id, nombres=[], huella="x")

    with unidad_de_trabajo(tenant_id) as uow:
        hecho = entornos_auto.promover(
            uow, principal, sandbox_id=sandbox_id, nombres=[], huella=seco["huella"]
        )
    assert {a["nombre"]: a["accion"] for a in hecho["aplicadas"]} == {
        "Nueva del sandbox": "crear",
        "Ya existe": "actualizar",
    }
    db.expire_all()
    actualizada = db.get(Automatizacion, produccion.id)
    # La definición viene; el estado no: los contadores son de producción.
    assert (actualizada.prioridad, actualizada.ejecuciones, actualizada.activa) == (1, 3, False)
    nueva = (
        db.execute(
            select(Automatizacion).where(
                Automatizacion.tenant_id == tenant_id, Automatizacion.nombre == "Nueva del sandbox"
            )
        )
        .scalars()
        .one()
    )
    assert (nueva.prioridad, nueva.activa) == (7, False)

    apuntes = (
        db.execute(
            select(ApunteAuditoria).where(
                ApunteAuditoria.tenant_id == tenant_id,
                ApunteAuditoria.accion == "automatizacion.promovida",
            )
        )
        .scalars()
        .all()
    )
    assert len(apuntes) == 2
    assert all(a.datos["desde_sandbox"] == str(sandbox_id) for a in apuntes)

    # Ya aplicada, la misma huella no vale: el plan de ahora es otro.
    with pytest.raises(Conflicto), unidad_de_trabajo(tenant_id) as uow:
        entornos_auto.promover(
            uow, principal, sandbox_id=sandbox_id, nombres=[], huella=seco["huella"]
        )


def test_promover_una_que_no_esta_en_el_sandbox_lo_dice(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.errors import ErrorValidacion

    from services.automation import entornos_auto

    monkeypatch.setattr(
        entornos_auto, "_sandbox", lambda _p, _s: {"tenant_sandbox_id": str(otro_tenant_id)}
    )
    principal = SimpleNamespace(tenant_id=tenant_id, id=uuid4(), permisos=set(), roles=set())
    with pytest.raises(ErrorValidacion) as fallo, unidad_de_trabajo(tenant_id) as uow:
        entornos_auto.promover(uow, principal, sandbox_id=uuid4(), nombres=["No existe"], huella="")
    assert "No existe" in fallo.value.mensaje
