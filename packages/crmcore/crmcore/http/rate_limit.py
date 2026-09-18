"""Rate limiting por tenant, usuario, clave de API e IP (CRM-00.01.06.01).

Ventana deslizante aproximada con dos cubos: el de la ventana en curso y el de
la anterior, ponderado por lo que queda de la actual. Es el algoritmo de la
ventana deslizante contada, y se elige por lo que evita:

  * una ventana **fija** deja pasar el doble del límite en el cambio de ventana
    (todo al final de una y todo al principio de la siguiente), que es justo
    cuando un cliente que reintenta en bucle golpea más fuerte;
  * un **log deslizante** exacto guarda una marca por petición, lo que con
    tráfico real es mucha memoria en Redis para una precisión que no cambia
    ninguna decisión.

**Dos backends, y el de memoria no es un juguete ni un equivalente.** Con Redis,
el límite es del despliegue entero; en memoria, es *por proceso*, así que tres
réplicas dejan pasar tres veces el límite. Está dicho aquí y en el manual porque
un operador que no lo sepa creerá que tiene un tope que no tiene.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from starlette.types import Scope

from crmcore.errors import LimiteExcedido
from crmcore.logging import get_logger

logger = get_logger(__name__)

_redis: Any = None
# Contadores en memoria: clave -> (inicio_ventana, cuenta_actual, cuenta_previa)
_memoria: dict[str, tuple[float, int, int]] = {}


@dataclass(frozen=True, slots=True)
class Dimension:
    """Una dimensión de límite: qué se cuenta y cuánto se permite."""

    nombre: str
    clave: str
    limite: int


async def _conectar_redis() -> Any:
    global _redis
    if _redis is not None:
        return _redis
    from crmcore.config import get_settings

    s = get_settings()
    try:
        import redis.asyncio as redis

        _redis = redis.from_url(s.redis_url, decode_responses=True)
        await _redis.ping()
        logger.info("rate_limit.redis_conectado")
    except Exception as exc:  # noqa: BLE001 — sin Redis se degrada a memoria, avisando
        logger.warning(
            "rate_limit.sin_redis",
            error=str(exc)[:160],
            aviso="el límite pasa a ser POR PROCESO, no del despliegue",
        )
        _redis = False
    return _redis


def _dimensiones(scope: Scope) -> list[Dimension]:
    """Dimensiones aplicables a esta petición.

    Se aplican todas y manda la más restrictiva. Son dimensiones distintas
    porque el abuso tiene formas distintas: un usuario con un bucle, una
    integración mal configurada, o un tenant entero desbocado. Un único
    contador global no distingue entre las tres y castiga a quien no debe.
    """
    from crmcore.config import get_settings
    from crmcore.tenancy.context import contexto_actual

    s = get_settings()
    ctx = contexto_actual()
    dims: list[Dimension] = []

    if ctx.tenant_id and s.rate_limit_por_tenant:
        dims.append(Dimension("tenant", f"t:{ctx.tenant_id}", s.rate_limit_por_tenant))
    if ctx.user_id and s.rate_limit_por_usuario:
        dims.append(Dimension("usuario", f"u:{ctx.user_id}", s.rate_limit_por_usuario))
    api_key = ctx.extra.get("api_key_id")
    if api_key and s.rate_limit_por_api_key:
        dims.append(Dimension("api_key", f"k:{api_key}", s.rate_limit_por_api_key))
    if s.rate_limit_por_ip:
        dims.append(Dimension("ip", f"i:{_ip_cliente(scope)}", s.rate_limit_por_ip))
    return dims


def _ip_cliente(scope: Scope) -> str:
    """IP del cliente, mirando el proxy solo si está declarado de confianza.

    Sin esa condición, cualquiera manda `X-Forwarded-For: 1.2.3.4` y se salta el
    límite por IP cambiando el valor en cada petición. Con proxy declarado, la
    cabecera es fiable porque la reescribe el proxy.
    """
    from crmcore.config import get_settings

    s = get_settings()
    if s.trust_proxy_headers:
        for clave, valor in scope.get("headers", []):
            if clave == b"x-forwarded-for":
                return valor.decode("latin-1").split(",")[0].strip()
    cliente = scope.get("client")
    return cliente[0] if cliente else "desconocido"


async def comprobar_limites(scope: Scope) -> None:
    """Lanza `LimiteExcedido` si alguna dimensión se ha pasado."""
    from crmcore.config import get_settings

    s = get_settings()
    ventana = s.rate_limit_ventana_s
    ahora = time.time()

    for dim in _dimensiones(scope):
        usado = await _incrementar(dim.clave, ventana, ahora)
        if usado > dim.limite:
            from crmcore.obs.metrics import observar_limite

            observar_limite(dim.nombre)
            # Se espera a que termine la ventana en curso. Decirlo con precisión
            # evita que el cliente reintente antes de tiempo y gaste otra
            # ventana al hacerlo.
            espera = int(ventana - (ahora % ventana)) or 1
            raise LimiteExcedido(
                f"Se ha superado el límite de peticiones ({dim.limite} por "
                f"{ventana}s) para {dim.nombre}",
                reintentar_en_s=espera,
                error_code=f"limite.{dim.nombre}",
                detalle={"dimension": dim.nombre, "limite": dim.limite, "usado": usado},
            )


async def _incrementar(clave: str, ventana: int, ahora: float) -> float:
    """Suma uno y devuelve el uso estimado de la ventana deslizante."""
    r = await _conectar_redis()
    if r:
        return await _incrementar_redis(r, clave, ventana, ahora)
    return _incrementar_memoria(clave, ventana, ahora)


async def _incrementar_redis(r: Any, clave: str, ventana: int, ahora: float) -> float:
    inicio = int(ahora // ventana) * ventana
    k_actual, k_previa = f"rl:{clave}:{inicio}", f"rl:{clave}:{inicio - ventana}"
    pipe = r.pipeline()
    pipe.incr(k_actual)
    # Caduca a dos ventanas: la actual se necesita completa y la anterior sigue
    # ponderando hasta que termine la actual.
    pipe.expire(k_actual, ventana * 2)
    pipe.get(k_previa)
    actual, _, previa = await pipe.execute()
    return _ponderar(int(actual), int(previa or 0), ventana, ahora, inicio)


def _incrementar_memoria(clave: str, ventana: int, ahora: float) -> float:
    inicio = int(ahora // ventana) * ventana
    guardado = _memoria.get(clave)
    if guardado is None or guardado[0] != inicio:
        # Solo se conserva la cuenta anterior si venía de la ventana
        # inmediatamente previa; si el hueco es mayor, no hay nada que ponderar.
        previa = guardado[1] if guardado and guardado[0] == inicio - ventana else 0
        _memoria[clave] = (inicio, 1, previa)
        return _ponderar(1, previa, ventana, ahora, inicio)
    _, actual, previa = guardado
    _memoria[clave] = (inicio, actual + 1, previa)
    return _ponderar(actual + 1, previa, ventana, ahora, inicio)


def _ponderar(actual: int, previa: int, ventana: int, ahora: float, inicio: float) -> float:
    """Uso estimado: la ventana actual más la parte de la anterior que sigue dentro."""
    transcurrido = (ahora - inicio) / ventana
    return actual + previa * (1.0 - transcurrido)


def limpiar_memoria() -> None:
    """Vacía los contadores en memoria. Solo para pruebas."""
    _memoria.clear()
