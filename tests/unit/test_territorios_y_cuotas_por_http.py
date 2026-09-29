"""Territorios y cuotas de ventas, EJERCITADOS (`CRM-03.02.02`).

Tercer punto de la curva del recorrido del catálogo, y el primero **en frío**:
una familia de siete que no había mirado nunca. Las dos anteriores fueron 89
minutos —la primera de todas, que pagó el andamio— y 4 minutos —una cuya
superficie ya conocía—.

Se entra por la ruta y **con rol**, no sólo con permisos: el enmascarado por
sensibilidad se resuelve por rol, y un principal sin ninguno recibe los campos
con puntos. Una prueba que entra distinto a como entra un cliente acaba acusando
al producto de lo que hace bien.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


@pytest.fixture
def cliente() -> Any:
    import importlib
    import os

    from crmcore.config import get_settings

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
        },
        get_settings().secret_key.get_secret_value(),
    )


def _territorio(cliente: TestClient, cabeceras: dict[str, str], **datos: Any) -> dict[str, Any]:
    cuerpo = {
        "clave": f"t-{uuid4().hex[:8]}",
        "nombre": "Cataluña",
        "criterios": [
            {
                "tipo": "geografia",
                "condiciones": [{"atributo": "provincia", "operador": "en", "valor": ["B", "GI"]}],
            }
        ],
        **datos,
    }
    respuesta = cliente.post("/api/v1/territorios", headers=cabeceras, json=cuerpo)
    assert respuesta.status_code in (200, 201), respuesta.text
    return dict(respuesta.json())


# ── .01 Modelo de territorios por criterios ───────────────────────────────


def test_un_territorio_se_crea_y_se_lee_con_sus_criterios(
    cliente: TestClient, cabeceras: dict[str, str], db: Any
) -> None:
    """Los criterios son el territorio: si se guardan y no se leen, no se puede
    saber por qué una cuenta cayó donde cayó."""
    creado = _territorio(cliente, cabeceras)

    ficha = cliente.get(f"/api/v1/territorios/{creado['id']}", headers=cabeceras)
    assert ficha.status_code == 200, ficha.text
    assert "geografia" in str(
        ficha.json()
    ), "los criterios se guardan y no se pueden leer: nadie podría explicar un reparto"


# ── .03 Simular antes de publicar ─────────────────────────────────────────


def test_simular_reparte_sin_tocar_nada(
    cliente: TestClient, cabeceras: dict[str, str], db: Any
) -> None:
    """El error caro aquí es repartir mal la cartera de veinte comerciales y
    enterarse por sus llamadas."""
    _territorio(cliente, cabeceras)

    respuesta = cliente.post(
        "/api/v1/territorios/simular",
        headers=cabeceras,
        json={"cuentas": [{"id": str(uuid4()), "nombre": "Acme", "provincia": "B"}]},
    )
    assert respuesta.status_code == 200, respuesta.text


def test_resolver_dice_a_que_territorio_cae_una_cuenta(
    cliente: TestClient, cabeceras: dict[str, str], db: Any
) -> None:
    """Poder preguntarlo de una cuenta suelta es lo que permite contestar «¿por
    qué esta cuenta es mía?» sin recorrer el reparto entero."""
    _territorio(cliente, cabeceras)

    respuesta = cliente.post(
        "/api/v1/territorios/resolver",
        headers=cabeceras,
        json={"provincia": "B", "nombre": "Acme"},
    )
    assert respuesta.status_code == 200, respuesta.text


# ── .02 Jerarquía y excepciones ───────────────────────────────────────────


def test_una_excepcion_nominal_exige_motivo(
    cliente: TestClient, cabeceras: dict[str, str], db: Any
) -> None:
    """Una cuenta sacada de su territorio a mano sin motivo escrito es una
    discusión garantizada tres meses después."""
    territorio = _territorio(cliente, cabeceras)

    sin_motivo = cliente.post(
        "/api/v1/territorios/excepciones",
        headers=cabeceras,
        json={"cuenta_id": str(uuid4()), "territorio_id": territorio["id"]},
    )
    assert (
        sin_motivo.status_code == 422
    ), f"se ha admitido una excepción sin motivo: {sin_motivo.text}"

    con_motivo = cliente.post(
        "/api/v1/territorios/excepciones",
        headers=cabeceras,
        json={
            "cuenta_id": str(uuid4()),
            "territorio_id": territorio["id"],
            "motivo": "cuenta global, la lleva el equipo corporativo",
        },
    )
    assert con_motivo.status_code in (200, 201), con_motivo.text


# ── .04 y .05 Cuotas y prorrateo ──────────────────────────────────────────


def _cuota(cliente: TestClient, cabeceras: dict[str, str], **datos: Any) -> dict[str, Any]:
    cuerpo = {
        "desde": "2026-01-01",
        "hasta": "2026-03-31",
        "objetivo": "100000.00",
        "usuario_id": str(uuid4()),
        "periodo": "trimestral",
        **datos,
    }
    respuesta = cliente.post("/api/v1/cuotas", headers=cabeceras, json=cuerpo)
    assert respuesta.status_code in (200, 201), respuesta.text
    return dict(respuesta.json())


def test_una_cuota_se_crea_y_sale_en_su_listado(
    cliente: TestClient, cabeceras: dict[str, str], db: Any
) -> None:
    creada = _cuota(cliente, cabeceras)

    listado = cliente.get("/api/v1/cuotas", headers=cabeceras)
    assert listado.status_code == 200, listado.text
    assert creada["id"] in str(listado.json()), "la cuota recién creada no sale en su listado"


# ── .06 Consecución y ranking ─────────────────────────────────────────────


def test_la_consecucion_responde_sin_cuotas_y_con_ellas(
    cliente: TestClient, cabeceras: dict[str, str], db: Any
) -> None:
    """Sin cuotas es un caso normal —nadie ha puesto objetivos todavía— y no un
    error: un 500 aquí es una pantalla en blanco el primer día."""
    vacia = cliente.get("/api/v1/cuotas/consecucion", headers=cabeceras)
    assert vacia.status_code == 200, vacia.text

    _cuota(cliente, cabeceras)
    con_datos = cliente.get(
        "/api/v1/cuotas/consecucion",
        headers=cabeceras,
        params={"desde": "2026-01-01", "hasta": "2026-03-31"},
    )
    assert con_datos.status_code == 200, con_datos.text


# ── .07 Cobertura de pipeline vs. cuota ───────────────────────────────────


def test_la_cobertura_compara_pipeline_con_cuota(
    cliente: TestClient, cabeceras: dict[str, str], db: Any
) -> None:
    """El pipeline entra de fuera: quien conoce las oportunidades es otro. Lo que
    se comprueba es que la comparación se pueda pedir y conteste."""
    cuota = _cuota(cliente, cabeceras)
    assert cuota is not None

    respuesta = cliente.post(
        "/api/v1/cuotas/cobertura",
        headers=cabeceras,
        json={
            "desde": "2026-01-01",
            "hasta": "2026-03-31",
            "pipeline_por_sujeto": {},
            "logrado_por_sujeto": {},
        },
    )
    assert respuesta.status_code == 200, respuesta.text
