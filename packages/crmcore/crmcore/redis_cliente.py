"""El cliente de Redis compartido, atado al bucle que lo usa.

Existe por un fallo que no da la cara: un cliente asíncrono queda atado al bucle
de eventos en el que se creó. Si el proceso cambia de bucle —un worker que se
reinicia, una tarea de mantenimiento que abre el suyo, una herramienta de línea
de comandos— el cliente guardado sigue pareciendo válido y **falla en cada
operación**. Lo que se guardaba aquí era un cliente global, así que a partir de
ese momento todo caía al respaldo en memoria sin un solo error visible.

Eso es lo peor que puede pasarle a un contador de presupuesto de error o a un
límite de tasa: siguen contestando, siguen devolviendo números, y los números
son de un solo proceso. Nadie se entera hasta que alguien compara.

Se guarda **por bucle**. Si el bucle cambia, se conecta de nuevo en vez de
arrastrar uno muerto. Y cuando no hay Redis, quien llama recibe `None` y tiene
que decidir qué hacer —y decirlo—, en vez de recibir un objeto que finge.
"""

from __future__ import annotations

import asyncio
from typing import Any

from crmcore.logging import get_logger

logger = get_logger(__name__)

# Clave: el identificador del bucle en curso. Valor: el cliente, o False cuando
# ya se ha intentado conectar en ese bucle y no había Redis. Distinguir False de
# «todavía no lo he intentado» evita reintentar la conexión en cada petición
# cuando Redis no está, que es justo cuando el sistema va peor de tiempo.
_clientes: dict[int, Any] = {}


async def cliente() -> Any:
    """El cliente de Redis del bucle en curso, o `None` si no hay Redis."""
    try:
        bucle = id(asyncio.get_running_loop())
    except RuntimeError:
        bucle = 0

    guardado = _clientes.get(bucle)
    if guardado is not None:
        return guardado or None

    from crmcore.config import get_settings

    try:
        import redis.asyncio as redis

        conexion = redis.from_url(get_settings().redis_url, decode_responses=True)
        await conexion.ping()
    except Exception as exc:  # noqa: BLE001 — sin Redis se sigue, peor y dicho
        logger.warning("redis.no_disponible", motivo=str(exc)[:160])
        _clientes[bucle] = False
        return None

    _clientes[bucle] = conexion
    # Los bucles que ya no existen se sueltan: en un proceso que abre y cierra
    # bucles, guardarlos todos sería una fuga lenta.
    for otro in [k for k in _clientes if k != bucle and k != 0]:
        if otro != bucle:
            _clientes.pop(otro, None)
    return conexion


def olvidar() -> None:
    """Suelta lo guardado. Para las pruebas y para un reinicio en caliente."""
    _clientes.clear()


def hay_cliente() -> bool:
    """Si en este bucle ya se comprobó que hay Redis. No conecta."""
    try:
        bucle = id(asyncio.get_running_loop())
    except RuntimeError:
        bucle = 0
    return bool(_clientes.get(bucle))
