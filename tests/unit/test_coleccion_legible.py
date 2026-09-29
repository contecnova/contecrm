"""Lo que se puede crear se tiene que poder leer.

Cuarenta colecciones del sistema tenían `POST` y no tenían `GET`: una cola de
casos, un canal de entrada, una lista de precios o un contrato se daban de alta
y desaparecían. La API contestaba **405 Method Not Allowed** y el front —que
declara esos recursos como listables— enseñaba una pantalla vacía sin decir por
qué. No era un fallo visible: era un agujero silencioso, y solo salió al abrir
la consola del navegador y mirar los errores uno a uno.

Este gate recorre las rutas **realmente montadas** en cada servicio, no los
decoradores del fichero: parte de los listados se registran desde
`crmcore.http.listados`, que un análisis del texto no ve. Si alguien añade un
`POST` a una colección nueva y se olvida del `GET`, falla aquí.

Las excepciones se nombran una a una **con su motivo**. Una excepción sin motivo
acaba siendo la puerta por la que vuelve el problema.
"""

from __future__ import annotations

import importlib
import os
from collections import defaultdict

import pytest

SERVICIOS = [
    "tenancy",
    "identity",
    "metadata",
    "orchestrator",
    "automation",
    "integration",
    "eventing",
    "party",
    "sales",
    "analytics",
    "intelligence",
    "service",
    "marketing",
]

# Rutas que aceptan `POST` sobre la raíz y **no son una colección**: serían
# acciones, donde listar no significa nada porque lo que hay es un efecto y no
# un conjunto.
#
# Hoy está vacío, y eso es el resultado: no queda ninguna. Se deja el mecanismo
# porque la próxima acción de ese tipo tendrá que declararse aquí **con su
# motivo** — una excepción sin motivo acaba siendo la puerta por la que vuelve
# el problema.
ACCIONES: dict[str, str] = {
    # Subcolecciones que SÍ se leen, por una puerta mejor que la suya. Cada una
    # con dónde, para que la exención se pueda comprobar y no sea un permiso.
    #
    # Se verificaron una a una antes de escribirlas aquí: de siete que marcó el
    # gate al extenderlo, seis tenían puerta. Una candidata es una hipótesis.
    "/accounts/{cuenta_id}/direcciones": "las devuelve `GET /accounts/{id}/360`",
    "/contacts/{contacto_id}/cuentas": (
        "se leen desde el otro lado, en `GET /accounts/{id}/relaciones`; la "
        "asimetría es real pero el dato se alcanza"
    ),
    "/proveedores/{cuenta_id}/homologacion": (
        "las lista `GET /proveedores/{id}/homologaciones`, que se añadió justo "
        "por esto: «se podía consultar de una en una sabiendo ya el nombre»"
    ),
    "/metadata/objetos/{nombre}/campos": (
        "los devuelve `GET /metadata/objetos/{nombre}/describe`, con sus "
        "validaciones y layouts — que es lo que un frontend necesita"
    ),
    "/sso-gobierno/proveedores/{proveedor_id}/certificados": (
        "los revisa `GET /factores/certificados`, que es donde se miran: con su "
        "caducidad al lado"
    ),
    "/tenants/{tenant_id}/exportacion": (
        "las lista `GET /tenants/{id}/exportaciones`, en plural: el alta va en "
        "singular y el listado en plural, así que el gate no los empareja"
    ),
    "/integraciones/conexiones/{conexion_id}/operaciones": (
        "vienen dentro del manifiesto de la conexión, que es de donde salen"
    ),
}


@pytest.fixture(autouse=True)
def _devolver_el_servicio():
    """Deja `SERVICE_NAME` como estaba.

    Estas pruebas cambian el servicio en curso para cargar el contrato de cada
    uno. Sin devolverlo, la siguiente prueba del fichero siguiente arranca
    creyendo que es otro servicio y falla por un motivo que no tiene nada que
    ver con lo que comprueba — que es la peor forma de fallo que puede tener una
    suite, porque se busca donde no está.
    """
    from crmcore.config import limpiar_cache_settings

    previo = os.environ.get("SERVICE_NAME")
    try:
        yield
    finally:
        if previo is None:
            os.environ.pop("SERVICE_NAME", None)
        else:
            os.environ["SERVICE_NAME"] = previo
        limpiar_cache_settings()


def _contrato(servicio: str) -> dict[str, dict[str, set[str]]]:
    """Camino → métodos, leído del contrato OpenAPI del servicio.

    Del contrato y no de `app.routes`: esta versión de FastAPI envuelve los
    routers incluidos en objetos `_IncludedRouter`, así que recorrer `routes`
    devuelve envoltorios y no rutas — y un gate que recorre envoltorios no ve
    nada y pasa siempre. Pasó: la primera versión de este fichero daba verde
    sobre un sistema con cuarenta colecciones ilegibles.
    """
    os.environ["SERVICE_NAME"] = servicio
    from crmcore.config import limpiar_cache_settings

    limpiar_cache_settings()
    app = importlib.import_module(f"services.{servicio}.main").app
    por_camino: dict[str, set[str]] = defaultdict(set)
    for camino, operaciones in (app.openapi().get("paths") or {}).items():
        if camino.startswith("/api/v1/"):
            por_camino[camino].update(m.upper() for m in operaciones)
    return por_camino


def _colecciones(por_camino: dict[str, set[str]]) -> list[str]:
    """Los caminos que son una colección, no una acción.

    El criterio: hay fichas colgando de él, es decir existe `<camino>/{algo}`.
    Sin esta distinción el gate marcaría también `/activos-marketing/aprobacion`
    —aprobar un activo— y exigirle un listado, que no significa nada: lo que hay
    ahí es un efecto, no un conjunto.
    """
    caminos = set(por_camino)
    salida = []
    for camino in caminos:
        # LAS SUBCOLECCIONES TAMBIÉN. Esto se saltaba cualquier camino con `{`, o
        # sea que la regla estaba escrita y **no se aplicaba justo donde más se
        # incumple**: las direcciones de una cuenta, los miembros de una campaña,
        # las excepciones de segregación de funciones. Una auditoría a mano tardó
        # ochenta y nueve minutos en encontrar UNA de esta forma; al mirar aquí
        # salieron once en segundos.
        #
        # Lo que sí se exige es que sea un CONJUNTO y no un efecto: se reconoce
        # porque cuelgan fichas de él, igual que en la raíz. Sin eso, el gate le
        # pediría un listado a `/activos/{id}/archivar`, que no significa nada.
        if camino.rstrip("/").endswith("}"):
            continue
        if any(
            otro.startswith(camino + "/") and otro[len(camino) + 1 :].startswith("{")
            for otro in caminos
        ):
            salida.append(camino)
    return sorted(salida)


@pytest.mark.parametrize("servicio", SERVICIOS)
def test_toda_coleccion_que_admite_alta_se_puede_listar(servicio: str) -> None:
    por_camino = _contrato(servicio)
    # Un contrato vacío dejaría este gate en verde sin haber mirado nada, que es
    # el defecto que costó 709 rutas sin comprobar en la prueba de fugas.
    assert por_camino, (
        f"«{servicio}» no publica contrato: o ha cambiado de forma o leerlo se ha "
        "roto. Las dos cosas hay que mirarlas."
    )
    sin_listado: list[str] = []
    for camino in _colecciones(por_camino):
        metodos = por_camino[camino]
        if "POST" not in metodos or "GET" in metodos:
            continue
        relativo = camino[len("/api/v1") :]
        if relativo in ACCIONES:
            continue
        sin_listado.append(relativo)

    assert not sin_listado, (
        f"En «{servicio}» hay colecciones que se pueden crear y no se pueden leer:\n  "
        + "\n  ".join(sin_listado)
        + "\n\nMonta su listado con `crmcore.http.listados.montar_listado`, o —si es "
        "una acción y no una colección— añádela a `ACCIONES` **con su motivo**."
    )


def test_las_excepciones_declaradas_siguen_existiendo() -> None:
    """Una excepción que sobra es la que tapará algo el día que vuelva.

    Si una de estas rutas desaparece o gana su listado, su línea aquí deja de
    tener sentido. Sin esta comprobación, la lista solo crece.
    """
    vistas: set[str] = set()
    for servicio in SERVICIOS:
        por_camino = _contrato(servicio)
        for camino in _colecciones(por_camino):
            if "POST" in por_camino[camino] and "GET" not in por_camino[camino]:
                vistas.add(camino[len("/api/v1") :])

    sobran = sorted(set(ACCIONES) - vistas)
    assert not sobran, "Excepciones declaradas que ya no hacen falta:\n  " + "\n  ".join(sobran)
