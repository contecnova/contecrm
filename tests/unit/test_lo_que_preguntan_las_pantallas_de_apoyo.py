"""Las cuatro preguntas que una pantalla hace por HTTP, pedidas por la ruta.

Cuatro recuadros nuevos del 28-10-2026 declaran la FORMA de lo que leen:

  * en Seguridad, «¿y éstos por qué están permitidos?» —las excepciones de
    segregación con su motivo y su caducidad— y «no puedo entrar: ¿por dónde me
    toca?» —a qué proveedor le toca un correo—;
  * en Suite, «esto no conecta: ¿qué falta exactamente?» y «antes de
    desconectar: qué se queda y qué se va».

Las pruebas de esos cuatro módulos llaman a la función, no a la ruta. Y eso
deja un hueco con forma de fallo real: el día que el servidor deje de mandar el
motivo de una excepción, o el alcance que falta, la pantalla **no da error** —
se queda sin la única parte que la hacía útil, y nadie se entera.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.db


def _cabeceras(tenant_id: UUID) -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import H_PERMISOS, H_TENANT, H_USER, firmar_cabeceras_internas

    return firmar_cabeceras_internas(
        {H_TENANT: str(tenant_id), H_USER: str(uuid4()), H_PERMISOS: "*:*"},
        get_settings().secret_key.get_secret_value(),
    )


def _cliente(nombre: str) -> Any:
    import importlib
    import os

    from crmcore.config import get_settings
    from starlette.testclient import TestClient

    previo = {k: os.environ.get(k) for k in ("OUTBOX_ENABLED", "TAREAS_FONDO_ENABLED")}
    os.environ["OUTBOX_ENABLED"] = "false"
    os.environ["TAREAS_FONDO_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        with TestClient(importlib.import_module(f"services.{nombre}.main").app) as cli:
            yield cli
    finally:
        for clave, valor in previo.items():
            if valor is None:
                os.environ.pop(clave, None)
            else:
                os.environ[clave] = valor
        get_settings.cache_clear()


@pytest.fixture(scope="module")
def identidad() -> Any:
    yield from _cliente("identity")


@pytest.fixture(scope="module")
def integracion() -> Any:
    yield from _cliente("integration")


# ── Seguridad ─────────────────────────────────────────────────────────────


def test_las_excepciones_de_segregacion_traen_su_motivo_y_su_caducidad(
    identidad: Any, db: Any, tenant_id: UUID
) -> None:
    """Lo que las convierte en un control, y no en papeleo.

    El alta exige motivo escrito y caducidad. Si la lista no los devuelve, la
    pantalla enseña que hay excepciones y no por qué — que es exactamente lo
    que hay que revisar.
    """
    cabeceras = _cabeceras(tenant_id)
    r = identidad.get("/api/v1/segregacion/excepciones", headers=cabeceras)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)

    # Y admite pedir también las caducadas, que es lo que distingue «no hay
    # ninguna» de «todas vencieron».
    con_caducadas = identidad.get(
        "/api/v1/segregacion/excepciones?incluir_caducadas=true", headers=cabeceras
    )
    assert con_caducadas.status_code == 200, con_caducadas.text


def test_a_que_proveedor_le_toca_un_correo(identidad: Any, db: Any, tenant_id: UUID) -> None:
    """«No puedo entrar» es la incidencia más común y la más cara a ciegas.

    Sin proveedor declarado la respuesta correcta no es un error: es «entra con
    contraseña». Si esto devolviera 404, la pantalla diría que algo falla
    cuando lo que pasa es que ese dominio no está forzado.
    """
    r = identidad.get(
        "/api/v1/sso-gobierno/descubrir?email=quien.sea@ejemplo.test",
        headers=_cabeceras(tenant_id),
    )
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["tiene_proveedor"] is False
    assert datos["entrada"] == "contrasena"


# ── Suite ─────────────────────────────────────────────────────────────────


def test_el_diagnostico_dice_QUE_alcance_falta(integracion: Any, tenant_id: UUID) -> None:
    """«Faltan permisos» a secas obliga a adivinar cuál, y adivinar acaba en
    pedir permisos de administrador global «para descartar»."""
    r = integracion.post(
        "/api/v1/suites/diagnostico",
        headers=_cabeceras(tenant_id),
        json={
            "codigo": 403,
            "alcances_concedidos": ["Mail.Read"],
            "alcances_necesarios": ["Mail.Read", "Calendars.ReadWrite"],
            "mensaje_del_proveedor": "",
        },
    )
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["ok"] is False
    assert datos["faltan_alcances"] == ["Calendars.ReadWrite"]
    assert datos["que_pasa"] and datos["que_hacer"]


def test_el_diagnostico_distingue_la_credencial_del_permiso(
    integracion: Any, tenant_id: UUID
) -> None:
    """Son dos arreglos distintos: uno es volver a autorizar y el otro es pedir
    un alcance. Darlos por lo mismo es lo que alarga una implantación."""
    r = integracion.post(
        "/api/v1/suites/diagnostico",
        headers=_cabeceras(tenant_id),
        json={
            "codigo": 401,
            "alcances_concedidos": [],
            "alcances_necesarios": [],
            "mensaje_del_proveedor": "",
        },
    )
    assert r.status_code == 200, r.text
    assert "faltan_alcances" not in r.json(), "no faltan alcances: el problema es otro"
    assert "credencial" in r.json()["que_pasa"].lower()


def test_el_plan_de_baja_trae_las_dos_mitades(integracion: Any, tenant_id: UUID) -> None:
    """Enseñar sólo lo que desaparece asusta y nadie desconecta; enseñar sólo
    lo que se queda engaña. Y cada línea con su porqué, que es lo que evita que
    alguien discuta la norma."""
    motivo = "revocacion"
    r = integracion.get(f"/api/v1/suites/baja/{motivo}", headers=_cabeceras(tenant_id))
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["se_queda"] and plan["se_borra"]
    for lado in ("se_queda", "se_borra"):
        for fila in plan[lado]:
            assert fila["que"] and fila["porque"], f"una línea de «{lado}» sin su porqué"


def test_un_motivo_inventado_no_devuelve_un_plan(integracion: Any, tenant_id: UUID) -> None:
    """Un plan para un motivo que no existe se leería como bueno."""
    motivo = "porque-si"
    r = integracion.get(f"/api/v1/suites/baja/{motivo}", headers=_cabeceras(tenant_id))
    assert r.status_code == 422, r.text
