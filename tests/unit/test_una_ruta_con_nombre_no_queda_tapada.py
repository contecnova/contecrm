"""Una ruta con nombre propio no queda detrás de un `/{id}` que se la trague.

Starlette elige la **primera** ruta que encaja por la forma del camino, y
`/usuarios/{usuario_id}` encaja con `/usuarios/licencias`: si la del parámetro
está declarada antes, «licencias» llega como identificador y contesta 422. No
falla al arrancar, no sale en el contrato —las dos rutas están publicadas— y
sólo se ve pidiendo la que quedó tapada.

Pasó dos veces el 05-11-2026 mientras se añadían fichas: la de usuarios iba a
quedar delante de `/licencias`, y montar la de dispositivos al principio del
módulo habría tapado `/dispositivos/lecturas`, `/reglas` y `/silenciosos`.

Las que llevan conversor —`/{x_id:uuid}`— no cuentan: ésas no encajan con un
nombre, que es justo para lo que sirve el conversor.

Validada plantando el caso malo: con la ficha de usuarios declarada antes de
`/licencias`, falla y la nombra.
"""

from __future__ import annotations

import importlib
import re

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


def _elegida(rutas: list, scope: dict) -> object | None:
    """La ruta que la aplicación elegiría, preguntándoselo a ella.

    Por su propio emparejamiento y no reconstruyendo el orden a mano: desde
    FastAPI 0.139 cada router incluido va envuelto y el orden efectivo lo decide
    él. Recorrer `app.router.routes` contando a mano daba **cero** rutas
    miradas — y verde. `_match` es interno; si cambia, el recuento de abajo lo
    dice en vez de dar verde sin mirar.
    """
    from starlette.routing import Match

    for ruta in rutas:
        if hasattr(ruta, "_match"):
            encaje, _, elegida, _ = ruta._match(scope)
            if encaje == Match.FULL:
                while hasattr(elegida, "_match"):
                    encaje, _, elegida, _ = elegida._match(scope)
                return elegida
        else:
            encaje, _ = ruta.matches(scope)
            if encaje == Match.FULL:
                return ruta
    return None


PARAMETRO = re.compile(r"\{([a-z_]+)(:[a-z]+)?\}")
EJEMPLO = "01a1a4ef-dc53-73e0-9454-c900526f3343"


def test_cada_operacion_publicada_llega_a_su_ruta() -> None:
    """Pedida con un identificador de ejemplo, cada operación del contrato la
    contesta su propia ruta y no otra declarada antes con la misma forma.

    Dos formas de quedar tapada, y las dos pasaron el 05-11-2026: un nombre
    propio detrás de un identificador (`/usuarios/licencias` tras
    `/usuarios/{usuario_id}`), y **dos identificadores con la misma forma**
    (`/almacen/tablas/{tabla}`, que lee por clave, y una ficha nueva en
    `/almacen/tablas/{tabla_analitica_id}` que no habría contestado nunca).
    """
    tapadas: list[str] = []
    miradas = 0
    for servicio in SERVICIOS:
        app = importlib.import_module(f"services.{servicio}.main").app
        for camino, operaciones in app.openapi()["paths"].items():
            ejemplo = PARAMETRO.sub(EJEMPLO, camino)
            for metodo in operaciones:
                if metodo not in {"get", "post", "put", "patch", "delete"}:
                    continue
                miradas += 1
                scope = {
                    "type": "http",
                    "path": ejemplo,
                    "method": metodo.upper(),
                    "root_path": "",
                    "headers": [],
                    "query_string": b"",
                }
                elegida = _elegida(app.router.routes, scope)
                elegido = PARAMETRO.sub(r"{\1}", getattr(elegida, "path", "") or "")
                if not elegido or not camino.endswith(elegido):
                    tapadas.append(
                        f"{servicio}: {metodo.upper()} {camino} lo contesta {elegido or 'nadie'}"
                    )
    assert miradas > 2000, f"sólo se han mirado {miradas} operaciones"
    assert not tapadas, (
        "Operaciones publicadas que no se alcanzan: otra ruta con la misma "
        "forma, declarada antes, se las queda. Declara la tapada antes, dale "
        "otra forma o usa un conversor (`/{x_id:uuid}`):\n  " + "\n  ".join(tapadas)
    )


def test_ninguna_ruta_con_nombre_queda_detras_de_un_identificador() -> None:
    tapadas: list[str] = []
    miradas = 0
    for servicio in SERVICIOS:
        app = importlib.import_module(f"services.{servicio}.main").app
        caminos = app.openapi()["paths"]
        for camino, operaciones in caminos.items():
            ultimo = camino.rsplit("/", 1)[-1]
            base = camino.rsplit("/", 1)[0]
            # Sólo las que tienen al lado una hermana con identificador: las
            # demás no tienen con quién confundirse.
            if "{" in ultimo or not any(
                c.rsplit("/", 1)[0] == base and c.rsplit("/", 1)[-1].startswith("{")
                for c in caminos
            ):
                continue
            for metodo in operaciones:
                if metodo not in {"get", "post", "put", "patch", "delete"}:
                    continue
                miradas += 1
                scope = {
                    "type": "http",
                    "path": camino,
                    "method": metodo.upper(),
                    "root_path": "",
                    "headers": [],
                    "query_string": b"",
                }
                elegida = _elegida(app.router.routes, scope)
                elegido = getattr(elegida, "path", "")
                if not elegido.endswith("/" + ultimo):
                    tapadas.append(f"{servicio}: {metodo.upper()} {camino} lo contesta {elegido}")
    # Que mire de verdad: sin rutas miradas esto daría verde sin comprobar nada.
    assert miradas > 100, f"sólo se han mirado {miradas} rutas con nombre propio"
    assert not tapadas, (
        "Rutas con nombre propio que no se alcanzan: la del identificador, "
        "declarada antes, se las queda y contesta 422. Declara la del "
        "identificador después, o con conversor (`/{x_id:uuid}`):\n  " + "\n  ".join(tapadas)
    )
