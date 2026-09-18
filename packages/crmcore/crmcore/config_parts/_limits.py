"""Límites, cuotas y resiliencia: lo que impide que un tenant tumbe a los demás."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class _LimitsSettings(BaseSettings):
    # ── Rate limiting (CRM-00.01.06.01) ───────────────────────────────────
    rate_limit_enabled: bool = True
    # Ventana de conteo. Una ventana corta reacciona antes a una ráfaga; una
    # larga tolera mejor el tráfico a golpes de un proceso por lotes.
    rate_limit_ventana_s: int = Field(60, ge=1, le=3600)
    # Topes por dimensión. Se aplican TODOS: el más restrictivo manda. Están
    # separados porque el abuso tiene formas distintas — un usuario con un
    # bucle, una integración mal configurada, un tenant entero desbocado.
    rate_limit_por_usuario: int = Field(600, ge=0, le=1_000_000)
    rate_limit_por_api_key: int = Field(3_000, ge=0, le=1_000_000)
    rate_limit_por_tenant: int = Field(6_000, ge=0, le=10_000_000)
    rate_limit_por_ip: int = Field(1_200, ge=0, le=1_000_000)

    # ── Tamaños de petición y respuesta ───────────────────────────────────
    max_body_mb: int = Field(25, ge=1, le=1024)
    # Tope de elementos en una operación masiva (CRM-00.02.01.11). Por encima,
    # la API obliga a usar el camino asíncrono con job id, que es el que tiene
    # progreso, reanudación e informe parcial.
    bulk_max_items: int = Field(1_000, ge=1, le=100_000)
    # Tope de operaciones en una petición compuesta (CRM-00.02.01.13).
    composite_max_ops: int = Field(25, ge=1, le=500)
    # Página máxima que se puede pedir. Sin tope, un `limit=1000000` es una
    # denegación de servicio escrita por el propio cliente sin querer.
    page_max_size: int = Field(200, ge=1, le=10_000)
    page_default_size: int = Field(50, ge=1, le=1_000)

    # ── Tiempos ───────────────────────────────────────────────────────────
    # Timeout de una llamada entre servicios. Corto: encadenar tres llamadas
    # con timeouts largos convierte un servicio lento en una caída general.
    http_interno_timeout_s: float = Field(10.0, ge=0.5, le=300.0)
    # Timeout de una llamada a un sistema externo (ERP, firma, telefonía).
    # Más largo porque no controlamos su latencia, pero acotado igual.
    http_externo_timeout_s: float = Field(30.0, ge=1.0, le=600.0)
    # Una petición que pasa de aquí se corta y devuelve 504. Existe para que
    # una consulta patológica no retenga una conexión del pool indefinidamente.
    request_timeout_s: float = Field(60.0, ge=1.0, le=900.0)

    # ── Circuit breaker (CRM-00.01.06.03) ─────────────────────────────────
    circuit_breaker_enabled: bool = True
    # Fallos consecutivos que abren el circuito.
    cb_umbral_fallos: int = Field(5, ge=1, le=1000)
    # Tiempo que permanece abierto antes de dejar pasar una petición de prueba.
    cb_reposo_s: int = Field(30, ge=1, le=3600)

    # ── Degradación bajo carga (CRM-00.01.06.04) ──────────────────────────
    degradacion_enabled: bool = True
    # Uso del pool de conexiones (0..1) a partir del cual se difiere lo no
    # crítico: recálculos, enriquecimientos, informes programados. Se difiere,
    # no se pierde.
    degradacion_umbral_pool: float = Field(0.85, ge=0.1, le=1.0)

    # ── Motor de procesos (CRM-00.03.02.16) ───────────────────────────────
    # Topes que impiden un proceso desbocado. Sin ellos, una automatización que
    # se dispara a sí misma consume el sistema entero.
    proceso_max_pasos: int = Field(1_000, ge=1, le=1_000_000)
    proceso_max_profundidad: int = Field(10, ge=1, le=100)
    proceso_max_duracion_h: int = Field(720, ge=1, le=8760)
    # Cadena máxima de automatizaciones que se disparan unas a otras
    # (CRM-00.03.03.06).
    automatizacion_max_cascada: int = Field(5, ge=1, le=100)
