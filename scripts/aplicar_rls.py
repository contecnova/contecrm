#!/usr/bin/env python3
"""Aplica RLS al esquema de un servicio, después de migrar.

    python scripts/aplicar_rls.py tenancy
    python scripts/aplicar_rls.py --todos
    python scripts/aplicar_rls.py --todos --comprobar    # solo informa (gate)

Va DESPUÉS de las migraciones porque una tabla nueva nace sin política, y una
tabla con `tenant_id` sin política es un agujero de aislamiento que no da
ningún síntoma hasta que dos clientes se ven los datos.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "packages" / "crmcore"))

SERVICIOS = [
    "tenancy",
    "identity",
    "metadata",
    "orchestrator",
    "automation",
    "integration",
    "eventing",
]


def _procesar(servicio: str, comprobar: bool) -> int:
    from crmcore.config import get_settings, limpiar_cache_settings
    from crmcore.db.rls import aplicar_politicas, tablas_sin_politica
    from sqlalchemy import create_engine

    os.environ["SERVICE_NAME"] = servicio
    limpiar_cache_settings()
    s = get_settings()
    esquema = s.esquema_resuelto
    url = s.database_admin_url or s.database_url

    engine = create_engine(url)
    try:
        with engine.connect() as conexion:
            if comprobar:
                faltan = tablas_sin_politica(conexion, esquema)
                if faltan:
                    print(
                        f"  {servicio}: {len(faltan)} tabla(s) SIN política de "
                        f"aislamiento → {', '.join(faltan)}",
                        file=sys.stderr,
                    )
                    return 1
                print(f"  {servicio}: todas las tablas con tenant_id tienen política")
                return 0

            tablas = aplicar_politicas(conexion, esquema)
            conexion.commit()
            print(f"  {servicio}: RLS aplicada a {len(tablas)} tabla(s)")
            return 0
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("servicio", nargs="?", choices=SERVICIOS)
    parser.add_argument("--todos", action="store_true")
    parser.add_argument(
        "--comprobar",
        action="store_true",
        help="No modifica nada: falla si falta alguna política",
    )
    args = parser.parse_args()

    servicios = SERVICIOS if args.todos else ([args.servicio] if args.servicio else [])
    if not servicios:
        parser.error("indica un servicio o usa --todos")

    peor = 0
    for servicio in servicios:
        peor = max(peor, _procesar(servicio, args.comprobar))
    return peor


if __name__ == "__main__":
    raise SystemExit(main())
