"""Lo que se daba de alta y no se podía cambiar, por HTTP y de punta a punta.

Complementa `test_lo_que_se_crea_se_puede_cambiar.py`, que mira el contrato:
aquí se comprueba que las rutas nuevas hacen lo que dicen. Un producto se
renombra y se retira sin borrarse, el de otro tenant no se ve, y una cola
cambia de miembros por la misma clave con la que se abre.
"""

from __future__ import annotations

from decimal import Decimal
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


# ── El coste congelado, y el aviso cuando cambia (CRM-09.02.01.01, .03) ────


def test_una_tarifa_de_coste_lleva_su_proveedor_y_una_de_venta_ninguno(
    monkeypatch: Any, tenant_id: UUID, db: Any
) -> None:
    """El motor sabía calcular costes de tarifas que el alta no dejaba crear."""
    from crmcore.config import get_settings

    try:
        with _cliente("sales", monkeypatch) as cli:
            cab = _cabeceras(tenant_id)
            base = {"nombre": "Tarifa", "moneda": "EUR"}
            sin_proveedor = cli.post(
                "/api/v1/listas-precio",
                headers=cab,
                json={**base, "clave": f"c-{uuid4().hex[:6]}", "sentido": "coste"},
            )
            assert sin_proveedor.status_code == 422, sin_proveedor.text
            venta_con_proveedor = cli.post(
                "/api/v1/listas-precio",
                headers=cab,
                json={**base, "clave": f"v-{uuid4().hex[:6]}", "proveedor_id": str(uuid4())},
            )
            assert venta_con_proveedor.status_code == 422, venta_con_proveedor.text
            bien = cli.post(
                "/api/v1/listas-precio",
                headers=cab,
                json={
                    **base,
                    "clave": f"c-{uuid4().hex[:6]}",
                    "sentido": "coste",
                    "proveedor_id": str(uuid4()),
                },
            )
            assert bien.status_code == 201, bien.text
    finally:
        get_settings.cache_clear()


def test_si_el_coste_sube_despues_de_ofertar_se_avisa_y_la_oferta_no_se_toca(
    monkeypatch: Any, tenant_id: UUID, db: Any
) -> None:
    from crmcore.config import get_settings

    try:
        with _cliente("sales", monkeypatch) as cli:
            cab = _cabeceras(tenant_id)
            sku = f"P-{uuid4().hex[:6]}"
            producto = cli.post(
                "/api/v1/productos",
                headers=cab,
                json={"sku": sku, "nombre": "Sensor", "precio_base": "1000", "coste": "700"},
            ).json()["id"]
            oferta = cli.post(
                "/api/v1/presupuestos",
                headers=cab,
                json={"lineas": [{"producto_id": producto, "cantidad": 1}]},
            )
            assert oferta.status_code == 201, oferta.text
            oid = oferta.json()["id"]

            sin_cambios = cli.get(f"/api/v1/presupuestos/{oid}/costes-al-dia", headers=cab)
            assert sin_cambios.status_code == 200, sin_cambios.text
            assert sin_cambios.json()["hay_cambios"] is False
            assert sin_cambios.json()["comparadas"] == 1

            # El proveedor sube: el producto cuesta ahora 800.
            assert (
                cli.patch(f"/api/v1/productos/{producto}", headers=cab, json={"coste": "800"})
            ).status_code == 200

            aviso = cli.get(f"/api/v1/presupuestos/{oid}/costes-al-dia", headers=cab).json()
            assert aviso["hay_cambios"] is True
            cambio = aviso["cambios"][0]
            assert cambio["referencia"] == sku
            assert Decimal(cambio["coste_en_la_oferta"]) == Decimal("700")
            assert Decimal(cambio["coste_hoy"]) == Decimal("800")
            assert cambio["peor"] is True
            assert aviso["la_oferta_se_ha_tocado"] is False

            # Y la oferta sigue con el coste con el que se aprobó: el 700 de
            # arriba sale de la línea guardada, leída después de la subida.
    finally:
        get_settings.cache_clear()


def test_la_oportunidad_copia_precio_y_coste_y_dice_su_margen(
    monkeypatch: Any, tenant_id: UUID, db: Any
) -> None:
    """La ruta de líneas decía que copiaba el precio del producto y guardaba lo
    que mandara quien llamaba: con un producto y sin precio, la línea quedaba a
    cero y sin coste, y la oportunidad no tenía margen (CRM-09.02.01.02)."""
    from crmcore.config import get_settings

    try:
        with _cliente("sales", monkeypatch) as cli:
            cab = _cabeceras(tenant_id)
            producto = cli.post(
                "/api/v1/productos",
                headers=cab,
                json={
                    "sku": f"P-{uuid4().hex[:6]}",
                    "nombre": "Sensor",
                    "precio_base": "1000",
                    "coste": "400",
                },
            ).json()["id"]
            # Sin proceso de venta no hay oportunidad: se crea uno con su etapa.
            embudo = cli.post(
                "/api/v1/pipelines",
                headers=cab,
                json={"clave": f"p{uuid4().hex[:8]}", "nombre": "Ventas", "por_defecto": True},
            ).json()
            cli.post(
                f"/api/v1/pipelines/{embudo['id']}/etapas",
                headers=cab,
                json={"clave": "nueva", "nombre": "Nueva", "orden": 1, "probabilidad": 10},
            )
            op = cli.post(
                "/api/v1/opportunities", headers=cab, json={"nombre": "Línea L1", "importe": "0"}
            )
            assert op.status_code in (200, 201), op.text
            oid = op.json()["id"]

            copiada = cli.post(
                f"/api/v1/opportunities/{oid}/lineas",
                headers=cab,
                json={"descripcion": "Sensor", "producto_id": producto, "cantidad": 2},
            )
            assert copiada.status_code == 201, copiada.text
            assert Decimal(str(copiada.json()["precio_unitario"])) == Decimal("1000")
            assert Decimal(str(copiada.json()["coste_unitario"])) == Decimal("400")

            # Un precio pactado a mano no se pisa.
            pactada = cli.post(
                f"/api/v1/opportunities/{oid}/lineas",
                headers=cab,
                json={"descripcion": "Sensor", "producto_id": producto, "precio_unitario": "900"},
            ).json()
            assert Decimal(str(pactada["precio_unitario"])) == Decimal("900")

            # Y una línea libre sin coste no cuenta como coste cero.
            cli.post(
                f"/api/v1/opportunities/{oid}/lineas",
                headers=cab,
                json={"descripcion": "Portes", "precio_unitario": "50"},
            )
            margen = cli.get(f"/api/v1/opportunities/{oid}/margen", headers=cab)
            assert margen.status_code == 200, margen.text
            salida = margen.json()
            assert salida["completo"] is False
            assert salida["lineas_sin_coste"] == ["Portes"]
            # (2·1000 + 900 − 3·400) / (2·1000 + 900): el conocido, sin los portes.
            assert Decimal(salida["margen_pct"]) == Decimal("58.62")
    finally:
        get_settings.cache_clear()
