"""API del gateway: proxy autenticado y superficie propia mínima."""

from __future__ import annotations

from typing import Any

import httpx
from crmcore.config import get_settings
from crmcore.errors import NoDisponible, NoEncontrado
from crmcore.http.deps import AutenticadoDep, PrincipalDep
from crmcore.logging import get_logger
from fastapi import APIRouter, Query, Request, Response

from services.gateway import proxy, rutas
from services.gateway.sesion import crear_router_sesion

logger = get_logger(__name__)

# Router propio del gateway, bajo `/api/v1`.
router = APIRouter(tags=["gateway"])

# Router del proxy: se monta SIN prefijo porque reenvía la ruta completa.
router_proxy = APIRouter(tags=["gateway"])

# Cliente HTTP reutilizado: crear uno por petición desperdicia el pool de
# conexiones y añade un handshake TLS a cada llamada interna.
_cliente: httpx.AsyncClient | None = None
_destinos: dict[str, rutas.Destino] = {}


async def arrancar() -> None:
    """Prepara el cliente HTTP y la tabla de destinos."""
    global _cliente, _destinos

    _destinos = rutas.cargar_destinos(get_settings().rutas_servicios)
    # Sin límite de conexiones el gateway puede abrir miles contra un servicio
    # lento y quedarse sin descriptores; con un límite, las peticiones esperan
    # en cola, que es un fallo mucho más benigno.
    _cliente = httpx.AsyncClient(
        limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
        follow_redirects=False,
    )
    logger.info("gateway.destinos", servicios=sorted(_destinos))


async def parar() -> None:
    if _cliente is not None:
        await _cliente.aclose()


@router.get("/servicios", summary="Servicios enrutados y su salud")
async def servicios(_: PrincipalDep) -> Any:
    """Estado de los servicios de detrás.

    Es el registro de servicios en su forma mínima (CRM-00.03.01.04): qué hay,
    dónde está y si responde. Se consulta en vivo en vez de cachearse: el valor
    de este endpoint es decir la verdad en el momento en que se pregunta.
    """
    if _cliente is None:
        raise NoDisponible("El gateway aún no ha arrancado", error_code="gateway.arrancando")

    salida = []
    for nombre, destino in sorted(_destinos.items()):
        try:
            respuesta = await _cliente.get(f"{destino.url_base}/health/ready", timeout=3.0)
            salida.append(
                {
                    "servicio": nombre,
                    "url": destino.url_base,
                    "estado": "listo" if respuesta.status_code == 200 else "no listo",
                    "detalle": respuesta.json().get("comprobaciones", {}),
                }
            )
        except Exception as exc:  # noqa: BLE001 — un servicio caído es información, no un error
            salida.append(
                {
                    "servicio": nombre,
                    "url": destino.url_base,
                    "estado": "inalcanzable",
                    "detalle": str(exc)[:200],
                }
            )
    return salida


@router.get(
    "/contrato/{servicio}",
    summary="El contrato OpenAPI de un servicio",
    description=(
        "Devuelve el OpenAPI del servicio indicado, tal cual lo publica él.\n\n"
        "Existe porque el front **genera los formularios leyendo el contrato**: "
        "los campos de un alta salen del esquema de la operación, no de una "
        "lista escrita en el front. Sin esta ruta, la llamada fallaba con 404, "
        "el front se lo tragaba —está dentro de un `catch`— y **todos** los "
        "formularios de alta salían vacíos, sin que nada lo dijera.\n\n"
        "No se enruta `/api/v1/<servicio>/...` de forma general a propósito: "
        "eso expondría cada ruta interna de cada servicio por un camino "
        "paralelo al de la tabla de enrutado, que es la única lista de "
        "acoplamiento del sistema."
    ),
)
async def contrato_de_servicio(servicio: str, _: PrincipalDep) -> Any:
    if _cliente is None:
        raise NoDisponible("El gateway aún no ha arrancado", error_code="gateway.arrancando")
    destino = _destinos.get(servicio)
    if destino is None:
        # 404 con la lista de los que sí hay: un 404 a secas deja a quien
        # integra sin saber si se equivocó de nombre o si el servicio no está
        # desplegado en esta instalación, que son dos problemas distintos.
        raise NoEncontrado(
            f"No hay ningún servicio enrutado con el nombre «{servicio}»",
            error_code="gateway.servicio_desconocido",
            detalle={"servicios": sorted(_destinos)},
        )
    # Por el prefijo configurado y no por `/openapi.json` a secas: el contrato
    # se publica bajo el prefijo de versión de la API (`/api/v1/openapi.json`),
    # que es el mismo ajuste con el que se sirve todo lo demás.
    prefijo = get_settings().api_prefix.rstrip("/")
    try:
        respuesta = await _cliente.get(f"{destino.url_base}{prefijo}/openapi.json", timeout=10.0)
    except httpx.HTTPError as exc:
        raise NoDisponible(
            f"El servicio «{servicio}» no ha contestado con su contrato",
            error_code="gateway.contrato_no_disponible",
        ) from exc
    if respuesta.status_code != 200:
        raise NoDisponible(
            f"El servicio «{servicio}» ha contestado {respuesta.status_code} a su contrato",
            error_code="gateway.contrato_no_disponible",
        )
    return respuesta.json()


@router.get(
    "/estado",
    summary="Cómo va MI CRM ahora mismo",
    description=(
        "La página de estado privada de este tenant: junta lo que publica cada "
        "servicio sobre **sus** componentes y devuelve una sola vista.\n\n"
        "Se compone en vez de calcularse en un sitio porque ningún servicio "
        "lee las tablas de otro: el estado de los webhooks lo sabe `eventing` y "
        "el de las cuotas lo sabe `tenancy`. Cada uno publica lo suyo.\n\n"
        "Solo dice lo de este tenant. Ni cuántos hay, ni cómo van los demás, ni "
        "qué versión corre cada réplica: una página de estado que filtra la "
        "forma de la plataforma es un mapa para quien quiera atacarla."
    ),
)
async def estado_del_tenant(request: Request, principal: AutenticadoDep) -> Any:
    import asyncio
    from datetime import datetime, timezone

    from crmcore.config import get_settings
    from crmcore.datos.estado import _peor

    if _cliente is None:
        raise NoDisponible("El gateway aún no ha arrancado", error_code="gateway.arrancando")

    cabeceras = proxy.cabeceras_de_identidad(
        principal, get_settings().secret_key.get_secret_value()
    )

    async def _preguntar(nombre: str) -> list[dict[str, Any]]:
        try:
            respuesta = await _cliente.get(
                f"{_destinos[nombre].url_base}/api/v1/estado",
                headers=cabeceras,
                timeout=5.0,
            )
            if respuesta.status_code != 200:
                raise RuntimeError(f"respondió {respuesta.status_code}")
            return [
                {**componente, "servicio": nombre}
                for componente in respuesta.json().get("componentes", [])
            ]
        except Exception:  # noqa: BLE001 — un servicio caído es información, no un error
            # No se filtra el mensaje: el de un error de conexión lleva host y
            # puerto, y esta página la ve el cliente.
            return [
                {
                    "servicio": nombre,
                    "componente": nombre,
                    "estado": "caido",
                    "detalle": "El servicio no responde",
                }
            ]

    # En paralelo: en serie, diez servicios con cinco segundos de plazo son
    # cincuenta segundos de espera en el peor caso — justo cuando algo va mal y
    # el cliente más necesita la página.
    respuestas = await asyncio.gather(*(_preguntar(n) for n in sorted(_destinos)))
    componentes: list[dict[str, Any]] = [c for lote in respuestas for c in lote]

    return {
        "estado": _peor([c["estado"] for c in componentes]) if componentes else "caido",
        "consultado_at": datetime.now(timezone.utc).isoformat(),
        "componentes": componentes,
        "cacheado": False,
    }


@router.get(
    "/estado/slo",
    summary="Cuánto margen queda antes de incumplir lo prometido",
    description=(
        "El presupuesto de error de cada servicio para este tenant "
        "(CRM-00.06.01.04), con el objetivo del **tier contratado**.\n\n"
        "Se compone aquí porque el tier lo sabe `tenancy` y el tráfico lo sabe "
        "cada servicio, y ninguno lee las tablas del otro. El gateway pregunta "
        "el tier una vez y se lo pasa a todos: así el objetivo que se aplica es "
        "el que se firmó, y no el que cada servicio se hubiera supuesto.\n\n"
        "Lo que no se ha podido consultar **se dice**. Un servicio que no "
        "responde y desaparece de la lista deja una página que enseña margen de "
        "sobra precisamente cuando algo va mal."
    ),
)
async def slo_del_tenant(request: Request, principal: AutenticadoDep) -> Any:
    import asyncio
    from datetime import datetime, timezone

    from crmcore.config import get_settings

    if _cliente is None:
        raise NoDisponible("El gateway aún no ha arrancado", error_code="gateway.arrancando")

    cabeceras = proxy.cabeceras_de_identidad(
        principal, get_settings().secret_key.get_secret_value()
    )

    tier = "estandar"
    tier_conocido = False
    if "tenancy" in _destinos:
        try:
            respuesta = await _cliente.get(
                f"{_destinos['tenancy'].url_base}/api/v1/compromisos",
                headers=cabeceras,
                timeout=5.0,
            )
            if respuesta.status_code == 200:
                tier = str(respuesta.json().get("tier") or "estandar")
                tier_conocido = True
        except Exception:  # noqa: BLE001 — sin tier se aplica el estándar y se dice
            tier_conocido = False

    async def _preguntar(nombre: str) -> dict[str, Any]:
        try:
            respuesta = await _cliente.get(
                f"{_destinos[nombre].url_base}/api/v1/estado/slo",
                headers=cabeceras,
                params={"tier": tier},
                timeout=5.0,
            )
            if respuesta.status_code != 200:
                raise RuntimeError(f"respondió {respuesta.status_code}")
            return {"servicio": nombre, **respuesta.json()}
        except Exception:  # noqa: BLE001 — un servicio que no contesta es información
            return {
                "servicio": nombre,
                "medible": False,
                "motivo": "El servicio no ha respondido a la consulta de SLO",
            }

    presupuestos = await asyncio.gather(*(_preguntar(n) for n in sorted(_destinos)))
    medibles = [p for p in presupuestos if p.get("medible")]
    agotados = [p["servicio"] for p in medibles if p.get("agotado")]
    sin_respuesta = [p["servicio"] for p in presupuestos if not p.get("medible")]

    return {
        "tier": tier,
        # Que el tier salga por defecto no es lo mismo que que sea el contratado,
        # y la diferencia cambia el objetivo que se está aplicando.
        "tier_confirmado": tier_conocido,
        "consultado_at": datetime.now(timezone.utc).isoformat(),
        "servicios": presupuestos,
        "servicios_medibles": len(medibles),
        "sin_medicion": sin_respuesta,
        "presupuesto_agotado_en": agotados,
        "se_puede_desplegar": not agotados,
        "que_significa": (
            f"Presupuesto agotado en {', '.join(agotados)}: toca parar de añadir y "
            "arreglar lo que falla"
            if agotados
            else "Queda margen en todos los servicios medibles: se puede seguir desplegando"
        ),
    }


@router.get(
    "/estado/contratos",
    summary="Contratos de evento de toda la instalación",
    description=(
        "Contract testing interno dirigido por el consumidor "
        "(CRM-00.03.01.03): junta lo que publica cada servicio sobre los "
        "contratos de evento que consume.\n\n"
        "Se junta aquí porque un contrato tiene dos lados en dos servicios "
        "distintos: mirarlo servicio a servicio enseña la mitad de cada uno y "
        "no deja ver lo único que importa, que es si lo que uno promete lo "
        "cumple para quien depende de ello."
    ),
)
async def contratos_de_la_instalacion(principal: AutenticadoDep) -> Any:
    import asyncio

    from crmcore.config import get_settings

    if _cliente is None:
        raise NoDisponible("El gateway aún no ha arrancado", error_code="gateway.arrancando")

    cabeceras = proxy.cabeceras_de_identidad(
        principal, get_settings().secret_key.get_secret_value()
    )

    async def _preguntar(nombre: str) -> dict[str, Any]:
        try:
            respuesta = await _cliente.get(
                f"{_destinos[nombre].url_base}/api/v1/estado/contratos",
                headers=cabeceras,
                timeout=5.0,
            )
            if respuesta.status_code != 200:
                raise RuntimeError(f"respondió {respuesta.status_code}")
            return dict(respuesta.json())
        except Exception:  # noqa: BLE001 — un servicio mudo es información
            # Un servicio que no contesta NO cuenta como «en verde»: contarlo
            # así daría por verificado un contrato que nadie ha comprobado, que
            # es exactamente lo que este gate existe para impedir.
            return {"servicio": nombre, "medible": False, "en_verde": False}

    partes = await asyncio.gather(*(_preguntar(n) for n in sorted(_destinos)))
    incumplimientos = [i for p in partes for i in p.get("incumplimientos", [])]
    return {
        "en_verde": not incumplimientos and all(p.get("medible", True) for p in partes),
        "incumplimientos": incumplimientos,
        "servicios": partes,
        "sin_respuesta": [p["servicio"] for p in partes if not p.get("medible", True)],
    }


@router.get(
    "/estado/ui-referencia",
    summary="Si la instalación necesita la interfaz de referencia",
    description=(
        "«Somos headless y la interfaz es opcional» (CRM-00.02.03.02) no se "
        "erosiona de golpe: se erosiona con una redirección cada vez. Esto lo "
        "mide en **todos** los servicios y junta los hallazgos.\n\n"
        "Un servicio que no contesta NO cuenta como independiente: contarlo así "
        "daría por comprobado lo que nadie ha mirado, que es justo lo que esto "
        "existe para impedir."
    ),
)
async def ui_de_referencia_de_la_instalacion(principal: AutenticadoDep) -> Any:
    import asyncio

    from crmcore.config import get_settings
    from crmcore.http.ui_opcional import estado_de_la_ui

    if _cliente is None:
        raise NoDisponible("El gateway aún no ha arrancado", error_code="gateway.arrancando")

    s = get_settings()
    cabeceras = proxy.cabeceras_de_identidad(principal, s.secret_key.get_secret_value())

    async def _preguntar(nombre: str) -> dict[str, Any]:
        try:
            respuesta = await _cliente.get(
                f"{_destinos[nombre].url_base}/api/v1/estado/ui-referencia",
                headers=cabeceras,
                timeout=5.0,
            )
            if respuesta.status_code != 200:
                raise RuntimeError(f"respondió {respuesta.status_code}")
            return dict(respuesta.json())
        except Exception:  # noqa: BLE001 — un servicio mudo es información
            return {
                "servicio": nombre,
                "independiente": False,
                "hallazgos": [
                    {
                        "donde": nombre,
                        "que": "el servicio no contesta",
                        "consecuencia": (
                            "no se puede afirmar que sea independiente de la interfaz, "
                            "y darlo por bueno sería declarar comprobado lo que nadie "
                            "ha mirado"
                        ),
                    }
                ],
            }

    partes = await asyncio.gather(*(_preguntar(n) for n in sorted(_destinos)))
    hallazgos = [h for p in partes for h in p.get("hallazgos", [])]
    return {
        "independiente": not hallazgos,
        "hallazgos": hallazgos,
        "servicios": partes,
        "la_interfaz": estado_de_la_ui(settings=s),
    }


@router.get(
    "/estado/presion",
    summary="Qué se está aplazando en la instalación y por qué",
    description=(
        "La presión de un solo servicio no dice nada: lo que se aplaza depende "
        "del que esté peor. Aquí se juntan las de todos (CRM-08.01.01.06).\n\n"
        "Un servicio que no contesta **no cuenta como tranquilo**: se dice que no "
        "se sabe, que es distinto."
    ),
)
async def presion_de_la_instalacion(principal: AutenticadoDep) -> Any:
    import asyncio

    from crmcore.config import get_settings

    if _cliente is None:
        raise NoDisponible("El gateway aún no ha arrancado", error_code="gateway.arrancando")

    cabeceras = proxy.cabeceras_de_identidad(
        principal, get_settings().secret_key.get_secret_value()
    )

    async def _preguntar(nombre: str) -> dict[str, Any]:
        try:
            respuesta = await _cliente.get(
                f"{_destinos[nombre].url_base}/api/v1/estado/presion",
                headers=cabeceras,
                timeout=5.0,
            )
            if respuesta.status_code != 200:
                raise RuntimeError(f"respondió {respuesta.status_code}")
            return dict(respuesta.json())
        except Exception:  # noqa: BLE001 — un servicio mudo es información
            return {"servicio": nombre, "medible": False, "presion": None}

    partes = await asyncio.gather(*(_preguntar(n) for n in sorted(_destinos)))
    medibles = [p for p in partes if p.get("presion") is not None]
    peor = max(medibles, key=lambda p: p["presion"], default=None)
    mudos = [p["servicio"] for p in partes if p.get("presion") is None]

    return {
        "peor": peor,
        "servicios": partes,
        "sin_respuesta": mudos,
        "que_significa": (
            "No ha contestado ningún servicio: no se puede decir que todo esté "
            "tranquilo, se puede decir que no se sabe."
            if not medibles
            else (peor or {}).get("que_significa", "")
        ),
        "aviso": (
            ""
            if not mudos
            else f"{len(mudos)} servicios no contestan. Un servicio mudo no cuenta como "
            "tranquilo: es justo el que suele estar peor."
        ),
    }


@router.get(
    "/superficie",
    summary="Todo lo que sabe hacer el CRM, en una lista",
    description=(
        "Junta la superficie de **todos** los servicios: cada operación con su "
        "método, su ruta pública, el permiso que exige y si es de "
        "administración.\n\n"
        "Es lo que hace comprobable la promesa de que la consola de "
        "administración está replicada al 100 % por API (CRM-07.01.01.01): la "
        "consola se construye leyendo esto, así que no puede existir una acción "
        "de consola que no sea una llamada de esta lista.\n\n"
        "Se agrega aquí y no se pide servicio a servicio porque quien la "
        "consume es un cliente de fuera, que no conoce —ni debe conocer— cómo "
        "está repartido el sistema por dentro."
    ),
)
async def superficie_completa(_: AutenticadoDep) -> Any:
    import asyncio
    from datetime import datetime, timezone

    if _cliente is None:
        raise NoDisponible("El gateway aún no ha arrancado", error_code="gateway.arrancando")

    async def _preguntar(nombre: str) -> dict[str, Any]:
        try:
            respuesta = await _cliente.get(
                f"{_destinos[nombre].url_base}/api/v1/superficie", timeout=5.0
            )
            if respuesta.status_code != 200:
                raise RuntimeError(f"respondió {respuesta.status_code}")
            return respuesta.json()
        except Exception:  # noqa: BLE001 — un servicio caído es información
            # Se devuelve el hueco en vez de omitirlo: una superficie a la que
            # le falta un servicio sin decirlo haría que la consola escondiera
            # media administración como si no existiera.
            return {"servicio": nombre, "alcanzable": False, "operaciones": []}

    partes = await asyncio.gather(*(_preguntar(n) for n in sorted(_destinos)))

    operaciones: list[dict[str, Any]] = []
    incompletos: list[str] = []
    for parte in partes:
        if parte.get("alcanzable") is False:
            incompletos.append(str(parte.get("servicio")))
            continue
        for operacion in parte.get("operaciones", []):
            operaciones.append({**operacion, "servicio": parte.get("servicio")})
    operaciones.sort(key=lambda o: (o["ruta"], o["metodo"]))

    return {
        "consultado_at": datetime.now(timezone.utc).isoformat(),
        "servicios": sorted(_destinos),
        # Nombrar a quien no contesta es la diferencia entre una lista corta y
        # una lista corta que se sabe corta.
        "servicios_sin_contestar": incompletos,
        "completa": not incompletos,
        "total": len(operaciones),
        "administracion": sum(1 for o in operaciones if o.get("administracion")),
        "operaciones": operaciones,
    }


@router_proxy.api_route(
    "/api/{ruta:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    summary="Proxy a los servicios",
    description=(
        "Toda la API pública pasa por aquí. El gateway resuelve el tenant, "
        "autentica, aplica los límites y reenvía con la identidad firmada."
    ),
    include_in_schema=False,
)
async def proxy_api(ruta: str, request: Request, principal: PrincipalDep) -> Response:
    if _cliente is None:
        raise NoDisponible("El gateway aún no ha arrancado", error_code="gateway.arrancando")

    ruta_completa = f"/api/{ruta}"
    nombre = rutas.servicio_de(ruta_completa)
    if nombre is None:
        raise NoEncontrado(
            "No hay ninguna ruta de la API que corresponda",
            error_code="gateway.ruta_desconocida",
        )
    destino = _destinos.get(nombre)
    if destino is None:
        # 503 y no 404: la ruta existe, lo que falta es el servicio. Un 404 haría
        # pensar que la llamada está mal escrita.
        raise NoDisponible(
            f"El servicio «{nombre}» no está desplegado en esta instalación",
            error_code="gateway.servicio_no_desplegado",
            detalle={"servicio": nombre},
        )

    s = get_settings()
    respuesta = await proxy.reenviar(
        _cliente,
        url_base=destino.url_base,
        metodo=request.method,
        ruta=ruta_completa,
        query=str(request.url.query or ""),
        cabeceras=dict(request.headers),
        cuerpo=await request.body(),
        identidad=proxy.cabeceras_de_identidad(principal, s.secret_key.get_secret_value()),
        timeout_s=s.http_interno_timeout_s,
    )
    # La respuesta del servicio se devuelve tal cual, incluidos su código y sus
    # cabeceras de contrato: el gateway no reinterpreta lo que dice el servicio.
    return Response(
        content=respuesta.content,
        status_code=respuesta.status_code,
        headers={
            k: v
            for k, v in respuesta.headers.items()
            if k.lower() not in ("content-length", "transfer-encoding", "connection")
        },
        media_type=respuesta.headers.get("content-type"),
    )


@router.get(
    "/buscar",
    summary="Buscar en todo el CRM",
    description=(
        "Pregunta a cada servicio por su índice y junta los resultados por "
        "relevancia. La búsqueda global se compone aquí y no en un índice "
        "compartido: así ningún servicio necesita leer el esquema de otro, y el "
        "aislamiento de cada índice sigue siendo el mismo que el de sus datos.\n\n"
        "Un servicio que no responda **no hace fallar la búsqueda**: se devuelve "
        "lo que haya y se dice cuáles faltan. Media respuesta útil vale más que "
        "un error, y ocultar que falta la mitad sería peor que las dos cosas."
    ),
)
async def buscar_global(
    peticion: Request,
    principal: AutenticadoDep,
    q: str = Query(..., min_length=1, max_length=300),
    limite: int = Query(20, ge=1, le=100),
) -> Any:
    """Reparte la consulta entre los servicios que tienen índice."""
    import asyncio

    if _cliente is None:
        raise NoDisponible("El gateway aún no ha arrancado", error_code="gateway.arrancando")

    # Los servicios con índice. Se declara la lista en vez de preguntar a todos:
    # el gateway ya sabe quién tiene búsqueda, y llamar a los diez para que
    # siete devuelvan 404 multiplica por tres el tiempo de cada consulta.
    con_indice = [s for s in ("party", "sales") if s in _destinos]

    cabeceras = {
        k: v
        for k, v in peticion.headers.items()
        if k.lower().startswith("x-") or k.lower() == "authorization"
    }

    async def _preguntar(servicio: str) -> tuple[str, list[dict[str, Any]] | None]:
        destino = _destinos[servicio]
        try:
            respuesta = await _cliente.get(
                f"{destino.url_base}/api/v1/buscar",
                params={"q": q, "limite": limite},
                headers=cabeceras,
                timeout=5.0,
            )
            if respuesta.status_code != 200:
                return servicio, None
            return servicio, list(respuesta.json().get("resultados") or [])
        except Exception:  # noqa: BLE001 — un servicio caído no puede tumbar la búsqueda
            return servicio, None

    respuestas = await asyncio.gather(*(_preguntar(s) for s in con_indice))

    resultados: list[dict[str, Any]] = []
    fallidos: list[str] = []
    for servicio, filas in respuestas:
        if filas is None:
            fallidos.append(servicio)
            continue
        for fila in filas:
            resultados.append({**fila, "servicio": servicio})

    resultados.sort(key=lambda r: float(r.get("relevancia") or 0), reverse=True)
    if fallidos:
        logger.warning("gateway.busqueda_parcial", servicios_caidos=fallidos)
    return {
        "consulta": q,
        "total": len(resultados[:limite]),
        "resultados": resultados[:limite],
        # Se dice siempre, aunque esté vacío: quien lo consume tiene que poder
        # distinguir «no hay resultados» de «no hemos podido preguntar».
        "servicios_sin_responder": fallidos,
    }


def _piezas() -> tuple[Any, dict[str, rutas.Destino], float]:
    """El cliente, los destinos y el plazo, resueltos al llamar y no al montar."""
    if _cliente is None:
        raise NoDisponible("El gateway aún no ha arrancado", error_code="gateway.arrancando")
    return _cliente, _destinos, get_settings().http_interno_timeout_s


ROUTERS = [router, crear_router_sesion(_piezas)]
ROUTERS_SIN_PREFIJO = [router_proxy]
