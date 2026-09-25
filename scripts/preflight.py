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
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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
    # Un gate EXCLUSIVO no puede correr a la vez que otro exclusivo: levanta un
    # Postgres embebido, y dos a la vez se cuelgan esperándose. Los demás sí
    # corren en paralelo entre ellos y con el exclusivo de turno.
    exclusivo: bool = False


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
        "procesos",
        [PY, "scripts/gen_procesos.py", "--check"],
        "todo",
        "el documento de procesos dice lo que el código hace de verdad",
    ),
    Gate(
        "arquitectura",
        [PY, "-m", "pytest", "tests/unit/test_contratos_arquitectura.py", "-q", "--no-header"],
        "fast",
        "servicios desacoplados, tenant_id obligatorio, permisos declarados",
    ),
    Gate(
        "atributos",
        [PY, "scripts/comprobar_atributos.py"],
        "tests",
        "nadie lee un campo que no existe (lo que en ejecución es un 500)",
    ),
    Gate(
        "acciones",
        [
            PY,
            "-m",
            "pytest",
            "tests/unit/test_acciones_alcanzables.py",
            "tests/unit/test_rutas_del_front.py",
            "tests/unit/test_catalogo_eventos.py",
            "-q",
            "--no-header",
        ],
        "tests",
        "lo que la API deja hacer se alcanza desde el front, y lo que emite se puede recibir",
    ),
    Gate(
        "trazabilidad",
        [PY, "-m", "pytest", "tests/unit/test_catalogo_trazabilidad.py", "-q", "--no-header"],
        "fast",
        "nada se declara hecho sin cita en el código y en el manual",
    ),
    Gate(
        "manuales",
        [PY, "-m", "pytest", "tests/unit/test_manuales.py", "-q", "--no-header"],
        "fast",
        "los dos manuales cubren todo y no describen lo que ya no existe",
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
        exclusivo=True,
    ),
    Gate(
        "migraciones",
        [PY, "scripts/migraciones_locales.py", "comprobar"],
        "tests",
        "ningún modelo cambiado se ha quedado sin su migración",
        exclusivo=True,
    ),
    Gate(
        "front",
        ["npm", "--prefix", "frontend", "run", "verificar"],
        "tests",
        "el front oficial tipa, cumple sus reglas, pasa sus pruebas y construye",
        # Opcional porque no toda máquina que toca el backend tiene Node
        # instalado, y negarse a correr el preflight por eso convertiría el
        # ciclo rápido en una instalación obligatoria. Si Node está, el gate
        # corre y falla como cualquier otro.
        opcional=True,
    ),
    Gate(
        "docs",
        [PY, "-m", "mkdocs", "build", "--strict", "--quiet"],
        "todo",
        "el manual construye y sus enlaces resuelven",
        opcional=True,
    ),
]


# Lo que puede tardar el preflight ENTERO, en segundos.
#
# No es una preferencia: es la condición para que exista. Un preflight que pasa
# de tres minutos deja de correrse —se pospone «para luego», y luego se empuja
# sin él— y un gate que no se corre no garantiza nada, con lo que el coste se
# paga entero y el beneficio no llega.
#
# Cuando esto falla, lo que se arregla es el gate lento, no la comprobación. La
# primera vez que se midió, 195 de los 200 segundos de las pruebas con base de
# datos se iban en crear y tirar un esquema de 98 tablas **por prueba**; pasar a
# aislar por transacción lo dejó en 11 segundos sin quitar ni una prueba.
#
# Se mide el RELOJ DE PARED, no la suma de los gates. Antes se sumaba, y eso
# medía trabajo hecho en vez de tiempo esperado: con los gates corriendo en
# paralelo, sumar decía tres minutos y medio donde quien lo lanzaba esperaba
# minuto y medio. Lo que hace que un preflight deje de correrse es lo que se
# tarda en volver al teclado.
PRESUPUESTO_S = 180.0

# Lo que cuesta de memoria el gate más gordo, medido: los que recorren los trece
# servicios construyen las trece aplicaciones FastAPI y se quedan en medio giga.
COSTE_POR_GATE_MB = 500


def _memoria_disponible_mb() -> int | None:
    """Memoria que se puede usar sin empezar a paginar, o `None` si no se sabe."""
    try:
        if sys.platform == "linux":
            for linea in Path("/proc/meminfo").read_text().splitlines():
                if linea.startswith("MemAvailable:"):
                    return int(linea.split()[1]) // 1024
            return None
        if sys.platform == "darwin":
            salida = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=10).stdout
            pagina = 4096
            paginas: dict[str, int] = {}
            for linea in salida.splitlines():
                if "page size of" in linea:
                    pagina = int(linea.split("page size of")[1].split()[0])
                elif ":" in linea:
                    clave, _, valor = linea.partition(":")
                    paginas[clave.strip()] = int(valor.strip().rstrip("."))
            # Libre más inactiva: la inactiva se puede reclamar sin paginar.
            libres = paginas.get("Pages free", 0) + paginas.get("Pages inactive", 0)
            return libres * pagina // (1024 * 1024)
    except Exception:  # noqa: BLE001 — no saberlo no puede impedir el preflight
        return None
    return None


def _paralelos() -> int:
    """Cuántos gates a la vez, limitado por lo que de verdad escasea.

    **La memoria, no los núcleos.** Con seis a la vez cada gate pasó de 14 s a
    112 s: no era la CPU —diez núcleos y el trabajo es de uno cada uno— era que
    Docker se lleva la mitad de la RAM de esta máquina y seis procesos de medio
    giga la metían a paginar. Un preflight que pagina tarda más en paralelo que
    en serie, que es lo contrario de lo que se buscaba.

    Se mide en vez de fijarse: la misma cifra no vale para una máquina con la
    pila levantada y otra sin ella, y un número escrito aquí sería el de la
    máquina de quien lo escribió.
    """
    por_cpu = max(2, min(6, (os.cpu_count() or 4) - 1))
    disponible = _memoria_disponible_mb()
    if disponible is None:
        return por_cpu
    # Se deja un gate de margen para el resto del sistema.
    por_memoria = max(1, disponible // COSTE_POR_GATE_MB - 1)
    return max(1, min(por_cpu, por_memoria))


PARALELOS = _paralelos()


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

    # Los exclusivos se turnan entre ellos; el resto va en paralelo. El cerrojo
    # es lo único que los separa: sin él, dos Postgres embebidos a la vez se
    # quedan esperándose y el preflight no termina nunca.
    turno = threading.Lock()

    def _ejecutar(gate: Gate) -> tuple[bool, float, str]:
        if not gate.exclusivo:
            return _correr(gate)
        with turno:
            return _correr(gate)

    reloj = time.perf_counter()
    with ThreadPoolExecutor(max_workers=PARALELOS) as pool:
        resultados = list(pool.map(_ejecutar, seleccionados))
    total = time.perf_counter() - reloj

    # Se imprime en el orden en que están declarados, no en el que terminaron:
    # el informe tiene que ser el mismo dos veces seguidas para poder compararlo.
    for gate, (ok, duracion, salida) in zip(seleccionados, resultados, strict=True):
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

    if total > PRESUPUESTO_S:
        print(
            f"\nTodo en verde, PERO el preflight tarda {total:.0f}s y el "
            f"presupuesto son {PRESUPUESTO_S:.0f}s.\n\n"
            "Un preflight que pasa de tres minutos deja de correrse, y un gate "
            "que no se corre no garantiza nada — con lo que el coste se paga\n"
            "entero y el beneficio no llega. Los tiempos de arriba dicen dónde "
            "se va: se arregla el gate lento, no se quita la comprobación.\n"
            "(Es tiempo de reloj, con los gates en paralelo: el número de arriba "
            "de cada uno es lo que tardó él, y suman más.)"
        )
        return 1

    print(
        f"\nTodo en verde. {total:.0f}s de reloj de {PRESUPUESTO_S:.0f}s de "
        f"presupuesto, con hasta {PARALELOS} gates a la vez."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
