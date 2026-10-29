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


def _cliente(nombre: str, **entorno: str) -> Any:
    import importlib
    import os

    from crmcore.config import get_settings
    from starlette.testclient import TestClient

    claves = ("OUTBOX_ENABLED", "TAREAS_FONDO_ENABLED", *entorno)
    previo = {k: os.environ.get(k) for k in claves}
    os.environ["OUTBOX_ENABLED"] = "false"
    os.environ["TAREAS_FONDO_ENABLED"] = "false"
    os.environ.update(entorno)
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
    # Con OIDC encendido: en esta instalación viene apagado —`OIDC_ENABLED`— y
    # el servidor rechaza declarar un proveedor con «no está activo en esta
    # instalación», que es lo correcto y no es lo que se está probando aquí.
    yield from _cliente("identity", OIDC_ENABLED="true")


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


def test_el_gobierno_del_sso_se_devuelve_y_no_solo_se_guarda(
    identidad: Any, db: Any, tenant_id: UUID
) -> None:
    """Cinco ajustes del SSO se escribían y **no los devolvía nadie**.

    El listado daba el nombre, el tipo y los NOMBRES de las claves de
    configuración, así que `forzar_sso` se veía como una palabra en una lista y
    nunca su valor. Lo que eso deja sin poder revisar es lo que más importa:

    - si se aceptan aserciones que empiezan en el IdP (CRM-00.05.01.11), que
      sin `InResponseTo` se pueden **reenviar** y por eso vienen apagadas;
    - si el segundo factor se delega al proveedor (CRM-00.05.01.24), o sea si
      aquí ya no se pide;
    - y si entrar por contraseña está cortado y **quiénes** se lo saltan
      (CRM-00.05.01.13), que la capacidad exige que sean nominales y queden
      escritas. Una excepción que no se ve deja de ser una excepción.
    """
    cabeceras = _cabeceras(tenant_id)
    alta = identidad.post(
        "/api/v1/proveedores-identidad",
        headers=cabeceras,
        json={
            "nombre": "idp-de-prueba",
            # OIDC y no SAML: SAML es opcional en esta instalación —`xmlsec`
            # obliga a compilar— y el servidor lo dice con esas palabras. Lo
            # que se prueba aquí es el gobierno del SSO, que es el mismo para
            # los dos protocolos.
            "tipo": "oidc",
            "dominio_email": "ejemplo.test",
            "jit_provisioning": True,
            # La configuración va COMPLETA porque el alta la exige, y hace
            # bien: un proveedor a medias se guarda y falla el día que alguien
            # intenta entrar. El servidor dice cuáles faltan.
            "config": {
                "issuer_url": "https://idp.ejemplo.test",
                "client_id": "cliente-de-prueba",
                "redirect_uri": "https://crm.ejemplo.test/sso/callback",
                "forzar_sso": True,
                "cuentas_de_rescate": ["rescate@ejemplo.test"],
            },
        },
    )
    assert alta.status_code in (200, 201), alta.text
    proveedor_id = alta.json()["id"]

    editar = identidad.patch(
        f"/api/v1/proveedores-identidad/{proveedor_id}",
        headers=cabeceras,
        json={
            "permite_idp_initiated": True,
            "acr_con_mfa": ["urn:mace:incommon:iap:silver"],
            "dominios": ["ejemplo.test", "otra.test"],
        },
    )
    assert editar.status_code == 200, editar.text

    r = identidad.get("/api/v1/proveedores-identidad", headers=cabeceras)
    assert r.status_code == 200, r.text
    fila = next(f for f in r.json()["items"] if f["nombre"] == "idp-de-prueba")
    assert fila["permite_idp_initiated"] is True
    assert fila["acr_con_mfa"] == ["urn:mace:incommon:iap:silver"]
    assert fila["dominios"] == ["ejemplo.test", "otra.test"]
    assert fila["forzar_sso"] is True
    # Los correos, no el recuento: «2 cuentas de rescate» no se puede revisar.
    assert fila["cuentas_de_rescate"] == ["rescate@ejemplo.test"]
    # Y lo que NO sale sigue sin salir: la configuración lleva secretos dentro.
    assert "config" not in fila


def test_las_cuentas_sin_contacto_se_piden_por_la_ruta(
    personas: Any, db: Any, tenant_id: UUID
) -> None:
    """La pregunta que el producto ponía de ejemplo y no sabía contestar.

    La pantalla de Nexus sugiere literalmente «qué cuentas llevan más de dos
    meses sin contacto». No había forma: la última actividad es un campo
    **calculado** —el máximo de las actividades de la cuenta— y los filtros del
    listado sólo admiten columnas, así que ni se podía filtrar ni ordenar por
    él. Se descubrió preguntándoselo al asistente, que contestó —con razón— que
    no podía.

    Lo que se fija aquí es lo que hace útil la respuesta:

      * **las que no tienen NINGUNA actividad entran**, y son las que más
        importan: dejarlas fuera por no tener fecha las esconde justo en el
        listado que existe para encontrarlas;
      * las que la tienen reciente **no** entran;
      * y la ruta no la tapa la de la ficha, que tiene la misma forma
        —`/accounts/{id}`— y la convertiría en un 422 por un UUID mal formado.
    """
    from datetime import timedelta

    from crmcore.fechas import ahora_utc

    from services.party.modelos import Actividad, Cuenta

    callada = Cuenta(tenant_id=tenant_id, nombre="Callada SL", clave_canonica="callada")
    hablada = Cuenta(tenant_id=tenant_id, nombre="Hablada SL", clave_canonica="hablada")
    muda = Cuenta(tenant_id=tenant_id, nombre="Muda SL", clave_canonica="muda")
    db.add_all([callada, hablada, muda])
    db.flush()
    db.add_all(
        [
            Actividad(
                tenant_id=tenant_id,
                tipo="llamada",
                asunto="hace mucho",
                cuenta_id=callada.id,
                created_at=ahora_utc() - timedelta(days=200),
            ),
            Actividad(
                tenant_id=tenant_id,
                tipo="llamada",
                asunto="ayer",
                cuenta_id=hablada.id,
                created_at=ahora_utc() - timedelta(days=1),
            ),
        ]
    )
    db.flush()

    r = personas.get("/api/v1/accounts/sin-contacto?dias=60", headers=_cabeceras(tenant_id))
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    # Es el LISTADO y no la ficha: si la ruta de `/{cuenta_id}` la tapara,
    # «sin-contacto» se leería como un identificador y esto sería un 422.
    assert "items" in cuerpo
    # **Por identificador y no por nombre.** Esta petición no declara rol, así
    # que la política de sensibilidad tapa el nombre —«···a SL»— y además lo
    # tapa igual para «Callada SL» y «Hablada SL», que tienen las mismas
    # letras: afirmar sobre el nombre haría pasar la prueba con la cuenta
    # equivocada. El identificador es estructural y nunca se enmascara.
    ids = {f["id"] for f in cuerpo["items"]}
    assert str(callada.id) in ids, "una de hace 200 días tiene que salir"
    assert str(muda.id) in ids, "la que no ha tenido NINGUNA actividad es la que más importa"
    assert str(hablada.id) not in ids, "una de ayer no lleva dos meses sin contacto"


def test_el_ajuste_que_fuerza_el_sso_se_lee_con_su_valor(
    tenants: Any, db: Any, tenant_id: UUID
) -> None:
    """La pantalla lo necesita porque el forzado va por DOS sitios.

    El del tenant y el de cada proveedor. Mirar sólo el del proveedor da por
    abierta una puerta que está cerrada, y al revés — así que la pantalla
    enseña los dos y éste sale de aquí.

    Y con su valor, no sólo su nombre: un ajuste que se lista y no se lee no
    contesta «¿está forzado?», que es la única pregunta que se hace.
    """
    # Lo sirve `tenancy`, no `identity`: los ajustes del tenant viven con el
    # tenant. Pedirlo al cliente equivocado da 404, que es lo que pasó al
    # escribir esto.
    r = tenants.get("/api/v1/ajustes", headers=_cabeceras(tenant_id))
    assert r.status_code == 200, r.text
    ajuste = r.json()["sso_forzado"]
    assert isinstance(ajuste["valor"], bool)
    # Y de dónde sale, porque no es lo mismo que lo imponga el despliegue a
    # que lo haya decidido el cliente.
    assert ajuste["origen"]
    assert ajuste["descripcion"]


def test_una_sesion_dice_si_al_salir_se_cerrara_tambien_en_el_proveedor(
    identidad: Any, db: Any, tenant_id: UUID
) -> None:
    """Salir aquí y dejar viva la del proveedor es no haber salido
    (CRM-00.05.01.12).

    La correspondencia entre una sesión de aquí y la del IdP se guarda —es la
    que hace que el aviso de cierre sepa a quién aplicarse— y **no la devolvía
    nadie**. Sin ella no hay forma de saber que volver a entrar no va a pedir
    credenciales.

    Que no esté enlazada no es un fallo de aquí: hay proveedores que no mandan
    índice de sesión. Es una carencia que hay que poder ver, y el propio código
    ya la anotaba en la auditoría sin que nadie pudiera consultarla.
    """
    r = identidad.get("/api/v1/sesiones", headers=_cabeceras(tenant_id))
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    # El campo está siempre, no sólo cuando hay enlace: un campo que aparece y
    # desaparece se lee como «no se sabe» en los dos casos.
    for fila in items:
        assert "enlazada_al_idp" in fila
        assert isinstance(fila["enlazada_al_idp"], bool)


def test_lo_que_el_perfil_declara_se_pide_por_la_ruta(
    integracion: Any, db: Any, tenant_id: UUID
) -> None:
    """El perfil de suite es configuración, no código (CRM-06.01.03.01).

    La pantalla enseña recurso a recurso **en qué sentido va** —leer o leer y
    escribir sobre el calendario de alguien no es lo mismo—, **con qué
    incremento se reanuda** (CRM-06.01.03.04) y **si trae datos de terceros**,
    con el aviso que escribe el propio servidor. Pidiéndolo por la ruta: el día
    que deje de mandar `incremento` o el aviso, la pantalla se queda sin la
    parte que la hacía revisable y no da ningún error.
    """
    # Por la puerta, como lo hace la pantalla: si mañana el alta exige un campo
    # más, esto se entera. Llamando a la función por dentro, no.
    alta = integracion.post(
        "/api/v1/suites/perfiles",
        headers=_cabeceras(tenant_id),
        json={
            "nombre": "suite-de-prueba",
            "sistema": "m365",
            # El perfil va COMPLETO porque el alta lo exige, y hace bien: sin
            # la correspondencia de campos «el dato llegaría y no se sabría
            # dónde ponerlo», y sin `token_url` no se puede autorizar a nadie.
            # Lo dijo el propio servidor al rechazar el primer intento.
            "config": {
                "clase": "suite_productividad",
                "base_url": "https://ejemplo.test",
                "token_url": "https://ejemplo.test/oauth2/token",
                "alcances": {
                    "base": "offline_access",
                    "calendario.leer": "Calendars.Read",
                    "calendario.escribir": "Calendars.ReadWrite",
                },
                "recursos": {
                    "calendario": {
                        "endpoint": "/me/events",
                        "campos": {"asunto": "subject", "inicio": "start.dateTime"},
                        "sentidos": ["leer", "escribir"],
                        "incremento": "token_delta",
                    },
                },
            },
        },
    )
    assert alta.status_code in (200, 201), alta.text

    r = integracion.get(
        "/api/v1/suites/perfiles/suite-de-prueba/capacidades",
        headers=_cabeceras(tenant_id),
    )
    assert r.status_code == 200, r.text
    datos = r.json()
    cal = next(d for d in datos["detalle"] if d["recurso"] == "calendario")
    assert cal["sentidos"] == ["leer", "escribir"]
    # El incremento: sin verlo nadie sabe si una sincronización que tarda está
    # avanzando o repitiéndose.
    assert cal["incremento"] == "token_delta"
    # Y el aviso de datos de terceros, con sus palabras: una agenda personal
    # tiene al médico y a la familia.
    assert cal["trae_dato_de_terceros"] is True
    assert cal["aviso"]


def test_que_entra_de_verdad_se_pide_por_la_ruta(integracion: Any, tenant_id: UUID) -> None:
    """Qué entra junta la política de la empresa y la preferencia de la persona
    (CRM-06.01.03.14), y lo marcado como privado no entra nunca.

    Lo que la pantalla enseña es `criterio`, `nunca_entra` y el porqué. Si el
    servidor dejara de mandar `nunca_entra`, el recuadro diría qué entra y
    callaría qué no, que es justo la mitad que alguien revisa.
    """
    r = integracion.post("/api/v1/suites/reglas", headers=_cabeceras(tenant_id), json={})
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["criterio"]
    assert "marcado_privado" in datos["nunca_entra"]
    assert datos["porque"]


def test_antes_de_sincronizar_se_pide_por_la_ruta(
    integracion: Any, db: Any, tenant_id: UUID
) -> None:
    """La comprobación que va antes de cada vuelta (CRM-06.01.03.15).

    Dos cosas que se midieron al escribir la pantalla, y las dos cambiaron cómo
    quedó:

    **El servidor exige usuario, perfil y recurso.** La pantalla la pregunta
    desde cada consentimiento, porque los tres están en esa fila; un formulario
    suelto los pedía a mano y contestaba 422.

    **Y sin consentimiento contesta 403, no un 200 diciendo que no.** La
    pantalla tiene que enseñar ese mensaje —«nadie ha autorizado leer correo de
    esta persona»— en vez de quedarse en blanco: es exactamente lo que hay que
    hacer, y un recuadro vacío lo esconde.
    """
    r = integracion.post(
        "/api/v1/suites/antes-de-sincronizar",
        headers=_cabeceras(tenant_id),
        json={"usuario_id": str(uuid4()), "perfil": "no-declarado", "recurso": "correo"},
    )
    assert r.status_code == 403, r.text
    datos = r.json()
    assert datos["error_code"] == "suite.sin_consentimiento"
    # Con el porqué en palabras: «no se puede» a secas manda a revisar la red
    # cuando lo que falta es que alguien autorice.
    assert "autoriz" in datos["detail"]


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
