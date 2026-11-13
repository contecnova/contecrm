"""Punto de entrada del gateway."""

from __future__ import annotations

import time
from typing import Any

from crmcore.errors import CuotaAgotada, NoAutenticado, Prohibido
from crmcore.http.problems import manejar_error_dominio
from crmcore.service import crear_servicio
from starlette.responses import Response

from services.gateway import api, claves, incrustable, llamadas
from services.gateway.api import ROUTERS, ROUTERS_SIN_PREFIJO, arrancar, parar

app = crear_servicio(
    nombre="gateway",
    descripcion=(
        "Única puerta de entrada: resolución de tenant, autenticación, límites "
        "y enrutado con identidad firmada. Sin lógica de negocio, a propósito."
    ),
    routers=ROUTERS,
    routers_sin_prefijo=ROUTERS_SIN_PREFIJO,
    al_arrancar=arrancar,
    al_parar=parar,
    # El gateway no publica eventos de dominio ni tiene tablas propias: su
    # estado es la tabla de rutas, que viene de la configuración.
    necesita_bus=False,
    necesita_db=False,
)


@app.middleware("http")
async def lo_que_se_incrusta(request: Any, siguiente: Any) -> Any:
    """El CORS de la captura pública y de los componentes embebidos.

    Va como middleware y POR FUERA del CORS general —lo añade `crear_servicio`
    antes que éste, así que queda dentro—, porque la pregunta previa del
    navegador (`OPTIONS`) la contesta el CORS general por su cuenta y, con un
    origen que no es la consola, la contestaba con un 400: el formulario de la
    web de un cliente no llegaba ni a salir.

    Aquí el origen es la web de cualquier cliente y la cookie del CRM no tiene
    nada que hacer: se admite el origen según `INCRUSTABLE_ORIGENES` y **nunca
    con credenciales**. Una web no admitida recibe un 403 con el formato de
    siempre, también en la pregunta previa. Sin cabecera `Origin` no se mira:
    no es un navegador, y lo que autoriza es la clave o el token.
    """
    if not incrustable.es_incrustable(request.url.path):
        return await siguiente(request)
    origen = request.headers.get("origin", "")
    if origen and not incrustable.origen_admitido(origen):
        return await manejar_error_dominio(
            request,
            Prohibido(
                "Esta web no está entre las que pueden llamar a esta dirección",
                error_code="incrustable.origen_no_admitido",
            ),
        )
    if request.method == "OPTIONS" and request.headers.get("access-control-request-method"):
        return Response(status_code=204, headers=incrustable.cabeceras_cors(origen or "*"))
    respuesta = await siguiente(request)
    if origen:
        # El CORS general, si el origen también es de la consola, ya ha puesto
        # las suyas con credenciales: se cambian por éstas.
        for nombre in ("access-control-allow-credentials", "access-control-allow-origin"):
            if nombre in respuesta.headers:
                del respuesta.headers[nombre]
        respuesta.headers.update(incrustable.cabeceras_cors(origen))
    return respuesta


@app.middleware("http")
async def resolver_clave_api(request: Any, siguiente: Any) -> Any:
    """Si la petición trae una clave de API, la convierte en identidad.

    Va como middleware y no como dependencia porque validar la clave es una
    llamada de red a `identity`, y la dependencia común que resuelve el principal
    (`crmcore.http.deps.contexto_autenticado`) la usan los trece servicios: meter
    ahí una llamada de red la pagarían todos. Aquí la paga solo quien entra con
    clave, y solo en la puerta.

    Lo que deja es `request.state.principal_precalculado`, que es el hueco que
    esa dependencia mira antes que nada.

    Un fallo de validación NO se convierte en 401 aquí: se anota y se sigue. Si
    la ruta no exigía identidad —la salud, por ejemplo— no hay motivo para
    tumbarla, y si la exigía, `exige_autenticacion` contestará su 401 de siempre
    con el formato de error de la casa. Un middleware que responde por su cuenta
    devuelve un cuerpo distinto al del resto de la API.
    """
    credencial = request.headers.get("authorization", "")
    principal = None
    cliente = url = None
    if credencial.lower().startswith("bearer "):
        secreto = credencial[7:].strip()
        if claves.es_clave(secreto):
            cliente, url = api.cliente_y_destino("identity")
            if cliente is not None and url:
                try:
                    principal = await claves.principal_de_clave(
                        cliente,
                        secreto,
                        ip=ip_de(request),
                        url_identity=url,
                    )
                    request.state.principal_precalculado = principal
                except NoAutenticado:
                    pass
                except CuotaAgotada as exc:
                    # La única respuesta que da el middleware: con la cuota
                    # gastada no hay ruta que deba contestar otra cosa. Con el
                    # mismo formato de error que el resto de la API.
                    return await manejar_error_dominio(request, exc)
    inicio = time.monotonic()
    respuesta = await siguiente(request)
    # Cada llamada hecha con clave se apunta para el portal del integrador.
    if principal is not None and cliente is not None and url:
        lote = llamadas.apuntar(
            clave_id=str(principal.id),
            tenant_id=str(principal.tenant_id),
            metodo=request.method,
            ruta=request.url.path,
            status=respuesta.status_code,
            duracion_ms=int((time.monotonic() - inicio) * 1000),
            request_id=respuesta.headers.get("x-request-id", ""),
        )
        if lote:
            llamadas.despachar(cliente, url, lote)
    return respuesta


def ip_de(request: Any) -> str:
    """La dirección de quien llama, para la lista de redes de la clave.

    `X-Forwarded-For` solo cuenta detrás de un proxy declarado; si no, cualquiera
    se pondría la dirección que le conviniera y la lista de redes de una clave
    dejaría de significar nada.
    """
    # La misma regla que el resto del producto (`crmcore.http.ip_cliente`):
    # aquí había una tercera copia que cogía el primer valor de la cabecera.
    from crmcore.http.ip_cliente import ip_del_cliente

    par = request.client.host if request.client else ""
    return ip_del_cliente(par, request.headers.get("x-forwarded-for", ""))
