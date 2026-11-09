"""El motor externo de compensación, de verdad (CRM-03.02.03.04).

Hasta el 09-11-2026 `/compensacion/*` componía y conciliaba listas tecleadas y
no mandaba nada. Estas pruebas miran lo que llega al motor (un servidor HTTP de
verdad en un puerto), lo que queda guardado de ida y de vuelta, y la
conciliación contra las liquidaciones de la casa preguntadas a `sales`.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

from services.integration import compensacion as comp

pytestmark = pytest.mark.db

VENTA = str(uuid4())
OTRA = str(uuid4())
COMERCIAL = str(uuid4())


class _Motor:
    def __init__(self) -> None:
        self.recibido: list[tuple[str, dict[str, Any]]] = []


@pytest.fixture
def motor() -> Iterator[tuple[str, _Motor]]:
    estado = _Motor()

    class Manejador(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_: Any) -> None:
            return

        def do_POST(self) -> None:  # noqa: N802
            largo = int(self.headers.get("Content-Length") or 0)
            cuerpo = json.loads(self.rfile.read(largo) or b"{}") if largo else {}
            estado.recibido.append((self.path, cuerpo))
            if self.path == "/hechos":
                # El motor acepta y ya devuelve el cálculo de la primera venta.
                respuesta: Any = {
                    "resultados": [
                        {"ref": VENTA, "commission": "120.00", "period": "2026-11", "closed": False}
                    ]
                }
            else:
                respuesta = {
                    "resultados": [
                        {"ref": VENTA, "commission": "120.00", "period": "2026-11"},
                        {"ref": "a-mano-en-el-motor", "commission": "50"},
                    ]
                }
            crudo = json.dumps(respuesta).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(crudo)))
            self.end_headers()
            self.wfile.write(crudo)

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    try:
        yield f"http://127.0.0.1:{servidor.server_address[1]}", estado
    finally:
        servidor.shutdown()
        servidor.server_close()
        hilo.join(timeout=5)


def _sales(**kw: Any) -> dict[str, Any]:
    """Un `sales` de mentira: dos ventas ganadas y una liquidación de la casa."""
    ruta = kw["ruta"]
    if ruta == "/api/v1/opportunities":
        assert kw["parametros"]["estado"] == "ganada"
        return {
            "ok": True,
            "datos": {
                "items": [
                    {
                        "id": VENTA,
                        "nombre": "Renovación",
                        "importe": "1200.00",
                        "moneda": "EUR",
                        "fecha_cierre_real": "2026-11-03",
                        "owner_id": COMERCIAL,
                    },
                    {
                        "id": OTRA,
                        "nombre": "Ampliación",
                        "importe": "800.00",
                        "moneda": "EUR",
                        "fecha_cierre_real": "2026-11-05",
                        "owner_id": COMERCIAL,
                    },
                ],
                "siguiente": None,
            },
        }
    if ruta == "/api/v1/liquidaciones":
        return {
            "ok": True,
            "datos": {
                "liquidaciones": [{"id": "liq1", "desde": "2026-11-01", "hasta": "2026-11-30"}]
            },
        }
    if ruta == "/api/v1/liquidaciones/liq1":
        return {
            "ok": True,
            "datos": {
                "lineas": [
                    {"origen_id": VENTA, "importe": "100.00"},
                    {"origen_id": VENTA, "importe": "20.00"},
                    {"origen_id": OTRA, "importe": "80.00"},
                ]
            },
        }
    return {"ok": False, "estado": 404, "datos": {}}


@pytest.fixture
def cliente(monkeypatch: Any, db: Any) -> Iterator[TestClient]:
    from crmcore.config import get_settings
    from crmcore.service import crear_servicio

    from services.integration.api import ROUTERS
    from services.integration.api_compensacion import ROUTERS_COMPENSACION

    monkeypatch.setenv("URL_GUARD_HOSTS_PERMITIDOS", "127.0.0.1")
    monkeypatch.setattr(comp, "_invocar", _sales)
    get_settings.cache_clear()
    app = crear_servicio(
        nombre="integration",
        descripcion="integration para la compensación de verdad",
        routers=[*ROUTERS, *ROUTERS_COMPENSACION],
        necesita_bus=False,
    )
    with TestClient(app) as cli:
        yield cli
    get_settings.cache_clear()


@pytest.fixture
def cabeceras(tenant_id: UUID) -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import H_PERMISOS, H_TENANT, H_USER, firmar_cabeceras_internas

    return firmar_cabeceras_internas(
        {H_TENANT: str(tenant_id), H_USER: str(uuid4()), H_PERMISOS: "*:*"},
        get_settings().secret_key.get_secret_value(),
    )


def test_los_hechos_salen_al_motor_vuelven_y_se_concilian_con_la_casa(
    cliente: TestClient, cabeceras: dict[str, str], motor: tuple[str, _Motor]
) -> None:
    url, estado = motor
    conexion = cliente.post(
        "/api/v1/integraciones/conexiones",
        headers=cabeceras,
        json={"nombre": f"motor-{uuid4().hex[:6]}", "config": {"url_base": url}},
    )
    assert conexion.status_code == 201, conexion.text
    cid = conexion.json()["id"]
    mapeo = {
        "referencia": "ref",
        "comision": "commission",
        "periodo": "period",
        "cerrado": "closed",
    }
    for clave, ruta, cuerpo in (
        ("enviar_hechos", "/hechos", {"facts": "{{hechos}}"}),
        ("leer_calculo", "/calculo", {"from": "{{desde}}", "to": "{{hasta}}"}),
    ):
        op = cliente.post(
            f"/api/v1/integraciones/conexiones/{cid}/operaciones",
            headers=cabeceras,
            json={
                "clave": clave,
                "nombre": clave,
                "definicion": {
                    "metodo": "POST",
                    "ruta": ruta,
                    "cuerpo": cuerpo,
                    "ruta_resultados": "resultados",
                    "mapeo": mapeo,
                },
            },
        )
        assert op.status_code == 201, op.text

    assert cliente.get("/api/v1/compensacion/motor", headers=cabeceras).json()["conectado"] is False
    fijado = cliente.put("/api/v1/compensacion/motor", headers=cabeceras, json={"conexion_id": cid})
    assert fijado.status_code == 200, fijado.text
    assert fijado.json()["falta"] == []

    periodo = {"desde": "2026-11-01", "hasta": "2026-11-30"}
    recogidas = cliente.post("/api/v1/compensacion/envios/recoger", headers=cabeceras, json=periodo)
    assert recogidas.status_code == 200, recogidas.text
    assert recogidas.json()["nuevo"] == 2

    clawback = cliente.post(
        "/api/v1/compensacion/envios/manual",
        headers=cabeceras,
        json={
            "tipo": "devolucion",
            "referencia": "dev-1",
            "fecha": "2026-11-10",
            "importe": "-300",
            "motivo": "El cliente devolvió parte del pedido",
        },
    )
    assert clawback.status_code == 200, clawback.text

    enviado = cliente.post("/api/v1/compensacion/envios/enviar", headers=cabeceras)
    assert enviado.json() == {"enviados": 3, "calculados": 1, "errores": 0}
    ruta, cuerpo = estado.recibido[0]
    assert ruta == "/hechos"
    # Lo que sale es el hecho, nunca la comisión.
    assert {h["referencia"] for h in cuerpo["facts"]} == {VENTA, OTRA, "dev-1"}
    assert all(h["lleva_comision"] is False for h in cuerpo["facts"])

    calculo = cliente.post("/api/v1/compensacion/envios/calculo", headers=cabeceras, json=periodo)
    assert calculo.status_code == 200, calculo.text
    assert calculo.json()["calculados_sin_hecho"] == ["a-mano-en-el-motor"]
    assert set(calculo.json()["sin_calculo"]) == {OTRA, "dev-1"}

    conciliado = cliente.post(
        "/api/v1/compensacion/envios/conciliar", headers=cabeceras, json=periodo
    ).json()
    assert conciliado["liquidaciones_de_la_casa"] == 1
    assert conciliado["cuadran"] == 1  # la venta: 120 en el motor, 100 + 20 en la casa
    por_ref = {d["referencia"]: d for d in conciliado["diferencias"]}
    assert por_ref[OTRA]["comision_casa"] == "80.00"
    assert por_ref[OTRA]["porque"].startswith("El motor no ha devuelto")

    hechos = cliente.get("/api/v1/compensacion/envios", headers=cabeceras).json()["hechos"]
    venta = next(h for h in hechos if h["referencia"] == VENTA)
    assert venta["estado"] == "calculado"
    assert venta["comision_motor"] == "120.00" and venta["comision_casa"] == "120.00"
    assert venta["diferencia"] == "0.00"
    assert venta["respuesta"]["comision"] == "120.00"


def test_una_venta_mandada_cuyo_importe_cambia_no_se_reescribe(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from datetime import date
    from decimal import Decimal

    fila, que = comp.registrar_hecho(
        db,
        tenant_id,
        tipo="cierre",
        referencia="v-1",
        fecha=date(2026, 11, 1),
        importe=Decimal("1000"),
        moneda="EUR",
        usuario_id=None,
    )
    assert que == "nuevo"
    fila.estado = "enviado"
    db.flush()
    _, que = comp.registrar_hecho(
        db,
        tenant_id,
        tipo="cierre",
        referencia="v-1",
        fecha=date(2026, 11, 1),
        importe=Decimal("700"),
        moneda="EUR",
        usuario_id=None,
    )
    assert que == "cambio_tras_enviar"
    assert Decimal(str(fila.importe)) == Decimal("1000")


def test_si_el_motor_no_esta_conectado_se_dice(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from crmcore.errors import ErrorValidacion

    with pytest.raises(ErrorValidacion) as exc:
        comp.enviar_pendientes(db, tenant_id)
    assert exc.value.error_code == "compensacion.sin_motor"
