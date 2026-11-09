"""Las pantallas de lecciones, segregación, TCSEC y versiones piden lo que el servidor manda.

Cada una declara la forma de la respuesta (`llamar<Tipo>(…)`) y ninguna prueba
de servidor pedía esas rutas, así que si el servidor dejaba de mandar un campo
la pantalla se quedaba vacía sin que nadie se enterara. Lo cazó
`test_la_pantalla_no_lee_campos_que_nadie_envia` el 09-11-2026. Aquí se pide
cada ruta por HTTP y se comprueban los campos que lee su pantalla.
"""

from __future__ import annotations

import importlib
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

from tests.unit.test_forecast import pipeline, uow  # noqa: F401
from tests.unit.test_lecciones_aprendidas import _op

pytestmark = pytest.mark.db


@contextmanager
def _cliente(servicio: str, monkeypatch: Any) -> Iterator[TestClient]:
    from crmcore.config import get_settings
    from crmcore.tareas import RelevoDeTareas

    async def _no_correr(self: Any) -> None:
        return None

    monkeypatch.setattr(RelevoDeTareas, "correr", _no_correr)
    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        with TestClient(importlib.import_module(f"services.{servicio}.main").app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


def _cabeceras(tenant_id: UUID, usuario: UUID | None = None) -> dict[str, str]:
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
            H_USER: str(usuario or uuid4()),
            H_PERMISOS: "*:*",
            H_ROLES: "admin",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


def test_la_leccion_y_el_expediente(
    db: Any,
    tenant_id: UUID,
    pipeline: Any,  # noqa: F811
    contexto_tenant: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from crmcore.db.uow import UnidadDeTrabajo

    from services.sales import lecciones as lec

    monkeypatch.setattr("crmcore.http.interno.invocar", lambda **_: {"estado": 503, "datos": None})
    perdida = _op(db, tenant_id, pipeline, "perdida", dias=20, motivo_perdida="precio")
    fila = lec.al_cerrar(UnidadDeTrabajo(db=db, tenant_id=tenant_id), perdida, ganada=False)
    db.flush()
    with _cliente("sales", monkeypatch) as cli:
        cab = _cabeceras(tenant_id)

        r = cli.get(f"/api/v1/lecciones/{fila.id}", headers=cab)
        assert r.status_code == 200, r.text[:300]
        leccion = r.json()
        for campo in ("id", "oportunidad_id", "titulo", "resultado", "estado", "obligatoria"):
            assert campo in leccion, (campo, sorted(leccion))
        assert isinstance(leccion["factores"], list)

        r = cli.get(f"/api/v1/opportunities/{perdida.id}/expediente", headers=cab)
        assert r.status_code == 200, r.text[:300]
        expediente = r.json()
        for campo in (
            "oportunidad",
            "recorrido",
            "cambios_de_rumbo",
            "presupuestos",
            "competencia",
        ):
            assert campo in expediente, (campo, sorted(expediente))
        assert {"id", "nombre", "importe", "moneda"} <= set(expediente["oportunidad"])


def test_simular_la_segregacion(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _cliente("identity", monkeypatch) as cli:
        r = cli.post(
            "/api/v1/segregacion/simular",
            headers=_cabeceras(tenant_id),
            json={"usuario_id": str(uuid4()), "roles": ["admin"]},
        )
        assert r.status_code == 200, r.text[:300]
        assert {"conflictos_nuevos", "limpio"} <= set(r.json())
        assert isinstance(r.json()["conflictos_nuevos"], list)


def test_la_evaluacion_tcsec(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _cliente("tenancy", monkeypatch) as cli:
        r = cli.get("/api/v1/tcsec/evaluacion", headers=_cabeceras(tenant_id))
        assert r.status_code == 200, r.text[:300]
        ev = r.json()
        for campo in (
            "generado_at",
            "nivel",
            "nombre_nivel",
            "siguiente",
            "falta_para_el_siguiente",
            "niveles",
            "requisitos",
        ):
            assert campo in ev, (campo, sorted(ev))
        requisito = ev["requisitos"][0]
        assert {"clave", "nivel", "titulo", "exige", "como", "estado", "detalle", "datos"} <= set(
            requisito
        )


def test_publicar_una_version_desde_el_editor(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _cliente("orchestrator", monkeypatch) as cli:
        cab = _cabeceras(tenant_id)
        definicion = {"inicio": "fin", "pasos": {"fin": {"tipo": "fin"}}}
        r = cli.post(
            "/api/v1/procesos/definiciones",
            headers=cab,
            json={
                "clave": "de_prueba",
                "nombre": "De prueba",
                "definicion": definicion,
                "estado": "borrador",
            },
        )
        assert r.status_code in (200, 201), r.text[:300]
        version = r.json()["version"]
        r = cli.post(
            f"/api/v1/procesos/definiciones/de_prueba/{version}/estado",
            headers=cab,
            json={"estado": "publicada"},
        )
        assert r.status_code == 200, r.text[:300]
        for campo in ("id", "clave", "version", "nombre", "estado", "definicion"):
            assert campo in r.json(), (campo, sorted(r.json()))
        assert r.json()["estado"] == "publicada"


def test_el_consumo_de_otra_empresa_no_se_ve(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Medido el 09-11-2026: la ruta no pedía permiso ni miraba de quién era el
    tenant, así que cualquiera con sesión leía el consumo de otra empresa."""
    with _cliente("tenancy", monkeypatch) as cli:
        propio = cli.get(f"/api/v1/tenants/{tenant_id}/consumo", headers=_cabeceras(tenant_id))
        assert propio.status_code == 200, propio.text[:300]
        ajeno = cli.get(f"/api/v1/tenants/{uuid4()}/consumo", headers=_cabeceras(tenant_id))
        assert ajeno.status_code == 404, ajeno.text[:300]


def test_las_identidades_de_un_contacto_no_revientan(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La ruta pasaba `objeto=` a una función que recibe el contacto: 500 siempre."""
    with _cliente("party", monkeypatch) as cli:
        cab = _cabeceras(tenant_id)
        r = cli.get(f"/api/v1/calidad-dato/identidades/contacto/{uuid4()}", headers=cab)
        assert r.status_code == 200, r.text[:300]
        assert {"senales", "cruzable"} <= set(r.json())
        r = cli.get(f"/api/v1/calidad-dato/identidades/cuenta/{uuid4()}", headers=cab)
        assert r.status_code == 404, r.text[:300]
