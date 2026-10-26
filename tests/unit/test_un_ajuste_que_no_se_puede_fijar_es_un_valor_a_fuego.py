"""Leer un ajuste que nadie puede fijar es tener el número escrito en el código.

Medido el 12-10-2026: **28 claves** se leían con `rt.efectivo("x", db)` y no
figuraban en ningún catálogo. Eso hace dos cosas a la vez, y las dos malas:

  · leerla devuelve `None`, así que siempre gana el número escrito al lado —
    `rt.efectivo("lead_dias_reciclaje", db) or 180` es 180 y nada más;
  · y fijarla se **rechaza**: «el ajuste no se puede fijar por tenant».

Es la peor forma de un valor a fuego, porque el código aparenta lo contrario.
Un consultor que busque «días de reciclaje de un lead» en la consola no lo
encuentra, y quien lea el código cree que sí está.

De las 28, **veinte estaban declaradas** en el `ajustes.py` de su servicio y no
se registraban porque **nadie importaba ese módulo al arrancar**: los únicos que
lo importaban lo hacían dentro de una función. Medido: `party.main` y
`sales.main` arrancaban sin registrar ni una, y `marketing.main` registraba
cinco porque una de sus rutas sí lo importa arriba.

Las otras ocho no estaban en ninguna parte.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
RE_LECTURA = re.compile(r'efectivo\(\s*["\']([a-z_][a-z0-9_]*)["\']')

pytestmark = pytest.mark.db


def _leidas() -> dict[str, str]:
    """Clave → primer sitio donde se lee."""
    salida: dict[str, str] = {}
    for carpeta in ("services", "packages"):
        for fichero in sorted((RAIZ / carpeta).rglob("*.py")):
            if "__pycache__" in str(fichero) or fichero.name == "keys.py":
                continue
            for n, linea in enumerate(
                fichero.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
            ):
                for m in RE_LECTURA.finditer(linea):
                    salida.setdefault(m.group(1), f"{fichero.relative_to(RAIZ)}:{n}")
    return salida


def _catalogo_con_los_servicios_arrancados() -> dict[str, object]:
    """El catálogo tal como queda **al arrancar los servicios**, no al importar
    el núcleo.

    Es la diferencia entera: las claves de un servicio se registran al importar
    su `ajustes.py`, y si nadie lo importa al arrancar, la consola no las ve
    aunque estén escritas.
    """
    import importlib

    from crmcore.runtime.keys import CLAVES

    for servicio in (
        "party",
        "sales",
        "service",
        "marketing",
        "metadata",
        "identity",
        "tenancy",
        "analytics",
        "automation",
        "integration",
        "intelligence",
        "orchestrator",
        "eventing",
    ):
        importlib.import_module(f"services.{servicio}.main")
    return CLAVES


def test_el_recorrido_mira_de_verdad() -> None:
    leidas = _leidas()
    assert len(leidas) >= 60, f"solo se ven {len(leidas)} lecturas de ajuste"
    claves = _catalogo_con_los_servicios_arrancados()
    assert len(claves) >= 100, f"solo se ven {len(claves)} claves declaradas"


def test_todo_ajuste_que_se_lee_se_puede_fijar() -> None:
    """Si no se puede fijar, el número de al lado es el único que manda."""
    claves = _catalogo_con_los_servicios_arrancados()
    huerfanas = sorted(set(_leidas()) - set(claves))
    leidas = _leidas()
    assert not huerfanas, (
        "Ajustes que el código lee y que NADIE puede fijar —leerlos devuelve "
        "`None` y fijarlos se rechaza—, así que el valor escrito al lado es el "
        "único que manda:\n  " + "\n  ".join(f"{k}  ({leidas[k]})" for k in huerfanas)
    )


def test_los_servicios_registran_sus_ajustes_al_arrancar() -> None:
    """**Es la mitad que se escapaba.** Declararlos no basta: si el módulo que
    los registra no se importa al arrancar, la consola no los ve.

    Se comprueba por servicio y no en conjunto: con el catálogo entero cargado,
    uno que no registre los suyos queda tapado por los demás.
    """
    import importlib

    from crmcore.runtime.keys import CLAVES

    for servicio in ("party", "sales", "marketing"):
        propios = set(
            re.findall(
                r'clave="([a-z_][a-z0-9_]*)"',
                (RAIZ / "services" / servicio / "ajustes.py").read_text(encoding="utf-8"),
            )
        )
        assert propios, f"«{servicio}» declara ajustes y no se le ven"
        importlib.import_module(f"services.{servicio}.main")
        faltan = sorted(propios - set(CLAVES))
        assert not faltan, (
            f"Al arrancar «{servicio}» no quedan registrados ajustes que SÍ "
            f"declara en su `ajustes.py`. Falta importarlo en su `main.py`:\n  "
            + "\n  ".join(faltan)
        )


def test_el_umbral_que_fusiona_solo_se_puede_cambiar() -> None:
    """Era el caso más claro de los 28: se podía afinar cuándo se PROPONE una
    fusión de identidades —`identidad_umbral` se leía de los ajustes— y no
    cuándo se EJECUTA sola, que es la destructiva."""
    claves = _catalogo_con_los_servicios_arrancados()
    assert "identidad_umbral_automatico" in claves
    # Se mira LA ASIGNACIÓN QUE DECIDE, por el árbol y no por texto. El nombre
    # aparece en dos sitios, así que buscarlo suelto deja pasar que la
    # comparación vuelva a la constante mientras el otro uso lo mantiene
    # —medido: con el texto suelto, la mutación no caía—. Y por AST y no por
    # línea, porque una asignación puede ocupar varias: una prueba que depende
    # de dónde parte el formateador se rompe sin que nada esté mal.
    import ast

    arbol = ast.parse((RAIZ / "services/party/identidad.py").read_text(encoding="utf-8"))
    decisiones = [
        n
        for n in ast.walk(arbol)
        if isinstance(n, ast.Assign)
        and any(getattr(d, "id", "") == "automatico" for d in n.targets)
    ]
    assert decisiones, "ha desaparecido la asignación que decide el umbral automático"
    for decision in decisiones:
        llamadas = {
            getattr(c.func, "attr", "") or getattr(c.func, "id", "")
            for c in ast.walk(decision)
            if isinstance(c, ast.Call)
        }
        assert "efectivo" in llamadas, (
            "la unión automática ha vuelto a decidir con una constante: " f"{ast.unparse(decision)}"
        )
