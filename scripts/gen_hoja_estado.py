#!/usr/bin/env python3
"""Genera la hoja web de estado del proyecto desde el catálogo.

    python scripts/gen_hoja_estado.py            # escribe docs/hoja-estado.html
    python scripts/gen_hoja_estado.py --check    # falla si está desfasada

**Generada, no mantenida a mano.** El catálogo (`docs/catalogo/catalogo.yaml`)
es la fuente de verdad del alcance y del estado, y un gate impide declarar
«hecho» lo que no está citado en el código y documentado en el manual. Si esta
hoja se editara a mano, al segundo día diría lo que alguien creyó que había
hecho — que es exactamente lo que el catálogo existe para evitar.

Lo que falta de cada capacidad «en curso» se lee de la tabla «Lo que está a
medias» del manual funcional, para no tener ese texto escrito en dos sitios.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CATALOGO = RAIZ / "docs" / "catalogo" / "catalogo.yaml"
MANUAL = RAIZ / "docs" / "manual-3-funcionalidades.md"
SALIDA = RAIZ / "docs" / "hoja-estado.html"

# `| `CRM-…` Nombre | Qué hay | Qué falta |`
RE_MEDIAS = re.compile(r"^\| `(CRM-[\d.]+)` [^|]+\|([^|]+)\|([^|]+)\|", re.M)


def _notas_a_medias() -> dict[str, dict[str, str]]:
    if not MANUAL.exists():
        return {}
    texto = MANUAL.read_text(encoding="utf-8")
    return {
        cid: {"hay": _limpiar(hay), "falta": _limpiar(falta)}
        for cid, hay, falta in RE_MEDIAS.findall(texto)
    }


def _limpiar(texto: str) -> str:
    """Quita el énfasis de Markdown: aquí el resaltado lo pone el CSS."""
    return re.sub(r"\*\*(.+?)\*\*", r"\1", texto).strip()


def _datos() -> dict:
    import yaml

    catalogo = yaml.safe_load(CATALOGO.read_text(encoding="utf-8"))
    notas = _notas_a_medias()

    capacidades = []
    for modulo in catalogo["modulos"]:
        for seccion in modulo["secciones"]:
            for funcion in seccion["funciones"]:
                for cap in funcion["capacidades"]:
                    nota = notas.get(cap["id"], {})
                    capacidades.append(
                        {
                            "id": cap["id"],
                            "t": cap["t"],
                            "c": cap.get("c", "A"),
                            "fase": cap.get("fase", 0),
                            "svc": cap.get("svc", "core"),
                            "estado": cap.get("estado", "pendiente"),
                            "reutiliza": cap.get("reutiliza", ""),
                            "modulo": f"{modulo['id']} · {modulo['nombre']}",
                            "seccion": f"{seccion['id']} · {seccion['nombre']}",
                            "funcion": funcion["nombre"],
                            "hay": nota.get("hay", ""),
                            "falta": nota.get("falta", ""),
                        }
                    )

    return {
        "generado": date.today().isoformat(),
        "version": str(catalogo.get("version", "")),
        "criticidades": catalogo.get("criticidades", {}),
        "estados": catalogo.get("estados", {}),
        "fases": {str(k): v for k, v in (catalogo.get("fases") or {}).items()},
        "capacidades": capacidades,
        "eventos": catalogo.get("anexo_b_eventos", []),
        "restricciones": catalogo.get("restricciones_transversales", []),
    }


def _sin_fecha(html: str) -> str:
    """El HTML menos la fecha de generación.

    La fecha cambia todos los días, así que compararla haría que el gate fallara
    cada mañana sin que nada del proyecto hubiera cambiado — y un gate que falla
    por sistema se acaba ignorando, que es peor que no tenerlo.
    """
    return re.sub(r'"generado":"\d{4}-\d{2}-\d{2}"', '"generado":""', html)


def main() -> int:
    datos = _datos()
    plantilla = (Path(__file__).parent / "plantilla_hoja_estado.html").read_text(encoding="utf-8")
    html = plantilla.replace(
        "/*__DATOS__*/null", json.dumps(datos, ensure_ascii=False, separators=(",", ":"))
    )

    if "--check" in sys.argv:
        actual = SALIDA.read_text(encoding="utf-8") if SALIDA.exists() else ""
        if _sin_fecha(actual) != _sin_fecha(html):
            print(
                f"«{SALIDA.relative_to(RAIZ)}» está desfasada respecto del catálogo "
                "o del manual.\nRegenérala:  python scripts/gen_hoja_estado.py",
                file=sys.stderr,
            )
            return 1
        print("hoja de estado al día")
        return 0

    SALIDA.write_text(html, encoding="utf-8")
    total = len(datos["capacidades"])
    hechas = sum(1 for c in datos["capacidades"] if c["estado"] == "hecho")
    print(f"Escrito {SALIDA.relative_to(RAIZ)} ({total} capacidades, {hechas} hechas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
