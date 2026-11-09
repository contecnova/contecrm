"""Subir un fichero con clave de idempotencia y descargarlo con el enlace
firmado, por HTTP (los dos rotos hasta el 09-11-2026).

  * La interfaz manda SIEMPRE `Idempotency-Key`, y la dependencia global de
    idempotencia leía el cuerpo crudo de una petición cuyo formulario ya había
    leído FastAPI: «Stream consumed», 500 en toda subida de fichero.
  * El enlace firmado —el que existe para abrirse sin sesión: un `<img src>`, un
    correo, un proveedor que descarga una grabación— pedía `DbDep`, que exige
    tenant: 401 «auth.requerida» siempre, con el token bien firmado.

Salió al transcribir una reunión (CRM-01.02.01.05): el audio se sube como
adjunto de la actividad y el proveedor lo descarga de un enlace firmado.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

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
        modulo = importlib.import_module("services.party.main")
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
            H_USER: str(uuid4()),
            H_PERMISOS: "*:*",
            H_ROLES: "admin",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


def test_se_sube_con_clave_y_se_descarga_con_el_enlace_sin_sesion(
    cliente: TestClient, cabeceras: dict[str, str]
) -> None:
    contenido = b"RIFF-una-grabacion-de-prueba"
    clave = str(uuid4())
    r = cliente.post(
        "/api/v1/adjuntos/actividad",
        headers={**cabeceras, "Idempotency-Key": clave},
        files={"fichero": ("reunion.wav", contenido, "audio/wav")},
        data={"objeto_id": str(uuid4())},
    )
    assert r.status_code == 201, r.text
    adjunto = r.json()["id"]

    # El mismo formulario con la misma clave no sube otro: devuelve el primero.
    otra = cliente.post(
        "/api/v1/adjuntos/actividad",
        headers={**cabeceras, "Idempotency-Key": clave},
        files={"fichero": ("reunion.wav", contenido, "audio/wav")},
        data={"objeto_id": r.json()["objeto_id"]},
    )
    assert otra.status_code == 201 and otra.json()["id"] == adjunto

    e = cliente.post(f"/api/v1/adjuntos/actividad/{adjunto}/enlace", headers=cabeceras)
    assert e.status_code == 200, e.text
    # Sin ninguna cabecera: es para lo que existe el enlace.
    d = cliente.get(f"/api/v1/adjuntos/actividad/enlace/{e.json()['token']}")
    assert d.status_code == 200, d.text
    assert d.content == contenido

    manipulado = e.json()["token"][:-1] + ("0" if e.json()["token"][-1] != "0" else "1")
    assert cliente.get(f"/api/v1/adjuntos/actividad/enlace/{manipulado}").status_code == 403
