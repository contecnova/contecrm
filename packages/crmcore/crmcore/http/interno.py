"""Llamadas entre servicios de la casa, firmadas.

Un servicio necesita a veces preguntar algo a otro. No lee su base —los
permisos de Postgres no se lo permiten, y ese es justo el punto—, así que lo
pregunta por HTTP. Aquí está lo común: dónde vive cada servicio y cómo se firma
la llamada.

La dirección sale de `RUTAS_SERVICIOS`, la misma variable que usa el gateway
para enrutar. Tenerla en un solo sitio es lo que evita que un despliegue mueva
un servicio y la mitad del sistema siga hablando con la dirección vieja.
"""

from __future__ import annotations

from typing import Any

from crmcore.errors import NoDisponible
from crmcore.logging import get_logger

logger = get_logger(__name__)


def direccion_de(servicio: str) -> str:
    """Dónde escucha un servicio, según `RUTAS_SERVICIOS`. Cadena vacía si no consta."""
    from crmcore.config import get_settings

    for trozo in get_settings().rutas_servicios.replace("\n", "").split(","):
        nombre, _, url = trozo.strip().partition("=")
        if nombre.strip() == servicio:
            return url.strip().rstrip("/")
    return ""


def cabeceras_firmadas() -> dict[str, str]:
    """Firma una llamada interna SIN identidad de usuario.

    Todos los valores van vacíos a propósito: esto no suplanta a nadie. Es el
    servicio diciendo «soy de la casa», y solo sirve para rutas que no deciden
    nada sobre datos de un usuario concreto.
    """
    from crmcore.config import get_settings
    from crmcore.http.deps import (
        H_ACTOR_REAL,
        H_PERMISOS,
        H_PLATAFORMA,
        H_ROLES,
        H_SCOPES,
        H_TENANT,
        H_USER,
        firmar_cabeceras_internas,
    )

    vacias = dict.fromkeys(
        (H_TENANT, H_USER, H_PERMISOS, H_ROLES, H_SCOPES, H_ACTOR_REAL, H_PLATAFORMA), ""
    )
    return firmar_cabeceras_internas(vacias, get_settings().secret_key.get_secret_value())


def pedir(servicio: str, ruta: str, *, timeout_s: float = 5.0) -> dict[str, Any] | None:
    """GET firmado a otro servicio. `None` si contesta 404.

    Un fallo de red se convierte en `NoDisponible` y no en un error genérico:
    quien llama tiene que poder distinguir «no existe» de «no he podido
    preguntar», porque la respuesta al usuario es distinta —y tratar lo segundo
    como lo primero es cómo se acaba diciendo «no existe» de algo que sí existe.
    """
    import httpx

    base = direccion_de(servicio)
    if not base:
        raise NoDisponible(
            f"No hay dirección configurada para el servicio «{servicio}»",
            error_code="interno.servicio_sin_direccion",
        )
    try:
        salida = httpx.get(f"{base}{ruta}", headers=cabeceras_firmadas(), timeout=timeout_s)
    except httpx.HTTPError as exc:
        logger.error("interno.sin_respuesta", servicio=servicio, ruta=ruta, error=str(exc)[:200])
        raise NoDisponible(
            f"El servicio «{servicio}» no responde",
            error_code="interno.servicio_no_responde",
        ) from exc
    if salida.status_code == 404:
        return None
    if salida.status_code >= 400:
        raise NoDisponible(
            f"El servicio «{servicio}» ha contestado {salida.status_code}",
            error_code="interno.respuesta_inesperada",
        )
    return dict(salida.json())


def resolver_tenant(valor: str) -> Any:
    """Traduce el identificador o el slug del tenant a UUID.

    Vive aquí y no en un servicio porque lo necesitan **todas las puertas de
    entrada**, y hay más de una: el inicio de sesión del CRM, el portal del
    partner, el del cliente. A esas rutas se llega sin credencial —es donde se
    consigue la primera— así que el tenant no puede venir del principal: llega
    en el cuerpo, como una pista sin firmar, y lo que concede acceso es lo que
    venga detrás.

    Se pregunta a `tenancy` por HTTP en vez de leer su tabla: la propiedad
    exclusiva de datos por servicio es justo lo que hace que esa consulta ni
    siquiera esté permitida a nivel de permisos de base de datos.

    **El error es el mismo que una credencial mal puesta**, y a propósito: decir
    «esa organización no existe» convierte cualquier pantalla de acceso en un
    buscador de clientes, que es media lista de la competencia.
    """
    from crmcore.errors import ErrorValidacion
    from crmcore.ids import es_id_valido, sin_prefijo

    if es_id_valido(valor):
        return sin_prefijo(valor)

    datos = pedir("tenancy", f"/api/v1/interno/tenants/por-slug/{valor}")
    if datos is None:
        raise ErrorValidacion(
            "Credenciales no válidas",
            error_code="auth.credenciales_invalidas",
        )
    return sin_prefijo(str(datos["tenant_id"]))
