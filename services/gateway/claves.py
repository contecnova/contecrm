"""Autenticación por clave de API, en el gateway (CRM-00.05.01.07).

**Por qué aquí y no en `crmcore`.** Validar una clave exige preguntar a
`identity`: el hash está en su tabla y el catálogo de roles del tenant también.
Si esa llamada viviera en la dependencia común, los trece servicios harían una
petición de red por cada petición que atienden, y además cualquiera de ellos
podría autenticar por su cuenta — que es exactamente lo que el gateway existe
para evitar. Aquí se resuelve una vez, en la puerta, y hacia dentro viaja la
identidad firmada de siempre.

**Por qué existía el agujero.** `identity.servicio.validar_clave_api` estaba
escrita entera, con su comprobación de redes admitidas y su auditoría, y NO LA
LLAMABA NADIE. Se podían crear claves desde la API, se listaban, se revocaban…
y ninguna autenticaba: una clave recién creada contestaba 401 en cualquier ruta.
Una credencial que no abre nada no es una credencial, es una fila.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

import httpx
from crmcore.authz.principal import Principal
from crmcore.config import get_settings
from crmcore.errors import NoAutenticado
from crmcore.http.deps import firmar_cabeceras_internas
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Las claves llevan este prefijo desde que se crean. Sirve para distinguirlas de
# un JWT sin intentar decodificarlas: un JWT empieza por `eyJ`, y probar a
# decodificar una clave para ver si «suena a token» daría un 401 con el motivo
# equivocado.
PREFIJO = "crm_"


# Cuánto se recuerda una clave válida. Sin caché, cada petición de una
# integración añadiría una llamada a `identity` — o sea, el doble de latencia en
# el camino de todas las llamadas de máquina. Treinta segundos es el compromiso:
# revocar una clave tarda eso en surtir efecto y se dice en el manual.
def _claves_ttl_cache_s() -> float:
    """Antes `_claves_ttl_cache_s() = 30.0`.

    Era una constante de módulo. Sale del `.env`, que es donde una instalación
    puede afinarla sin tocar código.
    """
    from crmcore.config import get_settings

    return get_settings().claves_ttl_cache_s


_cache: dict[str, tuple[float, Principal]] = {}


def limpiar_cache() -> None:
    """Para las pruebas y para el arranque."""
    _cache.clear()


def es_clave(credencial: str) -> bool:
    return credencial.startswith(PREFIJO)


async def principal_de_clave(
    cliente: httpx.AsyncClient, secreto: str, *, ip: str, url_identity: str
) -> Principal:
    """La identidad que representa esa clave, preguntando a `identity`."""
    ahora = time.monotonic()
    guardado = _cache.get(secreto)
    if guardado and guardado[0] > ahora:
        return guardado[1]

    s = get_settings()
    # La ruta es interna y va firmada: sin el secreto compartido no se entra.
    cabeceras = firmar_cabeceras_internas({}, s.secret_key.get_secret_value())
    try:
        respuesta = await cliente.post(
            f"{url_identity}/api/v1/claves-api/validar",
            json={"secreto": secreto, "ip": ip},
            headers=cabeceras,
            timeout=s.gateway_timeout_s if hasattr(s, "gateway_timeout_s") else 10.0,
        )
    except httpx.HTTPError as exc:
        # Que identity no conteste NO puede dejar pasar a nadie. Se rechaza, y
        # se registra distinto de una clave mala para que se pueda diagnosticar.
        logger.error("gateway.clave_api_incomprobable", error=str(exc)[:200])
        raise NoAutenticado(
            "No se ha podido comprobar la credencial",
            error_code="auth.clave_incomprobable",
        ) from exc

    if respuesta.status_code != 200:
        # El mismo error para clave inexistente, revocada, caducada o con la IP
        # fuera de su lista: distinguirlos diría a quien prueba en qué acertó.
        logger.warning("gateway.clave_api_rechazada", codigo_http=respuesta.status_code)
        raise NoAutenticado("Clave de API no válida", error_code="auth.clave_invalida")

    datos: dict[str, Any] = respuesta.json()
    principal = Principal(
        id=UUID(str(datos["clave_id"])),
        # `servicio`, no `usuario`: detrás de una clave no hay una persona, y la
        # auditoría tiene que poder decirlo. Lo que hace una integración a las
        # tres de la mañana no lo ha hecho nadie.
        tipo="servicio",
        tenant_id=UUID(str(datos["tenant_id"])),
        permisos=frozenset(datos.get("permisos") or []),
        roles=frozenset([str(datos.get("rol") or "")]),
        # Los alcances de la clave ACOTAN por encima de los permisos del rol:
        # una clave de solo lectura no escribe aunque su rol pudiera.
        scopes=frozenset(datos.get("scopes") or []),
    )
    _cache[secreto] = (ahora + _claves_ttl_cache_s(), principal)
    return principal
