#!/usr/bin/env python3
"""Postgres local sin Docker, para desarrollo y para los gates.

    python scripts/postgres_local.py url     # levanta (si hace falta) e imprime la URL
    python scripts/postgres_local.py parar   # lo para
    python scripts/postgres_local.py estado

Usa `pgserver`, que trae los binarios de PostgreSQL 16 dentro del wheel: da un
Postgres de verdad sin Docker y sin permisos de administrador. Eso es lo que
permite que el gate de `pre-push` corra las pruebas que necesitan base de datos
en cualquier máquina — y por tanto que nadie acabe empujando con `--no-verify`.

**Un aviso que importa**: este Postgres corre como **superusuario**, y un
superusuario se salta las políticas de Row-Level Security aunque estén en FORCE.
Sirve para desarrollar y para la mayoría de las pruebas, pero un fallo de
aislamiento entre tenants solo se reproduce fielmente con el Postgres de Docker
y el rol de aplicación. Las pruebas de aislamiento crean ese rol explícitamente
por esa razón.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PGDATA = RAIZ / "var" / "pgdata"


def _servidor(persistente: bool = True):  # noqa: ANN202 — tipo de pgserver
    import pgserver

    PGDATA.mkdir(parents=True, exist_ok=True)
    # `cleanup_mode=None` es imprescindible: por defecto (`"stop"`), pgserver
    # PARA el servidor cuando termina el proceso que lo pidió — y este proceso
    # termina justo después de imprimir la URL. Con el valor por defecto, el
    # arranque levantaba Postgres, lo mataba al salir y luego los ocho servicios
    # fallaban con «connection to server on socket … failed». Se descubrió
    # ejecutando `./setup.sh arrancar`, no leyendo el código.
    return pgserver.get_server(PGDATA, cleanup_mode=None if persistente else "stop")


def main() -> int:
    comando = sys.argv[1] if len(sys.argv) > 1 else "url"

    if comando == "url":
        uri = _servidor().get_uri()
        # SQLAlchemy con psycopg 3 necesita el prefijo explícito; pgserver
        # devuelve el de libpq.
        print(uri.replace("postgresql://", "postgresql+psycopg://", 1))
        return 0

    if comando == "parar":
        import pgserver

        servidor = pgserver.get_server(PGDATA, cleanup_mode=None)
        servidor.cleanup()
        print("Postgres local parado")
        return 0

    if comando == "estado":
        if not (PGDATA / "PG_VERSION").exists():
            print("Postgres local: sin inicializar")
            return 1
        try:
            _servidor().psql("SELECT 1")
            print(f"Postgres local: levantado en {PGDATA}")
            return 0
        except Exception as exc:  # noqa: BLE001 — informar del estado, no lanzar
            print(f"Postgres local: no responde ({str(exc)[:120]})")
            return 1

    print(f"Comando desconocido: {comando} (usa url|parar|estado)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
