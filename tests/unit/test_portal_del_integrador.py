"""El portal del integrador, con las llamadas de verdad (CRM-00.02.04.06).

El cálculo del panel estaba escrito y nadie le daba llamadas: recibía las que
mandara quien preguntaba. Ahora el gateway apunta cada llamada hecha con clave,
`identity` las guarda, y el panel de la clave y su cuota salen de ahí.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from tests.unit.test_reverificacion_y_mfa_adaptativa import (  # noqa: F401
    _cabeceras,
    cliente_identidad,
)


def _firmadas() -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import firmar_cabeceras_internas

    return firmar_cabeceras_internas({}, get_settings().secret_key.get_secret_value())


@pytest.mark.db
def test_las_llamadas_de_una_clave_dan_su_panel_y_su_cuota(
    cliente_identidad: Any,  # noqa: F811
    tenant_id: UUID,
    db: Any,
) -> None:
    cli, cab = cliente_identidad, _cabeceras(tenant_id)
    alta = cli.post(
        "/api/v1/claves-api",
        headers=cab,
        json={"nombre": "ERP nocturno", "scopes": ["account:read"], "cuota_mes": 2},
    )
    assert alta.status_code == 201, alta.text
    clave_id, secreto = alta.json()["id"], alta.json()["secreto"]

    ahora = datetime.now(timezone.utc)
    base = {"clave_id": clave_id, "tenant_id": str(tenant_id), "metodo": "GET"}
    lote = cli.post(
        "/api/v1/claves-api/llamadas",
        headers=_firmadas(),
        json={
            "llamadas": [
                {**base, "cuando": ahora.isoformat(), "ruta": "/api/v1/accounts/x", "status": 404},
                {**base, "cuando": ahora.isoformat(), "ruta": "/api/v1/accounts", "status": 503},
                # Más vieja que lo que se guarda: se purga.
                {
                    **base,
                    "cuando": (ahora - timedelta(days=400)).isoformat(),
                    "ruta": "/api/v1/accounts",
                    "status": 200,
                },
            ]
        },
    )
    assert lote.status_code == 200, lote.text
    assert lote.json()["guardadas"] == 3
    assert lote.json()["purgadas"] >= 1

    panel = cli.post(f"/api/v1/claves-api/{clave_id}/panel", headers=cab)
    assert panel.status_code == 200, panel.text
    datos = panel.json()
    assert datos["llamadas"] == 2
    # Separados por culpa: el 404 es del integrador, el 503 nuestro.
    assert datos["errores_suyos"] == 1
    assert datos["errores_nuestros"] == 1
    assert datos["consumido_pct"] == 100.0

    # Con la cuota gastada, la clave contesta 429 y no 401: es buena, pero ya
    # no le quedan llamadas este mes.
    validar = cli.post(
        "/api/v1/claves-api/validar", headers=_firmadas(), json={"secreto": secreto, "ip": ""}
    )
    assert validar.status_code == 429, validar.text
    assert validar.json()["error_code"] == "clave_api.cuota_agotada"

    # Y sin cuota vuelve a pasar.
    assert (
        cli.post(f"/api/v1/claves-api/{clave_id}/cuota", headers=cab, json={"cuota_mes": None})
    ).status_code == 200
    assert (
        cli.post(
            "/api/v1/claves-api/validar", headers=_firmadas(), json={"secreto": secreto, "ip": ""}
        ).status_code
        == 200
    )

    ajeno = cli.post(f"/api/v1/claves-api/{clave_id}/panel", headers=_cabeceras(uuid4()))
    assert ajeno.status_code == 404


def test_el_gateway_manda_las_llamadas_por_lotes(monkeypatch: Any) -> None:
    from crmcore.config import get_settings

    from services.gateway import llamadas

    monkeypatch.setattr(get_settings(), "claves_llamadas_lote", 3)
    monkeypatch.setattr(get_settings(), "claves_llamadas_intervalo_s", 3600.0)
    monkeypatch.setattr(llamadas, "_pendientes", [])
    monkeypatch.setattr(llamadas, "_ultimo_envio", __import__("time").monotonic())
    datos = {
        "clave_id": "k",
        "tenant_id": "t",
        "metodo": "GET",
        "ruta": "/api/v1/accounts",
        "status": 200,
        "duracion_ms": 5,
        "request_id": "r",
    }
    assert llamadas.apuntar(**datos) is None
    assert llamadas.apuntar(**datos) is None
    lote = llamadas.apuntar(**datos)
    assert lote is not None and len(lote) == 3
    assert llamadas.apuntar(**datos) is None


@pytest.mark.asyncio
async def test_una_cuota_gastada_llega_como_cuota_y_no_como_clave_mala() -> None:
    """Un 401 haría que el integrador revisara su clave, que está bien."""
    import httpx
    from crmcore.errors import CuotaAgotada

    from services.gateway import claves

    def responder(peticion: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "detail": "La clave ha gastado su cuota",
                "error_code": "clave_api.cuota_agotada",
            },
            headers={"retry-after": "120"},
        )

    claves.limpiar_cache()
    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as cliente:
        with pytest.raises(CuotaAgotada) as error:
            await claves.principal_de_clave(
                cliente, "crm_" + uuid4().hex, ip="", url_identity="http://identity"
            )
    assert error.value.reintentar_en_s == 120


async def test_lo_apuntado_sale_aunque_no_llegue_otra_llamada(monkeypatch: Any) -> None:
    """El lote sólo salía con la llamada siguiente: una integración que dejaba
    de llamar se llevaba sus últimas llamadas sin que llegaran al portal."""
    import asyncio

    from crmcore.config import get_settings

    from services.gateway import llamadas

    monkeypatch.setattr(get_settings(), "claves_llamadas_lote", 1000)
    monkeypatch.setattr(get_settings(), "claves_llamadas_intervalo_s", 0.5)
    monkeypatch.setattr(llamadas, "_pendientes", [])
    import time as _time

    monkeypatch.setattr(llamadas, "_ultimo_envio", _time.monotonic())
    llamadas.apuntar(
        clave_id="k",
        tenant_id="t",
        metodo="GET",
        ruta="/api/v1/accounts",
        status=500,
        duracion_ms=3,
        request_id="r",
    )
    enviados: list[Any] = []

    class _Cliente:
        async def post(self, url: str, **kw: Any) -> Any:
            enviados.append(kw["json"]["llamadas"])

            class _R:
                status_code = 200

            return _R()

    tarea = asyncio.get_running_loop().create_task(
        llamadas.vaciar_cada_intervalo(lambda _s: (_Cliente(), "http://identity"))
    )
    await asyncio.sleep(1.2)
    tarea.cancel()
    assert enviados and enviados[0][0]["status"] == 500
