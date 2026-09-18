"""API del gateway: proxy autenticado y superficie propia mínima."""

from __future__ import annotations

from typing import Any

import httpx
from crmcore.config import get_settings
from crmcore.errors import NoDisponible, NoEncontrado
from crmcore.http.deps import PrincipalDep
from crmcore.logging import get_logger
from fastapi import APIRouter, Request, Response

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
    import os

    _destinos = rutas.cargar_destinos(os.environ.get("RUTAS_SERVICIOS", ""))
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


ROUTERS = [router]
ROUTERS_SIN_PREFIJO = [router_proxy]
