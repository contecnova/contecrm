"""El modo sin conexión, aplicado de verdad (CRM-06.02.01.04), por HTTP.

Medido el 09-11-2026: `POST /{servicio}/movil/sincronizar` sólo devolvía el
**plan** y el front no tenía nada sin conexión, así que lo hecho sin red no
llegaba a ningún sitio. Ahora, con `aplicar: true`, el servidor escribe lo que
no choca —por la MISMA función que el PATCH de la ficha genérica y con su
permiso— y devuelve los conflictos con lo que hay en el servidor, que es lo que
pinta la pantalla para resolverlos.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


@pytest.fixture
def cliente(monkeypatch: Any) -> Any:
    import importlib
    import os

    from crmcore.config import get_settings
    from crmcore.tareas import RelevoDeTareas

    async def _no_correr(self: Any) -> None:
        return None

    monkeypatch.setattr(RelevoDeTareas, "correr", _no_correr)
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


def _cabeceras(tenant_id: UUID, permisos: str) -> dict[str, str]:
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
            H_PERMISOS: permisos,
            H_ROLES: "comercial",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


def _contacto(db: Any, tenant_id: UUID, **campos: Any) -> Any:
    from services.party.modelos import Contacto

    fila = Contacto(
        tenant_id=tenant_id,
        nombre=campos.pop("nombre", "Ana"),
        nombre_completo="Ana Pérez",
        clave_canonica="ana perez",
        **campos,
    )
    db.add(fila)
    db.flush()
    db.refresh(fila)
    return fila


def test_lo_que_no_choca_se_escribe_y_lo_que_choca_vuelve_con_lo_del_servidor(
    cliente: Any, db: Any, tenant_id: UUID
) -> None:
    fila = _contacto(db, tenant_id, cargo="Directora")
    version = int(fila.version or 0)
    cab = _cabeceras(tenant_id, "*:*")

    respuesta = cliente.post(
        "/api/v1/party/movil/sincronizar",
        headers=cab,
        json={
            "aplicar": True,
            "operaciones": [
                {
                    # Por la COLECCIÓN, que es lo que tiene el front encolado.
                    "id_cliente": "sin-red-1",
                    "recurso": "contacts",
                    "registro_id": str(fila.id),
                    "version_base": version,
                    "campos_base": {"nombre": "Ana"},
                    "campos": {"nombre": "Ana María"},
                },
            ],
        },
    )
    assert respuesta.status_code == 200, respuesta.text
    entrada = respuesta.json()["plan"][0]
    assert entrada["accion"] == "aplicada", entrada
    db.expire_all()
    assert db.get(type(fila), fila.id).nombre == "Ana María"
    nueva = entrada["version"]
    assert nueva > version
    # Lo escrito sale de la cola: si no, el aviso de pendientes no se apaga.
    assert respuesta.json()["cola"]["pendientes"] == 0

    # Ahora el móvil escribe el cargo sobre la versión VIEJA y otra persona ya
    # lo cambió: es un choque, no se escribe, y viene lo que hay en el servidor.
    fila_bd = db.get(type(fila), fila.id)
    fila_bd.cargo = "Consejera"
    db.flush()
    choque = cliente.post(
        "/api/v1/party/movil/sincronizar",
        headers=cab,
        json={
            "aplicar": True,
            "operaciones": [
                {
                    "id_cliente": "sin-red-2",
                    "recurso": "contacts",
                    "registro_id": str(fila.id),
                    "version_base": version,
                    "campos_base": {"cargo": "Directora"},
                    "campos": {"cargo": "Gerente"},
                },
            ],
        },
    )
    assert choque.status_code == 200, choque.text
    plan = choque.json()["plan"][0]
    assert plan["accion"] == "conflicto"
    assert plan["valores_servidor"] == {"cargo": "Consejera"}
    db.expire_all()
    assert db.get(type(fila), fila.id).cargo == "Consejera"


def test_sin_el_permiso_de_escribir_no_se_escribe(cliente: Any, db: Any, tenant_id: UUID) -> None:
    """La misma puerta que el PATCH: quien no puede editar el contacto con
    conexión tampoco puede sin ella."""
    fila = _contacto(db, tenant_id)
    respuesta = cliente.post(
        "/api/v1/party/movil/sincronizar",
        headers=_cabeceras(tenant_id, "*:read"),
        json={
            "aplicar": True,
            "operaciones": [
                {
                    "id_cliente": "sin-red-3",
                    "objeto": "contacto",
                    "registro_id": str(fila.id),
                    "version_base": int(fila.version or 0),
                    "campos": {"nombre": "Otra"},
                }
            ],
        },
    )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["plan"][0]["accion"] == "rechazada"
    db.expire_all()
    assert db.get(type(fila), fila.id).nombre == "Ana"


def test_una_creacion_va_por_su_ruta(cliente: Any, db: Any, tenant_id: UUID) -> None:
    """Crear tiene sus propias reglas por objeto: aquí se escribiría sin ellas."""
    respuesta = cliente.post(
        "/api/v1/party/movil/sincronizar",
        headers=_cabeceras(tenant_id, "*:*"),
        json={
            "aplicar": True,
            "operaciones": [
                {"id_cliente": "sin-red-4", "tipo": "crear", "objeto": "contacto", "campos": {}}
            ],
        },
    )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["plan"][0]["accion"] == "aplicar_por_su_ruta"


def test_solo_se_escribe_lo_que_cambio_el_movil(cliente: Any, db: Any, tenant_id: UUID) -> None:
    """Un formulario manda el registro entero. Escribirlo todo pisaría con el
    valor viejo lo que otra persona cambió en un campo que el móvil ni tocó."""
    fila = _contacto(db, tenant_id, cargo="Directora")
    version = int(fila.version or 0)
    fila_bd = db.get(type(fila), fila.id)
    fila_bd.cargo = "Consejera"  # lo cambia otra persona mientras tanto
    db.flush()
    respuesta = cliente.post(
        "/api/v1/party/movil/sincronizar",
        headers=_cabeceras(tenant_id, "*:*"),
        json={
            "aplicar": True,
            "operaciones": [
                {
                    "id_cliente": "sin-red-5",
                    "objeto": "contacto",
                    "registro_id": str(fila.id),
                    "version_base": version,
                    "campos_base": {"nombre": "Ana", "cargo": "Directora"},
                    "campos": {"nombre": "Ana María", "cargo": "Directora"},
                }
            ],
        },
    )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["plan"][0]["accion"] == "aplicada"
    db.expire_all()
    final = db.get(type(fila), fila.id)
    assert final.nombre == "Ana María"
    assert final.cargo == "Consejera"
