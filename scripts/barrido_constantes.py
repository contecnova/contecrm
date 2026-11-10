#!/usr/bin/env python3
"""Barrido de constantes: candidatos a número mágico o lista de negocio.

    .venv/bin/python scripts/barrido_constantes.py .
    .venv/bin/python scripts/barrido_constantes.py . --detalle parametro

Recorre services/** y packages/crmcore/crmcore/** —sin pruebas, ni ajustes.py,
ni config_parts, ni runtime/keys.py, ni config.py— y clasifica por AST:

- plazo: `timedelta(days|weeks|hours=N)` con N literal distinto de 0 y 1;
- parametro: defecto numérico de un parámetro con nombre de negocio (tope,
  umbral, dias, horas, pct, margen, ventana, fallos…) que no sea técnico;
- comparacion: un número no trivial dentro de una comparación;
- constante_num: `MAYUSCULAS = número` a nivel de módulo;
- lista_str: `MAYUSCULAS = (\"a\", \"b\")` (tupla, lista, set o frozenset de textos);
- semilla_vocabulario: una lista_str que se pasa a `vocabulario.registrar`: son
  los valores de fábrica de un vocabulario que la empresa edita, no un límite
  (desde el 10-11-2026 se cuentan aparte).

**Da candidatos, no veredictos.** Cada uno se mira a mano: un `limite=50` de
un listado es paginación, un `VERSION_SOBRE = 1` es protocolo y una lista de
estados de una máquina del sistema es vocabulario. No es un gate.
"""

import ast
import collections
import pathlib
import re
import sys

raiz = pathlib.Path(sys.argv[1])
detalle = sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == "--detalle" else None
EXCLUIR = re.compile(
    r"(/tests?/|test_|/ajustes\.py$|/config_parts/|/runtime/keys\.py$|/config\.py$|__pycache__)"
)
TRIVIAL = {0, 1, -1, 2, 100, 1000, 1024, 60, 3600, 24, 7, 0.5}
NOMBRE_NEGOCIO = re.compile(
    r"(tope|max|min|umbral|limite|dias|horas|minutos|pct|porcentaje|plazo|margen|descuento|ventana|reintentos|fallos|edad|caduc|venc)",
    re.I,
)
TECNICO = re.compile(
    r"(timeout|_s$|segundos|bytes|_kb|_mb|longitud|len|ancho|alto|puerto|port|pool|chunk|lote|batch|page|pagina|limit$|offset)",
    re.I,
)

cats = collections.Counter()
por_serv = collections.Counter()
filas = []


def serv(p):
    parts = p.relative_to(raiz).parts
    return parts[1] if parts[0] == "services" else "crmcore"


def num(n):
    return (
        isinstance(n, ast.Constant)
        and isinstance(n.value, (int, float))
        and not isinstance(n.value, bool)
    )


def nota(cat, p, n, txt):
    cats[cat] += 1
    por_serv[(serv(p), cat)] += 1
    filas.append((cat, f"{p.relative_to(raiz)}:{n.lineno}", txt))


ficheros = [
    p
    for base in ("services", "packages/crmcore/crmcore")
    for p in (raiz / base).rglob("*.py")
    if not EXCLUIR.search(str(p))
]
for p in ficheros:
    try:
        arbol = ast.parse(p.read_text())
    except Exception:
        continue
    # Las listas que siembran un vocabulario editable (`vocabulario.registrar`).
    semillas = {
        a.id
        for n in ast.walk(arbol)
        if isinstance(n, ast.Call)
        and getattr(n.func, "attr", "") == "registrar"
        and getattr(getattr(n.func, "value", None), "id", "") == "vocabulario"
        for a in n.args[1:2]
        if isinstance(a, ast.Name)
    }
    for n in ast.walk(arbol):
        # 1. plazos: timedelta(days=30)
        if (
            isinstance(n, ast.Call)
            and getattr(n.func, "attr", getattr(n.func, "id", "")) == "timedelta"
        ):
            for k in n.keywords:
                if (
                    num(k.value)
                    and k.value.value not in (0, 1)
                    and k.arg in ("days", "weeks", "hours")
                ):
                    nota("plazo", p, n, f"timedelta({k.arg}={k.value.value})")
        # 2. defaults de parámetros con nombre de negocio
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = n.args
            pares = list(zip(a.args[len(a.args) - len(a.defaults) :], a.defaults, strict=False)) + [
                (x, d) for x, d in zip(a.kwonlyargs, a.kw_defaults, strict=False) if d is not None
            ]
            for arg, d in pares:
                if (
                    num(d)
                    and NOMBRE_NEGOCIO.search(arg.arg)
                    and not TECNICO.search(arg.arg)
                    and d.value not in (0, 1)
                ):
                    nota("parametro", p, n, f"{n.name}({arg.arg}={d.value})")
        # 3. umbrales en comparaciones
        if isinstance(n, ast.Compare):
            for c in [n.left, *n.comparators]:
                if num(c) and c.value not in TRIVIAL and abs(c.value) < 10**6:
                    nota("comparacion", p, n, ast.unparse(n)[:90])
        # 4/5. constantes de módulo
        if isinstance(n, ast.Module):
            for s in n.body:
                if isinstance(s, (ast.Assign, ast.AnnAssign)):
                    objs = s.targets if isinstance(s, ast.Assign) else [s.target]
                    nombre = getattr(objs[0], "id", "")
                    v = s.value
                    if not nombre or not nombre.lstrip("_").isupper() or v is None:
                        continue
                    if num(v) and not TECNICO.search(nombre):
                        nota("constante_num", p, s, f"{nombre} = {v.value}")
                    elif (
                        isinstance(v, ast.Call)
                        and getattr(v.func, "id", "") in ("frozenset", "set", "tuple")
                        and v.args
                    ):
                        v = v.args[0]
                    if (
                        isinstance(v, (ast.Tuple, ast.List, ast.Set))
                        and v.elts
                        and all(
                            isinstance(e, ast.Constant) and isinstance(e.value, str) for e in v.elts
                        )
                    ):
                        nota(
                            "semilla_vocabulario" if nombre in semillas else "lista_str",
                            p,
                            s,
                            f"{nombre} = ({len(v.elts)} valores) {ast.unparse(v)[:70]}",
                        )

print(f"ficheros recorridos: {len(ficheros)}")
for c, k in cats.most_common():
    print(f"{c:15} {k}")
print("\npor servicio:")
servs = sorted({s for s, _ in por_serv})
cs = [c for c, _ in cats.most_common()]
print("servicio".ljust(14) + "".join(c[:12].rjust(14) for c in cs))
for s in servs:
    print(s.ljust(14) + "".join(str(por_serv[(s, c)]).rjust(14) for c in cs))
if detalle:
    print()
    for c, donde, t in filas:
        if c == detalle:
            print(f"{donde}  {t}")
