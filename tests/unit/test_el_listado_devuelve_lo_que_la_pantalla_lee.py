"""Los listados que una pantalla lee devuelven los campos que lee.

Fija lo que el guardián estático —`test_la_pantalla_no_se_inventa_el_campo`—
sólo puede comprobar por fuera. El guardián dice que la pantalla no pide nada
que la ruta no declare; esto dice que la ruta **lo manda de verdad**, que es lo
que el 29-10-2026 fallaba en cuatro pantallas a la vez.

Las tres que se arreglan aquí tienen el mismo origen: el dato que hace falta
para leer la fila no es una columna de la fila.

  · el **título** de un artículo vive en `versiones_articulo`;
  · los **miembros** de una campaña se cuentan en `miembros_campana`;
  · los **criterios** de un territorio sí son una columna, y el listado escrito
    a mano no la devolvía.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.fechas import hoy

from services.sales import territorios as ter
from services.service import conocimiento as kb


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


# ── El título de un artículo (CRM-04.03.01.01) ────────────────────────────


@pytest.mark.db
def test_el_listado_de_articulos_trae_su_titulo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Sin esto la lista sale sin nombres y el buscador tumba la pantalla."""
    articulo, _ = kb.crear_articulo(
        uow, clave="reiniciar", titulo="Cómo reiniciar", cuerpo="Pulsa el botón"
    )
    db.flush()

    salida = kb.titulos_de(db, [articulo])
    assert salida[articulo.id]["titulo"] == "Cómo reiniciar"
    # Y se dice que lo que se enseña es el borrador: citarle a un cliente un
    # texto que nadie ha aprobado es justo lo que esto evita.
    assert salida[articulo.id]["es_borrador"] is True
    assert salida[articulo.id]["publico"] is False


@pytest.mark.db
def test_manda_la_version_publicada_y_no_la_ultima(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """El caso que lo pide: se publica la 1 y se escribe la 2 encima.

    Si ganara la última, el portal enseñaría el nombre de un artículo que
    todavía no ha aprobado nadie.
    """
    articulo, _ = kb.crear_articulo(
        uow,
        clave="reiniciar",
        titulo="Cómo reiniciar",
        cuerpo="Pulsa el botón",
        revisar_el=hoy() + timedelta(days=90),
    )
    kb.publicar(uow, articulo.id, aprobada_por=uuid4(), audiencia="cliente")
    db.flush()
    kb.nueva_version(uow, articulo.id, titulo="Reinicio (borrador nuevo)", cuerpo="…")
    db.flush()

    salida = kb.titulos_de(db, [articulo])
    assert salida[articulo.id]["titulo"] == "Cómo reiniciar"
    assert salida[articulo.id]["es_borrador"] is False
    assert salida[articulo.id]["publico"] is True


@pytest.mark.db
def test_un_articulo_sin_version_no_se_queda_sin_nombre(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Una fila que no se puede ni nombrar ni abrir es peor que no tenerla."""
    articulo, _ = kb.crear_articulo(
        uow, clave="reiniciar", titulo="Cómo reiniciar", cuerpo="Pulsa el botón"
    )
    db.flush()
    for version in list(articulo.versiones) if hasattr(articulo, "versiones") else []:
        db.delete(version)
    db.execute(
        kb.VersionArticulo.__table__.delete().where(kb.VersionArticulo.articulo_id == articulo.id)
    )
    db.flush()

    salida = kb.titulos_de(db, [articulo])
    assert salida[articulo.id]["titulo"] == "reiniciar"


@pytest.mark.db
def test_una_pagina_entera_se_resuelve_de_golpe(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Y se dice cuántos ha recorrido: una que no mirara ninguno saldría igual
    de verde que una que los mira todos."""
    articulos = []
    for i in range(5):
        articulo, _ = kb.crear_articulo(uow, clave=f"art-{i}", titulo=f"Artículo {i}", cuerpo="…")
        articulos.append(articulo)
    db.flush()

    salida = kb.titulos_de(db, articulos)
    assert len(salida) == 5
    assert {s["titulo"] for s in salida.values()} == {f"Artículo {i}" for i in range(5)}


@pytest.mark.db
def test_sin_articulos_no_consulta(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    assert kb.titulos_de(db, []) == {}


# ── Los miembros de una campaña (CRM-02.02.01.04) ─────────────────────────


@pytest.fixture
def cliente_marketing() -> Any:
    import importlib
    import os

    from crmcore.config import get_settings
    from starlette.testclient import TestClient

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        modulo = importlib.import_module("services.marketing.main")
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
        },
        get_settings().secret_key.get_secret_value(),
    )


@pytest.mark.db
def test_el_listado_de_campanas_cuenta_sus_miembros(
    cliente_marketing: Any, cabeceras: dict[str, str], db: Any
) -> None:
    """La pantalla pintaba «miembros» y la campaña no tiene esa columna.

    Se entra por la ruta y no por el ORM: el agregado lo pega el camino de
    lectura, así que comprobarlo en la tabla no diría nada de lo que ve quien
    abre la pantalla.
    """
    creada = cliente_marketing.post(
        "/api/v1/campanas",
        headers=cabeceras,
        json={"clave": f"c-{uuid4().hex[:8]}", "nombre": "Campaña con gente"},
    )
    assert creada.status_code in (200, 201), creada.text
    campana_id = creada.json()["id"]

    for _ in range(3):
        alta = cliente_marketing.post(
            f"/api/v1/campanas/{campana_id}/miembros",
            headers=cabeceras,
            json={"objeto": "contacto", "objeto_ids": [str(uuid4())]},
        )
        assert alta.status_code in (200, 201), alta.text

    listado = cliente_marketing.get("/api/v1/campanas?limite=50", headers=cabeceras)
    assert listado.status_code == 200, listado.text
    filas = listado.json()["items"]
    suya = next(f for f in filas if f["id"] == campana_id)
    assert suya["miembros"] == 3


# ── Los criterios de un territorio (CRM-01.04.01) ─────────────────────────


@pytest.mark.db
def test_el_listado_de_territorios_devuelve_sus_criterios(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Decía «0 criterios» en todos, incluido el que reparte media cartera.

    Y el `?? 0` de la pantalla es lo que lo escondía: sin él se habría visto
    como un hueco, con él se veía como un territorio sin criterios.
    """
    from services.sales.api_territorios import listar

    creado, _avisos = ter.crear(
        uow,
        clave="norte",
        nombre="Norte",
        criterios=[{"tipo": "geografia", "condiciones": [{"campo": "provincia", "valor": "B"}]}],
        prioridad=10,
    )
    db.flush()

    class _Principal:
        pass

    principal = _Principal()
    principal.tenant_id = tenant_id  # type: ignore[attr-defined]

    filas = listar(db, principal)  # type: ignore[arg-type]
    suyo = next(f for f in filas if f["id"] == str(creado.id))
    assert len(suyo["criterios"]) == 1
    assert suyo["criterios"][0]["tipo"] == "geografia"
    assert suyo["padre_id"] is None
