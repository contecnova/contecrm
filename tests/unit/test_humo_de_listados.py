"""Ninguna ruta de listado revienta al abrirla (barrido de humo).

POR QUÉ. Hoy han salido cuatro cosas marcadas «hecho» que no funcionaban, y las
cuatro pasaban todos los gates: descargar un informe en CSV era un 500, los
informes programados fallaban cada noche, ocho rutas estaban publicadas sin
responder y el comentario de cada aprobación se perdía. El criterio de «hecho»
exige código, prueba y manual, y **ninguna de las tres cosas comprueba que la
vía real devuelva algo**.

Esta prueba es esa comprobación que faltaba, en su forma más barata: se abre
cada listado sin parámetros, como lo abre una pantalla al entrar, y se exige que
no conteste 500. No mira que el dato sea el correcto —eso es de cada prueba de
dominio— sino que la ruta exista, se resuelva y devuelva algo. Es exactamente el
fallo que ninguna prueba de función caza, porque la función está bien y lo que
está mal es el camino.

Un 500 aquí es una pantalla en blanco para alguien. No hay excepciones: si una
ruta no puede contestar sin datos, contesta vacío, no revienta.

HASTA DÓNDE SE HA COMPROBADO, a día 28-09-2026: **`party`, `sales` y `service`
en verde. Los otros diez servicios NO se han llegado a correr enteros.** La
tanda completa pasa de diez minutos y se cortó tres veces por tiempo y por
carga de la máquina. Así que de esos diez no se sabe si hay listados rotos —no
es que estén bien: es que no se han mirado—, y queda dicho aquí y no sólo en la
cabeza de quien lo escribió.
"""

from __future__ import annotations

import importlib
import os
from typing import Any
from uuid import UUID

import pytest

# Su fallo llega a producción y no se arregla después: una fuga entre tenants o
# una ruta publicada que no responde. Por eso esta prueba NO sale del push.
pytestmark = pytest.mark.despliegue

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


@pytest.fixture(autouse=True)
def _devolver_el_servicio() -> Any:
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


def _cabeceras(tenant_id: UUID) -> dict[str, str]:
    """Identidad firmada de administrador del tenant.

    Con `*:*`: un 403 por falta de permiso taparía el 500 que se busca, y la
    prueba pasaría por el motivo equivocado.
    """
    from uuid import uuid4

    from crmcore.config import get_settings
    from crmcore.http.deps import H_PERMISOS, H_TENANT, H_USER, firmar_cabeceras_internas

    return firmar_cabeceras_internas(
        {H_TENANT: str(tenant_id), H_USER: str(uuid4()), H_PERMISOS: "*:*"},
        get_settings().secret_key.get_secret_value(),
    )


def _listados_de(app: Any) -> list[str]:
    """Las rutas que se abren solas: GET, sin parámetros y sin datos exigidos."""
    caminos = []
    for camino, ops in (app.openapi().get("paths") or {}).items():
        if "{" in camino or not camino.startswith("/api/v1/"):
            continue
        get = ops.get("get")
        if get is None:
            continue
        # Las que exigen algo por la URL contestan 422, no 500, y ese no es el
        # fallo que se busca aquí: se saltan para que el resultado sea legible.
        if any(p.get("required") for p in get.get("parameters") or []):
            continue
        # LOS FLUJOS DE EVENTOS NO SE ABREN AQUÍ, y no es una excepción cómoda:
        # un `text/event-stream` se queda abierto a propósito mandando lo que
        # pasa, así que pedirlo y esperar a que termine es esperar para siempre.
        # Colgó este barrido diez minutos en `identity` —`/chat/eventos`— y es
        # el mismo tropiezo que ya tuvo el registro de fuentes, que lo resolvió
        # con un plazo corto. Aquí no hace falta plazo: se reconoce por lo que
        # el propio contrato declara que devuelve.
        respuestas = (get.get("responses") or {}).get("200") or {}
        if "text/event-stream" in (respuestas.get("content") or {}):
            continue
        caminos.append(camino)
    return sorted(caminos)


def _escrituras_de(app: Any) -> list[tuple[str, str]]:
    """Las escrituras a una COLECCIÓN: crear algo donde antes no había nada.

    Solo las que no llevan parámetros en la ruta. Las que sí los llevan —editar
    o borrar un registro concreto— ya las recorre `test_fuzzing_tenant` con un
    identificador de otro tenant, y repetirlas aquí sería pagar dos veces por lo
    mismo.
    """
    caminos = []
    for camino, ops in (app.openapi().get("paths") or {}).items():
        if "{" in camino or not camino.startswith("/api/v1/"):
            continue
        for metodo in ("post", "put", "patch"):
            if metodo in ops:
                caminos.append((metodo.upper(), camino))
    return sorted(caminos)


@pytest.mark.parametrize("servicio", SERVICIOS)
def test_ninguna_escritura_revienta_con_el_cuerpo_vacio(
    servicio: str, db: Any, tenant_id: UUID
) -> None:
    """Mandar `{}` a una escritura tiene que dar 422, nunca 500.

    Un 422 es la respuesta correcta —«te faltan estos campos»— y es lo que
    convierte un formulario en algo que se puede rellenar. Un 500 es una
    pantalla que dice «error interno» sin decir qué falta, y además **puede
    dejar datos a medias**: una escritura que revienta después de haber escrito
    algo es peor que una que no escribe.

    Esto es el complemento del barrido de listados, que solo abría los GET. Lo
    que de verdad hace daño está en el otro lado: quien lee un listado roto ve
    una pantalla vacía, y quien manda una escritura rota puede dejar el registro
    partido por la mitad.
    """
    from crmcore.config import limpiar_cache_settings
    from fastapi.testclient import TestClient

    os.environ["SERVICE_NAME"] = servicio
    limpiar_cache_settings()
    app = importlib.import_module(f"services.{servicio}.main").app

    cliente = TestClient(app, raise_server_exceptions=False)
    cabeceras = _cabeceras(tenant_id)
    rotas: list[str] = []
    for metodo, camino in _escrituras_de(app):
        respuesta = cliente.request(metodo, camino, headers=cabeceras, json={})
        # SOLO EL 500, y no todo lo que empieza por cinco. Un 502 o un 503 son
        # respuestas previstas y con motivo —«falta la dirección de identity»—
        # y eso no es un fallo: es el sistema diciendo qué le falta. El 500 es
        # el que no dice nada, y es el que puede haber dejado algo a medias.
        #
        # La primera versión exigía `>= 500` y marcó en rojo una ruta que no
        # lleva cuerpo: con `{}` hace su trabajo, llama al vecino y contesta 502
        # porque en el entorno de pruebas no hay vecino. La prueba estaba mal, no
        # la ruta.
        if respuesta.status_code == 500:
            detalle = ""
            try:
                detalle = str(respuesta.json())[:160]
            except Exception:  # noqa: BLE001
                detalle = respuesta.text[:160]
            rotas.append(f"{respuesta.status_code} {metodo} {camino} → {detalle}")

    assert not rotas, (
        f"En «{servicio}» hay escrituras que revientan con el cuerpo vacío:\n  "
        + "\n  ".join(rotas)
        + "\n\nCon `{}` lo correcto es un 422 diciendo qué falta, o hacer el "
        "trabajo si la ruta no lleva cuerpo. Un 500 no dice nada y puede haber "
        "dejado datos a medias."
    )


@pytest.mark.parametrize("servicio", SERVICIOS)
def test_ningun_listado_revienta_al_abrirlo(servicio: str, db: Any, tenant_id: UUID) -> None:
    from crmcore.config import limpiar_cache_settings
    from fastapi.testclient import TestClient

    os.environ["SERVICE_NAME"] = servicio
    limpiar_cache_settings()
    modulo = importlib.import_module(f"services.{servicio}.main")
    app = modulo.app

    cliente = TestClient(app, raise_server_exceptions=False)
    cabeceras = _cabeceras(tenant_id)
    rotas: list[str] = []
    for camino in _listados_de(app):
        respuesta = cliente.get(camino, headers=cabeceras)
        if respuesta.status_code >= 500:
            detalle = ""
            try:
                detalle = str(respuesta.json())[:160]
            except Exception:  # noqa: BLE001
                detalle = respuesta.text[:160]
            rotas.append(f"{respuesta.status_code} GET {camino} → {detalle}")

    assert not rotas, (
        f"En «{servicio}» hay listados que revientan al abrirlos:\n  "
        + "\n  ".join(rotas)
        + "\n\nUn 500 al abrir una pantalla es una pantalla en blanco. Si la ruta "
        "no puede contestar sin datos, que conteste vacío."
    )


# ── La recogida de Postgres abandonados ───────────────────────────────────


def test_solo_se_recoge_lo_que_de_verdad_esta_abandonado() -> None:
    """Dos condiciones, y las dos hacen falta.

    El 28-09-2026 había ONCE servidores de pruebas sueltos, el más viejo de casi
    catorce horas y 849 MB entre todos. El `cleanup()` del fixture no se ejecuta
    cuando la tanda muere de mala manera —un `SIGKILL` no admite manejador— así
    que se limpia al arrancar la siguiente.

    Lo que no puede pasar es que la limpieza le mate el servidor a una sesión
    que esté corriendo AHORA: de ahí la segunda condición. Se prueba la decisión
    y no el efecto, porque un huérfano de verdad no se puede fabricar: en cuanto
    termina quien lo creó, `pgserver` lo para.
    """
    from tests.conftest import esta_abandonado  # type: ignore[import-not-found]

    # Huérfano y viejo: se recoge.
    assert esta_abandonado("1", "13:50:15") is True
    assert esta_abandonado("1", "2-03:00:00") is True
    # Huérfano pero recién arrancado: es de una tanda que está corriendo.
    assert esta_abandonado("1", "00:42") is False
    assert esta_abandonado("1", "00:15:30") is False
    # Viejo pero CON padre: alguien lo tiene cogido.
    assert esta_abandonado("4821", "13:50:15") is False


def test_el_postgres_de_desarrollo_no_se_recoge() -> None:
    """`var/pgdata` es persistente A PROPÓSITO y no es de ninguna tanda.

    Lo levanta `scripts/postgres_local.py` para `setup.sh`: es el Postgres con
    el que se desarrolla, vive fuera de cualquier prueba y lleva horas
    encendido por definición. La primera versión de esta recogida lo daba por
    abandonado —era de este repositorio, huérfano y viejo, las tres cosas— y lo
    habría parado en mitad del trabajo de alguien.

    Se distingue por el prefijo del directorio: los de pruebas nacen en un
    temporal `contecrm-test-…` y éste no.
    """
    import inspect

    from tests import conftest
    from tests.conftest import _recoger_servidores_abandonados  # noqa: F401  (existe)

    fuente = inspect.getsource(conftest._recoger_servidores_abandonados)
    assert "contecrm-test-" in fuente, (
        "la recogida ya no filtra por el prefijo de los directorios de pruebas: "
        "sin eso para también el Postgres de desarrollo"
    )
