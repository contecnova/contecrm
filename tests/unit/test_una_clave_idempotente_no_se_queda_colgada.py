"""Una petición idempotente que se corta libera su clave (FUN-A-8, 13-11-2026).

La reserva solo se guardaba si la aplicación volvía. Cancelada por el tiempo
máximo de la petición, o con una excepción que nadie tradujo, la clave se
quedaba «en curso» las 24 h de retención y todos los reintentos con ella
recibían 409.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from crmcore.http import middleware


@pytest.mark.parametrize("excepcion", [RuntimeError("se rompió"), asyncio.CancelledError()])
async def test_la_reserva_se_libera_como_fallo(
    excepcion: BaseException, monkeypatch: pytest.MonkeyPatch
) -> None:
    guardadas: list[tuple[str, Any, dict[str, Any]]] = []

    async def _guardar(clave: str, tenant_id: Any, estado: dict[str, Any]) -> None:
        guardadas.append((clave, tenant_id, estado))

    monkeypatch.setattr(middleware, "_guardar_respuesta", _guardar)
    tenant = uuid4()

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        scope.setdefault("state", {})["idempotencia"] = {"clave": "k-1", "tenant_id": tenant}
        raise excepcion

    async def _recibir() -> dict[str, Any]:
        return {"type": "http.request", "body": b""}

    async def _enviar(_: Any) -> None:
        return None

    with pytest.raises(type(excepcion)):
        await middleware.IdempotenciaMiddleware(app)(
            {"type": "http", "method": "POST", "state": {}}, _recibir, _enviar
        )
    assert guardadas == [("k-1", tenant, {"status": 500, "cuerpo": b""})]
