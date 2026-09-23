#!/usr/bin/env python3
"""Ningún acceso a un atributo que no existe (`mypy --attr-defined`).

    python scripts/comprobar_atributos.py

**Por qué solo este código de error.** El árbol tiene más de mil avisos de mypy,
casi todos de `UUID | None` frente a `UUID`, que son ruido en un repositorio que
aún se está escribiendo. `attr-defined` no es ruido: es escribir el nombre de un
campo que no existe, y Python no lo dice hasta que esa línea corre. Cuando corre,
es un 500.

Encontró estos, todos reales y todos invisibles hasta que alguien abría la
pantalla:

  * `principal.usuario_id` en 34 sitios de nueve servicios — se llama `id`. La
    pantalla de estado, la de cuadros de mando y la consola de agente daban 500.
  * `tenant.plan_codigo` — se llama `plan`.
  * `ConsentimientoCanal.caduca_at` — la columna no existía, así que la lista de
    renovaciones pendientes nunca funcionó y la caducidad del consentimiento era
    decorativa.
  * `crmcore.db.session.sesion_admin` — no existe; toda llamada a un proveedor de
    IA moría con ImportError.
  * `crmcore.audit.modelos.EntradaAuditoria` — se llama `ApunteAuditoria`. El
    control de GRC que cuenta apuntes de auditoría no se pudo evaluar nunca.
  * `Settings.jwt_secret` — se llama `secret_key`. Toda llamada gRPC autenticada
    moría antes de validar el token.

**Lo que se calla y por qué.** mypy no sabe resolver atributos sobre un
parámetro declarado `modelo: type` —el patrón de los ayudantes genéricos, como
el listado o el archivado— ni sobre la clase base de una jerarquía cuyos hijos
sí los tienen. Esos avisos se filtran por su forma, no por fichero y línea: una
lista de excepciones por línea se queda obsoleta al primer cambio y acaba
silenciando cosas nuevas.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

# Formas de aviso que mypy no puede resolver y que no son un error del código.
# Cada una dice por qué.
RUIDO = (
    # `modelo: type` en los ayudantes genéricos: mypy no sabe qué clase llega.
    re.compile(r'"type" has no attribute'),
    # Jerarquías donde el atributo lo declara cada hijo, no la base.
    re.compile(r'"EntidadBase" has no attribute'),
    # `.all()` devuelve `Sequence` en la firma y una lista en tiempo de
    # ejecución; ordenarla funciona.
    re.compile(r'"Sequence\[[^"]*\]" has no attribute'),
    # SQLAlchemy: `__table__` está tipado como `FromClause`.
    re.compile(r'"FromClause" has no attribute'),
    # Valores que vienen de JSON y se comprueban antes de usarse.
    re.compile(r'"object" has no attribute'),
    re.compile(r'"dict\[Any, Any\]" has no attribute'),
    # Acceso defensivo con `getattr(..., None)`, que ya contempla que falte.
    re.compile(r'"CampoDefinido" has no attribute'),
)


def main() -> int:
    salida = subprocess.run(
        [sys.executable, "-m", "mypy", "services/", "packages/"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
    ).stdout

    reales = [
        linea
        for linea in salida.splitlines()
        if "[attr-defined]" in linea and not any(p.search(linea) for p in RUIDO)
    ]
    if reales:
        print("Accesos a atributos que no existen:\n", file=sys.stderr)
        for linea in reales:
            print(f"  {linea}", file=sys.stderr)
        print(
            "\nPython no lo dice hasta que esa línea corre, y entonces es un 500.",
            file=sys.stderr,
        )
        return 1
    print("sin accesos a atributos inexistentes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
