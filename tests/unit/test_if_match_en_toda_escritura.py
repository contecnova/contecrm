"""`If-Match` se respeta en toda escritura sobre un registro (CRM-00.02.01.09).

Medido el 10-11-2026: sólo la edición genérica lo comprobaba. El PATCH escrito a
mano de un contacto y su borrado aceptaban una versión vieja y pisaban o
borraban el cambio de otro. Lo cazó el modo sin conexión, que encola el borrado
con su versión. Ahora lo comprueba el núcleo para cualquier ruta
(`crmcore.http.concurrencia`).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from tests.unit.test_las_pantallas_de_gobierno_y_lecciones_piden_lo_que_hay import (
    _cabeceras,
    _cliente,
)

pytestmark = pytest.mark.db


def test_una_version_vieja_no_pisa_ni_borra(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _cliente("party", monkeypatch) as cli:
        cab = _cabeceras(tenant_id)
        r = cli.post("/api/v1/contacts", headers=cab, json={"nombre": "Concurrencia"})
        assert r.status_code == 201, r.text[:300]
        contacto = r.json()
        ruta = f"/api/v1/contacts/{contacto['id']}"
        leida = str(contacto["version"])

        # Otro lo cambia: la versión sube.
        r = cli.patch(ruta, headers={**cab, "If-Match": f'"{leida}"'}, json={"cargo": "Uno"})
        assert r.status_code == 200, r.text[:300]
        assert str(r.json()["version"]) != leida

        # Con la versión que ya no es, ni editar ni borrar.
        r = cli.patch(ruta, headers={**cab, "If-Match": f'"{leida}"'}, json={"cargo": "Dos"})
        assert r.status_code == 409, r.text[:300]
        r = cli.delete(ruta, headers={**cab, "If-Match": f'"{leida}"'})
        assert r.status_code == 409, r.text[:300]

        # Con la buena, sí; y sin cabecera, como siempre.
        actual = cli.get(ruta, headers=cab).json()["version"]
        r = cli.delete(ruta, headers={**cab, "If-Match": f'"{actual}"'})
        assert r.status_code == 204, r.text[:300]


def test_sin_cabecera_nada_cambia(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _cliente("party", monkeypatch) as cli:
        cab = _cabeceras(tenant_id)
        contacto = cli.post("/api/v1/contacts", headers=cab, json={"nombre": "Sin cabecera"}).json()
        ruta = f"/api/v1/contacts/{contacto['id']}"
        assert cli.patch(ruta, headers=cab, json={"cargo": "Uno"}).status_code == 200
        assert cli.patch(ruta, headers=cab, json={"cargo": "Dos"}).status_code == 200
        assert cli.delete(ruta, headers=cab).status_code == 204
