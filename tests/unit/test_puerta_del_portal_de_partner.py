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
