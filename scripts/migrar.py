#!/usr/bin/env python3
"""Migraciones por servicio.

    python scripts/migrar.py tenancy upgrade head
    python scripts/migrar.py identity revision -m "sesiones"
    python scripts/migrar.py --todos upgrade head

Existe porque Alembic construye su directorio de versiones **antes** de ejecutar
`env.py`, así que fijar ahí `version_locations` llega tarde: la primera
migración de un servicio acababa en la carpeta común y, a partir de ahí, cada
servicio veía las migraciones de los demás como pendientes («Target database is
not up to date» al generar la segunda). Aquí la configuración se arma en
memoria, con la carpeta del servicio ya puesta.

También evita el error que más caro sale con este esquema: olvidar el
`-x servicio=` y migrar el esquema equivocado.

Que cada servicio tenga su cadena de migraciones es lo que hace posible el
despliegue independiente (CRM-00.03.01.06): ninguno espera al de otro.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))


def _servicios_con_modelos() -> list[str]:
    """Los servicios que tienen tablas, leídos del árbol.

    Escrita a mano, esta lista se queda desfasada en cuanto alguien añade un
    servicio: lo normal es acordarse de crear la carpeta de migraciones y
    olvidarse de esta constante, y entonces `--todos` salta ese servicio **en
    silencio** y su esquema se queda sin migrar hasta que algo falla en
    producción.

    El criterio es tener `modelos.py`: un servicio sin tablas —el gateway— no
    tiene nada que migrar, y pedirle una migración solo produce ruido.
    """
    servicios = RAIZ / "services"
    return sorted(
        p.name
        for p in servicios.iterdir()
        if p.is_dir() and not p.name.startswith("_") and (p / "modelos.py").exists()
    )


SERVICIOS = _servicios_con_modelos()


def _config(servicio: str):  # noqa: ANN202 — alembic.config.Config, import perezoso
    from alembic.config import Config

    versiones = RAIZ / "alembic" / "versions" / servicio
    versiones.mkdir(parents=True, exist_ok=True)

    config = Config(str(RAIZ / "alembic.ini"))
    config.set_main_option("script_location", str(RAIZ / "alembic"))
    config.set_main_option("version_locations", str(versiones))
    config.set_main_option("servicio", servicio)
    config.cmd_opts = argparse.Namespace(x=[f"servicio={servicio}"])  # lo lee env.py
    os.environ["SERVICE_NAME"] = servicio
    return config


def ejecutar(servicio: str, comando: str, argumento: str, mensaje: str) -> int:
    from alembic import command

    config = _config(servicio)
    print(f"── {servicio} ──")
    try:
        if comando == "upgrade":
            command.upgrade(config, argumento or "head")
        elif comando == "downgrade":
            if not argumento:
                print(
                    "  downgrade exige destino explícito (p. ej. -1 o una revisión).\n"
                    "  Sin destino, el valor por defecto sería revertirlo todo.",
                    file=sys.stderr,
                )
                return 2
            command.downgrade(config, argumento)
        elif comando == "revision":
            command.revision(config, message=mensaje, autogenerate=True)
        elif comando == "historial":
            command.history(config, verbose=True)
        elif comando == "actual":
            command.current(config, verbose=True)
        else:
            print(f"  comando desconocido: {comando}", file=sys.stderr)
            return 2
    except Exception as exc:  # noqa: BLE001 — se informa por servicio y se sigue
        print(f"  FALLO: {exc}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    # Los posicionales se leen sin orden fijo porque `--todos upgrade head` y
    # `tenancy upgrade head` tienen distinto número de piezas, y obligar a
    # recordar cuál va dónde es una forma tonta de que alguien migre el esquema
    # equivocado.
    parser.add_argument("partes", nargs="*", help="[servicio] comando [argumento]")
    parser.add_argument("-m", "--mensaje", default="cambios")
    parser.add_argument("--todos", action="store_true", help="aplica a todos los servicios")
    args = parser.parse_args()

    partes = list(args.partes)
    servicio = partes.pop(0) if partes and partes[0] in SERVICIOS else ""
    comando = partes.pop(0) if partes else ""
    argumento = partes.pop(0) if partes else ""

    comandos = {"upgrade", "downgrade", "revision", "historial", "actual"}
    if comando not in comandos:
        parser.error(
            f"comando desconocido: «{comando or ''}». Usa uno de: {', '.join(sorted(comandos))}"
        )

    if args.todos:
        if comando == "revision":
            # Generar una revisión para todos a la vez produce siete migraciones
            # con el mismo mensaje y ninguna revisada. Se hace de una en una.
            print("`--todos` no vale para `revision`: genera una por servicio", file=sys.stderr)
            return 2
        peor = 0
        for nombre in SERVICIOS:
            peor = max(peor, ejecutar(nombre, comando, argumento, args.mensaje))
        return peor

    if not servicio:
        parser.error(f"indica un servicio ({', '.join(SERVICIOS)}) o usa --todos")
    return ejecutar(servicio, comando, argumento, args.mensaje)


if __name__ == "__main__":
    raise SystemExit(main())
