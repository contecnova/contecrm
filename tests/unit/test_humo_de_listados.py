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
from pathlib import Path
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


# Cuánto barre cada servicio, medido el 28-09-2026: (escrituras, listados).
#
# EL TOTAL, AL LADO DEL SUELO. Sin eso un número de cobertura no dice nada: la
# prueba de fugas entre tenants publicaba cuántas rutas probaba y **nadie tenía
# el total real enfrente**, así que parecía razonable mientras se dejaba 709 de
# 1.878 sin mirar. Y se cuenta **del producto** —las aplicaciones tal como se
# despliegan—, no de una lista escrita a mano, que es la otra mitad del error.
#
# Margen del 10 % hacia abajo: retirar una ruta a propósito no rompe el gate, y
# que un filtro deje de encontrar la mitad, sí.
BARRIDO_ESPERADO = {
    "tenancy": (24, 40),
    "identity": (38, 42),
    "metadata": (10, 20),
    "orchestrator": (13, 17),
    "automation": (4, 12),
    "integration": (56, 44),
    "eventing": (4, 16),
    "party": (32, 43),
    "sales": (64, 67),
    "analytics": (29, 30),
    "intelligence": (40, 28),
    "service": (39, 54),
    "marketing": (42, 37),
}


def _suelo(servicio: str, cual: int) -> int:
    return int(BARRIDO_ESPERADO[servicio][cual] * 0.9)


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

    # BARRER CERO NO ES ESTAR EN VERDE. Si el filtro dejara de encontrar rutas
    # —porque cambie el prefijo, porque el servicio mueva sus routers o porque
    # este ayudante se rompa—, la lista de rotas saldría vacía y esto pasaría sin
    # haber mirado nada. Es exactamente el defecto que tenía la prueba de fugas
    # entre tenants, donde costó 709 rutas sin comprobar.
    cuantas = len(_escrituras_de(app))
    assert cuantas >= _suelo(servicio, 0), (
        f"El barrido solo ve {cuantas} escrituras a colección en «{servicio}»; "
        f"había {BARRIDO_ESPERADO[servicio][0]}. O el servicio ha cambiado de "
        "forma o este barrido ha dejado de encontrarlas: las dos cosas hay que "
        "mirarlas. Si la bajada es a propósito, ajusta el número en el mismo "
        "commit y di por qué."
    )
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

    cuantos = len(_listados_de(app))
    assert cuantos >= _suelo(servicio, 1), (
        f"El barrido solo ve {cuantos} listados en «{servicio}»; había "
        f"{BARRIDO_ESPERADO[servicio][1]}. O ha cambiado de forma o este barrido "
        "ha dejado de encontrarlos."
    )
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


# ── Que nadie se olvide de la marca ───────────────────────────────────────
#
# Una prueba de aislamiento SIN la marca `despliegue` cae al nivel de bloque y
# **no falla nada**: sigue corriendo, sigue en verde, y simplemente deja de
# proteger el push. Es el peor tipo de agujero —el que no se nota— y hasta
# ahora dependía de que quien la escribiera se acordara.
#
# La señal de que una prueba comprueba aislamiento es que use `otro_tenant_id`:
# el fixture existe para una sola cosa, preguntar como un tenant por lo de otro.
# Así que toda prueba que lo use tiene que haber DECIDIDO a qué nivel va, y esta
# comprobación no decide por ella: la obliga a decidir.

# Las que comprueban aislamiento DE SU DOMINIO y pueden esperar al bloque. El
# motivo es común y por eso se escribe una vez: el fuzzing recorre **todas** las
# rutas de los trece servicios con un identificador ajeno y está en el push, así
# que la red ancha ya la cubre; éstas comprueban el detalle de su área.
#
# Si una de estas empieza a proteger algo que no puede esperar, se le pone la
# marca y se quita de aquí. Y si aparece un fichero nuevo con `otro_tenant_id`
# que no esté ni marcado ni aquí, esta prueba lo dice.
AISLAMIENTO_DE_DOMINIO = {
    "test_adjuntos_y_notificaciones.py",
    # Las cuatro de los bloques de auditoría del catálogo (26-10-2026). Las tres
    # primeras comprueban aislamiento **de paso**: lo suyo es la jerarquía de
    # ajustes, el modelo extensible y el motor de reglas, y el caso genérico
    # —que un listado no deje ver lo de otro— ya lo barre el fuzzing en cada
    # push. La cuarta, `test_una_empresa_no_ve_a_otra.py`, es justo lo
    # contrario: su asunto ES el aislamiento, así que lleva la marca y corre en
    # cada push.
    "test_extender_el_modelo_sin_escribir_codigo.py",
    "test_la_automatizacion_no_se_muerde_la_cola.py",
    "test_la_configuracion_baja_por_la_jerarquia.py",
    "test_auditoria_cadena.py",
    "test_busqueda.py",
    "test_byok.py",
    "test_captura_leads.py",
    "test_casos_y_sla.py",
    "test_cumplimiento_y_slo.py",
    "test_documental.py",
    "test_forecast.py",
    "test_grc.py",
    "test_metamodelo.py",
    "test_proyeccion_campos.py",
    "test_relaciones_metadata.py",
    "test_retencion.py",
    "test_scim.py",
    "test_tablas_decision.py",
    "test_trabajos_y_masivo.py",
    "test_visibilidad_listados.py",
}


def test_toda_prueba_de_aislamiento_ha_decidido_a_que_nivel_va() -> None:
    """La red que le faltaba a la marca.

    Sin esto, quien escriba mañana una prueba de aislamiento y olvide
    `pytestmark = pytest.mark.despliegue` no se entera de nada: la prueba pasa,
    el push pasa, y lo único que ocurre es que deja de correr donde importa.
    Un olvido que no rompe nada es un olvido que nadie corrige.

    No decide por nadie: obliga a que la decisión esté escrita, en la marca o en
    la lista de las que pueden esperar.
    """
    raiz = Path(__file__).resolve().parent
    sin_decidir: list[str] = []
    sobran: list[str] = []

    for fichero in sorted(raiz.glob("test_*.py")):
        texto = fichero.read_text("utf-8")
        usa_otro_tenant = "otro_tenant_id" in texto
        tiene_marca = "mark.despliegue" in texto
        declarada = fichero.name in AISLAMIENTO_DE_DOMINIO

        if usa_otro_tenant and not tiene_marca and not declarada:
            sin_decidir.append(fichero.name)
        if declarada and not usa_otro_tenant:
            sobran.append(fichero.name)

    assert not sin_decidir, (
        "Estas pruebas comprueban aislamiento entre tenants y no han decidido a "
        "qué nivel van:\n  "
        + "\n  ".join(sin_decidir)
        + "\n\nO llevan `pytestmark = pytest.mark.despliegue` —y entonces corren en "
        "cada push— o se añaden a AISLAMIENTO_DE_DOMINIO, que significa que el "
        "fuzzing ya cubre su caso genérico y el detalle puede esperar al bloque. "
        "Lo que no vale es no decidirlo: el olvido no rompe nada y por eso no se "
        "corrige nunca."
    )
    assert not sobran, (
        f"{sobran} ya no comprueba aislamiento: quítalo de AISLAMIENTO_DE_DOMINIO. "
        "Una lista con entradas que sobran se deja de leer."
    )
