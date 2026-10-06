"""El nivel completo tiene que poder salir en verde (`QUALITY_GATES`).

Medido el 06-10-2026. El preflight tenía **un solo presupuesto de CPU** —300 s—
para sus tres niveles, y los tres gastan cosas muy distintas: 22 s el rápido,
139 s el del push y 354 s el completo. O sea que el nivel completo estaba por
encima de su propio tope y **no podía salir en verde nunca**.

Lo que eso costaba no es el rojo, que se ve: es que `_apuntar_pase_completo`
solo se ejecuta detrás del verde, así que el apunte de «aquí pasó la batería
entera» no se escribía ni pasando los veinte gates. El aviso de «van N commits
sin un pase completo» no bajaba de N por mucho que se corriera, y un aviso que
no baja nunca se aprende a ignorar — que es como se pierde el apunte entero.

Y el otro lado del mismo número: con 300 s de tope, el nivel rápido —el que más
se corre— tenía casi catorce veces su coste de margen. El guardián del
crecimiento estaba dormido justo donde más se nota.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from typing import Any

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[2]


def _preflight() -> Any:
    spec = importlib.util.spec_from_file_location("preflight_", RAIZ / "scripts" / "preflight.py")
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    # Registrado ANTES de ejecutarlo: `@dataclass` resuelve sus anotaciones
    # mirando `sys.modules[cls.__module__]`, y sin esto revienta al importar.
    sys.modules[spec.name] = modulo
    try:
        spec.loader.exec_module(modulo)
    finally:
        sys.modules.pop(spec.name, None)
    return modulo


# Lo medido el 06-10-2026 con la máquina libre, en segundos de CPU. Si alguien
# añade trabajo esto sube y el preflight lo dice; aquí sirve para lo contrario:
# comprobar que el tope de cada nivel está POR ENCIMA de lo que ese nivel cuesta.
COSTE_MEDIDO_CPU = {"rapido": 22.0, "push": 139.0, "completo": 354.0}


@pytest.mark.parametrize(
    ("banderas", "nivel"),
    [
        (set(), "rapido"),
        ({"tests"}, "push"),
        ({"tests", "todo", "suite"}, "completo"),
    ],
)
def test_cada_nivel_elige_su_presupuesto(banderas: set[str], nivel: str) -> None:
    pf = _preflight()
    elegido, _reloj, _cpu = pf._presupuesto({"fast", *banderas})
    assert elegido == nivel


def test_ningun_nivel_esta_por_encima_de_su_propio_tope() -> None:
    """Es el fallo entero: un nivel que cuesta más que su tope sale en rojo
    haciendo todo bien, y detrás del verde está lo que apunta el pase."""
    pf = _preflight()
    for nivel, coste in COSTE_MEDIDO_CPU.items():
        _reloj, tope = pf.PRESUPUESTOS[nivel]
        assert coste < tope, (
            f"el nivel «{nivel}» cuesta {coste:.0f}s de CPU medidos y su tope "
            f"son {tope:.0f}s: no puede salir en verde ni haciéndolo todo bien"
        )


def test_el_margen_no_es_tan_ancho_que_no_vigile_nada() -> None:
    """Un tope diez veces el coste no es un presupuesto, es un adorno. Era
    exactamente lo que le pasaba al nivel rápido: 22 s contra 300."""
    pf = _preflight()
    for nivel, coste in COSTE_MEDIDO_CPU.items():
        _reloj, tope = pf.PRESUPUESTOS[nivel]
        assert tope <= coste * 2, (
            f"el nivel «{nivel}» tiene {tope:.0f}s de tope para {coste:.0f}s de "
            "coste: con ese margen puede duplicarse el trabajo sin que salte"
        )


def test_el_apunte_del_pase_va_detras_del_verde_y_no_antes() -> None:
    """Si se apuntara antes de comprobar, el apunte diría que pasó la batería
    entera justo en el commit donde algo se rompió."""
    fuente = (RAIZ / "scripts" / "preflight.py").read_text(encoding="utf-8")
    cuerpo = fuente.split("def main(")[1]
    assert cuerpo.index("if fallos:") < cuerpo.index("_decir_que_falta_por_correr(")
