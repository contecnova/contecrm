"""Un tenant suspendido no escribe, y se comprueba EN EL GATEWAY (CRM-00.01.03.04).

La comprobación llevaba escrita en `tenancy` desde el principio, y su propia
documentación decía «lo llama el gateway en cada petición». **No era verdad.**
El 28-09-2026 se montó el caso: un tenant SUSPENDIDO creó una cuenta —201— y uno
en solo lectura también. No era un guardián apagado: era un guardián que nunca se
encendió y que se contaba como encendido.

Por eso esto prueba **la ruta del gateway**, y no la función. Probar la función
habría salido en verde todo este tiempo: la función siempre estuvo bien. Lo que
faltaba era que alguien la llamara, y eso sólo se ve pidiendo lo que tendría que
impedirse.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest

SUSPENDIDO = {
    "estado": "suspendido",
    "puede_leer": False,
    "puede_escribir": False,
    "motivo": "impago",
}
SOLO_LECTURA = {
    "estado": "solo_lectura",
    "puede_leer": True,
    "puede_escribir": False,
    "motivo": "mantenimiento",
}
ACTIVO = {"estado": "activo", "puede_leer": True, "puede_escribir": True, "motivo": ""}


@pytest.fixture(autouse=True)
def _sin_memoria() -> Any:
    """La caché se vacía entre pruebas: si no, la primera decide el resto."""
    from services.gateway import operatividad

    operatividad.limpiar_cache()
    yield
    operatividad.limpiar_cache()


def _cliente(estado: dict[str, Any], recibidas: list[httpx.Request]) -> httpx.AsyncClient:
    def responder(peticion: httpx.Request) -> httpx.Response:
        recibidas.append(peticion)
        if "/operatividad" in peticion.url.path:
            return httpx.Response(200, json=estado)
        return httpx.Response(201, json={"id": str(uuid4())})

    return httpx.AsyncClient(transport=httpx.MockTransport(responder))


async def _pedir(estado: dict[str, Any], metodo: str) -> tuple[Any, list[httpx.Request]]:
    from crmcore.errors import CrmError

    from services.gateway import operatividad

    recibidas: list[httpx.Request] = []
    async with _cliente(estado, recibidas) as cliente:
        try:
            await operatividad.exigir(cliente, "http://tenancy", uuid4(), metodo)
        except CrmError as exc:
            return exc, recibidas
    return None, recibidas


async def test_un_tenant_suspendido_no_pasa_ni_a_leer() -> None:
    fallo, _ = await _pedir(SUSPENDIDO, "GET")
    assert fallo is not None, "Un tenant SUSPENDIDO ha pasado el gateway"
    assert fallo.error_code == "tenant.suspendido"
    # Con el motivo dentro: «suspendido» a secas obliga a llamar para saber por qué.
    assert "impago" in str(fallo)


async def test_en_solo_lectura_se_lee_pero_no_se_escribe() -> None:
    """La ventana de mantenimiento sin corte (CRM-08.02.01.03).

    Es la razón de ser del estado: quien consulta sigue trabajando y quien
    escribe recibe un error que dice qué pasa, en vez de una pantalla colgada.
    """
    lectura, _ = await _pedir(SOLO_LECTURA, "GET")
    assert lectura is None, "En solo lectura, leer tiene que seguir funcionando"

    for metodo in ("POST", "PUT", "PATCH", "DELETE"):
        escritura, _ = await _pedir(SOLO_LECTURA, metodo)
        assert escritura is not None, f"{metodo} ha pasado con el tenant en solo lectura"
        assert escritura.error_code == "tenant.solo_lectura"


async def test_un_tenant_activo_pasa() -> None:
    """El control. Sin esto, una guarda que lo bloqueara todo pasaría las otras
    dos con matrícula de honor."""
    for metodo in ("GET", "POST", "DELETE"):
        fallo, _ = await _pedir(ACTIVO, metodo)
        assert fallo is None, f"{metodo} bloqueado con el tenant activo: {fallo}"


async def test_un_tenant_que_no_existe_no_opera() -> None:
    """404 al preguntar es «no puede», no «no se sabe».

    Dejarlo pasar porque la respuesta fue 404 sería lo contrario de lo que este
    módulo hace.
    """
    recibidas: list[httpx.Request] = []

    def responder(peticion: httpx.Request) -> httpx.Response:
        recibidas.append(peticion)
        return httpx.Response(404, json={"detail": "no existe"})

    from crmcore.errors import CrmError

    from services.gateway import operatividad

    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as cliente:
        with pytest.raises(CrmError) as excinfo:
            await operatividad.exigir(cliente, "http://tenancy", uuid4(), "GET")
    assert excinfo.value.error_code == "tenant.suspendido"


async def test_se_pregunta_una_vez_y_no_en_cada_peticion() -> None:
    """Preguntar en cada petición doblaría la latencia de todo el sistema."""
    from services.gateway import operatividad

    recibidas: list[httpx.Request] = []
    tenant = uuid4()
    async with _cliente(ACTIVO, recibidas) as cliente:
        for _ in range(5):
            await operatividad.exigir(cliente, "http://tenancy", tenant, "GET")

    preguntas = [r for r in recibidas if "/operatividad" in r.url.path]
    assert len(preguntas) == 1, f"Se ha preguntado {len(preguntas)} veces en cinco peticiones"


async def test_si_tenancy_no_contesta_se_deja_pasar_y_se_deja_constancia() -> None:
    """Abrir y no cerrar, a propósito.

    Cerrar el sistema entero porque el servicio de tenants está reiniciándose
    convertiría una molestia en una caída total, y lo que se protege aquí
    —cobrar, y una ventana de mantenimiento— aguanta unos segundos. Lo que no
    puede pasar es que no se entere nadie.
    """
    from crmcore.errors import CrmError

    from services.gateway import operatividad

    def responder(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("tenancy no responde")

    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as cliente:
        try:
            await operatividad.exigir(cliente, "http://tenancy", uuid4(), "POST")
        except CrmError as exc:  # pragma: no cover — no debe pasar
            pytest.fail(f"Se ha cerrado el paso porque tenancy no contesta: {exc}")


async def test_sin_tenant_no_hay_nada_que_comprobar() -> None:
    """Las rutas de entrar ocurren antes de estar dentro de ningún tenant."""
    from services.gateway import operatividad

    recibidas: list[httpx.Request] = []
    async with _cliente(SUSPENDIDO, recibidas) as cliente:
        await operatividad.exigir(cliente, "http://tenancy", None, "POST")
    assert recibidas == [], "Se ha preguntado por un tenant que no hay"


def test_el_gateway_lo_llama_de_verdad_antes_de_reenviar() -> None:
    """Lo que faltaba no era la función: era la llamada.

    Esta prueba existe porque la comprobación anterior estaba escrita, probada
    y muerta. Si alguien quita la llamada del proxy, todo lo de arriba seguiría
    en verde y la suspensión volvería a no aplicarse.
    """
    import inspect

    from services.gateway import api

    fuente = inspect.getsource(api.proxy_api)
    assert "operatividad.exigir" in fuente, (
        "El proxy del gateway ya no comprueba si el tenant puede operar. Es el "
        "único paso obligado de la API: sin esta llamada, un tenant suspendido "
        "vuelve a escribir y ninguna otra prueba lo nota."
    )
    # Y ANTES de reenviar, no después: comprobarlo cuando el dato ya se ha
    # escrito no es comprobarlo.
    assert fuente.index("operatividad.exigir") < fuente.index(
        "proxy.reenviar"
    ), "La comprobación tiene que ir ANTES de reenviar la petición."


def test_el_plazo_de_la_cache_es_configurable() -> None:
    """Nada a fuego: una instalación que no pueda esperar treinta segundos a que
    una suspensión surta efecto tiene que poder bajarlo sin tocar el producto."""
    from crmcore.runtime.keys import CLAVES

    assert "gateway_operatividad_ttl_s" in CLAVES
