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
    # equivocado. `crmcore.service.crear_servicio()` lo exige.
    service_name: str = ""
    service_version: str = "0.1.0"

    # Entorno de ejecución (CRM-07.02.01.01: desarrollo, pruebas, UAT y
    # producción son despliegues separados, distinguidos por este valor).
    #
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

    # Los servicios DE ESTE DESPLIEGUE, como `nombre=url` separados por comas:
    # `tenancy=http://tenancy:8000,party=http://party:8000`.
    #
    # Lo lee el gateway para enrutar —un servicio que no esté aquí no es
    # alcanzable y responde 503 diciendo cuál falta, que es mejor que un 404
    # genérico— y lo lee `tenancy` para saber **quién tiene que contestar** al
    # inventario documental del certificado de destrucción (RT-5). Sin la lista,
    # ese certificado daría por completa una respuesta a la que le faltan
    # servicios enteros.
    #
    # Va en configuración y no en código para que añadir un servicio sea
    # desplegarlo, no editar y volver a publicar.
    rutas_servicios: str = ""

    # URL base pública del sistema, usada para componer enlaces absolutos
    # (callbacks de OAuth, enlaces de correo, URLs firmadas). Sin esto los
    # enlaces salen relativos y rotos en el correo.
    public_base_url: str = "http://localhost:18080"

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

    # ── Interfaz ──────────────────────────────────────────────────────────
    # Densidad por defecto de la interfaz.
    #
    # «compacta» cabe mucho más en pantalla y es lo que quiere quien trabaja
    # aquí ocho horas: catorce filas de una lista en vez de cuatro. «comoda» da
    # aire y se lee de lejos, que es lo que hace falta en una demostración o en
    # una pantalla compartida.
    #
    # Esto es el DEFECTO DEL DESPLIEGUE, no la preferencia de nadie: cada
    # persona puede fijar la suya y la suya manda. Está aquí, y no a fuego en
    # el front, para que una instalación entera pueda arrancar en cómoda sin
    # tocar código ni reconstruir la imagen.
    ui_densidad: Literal["compacta", "comoda"] = "compacta"
