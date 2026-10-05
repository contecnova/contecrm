"""El partner puede entrar por su portal (`CRM-03.05.*`, portal de partner).

`POST /portal-partner/entrar` y `/canjear` contestaban **401 `auth.requerida`**.
A las dos se llega sin credencial —son donde el partner consigue la primera— y
las dos pedían la sesión con `UowDep`, que la abre con el tenant del principal.
La puerta pedía la llave que reparte, así que ningún partner podía entrar nunca.

Es la tercera vez que aparece la misma avería en este repositorio: le pasó a
`/auth/login`, que lo dejó escrito en su propio comentario, y a las tres rutas
de SSO. Por eso el que traduce el nombre de la organización a identificador
vive ahora en `crmcore.http.interno` y no en `identity`: dos implementaciones de
«¿de qué tenant es este nombre?» divergen siempre, y la que se queda atrás es la
puerta por la que se entra.

El tenant llega en el cuerpo y es una **pista sin firmar**. Lo que concede
acceso es otra cosa: tener un acceso activo con ese correo en ese tenant, o un
enlace de un solo uso que emitimos nosotros. Que la pista no baste se comprueba
abajo.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.db


@pytest.fixture
def api_sales(_esquema: str) -> Any:
    """El servicio tal como se despliega, con su arranque.

    Depende de `_esquema` porque es quien deja `DATABASE_URL` apuntando al
    Postgres de las pruebas: sin él la aplicación lo busca en `127.0.0.1:5432`,
    no lo encuentra, y todo falla por el motivo equivocado.
    """
    import importlib
    import os

    from crmcore.config import get_settings
    from starlette.testclient import TestClient

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        os.environ["SERVICE_NAME"] = "sales"
        app = importlib.import_module("services.sales.main").app
        with TestClient(app, raise_server_exceptions=False) as cliente:
            yield cliente
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


@pytest.fixture
def tenant_confirmado(_esquema: str) -> Any:
    """Un tenant cuyas filas se escriben de verdad y se borran al acabar.

    La aplicación abre su propia conexión, así que no vería nada escrito dentro
    de la transacción que el fixture `db` deshace al terminar. Y hay que
    limpiar: en la suite el rol es SUPERUSER, o sea que **no se aplica el
    aislamiento por tenant**, y una fila confirmada aquí la ve cualquier prueba
    posterior que consulte sin filtrar.
    """
    from crmcore.db.base import Base
    from crmcore.db.session import sesion

    tenant = uuid4()
    yield tenant

    # UNA TRANSACCIÓN POR TABLA: con todas en la misma, el primer
    # `UndefinedTable` —hay modelos compartidos que no existen en este esquema—
    # aborta la transacción entera y las demás ni se intentan, así que el
    # borrado parece hecho y no lo está.
    borradas = 0
    for tabla in reversed(Base.metadata.sorted_tables):
        if "tenant_id" not in tabla.c:
            continue
        try:
            with sesion(None, sistema=True) as db:
                borradas += db.execute(tabla.delete().where(tabla.c.tenant_id == tenant)).rowcount
        except Exception:  # noqa: BLE001 — tabla que no está en este esquema
            continue
    assert borradas, (
        "la limpieza no ha borrado ni una fila: o la prueba no escribió nada "
        "—y entonces no probaba lo que dice— o el borrado no está llegando"
    )


def _partner_con_acceso(tenant_id: UUID, email: str) -> None:
    """Un partner activo con un acceso, por la vía normal."""
    from crmcore.db.session import sesion
    from crmcore.db.uow import UnidadDeTrabajo
    from crmcore.tenancy.context import con_contexto

    from services.sales.partners import AccesoPartner, crear_partner

    with con_contexto(tenant_id=tenant_id, origen="prueba"), sesion(tenant_id) as db:
        # POR LA VÍA NORMAL y no montando la fila a mano: `Partner` exige
        # `clave`, y rellenar columnas a ojo choca con la primera restricción
        # que alguien añada. La primera versión de esto falló justo así.
        uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
        partner = crear_partner(uow, clave="acme", nombre="ACME Partners")
        # Nace en «alta», y `emitir_enlace` solo abre a los operativos: un
        # partner que todavía no está activo no entra, y tampoco se le dice por
        # qué. Aquí se quiere el caso bueno.
        partner.estado = "activo"
        db.flush()
        db.add(
            AccesoPartner(
                tenant_id=tenant_id,
                partner_id=partner.id,
                email=email,
                nombre="Ana",
                nivel="responsable",
                activo=True,
            )
        )


def test_pedir_el_enlace_no_exige_haber_entrado(api_sales: Any, tenant_confirmado: UUID) -> None:
    """La avería: la puerta contestaba «tienes que haber entrado».

    Se mira el **código de error** y no solo el número: desde que `get_uow`
    convierte «anónimo sin tenant» en 401, esta avería parece correcta desde
    fuera y un barrido que solo mire el estado no la ve.
    """
    _partner_con_acceso(tenant_confirmado, "ana@acme.com")

    salida = api_sales.post(
        "/api/v1/portal-partner/entrar",
        json={"tenant": str(tenant_confirmado), "email": "ana@acme.com"},
    )

    assert salida.status_code == 200, salida.text[:300]
    assert salida.json()["token"], "no ha emitido enlace para un acceso que existe"


def test_canjear_el_enlace_deja_entrar(api_sales: Any, tenant_confirmado: UUID) -> None:
    """El camino entero, que es lo que ninguna prueba recorría."""
    _partner_con_acceso(tenant_confirmado, "ana@acme.com")

    pedido = api_sales.post(
        "/api/v1/portal-partner/entrar",
        json={"tenant": str(tenant_confirmado), "email": "ana@acme.com"},
    )
    token = pedido.json()["token"]

    entrada = api_sales.post(
        "/api/v1/portal-partner/canjear",
        json={"tenant": str(tenant_confirmado), "token": token},
    )

    assert entrada.status_code == 200, entrada.text[:300]
    assert entrada.json()["nivel"] == "responsable"


def test_el_enlace_es_de_un_solo_uso(api_sales: Any, tenant_confirmado: UUID) -> None:
    """Quien lo capture —en un correo reenviado, en un registro— no entra
    detrás del que ya entró."""
    _partner_con_acceso(tenant_confirmado, "ana@acme.com")
    token = api_sales.post(
        "/api/v1/portal-partner/entrar",
        json={"tenant": str(tenant_confirmado), "email": "ana@acme.com"},
    ).json()["token"]

    cuerpo = {"tenant": str(tenant_confirmado), "token": token}
    assert api_sales.post("/api/v1/portal-partner/canjear", json=cuerpo).status_code == 200
    segunda = api_sales.post("/api/v1/portal-partner/canjear", json=cuerpo)

    assert segunda.status_code != 200, "el mismo enlace ha abierto dos sesiones"


def test_un_correo_desconocido_recibe_la_misma_respuesta(
    api_sales: Any, tenant_confirmado: UUID
) -> None:
    """Distinguirlo convertiría el portal en un comprobador de qué empresas son
    partners nuestros, que es media lista de la competencia."""
    _partner_con_acceso(tenant_confirmado, "ana@acme.com")

    conocido = api_sales.post(
        "/api/v1/portal-partner/entrar",
        json={"tenant": str(tenant_confirmado), "email": "ana@acme.com"},
    )
    desconocido = api_sales.post(
        "/api/v1/portal-partner/entrar",
        json={"tenant": str(tenant_confirmado), "email": "nadie@ningunsitio.com"},
    )

    assert conocido.status_code == desconocido.status_code == 200
    assert set(conocido.json()) == set(desconocido.json()), (
        "las dos respuestas no tienen la misma forma: la diferencia dice si ese "
        "correo es partner nuestro"
    )
    assert desconocido.json()["token"] is None


def test_el_tenant_del_cuerpo_no_da_acceso_por_si_solo(
    api_sales: Any, tenant_confirmado: UUID
) -> None:
    """La pista es una pista.

    Nombrar el tenant de otro no abre nada: lo que concede acceso es tener allí
    un acceso activo con ese correo.
    """
    _partner_con_acceso(tenant_confirmado, "ana@acme.com")

    salida = api_sales.post(
        "/api/v1/portal-partner/entrar",
        json={"tenant": str(uuid4()), "email": "ana@acme.com"},
    )

    assert salida.status_code == 200
    assert salida.json()["token"] is None, (
        "ha emitido un enlace nombrando el tenant de otro: el acceso de ana no " "es de ese tenant"
    )


def test_el_enlace_de_un_tenant_no_se_canjea_en_otro(
    api_sales: Any, tenant_confirmado: UUID
) -> None:
    """Un enlace válido no puede valer en otra organización: sería entrar en el
    portal de otro cliente con un correo propio."""
    _partner_con_acceso(tenant_confirmado, "ana@acme.com")
    token = api_sales.post(
        "/api/v1/portal-partner/entrar",
        json={"tenant": str(tenant_confirmado), "email": "ana@acme.com"},
    ).json()["token"]

    salida = api_sales.post(
        "/api/v1/portal-partner/canjear",
        json={"tenant": str(uuid4()), "token": token},
    )

    assert salida.status_code != 200, "un enlace ha valido en un tenant que no es el suyo"


def test_sin_tenant_no_se_acepta_la_peticion(api_sales: Any) -> None:
    """Sin él la ruta no puede abrir ninguna sesión, y adivinarlo sería peor."""
    salida = api_sales.post("/api/v1/portal-partner/entrar", json={"email": "a@b.com"})
    assert salida.status_code == 422


# ── Y el portal de cliente: lo que anuncia es lo que sirve ───────────────


def test_el_portal_no_anuncia_lo_que_no_sirve() -> None:
    """`secciones_de` decía ocho y había ruta para una (`CRM-04.03.02.01`).

    El portal anunciaba contratos, activos, pedidos, facturas y contactos, y no
    hay endpoint para ninguna: el cliente pinta botones que no llevan a ninguna
    parte — que es justo lo contrario de para lo que existe esa función, cuyo
    comentario decía «para que el portal no pinte botones que…».

    Añadir una sección a `SECCIONES_SERVIDAS` sin su ruta hace fallar esto, y
    es deliberado: una sección anunciada y sin servir es una promesa que el
    cliente descubre pulsando.
    """
    from pathlib import Path

    from services.service import portal

    # Se mira en TODOS los servicios, no sólo en el dueño del acceso. Contratos
    # y pedidos los sirve `sales` y los contactos `party`, porque traerlos a
    # `service` obligaría a copiar sus tablas — y la copia es siempre la que se
    # queda vieja. Mirando sólo aquí, el gate habría dado verde con tres de las
    # siete sin servir.
    raiz = Path(__file__).resolve().parents[2] / "services"
    rutas = "\n".join(f.read_text(encoding="utf-8") for f in raiz.rglob("api*.py"))
    sin_ruta = [s for s in portal.SECCIONES_SERVIDAS if f'"/mi/{s}"' not in rutas]
    assert not sin_ruta, (
        f"estas secciones se anuncian y no tienen ruta: {sin_ruta}. O se sirve, "
        "o se quita de SECCIONES_SERVIDAS."
    )
    # Y al revés: una ruta `/mi/<algo>` que sirva una sección que nadie anuncia
    # es una sección a la que no llega ningún acceso, o sea código muerto con
    # aspecto de función.
    anunciadas = {s for ss in portal.SECCIONES_POR_NIVEL.values() for s in ss}
    assert set(portal.SECCIONES_SERVIDAS) <= anunciadas, (
        "hay secciones servidas que ningún nivel anuncia: "
        f"{sorted(set(portal.SECCIONES_SERVIDAS) - anunciadas)}"
    )


def test_la_seccion_se_comprueba_en_el_servidor() -> None:
    """`secciones_de` es una ayuda al cliente, no un control.

    Filtrar en el cliente funciona hasta que alguien mira la respuesta de la
    API, y entonces el portal deja de ser un portal para ser una copia del CRM
    con un filtro de pantalla. `exigir_seccion` no la llamaba nadie.
    """
    import ast
    from pathlib import Path

    from services.service import portal

    # TODA ruta `/mi/<seccion>` de cualquier servicio tiene que llevar la guarda
    # declarada. Antes se comprobaba una sola función por su nombre, y eso daba
    # verde con seis rutas nuevas sin comprobar nada.
    raiz = Path(__file__).resolve().parents[2] / "services"
    sin_guarda: list[str] = []
    recorridas = 0
    for fichero in sorted(raiz.rglob("api*.py")):
        arbol = ast.parse(fichero.read_text(encoding="utf-8"), str(fichero))
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in nodo.decorator_list:
                if not isinstance(deco, ast.Call) or not deco.args:
                    continue
                camino = getattr(deco.args[0], "value", "")
                if not isinstance(camino, str) or not camino.startswith("/mi/"):
                    continue
                seccion = camino.split("/")[2]
                if seccion not in portal.SECCIONES_SERVIDAS:
                    continue
                recorridas += 1
                if "exige_seccion_portal(" not in ast.unparse(deco):
                    sin_guarda.append(f"{fichero.name}::{nodo.name}")
    assert recorridas >= len(portal.SECCIONES_SERVIDAS), (
        f"sólo se han recorrido {recorridas} rutas de portal para "
        f"{len(portal.SECCIONES_SERVIDAS)} secciones servidas: la comprobación no "
        "está mirando donde cree"
    )
    assert not sin_guarda, (
        "estas rutas del portal no declaran la guarda de sección, así que la "
        f"comprobación se queda en el cliente: {sorted(sin_guarda)}"
    )


def test_un_acceso_sin_la_seccion_no_entra() -> None:
    """Las secciones declaradas en el acceso **intersecan** con las del nivel:
    declarar una no puede ser una forma de saltarse el otro."""
    from crmcore.errors import Prohibido

    from services.service import portal as prt

    class _Acceso:
        nivel = "propio"
        secciones = ["conocimiento"]  # no incluye «casos»

    with pytest.raises(Prohibido) as fallo:
        prt.exigir_seccion(_Acceso(), "casos")
    assert fallo.value.error_code == "portal.seccion_no_permitida"


def test_un_acceso_con_la_seccion_si_entra() -> None:
    """La otra mitad: sin esto, un cambio que cerrara todo pasaría igual."""
    from services.service import portal as prt

    class _Acceso:
        nivel = "propio"
        secciones: list[str] = []

    prt.exigir_seccion(_Acceso(), "casos")  # no lanza


def test_el_cruce_con_lo_servido_se_aplica_de_verdad(monkeypatch) -> None:
    """La mitad que faltaba, y sin ella la de arriba no significaba nada.

    Comprobar que `SECCIONES_SERVIDAS` cuadra con las rutas no basta: hay que
    comprobar que `secciones_de` **la usa**. Sin esto, quitar el cruce pasaba en
    verde y el portal volvía a anunciar botones muertos.

    Antes esto se medía con la resta `por_nivel - anunciadas`, que valía mientras
    hubiera alguna sección anunciada y sin servir. El 05-10-2026 se sirvieron
    todas y la resta quedó vacía: la prueba habría seguido en verde con el cruce
    quitado, que es exactamente el fallo que vigila. Ahora se **planta** una
    sección sin servir, que es una medida que no depende de cuántas falten.
    """
    from services.service import portal as prt

    class _Admin:
        nivel = "admin"
        secciones: list[str] = []

    # Se añade al nivel una sección que NO está servida. Si el cruce se aplica,
    # no sale; si alguien lo quita, sale — y el portal pinta un botón muerto.
    monkeypatch.setitem(
        prt.SECCIONES_POR_NIVEL, "admin", (*prt.SECCIONES_POR_NIVEL["admin"], "inventada")
    )
    anunciadas = set(prt.secciones_de(_Admin()))
    assert "inventada" not in anunciadas, (
        "se anuncia una sección que no está servida: el cruce con "
        "SECCIONES_SERVIDAS no se está aplicando"
    )
    assert anunciadas <= set(
        prt.SECCIONES_SERVIDAS
    ), f"se anuncian secciones sin ruta detrás: {sorted(anunciadas - set(prt.SECCIONES_SERVIDAS))}"
    assert anunciadas, (
        "el nivel más alto no ve ninguna sección: o se ha vaciado "
        "SECCIONES_SERVIDAS o el cruce está tirando de más"
    )
