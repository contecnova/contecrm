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


def _mira_el_reloj(nodo: ast.AST) -> bool:
    """Si este nodo calcula el día ignorando la zona del cliente.

    Los dos de siempre —`date.today()` y `datetime.now(timezone.utc).date()`— y
    además `utcnow()`, que da un instante **sin huso**: comparar eso con una
    marca que sí lo lleva ordena por el carácter y no por el momento.

    Se mira el nombre del método y no el del módulo: basta un
    `from datetime import date as _d` para que una comparación por módulo deje
    de ver nada, y quien lo escribe no lo hace para esquivar el guardián — lo
    hace importando como siempre ha importado.
    """
    if not isinstance(nodo, ast.Call) or not isinstance(nodo.func, ast.Attribute):
        return False
    metodo = nodo.func.attr
    if metodo in ("today", "utcnow"):
        return True
    # `…now(timezone.utc).date()`: el día de UTC, que no es el del cliente.
    if metodo == "date" and isinstance(nodo.func.value, ast.Call):
        interior = nodo.func.value.func
        return isinstance(interior, ast.Attribute) and interior.attr == "now"
    return False


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
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if nodo.name in AYUDANTES:
                # El ayudante mismo no cuenta: su trabajo ES resolver la fecha, y
                # lo hace con la sesión que le den.
                continue
            # **Por el árbol y no por el texto.** Contaba las apariciones de
            # `date.today()` en el cuerpo tal cual, así que un comentario que
            # explicara por qué NO hay que usarlo contaba como si lo usara: pasó
            # el 06-10-2026, y el aviso señalaba una función que acababa de
            # dejar de mirar el reloj. Un guardián que se dispara con la prosa
            # enseña a no escribir el motivo, que es lo contrario de lo que
            # queremos — y se calla si alguien borra el comentario.
            cuantos = sum(1 for sub in ast.walk(nodo) if _mira_el_reloj(sub))
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


# ── Lo que se le añadió el 06-10-2026 ─────────────────────────────────────
#
# Venía de un fichero aparte, y tenerlo aparte era el mismo error que este
# repositorio se dedica a quitar: DOS guardianes de la misma regla divergen, y
# el que menos se mira es el que se queda corto. Se funden en éste.


# Las que reciben `hoy` y, si no se lo pasan, caen al día de UTC. Van nombradas
# una a una: una lista cerrada que solo puede ENCOGER, no un tope con hueco.
#
# Las tres son puras y sus rutas no llevan sesión —`/cohortes` y `/embudo` reciben
# los datos enteros en el cuerpo—, así que hoy no hay de dónde sacar la zona del
# cliente. Para quitarlas hay que darle sesión a esas rutas, que es un cambio de
# su contrato y no se hace de pasada.
#
#   06-10-2026  3  medición inicial, al fundir aquí el guardián que estaba aparte
CAEN_A_UTC_SIN_DIA = [
    "services/analytics/cohortes.py::cohortes",
    "services/analytics/cohortes.py::embudo",
    "packages/crmcore/crmcore/obs/slo.py::periodo",
]


def test_una_funcion_que_recibe_hoy_no_lo_busca_dentro() -> None:
    """La mitad que de verdad sostiene la decisión de pasar `hoy`.

    Veintidós funciones lo reciben para que una prueba pueda fijar el día. Si
    además miraran el reloj cuando no se lo pasan, en ese caso —que es el de
    producción— seguirían siendo imposibles de fijar desde fuera.
    """
    sospechosas: list[str] = []
    con_hoy = 0

    for fichero in [*(RAIZ / "services").rglob("*.py"), *(RAIZ / "packages").rglob("*.py")]:
        if "__pycache__" in str(fichero) or fichero.name == "fechas.py":
            continue
        try:
            arbol = ast.parse(fichero.read_text(encoding="utf-8"), str(fichero))
        except SyntaxError:  # pragma: no cover
            continue
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            args = {a.arg for a in nodo.args.args} | {a.arg for a in nodo.args.kwonlyargs}
            if "hoy" not in args:
                continue
            con_hoy += 1
            if {"db", "uow", "session"} & args:
                # Con sesión a mano, resolverlo dentro es lo correcto: lo cubre
                # el primer recorrido de este fichero.
                continue
            if any(_mira_el_reloj(sub) for sub in ast.walk(nodo)):
                sospechosas.append(f"{fichero.relative_to(RAIZ)}::{nodo.name}")

    assert con_hoy >= 15, f"solo se ven {con_hoy} funciones con `hoy`: el recorrido no mira"
    assert sorted(sospechosas) == sorted(CAEN_A_UTC_SIN_DIA), (
        "Ha cambiado la lista de funciones que reciben `hoy` y aun así miran el "
        "reloj cuando no se lo pasan. Si ha subido, en ese caso —que es el de "
        "producción— no hay forma de fijar el día desde fuera.\n"
        f"  ahora:  {sorted(sospechosas)}\n"
        f"  medido: {sorted(CAEN_A_UTC_SIN_DIA)}"
    )


def test_una_fecha_no_se_compara_como_texto() -> None:
    """Dos instantes iguales escritos con husos distintos se ordenan por el
    carácter y no por el momento.

    Lo tenía la validación de «no puede estar en el pasado», que es el campo que
    existe justamente para eso: `…T21:00:00+02:00` es mayor como texto que
    `…T20:00:00Z` y es dos horas anterior.
    """
    from datetime import timedelta

    from services.metadata.validacion import _esta_en_el_pasado

    ahora = datetime(2026, 10, 6, 20, 0, tzinfo=timezone.utc)

    ya_paso = datetime(2026, 10, 6, 21, 0, tzinfo=timezone(timedelta(hours=2)))
    assert (
        _esta_en_el_pasado(ya_paso, ahora) is True
    ), "las 21:00 en +02:00 son las 19:00 UTC: ya han pasado"
    aun_no = datetime(2026, 10, 6, 23, 30, tzinfo=timezone(timedelta(hours=2)))
    assert _esta_en_el_pasado(aun_no, ahora) is False

    # Una fecha sin huso se lee en UTC y no en la hora de la máquina: dónde esté
    # el servidor no puede decidir si un dato se acepta.
    assert _esta_en_el_pasado(datetime(2026, 10, 6, 21, 0), ahora) is False
    assert _esta_en_el_pasado(datetime(2026, 10, 6, 19, 0), ahora) is True


def test_una_fecha_sin_hora_solo_pasa_cuando_acaba_el_dia() -> None:
    """Rechazar «hoy» en un campo que pide una fecha futura obligaría a poner
    mañana para decir hoy."""
    from datetime import date

    from services.metadata.validacion import _esta_en_el_pasado

    ahora = datetime(2026, 10, 6, 20, 0, tzinfo=timezone.utc)
    assert _esta_en_el_pasado(date(2026, 10, 6), ahora) is False
    assert _esta_en_el_pasado(date(2026, 10, 5), ahora) is True


def test_un_segmento_sin_el_dia_del_cliente_no_se_inventa_uno() -> None:
    """Caer a UTC en silencio sería el mismo fallo con otro nombre: el corte
    saldría del reloj del servidor y, de madrugada, un día antes."""
    from datetime import date

    from crmcore.errors import ErrorValidacion

    from services.marketing.segmentos import _valor_temporal

    hoy_del_cliente = date(2026, 10, 6)
    assert _valor_temporal("hace_menos_de_dias", 7, hoy_del_cliente) == date(2026, 9, 29)

    with pytest.raises(ErrorValidacion) as fallo:
        _valor_temporal("hace_menos_de_dias", 7)
    assert fallo.value.error_code == "marketing.segmento_sin_dia"


def test_el_criterio_esta_escrito_para_quien_venga_detras() -> None:
    """Una convención que vive en la cabeza de quien la puso es la que el
    siguiente no sigue."""
    manual = (RAIZ / "docs" / "manual-tecnico.md").read_text(encoding="utf-8")
    assert "fechas.hoy(db)" in manual, "el manual técnico no dice de dónde sale el día de hoy"
