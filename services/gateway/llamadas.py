"""Lo que el gateway apunta de cada llamada hecha con clave de API (CRM-00.02.04.06).

El portal del integrador sirve para la llamada de las tres de la mañana: qué
ruta, qué contestamos y cuándo. El cálculo estaba escrito y nadie le daba
llamadas; las únicas que conoce el sistema son las que pasan por aquí.

Se apuntan en memoria y se mandan a `identity` —dueña de las claves— por lotes,
al llenarse (`CLAVES_LLAMADAS_LOTE`) o al pasar el intervalo
(`CLAVES_LLAMADAS_INTERVALO_S`). Una llamada de red por petición la pagaría el
integrador en cada respuesta.

Si `identity` no contesta, el lote **se pierde y se dice**: se cuenta y se
registra. Reintentarlo sin fin haría crecer la memoria del gateway justo cuando
el sistema ya va mal, y el registro de llamadas no es el que decide si una
petición pasa.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

from crmcore.config import get_settings
from crmcore.http.deps import firmar_cabeceras_internas
from crmcore.logging import get_logger

logger = get_logger(__name__)

_pendientes: list[dict[str, Any]] = []
_ultimo_envio = time.monotonic()
_perdidas = 0


def perdidas() -> int:
    """Cuántas llamadas no se han podido guardar desde que arrancó el proceso."""
    return _perdidas


def apuntar(
    *,
    clave_id: str,
    tenant_id: str,
    metodo: str,
    ruta: str,
    status: int,
    duracion_ms: int,
    request_id: str,
) -> list[dict[str, Any]] | None:
    """Apunta una llamada. Devuelve el lote a mandar cuando toca, o `None`."""
    global _ultimo_envio
    _pendientes.append(
        {
            "clave_id": clave_id,
            "tenant_id": tenant_id,
            "cuando": datetime.now(timezone.utc).isoformat(),
            "metodo": metodo,
            "ruta": ruta[:500],
            "status": status,
            "duracion_ms": duracion_ms,
            "request_id": request_id[:64],
        }
    )
    s = get_settings()
    ahora = time.monotonic()
    if len(_pendientes) < s.claves_llamadas_lote and (
        ahora - _ultimo_envio < s.claves_llamadas_intervalo_s
    ):
        return None
    lote = list(_pendientes)
    _pendientes.clear()
    _ultimo_envio = ahora
    return lote


async def enviar(cliente: Any, url_identity: str, lote: list[dict[str, Any]]) -> None:
    """Manda el lote a `identity`. No lanza: un fallo se cuenta y se registra."""
    global _perdidas
    cabeceras = firmar_cabeceras_internas({}, get_settings().secret_key.get_secret_value())
    try:
        respuesta = await cliente.post(
            f"{url_identity}/api/v1/claves-api/llamadas",
            json={"llamadas": lote},
            headers=cabeceras,
            timeout=10.0,
        )
        if respuesta.status_code >= 400:
            _perdidas += len(lote)
            logger.error(
                "gateway.llamadas_no_guardadas",
                llamadas=len(lote),
                status=respuesta.status_code,
                perdidas_desde_el_arranque=_perdidas,
            )
    except Exception as exc:  # noqa: BLE001 — esto no puede tumbar el gateway
        _perdidas += len(lote)
        logger.error(
            "gateway.llamadas_no_guardadas",
            llamadas=len(lote),
            error=str(exc)[:200],
            perdidas_desde_el_arranque=_perdidas,
        )


def tomar_pendientes() -> list[dict[str, Any]]:
    """Lo apuntado y sin mandar, vaciando la lista."""
    global _ultimo_envio
    lote = list(_pendientes)
    _pendientes.clear()
    _ultimo_envio = time.monotonic()
    return lote


async def vaciar_cada_intervalo(destino: Any) -> None:
    """Manda lo pendiente cada `CLAVES_LLAMADAS_INTERVALO_S`, haya tráfico o no.

    Sin esto el lote sólo salía con la llamada siguiente: una integración que
    dejaba de llamar se llevaba sus últimas llamadas —normalmente las del
    error que hizo que dejara de llamar— sin que llegaran nunca al portal.
    `destino` es `cliente_y_destino` del gateway, que sabe dónde está identity.
    """
    while True:
        await asyncio.sleep(get_settings().claves_llamadas_intervalo_s)
        lote = tomar_pendientes()
        if not lote:
            continue
        cliente, url = destino("identity")
        if cliente is not None and url:
            await enviar(cliente, url, lote)


def despachar(cliente: Any, url_identity: str, lote: list[dict[str, Any]]) -> None:
    """Manda el lote sin esperar: la respuesta al integrador no espera por esto."""
    asyncio.get_running_loop().create_task(enviar(cliente, url_identity, lote))
