"""Campos calculados (CRM-00.04.01.04).

Una fórmula la escribe **quien configura el CRM**, no quien lo programa. Es
entrada del tenant, y eso decide lo único que de verdad importa aquí: que no
haya forma de llegar al intérprete desde una fórmula. Lo demás —qué funciones
hay, cómo se redondea— es comodidad; esto es la diferencia entre un campo
calculado y una ejecución remota de código.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from crmcore.datos import formulas

# ── Lo que no se puede escribir ───────────────────────────────────────────


@pytest.mark.parametrize(
    "formula",
    [
        "__import__('os').system('ls')",
        "().__class__.__bases__",
        "(lambda: 1)()",
        "[x for x in range(10)]",
        "abierto[0]",
        "objeto.atributo",
        "9**9**9",
    ],
)
def test_una_formula_no_puede_alcanzar_el_interprete(formula: str) -> None:
    """Con atributos se llega a `__class__` y de ahí a cualquier cosa; con `**`
    se cuelga el proceso sin necesidad de llegar a ningún sitio."""
    assert formulas.validar(formula) != []
    assert formulas.evaluar(formula, {}) is None


def test_una_funcion_que_no_existe_se_rechaza() -> None:
    assert formulas.validar("inventada(1)") == ["La función «inventada» no existe"]


def test_una_formula_demasiado_grande_se_rechaza() -> None:
    """Mil nodos es alguien pegando algo generado, y evaluarlo en cada fila de
    un listado convierte una lista en una espera."""
    problemas = formulas.validar(" + ".join(["1"] * 300))
    assert any("tope" in p for p in problemas)


# ── Lo que sí se puede ────────────────────────────────────────────────────


def test_aritmetica_sobre_campos_del_registro() -> None:
    assert formulas.evaluar("importe * 1.21", {"importe": 100}) == Decimal("121.00")


def test_los_importes_en_texto_se_tratan_como_numeros() -> None:
    """Viajan como cadena por el contrato, para no perder precisión al
    serializar. Sin convertirlos, `importe * 1.21` fallaría."""
    assert formulas.evaluar("importe * 2", {"importe": "10.50"}) == Decimal("21.00")


def test_un_campo_vacio_da_vacio_y_no_cero() -> None:
    """Tratar el vacío como cero haría que «media de descuento» contara los
    registros sin descuento: es otra respuesta, y nadie la ha pedido."""
    assert formulas.evaluar("importe + descuento", {"importe": 100}) is None


def test_un_campo_que_no_existe_no_rompe_la_formula() -> None:
    assert formulas.evaluar("si(vacio(loquesea), 'sin dato', 'con dato')", {}) == "sin dato"


def test_condicional_y_texto() -> None:
    salida = formulas.evaluar(
        "si(importe > 1000, texto('VIP ', nombre), nombre)",
        {"importe": 5000, "nombre": "ACME"},
    )
    assert salida == "VIP ACME"


def test_redondeo_con_decimales() -> None:
    assert formulas.evaluar("redondear(importe / 3, 2)", {"importe": 100}) == Decimal("33.33")


def test_dias_entre_fechas() -> None:
    assert (
        formulas.evaluar("dias_entre(alta, cierre)", {"alta": "2026-01-01", "cierre": "2026-03-02"})
        == 60
    )


def test_maximo_ignora_los_vacios() -> None:
    assert formulas.evaluar("maximo(a, b, c)", {"a": 3, "c": 9}) == 9


# ── Lo que pasa cuando algo falla ─────────────────────────────────────────


def test_una_division_por_cero_no_tumba_la_ficha() -> None:
    """Un campo calculado que revienta no puede impedir que se lea la ficha
    entera: la alternativa convierte una fórmula mal escrita en un objeto
    inaccesible."""
    assert formulas.evaluar("importe / 0", {"importe": 10}) is None


def test_comparar_cosas_incomparables_da_falso_y_no_error() -> None:
    assert formulas.evaluar("si(nombre > importe, 1, 2)", {"nombre": "x", "importe": 3}) == 2
