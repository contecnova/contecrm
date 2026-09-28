"""Si el tenant puede operar, aplicado donde pasa todo (CRM-00.01.03.04).

**Esto no existía.** La comprobación llevaba escrita en `tenancy` desde el
principio, con una documentación que decía «lo llama el gateway en cada
petición», y el gateway no la llamaba. El 28-09-2026 se montó el caso y se vio:
un tenant **suspendido** creó una cuenta —201— y uno en **solo lectura**
también. La suspensión y la ventana de mantenimiento existían en la tabla y en
ningún otro sitio.

No era un guardián apagado: era un guardián que nunca se encendió y que se
contaba como encendido, que es bastante peor.

**Por qué aquí.** El gateway es el único paso obligado de toda la API pública, y
ningún servicio puede leer la tabla de tenants de otro —los permisos de Postgres
lo impiden, que es el aislamiento funcionando—. Así que se pregunta a `tenancy`,
que es de quien es el dato y donde vive la regla.

**Por qué con caché.** Preguntar en cada petición doblaría la latencia de todo el
sistema. Se recuerda unos segundos, como ya se hace con las claves de API. Lo
que eso significa —suspender a alguien tarda ese tiempo en surtir efecto— va en
el manual, y el plazo es configurable en caliente por si a alguna instalación no
le sirve.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from crmcore.errors import NoDisponible, SoloLectura, TenantSuspendido
from crmcore.logging import get_logger

logger = get_logger(__name__)

# tenant_id → (vence_en, estado)
_cache: dict[str, tuple[float, dict[str, Any]]] = {}

METODOS_DE_ESCRITURA = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def limpiar_cache() -> None:
    """Para las pruebas y para cuando un operador quiere efecto inmediato."""
    _cache.clear()


def _plazo() -> float:
    from crmcore.runtime import settings as rt

    return float(rt.efectivo("gateway_operatividad_ttl_s") or 30.0)


async def _preguntar(cliente: Any, url_base: str, tenant_id: UUID) -> dict[str, Any]:
    from crmcore.http.interno import cabeceras_firmadas

    respuesta = await cliente.get(
        f"{url_base}/api/v1/interno/tenants/{tenant_id}/operatividad",
        headers=cabeceras_firmadas(),
    )
    if respuesta.status_code == 404:
        # Un tenant que no existe no puede operar. Dejarlo pasar porque «no se
        # sabe» sería justo lo contrario de lo que este módulo hace.
        return {"estado": "inexistente", "puede_leer": False, "puede_escribir": False, "motivo": ""}
    respuesta.raise_for_status()
    return dict(respuesta.json())


async def exigir(cliente: Any, url_base: str, tenant_id: UUID | None, metodo: str) -> None:
    """Lanza si este tenant no puede hacer lo que está pidiendo.

    Sin `tenant_id` no hay nada que comprobar: son las rutas de entrar, que
    ocurren antes de estar dentro de ninguno.

    **Si `tenancy` no contesta, se deja pasar** y se deja constancia. Es una
    decisión y no un descuido: cerrar el sistema entero porque el servicio de
    tenants está reiniciándose convertiría una molestia en una caída total, y lo
    que se protege aquí —cobrar, y una ventana de mantenimiento— aguanta unos
    segundos. Lo que no puede pasar es que no se entere nadie, y por eso el aviso
    es de nivel error.
    """
    if tenant_id is None:
        return

    clave = str(tenant_id)
    ahora = time.monotonic()
    guardado = _cache.get(clave)
    if guardado is None or guardado[0] <= ahora:
        try:
            estado = await _preguntar(cliente, url_base, tenant_id)
        except Exception as exc:  # noqa: BLE001 — abrir, no cerrar; ver arriba
            logger.error(
                "gateway.operatividad_sin_respuesta",
                tenant_id=clave,
                error=str(exc)[:200],
            )
            return
        _cache[clave] = (ahora + _plazo(), estado)
        guardado = _cache[clave]

    estado = guardado[1]
    motivo = str(estado.get("motivo") or "")
    if not estado.get("puede_leer"):
        raise TenantSuspendido(
            f"El servicio está suspendido: {motivo or 'contacta con soporte'}",
            error_code="tenant.suspendido",
        )
    if metodo.upper() in METODOS_DE_ESCRITURA and not estado.get("puede_escribir"):
        raise SoloLectura(
            f"El servicio está en solo lectura: {motivo or 'contacta con soporte'}",
            error_code="tenant.solo_lectura",
        )


__all__ = ["METODOS_DE_ESCRITURA", "NoDisponible", "exigir", "limpiar_cache"]
