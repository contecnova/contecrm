"""Las rutas de los modelos entrenados, del asistente y de las preguntas a los
datos, recorridas por HTTP (CRM-02.01.02.02, CRM-05.02.01.02, CRM-05.02.01.03,
CRM-02.01.01.08, CRM-04.03.02.02, CRM-05.02.02.04).

Las pantallas «Modelos predictivos» y «Asistente IA» y el panel de predicción
de las fichas leen la forma de estas respuestas. Aquí se pide cada una por su
ruta, como lo hace la pantalla, y se fija lo que la pantalla lee: si el
servidor deja de mandar un campo, esto se pone rojo antes que la pantalla se
quede en blanco.

El CRM de verdad (sales, marketing) y el modelo se sustituyen por dobles: lo
que se prueba es la puerta y lo que hay al otro lado.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from starlette.testclient import TestClient

from services.intelligence import acciones_asistente as acc
from services.intelligence import rag as rag_mod
from tests.unit.test_ia_generativa import _proveedor, uow  # noqa: F401
from tests.unit.test_ia_predictivo_entrenado import (  # noqa: F401
    _crm_para_consulta,
    _historico,
    _lector,
    _sin_dobles,
)

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
        modulo = importlib.import_module("services.intelligence.main")
        with TestClient(modulo.app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


@pytest.fixture
def usuario() -> UUID:
    return uuid4()


@pytest.fixture
def cabeceras(tenant_id: UUID, usuario: UUID) -> dict[str, str]:
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
            H_USER: str(usuario),
            H_PERMISOS: "*:*",
            H_ROLES: "admin",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


def test_entrenar_versiones_programar_y_puntuar_por_la_ruta(
    cliente: TestClient, cabeceras: dict[str, str]
) -> None:
    historico = _historico(senal=True)
    _lector(historico)
    r = cliente.post("/api/v1/ia/predictivo/cierre/entrenar", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert {"entrenado", "publicado", "version", "porque", "metricas", "casos"} <= set(cuerpo)
    assert cuerpo["publicado"] is True

    v = cliente.get("/api/v1/ia/predictivo/versiones", headers=cabeceras).json()
    assert v["entrenables"]["cierre"] == "oportunidad"
    assert {"tipo", "version", "estado", "origen", "metricas", "ejemplos"} <= set(v["versiones"][0])

    p = cliente.put(
        "/api/v1/ia/predictivo/cierre/programacion", headers=cabeceras, json={"activa": True}
    )
    assert p.status_code == 200 and p.json()["activa"] is True
    programas = cliente.get("/api/v1/ia/predictivo/programaciones", headers=cabeceras).json()
    assert {"tipo", "activa", "cada_dias", "proxima_at", "ultimo_resultado"} <= set(programas[0])

    abierta = next(o for o in historico if o["estado"] == "abierta")
    f = cliente.get(f"/api/v1/ia/predictivo/oportunidad/{abierta['id']}", headers=cabeceras)
    assert f.status_code == 200, f.text
    cierre = f.json()["predicciones"][0]
    assert {"tipo", "hay", "valor", "factores", "modelo"} <= set(cierre)


def test_el_segmento_sin_modelo_publicado_se_niega_diciendo_por_que(
    cliente: TestClient, cabeceras: dict[str, str]
) -> None:
    _lector(_historico())
    r = cliente.post(
        "/api/v1/ia/predictivo/segmento",
        headers=cabeceras,
        json={"criterio": "propension", "minimo": 0.5},
    )
    assert r.status_code == 422 and r.json()["error_code"] == "predictivo.sin_modelo"


def test_el_asistente_propone_y_la_accion_se_confirma_por_la_ruta(
    cliente: TestClient,
    cabeceras: dict[str, str],
    uow: UnidadDeTrabajo,  # noqa: F811
) -> None:
    _proveedor(uow)
    uow.db.flush()
    rag_mod.registrar_respondedor(lambda **kw: {"texto": "Vence en marzo [1]."})
    acc.registrar_proponedor(
        lambda **kw: {"accion": "crear_tarea", "argumentos": {"asunto": "Llamar"}, "porque": ""}
    )
    hechas: list[dict[str, Any]] = []
    acc.registrar_ejecutor(lambda **kw: hechas.append(kw) or {"estado": 201, "datos": {"id": "t1"}})
    r = cliente.post(
        "/api/v1/ia/asistencia/conversar",
        headers=cabeceras,
        json={
            "pregunta": "¿Cuándo vence? Y crea una tarea",
            "fragmentos": [
                {
                    "texto": "Vence en marzo.",
                    "permiso": "account:read",
                    "fuente": "leccion",
                    "id": "L1",
                }
            ],
        },
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert {"texto", "respondida", "fuentes", "porque", "accion_propuesta"} <= set(cuerpo)
    propuesta = cuerpo["accion_propuesta"]
    assert {"id", "nombre", "argumentos", "campos", "ruta", "estado", "faltan"} <= set(propuesta)
    assert hechas == []

    c = cliente.post(
        f"/api/v1/ia/asistente/acciones/{propuesta['id']}",
        headers=cabeceras,
        json={"confirmar": True, "argumentos": {}},
    )
    assert c.status_code == 200, c.text
    assert c.json()["estado"] == "ejecutada" and c.json()["codigo_respuesta"] == 201
    assert len(hechas) == 1
    mias = cliente.get("/api/v1/ia/asistente/acciones", headers=cabeceras).json()
    assert mias["acciones"][0]["estado"] == "ejecutada"


def test_la_pregunta_a_los_datos_se_ejecuta_por_la_ruta(
    cliente: TestClient,
    cabeceras: dict[str, str],
    uow: UnidadDeTrabajo,  # noqa: F811
    monkeypatch: Any,
) -> None:
    _proveedor(uow)
    uow.db.flush()
    _crm_para_consulta([], monkeypatch)
    rag_mod.registrar_traductor(
        lambda **kw: {
            "plan": {
                "objeto": "oportunidad",
                "filtros": [{"campo": "estado", "operador": "=", "valor": "ganada"}],
            },
            "interpretacion": "Las ganadas",
        }
    )
    r = cliente.post(
        "/api/v1/ia/preguntar-datos", headers=cabeceras, json={"pregunta": "¿Cuántas ganadas?"}
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["ejecutado"] is True
    assert {
        "respuesta",
        "interpretacion",
        "consulta",
        "total",
        "leidas",
        "parcial",
        "filas",
    } <= set(cuerpo)
    assert cuerpo["consulta"]["parametros"] == {"estado": "ganada"}
