#!/usr/bin/env python3
"""Genera la referencia de ajustes del manual.

    python scripts/gen_referencia_ajustes.py          # escribe el manual VI
    python scripts/gen_referencia_ajustes.py --check  # gate

Cada ajuste tiene **dos nombres**: la variable de entorno (`BULK_MAX_ITEMS`) y
la clave con la que aparece en la consola de administración (`bulk_max_items`).
Documentar solo uno es lo que hace que quien copia la clave del panel no
encuentre nada en el manual, así que aquí salen los dos.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
MIXINS = RAIZ / "packages" / "crmcore" / "crmcore" / "config_parts"
SALIDA = RAIZ / "docs" / "manual-6-referencia-ajustes.md"

TITULOS = {
    "_app": "Identidad del servicio y red",
    "_db": "Base de datos y aislamiento",
    "_tenancy": "Multi-tenancy, cuotas y residencia",
    "_bus": "Bus de eventos, outbox y webhooks",
    "_auth": "Identidad: tokens, sesiones, MFA",
    "_limits": "Límites, resiliencia y topes de proceso",
    "_obs": "Observabilidad y auditoría",
    "_security": "Protección del dato",
}
ORDEN = ["_app", "_db", "_tenancy", "_bus", "_auth", "_limits", "_obs", "_security"]


def _comentario(lineas: list[str], linea_campo: int) -> str:
    comentarios: list[str] = []
    i = linea_campo - 2
    while i >= 0:
        texto = lineas[i].strip()
        if texto.startswith("#"):
            comentarios.insert(0, texto.lstrip("#").strip())
            i -= 1
        else:
            break
    utiles = [c for c in comentarios if c and not c.startswith("──")]
    return " ".join(utiles)


def _rango(nodo: ast.AnnAssign) -> str:
    if not isinstance(nodo.value, ast.Call):
        return ""
    limites = {}
    for kw in nodo.value.keywords:
        if kw.arg in ("ge", "le", "gt", "lt"):
            try:
                limites[kw.arg] = ast.literal_eval(kw.value)
            except (ValueError, TypeError):
                pass
    if "ge" in limites and "le" in limites:
        return f"{limites['ge']}–{limites['le']}"
    if "ge" in limites:
        return f"≥ {limites['ge']}"
    if "le" in limites:
        return f"≤ {limites['le']}"
    return ""


def _default(nodo: ast.AnnAssign, nombre: str) -> str:
    if any(p in nombre for p in ("secret", "password", "key")) and "url" not in nombre:
        return "*(secreto)*"
    if nodo.value is None:
        return ""
    try:
        if isinstance(nodo.value, ast.Call):
            if nodo.value.args:
                return f"`{ast.literal_eval(nodo.value.args[0])}`"
            for kw in nodo.value.keywords:
                if kw.arg == "default":
                    return f"`{ast.literal_eval(kw.value)}`"
            return ""
        valor = ast.literal_eval(nodo.value)
        return "*(vacío)*" if valor in ("", None) else f"`{valor}`"
    except (ValueError, TypeError, SyntaxError):
        return ""


def generar() -> str:
    from crmcore.runtime.keys import CLAVES

    partes = [
        "# Manual VI — Referencia de ajustes",
        "",
        "> **Generado** por `python scripts/gen_referencia_ajustes.py` desde los",
        "> propios `Settings`. No se edita a mano: la explicación de cada ajuste",
        "> vive junto a su campo en `packages/crmcore/crmcore/config_parts/`.",
        "",
        "Cada ajuste se configura como **variable de entorno** (en `.env` o en el",
        "entorno del proceso). Los marcados con 🔥 se pueden cambiar además",
        "**en caliente por tenant** desde la consola de administración, sin",
        "reiniciar: ahí el valor de `.env` es solo el punto de partida.",
        "",
    ]

    # El recuento va antes de las tablas, no interpolado por índice: la versión
    # anterior lo insertaba en una posición calculada y acababa en medio de la
    # primera sección.
    campos = _contar_campos()
    partes += [
        f"**{campos} ajustes** en total, de los cuales **{len(CLAVES)}** son "
        "editables en caliente por tenant.",
        "",
    ]

    total = 0
    for modulo in ORDEN:
        ruta = MIXINS / f"{modulo}.py"
        if not ruta.exists():
            continue
        fuente = ruta.read_text(encoding="utf-8")
        lineas = fuente.splitlines()
        arbol = ast.parse(fuente)

        partes += [
            f"## {TITULOS.get(modulo, modulo)}",
            "",
            "| Variable de entorno | Clave en caliente | Defecto | Rango | Qué hace |",
            "|---|---|---|---|---|",
        ]
        for clase in [n for n in arbol.body if isinstance(n, ast.ClassDef)]:
            for nodo in clase.body:
                if not isinstance(nodo, ast.AnnAssign) or not isinstance(nodo.target, ast.Name):
                    continue
                nombre = nodo.target.id
                if nombre.startswith("_") or nombre == "model_config":
                    continue
                total += 1
                caliente = "🔥 `%s`" % nombre if nombre in CLAVES else "—"
                descripcion = _comentario(lineas, nodo.lineno).replace("|", "\\|")
                # Se recorta la explicación larga: el manual es una tabla de
                # consulta, y el porqué completo está en el código, enlazado.
                if len(descripcion) > 300:
                    descripcion = descripcion[:297].rsplit(" ", 1)[0] + "…"
                partes.append(
                    f"| `{nombre.upper()}` | {caliente} | {_default(nodo, nombre)} "
                    f"| {_rango(nodo)} | {descripcion} |"
                )
        partes.append("")

    return "\n".join(partes).rstrip() + "\n"


def _contar_campos() -> int:
    """Cuántos ajustes hay declarados, sin repetir el recorrido de las tablas."""
    n = 0
    for modulo in ORDEN:
        ruta = MIXINS / f"{modulo}.py"
        if not ruta.exists():
            continue
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        for clase in [c for c in arbol.body if isinstance(c, ast.ClassDef)]:
            n += sum(
                1
                for nodo in clase.body
                if isinstance(nodo, ast.AnnAssign)
                and isinstance(nodo.target, ast.Name)
                and not nodo.target.id.startswith("_")
                and nodo.target.id != "model_config"
            )
    return n


def main() -> int:
    contenido = generar()
    if "--check" in sys.argv:
        actual = SALIDA.read_text(encoding="utf-8") if SALIDA.exists() else ""
        if actual != contenido:
            print(
                "La referencia de ajustes está desfasada.\n"
                "Regenérala:  python scripts/gen_referencia_ajustes.py",
                file=sys.stderr,
            )
            return 1
        print("referencia de ajustes al día")
        return 0
    SALIDA.write_text(contenido, encoding="utf-8")
    print(f"Escrito {SALIDA.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
