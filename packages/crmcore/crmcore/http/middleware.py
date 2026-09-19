"""Middleware ASGI puro: contexto, correlación, tiempos y límites.

**Por qué ASGI puro y no `BaseHTTPMiddleware`.** Starlette ejecuta la aplicación
de debajo de un `BaseHTTPMiddleware` en otra tarea de asyncio, y una tarea nueva
recibe una COPIA del contexto: lo que se fije en el middleware no lo ve el
endpoint. Como aquí lo que se fija es el tenant, usar el middleware cómodo
significaría que el aislamiento por tenant no llega a la consulta. No es una
preferencia de estilo; es la diferencia entre funcionar y no funcionar.

El orden en que se montan (el último añadido es el más externo) importa:

    1. Contexto      — el más externo: todo lo demás necesita `request_id`.
    2. Tiempos       — mide lo que tardan los de dentro.
    3. Límites       — rechaza antes de tocar la base de datos.
    4. Idempotencia  — el más interno: solo llega aquí lo que ya pasó los límites
                       y tiene tenant, que es lo que la clave necesita.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from crmcore.ids import nuevo_id
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Rutas que no generan telemetría de negocio ni exigen tenant. Se listan aquí y
# no se detectan por heurística para que añadir una sea una decisión visible.
RUTAS_INFRAESTRUCTURA = frozenset({"/health", "/health/ready", "/health/live", "/metrics"})


def _cabecera(scope: Scope, nombre: str) -> str:
    """Lee una cabecera del scope ASGI, sin distinguir mayúsculas."""
    objetivo = nombre.lower().encode()
    for clave, valor in scope.get("headers", []):
        if clave == objetivo:
            return valor.decode("latin-1")
    return ""


class ContextoMiddleware:
    """Fija el contexto de la petición y propaga la correlación (CRM-00.02.04.07).

    Resuelve la pista de tenant (cabecera o subdominio) pero **no concede acceso
    con ella**: la identidad autoritativa la establece la capa de autenticación,
    que compara con esta pista y rechaza si se contradicen. Aquí solo se deja
    preparado el contexto para que los logs de la propia autenticación ya salgan
    con tenant.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from crmcore.config import get_settings
        from crmcore.tenancy.context import ContextoPeticion, fijar_contexto, restaurar_contexto
        from crmcore.tenancy.resolver import pista_por_cabecera, pista_por_host

        s = get_settings()

        # Se respeta el `X-Request-Id` entrante si viene: así una petición que
        # atraviesa gateway → servicio → servicio conserva un único hilo en los
        # logs. Si no viene, se genera aquí.
        request_id = _cabecera(scope, "x-request-id") or str(nuevo_id())
        # `traceparent` es el formato de W3C Trace Context, que es lo que
        # entienden OpenTelemetry y los proxies. Se propaga tal cual.
        traceparent = _cabecera(scope, "traceparent")
        trace_id = traceparent.split("-")[1] if traceparent.count("-") >= 3 else request_id

        pista = pista_por_cabecera(_cabecera(scope, s.tenant_header)) or pista_por_host(
            _cabecera(scope, "host"), s.tenant_root_domain
        )

        ctx = ContextoPeticion(
            tenant_slug=pista,
            request_id=request_id,
            trace_id=trace_id,
            origen="api",
        )
        token = fijar_contexto(ctx)

        async def send_con_correlacion(message: Message) -> None:
            if message["type"] == "http.response.start":
                cabeceras = list(message.get("headers", []))
                cabeceras.append((b"x-request-id", request_id.encode()))
                if traceparent:
                    cabeceras.append((b"traceparent", traceparent.encode()))
                # Aviso de retirada de la versión de API, si hay fecha anunciada
                # (CRM-00.02.01.07). Va en TODA respuesta: es el único canal que
                # el integrador ya está leyendo.
                if s.api_sunset_date:
                    cabeceras.append((b"sunset", s.api_sunset_date.encode()))
                    cabeceras.append((b"deprecation", b"true"))
                message["headers"] = cabeceras
            await send(message)

        try:
            await self.app(scope, receive, send_con_correlacion)
        finally:
            restaurar_contexto(token)


class TiemposMiddleware:
    """Mide, registra y publica la duración de cada petición.

    Alimenta el objetivo de latencia p95/p99 por tenant (CRM-08.01.01.01). La
    métrica se emite siempre; el apunte de log solo cuando la petición es lenta
    o falla, porque un apunte por petición en un sistema con tráfico es ruido
    que acaba haciendo que nadie mire los logs.
    """

    def __init__(self, app: ASGIApp, *, umbral_lento_s: float = 1.0) -> None:
        self.app = app
        self._umbral = umbral_lento_s

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in RUTAS_INFRAESTRUCTURA:
            await self.app(scope, receive, send)
            return

        inicio = time.perf_counter()
        estado: dict[str, Any] = {"status": 500}

        async def send_midiendo(message: Message) -> None:
            if message["type"] == "http.response.start":
                estado["status"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_midiendo)
        finally:
            duracion = time.perf_counter() - inicio
            # La plantilla de ruta (`/accounts/{id}`) y no la ruta concreta: con
            # la concreta habría una serie de métricas por identificador, y eso
            # tumba a Prometheus en una tarde.
            ruta = _plantilla_de_ruta(scope)
            from crmcore.obs.metrics import observar_peticion

            observar_peticion(
                metodo=scope.get("method", ""),
                ruta=ruta,
                status=estado["status"],
                duracion_s=duracion,
            )
            if duracion >= self._umbral or estado["status"] >= 500:
                logger.warning(
                    "http.peticion_lenta" if estado["status"] < 500 else "http.peticion_fallida",
                    metodo=scope.get("method", ""),
                    ruta=ruta,
                    status=estado["status"],
                    duracion_ms=round(duracion * 1000, 1),
                )


def _plantilla_de_ruta(scope: Scope) -> str:
    """Ruta con los parámetros sin sustituir, para agrupar métricas.

    Starlette deja la ruta resuelta en `scope["route"]` después de enrutar. Si
    todavía no hay (404, o se pregunta antes), se devuelve `desconocida` en vez
    de la ruta literal: una ruta inexistente con un identificador dentro también
    dispararía la cardinalidad.
    """
    ruta = scope.get("route")
    plantilla = getattr(ruta, "path", None)
    return plantilla or "desconocida"


class LimitesMiddleware:
    """Rate limiting y tamaño máximo de cuerpo (CRM-00.01.06.01).

    Va lo más fuera posible dentro de la aplicación: rechazar aquí cuesta una
    consulta a Redis, y rechazar después de haber abierto una transacción y
    leído la base cuesta mucho más — que es exactamente lo que no interesa
    cuando alguien está desbordando el sistema.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in RUTAS_INFRAESTRUCTURA:
            await self.app(scope, receive, send)
            return

        from crmcore.config import get_settings

        s = get_settings()

        longitud = _cabecera(scope, "content-length")
        if longitud.isdigit() and int(longitud) > s.max_body_mb * 1024 * 1024:
            from crmcore.errors import CuerpoDemasiadoGrande

            await _responder_error(
                send,
                CuerpoDemasiadoGrande(
                    f"El cuerpo supera el máximo de {s.max_body_mb} MB",
                    error_code="http.cuerpo_demasiado_grande",
                    detalle={"maximo_mb": s.max_body_mb},
                ),
                scope,
            )
            return

        if s.rate_limit_enabled:
            from crmcore.errors import LimiteExcedido
            from crmcore.http.rate_limit import comprobar_limites

            try:
                await comprobar_limites(scope)
            except LimiteExcedido as exc:
                await _responder_error(send, exc, scope)
                return

        await self.app(scope, receive, send)


class IdempotenciaMiddleware:
    """Guarda la respuesta de una escritura idempotente (CRM-00.02.01.08).

    Es **la segunda mitad**. La primera —reservar la clave— la hace una
    dependencia global (`crmcore.http.idempotency.dependencia`), y están
    separadas por un motivo que costó descubrir: **el middleware corre antes de
    la autenticación**, así que aquí todavía no se sabe qué tenant es.

    Usar la pista de tenant de la cabecera sin verificar habría parecido que
    funcionaba, y habría sido una fuga: quien mintiera sobre su tenant podría
    recibir la respuesta guardada de otro cliente, con su contenido dentro. La
    clave se reserva donde la identidad ya está comprobada, y aquí solo se
    captura el resultado.

    Qué hace falta de un middleware, entonces: el **cuerpo de la respuesta**, que
    una dependencia no ve. Por eso esta mitad sigue aquí.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        estado: dict[str, Any] = {"status": 0, "cuerpo": b""}

        async def _capturar(mensaje: Message) -> None:
            if mensaje["type"] == "http.response.start":
                estado["status"] = mensaje["status"]
            elif mensaje["type"] == "http.response.body":
                estado["cuerpo"] += mensaje.get("body", b"")
            await send(mensaje)

        await self.app(scope, receive, _capturar)

        # La dependencia deja aquí la clave que reservó. Si no hay nada, esta
        # petición no era idempotente y no hay nada que guardar.
        reserva = (scope.get("state") or {}).get("idempotencia")
        if reserva:
            await _guardar_respuesta(reserva["clave"], reserva["tenant_id"], estado)


async def _guardar_respuesta(clave: str, tenant_id: UUID, estado: dict[str, Any]) -> None:
    """Guarda la respuesta, o libera la clave si la operación falló.

    Una operación fallida **libera** la clave: si se guardara el error, el
    cliente que reintenta tras arreglar su problema recibiría para siempre el
    fallo de la primera vez.
    """
    import json

    from crmcore.db.session import nueva_sesion
    from crmcore.http.idempotency import completar, fallar

    db = nueva_sesion(tenant_id)
    try:
        if estado["status"] >= 400:
            fallar(db, clave=clave, tenant_id=tenant_id, error=f"HTTP {estado['status']}")
        else:
            try:
                cuerpo = json.loads(estado["cuerpo"]) if estado["cuerpo"] else None
            except ValueError:
                # Una respuesta que no es JSON —un fichero, un XML— no se
                # guarda: repetirla exigiría almacenar el binario entero, y para
                # eso está volver a pedirla.
                cuerpo = None
            completar(db, clave=clave, tenant_id=tenant_id, status=estado["status"], cuerpo=cuerpo)
        db.commit()
    except Exception as exc:  # noqa: BLE001 — no puede tumbar una respuesta ya enviada
        logger.error("idempotencia.fallo_al_guardar", error=str(exc)[:200])
        db.rollback()
    finally:
        db.close()


async def _responder_error(send: Send, exc: Any, scope: Scope) -> None:
    """Responde un Problem Details sin pasar por la aplicación.

    Hace falta porque un middleware ASGI puro está por fuera de los manejadores
    de excepción de FastAPI: si lanzara, la excepción saldría por el servidor
    como un 500 sin formato.
    """
    import json

    from crmcore.http.problems import CONTENT_TYPE
    from crmcore.tenancy.context import contexto_actual

    problema = exc.a_problema(
        instancia=scope.get("path", ""), request_id=contexto_actual().request_id
    )
    cuerpo = json.dumps(problema, ensure_ascii=False).encode()
    cabeceras = [
        (b"content-type", CONTENT_TYPE.encode()),
        (b"content-length", str(len(cuerpo)).encode()),
    ]
    reintentar = getattr(exc, "reintentar_en_s", None)
    if reintentar:
        cabeceras.append((b"retry-after", str(int(reintentar)).encode()))
    await send({"type": "http.response.start", "status": exc.status_code, "headers": cabeceras})
    await send({"type": "http.response.body", "body": cuerpo})


def fijar_identidad_en_contexto(
    *,
    tenant_id: UUID | None,
    user_id: UUID | None,
    scopes: frozenset[str],
    es_admin_plataforma: bool = False,
    actor_real_id: UUID | None = None,
) -> None:
    """Completa el contexto con la identidad ya verificada.

    Lo llama la dependencia de autenticación, no el middleware: el middleware
    corre antes de que se sepa quién es nadie. Se reemplaza el contexto entero
    (es inmutable) en vez de mutarlo.
    """
    from dataclasses import replace

    from crmcore.tenancy.context import contexto_actual, fijar_contexto

    fijar_contexto(
        replace(
            contexto_actual(),
            tenant_id=tenant_id,
            user_id=user_id,
            scopes=scopes,
            es_admin_plataforma=es_admin_plataforma,
            actor_real_id=actor_real_id,
        )
    )
