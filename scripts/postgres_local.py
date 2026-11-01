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


def _restos_de_un_apagado_a_medias() -> str:
    """Borra el `postmaster.pid` que dejó un apagado que no llegó a terminar.

    PostgreSQL escribe su PID en `postmaster.pid` y lo borra al cerrar. Si al
    proceso lo matan a mitad del cierre —`./setup.sh parar` interrumpido, la
    terminal cerrada, un reinicio— el fichero se queda, y con la última línea
    puesta en `stopping`. `pgserver` lo lee, ve que no dice `ready` y revienta
    con un `AssertionError` pelado, sin decir qué pasa ni cómo salir.

    Y lo que lo convierte en un callejón sin salida es que **`parar` también
    pasa por aquí**: con el fichero huérfano no se podía ni arrancar ni parar,
    sólo borrarlo a mano. Medido el 01-11-2026 en esta máquina, con un fichero
    del 30-10 cuyo PID (718) ya lo había reciclado `distnoted`.

    Lo peligroso sería borrarlo con un Postgres vivo detrás: dos servidores
    sobre el mismo directorio corrompen los datos. Por eso **no basta con que
    el PID no responda**: un PID se reutiliza, así que se comprueba además que
    el proceso sea realmente un `postgres` de *este* directorio. Si lo es, no
    se toca nada y que decida `pgserver`.

    Devuelve qué se encontró, para que el que llama lo pueda contar.
    """
    import psutil

    pidfile = PGDATA / "postmaster.pid"
    if not pidfile.exists():
        return ""

    lineas = pidfile.read_text(encoding="utf-8").splitlines()
    try:
        pid = int(lineas[0].strip())
    except (IndexError, ValueError):
        # Un fichero ilegible no puede estar protegiendo a nadie.
        pidfile.unlink(missing_ok=True)
        return "postmaster.pid ilegible: borrado"

    try:
        proceso = psutil.Process(pid)
        # `name()` es «postgres» tanto en el postmaster como en sus hijos.
        # `cwd()` es el directorio de datos: es lo que distingue a *nuestro*
        # servidor de cualquier otro Postgres de la máquina que haya cogido
        # ese PID por casualidad.
        suyo = proceso.name().startswith("postgres") and proceso.cwd() == str(PGDATA)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        suyo = False

    if suyo:
        return ""

    estado = lineas[7].strip() if len(lineas) > 7 else "sin estado"
    pidfile.unlink(missing_ok=True)
    # El socket y su cerrojo llevan el mismo PID muerto dentro y bloquean el
    # arranque igual que el pidfile. El directorio del socket es la línea 5.
    socket_dir = Path(lineas[4].strip()) if len(lineas) > 4 and lineas[4].strip() else PGDATA
    puerto = lineas[3].strip() if len(lineas) > 3 else "5432"
    for resto in (f".s.PGSQL.{puerto}", f".s.PGSQL.{puerto}.lock"):
        (socket_dir / resto).unlink(missing_ok=True)
    return f"restos de un apagado a medias (PID {pid}, «{estado}»): limpiados"


def _servidor(persistente: bool = True):  # noqa: ANN202 — tipo de pgserver
    import pgserver

    PGDATA.mkdir(parents=True, exist_ok=True)
    if aviso := _restos_de_un_apagado_a_medias():
        print(aviso, file=sys.stderr)
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
