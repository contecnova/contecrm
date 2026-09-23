"""La clave de deduplicación siempre cabe en su columna.

No es una comprobación de estilo. Cuando no cabe, Postgres rechaza la fila con
`StringDataRightTruncation` y se lleva por delante **la transacción del cambio
que emitió el evento**: dar de alta un usuario fallaba porque su evento
`user.org.changed` componía `org:{tenant}:{usuario}` —77 caracteres— y la
columna admite 64. El alta no tenía nada malo; lo que fallaba era el apunte del
evento.

Pasaba en una docena de sitios que componen su clave a mano, así que la defensa
está en el sobre —donde se construye el evento— y no en cada uno de ellos. Aquí
se comprueba eso: que el sobre acota, que acota de forma estable y que dos
claves distintas siguen siendo distintas después de acotarlas.
"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from crmcore.events.envelope import TOPE_DEDUP, crear_evento

RAIZ = Path(__file__).resolve().parents[2]


def _evento(clave: str) -> str:
    return crear_evento(
        "prueba.hecho",
        tenant_id=uuid4(),
        subject=("cosa", uuid4()),
        dedup_key=clave,
    ).dedup_key


def test_una_clave_larga_se_acota_al_ancho_de_la_columna() -> None:
    clave = f"org:{uuid4()}:{uuid4()}"
    assert len(clave) > TOPE_DEDUP, "la clave del caso real ya no es larga; revisa el ejemplo"
    assert len(_evento(clave)) == TOPE_DEDUP


def test_una_clave_corta_no_se_toca() -> None:
    # Acotar lo que ya cabe cambiaría claves existentes, y una clave que cambia
    # es un hecho que se procesa dos veces.
    clave = "preaviso:0195f0e3-3a3a-7f2e-9a9a-2c0b1f3a5d77"
    assert _evento(clave) == clave


def test_acotar_es_estable_y_no_junta_claves_distintas() -> None:
    base = f"case.assigned:{uuid4()}"
    a, b = f"{base}:{uuid4()}", f"{base}:{uuid4()}"
    # Estable: el mismo hecho tiene que dar la misma clave en dos procesos
    # distintos, o la deduplicación no deduplica nada.
    assert _evento(a) == _evento(a)
    # Y distinta: si dos asignaciones distintas compartieran clave, la segunda
    # se descartaría como repetida y esa asignación se perdería.
    assert _evento(a) != _evento(b)


def test_el_principio_de_la_clave_sigue_siendo_legible() -> None:
    # Quien mira la tabla de salida buscando por qué algo no llegó tiene que
    # poder saber de qué es la fila. Un resumen puro no dice nada.
    acotada = _evento(f"lead.assigned:{uuid4()}:{uuid4()}")
    assert acotada.startswith("lead.assigned:")


def test_la_columna_y_el_tope_no_pueden_separarse() -> None:
    """Las tablas declaran su ancho con la constante, no con un número.

    Si alguien ampliara la columna a mano y dejara el tope en 64, se seguiría
    acotando sin motivo; si redujera la columna, volvería el error original.
    """
    modelos = (RAIZ / "packages/crmcore/crmcore/bus/modelos.py").read_text("utf-8")
    anchos = re.findall(r"dedup_key: Mapped\[str\] = mapped_column\(String\(([^)]+)\)", modelos)
    assert anchos, "no se ha encontrado ninguna columna `dedup_key`"
    assert set(anchos) == {"TOPE_DEDUP"}, f"columnas con ancho a mano: {sorted(set(anchos))}"
