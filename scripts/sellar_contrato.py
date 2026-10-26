#!/usr/bin/env python3
"""Sella el contrato publicado: qué operaciones ofrece hoy esta versión mayor.

    python scripts/sellar_contrato.py            # comprueba
    python scripts/sellar_contrato.py --sellar   # lo vuelve a escribir

**Por qué.** `CRM-00.02.01.06` promete compatibilidad hacia atrás dentro de la
versión mayor: lo que un integrador usa hoy sigue estando mañana. Esa promesa
no se rompe con un error — se rompe en silencio, y quien se entera es el
cliente de otro, en producción, el día del despliegue.

Lo que se guarda son las **operaciones**: método y camino, nada más. Los campos
los vigilan otros gates —los contratos que leen las pantallas, el de atributos—
y meterlos aquí haría un fichero que nadie revisa y que cambia en cada commit.

Quitar una operación **no se bloquea**: se bloquea quitarla sin decirlo. Para
retirar algo de verdad hay dos caminos y los dos son explícitos: anunciar la
retirada con `API_SUNSET_DATE` y subir la versión mayor, o sellar de nuevo
dejando constancia en el commit de qué se fue y por qué.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
SELLO = RAIZ / "docs/contrato-publicado.json"

# Los catorce procesos que publican API. Escrito y no deducido: un servicio
# nuevo que no conste aquí dejaría su contrato sin sellar en silencio, y lo que
# no se sella no se protege.
SERVICIOS = (
    "analytics",
    "automation",
    "eventing",
    "gateway",
    "identity",
    "integration",
    "intelligence",
    "marketing",
    "metadata",
    "orchestrator",
    "party",
    "sales",
    "service",
    "tenancy",
)

METODOS = ("get", "post", "put", "patch", "delete")


def operaciones() -> dict[str, list[str]]:
    """Las operaciones que publica cada servicio hoy, ordenadas."""
    os.environ.setdefault("OUTBOX_ENABLED", "false")
    salida: dict[str, list[str]] = {}
    for servicio in SERVICIOS:
        app = importlib.import_module(f"services.{servicio}.main").app
        contrato = app.openapi()
        suyas = sorted(
            f"{metodo.upper()} {ruta}"
            for ruta, ops in contrato.get("paths", {}).items()
            for metodo in ops
            if metodo in METODOS
        )
        salida[servicio] = suyas
    return salida


def main() -> int:
    hoy = operaciones()
    if "--sellar" in sys.argv:
        SELLO.write_text(json.dumps(hoy, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
        print(f"Sellado {SELLO.relative_to(RAIZ)}: {sum(len(v) for v in hoy.values())} operaciones")
        return 0

    if not SELLO.exists():
        print("No hay sello. Créalo con «python scripts/sellar_contrato.py --sellar».")
        return 1

    sellado = json.loads(SELLO.read_text())
    idas: list[str] = []
    for servicio, antes in sellado.items():
        ahora = set(hoy.get(servicio, []))
        idas += [f"{servicio}: {op}" for op in antes if op not in ahora]

    if idas:
        print("Operaciones que estaban publicadas y ya no están:")
        for linea in sorted(idas):
            print(f"  {linea}")
        print(
            "\nDentro de la misma versión mayor, lo que un integrador usa hoy "
            "tiene que seguir estando mañana. Si la retirada es a propósito: "
            "anúnciala con API_SUNSET_DATE y sube la versión mayor, o vuelve a "
            "sellar dejando dicho en el commit qué se fue y por qué."
        )
        return 1

    nuevas = sum(len(set(v) - set(sellado.get(s, []))) for s, v in hoy.items())
    print(f"El contrato se sostiene. {nuevas} operaciones nuevas desde el último sello.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
