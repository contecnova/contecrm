"""Lo que se daba de alta y no se podía cambiar, por HTTP y de punta a punta.

Complementa `test_lo_que_se_crea_se_puede_cambiar.py`, que mira el contrato:
aquí se comprueba que las rutas nuevas hacen lo que dicen. Un producto se
renombra y se retira sin borrarse, el de otro tenant no se ve, y una cola
cambia de miembros por la misma clave con la que se abre.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

from tests.unit.test_reverificacion_y_mfa_adaptativa import _cabeceras

pytestmark = pytest.mark.db


def _cliente(servicio: str, monkeypatch: Any) -> Any:
    import importlib

    from crmcore.config import get_settings
    from crmcore.tareas import RelevoDeTareas

    # Los barridos de fondo abren su propia transacción contra la misma base y
    # se llevan el savepoint del caso; lo que se prueba aquí son las rutas.
    async def _no_correr(self: Any) -> None:
        return None

    monkeypatch.setattr(RelevoDeTareas, "correr", _no_correr)
    monkeypatch.setenv("OUTBOX_ENABLED", "false")
    get_settings.cache_clear()
    modulo = importlib.import_module(f"services.{servicio}.main")
    return TestClient(modulo.app)


def test_un_producto_se_corrige_y_se_retira_sin_borrarse(
    monkeypatch: Any, tenant_id: UUID, db: Any
) -> None:
    from crmcore.config import get_settings

    try:
        with _cliente("sales", monkeypatch) as cli:
            alta = cli.post(
                "/api/v1/productos",
                headers=_cabeceras(tenant_id),
                json={
                    "sku": f"P-{uuid4().hex[:6]}",
                    "nombre": "Licencia anul",
                    "precio_base": "10",
                },
            )
            assert alta.status_code == 201, alta.text
            pid = alta.json()["id"]

            cambio = cli.patch(
                f"/api/v1/productos/{pid}",
                headers=_cabeceras(tenant_id),
                json={"nombre": "Licencia anual", "activo": False},
            )
            assert cambio.status_code == 200, cambio.text

            ficha = cli.get(f"/api/v1/productos/{pid}", headers=_cabeceras(tenant_id))
            assert ficha.status_code == 200, ficha.text
            assert ficha.json()["nombre"] == "Licencia anual"
            assert ficha.json()["activo"] is False

            # Retirado no es borrado: los presupuestos viejos lo siguen nombrando.
            assert cli.delete(
                f"/api/v1/productos/{pid}", headers=_cabeceras(tenant_id)
            ).status_code in (404, 405)

            ajeno = cli.get(f"/api/v1/productos/{pid}", headers=_cabeceras(uuid4()))
            assert ajeno.status_code == 404, ajeno.text
    finally:
        get_settings.cache_clear()


def test_una_cola_cambia_de_miembros_por_su_clave(
    monkeypatch: Any, tenant_id: UUID, db: Any
) -> None:
    from crmcore.config import get_settings

    clave = f"soporte_{uuid4().hex[:6]}"
    alguien = str(uuid4())
    try:
        with _cliente("service", monkeypatch) as cli:
            alta = cli.post(
                "/api/v1/colas",
                headers=_cabeceras(tenant_id),
                json={"clave": clave, "nombre": "Soporte"},
            )
            assert alta.status_code == 201, alta.text

            cambio = cli.patch(
                f"/api/v1/colas/{clave}",
                headers=_cabeceras(tenant_id),
                json={"miembros": [alguien], "nivel": 2},
            )
            assert cambio.status_code == 200, cambio.text
            assert cambio.json()["miembros"] == [alguien]
            assert cambio.json()["nivel"] == 2
            # Lo que no se manda se queda como estaba.
            assert cambio.json()["nombre"] == "Soporte"

            ajena = cli.patch(
                f"/api/v1/colas/{clave}", headers=_cabeceras(uuid4()), json={"nivel": 3}
            )
            assert ajena.status_code == 404, ajena.text
    finally:
        get_settings.cache_clear()
