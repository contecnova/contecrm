"""Lo que la API deja hacer con un registro, se puede hacer desde el front.

Un CRM no son listados: son **acciones sobre registros**. Convertir un lead,
moverlo de etapa, escalar un caso, reabrirlo, fusionar duplicados. La API
publica más de doscientas y el front no ofrecía **ninguna**: se podía listar y
crear, y nada más. Con eso no se cierra un ciclo de trabajo, solo se mira.

Escribir un botón por acción habría garantizado que la mitad no se escribiera
nunca y que la otra mitad se quedara desfasada, así que la ficha las saca del
contrato: `crmcore` publica la superficie con el permiso de cada operación y el
OpenAPI dice qué campos pide cada una.

Este gate comprueba **que el mecanismo las alcanza**: recorre las acciones que
publica cada servicio sobre un registro y verifica que encajan en la forma que
la ficha sabe resolver —un solo parámetro, colgando de la colección—. Una acción
que no encaje no saldría en ninguna pantalla, y nadie se enteraría.
"""

from __future__ import annotations

import importlib
import os
import re

import pytest

SERVICIOS = [
    "tenancy",
    "identity",
    "metadata",
    "orchestrator",
    "automation",
    "integration",
    "eventing",
    "party",
    "sales",
    "analytics",
    "intelligence",
    "service",
    "marketing",
]

PARAMETRO = re.compile(r"\{[^}]+\}")


@pytest.fixture(autouse=True)
def _devolver_el_servicio():
    """Deja `SERVICE_NAME` como estaba, para no contaminar el resto de la suite."""
    from crmcore.config import limpiar_cache_settings

    previo = os.environ.get("SERVICE_NAME")
    try:
        yield
    finally:
        if previo is None:
            os.environ.pop("SERVICE_NAME", None)
        else:
            os.environ["SERVICE_NAME"] = previo
        limpiar_cache_settings()


def _contrato(servicio: str) -> dict:
    os.environ["SERVICE_NAME"] = servicio
    from crmcore.config import limpiar_cache_settings

    limpiar_cache_settings()
    app = importlib.import_module(f"services.{servicio}.main").app
    return app.openapi().get("paths") or {}


def _acciones(paths: dict) -> list[str]:
    """`POST /api/v1/<coleccion>/{id}/<accion>`, que es lo que la ficha resuelve."""
    return [
        camino
        for camino, ops in paths.items()
        if "post" in ops
        and camino.startswith("/api/v1/")
        and len(PARAMETRO.findall(camino)) == 1
        and len(camino.split("/")) == 6
        and camino.split("/")[4].startswith("{")
    ]


@pytest.mark.parametrize("servicio", SERVICIOS)
def test_las_acciones_de_un_registro_las_alcanza_la_ficha(servicio: str) -> None:
    paths = _contrato(servicio)
    acciones = _acciones(paths)

    # Cada acción tiene que colgar de una colección que exista y se pueda leer:
    # si la colección no tiene listado, a su ficha no se llega, y a la acción
    # tampoco.
    huerfanas: list[str] = []
    for camino in acciones:
        coleccion = "/".join(camino.split("/")[:4])
        ops = paths.get(coleccion) or {}
        if "get" not in ops:
            huerfanas.append(f"{camino} (su colección {coleccion} no se puede listar)")

    assert not huerfanas, (
        f"En «{servicio}» hay acciones a las que no se llega desde ninguna ficha:\n  "
        + "\n  ".join(huerfanas)
    )


def test_hay_acciones_de_verdad_y_el_gate_las_ve() -> None:
    """Un gate que no ve nada pasa siempre.

    Ha pasado ya dos veces en este repositorio —comprobaciones escritas sobre
    `app.routes`, que en esta versión de FastAPI devuelve envoltorios—, así que
    aquí se fija un suelo: si el recuento cae a cero, lo que se ha roto es la
    comprobación, no el sistema.
    """
    total = sum(len(_acciones(_contrato(s))) for s in SERVICIOS)
    # 144 medidas al escribir esto. El suelo va por debajo para que quitar una
    # acción a propósito no rompa el gate, pero lo bastante cerca para que
    # una comprobación que deja de ver el sistema sí lo rompa.
    assert total > 120, f"solo se ven {total} acciones sobre registros; el gate no está mirando"
