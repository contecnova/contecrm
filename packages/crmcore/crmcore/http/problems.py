"""Traducción de cualquier fallo a Problem Details (RFC 9457).

Tres manejadores cubren las tres formas en que algo puede salir mal:

  * un error de dominio nuestro (`CrmError`) → su código y su estado,
  * un error de validación de FastAPI → 422 con el detalle por campo,
  * cualquier otra excepción → 500 **sin filtrar el detalle interno**.

Esa última es la que importa: un traceback en la respuesta enseña rutas, nombres
de tabla y a veces datos. El detalle va al log con el `request_id`, y la
respuesta lleva ese mismo `request_id` para que soporte pueda cruzarlos.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from crmcore.errors import CrmError, ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Tipo de contenido que exige RFC 9457. Un cliente que sepa leerlo lo distingue
# de un JSON cualquiera por esto, no por adivinar la forma del cuerpo.
CONTENT_TYPE = "application/problem+json"


def _request_id(request: Request) -> str:
    from crmcore.tenancy.context import contexto_actual

    ctx = contexto_actual()
    return ctx.request_id or request.headers.get("x-request-id", "")


def _respuesta(problema: dict[str, Any], status: int, cabeceras: dict[str, str] | None = None):
    return JSONResponse(
        status_code=status, content=problema, media_type=CONTENT_TYPE, headers=cabeceras or {}
    )


async def manejar_error_dominio(request: Request, exc: CrmError) -> JSONResponse:
    rid = _request_id(request)
    problema = exc.a_problema(instancia=str(request.url.path), request_id=rid)

    cabeceras: dict[str, str] = {}
    # `Retry-After` en los 429: sin ella, el cliente educado reintenta a ciegas
    # y el maleducado reintenta en bucle. Con ella, los dos saben cuánto esperar.
    reintentar = getattr(exc, "reintentar_en_s", None)
    if reintentar:
        cabeceras["Retry-After"] = str(int(reintentar))

    nivel = logger.warning if exc.status_code < 500 else logger.error
    nivel(
        "http.error_dominio",
        code=exc.code,
        error_code=exc.error_code,
        status=exc.status_code,
        ruta=str(request.url.path),
    )
    return _respuesta(problema, exc.status_code, cabeceras)


async def manejar_validacion(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 con el detalle por campo.

    Se devuelven TODOS los campos mal, no el primero: un formulario que corrige
    un error por intento es una conversación de cinco viajes con el servidor.
    """
    errores = [
        {
            "campo": ".".join(str(p) for p in e.get("loc", ()) if p != "body"),
            "motivo": e.get("type", ""),
            "mensaje": e.get("msg", ""),
        }
        for e in exc.errors()
    ]
    err = ErrorValidacion(
        "Los datos enviados no son válidos",
        error_code="validacion.cuerpo",
        errores=errores,
    )
    return _respuesta(
        err.a_problema(instancia=str(request.url.path), request_id=_request_id(request)),
        err.status_code,
    )


async def manejar_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """404 de rutas inexistentes, 405, y los `HTTPException` de terceros.

    Se traducen al mismo sobre que el resto: un cliente no debería encontrarse
    con dos formatos de error según qué capa falló.
    """
    from crmcore.errors import POR_CODIGO, CrmError

    por_estado = {
        401: "no_autenticado",
        403: "prohibido",
        404: "no_encontrado",
        409: "conflicto",
        413: "cuerpo_demasiado_grande",
        422: "validacion",
        429: "limite_excedido",
    }
    cls = POR_CODIGO.get(por_estado.get(exc.status_code, ""), CrmError)
    err = cls(str(exc.detail) if exc.detail else "Error")
    problema = err.a_problema(instancia=str(request.url.path), request_id=_request_id(request))
    problema["status"] = exc.status_code
    return _respuesta(problema, exc.status_code, dict(getattr(exc, "headers", None) or {}))


async def manejar_no_previsto(request: Request, exc: Exception) -> JSONResponse:
    """Cualquier cosa no prevista. El detalle va al log, no a la respuesta."""
    rid = _request_id(request)
    logger.exception(
        "http.error_no_previsto",
        ruta=str(request.url.path),
        excepcion=type(exc).__name__,
        request_id=rid,
    )
    from crmcore.errors import ErrorInterno

    err = ErrorInterno(
        "Error interno. Si el problema persiste, facilita el identificador de "
        "la petición al soporte.",
        error_code="interno.no_previsto",
    )
    return _respuesta(err.a_problema(instancia=str(request.url.path), request_id=rid), 500)


async def manejar_repetida(_peticion: Request, exc: Exception) -> JSONResponse:
    """Devuelve la respuesta que se guardó la primera vez (CRM-00.02.01.08).

    No es un error, aunque llegue como excepción: la dependencia de idempotencia
    no puede responder —solo cortar—, así que corta con esto y aquí se traduce
    en la respuesta original.

    Lleva `Idempotency-Replayed` para que el cliente pueda distinguir «se ha
    hecho ahora» de «ya estaba hecho». Esa diferencia importa al conciliar, y sin
    la marca es indistinguible.
    """
    from crmcore.http.idempotency import RespuestaRepetida

    assert isinstance(exc, RespuestaRepetida)
    return JSONResponse(
        content=exc.cuerpo,
        status_code=exc.status,
        headers={"Idempotency-Replayed": "true"},
    )


def registrar_manejadores(app: FastAPI) -> None:
    """Engancha los manejadores. Lo llama la factoría de servicio."""
    from crmcore.http.idempotency import RespuestaRepetida

    app.add_exception_handler(RespuestaRepetida, manejar_repetida)  # type: ignore[arg-type]
    app.add_exception_handler(CrmError, manejar_error_dominio)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, manejar_validacion)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, manejar_http)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, manejar_no_previsto)
