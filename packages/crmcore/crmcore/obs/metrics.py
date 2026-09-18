"""Métricas Prometheus, con la cardinalidad controlada.

El catálogo pide métricas **por tenant** (CRM-00.06.01.02), y ahí está la
trampa: una etiqueta por tenant multiplica cada serie por el número de tenants.
Con veinte tenants es útil; con cinco mil, Prometheus se queda sin memoria y se
pierden también las métricas que sí importaban.

La solución es un tope (`metrics_max_tenants`): los primeros N tenants vistos
llevan su etiqueta y el resto se agrupan en `otros`. Así el panel por cliente
funciona donde tiene sentido y el sistema no se cae donde no lo tiene. El tope
es configurable, claro, porque cuál es el número correcto depende del despliegue.
"""

from __future__ import annotations

import threading
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

# Registro propio en vez del global: el global recoge además las métricas del
# proceso de Python (GC, descriptores), que no aportan aquí y ensucian.
REGISTRO = CollectorRegistry()

# Buckets pensados para una API de negocio: mucha resolución en los
# milisegundos, donde vive el p95, y colas largas para ver los casos malos.
# Los de por defecto de la librería empiezan en 5 ms y saltan demasiado pronto.
BUCKETS_LATENCIA = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

peticiones = Counter(
    "crm_http_peticiones_total",
    "Peticiones HTTP atendidas",
    ["service", "metodo", "ruta", "status", "tenant"],
    registry=REGISTRO,
)
latencia = Histogram(
    "crm_http_duracion_segundos",
    "Duración de las peticiones HTTP",
    ["service", "metodo", "ruta", "tenant"],
    buckets=BUCKETS_LATENCIA,
    registry=REGISTRO,
)
eventos_publicados = Counter(
    "crm_eventos_publicados_total",
    "Eventos de dominio publicados en el bus",
    ["service", "tipo", "tenant"],
    registry=REGISTRO,
)
eventos_consumidos = Counter(
    "crm_eventos_consumidos_total",
    "Eventos de dominio consumidos",
    ["service", "tipo", "resultado"],
    registry=REGISTRO,
)
outbox_pendientes = Gauge(
    "crm_outbox_pendientes",
    "Eventos esperando publicación en la tabla de salida",
    ["service"],
    registry=REGISTRO,
)
# La antigüedad del pendiente más viejo dice mucho más que cuántos hay: mil
# eventos publicándose sin parar es normal; uno atascado desde hace una hora es
# un incidente.
outbox_antiguedad = Gauge(
    "crm_outbox_antiguedad_segundos",
    "Antigüedad del evento pendiente más viejo",
    ["service"],
    registry=REGISTRO,
)
limites_aplicados = Counter(
    "crm_limites_aplicados_total",
    "Peticiones rechazadas por límite de uso",
    ["service", "dimension", "tenant"],
    registry=REGISTRO,
)
cuota_consumida = Gauge(
    "crm_cuota_consumida_pct",
    "Porcentaje de cuota consumido por tenant",
    ["service", "cuota", "tenant"],
    registry=REGISTRO,
)
procesos_activos = Gauge(
    "crm_procesos_activos",
    "Instancias de proceso en ejecución",
    ["service", "definicion"],
    registry=REGISTRO,
)

_tenants_vistos: set[str] = set()
_lock = threading.Lock()


def _etiqueta_tenant() -> str:
    """Etiqueta de tenant con tope de cardinalidad."""
    from crmcore.config import get_settings
    from crmcore.tenancy.context import contexto_actual

    s = get_settings()
    if not s.metrics_por_tenant:
        return "-"
    ctx = contexto_actual()
    if ctx.tenant_id is None:
        return "-"
    clave = ctx.tenant_slug or str(ctx.tenant_id)
    if clave in _tenants_vistos:
        return clave
    with _lock:
        if len(_tenants_vistos) >= s.metrics_max_tenants:
            return "otros"
        _tenants_vistos.add(clave)
    return clave


def _servicio() -> str:
    from crmcore.config import get_settings

    return get_settings().service_name or "desconocido"


def observar_peticion(*, metodo: str, ruta: str, status: int, duracion_s: float) -> None:
    """Registra una petición atendida. Nunca lanza.

    Que no lance es un requisito, no una cortesía: una métrica rota no puede
    tumbar una petición que por lo demás fue bien.
    """
    try:
        svc, tenant = _servicio(), _etiqueta_tenant()
        peticiones.labels(svc, metodo, ruta, str(status), tenant).inc()
        latencia.labels(svc, metodo, ruta, tenant).observe(duracion_s)
    except Exception:  # noqa: BLE001 — ver docstring
        pass


def observar_evento_publicado(tipo: str) -> None:
    try:
        eventos_publicados.labels(_servicio(), tipo, _etiqueta_tenant()).inc()
    except Exception:  # noqa: BLE001 — la telemetría no rompe el flujo
        pass


def observar_evento_consumido(tipo: str, resultado: str) -> None:
    try:
        eventos_consumidos.labels(_servicio(), tipo, resultado).inc()
    except Exception:  # noqa: BLE001 — la telemetría no rompe el flujo
        pass


def observar_limite(dimension: str) -> None:
    try:
        limites_aplicados.labels(_servicio(), dimension, _etiqueta_tenant()).inc()
    except Exception:  # noqa: BLE001 — la telemetría no rompe el flujo
        pass


def exportar() -> bytes:
    """Cuerpo de la respuesta de `/metrics`."""
    return generate_latest(REGISTRO)


def reset_metricas() -> None:
    """Olvida los tenants vistos. Solo para pruebas de cardinalidad."""
    with _lock:
        _tenants_vistos.clear()


def _tipos_sin_usar(*_a: Any) -> None:  # pragma: no cover
    """Mantiene el import de `Any` para las anotaciones."""
