"""Lo que una entrada de menú dice que enseña, lo pide ESA pantalla.

El informe de cobertura del front cuenta un recurso como «enseñado» en cuanto
una entrada de navegación lo declara en su lista `recursos`. **Nadie comprobaba
esa declaración.** Declarar es gratis y callar sale caro, así que la lista se
llenó de recursos que la pantalla no pide nunca, y el informe —que es el que se
mira para decidir qué falta— daba por cubierto lo que no existe.

Medido el 27-10-2026, antes de tocar nada: de 45 recursos declarados, **30 no
los pedía ningún fichero del front**. Entre ellos `aprobaciones` (once
operaciones publicadas; la pantalla de aprobaciones pide `/api/v1/documentos`,
que es otra cosa), `aislamiento` y `residencia` (31 operaciones que sólo tenían
puerta por API), y `aprobaciones-documentales`, que ni siquiera existe como
recurso: cero operaciones con ese nombre.

**La primera versión de esta prueba medía flojo** y lo dice aquí porque es el
tipo de error que se repite: comprobaba que el recurso lo pidiera *algún*
fichero del front, no *la pantalla a la que lleva el menú*. Con la regla floja
salían 18 falsos; con la buena, 35. Y la diferencia no es contable: esta lista
es la que usa `Acciones.tsx` para contestar «¿dónde veo esto?», así que un
reclamo en la entrada equivocada manda a quien busca los recorridos a
Marketing, donde no están, en vez de a Campañas, donde sí.

**No hay tope que mantener.** Los 35 se quitaron en el mismo commit: 16 de ellos
sobraban —el recurso se enseña en un módulo genérico, que ya lo declara por su
cuenta— y 19 no se enseñaban en ninguna parte, así que vuelven al informe de
cobertura como lo que son. Un trinquete aquí sería un número que mantener para
algo que o es verdad o no lo es.

Lo que esto NO comprueba: que la pantalla lo enseñe **bien**. Sólo que lo pide,
que es la mitad que faltaba. La otra la fija el catálogo, capacidad a capacidad.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
FRONT = RAIZ / "frontend" / "src"
NAVEGACION = FRONT / "lib" / "navegacion.ts"
APP = FRONT / "App.tsx"

# Una entrada con `a:` y `recursos:`, en un objeto sin objetos dentro.
ENTRADA = re.compile(
    r'\{[^{}]*?(?<![\w])a:\s*"([^"]+)"[^{}]*?recursos:\s*\[([^\]]*)\][^{}]*?\}', re.S
)


@functools.cache
def _pagina_de_cada_ruta() -> dict[str, Path]:
    """Ruta del enrutador → fichero de la pantalla que la atiende."""
    app = APP.read_text(encoding="utf-8")
    componentes = dict(re.findall(r'<Route path="([^"]+)" element=\{<(\w+)', app))
    # `import { X as Y }`: el enrutador nombra a Y y el fichero exporta X.
    alias = dict(re.findall(r"(\w+)\s+as\s+(\w+)", app))
    donde: dict[str, Path] = {}
    for fichero in FRONT.rglob("*.tsx"):
        for nombre in re.findall(r"export function (\w+)", fichero.read_text(encoding="utf-8")):
            donde.setdefault(nombre, fichero)
    salida: dict[str, Path] = {}
    for ruta, componente in componentes.items():
        pagina = donde.get(componente) or donde.get(alias.get(componente, ""))
        if pagina is not None:
            salida[ruta] = pagina
    return salida


@functools.cache
def _reclamos() -> tuple[tuple[str, str], ...]:
    """(ruta del menú, recurso que declara enseñar)."""
    texto = NAVEGACION.read_text(encoding="utf-8")
    salida: list[tuple[str, str]] = []
    for ruta, lista in ENTRADA.findall(texto):
        for recurso in lista.split(","):
            limpio = recurso.strip().strip('"')
            if limpio:
                salida.append((ruta, limpio))
    return tuple(salida)


def _sin_pedir() -> tuple[str, ...]:
    paginas = _pagina_de_cada_ruta()
    rotos: list[str] = []
    for ruta, recurso in _reclamos():
        pagina = paginas.get(ruta)
        if pagina is None:
            rotos.append(f"{ruta} → no hay pantalla para esta ruta (declara «{recurso}»)")
            continue
        if f"api/v1/{recurso}" not in pagina.read_text(encoding="utf-8"):
            rotos.append(f"{ruta} ({pagina.name}) dice enseñar «{recurso}» y no lo pide")
    return tuple(rotos)


def test_el_recorrido_mira_de_verdad() -> None:
    """Primero, que esto no esté midiendo el vacío.

    Si la navegación o el enrutador cambiaran de forma, saldrían cero reclamos
    y el gate pasaría en verde sin haber abierto un fichero.
    """
    assert len(_reclamos()) >= 10, _reclamos()
    paginas = _pagina_de_cada_ruta()
    assert len(paginas) >= 15, sorted(paginas)
    # Y que al menos un reclamo se resuelve: si el literal que se busca
    # estuviera mal formado, no encontraría ninguno y todo saldría roto.
    assert len(_sin_pedir()) < len(_reclamos())


def test_cada_menu_pide_lo_que_dice_que_ensena() -> None:
    """Sin tope: o la pantalla lo pide, o el reclamo sobra."""
    rotos = _sin_pedir()
    assert not rotos, (
        "Entradas de menú que dicen llevar a un recurso que su pantalla no "
        "pide. El informe de cobertura lo cuenta como enseñado, y quien busque "
        "ese recurso acabará en una pantalla donde no está:\n  " + "\n  ".join(rotos)
    )
