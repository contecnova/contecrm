"""Trazas distribuidas con OpenTelemetry (CRM-00.06.01.03).

El contexto de traza ya viajaba: el middleware lee `traceparent`, lo propaga y
lo mete en cada línea de log. Eso resuelve «encuéntrame todo lo que pasó en esta
petición» mirando logs. Lo que faltaba es el **exportador**: mandar los tramos a
un colector para poder ver dónde se fue el tiempo entre cinco servicios, que es
la pregunta que los logs no contestan.

Tres decisiones, y la primera es la que más consecuencias tiene:

**OpenTelemetry es una dependencia opcional, y si se pide sin instalar, el
servicio no arranca.** Lo contrario —arrancar con las trazas apagadas en
silencio porque falta el paquete— es el fallo que se descubre el día que hace
falta la traza y no está. `TRACING_ENABLED=true` es una promesa; si no se puede
cumplir, hay que decirlo cuando se hace, no cuando se cobra.

**El formato de propagación es W3C Trace Context**, el mismo `traceparent` que
el middleware ya trataba a mano. Así una petición que entra desde un sistema que
ya traza —un gateway, un ESB— continúa su traza en vez de empezar una nueva, y
la instalación que no exporta nada sigue teniendo la correlación por log sin
instalar nada.

**Con el exportador apagado, esto cuesta cero.** No hay `import opentelemetry` en
el camino caliente: `span()` devuelve un contexto vacío y el middleware sigue
haciendo lo que hacía. Una biblioteca de observabilidad que penaliza a quien no
la usa acaba desactivada por otro motivo.

Qué se traza, y por qué esos tres:

  * **La petición HTTP**, que es la unidad que el usuario percibe.
  * **El paso de un proceso**, porque una orquestación que tarda dos días no se
    entiende con la traza de la petición que la arrancó — y es donde se pierde
    el tiempo de verdad.
  * **La salida hacia otro servicio o sistema externo**, que es donde está casi
    siempre la latencia que nadie se explica.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from crmcore.logging import get_logger

logger = get_logger(__name__)

# El proveedor configurado, o `None` si las trazas están apagadas. Se guarda
# aquí y no se consulta a OpenTelemetry en cada llamada porque lo que hay que
# evitar es justamente importar el paquete en el camino caliente.
_tracer: Any = None
# El proveedor que construimos, guardado aparte del global de OpenTelemetry. El
# tracer se saca de AQUÍ y no de `trace.get_tracer_provider()` por una razón
# concreta: el proveedor global solo se puede fijar una vez por proceso, y los
# `set_tracer_provider` siguientes se ignoran con un aviso. Tomando el tracer
# del nuestro, nuestros tramos van siempre al exportador que configuramos —
# aunque otra biblioteca haya fijado el global antes— y `reset()` cumple lo que
# promete en vez de dejar el primero puesto para siempre.
_proveedor: Any = None
_configurado = False
_candado = threading.Lock()

# Cabecera de propagación de W3C Trace Context. Está aquí y no en el middleware
# porque ahora la escriben dos sitios —la respuesta y las llamadas salientes— y
# tener el literal dos veces es como se acaban desincronizando.
H_TRACEPARENT = "traceparent"
H_TRACESTATE = "tracestate"


def configurar(nombre_servicio: str, version: str = "") -> bool:
    """Arranca el exportador si está pedido. Devuelve si quedó activo.

    Se llama una vez al arrancar el servicio. Si `TRACING_ENABLED` está puesto y
    OpenTelemetry no está instalado, **lanza**: ver la cabecera del módulo.
    """
    global _tracer, _proveedor, _configurado

    with _candado:
        if _configurado:
            return _tracer is not None
        _configurado = True

        from crmcore.config import get_settings

        s = get_settings()
        if not s.tracing_enabled:
            return False

        try:
            from opentelemetry import trace
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
        except ImportError as exc:
            raise RuntimeError(
                "TRACING_ENABLED está activo y OpenTelemetry no está instalado.\n"
                "  Instálalo:  pip install -r requirements-otel.txt\n"
                "  O apágalo:  TRACING_ENABLED=false\n"
                "Arrancar con las trazas apagadas en silencio es peor: el fallo "
                "se descubre el día que hace falta la traza y no está."
            ) from exc

        exportador = _crear_exportador(s.otel_endpoint, s.otel_protocolo)
        recurso = Resource.create(
            {
                "service.name": nombre_servicio,
                "service.version": version or "0",
                "deployment.environment": s.env,
            }
        )
        proveedor = TracerProvider(
            resource=recurso,
            # `ParentBased`: si la petición ya venía trazada, se respeta la
            # decisión de quien la empezó. Muestrear otra vez por nuestra cuenta
            # produciría trazas con agujeros —el tramo del servicio A está y el
            # del B no—, que es peor que no tener traza, porque parece un fallo.
            sampler=ParentBased(root=TraceIdRatioBased(s.otel_sample_ratio)),
        )
        proveedor.add_span_processor(BatchSpanProcessor(exportador))
        # Se fija también el global, para que una biblioteca auto-instrumentada
        # (SQLAlchemy, httpx) emita a nuestro colector. Es el mejor esfuerzo: si
        # alguien lo fijó antes, OpenTelemetry lo ignora con un aviso y nuestros
        # tramos siguen bien porque salen del proveedor de arriba.
        trace.set_tracer_provider(proveedor)
        _proveedor = proveedor
        _tracer = proveedor.get_tracer(nombre_servicio)

        logger.info(
            "trazas.activas",
            endpoint=s.otel_endpoint,
            protocolo=s.otel_protocolo,
            muestreo=s.otel_sample_ratio,
        )
        return True


def _crear_exportador(endpoint: str, protocolo: str) -> Any:
    """El exportador OTLP del protocolo pedido.

    Los dos existen porque los colectores reales no siempre aceptan los dos, y
    gRPC arrastra `grpcio`, que es una dependencia pesada que no todo el mundo
    quiere. Por defecto va HTTP, que es el que atraviesa proxies corporativos
    sin que nadie tenga que configurar nada.
    """
    if protocolo == "grpc":
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter as Grpc,
            )
        except ImportError as exc:
            raise RuntimeError(
                "OTEL_PROTOCOLO=grpc necesita `opentelemetry-exporter-otlp-proto-grpc`. "
                "Instálalo o usa OTEL_PROTOCOLO=http."
            ) from exc
        return Grpc(endpoint=endpoint)

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as Http

    return Http(endpoint=endpoint)


def activo() -> bool:
    return _tracer is not None


def proveedor() -> Any:
    """El `TracerProvider` configurado, o `None`. Para las pruebas y para quien
    quiera añadir un procesador propio."""
    return _proveedor


def reset() -> None:
    """Olvida la configuración. Solo para las pruebas.

    Sin esto, la primera prueba que configura trazas deja el proveedor puesto
    para todas las demás del mismo proceso, y una prueba que comprueba «apagado»
    pasaría o fallaría según el orden de ejecución.
    """
    global _tracer, _proveedor, _configurado
    with _candado:
        if _proveedor is not None:
            # Vaciar lo pendiente antes de soltarlo: si no, los tramos del
            # último trabajo se pierden al cerrar, que es justo cuando más falta
            # hacen si el cierre fue por un fallo.
            try:
                _proveedor.shutdown()
            except Exception:  # noqa: BLE001 — cerrar no puede impedir cerrar
                pass
        _tracer = None
        _proveedor = None
        _configurado = False


@contextmanager
def span(nombre: str, **atributos: Any) -> Iterator[Any]:
    """Abre un tramo, o no hace nada si las trazas están apagadas.

    Con el exportador apagado esto es un `yield None` y un `if`: es lo que
    permite sembrar el código de tramos sin que la instalación que no traza
    pague por ellos.
    """
    if _tracer is None:
        yield None
        return

    with _tracer.start_as_current_span(nombre) as tramo:
        for clave, valor in atributos.items():
            if valor is not None:
                tramo.set_attribute(clave, _atributo(valor))
        try:
            yield tramo
        except Exception as exc:
            # El tramo se marca como fallido Y se registra la excepción: sin lo
            # primero la traza sale verde cuando falló, y sin lo segundo no se
            # sabe de qué falló sin buscar el log a mano.
            from opentelemetry.trace import Status, StatusCode

            tramo.set_status(Status(StatusCode.ERROR, str(exc)[:200]))
            tramo.record_exception(exc)
            raise


def _atributo(valor: Any) -> Any:
    """OpenTelemetry solo admite escalares y listas de escalares."""
    if isinstance(valor, (str, bool, int, float)):
        return valor
    return str(valor)


def marcar(**atributos: Any) -> None:
    """Añade atributos al tramo en curso, si lo hay."""
    if _tracer is None:
        return
    from opentelemetry import trace

    tramo = trace.get_current_span()
    if tramo is None or not tramo.is_recording():
        return
    for clave, valor in atributos.items():
        if valor is not None:
            tramo.set_attribute(clave, _atributo(valor))


# ── Propagación ───────────────────────────────────────────────────────────


def inyectar(cabeceras: dict[str, str]) -> dict[str, str]:
    """Pone el contexto de traza en unas cabeceras salientes.

    Es la mitad que suele faltar. Sin ella cada servicio traza su trozo y no hay
    forma de unirlos, que es exactamente el problema que las trazas distribuidas
    vienen a resolver: se acaba con cinco trazas de un salto en vez de una de
    cinco.

    Cuando el exportador está apagado propaga igual el `traceparent` que llevaba
    la petición: la correlación por log entre servicios no debería depender de
    tener un colector montado.
    """
    if _tracer is not None:
        from opentelemetry.propagate import inject

        inject(cabeceras)
        return cabeceras

    from crmcore.tenancy.context import contexto_actual

    ctx = contexto_actual()
    if ctx.traceparent:
        cabeceras.setdefault(H_TRACEPARENT, ctx.traceparent)
    return cabeceras


def contexto_entrante(cabeceras: Mapping[str, str]) -> Any:
    """Reconstruye el contexto de traza de una petición entrante.

    Devuelve `None` con las trazas apagadas: el llamante sigue su camino sin
    tener que saber si hay exportador.
    """
    if _tracer is None:
        return None
    from opentelemetry.propagate import extract

    return extract(dict(cabeceras))


@contextmanager
def span_entrante(nombre: str, cabeceras: Mapping[str, str], **atributos: Any) -> Iterator[Any]:
    """Abre el tramo raíz de una petición, continuando la traza de quien llama."""
    if _tracer is None:
        yield None
        return

    from opentelemetry.trace import SpanKind

    with _tracer.start_as_current_span(
        nombre, context=contexto_entrante(cabeceras), kind=SpanKind.SERVER
    ) as tramo:
        for clave, valor in atributos.items():
            if valor is not None:
                tramo.set_attribute(clave, _atributo(valor))
        yield tramo


def traceparent_actual() -> str:
    """El `traceparent` del tramo en curso, en formato W3C.

    Existe para que el contexto del proceso (`crmcore.tenancy.context`) lleve el
    mismo identificador que la traza, y los logs y los tramos se puedan cruzar
    por él. Sin esto son dos mundos que hablan del mismo suceso con dos números
    distintos.
    """
    if _tracer is None:
        return ""
    from opentelemetry import trace

    contexto = trace.get_current_span().get_span_context()
    if not contexto.is_valid:
        return ""
    banderas = "01" if contexto.trace_flags.sampled else "00"
    return f"00-{contexto.trace_id:032x}-{contexto.span_id:016x}-{banderas}"
