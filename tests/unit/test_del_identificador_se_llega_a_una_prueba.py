"""Desde una capacidad se puede llegar al código; a una prueba, no siempre.

El gate del catálogo exige que toda capacidad `hecho` esté **citada** por su ID
y **documentada** en un manual. Eso convierte el catálogo en trazabilidad de
verdad… hasta el código. De ahí a una prueba no hay camino: la cita vale esté
donde esté, y en 227 de 752 casos no hay ninguna prueba que nombre el ID.

**Esto NO dice que esas 227 estén sin probar, y es importante no leerlo así.**
Comprobadas a mano dos al azar: el aislamiento estanco por partner
(`CRM-03.04.01.03`) y el opt-out de entrenamiento (`CRM-05.02.02.09`) tienen
pruebas de sobra — lo que no tienen es el identificador escrito en ellas. Lo que
falta es el último tramo de la cadena, no la red.

Lo que cuesta: en una auditoría la pregunta no es «¿está probado?» sino
«enséñame la prueba de ESTO». Sin el ID en la prueba hay que saberse el código
para contestar, y quien audita no se lo sabe — así que la respuesta acaba siendo
«confía en nosotros».

Por eso esto es un TOPE y no una exigencia: reescribir doscientos ficheros de prueba de
golpe sería un commit que nadie puede revisar, y la mitad de las citas saldrían
puestas a ojo. Lo que no puede es crecer: una capacidad nueva nace con su prueba
citada, y las viejas se van citando cuando se las toque.
"""

from __future__ import annotations

import functools
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[2]

# Cuántas capacidades `hecho` no las nombra ninguna prueba. Sólo puede BAJAR.
#
#   11-10-2026  227 de 752  medición inicial — MAL: este fichero se contaba a
#                            sí mismo, así que el tope nacía con dos de hueco
#   11-10-2026  228 de 752  MAL otra vez: ese 228 lo saqué sumando tres a la
#                            medición anterior en vez de volver a medir
#   11-10-2026  227 de 752  medido, ejecutando el recorrido
TOPE_SIN_PRUEBA_QUE_LAS_NOMBRE = 227


@functools.cache
def _capacidades_hechas() -> tuple[dict, ...]:
    catalogo = yaml.safe_load((RAIZ / "docs/catalogo/catalogo.yaml").read_text(encoding="utf-8"))
    return tuple(
        cap
        for modulo in catalogo["modulos"]
        for seccion in modulo["secciones"]
        for funcion in seccion["funciones"]
        for cap in funcion["capacidades"]
        # Las de `docs` quedan fuera: su entregable ES el documento, y el propio
        # gate del catálogo ya las exime de tener código que citar.
        if cap.get("estado") == "hecho" and cap.get("svc") != "docs"
    )


@functools.cache
def _texto_de_las_pruebas() -> str:
    # ESTE FICHERO NO CUENTA. Su prosa nombra identificadores para explicar el
    # hallazgo, y contarlos haría que citarlos aquí «arreglara» capacidades sin
    # haber escrito una sola prueba: un guardián mirando su propio reflejo. Ya
    # pasó al medirlo —el número salía 225 en vez de 227— y por eso el tope
    # nacía con dos de hueco, que es exactamente lo que un tope no puede tener.
    trozos = [
        p.read_text(encoding="utf-8", errors="ignore")
        for p in (RAIZ / "tests").rglob("*.py")
        if "__pycache__" not in str(p) and p.name != Path(__file__).name
    ]
    # Las del front cuentan: una capacidad de interfaz se prueba allí.
    trozos += [
        p.read_text(encoding="utf-8", errors="ignore")
        for p in (RAIZ / "frontend" / "src").rglob("*.test.*")
    ]
    return "\n".join(trozos)


@functools.cache
def _sin_prueba_que_las_nombre() -> tuple[str, ...]:
    texto = _texto_de_las_pruebas()
    return tuple(c["id"] for c in _capacidades_hechas() if c["id"] not in texto)


def test_el_recorrido_mira_de_verdad() -> None:
    """Un recorrido que no lee las pruebas daría «ninguna citada», que es el
    mismo rojo que no citar ninguna — y uno que no lea el catálogo daría cero,
    que es el verde de no haber mirado."""
    assert len(_capacidades_hechas()) >= 700
    assert len(_texto_de_las_pruebas()) > 1_000_000
    # Y una que evidentemente está citada, para saber que el corpus se lee.
    assert "CRM-00.04.01.03" not in _sin_prueba_que_las_nombre()


def test_la_distancia_entre_el_catalogo_y_las_pruebas_no_crece() -> None:
    """Una capacidad nueva nace con su prueba citada. Las viejas se van citando
    cuando se las toque — no de golpe, que sería un commit irrevisable."""
    cuantas = len(_sin_prueba_que_las_nombre())
    assert cuantas <= TOPE_SIN_PRUEBA_QUE_LAS_NOMBRE, (
        f"Han subido a {cuantas} las capacidades `hecho` que no nombra ninguna "
        f"prueba; el tope medido eran {TOPE_SIN_PRUEBA_QUE_LAS_NOMBRE}. Si has "
        "declarado una capacidad hecha, cita su identificador en la prueba que "
        "lo demuestra."
    )


def test_el_tope_no_se_queda_alto_cuando_se_arregla() -> None:
    """Un tope que no baja deja sitio para que entre una nueva cada vez que se
    arregla otra, y entonces el número miente sin que nadie lo note."""
    cuantas = len(_sin_prueba_que_las_nombre())
    assert cuantas >= TOPE_SIN_PRUEBA_QUE_LAS_NOMBRE - 3, (
        f"Van {cuantas} y el tope dice {TOPE_SIN_PRUEBA_QUE_LAS_NOMBRE}: baja el "
        "tope en el mismo commit en que se arreglan, o el margen se lo come la "
        "siguiente que entre sin citar."
    )


def test_lo_declarado_hecho_sigue_citado_en_alguna_parte() -> None:
    """La comprobación que ya existía, repetida aquí a propósito: este tope sólo
    tiene sentido mientras la cita en el código siga siendo obligatoria. Si
    alguien aflojara aquélla, éste pasaría a medir la distancia a una cadena que
    ya está rota por el otro extremo."""
    gate = (RAIZ / "tests/unit/test_catalogo_trazabilidad.py").read_text(encoding="utf-8")
    assert "def test_lo_declarado_hecho_esta_citado_en_el_codigo" in gate
    assert "def test_lo_declarado_hecho_esta_documentado" in gate
