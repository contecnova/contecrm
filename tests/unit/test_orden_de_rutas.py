"""Una ruta con parámetro no puede tapar a una ruta fija.

FastAPI casa las rutas **en el orden en que se declaran**. Si `/leads/{lead_id}`
va antes que `/leads/motivos-descarte`, la segunda no se alcanza nunca: la
petición encaja en la primera, «motivos-descarte» se intenta leer como UUID y el
servidor contesta **422 «no es un UUID válido»**, que no tiene nada que ver con
lo que se pidió.

Ha pasado dos veces en este repositorio —`/conocimiento/articulos` tapada por
`/conocimiento/{articulo_id}`, y `/leads/motivos-descarte` tapada por
`/leads/{lead_id}`— y las dos veces el síntoma fue un 422 incomprensible en una
pantalla que se quedaba vacía. No es algo que se vea leyendo el fichero: hay que
mirar el orden de dos decoradores que pueden estar a trescientas líneas.

Se comprueba sobre las rutas **realmente montadas**, porque parte se registran
desde código (`crmcore.http.listados`) y un análisis del texto no las ve.
"""

from __future__ import annotations

import importlib
import os

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


@pytest.fixture(autouse=True)
def _devolver_el_servicio():
    """Deja `SERVICE_NAME` como estaba.

    Estas pruebas cambian el servicio en curso para cargar el contrato de cada
    uno. Sin devolverlo, la siguiente prueba del fichero siguiente arranca
    creyendo que es otro servicio y falla por un motivo que no tiene nada que
    ver con lo que comprueba — que es la peor forma de fallo que puede tener una
    suite, porque se busca donde no está.
    """
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


@pytest.mark.parametrize("servicio", SERVICIOS)
def test_ninguna_ruta_con_parametro_tapa_una_ruta_fija(servicio: str) -> None:
    os.environ["SERVICE_NAME"] = servicio
    from crmcore.config import limpiar_cache_settings

    limpiar_cache_settings()
    app = importlib.import_module(f"services.{servicio}.main").app
    # El contrato y no `app.routes`: esta versión de FastAPI envuelve los
    # routers incluidos, y recorrer `routes` devuelve envoltorios. El orden del
    # diccionario de `paths` es el de declaración, que es el que se prueba.
    caminos = list((app.openapi().get("paths") or {}).items())

    tapadas: list[str] = []
    for i, (camino, ops) in enumerate(caminos):
        if "{" not in camino or not camino.startswith("/api/v1/"):
            continue
        metodos = {m.upper() for m in ops}
        for fijo, ops_fijo in caminos[i + 1 :]:
            if "{" in fijo or not fijo.startswith("/api/v1/"):
                continue
            if not (metodos & {m.upper() for m in ops_fijo}):
                continue
            tramos_p, tramos_f = camino.split("/"), fijo.split("/")
            if len(tramos_p) != len(tramos_f):
                continue
            if all(
                tp == tf or tp.startswith("{") for tp, tf in zip(tramos_p, tramos_f, strict=True)
            ):
                tapadas.append(f"{fijo} queda tapada por {camino}, declarada antes")

    assert not tapadas, (
        f"En «{servicio}» hay rutas inalcanzables:\n  "
        + "\n  ".join(dict.fromkeys(tapadas))
        + "\n\nDeclara la ruta fija ANTES que la que lleva parámetro. El síntoma, si "
        "no, es un 422 diciendo que el nombre de la ruta no es un identificador válido."
    )
