#!/usr/bin/env python3
"""Genera la vista navegable del catálogo y la matriz de trazabilidad.

    python scripts/gen_catalogo_md.py           # escribe docs/catalogo/*.md
    python scripts/gen_catalogo_md.py --check   # falla si está desfasado (gate)

Se genera y no se escribe a mano por la misma razón que `.env.example`: una
matriz de trazabilidad mantenida a mano dice lo que alguien creyó que había
hecho el día que la tocó por última vez.

Salidas:

  * `estado.md` — todas las capacidades por módulo, con estado, fase, servicio
    y de dónde se reutiliza. Es la matriz de evaluación del catálogo original,
    con las columnas que pedía.
  * `resumen.md` — el recuento por módulo, criticidad y fase. Es lo que se mira
    para saber por dónde va el proyecto sin leer 527 filas.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[1]
CATALOGO = RAIZ / "docs" / "catalogo" / "catalogo.yaml"
DESTINO = RAIZ / "docs" / "catalogo"

ICONO = {"hecho": "✅", "en-curso": "🔧", "pendiente": "⬜"}
NOMBRE_CRIT = {"C": "Core", "A": "Avanzado", "D": "Diferencial"}


def _capacidades(catalogo: dict) -> list[dict]:
    return [
        c
        for m in catalogo["modulos"]
        for s in m["secciones"]
        for f in s["funciones"]
        for c in f["capacidades"]
    ]


def estado_md(catalogo: dict) -> str:
    partes = [
        "# Estado del catálogo funcional",
        "",
        "> **Generado** por `python scripts/gen_catalogo_md.py` desde",
        "> [`catalogo.yaml`](catalogo.yaml). No se edita a mano.",
        "",
        "Una capacidad solo se marca **hecho** cuando se cumplen las tres cosas:",
        "el código la implementa, hay una prueba o un sitio del código que la cita",
        "por su identificador, y está en el manual. Lo comprueba",
        "`tests/unit/test_catalogo_trazabilidad.py`, así que este documento no",
        "puede decir que algo está hecho si no lo está.",
        "",
    ]

    total = Counter(c["estado"] for c in _capacidades(catalogo))
    partes += [
        f"**{len(_capacidades(catalogo))} capacidades**: "
        + " · ".join(f"{ICONO[e]} {n} {e}" for e, n in sorted(total.items())),
        "",
    ]

    for modulo in catalogo["modulos"]:
        capacidades = [
            c for s in modulo["secciones"] for f in s["funciones"] for c in f["capacidades"]
        ]
        cuenta = Counter(c["estado"] for c in capacidades)
        partes += [
            f"## Módulo {modulo['id']} — {modulo['nombre']}",
            "",
            f"{len(capacidades)} capacidades · "
            + " · ".join(f"{ICONO[e]} {n}" for e, n in sorted(cuenta.items())),
            "",
        ]
        for seccion in modulo["secciones"]:
            partes += [f"### {seccion['id']} {seccion['nombre']}", ""]
            for funcion in seccion["funciones"]:
                partes += [
                    f"#### {funcion['id']} · {funcion['nombre']}",
                    "",
                    "| ID | Capacidad | Crit. | Fase | Servicio | Estado | Se reutiliza de |",
                    "|---|---|:-:|:-:|---|:-:|---|",
                ]
                for c in funcion["capacidades"]:
                    reutiliza = c.get("reutiliza", "") or "—"
                    partes.append(
                        f"| `{c['id']}` | {c['t']} | {c['c']} | {c['fase']} | "
                        f"{c['svc']} | {ICONO[c['estado']]} | {reutiliza} |"
                    )
                partes.append("")
    return "\n".join(partes).rstrip() + "\n"


def resumen_md(catalogo: dict) -> str:
    capacidades = _capacidades(catalogo)
    partes = [
        "# Resumen del catálogo",
        "",
        "> **Generado** por `python scripts/gen_catalogo_md.py`. No se edita a mano.",
        "",
        "## Por módulo",
        "",
        "| Módulo | Capacidades | Hecho | En curso | Pendiente |",
        "|---|--:|--:|--:|--:|",
    ]
    for modulo in catalogo["modulos"]:
        caps = [c for s in modulo["secciones"] for f in s["funciones"] for c in f["capacidades"]]
        cuenta = Counter(c["estado"] for c in caps)
        partes.append(
            f"| {modulo['id']} — {modulo['nombre']} | {len(caps)} | "
            f"{cuenta.get('hecho', 0)} | {cuenta.get('en-curso', 0)} | "
            f"{cuenta.get('pendiente', 0)} |"
        )

    partes += ["", "## Por criticidad", "", "| Criticidad | Total | Hecho |", "|---|--:|--:|"]
    for crit in ("C", "A", "D"):
        caps = [c for c in capacidades if c["c"] == crit]
        hechos = sum(1 for c in caps if c["estado"] == "hecho")
        partes.append(f"| {crit} — {NOMBRE_CRIT[crit]} | {len(caps)} | {hechos} |")

    partes += [
        "",
        "## Por fase",
        "",
        "| Fase | Alcance | Capacidades | Hecho |",
        "|---|---|--:|--:|",
    ]
    for numero, fase in sorted(catalogo["fases"].items()):
        caps = [c for c in capacidades if c["fase"] == numero]
        hechos = sum(1 for c in caps if c["estado"] == "hecho")
        partes.append(
            f"| {numero} · {fase['nombre']} | {fase['alcance']} | {len(caps)} | {hechos} |"
        )

    partes += [
        "",
        "## Reutilización",
        "",
        f"**{sum(1 for c in capacidades if c.get('reutiliza'))} de {len(capacidades)}** "
        "capacidades tienen una implementación de referencia en otra solución de la "
        "casa. El inventario medido está en [REUTILIZACION.md](../REUTILIZACION.md).",
        "",
    ]
    origenes = Counter(str(c["reutiliza"]).split(":")[0] for c in capacidades if c.get("reutiliza"))
    partes += ["| Origen | Capacidades |", "|---|--:|"]
    for origen, n in origenes.most_common():
        partes.append(f"| {origen} | {n} |")
    return "\n".join(partes).rstrip() + "\n"


def main() -> int:
    catalogo = yaml.safe_load(CATALOGO.read_text(encoding="utf-8"))
    salidas = {
        DESTINO / "estado.md": estado_md(catalogo),
        DESTINO / "resumen.md": resumen_md(catalogo),
    }

    if "--check" in sys.argv:
        for ruta, contenido in salidas.items():
            actual = ruta.read_text(encoding="utf-8") if ruta.exists() else ""
            if actual != contenido:
                print(
                    f"«{ruta.relative_to(RAIZ)}» está desfasado respecto del catálogo.\n"
                    "Regenéralo:  python scripts/gen_catalogo_md.py",
                    file=sys.stderr,
                )
                return 1
        print("catálogo y documentación al día")
        return 0

    for ruta, contenido in salidas.items():
        ruta.write_text(contenido, encoding="utf-8")
        print(f"Escrito {ruta.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
