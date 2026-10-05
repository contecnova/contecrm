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

from crmcore.errors import NoDisponible, Prohibido, SoloLectura, TenantSuspendido
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


# Servicios que NUNCA se cierran por plan, con el motivo al lado. Cerrar
# cualquiera de estos dejaría a un cliente sin poder entrar, sin poder mirar lo
# que ha contratado o sin poder pagar — o sea, sin poder arreglar la situación.
NUNCA_POR_PLAN = {
    "gateway": "es la puerta: cerrarla es cerrarlo todo",
    "identity": "entrar y gestionar usuarios no depende de lo contratado",
    "tenancy": "es donde se ve y se cambia el propio plan",
    "docs": "el manual se lee siempre",
}


def reglas_contextuales(tenant_id: UUID | None) -> list[dict[str, Any]]:
    """Las reglas de acceso contextual del tenant, de la misma caché.

    Se leen de lo que ya trajo `exigir`: son del mismo tenant y de la misma
    petición, y pedirlas aparte doblaría el tráfico interno por el mismo dato.
    """
    if tenant_id is None:
        return []
    guardado = _cache.get(str(tenant_id))
    if guardado is None:
        return []
    crudas = guardado[1].get("reglas_contextuales") or []
    return [r for r in crudas if isinstance(r, dict)]


async def exigir_capacidad(
    cliente: Any, url_base: str, tenant_id: UUID | None, servicio: str
) -> None:
    """Corta si el plan del tenant no incluye este módulo.

    **Se cierra por módulo**, que es como se vende: un cliente que no ha
    contratado marketing no tiene por qué poder usar sus rutas sabiéndose la URL.
    El gateway ya sabe a qué servicio va cada ruta, así que no hace falta una
    tabla de rutas que mantener —y que se quedaría vieja—.

    **Y sólo se cierra lo que el plan niega EXPLÍCITAMENTE.** Un plan que no
    menciona un módulo lo deja pasar: la omisión abre, nunca cierra. Si cerrara
    por omisión, un plan mal escrito —o vacío, que es el de cualquier instalación
    recién montada— dejaría al cliente sin producto.
    """
    if tenant_id is None or servicio in NUNCA_POR_PLAN:
        return

    guardado = _cache.get(str(tenant_id))
    if guardado is None:
        # Sin dato en caché no se inventa: lo habrá traído `exigir`, que corre
        # antes en la misma petición. Si no está, se deja pasar por lo mismo que
        # allí — no cerrar el sistema porque `tenancy` esté reiniciándose.
        return

    capacidades = guardado[1].get("capacidades") or {}
    if servicio in capacidades and not capacidades[servicio]:
        raise Prohibido(
            f"«{servicio}» no está incluido en el plan contratado",
            error_code="plan.capacidad_no_contratada",
            detalle={"modulo": servicio},
        )


__all__ = [
    "METODOS_DE_ESCRITURA",
    "NUNCA_POR_PLAN",
    "NoDisponible",
    "exigir",
    "exigir_capacidad",
    "limpiar_cache",
]
