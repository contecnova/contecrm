"""Bus de eventos, outbox y entrega de webhooks."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class _BusSettings(BaseSettings):
    # ── Backend del bus ───────────────────────────────────────────────────
    # nats     JetStream: persistencia, consumidores durables, replay y
    #          reparto entre réplicas. Es el de producción.
    # redis    Redis Streams: sirve donde ya hay Redis y no se quiere una pieza
    #          más; con grupos de consumidores da reparto y reintento.
    # memoria  En proceso, sin red. SOLO pruebas: productor y consumidor viven
    #          en el mismo proceso y no hay nada que limpiar.
    #
    # El código de negocio no sabe cuál está activo: publica contra
    # `crmcore.bus.Bus` y el backend se elige aquí (CRM-00.02.02.05).
    bus_backend: Literal["nats", "redis", "memoria"] = "nats"

    nats_url: str = "nats://localhost:4222"
    redis_url: str = "redis://localhost:6379/0"

    # Prefijo de todos los subjects. Aísla despliegues que compartan broker
    # (un NATS común para pre-producción y demo, por ejemplo).
    bus_prefix: str = "contecrm"

    # ── Outbox (CRM-00.03.02.06) ──────────────────────────────────────────
    # El evento se escribe en la MISMA transacción que el cambio que lo
    # provoca, y un relevo lo publica después. Es lo que impide el estado
    # imposible: oportunidad ganada en la base y nadie enterado en el bus.
    #
    # El precio es entrega at-least-once —un evento puede publicarse dos veces
    # si el proceso muere entre publicar y marcar—, y por eso TODO consumidor
    # es idempotente por `dedup_key` (CRM-00.02.02.04).
    outbox_enabled: bool = True
    # Cuántos eventos publica el relevo por vuelta. Lotes grandes reducen
    # viajes pero alargan el bloqueo de las filas tomadas.
    outbox_lote: int = Field(100, ge=1, le=10_000)
    # Cada cuánto vuelve a mirar si hay pendientes cuando la última vuelta salió
    # vacía. Con eventos esperando publica de seguido, sin esperar.
    outbox_intervalo_s: float = Field(1.0, ge=0.05, le=60.0)
    # Intentos antes de mandar el evento a la cola de fallidos. Con backoff
    # exponencial, 8 intentos cubren varios minutos de caída del broker.
    outbox_max_intentos: int = Field(8, ge=1, le=100)
    # Base del backoff exponencial entre intentos, en segundos.
    outbox_backoff_base_s: float = Field(2.0, ge=0.1, le=300.0)

    # ── Inbox (deduplicación en el consumo) ───────────────────────────────
    # Registro de `dedup_key` ya procesadas. Es lo que convierte la entrega
    # at-least-once en efecto exactly-once desde fuera.
    inbox_enabled: bool = True
    # Cuánto se recuerda una clave. Debe cubrir de sobra la ventana de
    # reintentos del productor; una semana la cubre con holgura.
    inbox_retencion_dias: int = Field(7, ge=1, le=365)

    # ── Webhooks salientes (CRM-00.02.02.01..03) ──────────────────────────
    webhooks_enabled: bool = True
    webhook_timeout_s: float = Field(10.0, ge=0.5, le=120.0)
    webhook_max_intentos: int = Field(6, ge=1, le=50)
    webhook_backoff_base_s: float = Field(5.0, ge=0.5, le=600.0)
    # Ventana en la que se acepta la firma de una petición entrante, para que
    # un mensaje capturado no se pueda reenviar más tarde (anti-replay).
    webhook_firma_ventana_s: int = Field(300, ge=30, le=3600)
    # Tamaño máximo del cuerpo que se entrega. Un payload gigante es casi
    # siempre un error de diseño y además revienta al receptor.
    webhook_max_payload_kb: int = Field(256, ge=1, le=10_240)
