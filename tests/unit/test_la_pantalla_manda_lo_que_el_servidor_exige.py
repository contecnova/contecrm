"""Una pantalla no llama a una ruta sin lo que esa ruta exige.

El fallo que esto caza ya pasó, el mismo día en que se escribió el gate. El
panel de particiones de «Plataforma» llamaba a
`GET /api/v1/{servicio}/volumen/particiones-a-crear` sin parámetros, y esa ruta
**exige** `ultima_existente` —cuál es la última partición que ya hay, que es un
dato que sólo sabe quien administra la base—. La respuesta era un 422 y el
panel salía en error **siempre, para los catorce servicios**. No lo cazó nada:
el tipo de la respuesta es correcto, la ruta existe, el permiso es el bueno y
el front compila. Sólo se ve pidiéndola.

Es la otra mitad de `test_la_pantalla_no_lee_campos_que_nadie_envia`: aquella
comprueba que alguien recorre la ruta; ésta, que la pantalla la llama como el
servidor la admite.

**Lo que NO comprueba**: que los valores sean los correctos. Sólo que el
parámetro obligatorio viaja. Fijar los valores es cosa de las pruebas de cada
pantalla.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
FRONT = RAIZ / "frontend" / "src"

from tests.unit._contratos import SERVICIOS  # noqa: E402

# `llamar<Tipo>("/api/v1/…")` y `fetch(`${…}/api/v1/…`)`: lo que de verdad pide
# una ruta. Se queda con la ruta y con lo que venga detrás, que es donde van los
# parámetros.
RE_PETICION = re.compile(r"""["'`](/api/v1/[^"'`]*)["'`]""")


@functools.cache
def _parametros_obligatorios() -> dict[str, tuple[str, ...]]:
    """Ruta `GET` → parámetros de consulta que el servidor exige.

    Por el ayudante compartido: construir los catorce contratos cuesta diez
    segundos largos y hay varios gates que los necesitan. Dentro de una misma
    ejecución de pytest se construyen una vez y los comparten todos, que es lo
    que mantiene el nivel «push» dentro de su presupuesto.
    """
    from tests.unit._contratos import caminos

    salida: dict[str, tuple[str, ...]] = {}
    for servicio in SERVICIOS:
        try:
            rutas = caminos(servicio)
        except Exception:  # noqa: BLE001
            # Un servicio que no monta aquí no se da por bueno ni por malo: el
            # recuento de abajo es quien impide que esto pase en verde por no
            # haber mirado nada.
            continue
        for camino, ops in rutas.items():
            get = ops.get("get")
            if not get:
                continue
            exigidos = tuple(
                p["name"]
                for p in get.get("parameters", [])
                if p.get("in") == "query" and p.get("required")
            )
            if exigidos:
                salida[camino] = exigidos
    return salida


@functools.cache
def _con_periodo() -> frozenset[str]:
    """Colecciones declaradas `periodo: true`.

    Esas no escriben `desde` y `hasta` en la ruta: los pone la pantalla de
    módulo en cada petición, y se niega a pedir nada mientras no haya rango
    —porque un informe que se abre con «los últimos treinta días» da un número
    de un periodo que no eligió nadie—. La primera versión de este gate no lo
    sabía y señalaba dos pestañas que funcionan: mirarlo antes de creérselo es
    lo que separa un gate de un ruido.
    """
    texto = (FRONT / "lib" / "recursos.ts").read_text(encoding="utf-8")
    salida: set[str] = set()
    for bloque in re.finditer(r"\{[^{}]*?listar:\s*\"([^\"]+)\"[^{}]*?\}", texto, re.S):
        if re.search(r"periodo:\s*true", bloque.group(0)):
            salida.add(bloque.group(1))
    return frozenset(salida)


@functools.cache
def _peticiones_del_front() -> tuple[tuple[str, str], ...]:
    """(fichero, lo que se pide) por cada ruta literal del front."""
    salida: list[tuple[str, str]] = []
    for fichero in sorted(FRONT.rglob("*.ts*")):
        if "/pruebas/" in fichero.as_posix():
            continue
        for ruta in RE_PETICION.findall(fichero.read_text(encoding="utf-8")):
            salida.append((fichero.name, ruta))
    return tuple(salida)


def _forma(ruta: str) -> str:
    """La ruta como la nombra el OpenAPI: sin valores y sin consulta."""
    sin_consulta = ruta.split("?")[0]
    # `${id}` y `${servicio}` son valores puestos en marcha. El segundo ocupa el
    # sitio del nombre del servicio, que en el OpenAPI va literal: se prueban
    # todos abajo, aquí sólo se normaliza lo demás.
    return re.sub(r"\$\{[^}]*\}", "{}", sin_consulta).rstrip("/")


def _candidatas(ruta: str) -> list[str]:
    """Las formas del OpenAPI con las que esta petición podría casar."""
    forma = _forma(ruta)
    partes = forma.split("/")
    salida = [forma]
    # `/api/v1/{}/volumen/…` puede ser cualquiera de los catorce servicios.
    if len(partes) > 3 and partes[3] == "{}":
        salida += ["/".join(partes[:3] + [s] + partes[4:]) for s in SERVICIOS]
    return salida


def _sin_lo_que_exige() -> list[str]:
    obligatorios = _parametros_obligatorios()
    rotos: list[str] = []
    for fichero, ruta in _peticiones_del_front():
        consulta = ruta.split("?")[1] if "?" in ruta else ""
        for forma in _candidatas(ruta):
            exigidos = obligatorios.get(forma)
            if not exigidos:
                continue
            faltan = [p for p in exigidos if p not in consulta]
            # `desde` y `hasta` los pone la pantalla de módulo en los recursos
            # declarados con periodo: no viajan escritos en la ruta.
            if ruta.split("?")[0] in _con_periodo():
                faltan = [p for p in faltan if p not in ("desde", "hasta")]
            if faltan:
                rotos.append(f"{fichero}: «{ruta}» no manda {', '.join(faltan)}")
            break
    return sorted(set(rotos))


def test_el_recorrido_mira_de_verdad() -> None:
    """Si el OpenAPI no se pudiera leer, o el patrón dejara de casar, esto
    saldría en verde sin haber mirado una sola ruta. Ya pasó con otro gate de
    esta misma familia, y por eso está escrito aquí también."""
    obligatorios = _parametros_obligatorios()
    assert len(obligatorios) >= 20, f"sólo se ven {len(obligatorios)} rutas con parámetro exigido"
    peticiones = _peticiones_del_front()
    assert len(peticiones) >= 200, f"sólo se ven {len(peticiones)} peticiones en el front"
    # Y que al menos una petición del front case con una ruta del contrato: si
    # ninguna casara, no habría nada que comprobar y saldría verde igual.
    formas = {f for r in peticiones for f in _candidatas(r[1])}
    assert formas & set(obligatorios) or any(
        f.split("?")[0] in obligatorios for _n, f in peticiones
    ), "ninguna petición del front casa con una ruta del contrato"


def test_ninguna_pantalla_llama_sin_lo_que_la_ruta_exige() -> None:
    """Sin tope: o se manda el parámetro, o la llamada responde 422 siempre."""
    rotos = _sin_lo_que_exige()
    assert not rotos, (
        "Pantallas que llaman a una ruta sin un parámetro que el servidor "
        "exige. La respuesta es un 422 y el panel sale en error siempre, para "
        "todos los casos:\n  " + "\n  ".join(rotos)
    )
