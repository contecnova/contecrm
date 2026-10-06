"""El día de hoy se recibe, no se busca (CRM-00.01.03.02).

Hay veintidós funciones del producto que reciben `hoy` como parámetro. **Eso es
una decisión, no una deuda**: una función que mira el reloj por dentro no se
puede probar sin mover el reloj de la máquina, y lo que se prueba entonces es el
reloj. Con `hoy` recibido, una prueba fija el día y comprueba el cálculo.

Lo que no había era quien vigilara las dos mitades de esa decisión:

**Que nadie mire el reloj a escondidas.** `date.today()` y `datetime.now()` sin
huso dan la hora de la máquina, no la del cliente. Entre las 00:00 y las 02:00 en
España eso es **otro día**, y un «últimos siete días» calculado así se come el
último. Ya costó veinticinco sitios en una sesión anterior, y al escribir este
guardián quedaban tres más: dos en los operadores temporales de los segmentos y
uno comparando fechas **como texto**, que es peor —dos instantes iguales
escritos con husos distintos se ordenan por el carácter, no por el momento—.

**Que quien llama pase el día del cliente.** Una ruta que resuelve `hoy` por su
cuenta deshace el trabajo: el parámetro está para recibir `fechas.hoy(db)`, que
es la fecha donde está quien usa el CRM.
"""

from __future__ import annotations

import ast
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[2]

# Dónde se mira: el producto. Las pruebas pueden mirar el reloj —comprueban
# justamente eso— y los scripts de operación corren en la máquina, no por un
# cliente.
DIRECTORIOS = ("services", "packages/crmcore/crmcore")

# Lo que se prohíbe, y lo que se espera en su lugar.
PROHIBIDO = {
    "today": "`fechas.hoy(db)`, que es el día donde está el cliente",
    "utcnow": "`fechas.ahora(db)`: `utcnow()` además devuelve un instante sin huso",
}

# Las excepciones, con su motivo. Se escriben aquí y no se dejan fuera en
# silencio: una lista incompleta sin explicación se lee como una lista completa.
#
# `crmcore/fechas.py` es quien resuelve la fecha del tenant: es el único sitio
# donde mirar el reloj es el trabajo.
EXENTOS = {
    "packages/crmcore/crmcore/fechas.py": "es quien resuelve la hora del tenant",
}


def _ficheros() -> list[pathlib.Path]:
    salida: list[pathlib.Path] = []
    for carpeta in DIRECTORIOS:
        salida.extend(sorted((RAIZ / carpeta).rglob("*.py")))
    return salida


def _llamada(nodo: ast.AST) -> str:
    """El método llamado: `today` de `date.today()`, venga como venga el módulo.

    **Por el nombre del método y no por el del módulo.** La primera versión
    comparaba `date.today`, y bastaba con `from datetime import date as _d` para
    pasar por delante: la mutación plantada lo hizo a la primera. Quien quiere
    saltarse esto no lo hace a propósito —lo hace importando como siempre ha
    importado—, así que el guardián no puede depender de cómo se llame el módulo
    en ese fichero.
    """
    if not isinstance(nodo, ast.Call):
        return ""
    fn = nodo.func
    return fn.attr if isinstance(fn, ast.Attribute) else ""


def test_nadie_mira_el_reloj_de_la_maquina() -> None:
    """`date.today()` y `datetime.utcnow()` dan la hora de la máquina, no la del
    cliente. De madrugada eso es otro día."""
    culpables: list[str] = []
    mirados = 0

    for fichero in _ficheros():
        rel = str(fichero.relative_to(RAIZ))
        if rel in EXENTOS:
            continue
        mirados += 1
        try:
            arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — lo caza `ruff` antes
            continue
        for nodo in ast.walk(arbol):
            nombre = _llamada(nodo)
            if nombre in PROHIBIDO:
                culpables.append(
                    f"{rel}:{getattr(nodo, 'lineno', 0)} usa `{nombre}()` — usa {PROHIBIDO[nombre]}"
                )

    # BARRER CERO NO ES ESTAR EN VERDE: si el recorrido dejara de encontrar
    # ficheros, la lista saldría vacía y esto pasaría sin haber mirado nada.
    assert mirados > 300, f"el recorrido solo ve {mirados} ficheros: no está mirando"
    assert not culpables, (
        "Hay código que mira el reloj de la máquina en vez del del cliente:\n  "
        + "\n  ".join(culpables)
        + "\n\nEntre las 00:00 y las 02:00 en España eso es OTRO DÍA, y un "
        "«últimos siete días» calculado así se come el último."
    )


def test_una_fecha_sin_huso_no_se_compara_como_texto() -> None:
    """Dos instantes iguales escritos con husos distintos se ordenan por el
    carácter y no por el momento. Es el fallo que tenía la validación de «no
    puede estar en el pasado», en el campo que existe justamente para eso."""
    from datetime import datetime, timedelta, timezone

    from services.metadata.validacion import _esta_en_el_pasado

    ahora = datetime(2026, 10, 6, 20, 0, tzinfo=timezone.utc)

    # **El caso que delata la comparación por texto.** Las 21:00 en +02:00 son
    # las 19:00 UTC: ya pasaron. Pero como cadena, «2026-10-06T21:00:00+02:00»
    # es MAYOR que «2026-10-06T20:00:00+00:00» —compara el 21 contra el 20— y
    # sale «aún no ha pasado». Un campo que existe para impedir fechas pasadas
    # aceptaba una pasada.
    ya_paso = datetime(2026, 10, 6, 21, 0, tzinfo=timezone(timedelta(hours=2)))
    assert (
        _esta_en_el_pasado(ya_paso, ahora) is True
    ), "las 21:00 en +02:00 son las 19:00 UTC: ya han pasado"

    # Y el contrario: las 23:30 en +02:00 son las 21:30 UTC, que todavía no han
    # llegado.
    aun_no = datetime(2026, 10, 6, 23, 30, tzinfo=timezone(timedelta(hours=2)))
    assert _esta_en_el_pasado(aun_no, ahora) is False

    # Una fecha sin huso se lee **en UTC** y no en la hora de la máquina. El caso
    # que lo distingue: las 21:00 sin huso son futuro en UTC —ahora son las
    # 20:00— y serían pasado si se leyeran como hora local de una máquina en
    # +02:00. Dónde esté el servidor no puede decidir si un dato se acepta.
    sin_huso_futuro = datetime(2026, 10, 6, 21, 0)
    assert _esta_en_el_pasado(sin_huso_futuro, ahora) is False

    sin_huso_pasado = datetime(2026, 10, 6, 19, 0)
    assert _esta_en_el_pasado(sin_huso_pasado, ahora) is True


def test_una_fecha_sin_hora_solo_pasa_cuando_acaba_el_dia() -> None:
    """Rechazar «hoy» en un campo que pide una fecha futura obligaría a poner
    mañana para decir hoy."""
    from datetime import date, datetime, timezone

    from services.metadata.validacion import _esta_en_el_pasado

    ahora = datetime(2026, 10, 6, 20, 0, tzinfo=timezone.utc)
    assert _esta_en_el_pasado(date(2026, 10, 6), ahora) is False
    assert _esta_en_el_pasado(date(2026, 10, 5), ahora) is True


def test_los_operadores_temporales_cuentan_desde_el_dia_que_se_les_da() -> None:
    """Un segmento «leads de los últimos siete días» consultado a las 00:30 en
    Madrid contaba desde el día anterior, y el lead de ayer por la noche se
    quedaba fuera sin que nadie entendiera por qué."""
    from datetime import date

    from services.marketing.segmentos import _valor_temporal

    hoy = date(2026, 10, 6)
    assert _valor_temporal("hace_menos_de_dias", 7, hoy) == date(2026, 9, 29)
    assert _valor_temporal("hace_mas_de_dias", 30, hoy) == date(2026, 9, 6)


def test_las_funciones_que_reciben_hoy_no_lo_buscan_dentro() -> None:
    """La mitad que de verdad importa de esa decisión: una función que recibe
    `hoy` **y además** mira el reloj cuando no se lo pasan sigue siendo
    imposible de fijar desde fuera en el caso que no se pasa."""
    sospechosas: list[str] = []
    con_hoy = 0

    for fichero in _ficheros():
        rel = str(fichero.relative_to(RAIZ))
        if rel in EXENTOS:
            continue
        try:
            arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            argumentos = [a.arg for a in nodo.args.args] + [a.arg for a in nodo.args.kwonlyargs]
            if "hoy" not in argumentos:
                continue
            con_hoy += 1
            for dentro in ast.walk(nodo):
                if _llamada(dentro) in PROHIBIDO:
                    sospechosas.append(f"{rel}:{nodo.lineno} `{nodo.name}`")

    # El suelo: si dejaran de verse, este recorrido no estaría mirando nada.
    assert con_hoy >= 15, f"solo se ven {con_hoy} funciones con `hoy`: el recorrido no mira"
    assert not sospechosas, (
        "Estas reciben `hoy` y aun así miran el reloj por dentro, así que no se "
        "pueden fijar desde fuera:\n  " + "\n  ".join(sospechosas)
    )


def test_el_criterio_esta_escrito_para_quien_venga_detras() -> None:
    """Una convención que vive en la cabeza de quien la puso es la que el
    siguiente no sigue."""
    manual = (RAIZ / "docs" / "manual-tecnico.md").read_text(encoding="utf-8")
    assert "fechas.hoy(db)" in manual, "el manual técnico no dice de dónde sale el día de hoy"
