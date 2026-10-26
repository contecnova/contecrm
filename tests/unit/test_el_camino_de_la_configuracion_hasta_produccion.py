"""Auditoría de la familia de entornos y despliegue (CRM-07.02.01).

Nueve capacidades declaradas hechas, ninguna con nota de auditoría. Se
recorrieron una a una el 26-10-2026 y tres no tenían ninguna prueba que las
nombrara por su identificador, que es lo que convierte el catálogo en
trazabilidad: sin el ID en la prueba, «enséñame la prueba de ESTO» se contesta
sabiéndose el código, y quien audita no se lo sabe.

Las tres, y lo que se encontró al mirarlas:

  · **CRM-07.02.01.01**, entornos separados. Están, son cuatro y la lista es
    cerrada. Lo que no estaba probado es que la separación **sea de verdad**:
    que lo desplegado en pruebas no se vea desde producción. Se prueba aquí.
  · **CRM-07.02.01.04**, configuración como código con control de versiones.
    Aquí sí había un agujero: el paquete guarda `referencia_git` desde el
    principio y **ninguna ruta la devolvía**. Se escribía al empaquetar y no se
    leía en ningún sitio, así que la pregunta que justifica el campo —«¿de qué
    commit sale lo que hay en producción?»— no se podía contestar desde el
    producto. Un campo que se escribe y no se lee no existe para quien lo
    necesita.
  · **CRM-07.02.01.05**, gates de calidad. Este repositorio no tiene CI a
    propósito: las garantías van en el pre-commit y en `preflight.py`. Lo que
    se vigila es que los niveles sigan existiendo y que el gate del catálogo
    siga dentro del nivel que corre antes de empujar — porque un gate que se
    cae de la lista deja de correr sin que nadie lo note.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture
def cliente(db: Any) -> Iterator[Any]:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        with TestClient(importlib.import_module("services.metadata.main").app) as cli:
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


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> Any:
    from crmcore.db.uow import UnidadDeTrabajo

    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


# ── CRM-07.02.01.01 · Entornos separados ──────────────────────────────────


def test_lo_desplegado_en_un_entorno_no_se_ve_desde_otro_crm_07_02_01_01(
    cliente: Any, cabeceras: dict[str, str], uow: Any, contexto_tenant: UUID
) -> None:
    """**Separados de verdad, no sólo nombrados.** Cuatro etiquetas sobre un
    único estado compartido serían peor que un entorno solo: darían la
    impresión de que probar no toca producción."""
    from services.metadata import entornos as ent

    en_pruebas = ent.empaquetar(uow, nombre="pruebas", contenido={"campos": [{"clave": "a"}]})
    en_produccion = ent.empaquetar(uow, nombre="prod", contenido={"campos": [{"clave": "b"}]})
    ent.desplegar(uow, paquete_id=en_pruebas.id, entorno="pruebas")
    ent.desplegar(uow, paquete_id=en_produccion.id, entorno="produccion")
    uow.db.flush()

    for entorno, esperado in (("pruebas", "pruebas"), ("produccion", "prod")):
        r = cliente.get(f"/api/v1/entornos/{entorno}/desplegado", headers=cabeceras)
        assert r.status_code == 200, r.text
        assert r.json()["paquete"] == esperado, (
            f"«{entorno}» enseña el paquete de otro entorno: los cuatro nombres "
            "estarían sobre un único estado compartido"
        )


def test_los_entornos_son_una_lista_cerrada_crm_07_02_01_01(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """Un entorno no es un dato: es una etapa del camino hasta producción. Y
    desplegar en uno inventado no puede quedarse guardado en ninguna parte."""
    from services.metadata.entornos import ENTORNOS

    r = cliente.get("/api/v1/entornos", headers=cabeceras)
    assert r.status_code == 200, r.text
    nombres = [e["nombre"] for e in r.json()["items"]]
    assert nombres == list(ENTORNOS)
    assert nombres[-1] == "produccion", "producción no es la última etapa del camino"

    inventado = cliente.get("/api/v1/entornos/casi_produccion/desplegado", headers=cabeceras)
    assert inventado.status_code == 422, inventado.text


# ── CRM-07.02.01.04 · Configuración como código ───────────────────────────


def test_de_que_commit_sale_lo_que_hay_puesto_crm_07_02_01_04(
    cliente: Any, cabeceras: dict[str, str], uow: Any, contexto_tenant: UUID
) -> None:
    """**El agujero.** `referencia_git` se escribía al empaquetar y no la
    devolvía ninguna ruta: la pregunta que justifica el campo no se podía
    contestar desde el producto."""
    from services.metadata import entornos as ent

    paquete = ent.empaquetar(
        uow,
        nombre="base",
        contenido={"campos": [{"clave": "nif"}]},
        referencia_git="refs/tags/v2.4.0@9f3c1ab",
    )
    ent.desplegar(uow, paquete_id=paquete.id, entorno="produccion", motivo="release de octubre")
    uow.db.flush()

    r = cliente.get("/api/v1/entornos/produccion/desplegado", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["hay"] is True
    assert cuerpo["referencia_git"] == "refs/tags/v2.4.0@9f3c1ab"
    assert cuerpo["motivo"] == "release de octubre"
    assert cuerpo["desplegado_at"] and cuerpo["huella"]


def test_sin_referencia_de_repositorio_se_dice_crm_07_02_01_04(
    cliente: Any, cabeceras: dict[str, str], uow: Any, contexto_tenant: UUID
) -> None:
    """Vacío es legítimo —hay tenants que configuran desde la consola— y por eso
    se dice en vez de dejar el hueco: lo que significa es que no hay un commit
    al que volver, sólo el paquete anterior."""
    from services.metadata import entornos as ent

    paquete = ent.empaquetar(uow, nombre="consola", contenido={"campos": [{"clave": "nif"}]})
    ent.desplegar(uow, paquete_id=paquete.id, entorno="produccion")
    uow.db.flush()

    cuerpo = cliente.get("/api/v1/entornos/produccion/desplegado", headers=cabeceras).json()
    assert cuerpo["referencia_git"] == ""
    assert "no declara referencia" in cuerpo["que_significa"]


def test_sin_nada_desplegado_no_se_dice_que_este_vacio_crm_07_02_01_04(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """«No consta» y «está vacío» son cosas distintas: lo que haya puesto se
    puso fuera del camino, y eso es justo lo que hay que mirar."""
    cuerpo = cliente.get("/api/v1/entornos/produccion/desplegado", headers=cabeceras).json()
    assert cuerpo["hay"] is False
    assert "fuera del camino" in cuerpo["porque"]


# ── CRM-07.02.01.05 · Gates de calidad ────────────────────────────────────


def test_los_gates_locales_siguen_en_su_sitio_crm_07_02_01_05() -> None:
    """Este repositorio **no tiene CI a propósito**: las garantías van en el
    pre-commit y en `preflight.py`, en tres niveles. Lo que no puede pasar es
    que un gate se caiga de la lista y deje de correr sin que nadie lo note —
    y menos el del catálogo, que es el que impide declarar hecho lo que no está
    citado ni documentado."""
    preflight = (RAIZ / "scripts/preflight.py").read_text(encoding="utf-8")
    for pieza in ("trazabilidad", "test_catalogo_trazabilidad.py", "ruff"):
        assert pieza in preflight, f"ya no consta «{pieza}» entre los gates"

    hook = (RAIZ / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "preflight" in hook, (
        "el pre-commit ya no llama al preflight: sin CI, es la única puerta que "
        "corre sola antes de empujar"
    )
