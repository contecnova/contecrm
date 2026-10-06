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
from crmcore.obs import trazas

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


def _cabeceras(scope: Scope) -> dict[str, str]:
    """Todas las cabeceras como diccionario, para el extractor de propagación.

    OpenTelemetry espera un mapa, y el `scope` ASGI trae una lista de pares de
    bytes. Se construye solo cuando hay que extraer contexto.
    """
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


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
            traceparent=traceparent,
            origen="api",
        )
        token = fijar_contexto(ctx)

        async def send_con_correlacion(message: Message) -> None:
            if message["type"] == "http.response.start":
                cabeceras = list(message.get("headers", []))
                cabeceras.append((b"x-request-id", request_id.encode()))
                # Se devuelve el `traceparent` del tramo en curso si hay
                # exportador, y el entrante si no. Devolver el entrante cuando
                # sí se traza daría al cliente el identificador del padre y no
                # el del tramo que acaba de ejecutarse, que es el que querría
                # buscar en el visor.
                saliente = trazas.traceparent_actual() or traceparent
                if saliente:
                    cabeceras.append((b"traceparent", saliente.encode()))
                # Aviso de retirada de la versión de API, si hay fecha anunciada
                # (CRM-00.02.01.07). Va en TODA respuesta: es el único canal que
                # el integrador ya está leyendo.
                if s.api_sunset_date:
                    cabeceras.append((b"sunset", s.api_sunset_date.encode()))
                    cabeceras.append((b"deprecation", b"true"))
                message["headers"] = cabeceras
            await send(message)

        try:
            # El tramo raíz continúa la traza de quien llama, y con el
            # exportador apagado no cuesta nada: `span_entrante` devuelve un
            # contexto vacío sin importar OpenTelemetry.
            with trazas.span_entrante(
                f"{scope.get('method', 'GET')} {scope.get('path', '/')}",
                _cabeceras(scope),
                **{
                    "http.request.method": scope.get("method", ""),
                    "url.path": scope.get("path", ""),
                    "crm.request_id": request_id,
                    "crm.tenant_slug": pista or None,
                },
            ):
                await self.app(scope, receive, send_con_correlacion)
        finally:
            restaurar_contexto(token)


class CifradoEnTransitoMiddleware:
    """HSTS, cabeceras de seguridad y rechazo de HTTP en claro (CRM-00.05.03.01).

    `HSTS_MAX_AGE` **estaba configurado y no se aplicaba en ninguna respuesta**:
    el ajuste existía, se documentaba, y ninguna cabecera salía. Es el mismo
    modo de fallo que una preferencia de idioma que no se aplica — nadie lo
    llama avería porque no hay error, simplemente no pasa nada. Aquí sí pasa.

    Qué hace, y por qué cada cosa:

      * **HSTS**: le dice al navegador que no vuelva a hablar con este dominio
        por HTTP. Sin él, la primera petición de cada navegador puede ir en
        claro y ser interceptada antes de que exista la sesión.
      * **Rechaza HTTP** cuando `TLS_EXIGIDO`. Se responde 403 y no se redirige:
        una redirección a HTTPS llega después de que la credencial ya haya
        viajado en claro, así que «arregla» la siguiente petición y no la que
        importa.
      * **`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`**: el
        mínimo que evita que una respuesta de esta API se interprete como otra
        cosa, se embeba en un marco ajeno o filtre la URL completa —con sus
        identificadores— al navegar fuera.

    El esquema real se lee de `X-Forwarded-Proto` **solo si hay proxy de
    confianza declarado**. Sin esa condición, cualquiera mandaría la cabecera y
    se saltaría la comprobación entera.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from crmcore.config import get_settings

        s = get_settings()
        if s.tls_efectivo and scope.get("path") not in RUTAS_INFRAESTRUCTURA:
            if not _es_https(scope, s):
                from crmcore.errors import Prohibido

                await _responder_error(
                    send,
                    Prohibido(
                        "Esta instalación solo atiende por HTTPS: una petición en "
                        "claro lleva la credencial y los datos del cliente a la vista",
                        error_code="http.tls_requerido",
                    ),
                    scope,
                )
                return

        async def send_con_cabeceras(message: Message) -> None:
            if message["type"] == "http.response.start":
                cabeceras = list(message.get("headers", []))
                if s.hsts_max_age > 0:
                    cabeceras.append(
                        (
                            b"strict-transport-security",
                            f"max-age={s.hsts_max_age}; includeSubDomains".encode(),
                        )
                    )
                cabeceras.append((b"x-content-type-options", b"nosniff"))
                cabeceras.append((b"x-frame-options", b"DENY"))
                cabeceras.append((b"referrer-policy", b"strict-origin-when-cross-origin"))
                message["headers"] = cabeceras
            await send(message)

        await self.app(scope, receive, send_con_cabeceras)


def _es_https(scope: Scope, s: Any) -> bool:
    """Si la petición llegó cifrada de verdad.

    `X-Forwarded-Proto` solo se cree cuando hay proxy de confianza declarado:
    sin esa condición, cualquiera manda la cabecera y se salta la comprobación.
    """
    if scope.get("scheme") == "https":
        return True
    if s.trust_proxy_headers and s.proxies_de_confianza:
        return _cabecera(scope, "x-forwarded-proto").lower() == "https"
    return False


# Tope de lo que se copia del cuerpo. Un adjunto de veinte megas no se guarda
# en un log, y un cuerpo de CRM que no quepa en cuatro kilos tampoco se lee.
TOPE_CUERPO_LOG = 4096


def _settings_obs() -> Any:
    from crmcore.config import get_settings

    return get_settings()


def _receive_que_copia(receive: Receive, destino: list[bytes]) -> Receive:
    """Deja pasar el cuerpo intacto y se queda una copia acotada.

    Intacto es la palabra: el `receive` de ASGI se consume una sola vez, así que
    quedarse el cuerpo sin devolverlo dejaría a la aplicación sin él — un 422 en
    todas las escrituras en cuanto alguien encendiera el ajuste para depurar.
    """
    copiados = {"n": 0}

    async def envuelto() -> Message:
        mensaje = await receive()
        if mensaje.get("type") == "http.request":
            trozo = mensaje.get("body") or b""
            if trozo and copiados["n"] < TOPE_CUERPO_LOG:
                destino.append(trozo[: TOPE_CUERPO_LOG - copiados["n"]])
                copiados["n"] += len(trozo)
        return mensaje

    return envuelto


def _cuerpo_para_el_log(crudo: bytes) -> Any:
    """El cuerpo, censurado por clave y acotado.

    **Solo si es JSON que se puede leer.** Un cuerpo que no se puede analizar
    no se puede censurar, y soltarlo tal cual sacaría al log la contraseña de un
    inicio de sesión fallido o el correo de quien se acaba de dar de alta — que
    es exactamente lo que el ajuste advierte en su propio comentario. De lo que
    no se entiende se dice el tamaño, que para perseguir un 500 es casi todo lo
    que hacía falta.
    """
    import json

    from crmcore.logging import redactar_estructura

    cortado = len(crudo) >= TOPE_CUERPO_LOG
    try:
        dato = json.loads(crudo.decode("utf-8"))
    except Exception:  # noqa: BLE001 — binario, formulario, o cortado por el tope
        return {"ilegible": True, "bytes": len(crudo), "cortado": cortado}
    return {"json": redactar_estructura(dato), "cortado": cortado}


class TiemposMiddleware:
    """Mide, registra y publica la duración de cada petición.

    Alimenta el objetivo de latencia p95/p99 por tenant (CRM-08.01.01.01). La
    métrica se emite siempre; el apunte de log solo cuando la petición es lenta
    o falla, porque un apunte por petición en un sistema con tráfico es ruido
    que acaba haciendo que nadie mire los logs.
    """

    def __init__(self, app: ASGIApp, *, umbral_lento_s: float = 1.0, servicio: str = "") -> None:
        self.app = app
        self._umbral = umbral_lento_s
        # El nombre del servicio se necesita para el SLO: el presupuesto de
        # error es por servicio, y una cuenta agregada de todos no dice cuál
        # hay que arreglar.
        self._servicio = servicio
        # Últimas duraciones, para el p95 con el que se calcula la presión.
        self._ventana: list[float] = []

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

        # EL CUERPO, SOLO SI SE HA PEDIDO. `LOG_REQUEST_BODY` existía, estaba
        # documentado y **no lo leía nadie** (medido el 06-10-2026): encenderlo
        # no registraba ningún cuerpo, así que quien lo encendía para perseguir
        # un 500 seguía sin el dato y no sabía por qué.
        #
        # Va apagado de fábrica y se queda apagado: es la vía más rápida de
        # llevar datos personales a un sistema de logs que no está pensado para
        # guardarlos. Encendido, el cuerpo solo sale en el apunte de la petición
        # LENTA O FALLIDA, que es para lo que sirve; uno por petición sería el
        # ruido que hace que nadie mire los logs, además del volcado.
        cuerpo: list[bytes] = []
        if _settings_obs().log_request_body:
            receive = _receive_que_copia(receive, cuerpo)

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
                extra: dict[str, Any] = {}
                if cuerpo:
                    extra["cuerpo"] = _cuerpo_para_el_log(b"".join(cuerpo))
                logger.warning(
                    "http.peticion_lenta" if estado["status"] < 500 else "http.peticion_fallida",
                    metodo=scope.get("method", ""),
                    ruta=ruta,
                    status=estado["status"],
                    duracion_ms=round(duracion * 1000, 1),
                    **extra,
                )
            await self._anotar_slo(estado["status"], duracion)
            self._medir_presion(duracion)

    def _medir_presion(self, duracion_s: float) -> None:
        """Alimenta la presión del sistema (CRM-08.01.01.06).

        Va aquí por lo mismo que el SLO: la presión tiene que salir de **todas**
        las peticiones. Mientras nadie la midiera, la degradación controlada era
        un mecanismo que existía en el código y no se activaba nunca —la presión
        valía cero para siempre—, que es el peor tipo de función: la que da
        confianza sin hacer nada.

        Medir no puede tirar una petición, así que todo va dentro del `try`.
        """
        try:
            from crmcore import resiliencia
            from crmcore.config import get_settings
            from crmcore.obs.presion import aplicar, calcular

            self._ventana.append(duracion_s * 1000)
            if len(self._ventana) < 20:
                return
            # Ventana corta y deslizante: con una ventana larga, la presión tarda
            # minutos en bajar después de un pico y el sistema se queda degradado
            # cuando ya no hace falta.
            self._ventana = self._ventana[-100:]
            ordenadas = sorted(self._ventana)
            p95 = ordenadas[int(len(ordenadas) * 0.95) - 1]
            aplicar(
                calcular(
                    p95_ms=p95,
                    objetivo_ms=float(get_settings().slo_latencia_objetivo_ms),
                    presion_anterior=resiliencia.presion(),
                )
            )
        except Exception as exc:  # noqa: BLE001 — medir no puede tirar la petición
            logger.warning("presion.no_medida", motivo=str(exc)[:120])

    async def _anotar_slo(self, status: int, duracion_s: float) -> None:
        """Apunta la petición contra el presupuesto de error (CRM-00.06.01.04).

        Aquí y no en cada endpoint: el presupuesto tiene que contar **todas** las
        peticiones, y engancharlo ruta a ruta significa que cuenta las que
        alguien se acordó de enganchar — que son justo las que menos fallan.

        Se apunta por tenant y no por tier, porque el tier vive en `tenancy` y
        ningún servicio lee el esquema de otro. La lentitud se cuenta contra los
        tres umbrales a la vez, de modo que al leer se pueda aplicar el del tier
        contratado sin haber perdido la información.
        """
        if not self._servicio:
            return
        try:
            from crmcore.obs import slo
            from crmcore.tenancy.context import contexto_actual

            await slo.anotar(
                self._servicio,
                contexto_actual().tenant_id,
                # Un 4xx es un error del cliente, no del servicio: contarlo
                # gastaría el presupuesto del equipo por culpa de una
                # integración que manda mal los datos.
                ok=status < 500,
                ms=duracion_s * 1000,
            )
        except Exception as exc:  # noqa: BLE001 — medir no puede tirar la petición
            logger.warning("slo.no_anotado_middleware", motivo=str(exc)[:120])


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

    # Solo las ESCRITURAS. Una lectura no reserva clave de idempotencia nunca,
    # así que acumular su cuerpo es memoria gastada para nada — y en una
    # respuesta que no termina, como el flujo del chat, es memoria que crece sin
    # tope mientras alguien tenga el chat abierto.
    METODOS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method", "") not in self.METODOS:
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
    business_unit_id: UUID | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Completa el contexto con la identidad ya verificada.

    Lo llama la dependencia de autenticación, no el middleware: el middleware
    corre antes de que se sepa quién es nadie. Se reemplaza el contexto entero
    (es inmutable) en vez de mutarlo.

    Decía exactamente eso —«lo llama la dependencia de autenticación»— y **no la
    llamaba**: la dependencia lo hacía en línea, con dos campos más, y esto era
    un duplicado más estrecho que nadie ejecutaba. Dos formas de construir el
    contexto de identidad es cómo acaban dos caminos poniendo cosas distintas en
    él, y el que menos se mira es el que se queda corto. Ahora hay una.

    `extra` se **mezcla** con lo que ya hubiera en el contexto, no lo sustituye:
    por ahí viajan el principal, la IP y el motivo por el que una cookie no
    valía, y perder cualquiera de los tres deja a quien lo lee sin saber por qué.
    """
    from dataclasses import replace

    from crmcore.tenancy.context import contexto_actual, fijar_contexto

    ctx = contexto_actual()
    fijar_contexto(
        replace(
            ctx,
            tenant_id=tenant_id,
            user_id=user_id,
            business_unit_id=business_unit_id,
            scopes=scopes,
            es_admin_plataforma=es_admin_plataforma,
            actor_real_id=actor_real_id,
            extra={**ctx.extra, **(extra or {})},
        )
    )


class TiempoMaximoMiddleware:
    """Corta una petición que no contesta a tiempo y devuelve 504.

    `REQUEST_TIMEOUT_S` estaba en los ajustes, documentado —«una petición que
    pasa de aquí se corta y devuelve 504; existe para que una consulta
    patológica no retenga una conexión del pool indefinidamente»— y **no lo
    leía nadie**. Una consulta desbocada retenía su conexión hasta que el
    cliente se rendía, y cuarenta de esas dejan al servicio sin pool con la base
    perfectamente sana.

    Dos decisiones que importan:

    **Se acota hasta que la respuesta EMPIEZA, no hasta que termina.** Una
    descarga larga o un `text/event-stream` son lentos a propósito, y cortarlos
    a los sesenta segundos rompería exactamente lo que está funcionando. Lo que
    no puede pasar es que el manejador se quede pensando sin haber contestado
    nada.

    **La cancelación llega al manejador**, así que la transacción se deshace por
    el camino de siempre: el `except` de la unidad de trabajo ve el
    `CancelledError` y hace `rollback`. Sin eso, cortar dejaría escrituras a
    medias, que es peor que la consulta lenta.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        import asyncio

        from crmcore.config import get_settings

        if scope["type"] != "http" or scope.get("path") in RUTAS_INFRAESTRUCTURA:
            await self.app(scope, receive, send)
            return

        limite = float(get_settings().request_timeout_s)
        if limite <= 0:
            await self.app(scope, receive, send)
            return

        empezo_a_responder = asyncio.Event()

        async def send_vigilando(message: Message) -> None:
            if message["type"] == "http.response.start":
                empezo_a_responder.set()
            await send(message)

        tarea = asyncio.ensure_future(self.app(scope, receive, send_vigilando))
        espera = asyncio.ensure_future(empezo_a_responder.wait())
        try:
            hechas, _ = await asyncio.wait(
                {tarea, espera}, timeout=limite, return_when=asyncio.FIRST_COMPLETED
            )
            if tarea in hechas:
                await tarea
                return
            if espera in hechas:
                # Ya está contestando: se deja terminar, por larga que sea.
                await tarea
                return

            # Ni ha contestado ni ha terminado dentro del plazo.
            tarea.cancel()
            logger.error(
                "middleware.peticion_cortada",
                ruta=scope.get("path", ""),
                metodo=scope.get("method", ""),
                limite_s=limite,
            )
            try:
                await tarea
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            if not empezo_a_responder.is_set():
                cuerpo = (
                    b'{"type":"https://contecrm.dev/errores/tiempo_agotado",'
                    b'"title":"Tiempo agotado","status":504,'
                    b'"detail":"La peticion ha tardado demasiado y se ha cortado '
                    b"para no retener recursos. Acota lo que pides y vuelve a "
                    b'intentarlo.","code":"tiempo_agotado",'
                    b'"error_code":"http.tiempo_agotado"}'
                )
                await send(
                    {
                        "type": "http.response.start",
                        "status": 504,
                        "headers": [
                            (b"content-type", b"application/problem+json"),
                            (b"content-length", str(len(cuerpo)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": cuerpo})
        finally:
            espera.cancel()
