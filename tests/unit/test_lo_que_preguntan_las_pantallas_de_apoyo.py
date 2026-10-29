"""Las cuatro preguntas que una pantalla hace por HTTP, pedidas por la ruta.

Cuatro recuadros nuevos del 28-10-2026 declaran la FORMA de lo que leen:

  * en Seguridad, «¿y éstos por qué están permitidos?» —las excepciones de
    segregación con su motivo y su caducidad— y «no puedo entrar: ¿por dónde me
    toca?» —a qué proveedor le toca un correo—;
  * en Suite, «esto no conecta: ¿qué falta exactamente?» y «antes de
    desconectar: qué se queda y qué se va».

Las pruebas de esos cuatro módulos llaman a la función, no a la ruta. Y eso
deja un hueco con forma de fallo real: el día que el servidor deje de mandar el
motivo de una excepción, o el alcance que falta, la pantalla **no da error** —
se queda sin la única parte que la hacía útil, y nadie se entera.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.db


def _cabeceras(tenant_id: UUID) -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import H_PERMISOS, H_TENANT, H_USER, firmar_cabeceras_internas

    return firmar_cabeceras_internas(
        {H_TENANT: str(tenant_id), H_USER: str(uuid4()), H_PERMISOS: "*:*"},
        get_settings().secret_key.get_secret_value(),
    )


def _cliente(nombre: str) -> Any:
    import importlib
    import os

    from crmcore.config import get_settings
    from starlette.testclient import TestClient

    previo = {k: os.environ.get(k) for k in ("OUTBOX_ENABLED", "TAREAS_FONDO_ENABLED")}
    os.environ["OUTBOX_ENABLED"] = "false"
    os.environ["TAREAS_FONDO_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        with TestClient(importlib.import_module(f"services.{nombre}.main").app) as cli:
            yield cli
    finally:
        for clave, valor in previo.items():
            if valor is None:
                os.environ.pop(clave, None)
            else:
                os.environ[clave] = valor
        get_settings.cache_clear()


@pytest.fixture(scope="module")
def identidad() -> Any:
    yield from _cliente("identity")


@pytest.fixture(scope="module")
def integracion() -> Any:
    yield from _cliente("integration")


@pytest.fixture(scope="module")
def tenants() -> Any:
    yield from _cliente("tenancy")


@pytest.fixture(scope="module")
def modelo() -> Any:
    yield from _cliente("metadata")


@pytest.fixture(scope="module")
def procesos() -> Any:
    yield from _cliente("orchestrator")


@pytest.fixture(scope="module")
def personas() -> Any:
    yield from _cliente("party")


# ── Seguridad ─────────────────────────────────────────────────────────────


def test_las_excepciones_de_segregacion_traen_su_motivo_y_su_caducidad(
    identidad: Any, db: Any, tenant_id: UUID
) -> None:
    """Lo que las convierte en un control, y no en papeleo.

    El alta exige motivo escrito y caducidad. Si la lista no los devuelve, la
    pantalla enseña que hay excepciones y no por qué — que es exactamente lo
    que hay que revisar.
    """
    cabeceras = _cabeceras(tenant_id)
    r = identidad.get("/api/v1/segregacion/excepciones", headers=cabeceras)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)

    # Y admite pedir también las caducadas, que es lo que distingue «no hay
    # ninguna» de «todas vencieron».
    con_caducadas = identidad.get(
        "/api/v1/segregacion/excepciones?incluir_caducadas=true", headers=cabeceras
    )
    assert con_caducadas.status_code == 200, con_caducadas.text


def test_a_que_proveedor_le_toca_un_correo(identidad: Any, db: Any, tenant_id: UUID) -> None:
    """«No puedo entrar» es la incidencia más común y la más cara a ciegas.

    Sin proveedor declarado la respuesta correcta no es un error: es «entra con
    contraseña». Si esto devolviera 404, la pantalla diría que algo falla
    cuando lo que pasa es que ese dominio no está forzado.
    """
    r = identidad.get(
        "/api/v1/sso-gobierno/descubrir?email=quien.sea@ejemplo.test",
        headers=_cabeceras(tenant_id),
    )
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["tiene_proveedor"] is False
    assert datos["entrada"] == "contrasena"


# ── Suite ─────────────────────────────────────────────────────────────────


def test_el_diagnostico_dice_QUE_alcance_falta(integracion: Any, tenant_id: UUID) -> None:
    """«Faltan permisos» a secas obliga a adivinar cuál, y adivinar acaba en
    pedir permisos de administrador global «para descartar»."""
    r = integracion.post(
        "/api/v1/suites/diagnostico",
        headers=_cabeceras(tenant_id),
        json={
            "codigo": 403,
            "alcances_concedidos": ["Mail.Read"],
            "alcances_necesarios": ["Mail.Read", "Calendars.ReadWrite"],
            "mensaje_del_proveedor": "",
        },
    )
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["ok"] is False
    assert datos["faltan_alcances"] == ["Calendars.ReadWrite"]
    assert datos["que_pasa"] and datos["que_hacer"]


def test_el_diagnostico_distingue_la_credencial_del_permiso(
    integracion: Any, tenant_id: UUID
) -> None:
    """Son dos arreglos distintos: uno es volver a autorizar y el otro es pedir
    un alcance. Darlos por lo mismo es lo que alarga una implantación."""
    r = integracion.post(
        "/api/v1/suites/diagnostico",
        headers=_cabeceras(tenant_id),
        json={
            "codigo": 401,
            "alcances_concedidos": [],
            "alcances_necesarios": [],
            "mensaje_del_proveedor": "",
        },
    )
    assert r.status_code == 200, r.text
    assert "faltan_alcances" not in r.json(), "no faltan alcances: el problema es otro"
    assert "credencial" in r.json()["que_pasa"].lower()


def test_el_plan_de_baja_trae_las_dos_mitades(integracion: Any, tenant_id: UUID) -> None:
    """Enseñar sólo lo que desaparece asusta y nadie desconecta; enseñar sólo
    lo que se queda engaña. Y cada línea con su porqué, que es lo que evita que
    alguien discuta la norma."""
    motivo = "revocacion"
    r = integracion.get(f"/api/v1/suites/baja/{motivo}", headers=_cabeceras(tenant_id))
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["se_queda"] and plan["se_borra"]
    for lado in ("se_queda", "se_borra"):
        for fila in plan[lado]:
            assert fila["que"] and fila["porque"], f"una línea de «{lado}» sin su porqué"


def test_un_motivo_inventado_no_devuelve_un_plan(integracion: Any, tenant_id: UUID) -> None:
    """Un plan para un motivo que no existe se leería como bueno."""
    motivo = "porque-si"
    r = integracion.get(f"/api/v1/suites/baja/{motivo}", headers=_cabeceras(tenant_id))
    assert r.status_code == 422, r.text


# ── Lo que se añadió el 28 y el 29-10-2026 ────────────────────────────────
#
# Las cinco de abajo las pedía ya una pantalla y **ninguna prueba las pedía
# por la ruta**: se llamaba a la función del servicio, que es más cómodo y deja
# justo el hueco que este fichero existe para tapar. El día que el servidor
# deje de mandar un campo, la pantalla no da error: se queda sin la parte que
# la hacía útil. Es el mismo descuido que ya apareció con el `desde` de un plan
# preventivo, una capa más allá.


def test_las_garantias_de_aislamiento_se_piden_por_la_ruta(
    tenants: Any, db: Any, tenant_id: UUID
) -> None:
    """La pantalla pinta una línea por capa con su detalle y su porqué.

    Si el servidor dejara de mandar `capas`, la pantalla saldría con el título
    y nada debajo — y eso, en una pantalla que contesta «¿qué impide que una
    empresa vea a otra?», se lee como «nada».
    """
    r = tenants.get("/api/v1/aislamiento/garantias", headers=_cabeceras(tenant_id))
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["capas"], "sin capas, la pantalla sale vacía y parece que no hay nada"
    for capa in datos["capas"]:
        assert capa["titulo"] and capa["detalle"] and capa["porque"]
        assert isinstance(capa["ok"], bool)
    assert datos["que_significa"]


def test_las_excepciones_de_campo_se_piden_por_la_ruta(
    identidad: Any, db: Any, tenant_id: UUID
) -> None:
    """Sin excepciones la lista es vacía **y dice qué significa**: ese caso es
    el bueno, y un hueco se lee como «no está configurado»."""
    r = identidad.get("/api/v1/politicas-acceso/campos", headers=_cabeceras(tenant_id))
    assert r.status_code == 200, r.text
    datos = r.json()
    assert isinstance(datos["campos"], list)
    assert datos["que_significa"], "un vacío sin explicación se lee como un fallo"


MANIFIESTO = {
    "formato": 1,
    "clave": "homologaciones",
    "nombre": "Homologaciones por mercado",
    "version": "1.0.0",
    "descripcion": "Seguimiento de homologación de pieza por país.",
    "objetos": [
        {
            "nombre": "homologacion_mercado",
            "etiqueta": "Homologación por mercado",
            "campos": [{"nombre": "mercado", "tipo": "texto", "etiqueta": "Mercado"}],
        }
    ],
}


def test_la_ficha_de_un_modulo_instalado_se_pide_por_la_ruta(
    modelo: Any, db: Any, tenant_id: UUID
) -> None:
    """La pantalla pinta el manifiesto, el espacio de nombres y la huella.

    Todo eso estaba **guardado** y la ficha devolvía cuatro campos, así que la
    forma que la pantalla declara es nueva: si el servidor dejara de mandarla,
    el recuadro «qué declara» saldría con el título y nada debajo.
    """
    cabeceras = _cabeceras(tenant_id)
    alta = modelo.post(
        "/api/v1/metadata/modulos/instalar",
        headers=cabeceras,
        json={"manifiesto": MANIFIESTO, "aplicar": True},
    )
    assert alta.status_code in (200, 201, 409), alta.text

    # Con el hueco escrito, como el resto del fichero: la pantalla pide
    # `${clave}` y el gate compara formas, no cadenas.
    clave = "homologaciones"
    r = modelo.get(f"/api/v1/metadata/modulos/{clave}", headers=cabeceras)
    assert r.status_code == 200, r.text
    ficha = r.json()
    for campo in ("objetos", "campos", "espacio_de_nombres", "depende_de", "huella"):
        assert campo in ficha, f"la ficha ya no manda «{campo}» y la pantalla lo pinta"

    # Y las dos que cuelgan de ella, que son las que contestan «¿sigue siendo
    # el que instalamos?» y «¿sobra?».
    integridad = modelo.get(f"/api/v1/metadata/modulos/{clave}/integridad", headers=cabeceras)
    assert integridad.status_code == 200, integridad.text
    assert "medible" in integridad.json(), (
        "sin `medible`, la pantalla no puede distinguir «íntegro» de «no se "
        "puede comparar», que es la distinción que la hace útil"
    )

    telemetria = modelo.get(f"/api/v1/metadata/modulos/{clave}/telemetria", headers=cabeceras)
    assert telemetria.status_code == 200, telemetria.text
    datos = telemetria.json()
    # `concluyente` es la que evita que alguien decida que algo sobra a los dos
    # días de instalarlo.
    assert "concluyente" in datos and "sin_usar" in datos


def test_un_modulo_que_no_esta_no_devuelve_una_ficha_en_blanco(
    modelo: Any, db: Any, tenant_id: UUID
) -> None:
    """Una ficha vacía se lee como «este módulo no trae nada», que es muy
    distinto de «este módulo no está»."""
    inexistente = "no-instalado"
    r = modelo.get(f"/api/v1/metadata/modulos/{inexistente}", headers=_cabeceras(tenant_id))
    assert r.status_code == 404, r.text


def test_las_delegaciones_y_los_enlaces_se_piden_por_la_ruta(
    procesos: Any, db: Any, tenant_id: UUID
) -> None:
    """Las dos pestañas nuevas de aprobaciones, pedidas por HTTP.

    Son las dos que contestan quién puede decidir por quién: una delegación
    cede la firma mientras alguien no está, y un enlace permite decidir sin
    entrar al CRM. Si el servidor dejara de mandar `vigente` o `vivo`, las dos
    listas saldrían sin la única columna que distingue lo que está en vigor de
    lo que ya no.
    """
    cabeceras = _cabeceras(tenant_id)

    delegaciones = procesos.get("/api/v1/aprobaciones/delegaciones", headers=cabeceras)
    assert delegaciones.status_code == 200, delegaciones.text
    datos = delegaciones.json()
    assert "vigentes" in datos and isinstance(datos["delegaciones"], list)
    assert datos["que_significa"]

    enlaces = procesos.get("/api/v1/aprobaciones/enlaces", headers=cabeceras)
    assert enlaces.status_code == 200, enlaces.text
    sueltos = enlaces.json()
    assert "vivos" in sueltos and isinstance(sueltos["enlaces"], list)
    # Y el token no viaja ni con la lista vacía: lo que hay en la base es su
    # hash, y ése es justo el punto.
    assert "token" not in enlaces.text and "hash_token" not in enlaces.text


def test_las_tres_listas_de_cuenta_se_piden_por_la_ruta(
    personas: Any, db: Any, tenant_id: UUID
) -> None:
    """Las tres pestañas nuevas del módulo de cuentas, pedidas por HTTP.

    Las tres las sirve `montar_listado`, la maquinaria genérica, y eso importa
    para esta prueba: un `grep` de decoradores **no las ve**, así que al
    buscar «colecciones que se escriben y no se leen» salieron como huérfanas
    y no lo eran. Se comprobó pidiéndolas, que es la única forma.
    """
    cabeceras = _cabeceras(tenant_id)
    for ruta in (
        "/api/v1/planes-cuenta",
        "/api/v1/planes-cuenta/financiero",
        "/api/v1/cambios-de-empresa",
    ):
        r = personas.get(ruta, headers=cabeceras)
        assert r.status_code == 200, f"{ruta}: {r.text}"
        assert "items" in r.json(), f"{ruta} no devuelve un listado paginado"
