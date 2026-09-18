"""Identidad del servicio y entorno de ejecución."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class _AppSettings(BaseSettings):
    # ── Identidad del servicio ────────────────────────────────────────────
    # Cada proceso declara qué servicio es. Lo usan los logs, las métricas
    # (etiqueta `service`), el bus (nombre del consumidor durable), el esquema
    # de base de datos que le toca y el registro de servicios.
    #
    # No tiene default útil a propósito: un proceso que no sabe qué servicio es
    # produce telemetría inservible y, peor, podría conectarse al esquema
    # equivocado. `crmcore.service.create_service()` lo exige.
    service_name: str = ""
    service_version: str = "0.1.0"

    # "prod" por defecto para que un despliegue que se olvide de poner ENV pase
    # por la verificación estricta de secretos en vez de saltársela (el error
    # seguro es fallar al arrancar, no arrancar inseguro).
    env: Literal["dev", "staging", "prod"] = "prod"

    # Nombre del producto en textos visibles (correos, cabeceras, títulos de
    # OpenAPI). Configurable porque la marca blanca (CRM-00.01.04.06) lo cambia.
    app_name: str = "contecrm"

    # ── Red ───────────────────────────────────────────────────────────────
    # Puerto en el que escucha este servicio. Lo leen uvicorn (arranque),
    # el healthcheck de compose y el gateway (enrutado). Boot-only: cambiarlo
    # en caliente no reabre el socket.
    service_host: str = "127.0.0.1"
    service_port: int = Field(8000, ge=1, le=65535)

    # URL base pública del sistema, usada para componer enlaces absolutos
    # (callbacks de OAuth, enlaces de correo, URLs firmadas). Sin esto los
    # enlaces salen relativos y rotos en el correo.
    public_base_url: str = "http://localhost:8080"

    # ── Orígenes permitidos (CORS) ────────────────────────────────────────
    # Lista separada por comas. Vacío = ningún origen de navegador permitido,
    # que es lo correcto para un servicio interno: solo el gateway habla con él.
    cors_origins: str = ""

    # ── Contrato de API ───────────────────────────────────────────────────
    # Prefijo de versión de la API pública. El versionado es explícito y por
    # URI (CRM-00.02.01.05): un cambio rompedor estrena `v2` y `v1` sigue
    # sirviéndose hasta su fecha de retirada.
    api_prefix: str = "/api/v1"

    # Fecha de retirada de ESTA versión mayor, en ISO-8601, o vacío si no hay
    # una anunciada. Cuando está puesta, toda respuesta lleva las cabeceras
    # `Sunset` y `Deprecation` (CRM-00.02.01.07) para que los consumidores se
    # enteren por el canal que ya están leyendo, sin depender de una circular.
    api_sunset_date: str = ""

    # Documentación interactiva. Se puede apagar en producción si el operador
    # prefiere no publicar el esquema, aunque por defecto va encendida: un
    # sistema headless sin documentación navegable es mucho peor que uno que
    # enseña su contrato.
    api_docs_enabled: bool = True
