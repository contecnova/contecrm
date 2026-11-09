"""MFA obligatoria por rol (CRM-00.05.01.06) y «entrar como» de soporte
(CRM-00.01.02.06).

Lo que se fija es lo que decide si sirven:

- que la regla del login sea **la misma** que enseña el panel: el interruptor
  global suma y nunca resta, y los roles añaden a quién se le exige;
- que un valor del ajuste mal escrito no se convierta en «no se exige a
  nadie», y que un rol inventado se rechace al guardarlo;
- que la entrada con contraseña la pida de verdad a quien lleva el rol, **con el
  ajuste de su empresa** —en la entrada todavía no hay nadie autenticado y el
  contexto no lleva tenant—;
- que no se pueda entrar «como» alguien que no pertenece a esa empresa, y que
  `/auth/me` devuelva el motivo con el que se entró, que es lo que dice la
  franja.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.errors import NoEncontrado, Prohibido

from services.identity import servicio as svc


def _con_ajustes(monkeypatch: Any, valores: dict[str, Any]) -> list[Any]:
    """Sustituye `efectivo` y apunta con qué tenant en contexto se leyó."""
    from crmcore.runtime import settings as rt
    from crmcore.tenancy.context import contexto_actual

    leidos: list[Any] = []

    def _efectivo(clave: str, *a: Any, **k: Any) -> Any:
        leidos.append((clave, contexto_actual().tenant_id))
        return valores.get(clave)

    monkeypatch.setattr(rt, "efectivo", _efectivo)
    return leidos


# ── La regla ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("global_", "roles_exigidos", "roles_suyos", "esperado"),
    [
        (False, [], ["admin"], False),  # como antes: manda el interruptor
        (True, [], ["comercial"], True),  # el interruptor exige a todos
        (False, ["admin"], ["admin", "comercial"], True),
        (False, ["admin"], ["comercial"], False),
        (True, ["admin"], ["comercial"], True),  # suma, nunca resta
    ],
)
def test_el_interruptor_suma_y_los_roles_anaden(
    monkeypatch: Any,
    global_: bool,
    roles_exigidos: list[str],
    roles_suyos: list[str],
    esperado: bool,
) -> None:
    _con_ajustes(monkeypatch, {"mfa_obligatoria": global_, "mfa_obligatoria_roles": roles_exigidos})
    assert svc.mfa_exigida(None, roles_suyos) is esperado  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("crudo", "esperado"),
    [
        ("admin, comercial", ["admin", "comercial"]),
        (["comercial", " admin ", "", "admin"], ["admin", "comercial"]),
        ({"admin": True}, []),
        (None, []),
    ],
)
def test_un_valor_mal_escrito_no_se_lee_como_otra_cosa(
    monkeypatch: Any, crudo: Any, esperado: list[str]
) -> None:
    _con_ajustes(monkeypatch, {"mfa_obligatoria_roles": crudo})
    assert svc.roles_con_mfa_obligatoria(None) == esperado  # type: ignore[arg-type]


def test_al_entrar_se_lee_el_ajuste_de_la_empresa_y_no_el_del_contexto(
    monkeypatch: Any,
) -> None:
    """En la entrada el contexto no lleva tenant: sin ponerlo, `efectivo`
    saltaba al tier y el valor fijado para la empresa no se leía nunca."""
    tenant = uuid4()
    leidos = _con_ajustes(monkeypatch, {"mfa_obligatoria_roles": ["admin"]})
    assert svc.mfa_exigida(None, ["admin"], tenant) is True  # type: ignore[arg-type]
    assert leidos and all(t == tenant for _, t in leidos)


# ── En la base ────────────────────────────────────────────────────────────


def _persona(db: Any, tenant_id: UUID, roles: list[str], *, mfa: bool = False) -> Any:
    from services.identity.modelos import Membresia, Usuario

    usuario = Usuario(
        email=f"rol-{uuid4().hex[:8]}@ejemplo.com",
        nombre="Por Rol",
        hash_contrasena=svc.hashear_contrasena("una-contrasena-larga-2026"),
        activo=True,
        mfa_activo=mfa,
    )
    db.add(usuario)
    db.flush()
    db.add(Membresia(usuario_id=usuario.id, tenant_id=tenant_id, roles=roles, activa=True))
    db.flush()
    return usuario


@pytest.mark.db
def test_el_login_se_la_pide_a_quien_lleva_el_rol(
    db: Any, tenant_id: UUID, monkeypatch: Any
) -> None:
    _con_ajustes(monkeypatch, {"mfa_obligatoria": False, "mfa_obligatoria_roles": ["admin"]})
    admin = _persona(db, tenant_id, ["admin"])
    comercial = _persona(db, tenant_id, ["comercial"])

    with pytest.raises(Prohibido) as exc:
        svc.autenticar(
            db,
            email=admin.email,
            contrasena="una-contrasena-larga-2026",
            tenant_id=tenant_id,
        )
    assert exc.value.error_code == "auth.mfa_no_configurada"

    # Y a quien no lo lleva, no: exigirlo por rol no es exigirlo a todos.
    entra = svc.autenticar(
        db, email=comercial.email, contrasena="una-contrasena-larga-2026", tenant_id=tenant_id
    )
    assert entra.id == comercial.id


@pytest.mark.db
def test_un_rol_inventado_no_se_guarda(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Una regla con un rol que no existe no se cumple nunca y se lee como
    protección puesta."""
    from crmcore.errors import ErrorValidacion

    from services.identity import factores

    with pytest.raises(ErrorValidacion) as exc:
        factores.fijar_mfa_por_rol(db, tenant_id, ["director_galactico"], por=None)
    assert exc.value.error_code == "mfa.rol_desconocido"


@pytest.mark.db
def test_guardarlo_devuelve_a_quien_se_le_va_a_pedir(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Y cuántos se quedarían fuera, que es lo que hay que saber ANTES de que
    llamen el lunes."""
    from services.identity import factores

    sin = _persona(db, tenant_id, ["solo_lectura"])
    _persona(db, tenant_id, ["solo_lectura"], mfa=True)
    _persona(db, tenant_id, ["comercial"])

    panel = factores.fijar_mfa_por_rol(db, tenant_id, ["solo_lectura"], por=None)

    assert panel["mfa_obligatoria_roles"] == ["solo_lectura"]
    assert panel["exigida_sin_factor"] == 1
    exigidos = [u["email"] for u in panel["usuarios_sin_factor"] if u["exigida"]]
    assert exigidos == [sin.email]
    # Los roles de serie se pueden elegir aunque nadie los tenga definidos.
    assert "admin" in panel["roles_disponibles"]


# ── Entrar como, por soporte ─────────────────────────────────────────────


@pytest.mark.db
def test_no_se_entra_como_quien_no_es_de_esa_empresa(
    db: Any, tenant_id: UUID, monkeypatch: Any
) -> None:
    """Sin membresía, la sesión salía con los roles vacíos y no reproducía nada
    de lo que esa persona ve."""
    from services.identity.modelos import Usuario

    _con_ajustes(monkeypatch, {"suplantacion_enabled": True, "suplantacion_max_minutos": 30})
    soporte = _persona(db, tenant_id, ["admin"])
    soporte.es_plataforma = True
    ajena = Usuario(
        email=f"ajena-{uuid4().hex[:8]}@ejemplo.com",
        nombre="De otra empresa",
        hash_contrasena=svc.hashear_contrasena("una-contrasena-larga-2026"),
        activo=True,
    )
    db.add(ajena)
    db.flush()

    with pytest.raises(NoEncontrado) as exc:
        svc.suplantar(
            db,
            soporte=soporte,
            usuario_id=ajena.id,
            tenant_id=tenant_id,
            motivo="Ticket 1: no puede entrar",
        )
    assert exc.value.error_code == "auth.suplantacion_sin_membresia"


@pytest.mark.db
def test_dentro_por_soporte_me_dice_quien_y_por_que(
    db: Any, tenant_id: UUID, monkeypatch: Any
) -> None:
    """La franja de la interfaz dice «estás dentro como X por soporte: motivo»
    con lo que devuelve `/auth/me`; el motivo sale de la sesión, no del front."""
    from crmcore.authz.principal import Principal

    from services.identity.api import yo
    from services.identity.modelos import Sesion

    _con_ajustes(monkeypatch, {"suplantacion_enabled": True, "suplantacion_max_minutos": 30})
    soporte = _persona(db, tenant_id, ["admin"])
    soporte.es_plataforma = True
    objetivo = _persona(db, tenant_id, ["comercial"])

    sesion, _acceso, _refresco = svc.suplantar(
        db,
        soporte=soporte,
        usuario_id=objetivo.id,
        tenant_id=tenant_id,
        motivo="Ticket 4312: no puede cerrar una oportunidad",
    )
    assert db.get(Sesion, sesion.id).motivo_suplantacion.startswith("Ticket 4312")

    principal = Principal(
        id=objetivo.id,
        tenant_id=tenant_id,
        actor_real_id=soporte.id,
        sesion_id=sesion.id,
    )
    salida = yo(db, principal)
    assert salida.suplantado_por == soporte.id
    assert salida.suplantado_por_email == soporte.email
    assert salida.motivo_suplantacion == "Ticket 4312: no puede cerrar una oportunidad"
    assert salida.suplantacion_caduca_at is not None


# ── Por HTTP, como la pide la pantalla ───────────────────────────────────

from tests.unit.test_reverificacion_y_mfa_adaptativa import (  # noqa: E402
    _cabeceras,
    cliente_identidad,  # noqa: F401 — fixture
)


@pytest.mark.db
def test_la_pantalla_la_guarda_por_http_y_un_rol_inventado_se_rechaza(
    cliente_identidad: Any,  # noqa: F811
    tenant_id: UUID,
) -> None:
    from crmcore.http.deps import H_PERMISOS

    cabeceras = _cabeceras(tenant_id, **{H_PERMISOS: "tenant:write,user:read"})
    mal = cliente_identidad.put(
        "/api/v1/factores/obligatoria-por-rol",
        json={"roles": ["director_galactico"]},
        headers=cabeceras,
    )
    assert mal.status_code == 422, mal.text
    assert mal.json()["error_code"] == "mfa.rol_desconocido"

    bien = cliente_identidad.put(
        "/api/v1/factores/obligatoria-por-rol", json={"roles": ["admin"]}, headers=cabeceras
    )
    assert bien.status_code == 200, bien.text
    cuerpo = bien.json()
    assert cuerpo["mfa_obligatoria_roles"] == ["admin"]
    assert "exigida_sin_factor" in cuerpo and "roles_disponibles" in cuerpo
