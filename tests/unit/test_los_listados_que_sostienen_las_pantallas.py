"""Los cuatro listados de los que viven las pantallas principales, por la ruta.

Oportunidades, sus líneas, pipelines y casos: de estos cuatro cuelgan la
portada, el tablero de embudo, la ficha de cliente y la ficha de una venta, y
el 29-10-2026 **ninguno tenía una prueba que entrara por su ruta**. Se
recorrían por el ORM, que es por donde no entra ni una pantalla ni un cliente.

Lo destapó ampliar el guardián de contratos para que viera también las
llamadas `listar<T>()`: con ellas a la vista, estas cuatro rutas salieron como
«forma declarada por una pantalla que ninguna prueba de servidor pide».

Cada prueba comprueba **los campos que la pantalla lee**, no todos: fijar el
esquema entero convierte cualquier añadido en una prueba roja y acaba en que
se borra la comprobación.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


def _cliente(modulo: str) -> Any:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        app = importlib.import_module(modulo).app
        with TestClient(app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


@pytest.fixture
def ventas(db: Any, contexto_tenant: UUID) -> Any:
    yield from _cliente("services.sales.main")


@pytest.fixture
def servicio(db: Any, contexto_tenant: UUID) -> Any:
    yield from _cliente("services.service.main")


@pytest.fixture
def cabeceras(tenant_id: UUID) -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import (
        H_PERMISOS,
        H_ROLES,
        H_TENANT,
        H_USER,
        firmar_cabeceras_internas,
    )

    # Con rol: el enmascarado por sensibilidad se resuelve por rol, y un
    # principal sin ninguno recibe los campos con puntos — la prueba parecería
    # decir que el dato no se puede leer.
    return firmar_cabeceras_internas(
        {
            H_TENANT: str(tenant_id),
            H_USER: str(uuid4()),
            H_PERMISOS: "*:*",
            H_ROLES: "admin",
        },
        get_settings().secret_key.get_secret_value(),
    )


def _pipeline(ventas: TestClient, cabeceras: dict[str, str]) -> dict[str, Any]:
    clave = f"p{uuid4().hex[:8]}"
    creado = ventas.post(
        "/api/v1/pipelines",
        headers=cabeceras,
        json={"clave": clave, "nombre": "Ventas", "por_defecto": True},
    )
    assert creado.status_code in (200, 201), creado.text
    pipeline = dict(creado.json())
    etapa = ventas.post(
        f"/api/v1/pipelines/{pipeline['id']}/etapas",
        headers=cabeceras,
        json={"clave": "nueva", "nombre": "Nueva", "orden": 1, "probabilidad": 10},
    )
    assert etapa.status_code in (200, 201), etapa.text
    return pipeline


def _oportunidad(ventas: TestClient, cabeceras: dict[str, str], **extra: Any) -> dict[str, Any]:
    creada = ventas.post(
        "/api/v1/opportunities",
        headers=cabeceras,
        json={"nombre": "Renovación Acme", "importe": "1000.00", **extra},
    )
    assert creada.status_code in (200, 201), creada.text
    return dict(creada.json())


# ── Pipelines: de aquí salen las columnas del tablero ─────────────────────


def test_el_listado_de_pipelines_trae_sus_etapas(
    ventas: TestClient, cabeceras: dict[str, str]
) -> None:
    """Sin las etapas dentro, el tablero de embudo no tiene columnas."""
    _pipeline(ventas, cabeceras)

    respuesta = ventas.get("/api/v1/pipelines", headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    filas = respuesta.json()["items"]
    assert filas, "el listado de pipelines sale vacío"
    uno = filas[0]
    for campo in ("id", "nombre", "por_defecto", "etapas"):
        assert campo in uno, f"el listado no manda «{campo}», y el tablero lo lee"
    assert uno["etapas"], "un pipeline sin etapas deja el tablero sin columnas"
    for campo in ("id", "clave", "nombre", "orden", "probabilidad", "terminal", "ganada"):
        assert campo in uno["etapas"][0], f"la etapa no manda «{campo}»"


# ── Oportunidades: la portada, el tablero y la ficha de cliente ───────────


def test_el_listado_de_oportunidades_manda_lo_que_pintan_las_tres_pantallas(
    ventas: TestClient, cabeceras: dict[str, str]
) -> None:
    _pipeline(ventas, cabeceras)
    _oportunidad(ventas, cabeceras)

    respuesta = ventas.get("/api/v1/opportunities?limite=50", headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    filas = respuesta.json()["items"]
    assert filas, "el listado de oportunidades sale vacío"
    una = filas[0]
    # La unión de lo que leen portada, tablero y ficha de cliente.
    for campo in (
        "id",
        "nombre",
        "codigo",
        "importe",
        "moneda",
        "probabilidad",
        "etapa_id",
        "estado",
        "fecha_cierre",
        "cuenta_id",
        "owner_id",
    ):
        assert campo in una, f"el listado no manda «{campo}»"


def test_las_lineas_de_una_oportunidad_traen_su_importe(
    ventas: TestClient, cabeceras: dict[str, str]
) -> None:
    """La ficha de una venta suma por línea: sin `total` la suma sale a cero."""
    _pipeline(ventas, cabeceras)
    oportunidad = _oportunidad(ventas, cabeceras)

    alta = ventas.post(
        f"/api/v1/opportunities/{oportunidad['id']}/lineas",
        headers=cabeceras,
        json={"descripcion": "Licencias", "cantidad": "2", "precio_unitario": "500.00"},
    )
    assert alta.status_code in (200, 201), alta.text

    respuesta = ventas.get(f"/api/v1/opportunities/{oportunidad['id']}/lineas", headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    lineas = respuesta.json()
    assert len(lineas) == 1
    for campo in ("id", "descripcion", "cantidad", "precio_unitario", "descuento_pct", "total"):
        assert campo in lineas[0], f"la línea no manda «{campo}»"
    # Y el tipo se llama `tipo_ingreso`: la ficha lo declaraba como `tipo`, que
    # no existe. Declarado y nunca leído, así que no se veía.
    assert "tipo_ingreso" in lineas[0]
    assert "tipo" not in lineas[0]


# ── Casos: la ficha de cliente los lista ──────────────────────────────────


def test_el_listado_de_casos_manda_lo_que_lee_la_ficha_de_cliente(
    servicio: TestClient, cabeceras: dict[str, str]
) -> None:
    cuenta_id = uuid4()
    abierto = servicio.post(
        "/api/v1/casos",
        headers=cabeceras,
        json={"asunto": "No arranca", "cuenta_id": str(cuenta_id)},
    )
    assert abierto.status_code in (200, 201), abierto.text

    respuesta = servicio.get(f"/api/v1/casos?cuenta_id={cuenta_id}&limite=20", headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    filas = respuesta.json()["items"]
    assert filas, "el listado de casos del cliente sale vacío"
    for campo in ("id", "codigo", "asunto", "estado", "prioridad"):
        assert campo in filas[0], f"el listado no manda «{campo}»"
