"""Leer el propio CRM por su API, desde un servicio (CRM-00.05.01.07).

Hay trabajos que necesitan recorrer el CRM entero: llenar el almacén analítico,
registrar la fuente consultable, medir la salud de cada cuenta. Todos tienen el
mismo problema — los datos viven en otro servicio — y la misma tentación: leer
su esquema por debajo.

No se hace, y el motivo no es purismo. Por debajo se salta el **enmascarado por
rol**: el almacén acabaría con los campos que la API oculta, y de ahí a un cuadro
de mando que alguien comparte hay un paso. Pasando por la API con una credencial
de solo lectura, lo que se ve es exactamente lo que ve un lector.

**La credencial se pide, no se configura.** Una clave en el `.env` hay que
ponerla a mano, y esto tiene que poder ser un botón. Se emite por la ruta interna
de `identity`, que va tras la firma HMAC y que revoca la anterior con el mismo
nombre: acumular credenciales vivas es repartir llaves.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID


def url_del_crm() -> str:
    """Con qué dirección se ve a sí mismo este CRM.

    No es `public_base_url` ni `ci_base_url` al revés: es la que resuelve desde
    DENTRO de la pila, y en contenedores `localhost` es el propio proceso. Sin
    ella no se puede leer, y se dice con esas palabras en vez de fallar luego con
    un error de red que no explica nada.
    """
    from crmcore.config import get_settings
    from crmcore.errors import NoDisponible

    destino = get_settings().ci_url_del_crm or ""
    if not destino:
        raise NoDisponible(
            "Falta CI_URL_DEL_CRM: sin saber con qué dirección se ve a sí mismo, "
            "el CRM no puede leerse para llenar el almacén, registrar la fuente "
            "ni medir la salud de las cuentas.",
            error_code="integracion.sin_direccion",
        )
    return destino.rstrip("/")


def clave_de_lectura(tenant_id: UUID, *, nombre: str) -> str:
    """Emite una clave de solo lectura de ese tenant y devuelve su secreto.

    `nombre` identifica para qué es. Importa: la emisión ROTA la anterior que se
    llame igual, así que dos usos distintos con el mismo nombre se matan la llave
    entre ellos. Pasó: el registro de la fuente y el cargador del almacén
    compartían nombre, y cada carga dejaba la fuente registrada con una
    credencial revocada.
    """
    from crmcore.config import get_settings
    from crmcore.errors import ErrorDependencia
    from crmcore.http.deps import firmar_cabeceras_internas
    from crmcore.red import cliente_seguro

    s = get_settings()
    destino = _url_de_identity(s)
    cabeceras = firmar_cabeceras_internas({}, s.secret_key.get_secret_value())
    with cliente_seguro(timeout=10.0) as cli:
        respuesta = cli.post(
            f"{destino}/api/v1/claves-api/interna",
            json={"tenant_id": str(tenant_id), "nombre": nombre},
            headers=cabeceras,
        )
    if respuesta.status_code != 201:
        raise ErrorDependencia(
            f"No se ha podido emitir la clave de lectura «{nombre}»",
            error_code="integracion.sin_clave",
            detalle={"codigo_http": respuesta.status_code},
        )
    return str(respuesta.json()["secreto"])


def _url_de_identity(s: Any) -> str:
    """La dirección de `identity` en este despliegue, de `RUTAS_SERVICIOS`."""
    from crmcore.errors import ErrorDependencia

    for trozo in (s.rutas_servicios or "").replace("\n", " ").split(","):
        nombre, _, url = trozo.strip().partition("=")
        if nombre.strip() == "identity" and url.strip():
            return url.strip().rstrip("/")
    raise ErrorDependencia(
        "No hay dirección de `identity` en RUTAS_SERVICIOS",
        error_code="integracion.sin_identity",
    )
