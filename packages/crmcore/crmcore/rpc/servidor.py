"""El transporte gRPC, que es opcional (CRM-00.02.01.03).

**Dependencia opcional, y a propósito**, igual que SAML: `grpcio` trae una
extensión en C que tarda en instalarse y ocupa, y la inmensa mayoría de las
instalaciones hablan HTTP y JSON y no lo van a usar nunca. Ponerlo en
`requirements.txt` sería cobrarle ese peso a todo el mundo para el cliente que
mueve millones de filas.

Sin la librería, esto no es un hueco callado: `disponible()` dice que no y
`exigir_disponible()` explica qué instalar. El **contrato** —`crmcore.rpc.esquema`
y `crmcore.rpc.mensajes`— no es opcional y funciona siempre: el `.proto` se
genera y la compatibilidad se comprueba en el preflight aunque aquí no haya
transporte.

Y la decisión que importa:

**La misma identidad, los mismos permisos y el mismo tenant que HTTP.** Una
segunda puerta que valide el token con su propio código es la puerta por la que
se entra: las dos implementaciones divergen, la que menos gente mira se queda
atrás, y el día que se endurece algo se endurece en una sola. Aquí el token lo
valida `crmcore.http.deps.principal_de_token`, que es literalmente el mismo que
usa REST.

**Y un flujo abierto no es gratis.** Un `List` en streaming que el cliente deja
colgado retiene una conexión de base de datos hasta que alguien la mata: por eso
hay tope de elementos y de tiempo, y los dos salen de `Settings`.
"""

from __future__ import annotations

import re
from typing import Any

from crmcore.errors import NoAutenticado, NoDisponible, PeticionMalFormada
from crmcore.logging import get_logger

logger = get_logger(__name__)

PISTA_INSTALACION = (
    "El transporte gRPC necesita la librería opcional `grpcio`. No está en "
    "`requirements.txt` porque trae una extensión en C que tarda en instalarse y que "
    "no usa casi ningún despliegue. Para activarlo: `pip install -r "
    "requirements-grpc.txt`. El contrato protobuf (`crmcore.rpc.esquema`) funciona "
    "sin ella."
)

# `/crm.contacto.v1.ContactoService/Get`
RE_METODO = re.compile(
    r"^/(?P<paquete>[\w.]+)\.(?P<objeto>\w+)\.v(?P<version>\d+)\.\w+/(?P<metodo>\w+)$"
)

METODOS = ("Get", "List", "Create", "Update", "Watch")


def disponible() -> bool:
    """Si este despliegue tiene el transporte instalado."""
    try:
        import grpc  # noqa: F401
    except ImportError:
        return False
    return True


def exigir_disponible() -> None:
    if not disponible():
        raise NoDisponible(
            "Este despliegue no tiene el transporte gRPC instalado",
            error_code="rpc.no_instalado",
            detalle={"como_instalarlo": PISTA_INSTALACION},
        )


def resolver_metodo(ruta: str) -> dict[str, Any]:
    """Descompone la ruta de un método gRPC.

    Se rechaza lo que no encaja en vez de intentar adivinar. Adivinar aquí
    significa servir `contacto` a quien pidió `contactos`, y el cliente se queda
    con datos de un objeto que no es el suyo creyendo que la integración va bien.
    """
    encaje = RE_METODO.match(ruta or "")
    if not encaje:
        raise PeticionMalFormada(
            f"Ruta gRPC que no corresponde a ningún contrato: «{ruta}»",
            error_code="rpc.ruta_desconocida",
            detalle={"forma_esperada": "/crm.<objeto>.v<n>.<Objeto>Service/<Metodo>"},
        )
    metodo = encaje.group("metodo")
    if metodo not in METODOS:
        raise PeticionMalFormada(
            f"Método «{metodo}» que no existe en el contrato",
            error_code="rpc.metodo_desconocido",
            detalle={"metodos": list(METODOS)},
        )
    return {
        "paquete": encaje.group("paquete"),
        "objeto": encaje.group("objeto"),
        "version": int(encaje.group("version")),
        "metodo": metodo,
    }


def principal_de_metadatos(metadatos: list[tuple[str, str]] | dict[str, str]) -> Any:
    """Quién llama, validando el token **con el mismo código que HTTP**.

    No hay «autenticación de gRPC»: hay la autenticación del CRM, a la que se
    llega también por aquí. Montar aquí otra validación es garantizar que dentro
    de un año dicen cosas distintas, y la que se quede atrás será esta, que la
    mira menos gente.
    """
    from crmcore.config import get_settings
    from crmcore.http.deps import principal_de_token

    pares = dict(metadatos) if not isinstance(metadatos, dict) else dict(metadatos)
    # gRPC obliga a que las claves de metadatos vayan en minúsculas; HTTP no
    # distingue. Se normaliza para que el mismo cliente valga en los dos sitios.
    pares = {str(k).lower(): v for k, v in pares.items()}

    autorizacion = str(pares.get("authorization") or "")
    if not autorizacion.lower().startswith("bearer "):
        raise NoAutenticado(
            "Falta el metadato `authorization` con un token Bearer. gRPC no tiene "
            "cookies ni sesión: la identidad viaja en los metadatos de cada llamada.",
            error_code="rpc.sin_token",
        )
    return principal_de_token(autorizacion[7:].strip(), get_settings().jwt_secret)


def limites(settings: Any) -> dict[str, int]:
    """Los topes del transporte, **de la configuración y no del código**.

    Un flujo abierto retiene una conexión de base de datos mientras dura. Sin
    tope, un cliente que abre un `Watch` y se va de vacaciones deja esa conexión
    ocupada hasta que alguien mira por qué el pool está lleno.
    """
    return {
        "mensaje_max_bytes": int(settings.grpc_mensaje_max_bytes),
        "elementos_por_flujo": int(settings.grpc_elementos_por_flujo),
        "segundos_por_flujo": int(settings.grpc_segundos_por_flujo),
    }


def crear_servidor(
    *,
    manejadores: dict[str, Any],
    settings: Any,
    direccion: str = "0.0.0.0:50051",
) -> Any:
    """Levanta el servidor gRPC con un manejador genérico.

    **Genérico a propósito**: los objetos los define cada tenant en el
    metamodelo, así que no hay stubs compilados que registrar. El descriptor se
    construye en memoria (`crmcore.rpc.mensajes`) desde la misma declaración que
    genera el `.proto`, y por eso el fichero que se le da al integrador y lo que
    el servidor entiende no pueden decir cosas distintas.

    `manejadores` es `{"Get": callable, ...}`; cada uno recibe
    `(principal, objeto, peticion)` y devuelve un diccionario o un iterable de
    diccionarios. Los reales son los mismos que sirven REST: si no lo fueran,
    habría dos sitios donde se aplican las reglas de negocio y solo uno al día.
    """
    exigir_disponible()
    import grpc

    topes = limites(settings)
    faltan = sorted(set(METODOS) - set(manejadores))
    if faltan:
        raise NoDisponible(
            f"No se puede levantar gRPC sin manejador para: {', '.join(faltan)}. "
            "Publicar un método del contrato que contesta «no implementado» es peor "
            "que no publicarlo: el que integra lo descubre en su despliegue.",
            error_code="rpc.manejador_incompleto",
        )

    def _despachar(peticion: bytes, contexto: Any, ruta: str) -> Any:
        partes = resolver_metodo(ruta)
        principal = principal_de_metadatos(list(contexto.invocation_metadata()))
        return manejadores[partes["metodo"]](principal, partes["objeto"], peticion)

    class _Generico(grpc.GenericRpcHandler):
        def service(self, detalles: Any) -> Any:
            ruta = detalles.method
            partes = resolver_metodo(ruta)
            en_flujo = partes["metodo"] in ("List", "Watch")
            manejador = (
                grpc.unary_stream_rpc_method_handler
                if en_flujo
                else (grpc.unary_unary_rpc_method_handler)
            )
            return manejador(
                lambda peticion, contexto, _r=ruta: _despachar(peticion, contexto, _r),
                request_deserializer=bytes,
                response_serializer=bytes,
            )

    servidor = grpc.server(
        futures_threadpool(),
        options=[
            ("grpc.max_receive_message_length", topes["mensaje_max_bytes"]),
            ("grpc.max_send_message_length", topes["mensaje_max_bytes"]),
        ],
        handlers=(_Generico(),),
    )
    servidor.add_insecure_port(direccion)
    logger.info(
        "grpc.levantado",
        extra={"direccion": direccion, "topes": topes},
    )
    return servidor


def futures_threadpool() -> Any:
    """El pool del servidor. Acotado: sin tope, cada llamada abre un hilo y una
    conexión, y un cliente entusiasta agota el pool de la base de datos."""
    from concurrent import futures

    return futures.ThreadPoolExecutor(max_workers=16)
