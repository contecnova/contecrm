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

# Cuántos pueden quedar sin sesión.
#
#   04-10-2026  19  medición inicial
#   05-10-2026  15  los `_hoy()` locales aceptan sesión y la reciben de los
#                   trece sitios que la tenían a mano, y el trimestre «en curso»
#                   de ingresos y de territorios se resuelve en la zona del
#                   cliente — el 1 de enero a la una de la mañana en Madrid, en
#                   UTC todavía es diciembre y el informe que se abre solo salía
#                   con el trimestre anterior.
#
# Los quince que quedan son funciones **puras** con parámetro `hoy`: no calculan
# la fecha, la reciben, y quien las llama con sesión ya se la pasa. Bajar de ahí
# no es arreglar nada: es quitarles la pureza.
MAXIMO_SIN_SESION = 15


# Ayudantes locales que resuelven «hoy». Llamarlos **sin sesión** teniéndola a
# mano es la misma falta que escribir el patrón crudo, y durante un rato fue
# peor: al pasar los `_hoy()` locales a `crmcore.fechas.hoy(db)`, el patrón
# crudo desapareció de trece ficheros y este gate se habría quedado contento
# aunque ningún llamante pasara la sesión. O sea, la medida habría bajado sin
# que la zona del cliente se resolviera en ningún sitio.
AYUDANTES = ("_hoy", "_ahora_fecha")


def _calculos_de_hoy() -> tuple[int, list[str]]:
    """Cada sitio donde se calcula el día, y si tenía sesión a mano.

    Se cuentan dos cosas, y las dos hacen falta:

      * el patrón crudo (`date.today()`, `datetime.now(timezone.utc).date()`), y
      * la llamada a un ayudante local de fecha **sin pasarle la sesión**.

    Lo segundo se añadió el 05-10-2026 y es lo que impide que el arreglo sea
    cosmético: mover el UTC un nivel más abajo, a un `_hoy()` que nadie alimenta,
    deja el mismo día de ayer con otro aspecto.
    """
    sin_sesion: list[str] = []
    total = 0
    for fichero in [*(RAIZ / "services").rglob("*.py"), *(RAIZ / "packages").rglob("*.py")]:
        if "__pycache__" in str(fichero) or fichero.name == "fechas.py":
            continue
        texto = fichero.read_text(encoding="utf-8")
        try:
            arbol = ast.parse(texto, str(fichero))
        except SyntaxError:  # pragma: no cover
            continue
        # Sólo los ayudantes DEFINIDOS en este fichero: un `_hoy` de otro módulo
        # no se sabe si acepta sesión, y contarlo sería inventarse un hallazgo.
        locales = {
            n.name
            for n in ast.walk(arbol)
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name in AYUDANTES
        }
        lineas = texto.splitlines()
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if nodo.name in AYUDANTES:
                # El ayudante mismo no cuenta: su trabajo ES resolver la fecha, y
                # lo hace con la sesión que le den.
                continue
            cuerpo = "\n".join(lineas[nodo.lineno - 1 : nodo.end_lineno or nodo.lineno])
            cuantos = sum(cuerpo.count(p) for p in PATRONES)
            cuantos += sum(
                1
                for sub in ast.walk(nodo)
                if isinstance(sub, ast.Call)
                and getattr(sub.func, "id", "") in locales
                and not sub.args
                and not sub.keywords
            )
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
