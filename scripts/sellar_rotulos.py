#!/usr/bin/env python3
"""Sella cómo se llama hoy cada entrada del menú.

    python scripts/sellar_rotulos.py            # comprueba
    python scripts/sellar_rotulos.py --sellar   # lo vuelve a escribir

**Por qué.** Al renombrar una entrada, el manual se queda con el nombre viejo
y nadie lo mira: el gate de manuales comprueba que cubran todo y que no
describan lo que ya no existe, pero una pantalla renombrada **sigue
existiendo**, así que pasa. Medido el 03-11-2026, el día que se renombraron
cinco entradas para que dejaran de pisarse: tres citas se habían quedado
atrás, y una en las instrucciones de cómo llevarse una configuración a
producción.

Adivinarlo por parecido no vale, y lo dijo plantar el caso malo: «Entornos y
despliegue» pasó a llamarse «Promoción entre entornos» y no se parecen en
nada. Un renombrado que cambia el nombre entero es el que más despista y el
que se escapaba.

Con el sello, la prueba sabe qué rótulo existía antes y ya no, que es justo lo
que hay que buscar en el manual. Renombrar no se bloquea: se bloquea
renombrar sin arreglar el manual.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
FRONT = RAIZ / "frontend" / "src"
SELLO = RAIZ / "docs" / "rotulos-de-menu.json"


def rotulos_de_hoy() -> list[str]:
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
    # Entre `ruta:` y `titulo:` puede haber un comentario: con el patrón
    # pegado, el barrido de pantallas llegó a dejar dos módulos sin mirar.
    for m in re.finditer(r'ruta:\s*"[a-z-]+",[\s\S]{0,400}?titulo:\s*"([^"]+)"', mods):
        menu.add(m.group(1))
    return sorted(menu)


def main() -> int:
    hoy = rotulos_de_hoy()
    if len(hoy) < 40:
        print(f"Sólo se han leído {len(hoy)} rótulos: el patrón ha dejado de casar.")
        return 1

    if "--sellar" in sys.argv:
        SELLO.write_text(json.dumps(hoy, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"Sellados {len(hoy)} rótulos en {SELLO.relative_to(RAIZ)}")
        return 0

    if not SELLO.exists():
        print(f"Falta {SELLO.relative_to(RAIZ)}: sellar con --sellar")
        return 1
    sellados = set(json.loads(SELLO.read_text(encoding="utf-8")))
    nuevos = set(hoy) - sellados
    retirados = sellados - set(hoy)
    if nuevos or retirados:
        for r in sorted(retirados):
            print(f"  retirado: «{r}»  — comprueba que el manual no lo nombre")
        for n in sorted(nuevos):
            print(f"  nuevo:    «{n}»")
        print("\nSellar de nuevo: python scripts/sellar_rotulos.py --sellar")
        return 1
    print(f"Los {len(hoy)} rótulos del menú coinciden con el sello.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
