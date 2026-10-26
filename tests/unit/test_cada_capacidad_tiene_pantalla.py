"""De cada capacidad hecha se tiene que llegar a una pantalla (CRM-07.04.05.02).

El informe de cobertura que ya había mide **operaciones publicadas**: cuántas
rutas de la API tienen pantalla. Es útil y no contesta la pregunta que importa,
que es la del catálogo: **qué sabe hacer el CRM que ninguna pantalla enseña**.

La diferencia no es formal. Una pantalla genérica lista `/api/v1/webhooks` y con
eso cubre la operación; que además enseñe la cola de fallidos, el reenvío y el
catálogo de eventos —tres capacidades distintas del catálogo— no lo dice nadie.
Y al revés: hay capacidades enteras cuya única puerta es la API, y quien mira el
producto concluye que no están.

**El mecanismo es el mismo que el de las pruebas que citan por identificador**, y
por el mismo motivo: declarar obliga a mirar la pantalla. Una declaración se
escribe en un minuto; escribirla sin abrir la pantalla es tan posible aquí como
allí, y lo que lo hace caro es que la declaración **se enseña en el producto**
—la pantalla de cobertura la pinta—, así que una falsa la ve el primero que
entra.

El tope sólo baja. Cada bajada va en el mismo commit que la pantalla o la
declaración que la justifica, con una línea diciendo qué se miró.

NO cuentan los ficheros de prueba del front: una prueba no es una pantalla, y
contarlas haría que citar un identificador en un test «cubriera» la capacidad
sin que nadie la enseñe.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[2]
FRONT = RAIZ / "frontend" / "src"
RE_ID = re.compile(r"CRM-\d\d\.\d\d\.\d\d\.\d\d")

# ── Histórico. Cada línea, el bloque que la bajó ──────────────────────────
#
#   26-10-2026  684 de 753  medido por primera vez. El informe de cobertura
#                            que habia mide operaciones publicadas; este mide
#                            CAPACIDADES, que es lo que se vende y lo que el
#                            catalogo enumera. Solo 69 tenian una pantalla que
#                            las nombrara, y 53 de esas 69 son las propias
#                            capacidades de front: o sea que de todo lo demas
#                            que sabe hacer el CRM, 16 capacidades estaban
#                            declaradas en alguna pantalla. Las de `docs`
#                            quedan fuera del recuento
#   26-10-2026  540 de 753  declarado lo que ya se ensena: los 24 modulos
#                            genericos declaran ahora la lista de capacidades
#                            de PRODUCTO que se ven en ellos —no solo cual de
#                            front es la pantalla— y siete pantallas a medida
#                            (portada, ficha de cliente, tablero de embudo,
#                            bandeja de aprobaciones, gobierno de la suite,
#                            estado y rendimiento) dicen lo suyo en su
#                            cabecera. La lista se PINTA en la pantalla, que es
#                            lo unico que hace caro declarar algo que no se
#                            ensena. 144 capacidades en un bloque, ninguna
#                            pantalla nueva: estaban todas construidas y no lo
#                            decia nadie
TOPE_SIN_PANTALLA = 540


def _es_pantalla(p: Path) -> bool:
    texto = str(p)
    return "/pruebas/" not in texto and ".test." not in texto


@functools.cache
def _ids_del_front() -> frozenset[str]:
    partes = [
        p.read_text(encoding="utf-8", errors="ignore")
        for p in FRONT.rglob("*.ts*")
        if _es_pantalla(p)
    ]
    return frozenset(RE_ID.findall("\n".join(partes)))


@functools.cache
def _capacidades_hechas() -> tuple[dict, ...]:
    catalogo = yaml.safe_load((RAIZ / "docs/catalogo/catalogo.yaml").read_text(encoding="utf-8"))
    return tuple(
        cap
        for modulo in catalogo["modulos"]
        for seccion in modulo["secciones"]
        for funcion in seccion["funciones"]
        for cap in funcion["capacidades"]
        # Las de `docs` quedan fuera: su entregable ES el documento, y una
        # pantalla que «enseñe el manual» ya existe —la ayuda en producto—,
        # así que exigirles declaración sería contar dos veces lo mismo.
        if cap.get("estado") == "hecho" and cap.get("svc") != "docs"
    )


@functools.cache
def _sin_pantalla() -> tuple[str, ...]:
    vistas = _ids_del_front()
    return tuple(c["id"] for c in _capacidades_hechas() if c["id"] not in vistas)


def test_el_recorrido_mira_de_verdad() -> None:
    """Primero, que esto no esté midiendo el vacío.

    Si `FRONT` dejara de existir o el patrón dejara de casar, el recuento
    saldría cero y el gate pasaría en verde sin haber abierto un fichero. Ya
    pasó con el de las pruebas y por eso está escrito aquí también.
    """
    assert len(_capacidades_hechas()) > 700, len(_capacidades_hechas())
    assert len(_ids_del_front()) > 50, sorted(_ids_del_front())
    assert (FRONT / "lib" / "modulos.ts").exists()


def test_las_pruebas_del_front_no_cuentan() -> None:
    """Una prueba no es una pantalla.

    Se comprueba plantando el caso malo: hay identificadores que **sólo**
    aparecen en ficheros de prueba del front, y ninguno de ellos puede estar
    contado como «tiene pantalla».
    """
    solo_en_pruebas = set()
    for p in FRONT.rglob("*.ts*"):
        if _es_pantalla(p):
            continue
        solo_en_pruebas |= set(RE_ID.findall(p.read_text(encoding="utf-8", errors="ignore")))
    solo_en_pruebas -= _ids_del_front()
    assert solo_en_pruebas, "no hay ningún id que viva sólo en pruebas: el caso malo no se planta"
    assert not (solo_en_pruebas & set(_ids_del_front()))


def test_el_tope_de_capacidades_sin_pantalla_solo_baja() -> None:
    """Y que el tope no se quede atrás de la realidad.

    Las dos mitades: no puede subir —una capacidad que pierde su pantalla es
    una regresión— y no puede quedarse muy por encima, porque un tope con
    holgura deja entrar la siguiente sin que nadie se entere.
    """
    cuantas = len(_sin_pantalla())
    assert cuantas <= TOPE_SIN_PANTALLA, (
        f"Hay {cuantas} capacidades hechas que ninguna pantalla nombra, y el "
        f"tope medido eran {TOPE_SIN_PANTALLA}. Si has marcado algo «hecho», "
        f"declara en qué pantalla se ve:\n  " + "\n  ".join(sorted(_sin_pantalla())[:20])
    )
    assert cuantas >= TOPE_SIN_PANTALLA - 3, (
        f"Hay {cuantas} y el tope dice {TOPE_SIN_PANTALLA}: bájalo en este mismo "
        f"commit y di en el histórico qué pantalla lo justifica."
    )


@pytest.mark.parametrize("modulo", ["00", "07"])
def test_el_informe_reparte_por_modulo(modulo: str) -> None:
    """El total no sirve para repartir el trabajo: hace falta saber de qué
    módulo son. 703 es un número para un informe; «59 del módulo de
    multi-tenancy» es un número para una tarde."""
    del_modulo = [i for i in _sin_pantalla() if i.startswith(f"CRM-{modulo}.")]
    assert del_modulo or modulo == "07", f"módulo {modulo} sin huecos, revisa el tope"
