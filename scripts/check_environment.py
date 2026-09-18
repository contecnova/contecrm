#!/usr/bin/env python3
"""¿El entorno instalado es el que declaran los manifiestos?

    python scripts/check_environment.py          # informe
    python scripts/check_environment.py --quiet  # modo gate

Va **el primero** de todos los gates, y es deliberado: todos los demás dan por
hecho el entorno en el que corren. Si el árbol instalado no es el que declaran
`requirements*.txt`, lo que midan es otra cosa.

En otra solución de la casa, la primera vez que se comprobó esto salieron 12 de
50 restricciones violadas y las dos dependencias de desarrollo sin instalar —con
ellas, 1.343 pruebas que no podían ejecutarse—. O sea: el sistema que sustituye
a la CI llevaba tiempo sin poder funcionar, y ningún gate podía verlo porque
todos daban por hecho su propio entorno.
"""

from __future__ import annotations

import re
import sys
from importlib import metadata
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
MANIFIESTOS = ["requirements.txt", "requirements-dev.txt"]

RE_REQ = re.compile(r"^([A-Za-z0-9_.\-]+)(\[[^\]]+\])?\s*([=<>!~]=?)\s*([0-9][\w.\-]*)")


def _normalizar(nombre: str) -> str:
    return nombre.lower().replace("_", "-")


def _comparar(instalada: str, operador: str, exigida: str) -> bool:
    from packaging.version import InvalidVersion, Version

    try:
        v_inst, v_exig = Version(instalada), Version(exigida)
    except InvalidVersion:
        return True  # versión no comparable: no se bloquea por ella
    return {
        "==": v_inst == v_exig,
        ">=": v_inst >= v_exig,
        "<=": v_inst <= v_exig,
        ">": v_inst > v_exig,
        "<": v_inst < v_exig,
        "!=": v_inst != v_exig,
        "~=": v_inst >= v_exig,
    }.get(operador, True)


def main() -> int:
    silencioso = "--quiet" in sys.argv
    problemas: list[str] = []
    comprobadas = 0

    for manifiesto in MANIFIESTOS:
        ruta = RAIZ / manifiesto
        if not ruta.exists():
            continue
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            linea = linea.split("#")[0].strip()
            if not linea:
                continue
            coincidencia = RE_REQ.match(linea)
            if not coincidencia:
                continue
            nombre, _extra, operador, exigida = coincidencia.groups()
            comprobadas += 1
            try:
                instalada = metadata.version(_normalizar(nombre))
            except metadata.PackageNotFoundError:
                problemas.append(f"{nombre}: declarada en {manifiesto} y NO instalada")
                continue
            if not _comparar(instalada, operador, exigida):
                problemas.append(
                    f"{nombre}: instalada {instalada}, {manifiesto} exige {operador}{exigida}"
                )

    if problemas:
        print(
            f"Entorno distinto del declarado ({len(problemas)} de {comprobadas}):", file=sys.stderr
        )
        for p in problemas:
            print(f"  - {p}", file=sys.stderr)
        print(
            "\nInstala lo declarado antes de fiarte de ningún otro gate:\n"
            "  pip install -r requirements.txt -r requirements-dev.txt",
            file=sys.stderr,
        )
        return 1

    if not silencioso:
        print(f"Entorno conforme: {comprobadas} restricciones comprobadas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
