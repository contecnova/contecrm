#!/usr/bin/env python3
"""Genera `.env.example` a partir de los `Settings` reales.

Escribirlo a mano garantiza que se quede desfasado: alguien añade un ajuste, no
actualiza el fichero, y al mes siguiente el `.env.example` describe un sistema
que ya no existe. Aquí se genera del código, con el comentario que acompaña a
cada campo en su mixin, así que la explicación de un ajuste vive **junto al
ajuste** y llega sola a la documentación.

    python scripts/gen_env_example.py            # escribe .env.example
    python scripts/gen_env_example.py --check    # falla si está desfasado (gate)

El modo `--check` es lo que engancha el gate de pre-commit: si añades un campo y
no regeneras, el commit te lo dice.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
MIXINS = RAIZ / "packages/crmcore/crmcore/config_parts"
SALIDA = RAIZ / ".env.example"

# Orden en que aparecen las secciones. Fijo y no alfabético: el orden en que se
# configura un despliegue tiene sentido (identidad del servicio, base de datos,
# tenancy…) y el alfabético lo destruye.
ORDEN = ["_app", "_db", "_tenancy", "_bus", "_auth", "_limits", "_obs", "_security"]

TITULOS = {
    "_app": "Identidad del servicio y red",
    "_db": "Base de datos y aislamiento en el motor",
    "_tenancy": "Multi-tenancy, cuotas y residencia",
    "_bus": "Bus de eventos, outbox y webhooks",
    "_auth": "Identidad: tokens, sesiones, MFA y federación",
    "_limits": "Límites, resiliencia y topes de proceso",
    "_obs": "Observabilidad: logs, métricas, trazas y auditoría",
    "_security": "Protección del dato: cifrado, secretos y cabeceras",
}


def _comentarios_previos(lineas: list[str], linea_campo: int) -> list[str]:
    """Comentarios inmediatamente encima de la definición de un campo."""
    comentarios: list[str] = []
    i = linea_campo - 2  # 0-based, y la línea anterior a la del campo
    while i >= 0:
        texto = lineas[i].strip()
        if texto.startswith("#"):
            comentarios.insert(0, texto.lstrip("#").strip())
            i -= 1
        elif not texto:
            break
        else:
            break
    # Las cabeceras de bloque (`── Pool ──`) no describen el campo concreto: se
    # quitan para que el comentario que quede sea el suyo.
    return [c for c in comentarios if not c.startswith("──")]


def _valor_ejemplo(nodo: ast.AnnAssign, nombre: str) -> str:
    """Valor de ejemplo. Nunca un secreto real, ni siquiera de desarrollo."""
    if any(p in nombre for p in ("secret", "password", "key", "token")):
        if "url" in nombre:
            return ""
        return "CAMBIAME"
    if nodo.value is None:
        return ""
    try:
        if isinstance(nodo.value, ast.Call):  # Field(default, ...)
            if nodo.value.args:
                return str(ast.literal_eval(nodo.value.args[0]))
            for kw in nodo.value.keywords:
                if kw.arg == "default":
                    return str(ast.literal_eval(kw.value))
            return ""
        valor = ast.literal_eval(nodo.value)
        if isinstance(valor, bool):
            return "true" if valor else "false"
        return "" if valor is None else str(valor)
    except (ValueError, TypeError, SyntaxError):
        return ""


def generar() -> str:
    partes: list[str] = [
        "# ═══════════════════════════════════════════════════════════════════",
        "#  contecrm — configuración",
        "# ═══════════════════════════════════════════════════════════════════",
        "#",
        "# GENERADO por `python scripts/gen_env_example.py`. No se edita a mano:",
        "# la explicación de cada ajuste vive junto a su campo en",
        "# `packages/crmcore/crmcore/config_parts/*.py`, y de ahí sale esto. Si",
        "# editas aquí, el siguiente `--check` lo revierte.",
        "#",
        "# Copia este fichero a `.env` y cambia lo que marque CAMBIAME. `.env`",
        "# NUNCA se commitea: está en .gitignore.",
        "#",
        "# Todo ajuste es una variable de entorno. Los que además se pueden",
        "# cambiar en caliente por tenant, sin reiniciar, están en",
        "# `crmcore/runtime/keys.py` y se editan desde la consola de",
        "# administración: ahí el valor de aquí es solo el punto de partida.",
        "",
    ]

    for modulo in ORDEN:
        ruta = MIXINS / f"{modulo}.py"
        if not ruta.exists():
            continue
        fuente = ruta.read_text(encoding="utf-8")
        lineas = fuente.splitlines()
        arbol = ast.parse(fuente)

        partes.append("")
        partes.append(f"# ── {TITULOS.get(modulo, modulo)} " + "─" * max(0, 60 - len(TITULOS.get(modulo, modulo))))
        partes.append("")

        for clase in [n for n in arbol.body if isinstance(n, ast.ClassDef)]:
            for nodo in clase.body:
                if not isinstance(nodo, ast.AnnAssign) or not isinstance(nodo.target, ast.Name):
                    continue
                nombre = nodo.target.id
                if nombre.startswith("_") or nombre == "model_config":
                    continue
                for comentario in _comentarios_previos(lineas, nodo.lineno):
                    partes.append(f"# {comentario}")
                partes.append(f"{nombre.upper()}={_valor_ejemplo(nodo, nombre)}")
                partes.append("")

    return "\n".join(partes).rstrip() + "\n"


def main() -> int:
    contenido = generar()
    if "--check" in sys.argv:
        actual = SALIDA.read_text(encoding="utf-8") if SALIDA.exists() else ""
        if actual != contenido:
            print(
                "`.env.example` está desfasado respecto de los Settings.\n"
                "Regenéralo:  python scripts/gen_env_example.py",
                file=sys.stderr,
            )
            return 1
        print(".env.example al día")
        return 0
    SALIDA.write_text(contenido, encoding="utf-8")
    print(f"Escrito {SALIDA.relative_to(RAIZ)} ({contenido.count(chr(10))} líneas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
