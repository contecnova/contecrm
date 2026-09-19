"""Tablas de decisión evaluables y auditables (CRM-00.03.02.10).

Una tabla de decisión es la política de negocio escrita como datos: «si el
importe pasa de 50.000 y el margen baja del 15 %, aprueba el director». Vive
como dato para que la cambie quien manda en ella, que no es quien escribe el
código.

El modelo (`TablaDecision`) ya existía. Lo que faltaba —y es todo lo que la
hace utilizable— es esto:

**Evaluar con explicación, no solo con resultado.** Una tabla que devuelve
«director» y no dice por qué es tan opaca como el `if` que venía a sustituir. La
evaluación devuelve qué reglas casaron, cuáles no y en qué condición fallaron.
Es la misma decisión que se tomó en el enrutamiento de leads, y por el mismo
motivo: la pregunta que más se hace no es «¿qué salió?» sino «¿por qué salió
eso?».

**Analizar huecos y solapes antes de publicar.** Es lo que separa una tabla de
decisión de una lista de `if`. Un hueco —una combinación de entradas que ninguna
regla cubre— se descubre normalmente con un expediente parado y un cliente
esperando. Un solape bajo política `unica` es una ambigüedad que el sistema
resolvería en silencio eligiendo una de las dos.

**Cerrar la política de aciertos.** Sin declararla, dos reglas que casan a la
vez dan un resultado que depende del orden de lectura de la base, y por tanto
puede cambiar entre dos ejecuciones idénticas sin que nadie haya tocado nada.

Los operadores son los del motor de procesos, a propósito: una condición se
escribe igual en un paso de decisión que en una tabla, y quien aprende una sabe
la otra. Y siguen siendo lista cerrada — una definición es dato del tenant y no
puede convertirse en código ejecutable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.logging import get_logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.orchestrator.modelos import TablaDecision
from services.orchestrator.motor import OPERADORES, resolver

logger = get_logger(__name__)

# Políticas de aciertos. Son el subconjunto de DMN que resuelve casos reales sin
# convertir la tabla en un lenguaje: las demás (`rule order`, `output order`)
# devuelven listas ordenadas que en la práctica nadie consume distinto de
# `todas`.
POLITICAS = {
    # Exactamente una regla puede casar. Si casan dos, es un error de la tabla y
    # se dice: es la política de las decisiones donde una ambigüedad no es
    # aceptable —quién aprueba, qué tipo impositivo se aplica—.
    "unica": "Exactamente una regla debe casar; si casan varias, es un error",
    # Gana la primera que case, en el orden en que están escritas.
    "primera": "Gana la primera regla que case, por orden de la tabla",
    # Gana la de mayor prioridad. A igualdad, la primera.
    "prioridad": "Gana la regla de mayor prioridad declarada",
    # Pueden casar varias, pero todas tienen que dar la MISMA salida. Si
    # difieren, es un error: la tabla dice dos cosas distintas del mismo caso.
    "cualquiera": "Pueden casar varias, pero deben coincidir en la salida",
    # Se acumulan todas las que casen.
    "todas": "Se acumulan las salidas de todas las reglas que casen",
}

# Tipos declarables de una columna. Sirven para validar la tabla al guardarla,
# no para convertir en tiempo de evaluación: convertir callado es cómo un «50»
# de texto acaba comparándose con un 50 numérico y dando falso.
TIPOS = ("numero", "texto", "booleano", "lista", "fecha")

# Operadores que además de comparar acotan un intervalo numérico. Son los que el
# análisis de huecos sabe razonar; con el resto no se pronuncia, en vez de
# inventarse una cobertura que no puede demostrar.
OPERADORES_RANGO = {">", ">=", "<", "<=", "="}


# ── Resultado ─────────────────────────────────────────────────────────────


@dataclass
class ReglaEvaluada:
    """Qué pasó con una regla concreta. Esto es la explicación."""

    indice: int
    nombre: str
    caso: bool
    # Cuando no casó, en qué condición falló y con qué valores. Sin esto, «no
    # casó» obliga a reconstruir a mano la evaluación para entender por qué.
    fallo_en: dict[str, Any] | None = None
    salidas: dict[str, Any] = field(default_factory=dict)

    def a_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"indice": self.indice, "nombre": self.nombre, "caso": self.caso}
        if self.fallo_en:
            d["fallo_en"] = self.fallo_en
        if self.caso:
            d["salidas"] = self.salidas
        return d


@dataclass
class Decision:
    """Lo que devuelve evaluar una tabla."""

    clave: str
    politica: str
    # Salidas resueltas. Con política `todas` cada clave lleva una lista.
    salidas: dict[str, Any]
    entradas: dict[str, Any]
    reglas: list[ReglaEvaluada]
    # `True` cuando ninguna regla casó y se usaron los valores por defecto de
    # las columnas de salida. Se marca porque «no casó nada» y «casó la regla
    # que da ese valor» son cosas distintas, y en una auditoría la diferencia
    # importa.
    por_defecto: bool = False

    @property
    def casadas(self) -> list[ReglaEvaluada]:
        return [r for r in self.reglas if r.caso]

    def a_dict(self) -> dict[str, Any]:
        return {
            "clave": self.clave,
            "politica": self.politica,
            "entradas": self.entradas,
            "salidas": self.salidas,
            "por_defecto": self.por_defecto,
            "reglas": [r.a_dict() for r in self.reglas],
        }


# ── Validación ────────────────────────────────────────────────────────────


def validar(tabla: dict[str, Any]) -> list[str]:
    """Comprueba una tabla antes de guardarla. Devuelve los problemas.

    Antes y no al evaluarla: una tabla rota que se guarda se descubre la
    primera vez que un proceso real la usa, que es siempre el peor momento.
    """
    problemas: list[str] = []

    politica = str(tabla.get("politica") or "primera")
    if politica not in POLITICAS:
        problemas.append(
            f"Política de aciertos desconocida: «{politica}». Admitidas: {sorted(POLITICAS)}"
        )

    entradas = tabla.get("entradas") or []
    salidas = tabla.get("salidas") or []
    if not entradas:
        problemas.append("La tabla no declara ninguna entrada")
    if not salidas:
        problemas.append("La tabla no declara ninguna salida")

    claves_entrada: set[str] = set()
    for i, entrada in enumerate(entradas):
        clave = str(entrada.get("clave") or "")
        if not clave:
            problemas.append(f"La entrada {i + 1} no tiene clave")
            continue
        if clave in claves_entrada:
            problemas.append(f"Entrada duplicada: «{clave}»")
        claves_entrada.add(clave)
        if not entrada.get("expresion"):
            # Sin expresión la columna no sabe de dónde sale su valor, y la
            # tabla evaluaría siempre contra None sin decir nada.
            problemas.append(f"La entrada «{clave}» no dice de dónde sale su valor (`expresion`)")
        tipo = entrada.get("tipo")
        if tipo and tipo not in TIPOS:
            problemas.append(f"Tipo desconocido en la entrada «{clave}»: «{tipo}»")

    claves_salida: set[str] = set()
    for i, salida in enumerate(salidas):
        clave = str(salida.get("clave") or "")
        if not clave:
            problemas.append(f"La salida {i + 1} no tiene clave")
            continue
        if clave in claves_salida:
            problemas.append(f"Salida duplicada: «{clave}»")
        claves_salida.add(clave)
        tipo = salida.get("tipo")
        if tipo and tipo not in TIPOS:
            problemas.append(f"Tipo desconocido en la salida «{clave}»: «{tipo}»")

    reglas = tabla.get("reglas") or []
    if not reglas:
        problemas.append("La tabla no tiene ninguna regla")

    for i, regla in enumerate(reglas):
        etiqueta = regla.get("nombre") or f"regla {i + 1}"
        condiciones = regla.get("condiciones")
        if condiciones is None:
            problemas.append(f"«{etiqueta}» no declara condiciones")
            condiciones = []
        for condicion in condiciones:
            entrada = str(condicion.get("entrada") or "")
            if entrada not in claves_entrada:
                # Es el error más frecuente al editar una tabla: renombrar una
                # columna y dejar reglas apuntando al nombre viejo. Esas reglas
                # compararían contra None y no casarían nunca, en silencio.
                problemas.append(
                    f"«{etiqueta}» compara la entrada «{entrada}», que la tabla no declara"
                )
            op = str(condicion.get("op") or "=")
            if op not in OPERADORES:
                problemas.append(
                    f"«{etiqueta}» usa el operador «{op}», que no existe. "
                    f"Admitidos: {sorted(OPERADORES)}"
                )
        sal = regla.get("salidas") or {}
        if not sal:
            problemas.append(f"«{etiqueta}» no produce ninguna salida")
        sobrantes = sorted(set(sal) - claves_salida)
        if sobrantes:
            problemas.append(f"«{etiqueta}» produce salidas no declaradas: {sobrantes}")
        if politica == "prioridad" and "prioridad" not in regla:
            problemas.append(
                f"«{etiqueta}» no declara prioridad, y la política de la tabla es «prioridad»"
            )

    return problemas


def exigir_valida(tabla: dict[str, Any]) -> None:
    problemas = validar(tabla)
    if problemas:
        raise ErrorValidacion(
            "La tabla de decisión tiene problemas",
            error_code="decision.tabla_invalida",
            detalle={"problemas": problemas},
        )


# ── Evaluación ────────────────────────────────────────────────────────────


def evaluar(tabla: TablaDecision | dict[str, Any], variables: dict[str, Any]) -> Decision:
    """Aplica la tabla a unas variables y explica el resultado.

    Acepta la fila o un diccionario con la misma forma: lo segundo es lo que
    permite **simular una tabla antes de guardarla**, que es cuándo hace falta.
    """
    datos = _como_dict(tabla)
    politica = str(datos.get("politica") or "primera")
    if politica not in POLITICAS:
        raise ErrorValidacion(
            f"Política de aciertos desconocida: «{politica}»",
            error_code="decision.politica_desconocida",
            detalle={"admitidas": sorted(POLITICAS)},
        )

    # Se resuelven todas las entradas de una vez y se guardan: son parte de la
    # explicación. Sin ellas, «no casó ninguna regla» no se puede diagnosticar
    # sin reconstruir el contexto de aquella ejecución, que ya no existe.
    entradas: dict[str, Any] = {}
    for entrada in datos.get("entradas") or []:
        clave = str(entrada.get("clave"))
        entradas[clave] = resolver(entrada.get("expresion"), variables)

    evaluadas: list[ReglaEvaluada] = []
    for i, regla in enumerate(datos.get("reglas") or []):
        evaluadas.append(_evaluar_regla(i, regla, entradas, variables))

    casadas = [r for r in evaluadas if r.caso]
    salidas, por_defecto = _resolver_salidas(datos, politica, casadas, evaluadas)

    return Decision(
        clave=str(datos.get("clave") or ""),
        politica=politica,
        salidas=salidas,
        entradas=entradas,
        reglas=evaluadas,
        por_defecto=por_defecto,
    )


def _evaluar_regla(
    indice: int,
    regla: dict[str, Any],
    entradas: dict[str, Any],
    variables: dict[str, Any],
) -> ReglaEvaluada:
    nombre = str(regla.get("nombre") or f"regla {indice + 1}")
    for condicion in regla.get("condiciones") or []:
        clave = str(condicion.get("entrada") or "")
        op = OPERADORES.get(str(condicion.get("op") or "="))
        izquierda = entradas.get(clave)
        # El valor de comparación también se resuelve: así una regla puede
        # comparar una entrada con otra variable del contexto —«el descuento
        # supera el máximo de su tier»— y no solo con una constante.
        derecha = resolver(condicion.get("valor"), variables)
        try:
            cumple = bool(op(izquierda, derecha)) if op else False
        except TypeError:
            # Comparar una fecha con un número, por ejemplo. No casa, y no
            # revienta: una tabla mal escrita no puede detener un proceso que
            # lleva tres días en marcha.
            cumple = False
        if not cumple:
            return ReglaEvaluada(
                indice=indice,
                nombre=nombre,
                caso=False,
                fallo_en={
                    "entrada": clave,
                    "operador": str(condicion.get("op") or "="),
                    "esperado": derecha,
                    "encontrado": izquierda,
                },
            )
    # Una regla sin condiciones casa siempre. Es la fila «en cualquier otro
    # caso» y es legítima, siempre que esté la última: si está la primera con
    # política `primera`, las demás son código muerto — lo dice `analizar`.
    return ReglaEvaluada(
        indice=indice,
        nombre=nombre,
        caso=True,
        salidas=resolver(regla.get("salidas") or {}, variables),
    )


def _resolver_salidas(
    datos: dict[str, Any],
    politica: str,
    casadas: list[ReglaEvaluada],
    todas: list[ReglaEvaluada],
) -> tuple[dict[str, Any], bool]:
    columnas = datos.get("salidas") or []
    por_defecto = {
        str(c.get("clave")): c.get("por_defecto")
        for c in columnas
        if c.get("por_defecto") is not None
    }

    if not casadas:
        # Ninguna regla casó. Con valores por defecto declarados se usan; sin
        # ellos se devuelve vacío y se marca, en vez de inventarse un resultado.
        return dict(por_defecto), True

    if politica == "unica" and len(casadas) > 1:
        raise ErrorValidacion(
            "Varias reglas casan y la tabla exige que solo case una",
            error_code="decision.aciertos_ambiguos",
            detalle={"reglas": [r.nombre for r in casadas]},
        )

    if politica == "cualquiera" and len(casadas) > 1:
        primera = casadas[0].salidas
        discrepantes = [r.nombre for r in casadas[1:] if r.salidas != primera]
        if discrepantes:
            raise ErrorValidacion(
                "Varias reglas casan y no coinciden en la salida",
                error_code="decision.aciertos_discrepantes",
                detalle={"regla_base": casadas[0].nombre, "discrepantes": discrepantes},
            )
        return {**por_defecto, **primera}, False

    if politica == "todas":
        acumulado: dict[str, list[Any]] = {}
        for regla in casadas:
            for clave, valor in regla.salidas.items():
                acumulado.setdefault(clave, []).append(valor)
        return dict(acumulado), False

    if politica == "prioridad":
        # `max` con clave estable: a igual prioridad gana la primera escrita,
        # porque `max` devuelve el primero de los máximos. Es lo que hace que
        # dos ejecuciones idénticas den lo mismo.
        reglas = datos.get("reglas") or []
        ganadora = max(casadas, key=lambda r: _prioridad(reglas, r.indice))
        return {**por_defecto, **ganadora.salidas}, False

    # `primera` y `unica` con un solo acierto.
    return {**por_defecto, **casadas[0].salidas}, False


def _prioridad(reglas: list[Any], indice: int) -> float:
    try:
        return float(reglas[indice].get("prioridad", 0) or 0)
    except (TypeError, ValueError, IndexError):
        return 0.0


def _como_dict(tabla: TablaDecision | dict[str, Any]) -> dict[str, Any]:
    if isinstance(tabla, dict):
        return tabla
    return {
        "clave": tabla.clave,
        "politica": tabla.politica,
        "entradas": tabla.entradas,
        "salidas": tabla.salidas,
        "reglas": tabla.reglas,
    }


# ── Análisis: huecos, solapes y reglas muertas ────────────────────────────


def analizar(tabla: TablaDecision | dict[str, Any]) -> dict[str, Any]:
    """Busca lo que hace que una tabla falle en producción y no al probarla.

    Tres cosas, por orden de lo caras que salen:

      * **Huecos**: combinaciones de entradas que ninguna regla cubre. Sin esto
        se descubren con un expediente parado.
      * **Solapes**: pares de reglas que pueden casar a la vez. Bajo política
        `unica` es un error en cuanto pase; bajo `primera`, la segunda puede ser
        código muerto.
      * **Reglas inalcanzables**: las que nunca podrán casar porque otra anterior
        las tapa siempre.

    **Lo que este análisis NO hace, dicho por delante:** no es un demostrador.
    Razona sobre intervalos numéricos y sobre igualdades de texto, que es de lo
    que están hechas el 90 % de las tablas reales, y se declara *indeciso* sobre
    lo demás (`contiene`, `en` con listas variables, comparaciones entre dos
    entradas) en vez de afirmar una cobertura que no puede demostrar. Un
    analizador que dice «completa» cuando no lo sabe es peor que no tenerlo.
    """
    datos = _como_dict(tabla)
    politica = str(datos.get("politica") or "primera")
    reglas = datos.get("reglas") or []
    entradas = {str(e.get("clave")): e for e in (datos.get("entradas") or [])}

    solapes: list[dict[str, Any]] = []
    inalcanzables: list[dict[str, Any]] = []
    indecidibles: list[str] = []

    for i, a in enumerate(reglas):
        for j, b in list(enumerate(reglas))[i + 1 :]:
            veredicto = _pueden_casar_a_la_vez(a, b, entradas)
            if veredicto is None:
                etiqueta = f"{_nombre(a, i)} ↔ {_nombre(b, j)}"
                if etiqueta not in indecidibles:
                    indecidibles.append(etiqueta)
                continue
            if not veredicto:
                continue
            # Casan a la vez. Qué significa depende de la política.
            if politica in ("unica", "cualquiera"):
                solapes.append(
                    {
                        "reglas": [_nombre(a, i), _nombre(b, j)],
                        "motivo": (
                            "pueden casar a la vez y la política no lo admite"
                            if politica == "unica"
                            else "pueden casar a la vez; deben dar la misma salida"
                        ),
                    }
                )
            elif politica == "primera" and _cubre(a, b, entradas):
                inalcanzables.append(
                    {
                        "regla": _nombre(b, j),
                        "tapada_por": _nombre(a, i),
                        "motivo": "la anterior casa siempre que casaría esta, y gana por política",
                    }
                )
            else:
                solapes.append(
                    {"reglas": [_nombre(a, i), _nombre(b, j)], "motivo": "pueden casar a la vez"}
                )

    huecos = _huecos(reglas, entradas)
    tiene_por_defecto = any(
        c.get("por_defecto") is not None for c in (datos.get("salidas") or [])
    ) or any(not (r.get("condiciones") or []) for r in reglas)

    return {
        "politica": politica,
        "reglas": len(reglas),
        "solapes": solapes,
        "inalcanzables": inalcanzables,
        "huecos": huecos,
        # Si no hay valores por defecto NI una regla que case siempre, un hueco
        # deja la decisión sin respuesta. Con ellos, el hueco es una elección.
        "sin_red_de_seguridad": bool(huecos) and not tiene_por_defecto,
        # Lo que el análisis no ha podido decidir, con nombre. Decirlo es la
        # diferencia entre una herramienta y un adorno.
        "indecidibles": indecidibles,
    }


def _nombre(regla: dict[str, Any], indice: int) -> str:
    return str(regla.get("nombre") or f"regla {indice + 1}")


def _condiciones_por_entrada(regla: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    agrupadas: dict[str, list[dict[str, Any]]] = {}
    for condicion in regla.get("condiciones") or []:
        agrupadas.setdefault(str(condicion.get("entrada") or ""), []).append(condicion)
    return agrupadas


def _pueden_casar_a_la_vez(
    a: dict[str, Any], b: dict[str, Any], entradas: dict[str, Any]
) -> bool | None:
    """`True`/`False` si se puede decidir; `None` si no.

    Dos reglas NO pueden casar a la vez cuando existe al menos una entrada en la
    que sus condiciones son incompatibles. Basta una para separarlas.
    """
    ca, cb = _condiciones_por_entrada(a), _condiciones_por_entrada(b)
    indeciso = False
    for clave in set(ca) & set(cb):
        veredicto = _compatibles(ca[clave], cb[clave], entradas.get(clave) or {})
        if veredicto is False:
            return False
        if veredicto is None:
            indeciso = True
    return None if indeciso else True


def _compatibles(
    unas: list[dict[str, Any]], otras: list[dict[str, Any]], entrada: dict[str, Any]
) -> bool | None:
    """Si dos conjuntos de condiciones sobre la MISMA entrada pueden darse a la vez."""
    todas = unas + otras
    if any(str(c.get("op") or "=") not in OPERADORES_RANGO for c in todas):
        return None
    # Un valor que no es una constante (una referencia `@algo`) no se puede
    # razonar sin ejecutar: depende del contexto.
    if any(isinstance(c.get("valor"), str) and str(c.get("valor")).startswith("@") for c in todas):
        return None

    if entrada.get("tipo") == "numero" or all(_es_numero(c.get("valor")) for c in todas):
        return _intervalos_se_cortan(unas, otras)

    # Texto y booleano: solo `=`, que es un punto. Compatibles si es el mismo.
    valores_a = {c.get("valor") for c in unas if str(c.get("op") or "=") == "="}
    valores_b = {c.get("valor") for c in otras if str(c.get("op") or "=") == "="}
    if not valores_a or not valores_b:
        return None
    return bool(valores_a & valores_b)


def _es_numero(valor: Any) -> bool:
    try:
        float(valor)  # type: ignore[arg-type]
        return True
    except (TypeError, ValueError):
        return False


def _intervalo(condiciones: list[dict[str, Any]]) -> tuple[float, float]:
    """Intervalo cerrado [min, max] que describen unas condiciones numéricas."""
    minimo, maximo = float("-inf"), float("inf")
    for c in condiciones:
        op = str(c.get("op") or "=")
        valor = float(c.get("valor"))  # type: ignore[arg-type]
        if op == "=":
            minimo, maximo = max(minimo, valor), min(maximo, valor)
        elif op == ">":
            # Se trata `>` como `>=` con un epsilon implícito: para decidir si
            # dos intervalos se cortan, la diferencia entre abierto y cerrado
            # solo importa en el punto exacto, y equivocarse ahí produce un
            # aviso de más, nunca uno de menos. Un falso positivo se descarta
            # mirando; un falso negativo se descubre en producción.
            minimo = max(minimo, valor)
        elif op == ">=":
            minimo = max(minimo, valor)
        elif op == "<":
            maximo = min(maximo, valor)
        elif op == "<=":
            maximo = min(maximo, valor)
    return minimo, maximo


def _intervalos_se_cortan(unas: list[dict[str, Any]], otras: list[dict[str, Any]]) -> bool:
    a_min, a_max = _intervalo(unas)
    b_min, b_max = _intervalo(otras)
    return max(a_min, b_min) <= min(a_max, b_max)


def _cubre(a: dict[str, Any], b: dict[str, Any], entradas: dict[str, Any]) -> bool:
    """Si `a` casa siempre que casaría `b` (y por tanto `b` es inalcanzable)."""
    ca, cb = _condiciones_por_entrada(a), _condiciones_por_entrada(b)
    # `a` no puede cubrir a `b` si exige algo sobre una entrada que `b` no acota.
    if set(ca) - set(cb):
        return False
    for clave, condiciones_a in ca.items():
        if any(str(c.get("op") or "=") not in OPERADORES_RANGO for c in condiciones_a + cb[clave]):
            return False
        if not all(_es_numero(c.get("valor")) for c in condiciones_a + cb[clave]):
            # Texto: cubre si pide exactamente lo mismo.
            if {c.get("valor") for c in condiciones_a} != {c.get("valor") for c in cb[clave]}:
                return False
            continue
        a_min, a_max = _intervalo(condiciones_a)
        b_min, b_max = _intervalo(cb[clave])
        if not (a_min <= b_min and b_max <= a_max):
            return False
    return True


def _huecos(reglas: list[Any], entradas: dict[str, Any]) -> list[dict[str, Any]]:
    """Tramos numéricos que ninguna regla cubre, entrada por entrada.

    Se analiza **una entrada cada vez** y no el producto de todas: el producto
    cartesiano de cinco columnas con cuatro tramos cada una son 1.024 casos, y
    un informe de 1.024 líneas no lo lee nadie. Por columna, el aviso es
    accionable —«entre 0 y 1.000 no hay ninguna regla»— y es donde están casi
    todos los huecos reales, que son de tramo y no de combinación.
    """
    huecos: list[dict[str, Any]] = []
    for clave, entrada in entradas.items():
        if entrada.get("tipo") != "numero":
            continue
        intervalos: list[tuple[float, float]] = []
        analizable = True
        for regla in reglas:
            condiciones = [
                c for c in (regla.get("condiciones") or []) if str(c.get("entrada")) == clave
            ]
            if not condiciones:
                # Una regla que no acota esta columna la cubre entera, así que
                # no hay hueco posible en ella.
                analizable = False
                break
            if any(str(c.get("op") or "=") not in OPERADORES_RANGO for c in condiciones) or not all(
                _es_numero(c.get("valor")) for c in condiciones
            ):
                analizable = False
                break
            intervalos.append(_intervalo(condiciones))
        if not analizable or not intervalos:
            continue

        intervalos.sort()
        cubierto_hasta = float("-inf")
        for minimo, maximo in intervalos:
            if minimo > cubierto_hasta:
                huecos.append(
                    {
                        "entrada": clave,
                        "desde": None if cubierto_hasta == float("-inf") else cubierto_hasta,
                        "hasta": minimo,
                    }
                )
            cubierto_hasta = max(cubierto_hasta, maximo)
        if cubierto_hasta < float("inf"):
            huecos.append({"entrada": clave, "desde": cubierto_hasta, "hasta": None})
    return huecos


# ── Acceso ────────────────────────────────────────────────────────────────


def leer(db: Session, tenant_id: UUID, clave: str) -> TablaDecision:
    tabla = db.execute(
        select(TablaDecision).where(
            TablaDecision.tenant_id == tenant_id, TablaDecision.clave == clave
        )
    ).scalar_one_or_none()
    if tabla is None:
        raise NoEncontrado(
            f"No hay tabla de decisión «{clave}»", error_code="decision.tabla_no_existe"
        )
    return tabla


def guardar(db: Session, tenant_id: UUID, datos: dict[str, Any]) -> TablaDecision:
    """Crea o reemplaza una tabla, validándola antes.

    También se analiza, y el resultado se **registra**: publicar una tabla con
    huecos es una decisión legítima —a veces el hueco es un caso que no existe—
    pero tiene que constar que se tomó, para que no parezca un descuido cuando
    dentro de un año alguien lo encuentre.
    """
    exigir_valida(datos)
    clave = str(datos["clave"])
    tabla = db.execute(
        select(TablaDecision).where(
            TablaDecision.tenant_id == tenant_id, TablaDecision.clave == clave
        )
    ).scalar_one_or_none()
    if tabla is None:
        tabla = TablaDecision(tenant_id=tenant_id, clave=clave)
        db.add(tabla)

    tabla.nombre = str(datos.get("nombre") or clave)
    tabla.politica = str(datos.get("politica") or "primera")
    tabla.entradas = datos.get("entradas") or []
    tabla.salidas = datos.get("salidas") or []
    tabla.reglas = datos.get("reglas") or []
    tabla.activa = bool(datos.get("activa", True))
    db.flush()

    informe = analizar(datos)
    if informe["solapes"] or informe["huecos"] or informe["inalcanzables"]:
        logger.warning(
            "decision.tabla_con_avisos",
            clave=clave,
            solapes=len(informe["solapes"]),
            huecos=len(informe["huecos"]),
            inalcanzables=len(informe["inalcanzables"]),
            sin_red_de_seguridad=informe["sin_red_de_seguridad"],
        )
    return tabla


def decidir(db: Session, tenant_id: UUID, clave: str, variables: dict[str, Any]) -> Decision:
    """Evalúa una tabla guardada. Es la puerta que usan el motor y las reglas."""
    tabla = leer(db, tenant_id, clave)
    if not tabla.activa:
        raise ErrorValidacion(
            f"La tabla de decisión «{clave}» está desactivada",
            error_code="decision.tabla_inactiva",
        )
    return evaluar(tabla, variables)
