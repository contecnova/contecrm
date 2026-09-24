"""Punto de entrada del gateway."""

from __future__ import annotations

from typing import Any

from crmcore.config import get_settings
from crmcore.errors import NoAutenticado
from crmcore.service import crear_servicio

from services.gateway import api, claves
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
    if credencial.lower().startswith("bearer "):
        secreto = credencial[7:].strip()
        if claves.es_clave(secreto):
            cliente, url = api.cliente_y_destino("identity")
            if cliente is not None and url:
                try:
                    request.state.principal_precalculado = await claves.principal_de_clave(
                        cliente,
                        secreto,
                        ip=ip_de(request),
                        url_identity=url,
                    )
                except NoAutenticado:
                    pass
    return await siguiente(request)


def ip_de(request: Any) -> str:
    """La dirección de quien llama, para la lista de redes de la clave.

    `X-Forwarded-For` solo cuenta detrás de un proxy declarado; si no, cualquiera
    se pondría la dirección que le conviniera y la lista de redes de una clave
    dejaría de significar nada.
    """
    s = get_settings()
    if s.trust_proxy_headers:
        reenviada = request.headers.get("x-forwarded-for", "")
        if reenviada:
            return reenviada.split(",")[0].strip()
    return request.client.host if request.client else ""
