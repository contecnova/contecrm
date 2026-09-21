"""SCIM 2.0: aprovisionamiento y desaprovisionamiento (CRM-00.05.01.05).

El peso de estas pruebas está en la **baja**, que es la que no se ve fallar: un
alta rota la denuncia la persona que no puede entrar; una baja rota no la
denuncia nadie hasta que alguien que se fue hace meses sigue teniendo acceso.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado

from services.identity import scim
from services.identity.modelos import Membresia, RolTenant, Sesion, Usuario

BASE = "https://crm.ejemplo.com/api/v1/scim/v2"


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    """Unidad de trabajo sobre la transacción de la prueba, para poder afirmar
    sobre el estado sin depender de lo que quede escrito."""
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


# ── La trampa de `active` ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "crudo,esperado",
    [
        (True, True),
        (False, False),
        # Entra ID manda el booleano como texto y con mayúscula. `bool("False")`
        # es `True` en Python: leerlo así convierte una baja en «sigue activo»,
        # que es el fallo más caro que puede tener este módulo.
        ("False", False),
        ("false", False),
        ("True", True),
        ("0", False),
        ("1", True),
        (0, False),
        (1, True),
    ],
)
def test_active_se_lee_venga_como_venga(crudo: Any, esperado: bool) -> None:
    assert scim.como_booleano(crudo) is esperado


def test_un_active_ilegible_se_rechaza_en_vez_de_darse_por_activo() -> None:
    """Por defecto a `True` sería convertir una baja ilegible en un alta
    silenciosa; rechazando, el IdP reintenta y alguien lo ve."""
    with pytest.raises(ErrorValidacion) as e:
        scim.como_booleano("quizá")
    assert e.value.error_code == "scim.active_ilegible"


# ── Filtros ───────────────────────────────────────────────────────────────


def test_el_filtro_que_de_verdad_mandan_los_idp_funciona() -> None:
    condicion = scim.traducir_filtro('userName eq "Ana@Ejemplo.com"', {"username": Usuario.email})
    assert condicion is not None


def test_un_filtro_que_no_se_entiende_se_rechaza(monkeypatch: Any) -> None:
    """Devolver la lista entera ante un filtro compuesto haría que el IdP diera
    por existente a todo el mundo y no creara a nadie."""
    with pytest.raises(ErrorValidacion) as e:
        scim.traducir_filtro('userName eq "a" and active eq true', {"username": Usuario.email})
    assert e.value.error_code == "scim.filtro_no_soportado"


# ── Altas ─────────────────────────────────────────────────────────────────


@pytest.mark.db
def test_el_alta_no_pone_contrasena_local(uow: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Si la hubiera, existiría una vía de entrada que el IdP corporativo no
    controla, y la baja en el directorio no cerraría esa puerta."""
    usuario, membresia = scim.crear_usuario(
        uow, tenant_id, {"userName": "ana@ejemplo.com", "name": {"formatted": "Ana Ruiz"}}
    )
    assert usuario.hash_contrasena is None
    assert membresia.activa is True
    assert usuario.nombre == "Ana Ruiz"


@pytest.mark.db
def test_el_correo_se_coge_de_emails_si_username_no_lo_es(
    uow: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Hay IdP que mandan el nombre de cuenta en `userName`."""
    usuario, _ = scim.crear_usuario(
        uow,
        tenant_id,
        {"userName": "aruiz", "emails": [{"value": "Ana@Ejemplo.com", "primary": True}]},
    )
    assert usuario.email == "ana@ejemplo.com"


@pytest.mark.db
def test_repetir_el_alta_da_conflicto_con_el_id_dentro(
    uow: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es el caso más común en producción: el alta salió bien y la respuesta se
    perdió. Devolver el identificador deja al IdP reconciliar solo."""
    usuario, _ = scim.crear_usuario(uow, tenant_id, {"userName": "ana@ejemplo.com"})
    uow.db.flush()
    with pytest.raises(Conflicto) as e:
        scim.crear_usuario(uow, tenant_id, {"userName": "ana@ejemplo.com"})
    assert e.value.error_code == "scim.usuario_duplicado"
    assert e.value.detalle["id"] == str(usuario.id)


@pytest.mark.db
def test_un_grupo_desconocido_del_directorio_no_concede_nada(
    uow: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Si valiera por el nombre, quien administre el directorio corporativo
    podría darse permisos aquí creando un grupo llamado «admin»."""
    _, membresia = scim.crear_usuario(
        uow,
        tenant_id,
        {
            "userName": "ana@ejemplo.com",
            "groups": [{"display": "Domain Admins"}, {"display": "Impresoras Planta 2"}],
        },
    )
    assert membresia.roles == []


@pytest.mark.db
def test_un_rol_que_si_existe_en_el_tenant_si_se_asigna(
    uow: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    uow.db.add(RolTenant(tenant_id=tenant_id, nombre="Comercial", permisos=["account:read"]))
    uow.db.flush()
    _, membresia = scim.crear_usuario(
        uow, tenant_id, {"userName": "ana@ejemplo.com", "groups": [{"display": "Comercial"}]}
    )
    assert membresia.roles == ["Comercial"]


# ── Bajas: lo que de verdad importa ───────────────────────────────────────


@pytest.mark.db
def test_la_baja_corta_las_sesiones_abiertas(
    uow: Any, db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Marcar la membresía sin revocar las sesiones deja al que se va operando
    hasta que le caduque el token, que es justo el rato que importa."""
    from services.identity import servicio as svc

    usuario, _ = scim.crear_usuario(uow, tenant_id, {"userName": "ana@ejemplo.com"})
    uow.db.flush()
    svc.crear_sesion(uow.db, usuario=usuario, tenant_id=tenant_id, ip="10.0.0.1")
    uow.db.flush()

    scim.aplicar_patch(
        uow,
        usuario.id,
        tenant_id,
        {"Operations": [{"op": "replace", "path": "active", "value": False}]},
    )
    uow.db.flush()

    vivas = [
        s
        for s in db.query(Sesion).filter(Sesion.usuario_id == usuario.id).all()
        if s.revocada_at is None
    ]
    assert vivas == []


@pytest.mark.db
def test_patch_sin_path_tambien_da_de_baja(
    uow: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Okta manda el atributo dentro de `value`. Mirando solo `path`, la baja se
    ignora en silencio y se responde 200, que es peor que fallar."""
    usuario, _ = scim.crear_usuario(uow, tenant_id, {"userName": "ana@ejemplo.com"})
    uow.db.flush()
    _, membresia = scim.aplicar_patch(
        uow, usuario.id, tenant_id, {"Operations": [{"op": "replace", "value": {"active": False}}]}
    )
    assert membresia.activa is False


@pytest.mark.db
def test_active_en_texto_da_de_baja_de_verdad(
    uow: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La prueba que justifica todo el módulo: `"False"` de Entra ID."""
    usuario, _ = scim.crear_usuario(uow, tenant_id, {"userName": "ana@ejemplo.com"})
    uow.db.flush()
    _, membresia = scim.aplicar_patch(
        uow,
        usuario.id,
        tenant_id,
        {"Operations": [{"op": "Replace", "path": "active", "value": "False"}]},
    )
    assert membresia.activa is False


@pytest.mark.db
def test_delete_desactiva_pero_no_borra(uow: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Borrar dejaría huérfano todo lo que creó y el historial de auditoría
    apuntaría a un identificador que ya no existe."""
    usuario, _ = scim.crear_usuario(uow, tenant_id, {"userName": "ana@ejemplo.com"})
    uow.db.flush()
    scim.desactivar(uow, usuario.id, tenant_id)
    uow.db.flush()

    assert uow.db.get(Usuario, usuario.id) is not None
    _, membresia = scim.leer_usuario(uow.db, usuario.id, tenant_id)
    assert membresia.activa is False


@pytest.mark.db
def test_la_baja_en_un_tenant_no_echa_de_los_demas(
    uow: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es lo que permite que un consultor que trabaja para tres clientes tenga
    una sola identidad: mirar `Usuario.activo` aquí lo echaría de todos."""
    usuario, _ = scim.crear_usuario(uow, tenant_id, {"userName": "ana@ejemplo.com"})
    uow.db.add(Membresia(tenant_id=otro_tenant_id, usuario_id=usuario.id, roles=[]))
    uow.db.flush()

    scim.desactivar(uow, usuario.id, tenant_id)
    uow.db.flush()

    otra = (
        uow.db.query(Membresia)
        .filter(Membresia.usuario_id == usuario.id, Membresia.tenant_id == otro_tenant_id)
        .one()
    )
    assert otra.activa is True
    assert uow.db.get(Usuario, usuario.id).activo is True


@pytest.mark.db
def test_reactivar_vuelve_a_dejar_entrar(uow: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Quien vuelve de una excedencia no puede necesitar un alta nueva: sería
    una identidad distinta y perdería su historial."""
    usuario, _ = scim.crear_usuario(uow, tenant_id, {"userName": "ana@ejemplo.com"})
    uow.db.flush()
    scim.desactivar(uow, usuario.id, tenant_id)
    uow.db.flush()
    _, membresia = scim.aplicar_patch(
        uow,
        usuario.id,
        tenant_id,
        {"Operations": [{"op": "replace", "path": "active", "value": True}]},
    )
    assert membresia.activa is True


@pytest.mark.db
def test_no_se_toca_un_usuario_de_otro_tenant(
    uow: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El tenant sale de la clave de API; un id ajeno tiene que ser un 404 y no
    un 403, para no confirmar que ese usuario existe en otro sitio."""
    usuario = Usuario(email="ajena@otro.com", nombre="Ajena")
    uow.db.add(usuario)
    uow.db.flush()
    uow.db.add(Membresia(tenant_id=otro_tenant_id, usuario_id=usuario.id, roles=[]))
    uow.db.flush()

    with pytest.raises(NoEncontrado):
        scim.leer_usuario(uow.db, usuario.id, tenant_id)


# ── PATCH que no dice nada ────────────────────────────────────────────────


@pytest.mark.db
def test_un_patch_vacio_no_se_responde_con_un_ok(
    uow: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    usuario, _ = scim.crear_usuario(uow, tenant_id, {"userName": "ana@ejemplo.com"})
    uow.db.flush()
    with pytest.raises(ErrorValidacion) as e:
        scim.aplicar_patch(uow, usuario.id, tenant_id, {"Operations": []})
    assert e.value.error_code == "scim.patch_vacio"


@pytest.mark.db
def test_los_atributos_de_directorio_que_no_se_guardan_no_rompen_el_ciclo(
    uow: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Los IdP mandan decenas —departamento, oficina, manager—. Fallar por ellos
    pararía la sincronización entera, incluidas las bajas."""
    usuario, _ = scim.crear_usuario(uow, tenant_id, {"userName": "ana@ejemplo.com"})
    uow.db.flush()
    _, membresia = scim.aplicar_patch(
        uow,
        usuario.id,
        tenant_id,
        {
            "Operations": [
                {
                    "op": "replace",
                    "path": "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User:department",
                    "value": "Ventas",
                },
                {"op": "replace", "path": "active", "value": False},
            ]
        },
    )
    assert membresia.activa is False


# ── Búsqueda y representación ─────────────────────────────────────────────


@pytest.mark.db
def test_buscar_por_username_encuentra_sin_importar_mayusculas(
    uow: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Los IdP no normalizan el correo antes de preguntar, y un fallo aquí
    significa crear un duplicado en cada ciclo."""
    scim.crear_usuario(uow, tenant_id, {"userName": "ana@ejemplo.com"})
    uow.db.flush()
    filas, total = scim.buscar_usuarios(uow.db, tenant_id, filtro='userName eq "ANA@Ejemplo.com"')
    assert total == 1 and len(filas) == 1


@pytest.mark.db
def test_la_pagina_tiene_tope_aunque_pidan_mas(
    uow: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sin tope, un `count` desmedido de un IdP mal configurado se lleva por
    delante el servicio de identidad, que es el que no puede caer."""
    for i in range(3):
        scim.crear_usuario(uow, tenant_id, {"userName": f"u{i}@ejemplo.com"})
    uow.db.flush()
    filas, _ = scim.buscar_usuarios(uow.db, tenant_id, por_pagina=100000)
    assert len(filas) <= scim.MAXIMO_POR_PAGINA


@pytest.mark.db
def test_la_representacion_lleva_location_publica(
    uow: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    usuario, membresia = scim.crear_usuario(uow, tenant_id, {"userName": "ana@ejemplo.com"})
    uow.db.flush()
    salida = scim.usuario_a_scim(usuario, membresia, BASE)
    assert salida["schemas"] == [scim.ESQUEMA_USUARIO]
    assert salida["meta"]["location"] == f"{BASE}/Users/{usuario.id}"
    assert salida["active"] is True


def test_el_servidor_no_declara_lo_que_no_tiene() -> None:
    """Declarar `bulk` sin tenerlo hace que el IdP lo intente y se lleve un
    error a mitad de un ciclo de sincronización."""
    config = scim.configuracion_del_proveedor(BASE)
    assert config["bulk"]["supported"] is False
    assert config["sort"]["supported"] is False
    assert config["patch"]["supported"] is True
    assert config["filter"]["maxResults"] == scim.MAXIMO_POR_PAGINA


# ── Grupos ────────────────────────────────────────────────────────────────


@pytest.mark.db
def test_anadir_y_quitar_miembros_de_un_grupo(
    uow: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    rol = RolTenant(tenant_id=tenant_id, nombre="Comercial", permisos=["account:read"])
    uow.db.add(rol)
    usuario, _ = scim.crear_usuario(uow, tenant_id, {"userName": "ana@ejemplo.com"})
    uow.db.flush()

    _, miembros = scim.patch_grupo(
        uow,
        rol.id,
        tenant_id,
        {"Operations": [{"op": "add", "path": "members", "value": [{"value": str(usuario.id)}]}]},
    )
    assert [u.id for u in miembros] == [usuario.id]

    _, miembros = scim.patch_grupo(
        uow,
        rol.id,
        tenant_id,
        {
            "Operations": [
                {"op": "remove", "path": "members", "value": [{"value": str(usuario.id)}]}
            ]
        },
    )
    assert miembros == []
