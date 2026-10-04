"""«Hoy» es el día donde está el cliente, no donde está el servidor.

Había **64 sitios** calculando el día con `date.today()` o
`datetime.now(timezone.utc).date()`. Los dos ignoran la zona horaria del
tenant: el primero usa la del servidor y el segundo UTC. Para un cliente en
Madrid, entre las 00:00 y las 02:00 de verano —y entre las 00:00 y la 01:00 en
invierno— el sistema contesta **el día de ayer**.

Lo que eso rompe no es cosmético: una oportunidad que vence hoy sale como
vencida ayer, un presupuesto válido hasta hoy sale caducado, y una comisión del
día 1 cae en el mes anterior.

De los 64, **45 tenían una sesión a mano** con la que resolver la zona y se han
pasado a `crmcore.fechas.hoy(db)`. Los otros 19 son funciones puras sin sesión:
siguen cayendo a UTC, que es exactamente lo que hacían antes —no empeoran— y
están contados aquí abajo para que el número no se pierda.

Esta prueba comprueba lo que de verdad importa: que con una zona distinta de
UTC el día **cambie**. Una sustitución mecánica que dejara `hoy()` sin sesión
pasaría todas las pruebas de siempre y no habría arreglado nada.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[2]

# Los dos que ignoran la zona del tenant.
PATRONES = ("datetime.now(timezone.utc).date()", "date.today()")

# Cuántos pueden quedar sin sesión. Medido el 04-10-2026: 19. El suelo impide
# que el número crezca sin que nadie lo decida, y no se baja a cero porque
# bajarlo exige llevar la sesión hasta funciones que hoy no la tienen, y eso es
# un cambio de firma en cadena que se decide, no se cuela.
MAXIMO_SIN_SESION = 19


def _calculos_de_hoy() -> tuple[int, list[str]]:
    """Cada sitio donde se calcula el día, y si tenía sesión a mano."""
    sin_sesion: list[str] = []
    total = 0
    for fichero in [*(RAIZ / "services").rglob("*.py"), *(RAIZ / "packages").rglob("*.py")]:
        if "__pycache__" in str(fichero) or fichero.name == "fechas.py":
            continue
        texto = fichero.read_text(encoding="utf-8")
        if not any(p in texto for p in PATRONES):
            continue
        try:
            arbol = ast.parse(texto, str(fichero))
        except SyntaxError:  # pragma: no cover
            continue
        lineas = texto.splitlines()
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            cuerpo = "\n".join(lineas[nodo.lineno - 1 : nodo.end_lineno or nodo.lineno])
            cuantos = sum(cuerpo.count(p) for p in PATRONES)
            if not cuantos:
                continue
            total += cuantos
            args = {a.arg for a in nodo.args.args} | {a.arg for a in nodo.args.kwonlyargs}
            if not ({"db", "uow", "session"} & args):
                sin_sesion.append(f"{fichero.relative_to(RAIZ)}::{nodo.name}  x{cuantos}")
    return total, sin_sesion


def test_ningun_calculo_de_hoy_con_sesion_a_mano_la_ignora() -> None:
    """Si hay sesión, se usa. Lo contrario es ignorar la zona del cliente
    teniendo delante el dato con el que resolverla."""
    total, sin_sesion = _calculos_de_hoy()

    assert total > 0, (
        "no se ha encontrado ni un cálculo de «hoy»: el recorrido se ha quedado "
        "corto y su resultado no significa nada"
    )
    con_sesion = total - len(sin_sesion)
    assert con_sesion == 0, (
        f"{con_sesion} sitios calculan el día ignorando la zona del tenant "
        "**teniendo la sesión a mano**. Usa `crmcore.fechas.hoy(db)`: para un "
        "cliente en Madrid, de madrugada el sistema contesta el día de ayer."
    )


def test_los_que_no_tienen_sesion_estan_contados() -> None:
    """Los 19 restantes no empeoran nada —siguen en UTC, como antes— pero el
    número no puede crecer sin que alguien lo decida."""
    _, sin_sesion = _calculos_de_hoy()
    assert len(sin_sesion) <= MAXIMO_SIN_SESION, (
        f"han subido a {len(sin_sesion)} los cálculos de «hoy» sin sesión con la "
        f"que resolver la zona, y el tope medido eran {MAXIMO_SIN_SESION}. "
        "Cada uno de más es un sitio que contesta el día de ayer de "
        "madrugada:\n  " + "\n  ".join(sorted(sin_sesion))
    )


@pytest.mark.db
def test_con_la_zona_del_cliente_el_dia_cambia(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    """La comprobación que hace que todo lo anterior signifique algo.

    Una sustitución mecánica que dejara `hoy()` sin sesión pasaría todas las
    pruebas de siempre y no habría arreglado nada. Aquí se fija una zona donde
    la fecha es distinta de la de UTC y se exige que `hoy(db)` la siga.
    """
    from crmcore.fechas import hoy, zona_del_tenant
    from crmcore.runtime import settings as rt

    # SE FIJA DONDE SE FIJA DE VERDAD: en los ajustes del tenant, no en una
    # variable de entorno. La primera versión de esto hacía `setenv` y la zona
    # seguía saliendo UTC — la prueba decía «no funciona» sobre código que
    # funcionaba, porque estaba poniéndolo en el sitio equivocado.
    #
    # Kiritimati va 14 horas por delante de UTC: allí es mañana durante catorce
    # horas de cada día de UTC. Se elige por eso y no por exotismo: con una zona
    # de ±1 h la prueba solo diría algo una hora al día.
    rt.fijar(db, "zona_horaria", "Pacific/Kiritimati", ambito="tenant", ambito_id=str(tenant_id))

    assert str(zona_del_tenant(db)) == "Pacific/Kiritimati"
    en_utc = datetime.now(timezone.utc).date()
    del_cliente = hoy(db)

    # No se exige que sean distintos SIEMPRE —a las 03:00 UTC coinciden— sino
    # que el cálculo use la zona: se comprueba contra el día que de verdad es
    # allí, no contra una constante.
    esperado = datetime.now(zona_del_tenant(db)).date()
    assert del_cliente == esperado, (
        f"«hoy» ha dado {del_cliente} y en la zona del cliente es {esperado}: "
        "el cálculo no está usando la zona"
    )
    assert (del_cliente - en_utc).days in (
        0,
        1,
    ), f"diferencia inesperada entre {del_cliente} y {en_utc}"
