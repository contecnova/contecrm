"""El manual no nombra una pantalla que ya no se llama así.

Cuando se renombra una entrada del menú, el manual se queda con el nombre
viejo y nadie lo mira: el gate de manuales comprueba que **cubran** todo y que
no describan lo que ya no existe, pero una pantalla renombrada sigue
existiendo, así que pasa.

**Medido el 03-11-2026**, el mismo día que se renombraron cinco entradas para
que dejaran de pisarse: tres citas se habían quedado atrás —«Entornos y
despliegue», «Canales de ejecución» y «Consola de administración»—, y una de
ellas en las instrucciones de cómo llevarse una configuración a producción.
Quien siga el manual busca una entrada que ya no está.

**Cómo distingue una cita obsoleta de una cita cualquiera.** El manual nombra
entre comillas angulares doscientos y pico rótulos, y la mayoría no son
pantallas —«Cerrada ganada», «Administradores»—. No se puede adivinar cuál
pretendía ser una pantalla.

La primera versión de esta prueba lo intentó por parecido: una cita que se
parece **mucho** a una entrada sin ser ninguna. **No sirve, y lo dijo plantar
el caso malo**: devolví «Entornos y despliegue» al manual y la prueba pasó,
porque hoy esa pantalla se llama «Promoción entre entornos» y no se parecen en
nada. Un renombrado que cambia el nombre entero es justo el que más despista,
y era el que se escapaba.

Así que se hace como el contrato publicado: **se sellan los rótulos**. El
fichero `docs/rotulos-de-menu.json` guarda cómo se llama hoy cada entrada, y
esta prueba compara el sello con el menú de verdad. Un rótulo que estaba
sellado y ya no existe es un renombrado, y entonces —y sólo entonces— se mira
si el manual lo sigue nombrando.

Renombrar **no se bloquea**: se bloquea renombrar sin arreglar el manual. Para
cerrarlo: `python scripts/sellar_rotulos.py --sellar`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
FRONT = RAIZ / "frontend" / "src"

SELLO = RAIZ / "docs" / "rotulos-de-menu.json"


def _rotulos_del_menu() -> set[str]:
    """Cómo se llama hoy cada entrada: las de navegación y las de módulo."""
    textos: dict[str, str] = {}
    grupo = ""
    for fichero in ("es.ts", "es.pantallas.ts"):
        for linea in (FRONT / "i18n" / fichero).read_text(encoding="utf-8").split("\n"):
            abre = re.match(r"^  ([a-zA-Z0-9_]+): \{", linea)
            if abre:
                grupo = abre.group(1)
                continue
            par = re.match(r'^    ([a-zA-Z0-9_]+): "([^"]+)",', linea)
            if par and grupo:
                textos[f"{grupo}.{par.group(1)}"] = par.group(2)

    menu: set[str] = set()
    nav = (FRONT / "lib" / "navegacion.ts").read_text(encoding="utf-8")
    for bloque in re.findall(r"\{[^{}]*\}", nav):
        clave = re.search(r'\bclave:\s*"([^"]+)"', bloque)
        if clave and clave.group(1) in textos:
            menu.add(textos[clave.group(1)])
    mods = (FRONT / "lib" / "modulos.ts").read_text(encoding="utf-8")
    # Entre `ruta:` y `titulo:` puede haber un comentario: ver el barrido de
    # pantallas, donde ese mismo patrón pegado dejó dos módulos sin mirar.
    for m in re.finditer(r'ruta:\s*"[a-z-]+",[\s\S]{0,400}?titulo:\s*"([^"]+)"', mods):
        menu.add(m.group(1))
    return menu


def _citas_de_los_manuales() -> dict[str, str]:
    """Lo que los manuales nombran entre « », con dónde sale."""
    citas: dict[str, str] = {}
    for fichero in sorted(RAIZ.glob("docs/*.md")):
        texto = fichero.read_text(encoding="utf-8")
        for m in re.finditer(r"«([A-ZÁÉÍÓÚÑ][^»]{3,40})»", texto):
            # El manual parte líneas a 80 columnas, así que una cita puede
            # venir con un salto en medio. Sin esto, cada nombre largo sería
            # un falso positivo contra sí mismo.
            cita = " ".join(m.group(1).split())
            citas.setdefault(cita, fichero.name)
    return citas


def test_el_sello_de_rotulos_esta_al_dia() -> None:
    """Lo que el sello guarda es lo que el menú enseña."""
    assert (
        SELLO.exists()
    ), f"falta {SELLO.name}: sellar con «python scripts/sellar_rotulos.py --sellar»"
    sellados = set(json.loads(SELLO.read_text(encoding="utf-8")))
    menu = _rotulos_del_menu()
    assert len(menu) > 40, (
        f"solo se han leído {len(menu)} entradas de menú: la comprobación no " "está mirando nada"
    )
    nuevos = menu - sellados
    assert not nuevos, (
        "entradas de menú que el sello no conoce. Si son nuevas, sellar con "
        "«python scripts/sellar_rotulos.py --sellar»:\n  " + "\n  ".join(sorted(nuevos))
    )


def test_ninguna_cita_del_manual_es_un_nombre_que_ya_cambio() -> None:
    sellados = set(json.loads(SELLO.read_text(encoding="utf-8")))
    menu = _rotulos_del_menu()
    citas = _citas_de_los_manuales()
    assert len(citas) > 100, (
        f"solo se han leído {len(citas)} citas de los manuales: la "
        "comprobación no está mirando nada"
    )

    # Un rótulo que estaba sellado y ya no está en el menú es un renombrado.
    retirados = sellados - menu
    viejas = [f"{donde}: «{cita}»" for cita, donde in sorted(citas.items()) if cita in retirados]
    assert not viejas, (
        "el manual manda a una entrada que ya no se llama así, y quien lo siga "
        "la buscará sin encontrarla. Se renombraron y el manual se quedó "
        "atrás:\n  " + "\n  ".join(viejas)
    )
