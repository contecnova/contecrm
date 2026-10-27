"""Una tabla que el modelo declara y la migración no crea (CRM-00.03.01.06).

Cada servicio migra su propio esquema. El modelo vive en un sitio —a veces en
`crmcore`, compartido por los trece— y la migración en otro: la carpeta de ese
servicio. Cuando las dos mitades se separan, el síntoma no es un fallo de
arranque, es un 500 en una pantalla cualquiera:

    relation "esquemas_tenant" does not exist

Y casi nunca en la pantalla que uno esperaría. El 27-10-2026 faltaba
`esquemas_tenant` en **siete de los trece esquemas**; la consulta reventaba
dentro de la proyección de campos, dejaba la transacción envenenada, y lo que
llegaba al navegador era el error de la consulta SIGUIENTE —la de ABAC— sobre
`GET /ia/agentes-autonomos`, que no tiene nada que ver con el metamodelo.

**Por qué no lo caza ninguna prueba de las de siempre.** Las pruebas con base
no migran: montan el esquema con `Base.metadata.create_all`, que crea todas las
tablas del modelo. O sea que en las pruebas la tabla existe SIEMPRE, y la
deriva entre modelo y migración es justo lo que esa comodidad hace invisible.
Es la misma trampa de [piezas entre dos suites]: la prueba se fabrica un mundo
donde el fallo no cabe.

Y es la **quinta vez** que pasa lo mismo: `politicas_campo`, `politicas_abac`,
`papelera`, `documentos_enlazados` y ahora `esquemas_tenant`. Las cuatro
primeras se arreglaron de una en una, cada una con su comentario en
`alembic/env.py`. Este gate mira las trece a la vez.

**Cómo lo mide, y por qué estáticamente.** No importa nada y no toca la base:
reconstruye, leyendo el árbol, (a) qué tablas declara el modelo de cada
servicio —el cierre de importaciones desde `alembic/env.py`, que es
exactamente lo que alembic tiene delante al generar— y (b) qué tablas crean sus
migraciones. Medido contra la base el 27-10-2026: las dos reconstrucciones dan
**las 544 tablas exactas de los trece esquemas**, sin sobrar ni faltar ninguna.

**Lo que NO comprueba**: las columnas. Un `add_column` que falta sigue siendo un
500, y eso lo caza `alembic revision --autogenerate` saliendo vacío. Aquí sólo
las tablas, que es el caso que se ha repetido cinco veces.
"""

from __future__ import annotations

import ast
import functools
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
VERSIONES = RAIZ / "alembic" / "versions"


def _servicios() -> list[str]:
    """Del árbol, no de una lista escrita a mano.

    Mismo criterio que `scripts/aplicar_rls.py`, y por el mismo motivo: una
    lista a mano se queda corta y el gate da el visto bueno habiendo mirado
    nueve esquemas de trece.
    """
    return sorted(d.name for d in VERSIONES.iterdir() if d.is_dir() and not d.name.startswith("_"))


SERVICIOS = _servicios()


# ── Lo que el modelo declara ──────────────────────────────────────────────


def _fichero_de(modulo: str) -> Path | None:
    for base in (RAIZ, RAIZ / "packages" / "crmcore"):
        p = base / Path(*modulo.split("."))
        if (p / "__init__.py").exists():
            return p / "__init__.py"
        if p.with_suffix(".py").exists():
            return p.with_suffix(".py")
    return None


@functools.cache
def _modulo(modulo: str) -> tuple[frozenset[str], frozenset[str]]:
    """(tablas que declara, módulos que importa al cargarse)."""
    fichero = _fichero_de(modulo)
    if fichero is None:
        return frozenset(), frozenset()
    arbol = ast.parse(fichero.read_text(encoding="utf-8"))
    tablas = {
        nodo.value.value
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Assign)
        and isinstance(nodo.value, ast.Constant)
        and any(getattr(t, "id", "") == "__tablename__" for t in nodo.targets)
    }
    # Sólo las importaciones del cuerpo del módulo: una dentro de una función
    # no se ejecuta al importarlo, así que su modelo no queda registrado y
    # alembic no lo ve. Contarla aquí daría por declarada una tabla que no lo
    # está —y este gate saldría verde con el agujero puesto—.
    hijos: set[str] = set()
    for nodo in arbol.body:
        if isinstance(nodo, ast.Import):
            hijos |= {a.name for a in nodo.names}
        elif isinstance(nodo, ast.ImportFrom) and nodo.module and nodo.level == 0:
            # Las dos formas: `from crmcore.x import Y` puede traer el módulo
            # `crmcore.x.Y` o la clase `Y` de `crmcore.x`. Se prueban las dos y
            # la que no exista como fichero no aporta nada.
            hijos.add(nodo.module)
            hijos |= {f"{nodo.module}.{a.name}" for a in nodo.names}
    return frozenset(tablas), frozenset(
        h for h in hijos if h.split(".")[0] in ("crmcore", "services")
    )


@functools.cache
def _comunes() -> tuple[str, ...]:
    """Los módulos que `alembic/env.py` importa para TODOS los servicios.

    Se lee de allí y no se copia: una copia es otra lista que mantener, y el
    día que diverjan el gate mediría un mundo que no existe.
    """
    arbol = ast.parse((RAIZ / "alembic" / "env.py").read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Assign) and any(
            getattr(t, "id", "") == "comunes" for t in nodo.targets
        ):
            lista = nodo.value
            if isinstance(lista, ast.List):
                return tuple(e.value for e in lista.elts if isinstance(e, ast.Constant))
    raise AssertionError("no se encuentra la lista `comunes` en alembic/env.py")


@functools.cache
def declaradas(servicio: str) -> frozenset[str]:
    """Las tablas que alembic ve al generar la migración de este servicio."""
    pendientes = [*_comunes(), f"services.{servicio}.modelos"]
    vistos: set[str] = set()
    tablas: set[str] = set()
    while pendientes:
        modulo = pendientes.pop()
        if modulo in vistos:
            continue
        vistos.add(modulo)
        propias, hijos = _modulo(modulo)
        tablas |= propias
        pendientes.extend(hijos - vistos)
    return frozenset(tablas)


# ── Lo que las migraciones crean ──────────────────────────────────────────


@functools.cache
def _migraciones(servicio: str) -> tuple[frozenset[str], tuple[str, ...]]:
    """(tablas vivas tras aplicar todas, ficheros con DDL en texto plano)."""
    creadas: set[str] = set()
    borradas: set[str] = set()
    renombres: list[tuple[str, str | None]] = []
    en_texto: list[str] = []
    for fichero in sorted((VERSIONES / servicio).glob("*.py")):
        arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        for nodo in arbol.body:
            if not (isinstance(nodo, ast.FunctionDef) and nodo.name == "upgrade"):
                continue
            for llamada in ast.walk(nodo):
                if not (isinstance(llamada, ast.Call) and isinstance(llamada.func, ast.Attribute)):
                    continue
                nombre = llamada.func.attr
                primero = llamada.args[0] if llamada.args else None
                if nombre == "execute":
                    texto = ast.unparse(llamada).upper()
                    if "CREATE TABLE" in texto or "DROP TABLE" in texto:
                        en_texto.append(fichero.name)
                if not isinstance(primero, ast.Constant):
                    continue
                if nombre == "create_table":
                    creadas.add(primero.value)
                elif nombre == "drop_table":
                    borradas.add(primero.value)
                elif nombre == "rename_table":
                    destino = llamada.args[1] if len(llamada.args) > 1 else None
                    renombres.append(
                        (
                            primero.value,
                            destino.value if isinstance(destino, ast.Constant) else None,
                        )
                    )
    for viejo, nuevo in renombres:
        creadas.discard(viejo)
        if nuevo:
            creadas.add(nuevo)
    return frozenset(creadas - borradas), tuple(sorted(set(en_texto)))


def _sin_migracion() -> dict[str, list[str]]:
    return {
        s: sorted(declaradas(s) - _migraciones(s)[0])
        for s in SERVICIOS
        if declaradas(s) - _migraciones(s)[0]
    }


# ── Las pruebas ───────────────────────────────────────────────────────────


def test_el_recorrido_mira_de_verdad() -> None:
    """Si el cierre de importaciones dejara de encontrar modelos, o el lector
    de migraciones dejara de encontrar `create_table`, esto saldría en verde sin
    haber comparado nada. Ya ha pasado con otros gates de esta casa."""
    assert len(SERVICIOS) >= 13, SERVICIOS
    total_modelo = sum(len(declaradas(s)) for s in SERVICIOS)
    total_migrado = sum(len(_migraciones(s)[0]) for s in SERVICIOS)
    assert total_modelo >= 500, f"sólo se ven {total_modelo} tablas en los modelos"
    assert total_migrado >= 500, f"sólo se ven {total_migrado} tablas en las migraciones"
    # Y que `comunes` se esté leyendo de verdad: si la lista volviera vacía, las
    # tablas compartidas desaparecerían de los dos lados a la vez y la
    # comparación seguiría cuadrando.
    assert "crmcore.metamodelo" in _comunes(), _comunes()


def test_el_gate_caza_la_tabla_que_falta() -> None:
    """La validación por mutación: se planta el caso malo y se exige que lo vea.

    Sin esto, un gate que compara dos conjuntos vacíos pasa siempre.
    """
    servicio = "intelligence"
    migradas = set(_migraciones(servicio)[0])
    migradas.discard("esquemas_tenant")
    faltan = declaradas(servicio) - migradas
    assert faltan == {"esquemas_tenant"}, faltan


def test_ninguna_migracion_crea_tablas_en_texto_plano() -> None:
    """Un `op.execute("CREATE TABLE …")` haría mentir a la reconstrucción de
    arriba: la tabla existiría y este gate la daría por no creada. Si algún día
    hace falta, se añade aquí su lectura en vez de dejarlo pasar."""
    sueltas = {s: _migraciones(s)[1] for s in SERVICIOS if _migraciones(s)[1]}
    assert not sueltas, (
        "Migraciones que crean o borran tablas con SQL en texto plano. La "
        "reconstrucción de este gate no las ve, así que lo que comprueba deja "
        "de ser cierto:\n  " + "\n  ".join(f"{s}: {', '.join(f_)}" for s, f_ in sueltas.items())
    )


def test_toda_tabla_del_modelo_tiene_su_migracion() -> None:
    """Sin tope y sin lista de excepciones: una tabla declarada y no migrada es
    un 500 en cuanto alguien abra la pantalla que la usa."""
    rotos = _sin_migracion()
    assert not rotos, (
        "Tablas que el modelo declara y la migración del servicio no crea. En "
        "ese esquema la consulta revienta con «relation … does not exist», y el "
        "error que se ve suele ser el de la consulta siguiente:\n  "
        + "\n  ".join(f"{s}: {', '.join(t)}" for s, t in rotos.items())
    )
