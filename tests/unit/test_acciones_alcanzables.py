"""Lo que la API deja hacer con un registro, se puede hacer desde el front.

Un CRM no son listados: son **acciones sobre registros**. Convertir un lead,
moverlo de etapa, escalar un caso, reabrirlo, fusionar duplicados. La API
publica más de doscientas y el front no ofrecía **ninguna**: se podía listar y
crear, y nada más. Con eso no se cierra un ciclo de trabajo, solo se mira.

Escribir un botón por acción habría garantizado que la mitad no se escribiera
nunca y que la otra mitad se quedara desfasada, así que la ficha las saca del
contrato: `crmcore` publica la superficie con el permiso de cada operación y el
OpenAPI dice qué campos pide cada una.

Este gate comprueba **que el mecanismo las alcanza**: recorre las acciones que
publica cada servicio sobre un registro y verifica que encajan en la forma que
la ficha sabe resolver —un solo parámetro, colgando de la colección—. Una acción
que no encaje no saldría en ninguna pantalla, y nadie se enteraría.
"""

from __future__ import annotations

import importlib
import os
import re

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

PARAMETRO = re.compile(r"\{[^}]+\}")


@pytest.fixture(autouse=True)
def _devolver_el_servicio():
    """Deja `SERVICE_NAME` como estaba, para no contaminar el resto de la suite."""
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


def _contrato(servicio: str) -> dict:
    """Los caminos que publica ese servicio.

    Por el ayudante compartido, que lo construye **una vez por proceso**. Antes
    se construía aquí y sin caché: esta función se llama una vez por servicio
    en la parametrización y otras catorce en el recuento de abajo, así que el
    gate generaba veintiocho contratos para mirar catorce. Medido: 16,5 s de un
    presupuesto de 200 s para el nivel «push» entero.
    """
    from tests.unit._contratos import caminos

    return dict(caminos(servicio))


def _acciones(paths: dict) -> list[str]:
    """`POST /api/v1/<coleccion>/{id}/<accion>`, que es lo que la ficha resuelve."""
    return [
        camino
        for camino, ops in paths.items()
        if "post" in ops
        and camino.startswith("/api/v1/")
        and len(PARAMETRO.findall(camino)) == 1
        and len(camino.split("/")) == 6
        and camino.split("/")[4].startswith("{")
    ]


@pytest.mark.parametrize("servicio", SERVICIOS)
def test_las_acciones_de_un_registro_las_alcanza_la_ficha(servicio: str) -> None:
    paths = _contrato(servicio)
    acciones = _acciones(paths)

    # Cada acción tiene que colgar de una colección que exista y se pueda leer:
    # si la colección no tiene listado, a su ficha no se llega, y a la acción
    # tampoco.
    huerfanas: list[str] = []
    for camino in acciones:
        coleccion = "/".join(camino.split("/")[:4])
        ops = paths.get(coleccion) or {}
        if "get" not in ops:
            huerfanas.append(f"{camino} (su colección {coleccion} no se puede listar)")

    assert not huerfanas, (
        f"En «{servicio}» hay acciones a las que no se llega desde ninguna ficha:\n  "
        + "\n  ".join(huerfanas)
    )


def test_hay_acciones_de_verdad_y_el_gate_las_ve() -> None:
    """Un gate que no ve nada pasa siempre.

    Ha pasado ya dos veces en este repositorio —comprobaciones escritas sobre
    `app.routes`, que en esta versión de FastAPI devuelve envoltorios—, así que
    aquí se fija un suelo: si el recuento cae a cero, lo que se ha roto es la
    comprobación, no el sistema.
    """
    total = sum(len(_acciones(_contrato(s))) for s in SERVICIOS)
    # 144 medidas al escribir esto. El suelo va por debajo para que quitar una
    # acción a propósito no rompa el gate, pero lo bastante cerca para que
    # una comprobación que deja de ver el sistema sí lo rompa.
    assert total > 120, f"solo se ven {total} acciones sobre registros; el gate no está mirando"


# Cuerpos deliberadamente abiertos: no describen un formulario, sino un dato
# que viene de fuera y cuya forma no la decide este sistema. Van con nombre y
# motivo, y no como regla general, porque la excusa «esto es libre» es
# exactamente la que deja sin formulario a media aplicación.
ABIERTOS = {
    # Protocolo SCIM: la forma la fija el RFC y la manda un proveedor de
    # identidad, no una persona rellenando una pantalla.
    ("identity", "post", "/api/v1/scim/v2/Users"),
    ("identity", "put", "/api/v1/scim/v2/Users/{usuario_id}"),
    ("identity", "patch", "/api/v1/scim/v2/Users/{usuario_id}"),
    ("identity", "patch", "/api/v1/scim/v2/Groups/{grupo_id}"),
    # Un registro hipotético de cualquier objeto, para preguntar «¿quién vería
    # esto?». No hay un esquema: el objeto lo elige quien pregunta.
    ("identity", "post", "/api/v1/sharing-rules/explicar"),
    ("sales", "post", "/api/v1/territorios/resolver"),
    ("sales", "post", "/api/v1/lead-routing/reglas/probar"),
    # Las variables con las que se evalúa una tabla son las que esa tabla
    # declara: el esquema está en la tabla, no en el endpoint.
    ("orchestrator", "post", "/api/v1/tablas-decision/{clave}/evaluar"),
    # Cargas de sistemas de terceros y simulaciones sobre ellas.
    ("integration", "post", "/api/v1/modelo-canonico/traducir"),
    # Y su vuelta: un registro en el idioma común, cuyos campos los declara el
    # objeto canónico del tenant y no este endpoint. Por el mismo motivo que la
    # de entrada, y con el mismo cuidado: la excusa «esto es libre» es la que
    # deja sin formulario a media aplicación, así que va nombrada una a una.
    ("integration", "post", "/api/v1/modelo-canonico/traducir-salida"),
    ("integration", "post", "/api/v1/proveedores-servicio/simular"),
    ("integration", "post", "/api/v1/firma/simular"),
    # Importación: filas tal cual vienen del fichero.
    ("party", "post", "/api/v1/party-admin/importar/cuentas"),
}


@pytest.mark.parametrize("servicio", SERVICIOS)
def test_lo_que_pide_datos_dice_cuales(servicio: str) -> None:
    """Una operación con cuerpo sin esquema se pinta como un formulario vacío.

    No falla ni avisa: la pantalla abre, no hay dónde escribir y al enviar
    contesta que falta un campo que nunca ofreció. Pasaba en cinco sitios —el
    estado de una versión de proceso, la tabla de decisión que edita negocio,
    los tipos de registro, el renombrado de campos y la edición de una regla de
    enrutado— y en todos el alta sí tenía esquema, así que se podía crear algo
    que después no había forma de cambiar.
    """
    os.environ["SERVICE_NAME"] = servicio
    from crmcore.config import limpiar_cache_settings

    limpiar_cache_settings()
    doc = importlib.import_module(f"services.{servicio}.main").app.openapi()
    esquemas = (doc.get("components") or {}).get("schemas") or {}

    ciegas: list[str] = []
    for camino, ops in (doc.get("paths") or {}).items():
        for metodo, op in ops.items():
            if metodo not in ("post", "put", "patch"):
                continue
            cuerpo = (
                ((op.get("requestBody") or {}).get("content") or {})
                .get("application/json", {})
                .get("schema")
            )
            if cuerpo is None or (servicio, metodo, camino) in ABIERTOS:
                continue
            if "$ref" in cuerpo:
                cuerpo = esquemas.get(cuerpo["$ref"].split("/")[-1], {})
            if not cuerpo.get("properties"):
                ciegas.append(f"{metodo.upper()} {camino}")

    assert not ciegas, (
        f"En «{servicio}» hay operaciones que piden datos sin decir cuáles, "
        f"así que su formulario sale vacío:\n  " + "\n  ".join(ciegas)
    )


# Acciones que sí piden algo por query, con motivo. La lista es corta a
# propósito: es la excusa con la que se colaban catorce.
POR_QUERY = {
    # Vuelta del proveedor de identidad. El IdP construye la URL con lo que se
    # le dijo al mandarlo: no hay ninguna pantalla que rellene esto.
    ("identity", "post", "/api/v1/sso/saml/acs"),
}


@pytest.mark.parametrize("servicio", SERVICIOS)
def test_lo_que_pide_datos_los_pide_por_el_cuerpo(servicio: str) -> None:
    """Una acción que exige un dato por query no tiene formulario.

    El formulario de cada acción se genera del `requestBody` del contrato. Un
    parámetro de query no está ahí, así que la pantalla abría **sin un solo
    campo** y al enviar contestaba que faltaba el motivo que nunca pidió.
    Pasaba en catorce acciones: pausar una orden, rechazar una devolución,
    purgar la papelera, traspasar la cartera de quien se va.

    Hay una segunda razón para el cuerpo, y vale por sí sola: un motivo escrito
    por una persona puede llevar nombres dentro, y una URL queda en el log de
    acceso del servidor y en el historial del navegador.
    """
    os.environ["SERVICE_NAME"] = servicio
    from crmcore.config import limpiar_cache_settings

    limpiar_cache_settings()
    doc = importlib.import_module(f"services.{servicio}.main").app.openapi()

    sin_formulario: list[str] = []
    for camino, ops in (doc.get("paths") or {}).items():
        for metodo, op in ops.items():
            if metodo not in ("post", "put", "patch") or op.get("requestBody"):
                continue
            if (servicio, metodo, camino) in POR_QUERY:
                continue
            exigidos = [
                p["name"]
                for p in op.get("parameters") or []
                if p.get("in") == "query" and p.get("required") and p.get("name") != "authorization"
            ]
            if exigidos:
                sin_formulario.append(f"{metodo.upper()} {camino} pide {exigidos} por query")

    assert not sin_formulario, (
        f"En «{servicio}» hay acciones que exigen datos por query: su formulario "
        f"sale vacío y el dato acaba en la URL:\n  " + "\n  ".join(sin_formulario)
    )
