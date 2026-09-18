"""RT-1 — Frontless: todo existe como servicio con contrato antes que como UI.

Cubre CRM-00.02.01.01 (todo lo que hace la UI es posible por API),
CRM-00.02.01.04 (OpenAPI generado del código) y CRM-00.02.03.01 (cero lógica de
negocio en la capa de presentación).

El catálogo lo pide en su primera restricción transversal, y la forma de que no
se quede en una declaración es comprobarlo:

  * Todo servicio publica su **OpenAPI** y ahí está todo lo que sabe hacer.
  * Ninguna ruta se queda **sin documentar**: un endpoint sin descripción es uno
    que solo sabe usar quien lo escribió.
  * Toda operación de escritura declara **qué devuelve**, para que un cliente
    headless no tenga que adivinar la forma de la respuesta.
  * El **catálogo mínimo de recursos** del Anexo A está cubierto por rutas
    reales para lo que la fase actual dice tener hecho.

Lo que esta prueba NO puede comprobar —y conviene decirlo— es que no exista una
funcionalidad **solo** en una interfaz: aquí todavía no hay interfaz. Cuando la
haya, el gate que hace falta es el que compara las llamadas que hace la UI con
las rutas públicas, y está anotado en el manual técnico como pendiente de la
fase 1.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

RAIZ = Path(__file__).resolve().parents[2]
SERVICIOS = sorted(
    p.name
    for p in (RAIZ / "services").iterdir()
    if p.is_dir() and not p.name.startswith("_") and (p / "main.py").exists()
)

# Rutas que no forman parte del contrato funcional.
INFRAESTRUCTURA = {"/health", "/health/live", "/health/ready", "/metrics"}


def _app(servicio: str) -> Any:
    """Carga la aplicación de un servicio sin levantar nada."""
    import os

    os.environ["SERVICE_NAME"] = servicio
    os.environ["BUS_BACKEND"] = "memoria"
    modulo = importlib.import_module(f"services.{servicio}.main")
    return modulo.app


@pytest.mark.parametrize("servicio", SERVICIOS)
def test_cada_servicio_publica_su_contrato(servicio: str) -> None:
    """El OpenAPI existe, se genera del código y no está vacío."""
    esquema = _app(servicio).openapi()
    assert esquema["openapi"].startswith("3."), "se espera OpenAPI 3.x"
    funcionales = [r for r in esquema["paths"] if r not in INFRAESTRUCTURA]
    if servicio == "gateway":
        # El gateway es un proxy: su contrato es el de los servicios de detrás,
        # y su única ruta propia es el registro de servicios.
        assert "/api/v1/servicios" in esquema["paths"]
        return
    assert funcionales, f"«{servicio}» no publica ninguna ruta funcional"


@pytest.mark.parametrize("servicio", SERVICIOS)
def test_toda_ruta_esta_documentada(servicio: str) -> None:
    """Resumen obligatorio en cada operación.

    Un endpoint sin descripción obliga a leer el código para usarlo, que es
    exactamente lo que un contrato debería evitar.
    """
    esquema = _app(servicio).openapi()
    sin_resumen: list[str] = []
    for ruta, metodos in esquema["paths"].items():
        if ruta in INFRAESTRUCTURA:
            continue
        for metodo, operacion in metodos.items():
            if metodo not in ("get", "post", "put", "patch", "delete"):
                continue
            if not (operacion.get("summary") or "").strip():
                sin_resumen.append(f"{metodo.upper()} {ruta}")
    assert not sin_resumen, f"Rutas sin resumen en «{servicio}»: {sin_resumen}"


@pytest.mark.parametrize("servicio", SERVICIOS)
def test_los_errores_estan_declarados_en_el_contrato(servicio: str) -> None:
    """Toda operación declara al menos una respuesta de error.

    FastAPI documenta el 422 de validación solo; lo que se comprueba aquí es que
    ninguna operación declare únicamente el camino feliz, porque un cliente que
    no sabe qué errores esperar no puede tratarlos.
    """
    esquema = _app(servicio).openapi()
    solo_felices: list[str] = []
    for ruta, metodos in esquema["paths"].items():
        if ruta in INFRAESTRUCTURA:
            continue
        for metodo, operacion in metodos.items():
            if metodo not in ("post", "put", "patch", "delete"):
                continue
            codigos = set(operacion.get("responses", {}))
            if not any(c.startswith(("4", "5")) for c in codigos):
                solo_felices.append(f"{metodo.upper()} {ruta} → {sorted(codigos)}")
    assert (
        not solo_felices
    ), f"Operaciones de escritura sin errores declarados en «{servicio}»: {solo_felices}"


def test_el_anexo_a_esta_cubierto_para_lo_que_dice_estar_hecho() -> None:
    """Los recursos del Anexo A de la fase 0 tienen rutas reales.

    El Anexo A es la lista con la que se verifica que el sistema es headless de
    verdad. Aquí solo se exige lo de plataforma, que es lo que cubre la fase 0;
    los de ventas, servicio y marketing llegan con sus fases.
    """
    import yaml

    catalogo = yaml.safe_load(
        (RAIZ / "docs" / "catalogo" / "catalogo.yaml").read_text(encoding="utf-8")
    )
    # Correspondencia entre el nombre del recurso en el Anexo A y la ruta real.
    # Se declara porque el anexo usa nombres en inglés (es la convención de la
    # industria para un catálogo de API) y las rutas están en castellano.
    equivalencias = {
        "tenants": "/api/v1/tenants",
        "users": "/api/v1/usuarios",
        "roles": "/api/v1/roles",
        "metadata/objects": "/api/v1/metadata/objetos",
        "workflows": "/api/v1/procesos/definiciones",
        "workflow-instances": "/api/v1/instancias",
        "webhooks": "/api/v1/webhooks",
        "events": "/api/v1/eventos/catalogo",
        "feature-flags": "/api/v1/flags/{clave}",
        "quotas-usage": "/api/v1/tenants/{tenant_id}/consumo",
    }
    todas_las_rutas: set[str] = set()
    for servicio in SERVICIOS:
        todas_las_rutas |= set(_app(servicio).openapi()["paths"])

    faltan = [recurso for recurso, ruta in equivalencias.items() if ruta not in todas_las_rutas]
    assert not faltan, "Recursos del Anexo A previstos para la fase 0 sin ruta:\n  " + "\n  ".join(
        f"{r} → {equivalencias[r]}" for r in faltan
    )
    # Y que el anexo siga ahí completo, para que nadie lo recorte al implementarlo.
    assert len(catalogo["anexo_a_recursos"]["plataforma"]) >= 19
