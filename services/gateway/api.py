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


ROUTERS = [router]
ROUTERS_SIN_PREFIJO = [router_proxy]
