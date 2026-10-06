"""Cómo se arma la configuración de Alembic, en un solo sitio.

Vive aquí y no en `scripts/migrar.py` porque la necesitan **dos**: el script de
la línea de órdenes y el arranque del servicio cuando `DB_MIGRATE_ON_BOOT` está
encendido. Dos copias de este armado divergen, y la que menos se mire será la
que migre el esquema equivocado — que es el error que más caro sale con un
esquema por servicio.

El armado tiene una razón concreta: Alembic construye su directorio de versiones
**antes** de ejecutar `env.py`, así que fijar ahí `version_locations` llega
tarde. La primera migración de un servicio acababa en la carpeta común y, a
partir de ahí, cada servicio veía las migraciones de los demás como pendientes.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from crmcore.logging import get_logger

logger = get_logger(__name__)

# La raíz del proyecto: cuatro niveles por encima de este fichero
# (crmcore/db/migraciones.py → crmcore → crmcore → packages → raíz).
RAIZ = Path(__file__).resolve().parents[4]

# Clave del cerrojo de aviso de Postgres. Un número fijo y uno derivado del
# servicio: así dos réplicas del MISMO servicio se turnan, y dos servicios
# distintos no se estorban — sus esquemas son independientes y esperar al otro
# sería renunciar al despliegue independiente que justifica tener una cadena de
# migraciones por servicio.
CERROJO_MIGRACION = 0x43524D00  # "CRM\0"


def config(servicio: str) -> Any:
    """La configuración de Alembic de este servicio, armada en memoria."""
    from alembic.config import Config

    versiones = RAIZ / "alembic" / "versions" / servicio
    versiones.mkdir(parents=True, exist_ok=True)

    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "alembic"))
    cfg.set_main_option("version_locations", str(versiones))
    cfg.set_main_option("servicio", servicio)
    # Lo lee `env.py`. Olvidarlo migra el esquema equivocado, que es el error
    # que más caro sale con un esquema por servicio.
    import argparse

    cfg.cmd_opts = argparse.Namespace(x=[f"servicio={servicio}"])
    os.environ["SERVICE_NAME"] = servicio
    return cfg


def migrar_al_arrancar(servicio: str) -> dict[str, Any]:
    """Aplica las migraciones pendientes de este servicio, con cerrojo.

    `DB_MIGRATE_ON_BOOT` existía, estaba documentado y **no lo leía nadie**
    (medido el 06-10-2026): encenderlo no migraba nada, así que quien lo
    encendía arrancaba contra un esquema viejo y lo descubría en la primera
    consulta, como un «relation does not exist» sin contexto.

    **Con cerrojo de aviso**, que es la condición que lo hace aceptable: el
    propio ajuste advierte que en producción se deja apagado «para que dos
    réplicas no migren a la vez». Con el cerrojo, la segunda espera a la primera
    y luego no encuentra nada pendiente, en vez de las dos corriendo el mismo
    `CREATE TABLE`.

    Un fallo aquí **no arranca el servicio a medias**: se propaga. Arrancar
    contra un esquema que no es el que el código espera no es un servicio
    degradado, es uno que contesta mal.
    """
    from sqlalchemy import text

    from alembic import command
    from crmcore.db.session import get_engine

    clave = CERROJO_MIGRACION
    with get_engine().connect() as conexion:
        # `pg_advisory_lock` y no `try_lock`: si otra réplica está migrando, lo
        # que hace falta es ESPERARLA. Rendirse dejaría a esta arrancando contra
        # el esquema a medio migrar de la otra, que es el caso peor de los tres.
        conexion.execute(
            text("SELECT pg_advisory_lock(:a, :b)"), {"a": clave, "b": _sufijo(servicio)}
        )
        try:
            logger.info("migraciones.arranque_aplica", servicio=servicio)
            command.upgrade(config(servicio), "head")
            return {"aplicadas": True}
        finally:
            conexion.execute(
                text("SELECT pg_advisory_unlock(:a, :b)"), {"a": clave, "b": _sufijo(servicio)}
            )
            conexion.commit()


def _sufijo(servicio: str) -> int:
    """La mitad baja del cerrojo, derivada del nombre del servicio.

    Estable entre procesos y entre versiones: `hash()` de Python lleva semilla
    aleatoria por proceso, así que dos réplicas tomarían cerrojos DISTINTOS y el
    cerrojo no serviría para nada — que es peor que no tenerlo, porque parece
    puesto.
    """
    import zlib

    return zlib.crc32(servicio.encode("utf-8")) & 0x7FFFFFFF
