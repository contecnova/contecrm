"""Logging estructurado con structlog. JSON en producción, consola en desarrollo.

Todo apunte lleva, sin que el llamante tenga que acordarse, `service`,
`tenant_id`, `trace_id` y `user_id` cuando existen (CRM-00.06.01.01): los toma
del contexto de la petición. Eso es lo que hace que un incidente se pueda
seguir de un servicio a otro sin ir emparejando líneas a ojo.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import sys
import time
from typing import Any

import structlog

_configurado = False

_FORMATO_STDLIB = "%(asctime)s.%(msecs)03dZ %(levelname)s %(name)s %(message)s"
_FECHA_STDLIB = "%Y-%m-%dT%H:%M:%S"

# Salt de reserva cuando aún no se puede leer `secret_key` (por ejemplo, un
# apunte emitido durante la importación de la configuración). Es aleatorio POR
# PROCESO en vez de una constante conocida: los hashes siguen siendo estables
# dentro de un arranque —así correlacionan— pero no se pueden precomputar desde
# el código fuente.
_SALT_RESERVA = secrets.token_hex(16)

# Claves cuyo valor es una credencial. Se sustituyen enteras, siempre.
_CLAVES_SECRETAS = frozenset(
    {
        "authorization",
        "password",
        "contrasena",
        "refresh_token",
        "access_token",
        "token",
        "x-api-key",
        "api_key",
        "secret",
        "secreto",
        "cookie",
        "hashed_password",
        "client_secret",
        "private_key",
    }
)

# Claves con datos personales. En producción se sustituyen por un hash corto y
# estable: dos líneas sobre la misma persona siguen cruzándose, pero el valor
# original no sale del proceso.
_CLAVES_PII = frozenset(
    {
        "email",
        "correo",
        "actor_email",
        "user_agent",
        "ip",
        "ip_address",
        "telefono",
        "phone",
        "nombre_completo",
        "direccion",
    }
)


def _hash_pii(valor: object) -> str:
    """Hash corto y estable de un dato personal.

    Lleva salt derivado de `secret_key` para que unos logs filtrados no se
    puedan cruzar con un diccionario de correos precomputado. Sin salt, un
    SHA-256 de un correo es reversible en la práctica: basta probar los cien
    mil más comunes.
    """
    try:
        from crmcore.config import get_settings

        salt = get_settings().secret_key.get_secret_value() or _SALT_RESERVA
    except Exception:  # noqa: BLE001 — puede emitirse un log ANTES de que la config cargue
        salt = _SALT_RESERVA
    digest = hashlib.sha256(f"{salt}{valor}".encode()).hexdigest()
    return f"h:{digest[:12]}"


def _censurar(_logger: Any, _metodo: str, evento: dict[str, Any]) -> dict[str, Any]:
    """Procesador que censura credenciales y, fuera de desarrollo, PII."""
    try:
        from crmcore.config import get_settings

        redactar_pii = get_settings().redactar_pii_resuelto
    except Exception:  # noqa: BLE001 — sin configuración disponible, se asume lo estricto
        redactar_pii = True

    for clave in list(evento.keys()):
        minuscula = clave.lower()
        if minuscula in _CLAVES_SECRETAS:
            evento[clave] = "***"
        elif redactar_pii and minuscula in _CLAVES_PII and evento[clave] is not None:
            evento[clave] = _hash_pii(evento[clave])
    return evento


def redactar_estructura(dato: Any) -> Any:
    """Censura por clave **dentro** de una estructura, no solo en la raíz.

    El procesador de arriba mira las claves del apunte de log, así que un valor
    anidado —el cuerpo de una petición, por ejemplo— pasaría entero y en claro:
    la contraseña de un intento de inicio de sesión fallido, o el correo de
    quien se acaba de dar de alta.

    Se recorre entero y se aplica la MISMA lista: dos listas de claves
    sensibles divergen, y la que menos se mira es la que se queda corta.
    """
    if isinstance(dato, dict):
        salida: dict[str, Any] = {}
        try:
            from crmcore.config import get_settings

            redactar_pii = get_settings().redactar_pii_resuelto
        except Exception:  # noqa: BLE001 — sin configuración, lo estricto
            redactar_pii = True
        for clave, valor in dato.items():
            minuscula = str(clave).lower()
            if minuscula in _CLAVES_SECRETAS:
                salida[clave] = "***"
            elif redactar_pii and minuscula in _CLAVES_PII and valor is not None:
                salida[clave] = _hash_pii(valor)
            else:
                salida[clave] = redactar_estructura(valor)
        return salida
    if isinstance(dato, list):
        return [redactar_estructura(v) for v in dato]
    return dato


def _contexto_peticion(_logger: Any, _metodo: str, evento: dict[str, Any]) -> dict[str, Any]:
    """Añade servicio, tenant, traza y usuario desde el contexto en curso.

    Se hace aquí, en un procesador, y no en cada `logger.info(...)`, porque lo
    que depende de que alguien se acuerde acaba faltando justo en el apunte que
    hacía falta para entender el incidente.
    """
    from crmcore.tenancy.context import contexto_actual

    ctx = contexto_actual()
    if ctx.tenant_id and "tenant_id" not in evento:
        evento["tenant_id"] = str(ctx.tenant_id)
    if ctx.user_id and "user_id" not in evento:
        evento["user_id"] = str(ctx.user_id)
    if ctx.request_id and "request_id" not in evento:
        evento["request_id"] = ctx.request_id
    if ctx.trace_id and "trace_id" not in evento:
        evento["trace_id"] = ctx.trace_id
    try:
        from crmcore.config import get_settings

        nombre = get_settings().service_name
        if nombre:
            evento.setdefault("service", nombre)
    except Exception:  # noqa: BLE001 — un log durante el arranque no debe romper el arranque
        pass
    return evento


def setup_logging(nivel: str | None = None, formato: str | None = None) -> None:
    """Configura structlog y el logging estándar. Idempotente."""
    global _configurado
    if _configurado:
        return

    try:
        from crmcore.config import get_settings

        s = get_settings()
        nivel = nivel or s.log_level
        formato = formato or s.formato_log_resuelto
    except Exception:  # noqa: BLE001 — sin config utilizable se arranca con lo básico
        nivel = nivel or "INFO"
        formato = formato or "consola"

    formatter = logging.Formatter(_FORMATO_STDLIB, datefmt=_FECHA_STDLIB)
    formatter.converter = time.gmtime  # UTC, para que los husos no despisten
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, nivel.upper(), logging.INFO))

    procesadores: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        _contexto_peticion,
        _censurar,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    procesadores.append(
        structlog.processors.JSONRenderer()
        if formato == "json"
        else structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())
    )

    structlog.configure(
        processors=procesadores,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, nivel.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    _configurado = True


def get_logger(nombre: str) -> Any:
    """Logger estructurado. Configura el logging si nadie lo ha hecho aún."""
    if not _configurado:
        setup_logging()
    return structlog.get_logger(nombre)


def reset_logging() -> None:
    """Olvida la configuración. Solo para pruebas que cambian el formato."""
    global _configurado
    _configurado = False
