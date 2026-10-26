"""Un umbral escrito en el código es un umbral que nadie puede cambiar.

«Avisar con 30 días», «proponer la fusión a partir de 80», «suprimir tras 3
rebotes blandos»: son decisiones de negocio, y cada instalación —y a veces cada
cliente de la misma instalación— las quiere distintas. Mientras vivan en una
constante de módulo, cambiarlas es tocar código, volver a desplegar y esperar.

Medido el 26-10-2026: **85 constantes numéricas de módulo** en 70 ficheros.

Esta lista es un trinquete: **sólo puede encoger**. Se baja moviendo la
constante a `Settings` —y por tanto al `.env`— y, cuando tenga sentido
afinarla por cliente, declarando además su clave en caliente. En el mismo
commit se borra su línea de aquí.

**Qué NO entra en esta cuenta**, y por qué, con su motivo al lado en
`DE_ESTANDAR`: lo que no es una decisión de nadie sino una constante del mundo
—el radio de la Tierra, el tamaño de un nonce— o de un protocolo. Hacerlas
configurables no da libertad: da la posibilidad de romperlo.

    26-10-2026  85  medición inicial
    26-10-2026  80  los cinco umbrales de negocio de `party`: vigencia de la
                    salud, frescura del dato maestro, preaviso de proveedor,
                    descartes para sospechar y validez del veredicto fiscal
    26-10-2026  68  los doce de `intelligence`: confianzas de extracción,
                    transcripción y voz, parecido de caso, mínimos para
                    entrenar y para dar una prueba A/B por concluyente
    26-10-2026  44  los 24 del núcleo: profundidades, colas, ventanas y
                    tamaños. Todos operativos, así que van sólo al `.env`:
                    «por cliente» no significaría nada
    26-10-2026  32  los 7 de `analytics` y los 5 de `identity`: tamaños de
                    carga, techos de informe, y la longitud mínima de
                    contraseña y la validez de los enlaces de acceso
    26-10-2026   0  los 26 últimos. La lista queda VACÍA, y vaciarla no es
                    el final: el recorrido sigue puesto y lo que vuelva a
                    escribirse en el código cae en
                    `test_ningun_umbral_nuevo_nace_en_el_codigo`
"""

from __future__ import annotations

import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

# Números que no son umbrales: cero, uno, el dos de una división por la mitad,
# los porcentajes sobre cien, y las conversiones de tiempo y de tamaño.
NO_SON_UMBRALES = {0, 1, -1, 2, 100, 10, 1000, 60, 24, 3600, 1024}

# ── Lo que no es decisión de nadie ────────────────────────────────────────
DE_ESTANDAR = {
    "services/service/campo.py::RADIO_TIERRA_M": "el radio de la Tierra no lo decide un cliente",
    "packages/crmcore/crmcore/security/cifrado.py::NONCE_BYTES": (
        "lo fija AES-GCM; cambiarlo rompe el cifrado, no lo afina"
    ),
    "packages/crmcore/crmcore/security/byok.py::MINIMO_BYTES": (
        "longitud mínima de clave: bajarla es debilitar el cifrado a propósito"
    ),
    "packages/crmcore/crmcore/db/migraciones.py::CERROJO_MIGRACION": (
        "identificador del cerrojo de Postgres, no un umbral"
    ),
    "packages/crmcore/crmcore/events/envelope.py::TOPE_DEDUP": (
        "es el ancho de una columna en tres tablas del bus: cambiarlo exige "
        "una migración, y un ajuste que no se aplica hasta entonces es peor "
        "que una constante honesta"
    ),
    "services/tenancy/marca.py::CONTRASTE_MINIMO": (
        "4.5:1 lo fija WCAG AA; bajarlo es dejar de cumplirlo"
    ),
}

# ── Las que todavía viven en el código ────────────────────────────────────
EN_EL_CODIGO_HOY: set[str] = set()


def _constantes() -> dict[str, tuple[int | float, int]]:
    """`fichero::NOMBRE` → (valor, línea).

    Por el AST y no por `grep`: un número dentro de un comentario, de una
    cadena o de una lista no es una constante, y un recorrido que los contara
    daría una cifra inflada que nadie se creería.
    """
    salida: dict[str, tuple[int | float, int]] = {}
    for carpeta in ("services", "packages"):
        for fichero in sorted((RAIZ / carpeta).rglob("*.py")):
            ruta = str(fichero.relative_to(RAIZ))
            if "__pycache__" in ruta or "/migrations/" in ruta or "/tests/" in ruta:
                continue
            try:
                arbol = ast.parse(fichero.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover
                continue
            for nodo in ast.walk(arbol):
                if not (isinstance(nodo, ast.Assign) and len(nodo.targets) == 1):
                    continue
                nombre = getattr(nodo.targets[0], "id", "")
                if not nombre or not nombre.isupper():
                    continue
                if not isinstance(nodo.value, ast.Constant):
                    continue
                valor = nodo.value.value
                if isinstance(valor, bool) or not isinstance(valor, (int, float)):
                    continue
                if valor in NO_SON_UMBRALES:
                    continue
                salida[f"{ruta}::{nombre}"] = (valor, nodo.lineno)
    return salida


def test_el_recorrido_mira_de_verdad() -> None:
    """Sin esto, un recorrido que no encontrara ninguna constante diría que no
    queda ninguna por mover.

    El control NO es un número: éste baja según se mueven, y atarlo a una cifra
    obliga a tocar la prueba cada vez — que es como se acaba bajando el listón
    sin querer. Se comprueba que el AST sigue reconociéndolas, usando las
    EXENTAS, que por definición no se van a mover nunca.
    """
    encontradas = _constantes()
    assert DE_ESTANDAR, "no hay exentas con las que comprobar el recorrido"
    faltan = sorted(k for k in DE_ESTANDAR if k not in encontradas)
    assert not faltan, (
        "El recorrido ha dejado de ver constantes que siguen en el código. "
        "Lo que diga sobre las demás tampoco vale:\n  " + "\n  ".join(faltan)
    )
    # Y que mira más de un fichero: con uno solo, el AST «funciona» y el
    # recorrido no recorre.
    assert len({k.split("::")[0] for k in encontradas}) >= 5


def test_ningun_umbral_nuevo_nace_en_el_codigo() -> None:
    """Un umbral nuevo va a `Settings` desde el primer día. Añadirlo al código
    «de momento» es como se llegó a ochenta y cinco."""
    nuevas = sorted(
        set(_constantes()) - EN_EL_CODIGO_HOY - set(DE_ESTANDAR),
    )
    assert not nuevas, (
        "Constantes numéricas nuevas en el código. Si es una decisión de "
        "negocio o de operación, va a `Settings` y al `.env`; si es una "
        "constante del mundo o de un protocolo, apúntala en `DE_ESTANDAR` con "
        "su motivo:\n  " + "\n  ".join(nuevas)
    )


def test_las_que_se_mueven_salen_de_la_lista() -> None:
    """El trinquete sólo encoge si alguien lo encoge. Esto obliga a borrar la
    línea en el mismo commit que mueve la constante."""
    encontradas = set(_constantes())
    fantasmas = sorted(EN_EL_CODIGO_HOY - encontradas)
    assert not fantasmas, "Ya no están en el código y siguen apuntadas:\n  " + "\n  ".join(
        fantasmas
    )


def test_lo_de_estandar_lleva_su_motivo() -> None:
    """Una exención sin motivo se copia a la siguiente, y entonces la lista de
    exenciones se convierte en la lista de lo que no se mira."""
    for clave, motivo in DE_ESTANDAR.items():
        assert motivo.strip(), f"«{clave}» está exenta sin decir por qué"
    # Y las exentas tienen que existir: una lista con nombres que ya no están
    # se queda grande para siempre y deja de significar nada.
    encontradas = set(_constantes())
    fantasmas = sorted(k for k in DE_ESTANDAR if k not in encontradas)
    assert not fantasmas, "Exentas y ya no existen:\n  " + "\n  ".join(fantasmas)
