#!/usr/bin/env python3
"""Los gates locales. Este repositorio no tiene CI (CRM-07.02.01.05).

Todo lo que en otro repositorio comprobaría un servidor al abrir un pull
request, aquí lo comprueba la máquina de quien desarrolla, antes de que el
cambio salga de ella.

    python scripts/preflight.py            # tier `fast`: segundos
    python scripts/preflight.py --tests    # fast + la suite entera
    python scripts/preflight.py --todo     # además, lo lento

Esa apuesta tiene una consecuencia que conviene tener presente: **los gates solo
protegen si están instalados**. En otra solución de la casa se encontró que
`.git/hooks/` solo tenía los `.sample`, o sea que ninguno había corrido nunca —y
en ese hueco entraron 218 cadenas sin traducir y un test de política de
seguridad que llevaba tiempo en rojo sin que nadie lo supiera.

Instalación, **obligatoria**:

    pre-commit install
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PY = sys.executable


@dataclass(frozen=True, slots=True)
class Gate:
    nombre: str
    comando: list[str]
    tier: str
    garantiza: str
    # Un gate opcional avisa y no bloquea cuando falta su herramienta. Es lo que
    # permite que la suite corra en una máquina sin Docker sin volverse
    # impasable —y por tanto sin que nadie acabe empujando con `--no-verify`.
    opcional: bool = False


GATES: list[Gate] = [
    Gate(
        "entorno",
        [PY, "scripts/check_environment.py", "--quiet"],
        "fast",
        "el árbol instalado cumple requirements*.txt",
    ),
    Gate(
        "ruff",
        [PY, "-m", "ruff", "check", "."],
        "fast",
        "estilo y errores estáticos de Python",
    ),
    Gate(
        "formato",
        [PY, "-m", "ruff", "format", "--check", "."],
        "fast",
        "formato uniforme",
    ),
    Gate(
        "env-example",
        [PY, "scripts/gen_env_example.py", "--check"],
        "fast",
        ".env.example refleja los Settings reales",
    ),
    Gate(
        "catalogo",
        [PY, "scripts/gen_catalogo_md.py", "--check"],
        "fast",
        "la matriz de trazabilidad está regenerada desde el catálogo",
    ),
    Gate(
        "hoja-estado",
        [PY, "scripts/gen_hoja_estado.py", "--check"],
        "fast",
        "la hoja web de estado refleja el catálogo y el manual",
    ),
    Gate(
        "arquitectura",
        [PY, "-m", "pytest", "tests/unit/test_contratos_arquitectura.py", "-q", "--no-header"],
        "fast",
        "servicios desacoplados, tenant_id obligatorio, permisos declarados",
    ),
    Gate(
        "trazabilidad",
        [PY, "-m", "pytest", "tests/unit/test_catalogo_trazabilidad.py", "-q", "--no-header"],
        "fast",
        "nada se declara hecho sin cita en el código y en el manual",
    ),
    Gate(
        "contrato-headless",
        [PY, "-m", "pytest", "tests/unit/test_headless_contract.py", "-q", "--no-header"],
        "fast",
        "todo servicio publica su contrato y toda ruta está documentada",
    ),
    Gate(
        "pruebas-sin-bd",
        [PY, "-m", "pytest", "-m", "not db", "-q", "--no-header"],
        "tests",
        "todo lo que no necesita infraestructura",
    ),
    Gate(
        "pruebas-con-bd",
        [PY, "-m", "pytest", "-m", "db", "-q", "--no-header"],
        "tests",
        "aislamiento entre tenants, motor de procesos y persistencia",
    ),
    Gate(
        "docs",
        [PY, "-m", "mkdocs", "build", "--strict", "--quiet"],
        "todo",
        "el manual construye y sus enlaces resuelven",
        opcional=True,
    ),
]


def _correr(gate: Gate) -> tuple[bool, float, str]:
    inicio = time.perf_counter()
    try:
        proceso = subprocess.run(
            gate.comando, cwd=RAIZ, capture_output=True, text=True, timeout=1800
        )
    except FileNotFoundError:
        return (gate.opcional, time.perf_counter() - inicio, "herramienta no instalada")
    except subprocess.TimeoutExpired:
        return (False, time.perf_counter() - inicio, "tiempo agotado (30 min)")
    salida = (proceso.stdout + proceso.stderr).strip()
    return (proceso.returncode == 0, time.perf_counter() - inicio, salida)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--tests", action="store_true", help="incluye la suite")
    parser.add_argument("--todo", action="store_true", help="incluye lo lento")
    parser.add_argument("--solo", default="", help="un gate por su nombre")
    args = parser.parse_args()

    tiers = {"fast"}
    if args.tests or args.todo:
        tiers.add("tests")
    if args.todo:
        tiers.add("todo")

    seleccionados = [
        g for g in GATES if (g.nombre == args.solo) or (not args.solo and g.tier in tiers)
    ]
    if not seleccionados:
        print(f"No hay ningún gate llamado «{args.solo}»", file=sys.stderr)
        return 2

    fallos: list[tuple[Gate, str]] = []
    omitidos: list[str] = []
    print(f"preflight — {len(seleccionados)} gates\n")

    for gate in seleccionados:
        ok, duracion, salida = _correr(gate)
        if ok and "no instalada" in salida:
            omitidos.append(gate.nombre)
            print(f"  ~ {gate.nombre:22} omitido ({salida})")
            continue
        marca = "✓" if ok else "✗"
        print(f"  {marca} {gate.nombre:22} {duracion:5.1f}s  {gate.garantiza}")
        if not ok:
            fallos.append((gate, salida))

    if omitidos:
        # Se dice qué NO se ha comprobado. Un gate omitido en silencio da una
        # falsa sensación de cobertura, que es peor que no tener el gate.
        print(f"\nNo comprobado: {', '.join(omitidos)}")

    if fallos:
        print(f"\n{len(fallos)} gate(s) en rojo:\n")
        for gate, salida in fallos:
            print(f"── {gate.nombre} " + "─" * (60 - len(gate.nombre)))
            print(salida[-3000:] or "(sin salida)")
            print()
        return 1

    print("\nTodo en verde.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
