"""Campos calculados: una fórmula que se evalúa, no código que se ejecuta
(CRM-00.04.01.04).

Un campo calculado lo escribe **quien configura el CRM**, no quien lo programa.
Eso decide todo lo demás: la fórmula es entrada del tenant, y evaluarla con
`eval()` sería ejecutar código del cliente dentro del proceso del servidor —con
acceso a todo lo que el proceso ve—. Así que hay gramática cerrada y analizador
propio, y lo que no está en la gramática no se puede escribir.

**No se guarda el resultado, se calcula al leer.** Guardarlo obliga a recalcular
cada vez que cambia cualquier cosa de la que depende, y el día que falle un
recálculo el registro queda con un número viejo que parece bueno. Un valor
derivado que miente es peor que uno que cuesta un poco más de calcular.

La gramática es deliberadamente pequeña. Cubre lo que se pide de verdad —sumar
campos, concatenar, redondear, decidir entre dos valores— y no intenta ser un
lenguaje. Una fórmula que necesita bucles no es un campo calculado: es una
automatización, y ahí sí hay motor con topes y traza.
"""

from __future__ import annotations

import ast
import operator
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from crmcore.errors import ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Operadores admitidos. Lista cerrada: lo que no está, no se puede escribir.
# `**` queda fuera a propósito — `9**9**9` cuelga el proceso y no hay ninguna
# fórmula de negocio que lo necesite.
BINARIOS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}

COMPARACIONES: dict[type[ast.cmpop], Callable[[Any, Any], Any]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


def _si(condicion: Any, entonces: Any, si_no: Any) -> Any:
    return entonces if condicion else si_no


def _redondear(valor: Any, decimales: Any = 0) -> Any:
    try:
        return round(Decimal(str(valor)), int(decimales))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _texto(*partes: Any) -> str:
    return "".join("" if p is None else str(p) for p in partes)


def _dias_entre(desde: Any, hasta: Any) -> int | None:
    a, b = _fecha(desde), _fecha(hasta)
    return (b - a).days if a and b else None


def _fecha(valor: Any) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor)[:10])
    except (TypeError, ValueError):
        return None


# Funciones de la gramática. Nombres en castellano porque quien escribe la
# fórmula es quien configura el CRM, no quien lo programa.
FUNCIONES: dict[str, Callable[..., Any]] = {
    "si": _si,
    "redondear": _redondear,
    "texto": _texto,
    "dias_entre": _dias_entre,
    "maximo": lambda *v: max((x for x in v if x is not None), default=None),
    "minimo": lambda *v: min((x for x in v if x is not None), default=None),
    "absoluto": lambda v: abs(v) if isinstance(v, (int, float, Decimal)) else None,
    "longitud": lambda v: len(v) if isinstance(v, (str, list, tuple)) else None,
    "mayusculas": lambda v: str(v).upper() if v is not None else None,
    "minusculas": lambda v: str(v).lower() if v is not None else None,
    "vacio": lambda v: v in (None, "", [], {}),
}

# Tope de nodos de la expresión. Una fórmula de negocio no pasa de veinte; mil
# nodos es alguien pegando algo generado, y evaluarlo en cada lectura de cada
# fila de un listado convierte una lista en una espera.
MAX_NODOS = 200


def validar(formula: str) -> list[str]:
    """Comprueba la fórmula SIN evaluarla. Devuelve los problemas.

    Se valida al guardar el campo y no al leer el primer registro: una fórmula
    rota descubierta al leer es una ficha que no se puede abrir, y la persona
    que la escribió ya no está delante.
    """
    problemas: list[str] = []
    try:
        arbol = ast.parse(formula.strip(), mode="eval")
    except SyntaxError as exc:
        return [f"No se entiende la fórmula: {exc.msg}"]

    nodos = list(ast.walk(arbol))
    if len(nodos) > MAX_NODOS:
        problemas.append(f"La fórmula tiene {len(nodos)} partes y el tope son {MAX_NODOS}")

    for nodo in nodos:
        if isinstance(nodo, ast.Call):
            if not isinstance(nodo.func, ast.Name) or nodo.func.id not in FUNCIONES:
                nombre = getattr(nodo.func, "id", "?")
                problemas.append(f"La función «{nombre}» no existe")
        elif isinstance(nodo, ast.BinOp) and type(nodo.op) not in BINARIOS:
            problemas.append(f"El operador «{type(nodo.op).__name__}» no se admite")
        elif isinstance(nodo, (ast.Attribute, ast.Subscript, ast.Lambda, ast.comprehension)):
            # Cerrar estos es lo que impide que una fórmula alcance el intérprete:
            # con atributos se llega a `__class__` y de ahí a cualquier cosa.
            problemas.append("Las fórmulas no admiten atributos, índices ni funciones anónimas")
    return problemas


def evaluar(formula: str, valores: dict[str, Any]) -> Any:
    """Evalúa la fórmula sobre los valores del registro.

    Ante cualquier problema devuelve `None` y lo registra. **No lanza**: un campo
    calculado que revienta no puede impedir que se lea la ficha entera, y la
    alternativa —propagar el error— convierte una fórmula mal escrita en un
    objeto inaccesible.
    """
    problemas = validar(formula)
    if problemas:
        logger.warning("formula.invalida", formula=formula[:120], problemas=problemas)
        return None
    try:
        return _evaluar(ast.parse(formula.strip(), mode="eval").body, valores)
    except Exception as exc:  # noqa: BLE001 — una fórmula rota no rompe la ficha
        logger.warning("formula.fallo", formula=formula[:120], error=str(exc)[:200])
        return None


def _evaluar(nodo: ast.AST, valores: dict[str, Any]) -> Any:
    if isinstance(nodo, ast.Constant):
        return nodo.value
    if isinstance(nodo, ast.Name):
        # Un campo que no existe vale `None`, no lanza: los campos opcionales
        # están vacíos la mayor parte del tiempo y una fórmula que se rompe por
        # eso no serviría para nada.
        return _numerico(valores.get(nodo.id))
    if isinstance(nodo, ast.BinOp):
        fn = BINARIOS.get(type(nodo.op))
        if fn is None:
            raise ErrorValidacion("Operador no admitido", error_code="formula.operador")
        izquierda = _evaluar(nodo.left, valores)
        derecha = _evaluar(nodo.right, valores)
        if izquierda is None or derecha is None:
            # Sumar algo a un campo vacío da vacío, no cero. Tratar el vacío
            # como cero haría que «media de descuento» contara los registros sin
            # descuento, que es una respuesta distinta y nadie la habría pedido.
            return None
        return fn(izquierda, derecha)
    if isinstance(nodo, ast.UnaryOp) and isinstance(nodo.op, (ast.USub, ast.UAdd)):
        valor = _evaluar(nodo.operand, valores)
        if valor is None:
            return None
        return -valor if isinstance(nodo.op, ast.USub) else valor
    if isinstance(nodo, ast.Compare) and len(nodo.ops) == 1:
        fn = COMPARACIONES.get(type(nodo.ops[0]))
        if fn is None:
            raise ErrorValidacion("Comparación no admitida", error_code="formula.comparacion")
        izquierda = _evaluar(nodo.left, valores)
        derecha = _evaluar(nodo.comparators[0], valores)
        if izquierda is None or derecha is None:
            return False
        try:
            return fn(izquierda, derecha)
        except TypeError:
            return False
    if isinstance(nodo, ast.BoolOp):
        valores_rama = [_evaluar(v, valores) for v in nodo.values]
        return all(valores_rama) if isinstance(nodo.op, ast.And) else any(valores_rama)
    if isinstance(nodo, ast.UnaryOp) and isinstance(nodo.op, ast.Not):
        return not _evaluar(nodo.operand, valores)
    if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name):
        fn = FUNCIONES.get(nodo.func.id)
        if fn is None:
            raise ErrorValidacion("Función no admitida", error_code="formula.funcion")
        return fn(*[_evaluar(a, valores) for a in nodo.args])
    raise ErrorValidacion(
        f"La fórmula usa algo que no se admite: {type(nodo).__name__}",
        error_code="formula.nodo_no_admitido",
    )


def _numerico(valor: Any) -> Any:
    """Convierte a `Decimal` lo que el modelo guarda como cadena numérica.

    Los importes viajan como texto por el contrato —para no perder precisión al
    serializar— y sin esto `importe * 1.21` fallaría al multiplicar una cadena.
    """
    if isinstance(valor, str):
        try:
            return Decimal(valor)
        except InvalidOperation:
            return valor
    if isinstance(valor, float):
        return Decimal(str(valor))
    return valor
