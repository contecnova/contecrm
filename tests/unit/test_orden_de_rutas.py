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

**Y la tapada no siempre es una ruta fija.** Esta prueba solo miraba las fijas y
por eso pasaba en verde con OCHO rutas inalcanzables: una con parámetro también
tapa a otra con parámetro cuando es más general en cada tramo. Eran
`/documentos/aprobacion/{documento_id}` (tres servicios),
`/ia/prediccion/acierto/{tipo}`, `/metricas/{metrica_id}`,
`/firma/sobres/{sobre_firma_id}/archivar` y las dos de
`/canales-servicio/{canal_id}`. Las dos últimas familias no eran ni cuestión de
orden: eran la misma ruta escrita dos veces con distinto nombre de parámetro.

Se comprueba sobre las rutas **realmente montadas**, porque parte se registran
desde código (`crmcore.http.listados`) y un análisis del texto no las ve.
"""

from __future__ import annotations

import importlib
import os

import pytest

# Su fallo llega a producción y no se arregla después: una fuga entre tenants o
# una ruta publicada que no responde. Por eso esta prueba NO sale del push.
pytestmark = pytest.mark.despliegue

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

    # MIRAR CERO RUTAS NO ES ESTAR EN VERDE. Si el contrato viniera vacío
    # —porque el servicio cambie de forma o porque leerlo se rompa—, la lista de
    # tapadas saldría vacía y esto pasaría sin haber comprobado nada. Es el
    # defecto que tenía la prueba de fugas entre tenants, y allí costó 709 rutas.
    con_parametro = [c for c, _ in caminos if "{" in c and c.startswith("/api/v1/")]
    assert con_parametro, (
        f"«{servicio}» no publica ni una ruta con parámetro: o ha cambiado de forma "
        "o el contrato no se está leyendo. Pasar en verde sin mirar nada, no."
    )

    tapadas: list[str] = []
    for i, (camino, ops) in enumerate(caminos):
        if "{" not in camino or not camino.startswith("/api/v1/"):
            continue
        metodos = {m.upper() for m in ops}
        # La tapada NO tiene por qué ser una ruta fija, y darlo por hecho fue el
        # agujero de la primera versión de esta prueba: pasaba en verde mientras
        # ocho rutas eran inalcanzables. Basta con que la de delante sea más
        # general en cada tramo — `/documentos/{objeto_tipo}/{objeto_id}` se
        # traga `/documentos/aprobacion/{documento_id}` porque `{objeto_tipo}`
        # encaja con el literal «aprobacion».
        for detras, ops_detras in caminos[i + 1 :]:
            if not detras.startswith("/api/v1/"):
                continue
            if not (metodos & {m.upper() for m in ops_detras}):
                continue
            tramos_p, tramos_d = camino.split("/"), detras.split("/")
            if len(tramos_p) != len(tramos_d):
                continue
            if all(
                tp == td or tp.startswith("{") for tp, td in zip(tramos_p, tramos_d, strict=True)
            ):
                tapadas.append(f"{detras} queda tapada por {camino}, declarada antes")

    assert not tapadas, (
        f"En «{servicio}» hay rutas inalcanzables:\n  "
        + "\n  ".join(dict.fromkeys(tapadas))
        + "\n\nDeclara la ruta MÁS CONCRETA antes que la más general. Si las dos "
        "tienen la misma forma y solo cambian el nombre del parámetro, no hay orden "
        "que valga: son la misma ruta escrita dos veces y sobra una. El síntoma, si "
        "no, es un 422 diciendo que el nombre de la ruta no es un identificador válido."
    )
