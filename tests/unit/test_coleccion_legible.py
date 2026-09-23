"""Lo que se puede crear se tiene que poder leer.

Cuarenta colecciones del sistema tenían `POST` y no tenían `GET`: una cola de
casos, un canal de entrada, una lista de precios o un contrato se daban de alta
y desaparecían. La API contestaba **405 Method Not Allowed** y el front —que
declara esos recursos como listables— enseñaba una pantalla vacía sin decir por
qué. No era un fallo visible: era un agujero silencioso, y solo salió al abrir
la consola del navegador y mirar los errores uno a uno.

Este gate recorre las rutas **realmente montadas** en cada servicio, no los
decoradores del fichero: parte de los listados se registran desde
`crmcore.http.listados`, que un análisis del texto no ve. Si alguien añade un
`POST` a una colección nueva y se olvida del `GET`, falla aquí.

Las excepciones se nombran una a una **con su motivo**. Una excepción sin motivo
acaba siendo la puerta por la que vuelve el problema.
"""

from __future__ import annotations

import importlib
import os
from collections import defaultdict

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

# Rutas que aceptan `POST` sobre la raíz y **no son una colección**: serían
# acciones, donde listar no significa nada porque lo que hay es un efecto y no
# un conjunto.
#
# Hoy está vacío, y eso es el resultado: no queda ninguna. Se deja el mecanismo
# porque la próxima acción de ese tipo tendrá que declararse aquí **con su
# motivo** — una excepción sin motivo acaba siendo la puerta por la que vuelve
# el problema.
ACCIONES: dict[str, str] = {}


def _rutas_montadas(servicio: str) -> dict[str, set[str]]:
    """Prefijo de colección → métodos que admite su raíz."""
    os.environ["SERVICE_NAME"] = servicio
    from crmcore.config import limpiar_cache_settings

    limpiar_cache_settings()
    modulo = importlib.import_module(f"services.{servicio}.main")
    app = modulo.app

    por_prefijo: dict[str, set[str]] = defaultdict(set)
    for ruta in app.routes:
        camino = getattr(ruta, "path", "")
        metodos = getattr(ruta, "methods", set())
        if not camino.startswith("/api/v1/") or "{" in camino:
            continue
        por_prefijo[camino].update(metodos)
    return por_prefijo


@pytest.mark.parametrize("servicio", SERVICIOS)
def test_toda_coleccion_que_admite_alta_se_puede_listar(servicio: str) -> None:
    por_prefijo = _rutas_montadas(servicio)
    sin_listado: list[str] = []
    for camino, metodos in sorted(por_prefijo.items()):
        if "POST" not in metodos or "GET" in metodos:
            continue
        relativo = camino[len("/api/v1") :]
        if relativo in ACCIONES:
            continue
        sin_listado.append(relativo)

    assert not sin_listado, (
        f"En «{servicio}» hay colecciones que se pueden crear y no se pueden leer:\n  "
        + "\n  ".join(sin_listado)
        + "\n\nMonta su listado con `crmcore.http.listados.montar_listado`, o —si es "
        "una acción y no una colección— añádela a `ACCIONES` **con su motivo**."
    )


def test_las_excepciones_declaradas_siguen_existiendo() -> None:
    """Una excepción que sobra es una excepción que tapará algo el día que vuelva.

    Si una de estas rutas desaparece o se convierte en colección con su listado,
    su línea aquí deja de tener sentido y hay que quitarla. Sin esta
    comprobación, la lista solo crece.
    """
    vistas: set[str] = set()
    for servicio in SERVICIOS:
        for camino, metodos in _rutas_montadas(servicio).items():
            if "POST" in metodos and "GET" not in metodos:
                vistas.add(camino[len("/api/v1") :])

    sobran = sorted(set(ACCIONES) - vistas)
    assert not sobran, "Excepciones declaradas que ya no hacen falta:\n  " + "\n  ".join(sobran)
