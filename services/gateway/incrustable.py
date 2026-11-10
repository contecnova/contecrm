"""Lo que se llama desde la web de otro: la captura pública y los componentes.

Dos puertas que no son la API de siempre, porque quien llama no es nadie que
haya entrado: es el navegador de un desconocido en la web de un cliente.

  * **`POST /captura/{tenant}/{clave}`** — el formulario de contacto de la web
    (CRM-01.01.03.02). Lo autoriza la clave del canal; no lleva identidad.
  * **`/api/v1/embebido/<componente>`** — los componentes que se incrustan
    (CRM-00.02.03.05). Los autoriza un token acotado a un registro.

El gateway las reenvía **por su nombre**, no abriendo un prefijo: sólo reenviaba
`/api/*`, y la captura —que va sin prefijo a propósito, ver `services/sales/
api.py`— contestaba 404 desde fuera. Y les pone lo que es de la puerta y no
puede ponerse detrás, donde todas las peticiones llegan con la dirección del
gateway: el tope por IP, el tamaño del cuerpo y de qué webs se admiten. Lo que
es del canal —la clave, la trampa, el tope por hora— sigue en `sales`.

**Por qué el CORS de estas rutas es otro.** El de la aplicación admite la
consola y manda la cookie (`allow_credentials`); aquí el origen es la web de un
cliente cualquiera y la cookie del CRM no tiene nada que hacer. Con el CORS
general, el navegador ni siquiera dejaba salir la petición del formulario.

**Los ajustes son del `.env`, no de la consola.** El gateway no tiene base de
datos (`necesita_db=False`), así que un ajuste en caliente aquí se guardaría y
no se aplicaría nunca, que es peor que no poder tocarlo.
"""

from __future__ import annotations

from typing import Any

from crmcore.config import get_settings
from crmcore.errors import CuerpoDemasiadoGrande

# Lo único que se reenvía de la petición del navegador a `sales` en la captura.
# Una lista de las que SÍ, y aquí está bien que se quede corta: es una puerta
# pública, y lo que no está en la lista no tiene por qué llegar.
CABECERAS_DE_CAPTURA = ("content-type", "x-captura-secreto")


def es_incrustable(ruta: str) -> bool:
    """¿Es una de las dos puertas que se llaman desde la web de otro?"""
    prefijo = get_settings().api_prefix.rstrip("/")
    return ruta.startswith("/captura/") or ruta.startswith(f"{prefijo}/embebido/")


def _origenes() -> list[str]:
    crudo = get_settings().incrustable_origenes
    return [o.strip().rstrip("/") for o in crudo.split(",") if o.strip()]


def origen_admitido(origen: str) -> bool:
    """Si una web puede llamar a estas puertas desde el navegador."""
    admitidos = _origenes()
    return "*" in admitidos or origen.rstrip("/") in admitidos


def cabeceras_cors(origen: str) -> dict[str, str]:
    """Las de CORS para una web admitida. **Sin credenciales**, nunca."""
    abierto = "*" in _origenes()
    cabeceras = {
        "access-control-allow-origin": "*" if abierto else origen,
        "access-control-allow-methods": "GET, POST, OPTIONS",
        "access-control-allow-headers": "Authorization, Content-Type, X-Captura-Secreto",
        "access-control-expose-headers": "X-Request-Id, Retry-After",
        "access-control-max-age": "600",
    }
    if not abierto:
        # La respuesta cambia según quién pregunta: una caché intermedia que
        # no lo sepa le serviría a una web la respuesta de otra.
        cabeceras["vary"] = "Origin"
    return cabeceras


async def cuerpo_acotado(request: Any) -> bytes:
    """El cuerpo de la petición, cortando en cuanto pase del máximo.

    Se mira la longitud declarada y **también lo que llega**: un cuerpo por
    trozos no declara longitud, y leerlo entero antes de medirlo es justo lo
    que el tope quiere evitar. Lo leído se deja en la petición para que quien
    venga detrás lo encuentre.
    """
    maximo = int(get_settings().captura_publica_max_bytes)
    error = CuerpoDemasiadoGrande(
        f"Lo enviado pasa del máximo de {maximo} bytes",
        error_code="incrustable.cuerpo_demasiado_grande",
        detalle={"maximo_bytes": maximo},
    )
    declarada = request.headers.get("content-length", "")
    if declarada.isdigit() and int(declarada) > maximo:
        raise error
    cuerpo = b""
    async for trozo in request.stream():
        cuerpo += trozo
        if len(cuerpo) > maximo:
            raise error
    request._body = cuerpo
    return cuerpo
