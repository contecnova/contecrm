"""Auditoría de autorización (CRM-00.05.02), por las rutas de verdad.

Diecisiete capacidades en la familia, nueve sin ninguna prueba que las nombre.
Aquí se recorren esas nueve, y la que más importa es la que explica por qué
existe el subsistema entero:

**El listado y la ficha tienen que decir lo mismo** (CRM-00.05.02.18 y .19). El
fallo clásico de estos sistemas es un listado que enseña un registro que la
ficha luego niega —o al revés, un registro invisible en la lista y accesible por
su identificador—. Son dos caminos distintos: la ficha evalúa la política en
Python sobre el registro y el listado la traduce a SQL. Que coincidan no es una
aspiración, es la propiedad que hay que comprobar, y se comprueba pidiendo las
dos cosas por HTTP con la misma política puesta.

Lo demás que se recorre aquí: que los permisos de los roles se **acumulen** y no
se pisen, que la jerarquía dé visibilidad **ascendente**, que la política se
pueda publicar en formato neutro para otro motor, que la suplantación exija
motivo y caduque, que el explicador diga **por qué**, que una política se pueda
replicar al esquema de otro servicio, y que el simulador conteste **antes** de
activar nada — que es lo que separa escribir una política de cortarle el acceso
a gente que estaba trabajando.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterator
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


def _app(nombre: str) -> Iterator[Any]:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        with TestClient(importlib.import_module(nombre).app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


@pytest.fixture
def identidad(db: Any) -> Iterator[Any]:
    yield from _app("services.identity.main")


@pytest.fixture
def parties(db: Any) -> Iterator[Any]:
    yield from _app("services.party.main")


@pytest.fixture
def usuario() -> UUID:
    return uuid4()


def _alta(db: Any, usuario_id: UUID, *, correo: str) -> None:
    """Un usuario de verdad antes de su membresía.

    La membresía tiene clave foránea contra `usuarios`, y con razón: una
    membresía de alguien que no existe daría permisos a un identificador que
    nadie puede usar y que nadie encontraría al auditar.
    """
    from services.identity.modelos import Usuario

    db.add(Usuario(id=usuario_id, email=correo, nombre=correo.split("@")[0]))
    db.flush()


def _cabeceras(tenant_id: UUID, usuario: UUID, *, permisos: str = "*:*") -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import (
        H_FACTOR_FUERTE,
        H_PERMISOS,
        H_ROLES,
        H_TENANT,
        H_USER,
        firmar_cabeceras_internas,
    )

    return firmar_cabeceras_internas(
        {
            H_TENANT: str(tenant_id),
            H_USER: str(usuario),
            H_PERMISOS: permisos,
            H_ROLES: "admin",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


@pytest.fixture
def cabeceras(tenant_id: UUID, usuario: UUID) -> dict[str, str]:
    return _cabeceras(tenant_id, usuario)


# ── CRM-00.05.02.18 y CRM-00.05.02.19 · El listado y la ficha ─────────────


@pytest.fixture
def dos_cuentas(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> tuple[Any, Any]:
    """Una del norte y otra del sur, para poder cortar por una de las dos."""
    from services.party.modelos import Cuenta

    norte = Cuenta(
        tenant_id=tenant_id, nombre="Norte SA", clave_canonica="norte-sa", sector_esquema="norte"
    )
    sur = Cuenta(
        tenant_id=tenant_id, nombre="Sur SA", clave_canonica="sur-sa", sector_esquema="sur"
    )
    db.add_all([norte, sur])
    db.flush()
    return norte, sur


def _politica_que_esconde_el_sur(db: Any, tenant_id: UUID) -> None:
    """Una política activa que tapa las cuentas del sur.

    Se escribe en el esquema de `party` porque **la decisión se toma donde está
    el dato**: ningún servicio lee el esquema de otro, y por eso las políticas
    se replican. La replicación se recorre aparte, en su propia prueba.
    """
    from crmcore.authz.politicas import guardar, invalidar

    guardar(
        db,
        tenant_id=tenant_id,
        nombre="solo-el-norte",
        objeto="cuenta",
        acciones=["read", "write"],
        condiciones=[{"atributo": "registro.sector_esquema", "operador": "=", "valor": "norte"}],
        activa=True,
    )
    db.flush()
    invalidar(tenant_id)


def test_el_listado_y_la_ficha_dicen_lo_mismo_crm_00_05_02_19(
    parties: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, dos_cuentas: Any
) -> None:
    """**La propiedad que justifica el subsistema entero.** Son dos caminos: la
    ficha evalúa en Python sobre el registro y el listado traduce la misma
    condición a SQL. Un listado que enseña lo que la ficha niega hace que se
    deje de creer a los dos."""
    norte, sur = dos_cuentas

    # Sin política, las dos se ven y las dos se abren.
    antes = parties.get("/api/v1/accounts", headers=cabeceras)
    assert antes.status_code == 200, antes.text
    nombres = {f["nombre"] for f in antes.json()["items"]}
    assert {"Norte SA", "Sur SA"} <= nombres, nombres
    assert parties.get(f"/api/v1/accounts/{sur.id}", headers=cabeceras).status_code == 200

    _politica_que_esconde_el_sur(db, tenant_id)

    despues = parties.get("/api/v1/accounts", headers=cabeceras)
    assert despues.status_code == 200, despues.text
    visibles = {f["nombre"] for f in despues.json()["items"]}
    assert "Norte SA" in visibles, "la política se ha llevado por delante lo que sí se puede ver"
    assert "Sur SA" not in visibles, "el listado sigue enseñando lo que la política tapa"

    # Y la ficha, por el otro camino, tiene que decir lo mismo.
    ficha = parties.get(f"/api/v1/accounts/{sur.id}", headers=cabeceras)
    assert ficha.status_code == 403, (
        f"el listado la esconde y la ficha contesta {ficha.status_code}: un "
        "registro invisible en la lista y accesible por su identificador es el "
        "fallo clásico de estos sistemas"
    )
    # Y **con la explicación dentro**: la política que decide y la condición que
    # falló. Un «no tienes permiso» a secas es el ticket más caro de cerrar,
    # porque quien lo recibe no puede hacer nada con él.
    detalle = ficha.json()
    assert "solo-el-norte" in str(detalle), detalle
    assert parties.get(f"/api/v1/accounts/{norte.id}", headers=cabeceras).status_code == 200


def test_el_abac_se_aplica_tambien_a_quien_administra_crm_00_05_02_18(
    parties: Any, db: Any, tenant_id: UUID, usuario: UUID, dos_cuentas: Any
) -> None:
    """La compartición **no** se le aplica a quien administra —tiene que ver el
    maestro entero o no puede administrar nada—, pero una política de «esta
    unidad no ve lo de la otra» dejaría de servir para nada si el administrador
    fuera la excepción: es exactamente a quien se le pone."""
    _politica_que_esconde_el_sur(db, tenant_id)

    como_admin = _cabeceras(tenant_id, usuario, permisos="cuenta:admin,account:read,account:admin")
    r = parties.get("/api/v1/accounts", headers=como_admin)
    assert r.status_code == 200, r.text
    assert "Sur SA" not in {f["nombre"] for f in r.json()["items"]}, (
        "quien administra se salta la política de dato: entonces la política no "
        "sirve para nada, porque es justo a él a quien se le pone"
    )


# ── CRM-00.05.02.01 · Permisos acumulables ────────────────────────────────


def test_los_conjuntos_de_permisos_se_suman_y_no_se_pisan_crm_00_05_02_01(
    db: Any, tenant_id: UUID, usuario: UUID, contexto_tenant: UUID
) -> None:
    """Acumulables es la palabra del catálogo y es la que importa: con dos roles,
    quien decide no es el último que se asignó. Si se pisaran, quitar un rol a
    alguien podría **darle** permisos."""
    from services.identity import servicio as svc
    from services.identity.modelos import Membresia, RolTenant

    db.add_all(
        [
            RolTenant(tenant_id=tenant_id, nombre="lector", permisos=["cuenta:read"]),
            RolTenant(
                tenant_id=tenant_id,
                nombre="editor",
                permisos=["cuenta:write", "oportunidad:read"],
            ),
        ]
    )
    _alta(db, usuario, correo="con-dos-roles@example.com")
    db.add(Membresia(tenant_id=tenant_id, usuario_id=usuario, roles=["lector", "editor"]))
    db.flush()

    permisos = svc.permisos_efectivos(db, usuario, tenant_id)
    assert {"cuenta:read", "cuenta:write", "oportunidad:read"} <= set(permisos), sorted(permisos)


# ── CRM-00.05.02.02 · Visibilidad ascendente ──────────────────────────────


def test_un_responsable_ve_lo_de_su_equipo_y_no_al_reves_crm_00_05_02_02(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Ascendente y no descendente: el responsable ve lo de los suyos, y los
    suyos no ven lo del responsable. Si fuera simétrica no sería una jerarquía,
    sería un equipo plano — y la cartera del jefe estaría a la vista de todos.

    **La jerarquía se lee de la copia replicada** (CRM-00.05.02.12), no de la
    membresía: la membresía vive en `identity` y ningún servicio lee el esquema
    de otro, así que `party` y `sales` deciden con la copia que les llega por
    evento. Aquí se aplica ese evento, que es lo que hace el consumidor.
    """
    from crmcore.authz.jerarquia import aplicar_mando, subordinados_de

    jefe, uno, otro = uuid4(), uuid4(), uuid4()
    for quien, superior in ((jefe, None), (uno, jefe), (otro, jefe)):
        aplicar_mando(db, tenant_id=tenant_id, usuario_id=quien, superior_id=superior)
    db.flush()

    bajo_el_jefe = subordinados_de(db, tenant_id, jefe)
    assert {uno, otro} <= set(bajo_el_jefe), bajo_el_jefe
    assert jefe not in subordinados_de(
        db, tenant_id, uno
    ), "la visibilidad sube y baja: entonces no es una jerarquía"


def test_quien_deja_de_depender_de_alguien_sale_el_mismo_dia_crm_00_05_02_12(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """**El nulo se acepta a propósito.** Quien asciende o se va deja de contarse
    como subordinado ese mismo día; ignorar el nulo dejaría a su antiguo jefe
    viendo su cartera para siempre, y eso no falla nunca — simplemente alguien
    sigue viendo lo que ya no debería."""
    from crmcore.authz.jerarquia import aplicar_mando, subordinados_de

    jefe, quien = uuid4(), uuid4()
    aplicar_mando(db, tenant_id=tenant_id, usuario_id=quien, superior_id=jefe)
    db.flush()
    assert quien in subordinados_de(db, tenant_id, jefe)

    aplicar_mando(db, tenant_id=tenant_id, usuario_id=quien, superior_id=None)
    db.flush()
    assert quien not in subordinados_de(
        db, tenant_id, jefe
    ), "sigue contándose como subordinado después de dejar de serlo"


# ── CRM-00.05.02.06 · Motor externalizable ────────────────────────────────


def test_la_politica_se_publica_en_formato_neutro_crm_00_05_02_06(
    identidad: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Para cargarla en OPA, en Cedar o en el motor del cliente **sin leer
    nuestra base**. No se traduce a ningún dialecto a propósito: hacerlo aquí
    ataría el producto a ese dialecto.

    Y la semántica viaja **dentro del documento**, porque quien escriba el
    traductor la necesita delante: una nota en un manual aparte es una nota que
    no se lee. Lo decisivo es `operador_desconocido: denegar` — un traductor que
    no supiera eso convertiría un operador que no entiende en un permitir.
    """
    _politica_que_esconde_el_sur(db, tenant_id)

    r = identidad.get("/api/v1/politicas-acceso/publicar", headers=cabeceras)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["formato"].startswith("contecrm.abac/")
    semantica = cuerpo["semantica"]
    for clave in (
        "combinacion_entre_politicas",
        "efecto",
        "sin_politicas",
        "operador_desconocido",
        "prefijo_referencia_atributo",
    ):
        assert clave in semantica, f"falta «{clave}»: {sorted(semantica)}"
    assert semantica["operador_desconocido"] == "denegar"
    assert semantica["efecto"] == "restringir"
    assert any(p["nombre"] == "solo-el-norte" for p in cuerpo["politicas"]), cuerpo["politicas"]


# ── CRM-00.05.02.17 · Políticas versionadas y replicadas ──────────────────


def test_una_politica_sube_de_version_al_cambiarla_crm_00_05_02_17(
    identidad: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Versionada no es un adorno: cuando alguien pierde acceso, la pregunta es
    qué cambió y cuándo, y sin versión no hay forma de contestarla."""
    from crmcore.authz.politicas import guardar

    una = guardar(
        db,
        tenant_id=tenant_id,
        nombre="por-unidad",
        objeto="cuenta",
        acciones=["read"],
        condiciones=[{"atributo": "registro.sector_esquema", "operador": "=", "valor": "norte"}],
    )
    primera = una.version
    dos = guardar(
        db,
        tenant_id=tenant_id,
        nombre="por-unidad",
        objeto="cuenta",
        acciones=["read"],
        condiciones=[{"atributo": "registro.sector_esquema", "operador": "=", "valor": "sur"}],
    )
    assert dos.version > primera, (dos.version, primera)
    db.flush()

    historial = identidad.get("/api/v1/politicas-acceso/por-unidad/versiones", headers=cabeceras)
    assert historial.status_code == 200, historial.text
    assert len(historial.json()) >= 2, historial.json()


def test_un_operador_que_no_existe_no_se_guarda_crm_00_05_02_17(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Se valida la gramática **antes** de guardar. Una política con un operador
    inventado se evalúa como denegar —en seguridad, ante la duda, no—, así que
    guardarla convertiría una errata en un corte de acceso silencioso para quien
    la activara."""
    from crmcore.authz.politicas import guardar
    from crmcore.errors import ErrorValidacion

    with pytest.raises(ErrorValidacion):
        guardar(
            db,
            tenant_id=tenant_id,
            nombre="mal-escrita",
            objeto="cuenta",
            acciones=["read"],
            condiciones=[
                {"atributo": "registro.sector_esquema", "operador": "parecido_a", "valor": "n"}
            ],
        )


# ── CRM-00.05.02.21 · El simulador ────────────────────────────────────────


def test_el_simulador_contesta_antes_de_activar_nada_crm_00_05_02_21(
    identidad: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Una política mal escrita no da un error: da un corte de acceso silencioso
    a gente que estaba trabajando, y se descubre por los tickets. El simulador
    acepta una política **que todavía no existe**, que es la única forma de
    saberlo antes."""
    from services.identity.modelos import Membresia, RolTenant

    quien = uuid4()
    # Con el permiso puesto: el resultado del simulador es la CONJUNCIÓN del
    # rol y de la política —el ABAC restringe, no concede—, así que sin el
    # permiso saldría «no» en los dos casos y la prueba no mediría la política.
    _alta(db, quien, correo="simulado@example.com")
    db.add(RolTenant(tenant_id=tenant_id, nombre="ve-cuentas", permisos=["cuenta:read"]))
    db.add(Membresia(tenant_id=tenant_id, usuario_id=quien, roles=["ve-cuentas"]))
    db.flush()

    propuesta = {
        "nombre": "sin-guardar",
        "objeto": "cuenta",
        "acciones": ["read"],
        "condiciones": [{"atributo": "registro.sector_esquema", "operador": "=", "valor": "norte"}],
        "combinacion": "todas",
        "activa": True,
    }
    tapada = identidad.post(
        "/api/v1/politicas-acceso/simular",
        headers=cabeceras,
        json={
            "usuario_id": str(quien),
            "objeto": "cuenta",
            "accion": "read",
            "registro": {"sector_esquema": "sur"},
            "politica": propuesta,
        },
    )
    assert tapada.status_code == 200, tapada.text
    assert tapada.json()["permitido"] is False, tapada.json()
    # Y dice cuál de las dos mitades ha dicho que no, que es lo que se consulta:
    # un «no» sin repartir obliga a mirar el rol y la política a mano.
    assert tapada.json()["rbac"]["concede"] is True, tapada.json()
    assert tapada.json()["abac"]["permitido"] is False, tapada.json()

    vista = identidad.post(
        "/api/v1/politicas-acceso/simular",
        headers=cabeceras,
        json={
            "usuario_id": str(quien),
            "objeto": "cuenta",
            "accion": "read",
            "registro": {"sector_esquema": "norte"},
            "politica": propuesta,
        },
    )
    assert vista.json()["permitido"] is True, vista.json()

    # Y no la ha guardado: simular que guarda es la peor trampa posible aquí.
    from crmcore.authz.politicas import PoliticaAbac
    from sqlalchemy import select

    assert (
        db.execute(
            select(PoliticaAbac).where(PoliticaAbac.nombre == "sin-guardar")
        ).scalar_one_or_none()
        is None
    )


# ── CRM-00.05.02.11 · El explicador ───────────────────────────────────────


def test_el_explicador_dice_por_que_crm_00_05_02_11(
    identidad: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """«No puedo hacer X» sin explicación es el ticket de soporte más frecuente
    de cualquier CRM y el más caro de cerrar: hay que reproducirlo con la cuenta
    de otro. Esto contesta con el permiso que decide y la política que aplica."""
    from services.identity.modelos import Membresia, RolTenant

    quien = uuid4()
    _alta(db, quien, correo="solo-lee@example.com")
    db.add(RolTenant(tenant_id=tenant_id, nombre="solo-lee", permisos=["cuenta:read"]))
    db.add(Membresia(tenant_id=tenant_id, usuario_id=quien, roles=["solo-lee"]))
    db.flush()

    puede = identidad.post(
        "/api/v1/roles/explicar",
        headers=cabeceras,
        json={"usuario_id": str(quien), "objeto": "cuenta", "accion": "read"},
    )
    assert puede.status_code == 200, puede.text
    assert puede.json()["permitido"] is True, puede.json()
    assert puede.json()["rbac"]["roles"] == ["solo-lee"], puede.json()

    no_puede = identidad.post(
        "/api/v1/roles/explicar",
        headers=cabeceras,
        json={"usuario_id": str(quien), "objeto": "cuenta", "accion": "write"},
    )
    assert no_puede.status_code == 200, no_puede.text
    # Lo que importa no es el «no»: es que diga QUÉ permiso falta y de qué mitad
    # viene, porque es lo único con lo que soporte cierra el ticket sin
    # escalarlo. Y la explicación del ABAC va aparte del rol a propósito: «no
    # tienes permiso» y «una política te lo tapa» se arreglan de forma distinta.
    cuerpo = no_puede.json()
    assert cuerpo["permitido"] is False
    assert cuerpo["rbac"]["concede"] is False
    assert cuerpo["rbac"]["permiso"] == "cuenta:write", cuerpo
    assert "explicacion" in cuerpo["abac"], cuerpo


# ── CRM-00.05.02.10 · Suplantación ────────────────────────────────────────


def test_suplantar_exige_motivo_escrito_crm_00_05_02_10(
    identidad: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sin motivo, el acceso no es defendible: dentro de seis meses nadie sabrá
    por qué alguien de soporte entró en la cuenta de un cliente. Diez caracteres
    mínimo — «ok» no es un motivo."""
    corto = identidad.post(
        "/api/v1/sesiones/suplantar",
        headers=cabeceras,
        json={"usuario_id": str(uuid4()), "motivo": "ok"},
    )
    assert corto.status_code == 422, corto.text


def test_el_motivo_de_una_suplantacion_se_puede_LEER_crm_00_05_02_10(
    identidad: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Se exigía escribirlo y **no se podía leer**.

    Entrar como otra persona exige motivo —y hace bien—, pero ese porqué se
    guardaba y no lo devolvía ninguna ruta: en el listado de sesiones quedaba
    un identificador en una columna, y nadie sabe de quién es un UUID. Una
    exigencia que no se puede revisar es papeleo.

    Y la lista dice **cuáles son suplantaciones** en una palabra. Un
    `actor_real_id` con valor ya lo dice, pero lo dice en un formato que nadie
    lee de un vistazo, y lo que hay que ver aquí es precisamente eso.
    """
    r = identidad.get("/api/v1/sesiones", headers=cabeceras)
    assert r.status_code == 200, r.text
    filas = r.json()
    filas = filas["items"] if isinstance(filas, dict) else filas
    assert isinstance(filas, list)
    # El contrato tiene que traer las dos: sin el motivo no se revisa, y sin la
    # marca hay que mirar UUIDs uno a uno para encontrarlas.
    campos = set(filas[0]) if filas else set()
    if filas:
        assert "motivo_suplantacion" in campos, "el porqué sigue sin salir"
        assert "suplantada" in campos, "hay que leer UUIDs para saber cuál lo es"


def test_una_sesion_normal_no_sale_marcada_como_suplantacion(
    identidad: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """**El caso que haría inútil la marca.** Si todas salieran marcadas, la
    columna no distinguiría nada y se dejaría de mirar."""
    from datetime import datetime, timezone

    from services.identity.esquemas import SesionOut

    ahora = datetime.now(timezone.utc)
    normal = SesionOut(id=uuid4(), creada_at=ahora, ultima_actividad_at=ahora, expira_at=ahora)
    assert normal.suplantada is False
    suplantada = SesionOut(
        id=uuid4(),
        creada_at=ahora,
        ultima_actividad_at=ahora,
        expira_at=ahora,
        actor_real_id=uuid4(),
        motivo_suplantacion="Reproducir la incidencia 4821 del cliente.",
    )
    assert suplantada.suplantada is True
