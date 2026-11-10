"""Lo pendiente de la segunda tanda, en sales y analytics (09-11-2026).

- CRM-01.01.04.06: la ficha buena del lead, compuesta de lo que tiene hoy, de
  cada captura fusionada en él y de cada lead señalado como su duplicado, con
  reglas guardadas y la procedencia de cada valor.
- CRM-01.01.04.02: el umbral de duplicado del lead por objeto con el que se
  compara (otro lead, un contacto), y que cambia lo que se encuentra.
- El reparto de la compensación salía vacío: la lista de oportunidades sí trae
  `owner_id`; lo que faltaba era el dueño —nadie lo ponía al crear—.
- El embudo de la analítica leía 100 historiales, uno por llamada: ahora hay
  un listado en bloque, paginado.
- CRM-03.03.02.10: revisar las renovaciones de UN contrato, sin tocar los demás.

Todo por HTTP, que es como lo piden sus pantallas.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.fechas import hoy
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


@pytest.fixture
def usuario() -> UUID:
    return uuid4()


@pytest.fixture
def cab(tenant_id: UUID, usuario: UUID) -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import (
        H_FACTOR_FUERTE,
        H_PERMISOS,
        H_ROLES,
        H_TENANT,
        H_TIPO,
        H_USER,
        firmar_cabeceras_internas,
    )

    return firmar_cabeceras_internas(
        {
            H_TENANT: str(tenant_id),
            H_USER: str(usuario),
            H_PERMISOS: "*:*",
            H_ROLES: "admin",
            H_TIPO: "usuario",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


@pytest.fixture
def sales(monkeypatch: Any, db: Any) -> Any:
    import importlib

    import crmcore.http.interno as interno
    from crmcore.config import get_settings
    from crmcore.errors import NoDisponible
    from crmcore.tareas import RelevoDeTareas

    async def _no_correr(self: Any) -> None:
        return None

    def _sin_party(**_: Any) -> dict[str, Any]:
        raise NoDisponible("party no está en esta prueba", error_code="interno.sin_direccion")

    monkeypatch.setattr(RelevoDeTareas, "correr", _no_correr)
    monkeypatch.setattr(interno, "invocar", _sin_party)
    monkeypatch.setenv("OUTBOX_ENABLED", "false")
    get_settings.cache_clear()
    modulo = importlib.import_module("services.sales.main")
    with TestClient(modulo.app) as cli:
        yield cli
    get_settings.cache_clear()


def _embudo(db: Any, tenant_id: UUID, *, por_defecto: bool = True) -> Any:
    from services.sales.modelos import Etapa, Pipeline

    embudo = Pipeline(
        tenant_id=tenant_id,
        clave=f"p{uuid4().hex[:6]}",
        nombre="Ventas",
        por_defecto=por_defecto,
    )
    db.add(embudo)
    db.flush()
    for orden, clave in enumerate(("calificar", "proponer"), start=1):
        db.add(
            Etapa(
                tenant_id=tenant_id,
                pipeline_id=embudo.id,
                clave=clave,
                nombre=clave.title(),
                orden=orden,
            )
        )
    db.flush()
    return embudo


# ── CRM-01.01.04.06: la ficha buena del lead ──────────────────────────────


def test_la_ficha_buena_del_lead_sale_de_sus_capturas_y_duplicados(
    sales: Any, cab: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    from services.sales.modelos import Lead

    lead = Lead(
        tenant_id=tenant_id,
        nombre="Ana",
        apellidos="Pérez",
        empresa="Talleres Ebro",
        cargo="Compras",
        email="ana@ebro.example",
        campos={
            "capturas_fusionadas": [
                {
                    "canal": "feria",
                    "at": datetime.now(timezone.utc).isoformat(),
                    "datos": {"cargo": "Directora de compras", "telefono": "600111222"},
                }
            ]
        },
    )
    db.add(lead)
    db.flush()
    db.add(
        Lead(
            tenant_id=tenant_id,
            nombre="Ana",
            empresa="Talleres Ebro S.L.",
            email="ana@ebro.example",
            duplicado_de_id=lead.id,
        )
    )
    db.flush()

    # Se ofrece: tiene más de una versión de la verdad.
    r = sales.get("/api/v1/leads/calidad-dato/golden/candidatas", headers=cab)
    assert r.status_code == 200, r.text
    fila = next(c for c in r.json() if c["objeto_id"] == str(lead.id))
    assert fila["objeto"] == "lead"
    assert fila["capturas"] == 1 and fila["duplicados"] == 1

    # La feria manda: la regla por defecto del lead se guarda.
    r = sales.put(
        "/api/v1/leads/calidad-dato/golden/reglas/lead/*",
        headers=cab,
        json={"estrategia": "mayor_confianza", "confianza_por_fuente": {"feria": 90}},
    )
    assert r.status_code == 200, r.text
    reglas = sales.get("/api/v1/leads/calidad-dato/golden/reglas/lead", headers=cab).json()
    assert [x["campo"] for x in reglas["reglas"]] == ["*"]
    assert "cargo" in reglas["campos"]

    # Componer guarda y NO toca el lead.
    r = sales.post(
        f"/api/v1/leads/calidad-dato/golden/lead/{lead.id}/componer", headers=cab, json={}
    )
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["valores"]["cargo"] == "Directora de compras"
    assert g["procedencia"]["cargo"]["fuente"] == "feria"
    assert g["procedencia"]["cargo"]["regla"] == "por defecto del objeto"
    assert g["procedencia"]["empresa"]["candidatos"][-1]["origen"].startswith("lead:")
    assert any(x["campo"] == "cargo" for x in g["a_revisar"])
    db.refresh(lead)
    assert lead.cargo == "Compras"
    assert (
        sales.get(f"/api/v1/leads/calidad-dato/golden/lead/{lead.id}", headers=cab).json()[
            "valores"
        ]
        == g["valores"]
    )

    # Aplicar lo escribe, con el antes.
    r = sales.post(
        f"/api/v1/leads/calidad-dato/golden/lead/{lead.id}/componer",
        headers=cab,
        json={"aplicar": True},
    )
    assert r.status_code == 200, r.text
    assert {
        "campo": "cargo",
        "antes": "Compras",
        "despues": "Directora de compras",
    }.items() <= next(a for a in r.json()["aplicados"] if a["campo"] == "cargo").items()
    db.refresh(lead)
    assert lead.cargo == "Directora de compras"
    assert lead.telefono == "600111222"


def test_la_ficha_buena_del_lead_rechaza_lo_que_no_es_suyo(sales: Any, cab: dict[str, str]) -> None:
    assert (
        sales.get("/api/v1/leads/calidad-dato/golden/reglas/cuenta", headers=cab).status_code == 422
    )
    r = sales.put(
        "/api/v1/leads/calidad-dato/golden/reglas/lead/estado",
        headers=cab,
        json={"estrategia": "mayor_confianza"},
    )
    assert r.status_code == 422
    r = sales.put(
        "/api/v1/leads/calidad-dato/golden/reglas/lead/cargo",
        headers=cab,
        json={"estrategia": "azar"},
    )
    assert r.status_code == 422


# ── CRM-01.01.04.02: el umbral del lead por objeto ────────────────────────


def test_el_umbral_del_lead_por_objeto_cambia_lo_que_se_encuentra(
    sales: Any, cab: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    from services.sales import dedupe_leads
    from services.sales.modelos import Lead

    db.add(Lead(tenant_id=tenant_id, nombre="Ana", empresa="Talleres Martinez Ebro"))
    db.flush()
    nuevo = {"nombre": "Ana", "empresa": "Talleres Martín Ebro"}
    # Con el umbral general, se parece.
    antes = dedupe_leads.buscar(db, tenant_id, nuevo).candidatos
    assert [c.objeto for c in antes] == ["lead"]
    parecido = antes[0].similitud
    general = dedupe_leads._ajustes(db)["sugerencia"]
    assert general <= parecido < 1

    r = sales.put(
        "/api/v1/leads/calidad-dato/umbrales-duplicado",
        headers=cab,
        json={"por_objeto": {"lead": {"sugerencia": min(1.0, round(parecido + 0.02, 2))}}},
    )
    assert r.status_code == 200, r.text
    u = r.json()
    assert u["lead"]["sugerencia"]["propio"] is True
    assert u["contacto"]["sugerencia"]["propio"] is False
    assert u["contacto"]["sugerencia"]["valor"] == general

    # El lead exige más frente a otro lead: el mismo par ya no se propone.
    from crmcore.tenancy.context import con_contexto

    with con_contexto(tenant_id=tenant_id):
        assert dedupe_leads.buscar(db, tenant_id, nuevo).candidatos == []
    # Y no se compara con lo que no existe.
    r = sales.put(
        "/api/v1/leads/calidad-dato/umbrales-duplicado",
        headers=cab,
        json={"por_objeto": {"cuenta": {"bloqueo": 1}}},
    )
    assert r.status_code == 422


# ── El dueño de la oportunidad (reparto de la compensación) ───────────────


def test_quien_crea_la_oportunidad_es_su_dueno_y_el_listado_lo_trae(
    sales: Any, cab: dict[str, str], db: Any, tenant_id: UUID, usuario: UUID, monkeypatch: Any
) -> None:
    _embudo(db, tenant_id)
    r = sales.post("/api/v1/opportunities", headers=cab, json={"nombre": "Sin dueño dicho"})
    assert r.status_code == 201, r.text
    assert r.json()["owner_id"] == str(usuario)
    otro = uuid4()
    r = sales.post(
        "/api/v1/opportunities", headers=cab, json={"nombre": "Con dueño", "owner_id": str(otro)}
    )
    assert r.json()["owner_id"] == str(otro)

    # Es lo que lee la compensación externa: el listado con la identidad de
    # quien pide trae `owner_id`.
    r = sales.get("/api/v1/opportunities?estado=", headers=cab)
    assert {i["owner_id"] for i in r.json()["items"]} == {str(usuario), str(otro)}

    from crmcore.runtime import settings as rt

    real = rt.efectivo
    monkeypatch.setattr(
        rt,
        "efectivo",
        lambda clave, *a, **k: False
        if clave == "oportunidad_dueno_quien_crea"
        else real(clave, *a, **k),
    )
    r = sales.post("/api/v1/opportunities", headers=cab, json={"nombre": "Apagado"})
    assert r.json()["owner_id"] is None


def test_un_proceso_no_es_dueno_de_nada(db: Any, tenant_id: UUID) -> None:
    from services.sales.servicio import crear_oportunidad_nueva

    _embudo(db, tenant_id)
    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    assert crear_oportunidad_nueva(uow, nombre="De la revisión").owner_id is None


# ── El historial de etapas en bloque ──────────────────────────────────────


def test_el_historial_de_etapas_se_lee_en_bloque_y_paginado(
    sales: Any, cab: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    from services.sales.servicio import crear_oportunidad_nueva

    embudo = _embudo(db, tenant_id)
    otro = _embudo(db, tenant_id, por_defecto=False)
    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    ids = {
        str(crear_oportunidad_nueva(uow, nombre=f"O{i}", pipeline_id=embudo.id).id)
        for i in range(3)
    }
    crear_oportunidad_nueva(uow, nombre="De otro embudo", pipeline_id=otro.id)
    db.flush()

    vistos: dict[str, Any] = {}
    cursor = ""
    llamadas = 0
    while True:
        r = sales.get(
            "/api/v1/opportunities/historial-etapas",
            headers=cab,
            params={"pipeline_id": str(embudo.id), "limite": 2, "cursor": cursor},
        )
        assert r.status_code == 200, r.text
        llamadas += 1
        for fila in r.json()["items"]:
            vistos[fila["oportunidad_id"]] = fila
        cursor = r.json()["siguiente"] or ""
        if not cursor:
            break
    assert set(vistos) == ids
    assert llamadas == 2
    assert all(
        len(f["cambios"]) == 1 and f["cambios"][0]["etapa_hasta_id"] for f in vistos.values()
    )

    # Con los filtros comunes del listado: nada creado mañana.
    manana = (datetime.now(timezone.utc) + timedelta(days=1)).date()
    r = sales.get(
        "/api/v1/opportunities/historial-etapas",
        headers=cab,
        params={"pipeline_id": str(embudo.id), "created_at__desde": str(manana)},
    )
    assert r.status_code == 200, r.text
    assert r.json()["items"] == []
    # Y la ficha de una oportunidad sigue en su sitio.
    una = next(iter(ids))
    assert sales.get(f"/api/v1/opportunities/{una}", headers=cab).status_code == 200


# ── CRM-03.03.02.10: revisar sólo este contrato ───────────────────────────


def test_revisar_las_renovaciones_de_un_solo_contrato(
    sales: Any, cab: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    from services.sales import presupuestos as pre
    from services.sales.modelos import Contrato

    _embudo(db, tenant_id)
    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    dia = hoy(db)
    uno, otro = (
        pre.crear_contrato(
            uow,
            cuenta_id=uuid4(),
            inicio=dia - timedelta(days=300),
            fin=dia + timedelta(days=10),
            importe=Decimal("900"),
            preaviso_dias=30,
        )
        for _ in range(2)
    )
    db.flush()
    falta = uuid4()
    r = sales.post(
        "/api/v1/contratos/revisar-renovaciones",
        headers=cab,
        json={"contrato_id": str(uno.id), "contrato_ids": [str(falta)]},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["revisados"] == 1
    assert [o["contrato_id"] for o in d["oportunidades"]] == [str(uno.id)]
    assert d["no_revisados"] == [{"contrato_id": str(falta), "porque": "no existe"}]
    db.expire_all()
    assert db.get(Contrato, uno.id).oportunidad_renovacion_id is not None
    # El otro, intacto: ni oportunidad ni preaviso.
    assert db.get(Contrato, otro.id).oportunidad_renovacion_id is None
    assert db.get(Contrato, otro.id).preaviso_dado is False

    # Sin cuerpo, como la tarea periódica: todos los vigentes.
    r = sales.post("/api/v1/contratos/revisar-renovaciones", headers=cab)
    assert r.status_code == 200, r.text
    assert [o["contrato_id"] for o in r.json()["oportunidades"]] == [str(otro.id)]
