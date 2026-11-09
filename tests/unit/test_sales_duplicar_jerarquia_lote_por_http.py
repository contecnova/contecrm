"""Las rutas de `sales` que usan las pantallas nuevas, recorridas por HTTP
(CRM-01.01.03.03, CRM-07.01.01.07, CRM-03.02.01.02, CRM-00.02.01.11).

El alta de un lead que ya existe (409 y `forzar`), duplicar una oportunidad con
sus líneas, la previsión con el organigrama resuelto —por territorios y por
mando—, el traspaso de leads y oportunidades y el lote de leads.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.errors import NoDisponible
from crmcore.fechas import hoy
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

    # Sin `party`: la consulta a los contactos no puede depender de que haya una
    # pila levantada, y si la hay, no se le pregunta con un tenant de prueba.
    def _sin_party(**_: Any) -> dict[str, Any]:
        raise NoDisponible("sin party", error_code="interno.servicio_no_responde")

    monkeypatch.setattr("crmcore.http.interno.invocar", _sin_party)
    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        modulo = importlib.import_module("services.sales.main")
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


@pytest.fixture
def pipeline(db: Any, tenant_id: UUID) -> Any:
    from services.sales.modelos import Etapa, Pipeline

    fila = Pipeline(tenant_id=tenant_id, clave="ventas", nombre="Ventas", por_defecto=True)
    db.add(fila)
    db.flush()
    db.add_all(
        [
            Etapa(
                tenant_id=tenant_id,
                pipeline_id=fila.id,
                clave="contacto",
                nombre="Contacto",
                orden=1,
                probabilidad=10,
                criterios_salida=[],
            ),
            Etapa(
                tenant_id=tenant_id,
                pipeline_id=fila.id,
                clave="negociacion",
                nombre="Negociación",
                orden=2,
                probabilidad=60,
            ),
        ]
    )
    db.flush()
    return fila


def _oportunidad(db: Any, tenant_id: UUID, pipeline: Any, *, owner: UUID, importe: str) -> Any:
    from sqlalchemy import select

    from services.sales.modelos import Etapa, Oportunidad

    etapa = db.execute(
        select(Etapa).where(Etapa.pipeline_id == pipeline.id, Etapa.clave == "negociacion")
    ).scalar_one()
    fila = Oportunidad(
        tenant_id=tenant_id,
        nombre="Op",
        pipeline_id=pipeline.id,
        etapa_id=etapa.id,
        importe=Decimal(importe),
        moneda="EUR",
        probabilidad=60,
        fecha_cierre=hoy(),
        owner_id=owner,
        estado="abierta",
    )
    db.add(fila)
    db.flush()
    return fila


def test_un_lead_repetido_responde_409_y_forzar_lo_crea(
    cliente: Any, cabeceras: dict[str, str], db: Any
) -> None:
    primero = cliente.post(
        "/api/v1/leads", headers=cabeceras, json={"nombre": "Ana", "email": "ana@acme-leads.es"}
    )
    assert primero.status_code == 201, primero.text

    repetido = cliente.post(
        "/api/v1/leads", headers=cabeceras, json={"nombre": "Ana", "email": "ana@acme-leads.es"}
    )
    assert repetido.status_code == 409, repetido.text
    cuerpo = repetido.json()
    assert cuerpo["error_code"] == "sales.lead_duplicado"
    assert cuerpo["detalle"]["candidatos"][0]["id"] == primero.json()["id"]
    assert cuerpo["detalle"]["contactos_consultados"] is False

    forzado = cliente.post(
        "/api/v1/leads",
        headers=cabeceras,
        json={"nombre": "Ana", "email": "ana@acme-leads.es", "forzar": True},
    )
    assert forzado.status_code == 201, forzado.text


def test_duplicar_una_oportunidad_copia_sus_lineas_y_empieza_de_cero(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, pipeline: Any
) -> None:
    from services.sales.modelos import LineaOportunidad, Oportunidad

    original = _oportunidad(db, tenant_id, pipeline, owner=uuid4(), importe="0")
    db.add_all(
        [
            LineaOportunidad(
                tenant_id=tenant_id,
                oportunidad_id=original.id,
                descripcion="Licencias",
                cantidad=Decimal(2),
                precio_unitario=Decimal(100),
                total=Decimal(200),
                orden=1,
            ),
            LineaOportunidad(
                tenant_id=tenant_id,
                oportunidad_id=original.id,
                descripcion="Implantación",
                cantidad=Decimal(1),
                precio_unitario=Decimal(300),
                total=Decimal(300),
                orden=2,
            ),
        ]
    )
    db.flush()

    r = cliente.post(f"/api/v1/opportunities/{original.id}/duplicar", headers=cabeceras, json={})
    assert r.status_code == 201, r.text
    assert r.json()["lineas_copiadas"] == 2
    copia = db.get(Oportunidad, UUID(r.json()["oportunidad_id"]))
    assert copia.nombre == "Op (copia)"
    assert copia.importe == Decimal("500")
    # Empieza en la primera etapa: lo que dice cómo le fue a la otra no se copia.
    assert copia.etapa_id != original.etapa_id
    lineas = db.query(LineaOportunidad).filter(LineaOportunidad.oportunidad_id == copia.id)
    assert sorted(linea.descripcion for linea in lineas) == ["Implantación", "Licencias"]


def test_la_prevision_por_territorios_y_por_mando(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, pipeline: Any
) -> None:
    from crmcore.authz.jerarquia import aplicar_mando

    from services.sales import forecast
    from services.sales.territorios import MiembroTerritorio, Territorio

    forecast.sembrar_categorias(db, tenant_id)
    forecast.abrir_periodo(
        db, tenant_id, clave="P1", desde=hoy() - timedelta(days=5), hasta=hoy() + timedelta(days=5)
    )
    jefa, ana, luis, suelto = uuid4(), uuid4(), uuid4(), uuid4()
    _oportunidad(db, tenant_id, pipeline, owner=ana, importe="1000")
    _oportunidad(db, tenant_id, pipeline, owner=luis, importe="300")
    _oportunidad(db, tenant_id, pipeline, owner=suelto, importe="50")

    region = Territorio(tenant_id=tenant_id, clave="norte", nombre="Norte")
    db.add(region)
    db.flush()
    equipo = Territorio(tenant_id=tenant_id, clave="bilbao", nombre="Bilbao", padre_id=region.id)
    db.add(equipo)
    db.flush()
    db.add_all(
        [
            MiembroTerritorio(tenant_id=tenant_id, territorio_id=equipo.id, usuario_id=ana),
            MiembroTerritorio(tenant_id=tenant_id, territorio_id=equipo.id, usuario_id=luis),
        ]
    )
    db.flush()

    r = cliente.get("/api/v1/forecast/periodos/P1/organigrama", headers=cabeceras)
    assert r.status_code == 200, r.text
    datos = r.json()
    (norte,) = datos["nodos"]
    assert (norte["nombre"], norte["nivel"], norte["total"]) == ("Norte", "region", "1300.00")
    (bilbao,) = norte["hijos"]
    assert (bilbao["nivel"], bilbao["total"]) == ("equipo", "1300.00")
    assert {h["usuario_id"] for h in bilbao["hijos"]} == {str(ana), str(luis)}
    assert {h["nivel"] for h in bilbao["hijos"]} == {"comercial"}
    # El total de la compañía va aparte, y el agujero se ve con su dueño.
    assert datos["compania"]["total"] == "1350.00"
    assert datos["sin_asignar"] == "50.00" and datos["cuadra"] is False
    assert datos["sin_dueno"] == "0.00"
    assert [f["usuario_id"] for f in datos["fuera_del_organigrama"]] == [str(suelto)]

    aplicar_mando(db, tenant_id=tenant_id, usuario_id=ana, superior_id=jefa)
    aplicar_mando(db, tenant_id=tenant_id, usuario_id=luis, superior_id=jefa)
    r = cliente.get("/api/v1/forecast/periodos/P1/organigrama?fuente=mando", headers=cabeceras)
    assert r.status_code == 200, r.text
    (raiz,) = r.json()["nodos"]
    assert (raiz["usuario_id"], raiz["nivel"], raiz["total"]) == (str(jefa), "equipo", "1300.00")


def test_traspasar_leads_y_oportunidades(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, pipeline: Any
) -> None:
    from services.sales.modelos import Lead

    de, a = uuid4(), uuid4()
    _oportunidad(db, tenant_id, pipeline, owner=de, importe="10")
    db.add(Lead(tenant_id=tenant_id, nombre="L", owner_id=de))
    db.flush()
    ruta = "/api/v1/sales-admin/transferir-propiedad"
    r = cliente.post(ruta, headers=cabeceras, json={"de_usuario": str(de), "a_usuario": str(a)})
    assert r.status_code == 200, r.text
    assert r.json()["movidos"] == {"leads": 1, "oportunidades": 1}
    r = cliente.post(
        ruta,
        headers=cabeceras,
        json={
            "de_usuario": str(de),
            "a_usuario": str(a),
            "simular": False,
            "motivo": "cambio de cartera",
        },
    )
    assert r.status_code == 200, r.text
    assert db.query(Lead).one().owner_id == a


def test_el_lote_de_leads_actualiza_y_borra_como_la_ficha(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    from services.sales.modelos import Lead

    a = Lead(tenant_id=tenant_id, nombre="A")
    b = Lead(tenant_id=tenant_id, nombre="B")
    db.add_all([a, b])
    db.flush()
    r = cliente.post(
        "/api/v1/leads/masivo",
        headers=cabeceras,
        json={
            "operacion": "actualizar",
            "elementos": [
                {"id": str(a.id), "empresa": "ACME"},
                {"id": str(b.id), "empresa": "ACME"},
            ],
        },
    )
    assert r.status_code == 207, r.text
    assert r.json()["actualizados"] == 2
    db.refresh(a)
    assert a.empresa == "ACME"

    r = cliente.post(
        "/api/v1/leads/masivo",
        headers=cabeceras,
        json={"operacion": "borrar", "elementos": [{"id": str(b.id)}]},
    )
    assert r.status_code == 207, r.text
    assert r.json()["borrados"] == 1
    db.refresh(b)
    assert b.deleted_at is not None

    # Y lo que la ficha no admite, el lote tampoco: un campo que no existe es
    # un fallo de esa fila, no una escritura silenciosa.
    r = cliente.post(
        "/api/v1/leads/masivo",
        headers=cabeceras,
        json={"operacion": "actualizar", "elementos": [{"id": str(a.id), "inventado": 1}]},
    )
    assert r.status_code == 207
    assert r.json()["fallidos"] == 1
