"""Observabilidad: logs, métricas, trazas y auditoría."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings


class _ObsSettings(BaseSettings):
    # ── Logs (CRM-00.06.01.01) ────────────────────────────────────────────
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    # json en producción (lo consume el agregador), consola en desarrollo (lo
    # lee una persona). `auto` decide por `env`.
    log_format: Literal["auto", "json", "consola"] = "auto"
    # Hashear PII (correos, IPs, user-agents) en los logs. `None` = encendido
    # fuera de desarrollo y apagado en desarrollo, donde poder buscar un correo
    # en el log es justo lo que se necesita para depurar.
    log_redact_pii: bool | None = None
    # Cuerpo de las peticiones en el log. Apagado: es la vía más rápida de
    # filtrar datos personales a un sistema de logs que no está pensado para
    # guardarlos.
    log_request_body: bool = False

    # ── Métricas (CRM-00.06.01.02) ────────────────────────────────────────
    metrics_enabled: bool = True
    metrics_path: str = "/metrics"
    # Etiquetar las métricas con el tenant. Da visibilidad por cliente, que es
    # lo que pide el catálogo, pero multiplica las series por el número de
    # tenants: con miles de tenants hay que apagarlo o muestrear.
    metrics_por_tenant: bool = True
    # Tope de tenants distintos etiquetados. Pasado el tope, el resto se agrupa
    # en `otros`. Es lo que evita que la cardinalidad tumbe a Prometheus.
    metrics_max_tenants: int = Field(200, ge=1, le=10_000)

    # ── Trazas (CRM-00.06.01.03) ──────────────────────────────────────────
    # Apagado por defecto. Encenderlo SIN el paquete instalado impide arrancar,
    # a propósito: arrancar en silencio sin trazas es el fallo que se descubre
    # el día que hace falta la traza.
    tracing_enabled: bool = False
    # Por defecto el puerto OTLP/HTTP del colector (4318). El de gRPC es el 4317.
    otel_endpoint: str = "http://localhost:4318/v1/traces"
    # `http` no arrastra `grpcio` y atraviesa proxies corporativos sin
    # configurar nada; `grpc` es el que piden algunos colectores.
    otel_protocolo: Literal["http", "grpc"] = "http"
    # Fracción de peticiones trazadas (0..1). 1.0 en desarrollo; en producción
    # se baja porque el coste es real y una muestra basta para ver la forma.
    otel_sample_ratio: float = Field(0.1, ge=0.0, le=1.0)

    # ── Auditoría (CRM-00.05.04) ──────────────────────────────────────────
    audit_enabled: bool = True
    # Encadenar cada apunte con el hash del anterior. Convierte el log en
    # verificable: si alguien borra o edita una fila, la cadena se rompe y se
    # puede demostrar. Cuesta un hash por apunte.
    audit_hash_chain: bool = True
    # Retención antes de archivar o purgar (CRM-00.05.04.04). Seis años cubre
    # los plazos mercantiles habituales en España.
    audit_retencion_dias: int = Field(2190, ge=30, le=36_500)
    # Exportación a SIEM: destino syslog/HTTP. Vacío = no se exporta.
    audit_siem_url: str = ""

    # ── Notificaciones salientes (CRM-06.02.01.02) ────────────────────────
    # SMTP y no la API de un proveedor: lo hablan todos —SendGrid, SES,
    # Mailgun— y también el servidor corporativo del cliente que no quiere que
    # su correo salga de su red. Cambiar de proveedor es cambiar estas líneas,
    # no desplegar código.
    #
    # Vacío = no hay correo. Los avisos se quedan en la cola con su motivo, y no
    # se descartan: es un fallo de configuración que alguien va a arreglar.
    smtp_host: str = ""
    smtp_puerto: int = Field(587, ge=1, le=65_535)
    smtp_usuario: str = ""
    smtp_clave: SecretStr = SecretStr("")
    # `starttls` es lo normal en el 587; `ssl` en el 465; `ninguno` solo tiene
    # sentido contra un relé de la propia red, y con credenciales se rechaza.
    smtp_tls: Literal["starttls", "ssl", "ninguno"] = "starttls"
    smtp_remitente: str = ""
    smtp_timeout_s: float = Field(20.0, ge=1.0, le=300.0)

    # Reparto: cuántos avisos por vuelta y cuánto se espera entre reintentos.
    # La espera crece con el intento (1 min, 4, 9, 16…): un proveedor caído diez
    # minutos no puede costar diez minutos de avisos perdidos, y uno caído tres
    # días no puede costar tres días de reintentos.
    notificacion_lote: int = Field(100, ge=1, le=5_000)
    notificacion_max_intentos: int = Field(5, ge=1, le=50)
    notificacion_espera_base_s: int = Field(60, ge=1, le=3_600)
    notificacion_espera_vacio_s: float = Field(5.0, ge=0.1, le=300.0)

    # ── Salud ─────────────────────────────────────────────────────────────
    # Tiempo máximo que puede tardar una comprobación de readiness antes de
    # darla por fallida. Corto: un readiness lento hace que el orquestador
    # crea que el servicio está caído.
    health_check_timeout_s: float = Field(3.0, ge=0.1, le=30.0)
