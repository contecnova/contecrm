"""La compartición, aplicada en los listados (CRM-00.05.02.04).

Las reglas existían, se explicaban y se podían consultar para un registro
concreto. Lo que no pasaba es lo único que el usuario nota: **`GET /accounts`
seguía enseñándolo todo**. Las reglas vivían en el esquema de `identity` y los
registros en el de `party`; ningún servicio lee el de otro, así que el listado no
podía filtrar por ellas ni aunque alguien lo intentara.

Estas pruebas defienden tres cosas:

  * Que el listado filtra, por cada una de las cinco vías.
  * Que **el listado y la ficha dicen lo mismo**. Son dos implementaciones de la
    misma regla —una en SQL y otra en Python— y divergen el día que alguien toca
    una. Cuando eso pasa, el listado enseña un registro que la ficha luego niega.
  * Que ante la duda **no se enseña**.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.authz.comparticion import (
    ComparticionManual,
    ReglaComparticion,
    compartir,
    filtro_visibilidad,
    visibilidad_de,
)
from crmcore.authz.principal import Principal
from crmcore.authz.visibilidad import aplicar_visibilidad
from sqlalchemy import select

from services.party.modelos import Cuenta, MiembroEquipoCuenta


def _cuenta(db: Any, tenant_id: UUID, nombre: str, **extra: Any) -> Cuenta:
    fila = Cuenta(tenant_id=tenant_id, nombre=nombre, clave_canonica=nombre.lower(), **extra)
    db.add(fila)
    db.flush()
    return fila


def _quien(tenant_id: UUID, usuario_id: UUID, **extra: Any) -> Principal:
    return Principal(
        id=usuario_id,
        tenant_id=tenant_id,
        permisos=frozenset({"account:read"}),
        **extra,
    )


def _visibles(db: Any, principal: Principal) -> set[str]:
    consulta = aplicar_visibilidad(
        select(Cuenta).where(Cuenta.deleted_at.is_(None)),
        Cuenta,
        db=db,
        principal=principal,
        objeto="cuenta",
        permiso_ver_todo="account:admin",
    )
    return {c.nombre for c in db.execute(consulta).scalars()}


# ── Las cinco vías, en el listado ─────────────────────────────────────────


@pytest.mark.db
def test_por_defecto_solo_se_ven_las_propias(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es el caso que estaba roto: sin filtro, este listado devolvía las dos."""
    yo = uuid4()
    _cuenta(db, tenant_id, "Mia", owner_id=yo)
    _cuenta(db, tenant_id, "Ajena", owner_id=uuid4())
    db.flush()

    assert _visibles(db, _quien(tenant_id, yo)) == {"Mia"}


@pytest.mark.db
def test_lo_compartido_a_mano_aparece(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    yo = uuid4()
    ajena = _cuenta(db, tenant_id, "Ajena", owner_id=uuid4())
    db.flush()
    compartir(
        db,
        tenant_id=tenant_id,
        objeto="cuenta",
        registro_id=ajena.id,
        usuario_id=yo,
        acceso="lectura",
        motivo="cubre vacaciones",
    )
    db.flush()

    assert _visibles(db, _quien(tenant_id, yo)) == {"Ajena"}


@pytest.mark.db
def test_una_comparticion_revocada_deja_de_verse(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Revocar que no quita del listado es peor que no poder revocar: el
    administrador cree que ha cerrado el acceso y no lo ha cerrado."""
    from crmcore.authz.comparticion import revocar

    yo = uuid4()
    ajena = _cuenta(db, tenant_id, "Ajena", owner_id=uuid4())
    db.flush()
    fila = compartir(
        db,
        tenant_id=tenant_id,
        objeto="cuenta",
        registro_id=ajena.id,
        usuario_id=yo,
        acceso="lectura",
        motivo="temporal",
    )
    db.flush()
    assert _visibles(db, _quien(tenant_id, yo)) == {"Ajena"}

    revocar(db, fila.id)
    db.flush()
    assert _visibles(db, _quien(tenant_id, yo)) == set()


@pytest.mark.db
def test_una_comparticion_caducada_deja_de_verse(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La caducidad es la mitad del valor de compartir a mano: sin ella, cada
    sustitución de vacaciones deja un acceso permanente que nadie revisa."""
    from datetime import date, timedelta

    yo = uuid4()
    ajena = _cuenta(db, tenant_id, "Ajena", owner_id=uuid4())
    db.flush()
    db.add(
        ComparticionManual(
            tenant_id=tenant_id,
            objeto="cuenta",
            registro_id=ajena.id,
            usuario_id=yo,
            acceso="lectura",
            hasta=date.today() - timedelta(days=1),
        )
    )
    db.flush()

    assert _visibles(db, _quien(tenant_id, yo)) == set()


@pytest.mark.db
def test_el_equipo_de_la_cuenta_la_ve(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """El técnico que lleva tres años atendiendo a un cliente tiene que verlo
    aunque el comercial haya cambiado."""
    import services.party.visibilidad  # noqa: F401 — registra el resolutor

    yo = uuid4()
    ajena = _cuenta(db, tenant_id, "Ajena", owner_id=uuid4())
    db.flush()
    db.add(
        MiembroEquipoCuenta(tenant_id=tenant_id, cuenta_id=ajena.id, usuario_id=yo, rol="tecnico")
    )
    db.flush()

    assert _visibles(db, _quien(tenant_id, yo)) == {"Ajena"}


@pytest.mark.db
def test_una_regla_por_criterio_comparte_lo_que_cumple(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """«Todas las cuentas activas con el equipo de Bilbao». Es la vía que sin
    filtro en SQL era imposible de aplicar a un listado."""
    yo = uuid4()
    _cuenta(db, tenant_id, "Activa", owner_id=uuid4(), estado="activa")
    _cuenta(db, tenant_id, "Prospecto", owner_id=uuid4(), estado="prospecto")
    db.add(
        ReglaComparticion(
            tenant_id=tenant_id,
            nombre="Las activas, al equipo comercial",
            objeto="cuenta",
            destino_tipo="rol",
            destino_id="comercial",
            acceso="lectura",
            condiciones=[{"atributo": "registro.estado", "operador": "=", "valor": "activa"}],
            activa=True,
        )
    )
    db.flush()

    assert _visibles(db, _quien(tenant_id, yo, roles=frozenset({"comercial"}))) == {"Activa"}
    # Y a quien no tiene ese rol, la regla no le alcanza.
    assert _visibles(db, _quien(tenant_id, yo, roles=frozenset({"soporte"}))) == set()


@pytest.mark.db
def test_una_regla_desactivada_no_comparte(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    yo = uuid4()
    _cuenta(db, tenant_id, "Activa", owner_id=uuid4(), estado="activa")
    db.add(
        ReglaComparticion(
            tenant_id=tenant_id,
            nombre="Apagada",
            objeto="cuenta",
            destino_tipo="rol",
            destino_id="comercial",
            acceso="lectura",
            condiciones=[{"atributo": "registro.estado", "operador": "=", "valor": "activa"}],
            activa=False,
        )
    )
    db.flush()

    assert _visibles(db, _quien(tenant_id, yo, roles=frozenset({"comercial"}))) == set()


# ── El listado y la ficha dicen lo mismo ──────────────────────────────────


@pytest.mark.db
def test_el_listado_coincide_con_el_veredicto_de_cada_ficha(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Son dos implementaciones de la misma regla —una en SQL y otra en Python—
    y divergen el día que alguien toca una. Cuando eso pasa, el listado enseña
    un registro que la ficha luego niega, o al revés, y el usuario deja de
    fiarse de los dos.
    """
    import services.party.visibilidad  # noqa: F401

    yo = uuid4()
    _cuenta(db, tenant_id, "Propia", owner_id=yo, estado="activa")
    compartida = _cuenta(db, tenant_id, "Compartida", owner_id=uuid4(), estado="prospecto")
    de_equipo = _cuenta(db, tenant_id, "DeEquipo", owner_id=uuid4(), estado="prospecto")
    por_regla = _cuenta(db, tenant_id, "PorRegla", owner_id=uuid4(), estado="activa")
    _cuenta(db, tenant_id, "Invisible", owner_id=uuid4(), estado="prospecto")
    db.flush()

    compartir(
        db,
        tenant_id=tenant_id,
        objeto="cuenta",
        registro_id=compartida.id,
        usuario_id=yo,
        acceso="lectura",
        motivo="x",
    )
    db.add(
        MiembroEquipoCuenta(
            tenant_id=tenant_id, cuenta_id=de_equipo.id, usuario_id=yo, rol="tecnico"
        )
    )
    db.add(
        ReglaComparticion(
            tenant_id=tenant_id,
            nombre="Las activas",
            objeto="cuenta",
            destino_tipo="rol",
            destino_id="comercial",
            acceso="lectura",
            condiciones=[{"atributo": "registro.estado", "operador": "=", "valor": "activa"}],
            activa=True,
        )
    )
    db.flush()

    principal = _quien(tenant_id, yo, roles=frozenset({"comercial"}))
    del_listado = _visibles(db, principal)

    # Mapa y no conjunto: el equipo dice además QUÉ acceso concede.
    equipos = {de_equipo.id: "lectura"}
    de_la_ficha = set()
    for cuenta in db.execute(select(Cuenta)).scalars():
        veredicto = visibilidad_de(
            db,
            tenant_id=tenant_id,
            usuario_id=yo,
            objeto="cuenta",
            registro={
                **cuenta.a_dict(),
                "_usuario": {"roles": ["comercial"], "business_unit_id": ""},
            },
            equipos=equipos,
        )
        if veredicto.puede_leer:
            de_la_ficha.add(cuenta.nombre)

    assert del_listado == de_la_ficha
    assert del_listado == {"Propia", "Compartida", "DeEquipo", "PorRegla"}
    assert por_regla.nombre in del_listado


# ── Ante la duda, no se enseña ────────────────────────────────────────────


@pytest.mark.db
def test_sin_identidad_no_se_enseña_nada(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Quien llame sin autenticar no debería haber llegado aquí; si llega, no
    ve nada en vez de verlo todo."""
    from crmcore.authz.principal import ANONIMO

    _cuenta(db, tenant_id, "Algo", owner_id=uuid4())
    db.flush()
    assert _visibles(db, ANONIMO) == set()


@pytest.mark.db
def test_un_fallo_al_resolver_filtra_en_vez_de_abrir(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    """Un error resolviendo la visibilidad devuelve una consulta que no
    encuentra nada, no una sin filtrar. En visibilidad, ante la duda, no."""
    from crmcore.authz import visibilidad as modulo

    _cuenta(db, tenant_id, "Algo", owner_id=uuid4())
    db.flush()

    def _revienta(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("la tabla de reglas no responde")

    monkeypatch.setattr("crmcore.authz.comparticion.filtro_visibilidad", _revienta)
    assert _visibles(db, _quien(tenant_id, uuid4())) == set()
    _ = modulo


@pytest.mark.db
def test_quien_administra_el_objeto_no_se_filtra(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un administrador que ve media lista no puede administrar nada, y darle
    una compartición sobre todo convertiría la auditoría en ruido."""
    _cuenta(db, tenant_id, "Una", owner_id=uuid4())
    _cuenta(db, tenant_id, "Otra", owner_id=uuid4())
    db.flush()

    admin = Principal(
        id=uuid4(), tenant_id=tenant_id, permisos=frozenset({"account:read", "account:admin"})
    )
    assert _visibles(db, admin) == {"Una", "Otra"}


@pytest.mark.db
def test_la_comparticion_no_cruza_el_tenant(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Una regla de otro tenant no puede compartir aquí: sería la fuga más
    difícil de ver, porque el registro es del tenant correcto."""
    yo = uuid4()
    _cuenta(db, tenant_id, "Mia", owner_id=uuid4(), estado="activa")
    db.add(
        ReglaComparticion(
            tenant_id=otro_tenant_id,
            nombre="Regla del vecino",
            objeto="cuenta",
            destino_tipo="rol",
            destino_id="comercial",
            acceso="lectura",
            condiciones=[],
            activa=True,
        )
    )
    db.flush()

    assert _visibles(db, _quien(tenant_id, yo, roles=frozenset({"comercial"}))) == set()


# ── La traducción a SQL ───────────────────────────────────────────────────


def test_lo_que_no_se_puede_traducir_devuelve_none() -> None:
    """Nunca se inventa una traducción aproximada: una condición traducida «casi
    igual» produce un listado que casi acierta, y eso no se detecta mirándolo."""
    from crmcore.authz.abac import a_sql

    columna = Cuenta.estado
    assert a_sql(columna, "=", "activa") is not None
    assert a_sql(columna, "en", ["a", "b"]) is not None
    # Un valor que apunta a otro atributo del ámbito: en SQL no hay ámbito.
    assert a_sql(columna, "=", "@usuario.pais") is None
    # `contiene` depende del tipo de la columna y traducirlo mal es peor.
    assert a_sql(columna, "contiene", "x") is None
    assert a_sql(columna, "operador_inventado", "x") is None


@pytest.mark.db
def test_una_regla_sin_condiciones_comparte_todo_el_objeto(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es legítimo —«todas las cuentas con el equipo de dirección»— y por eso se
    permite; el módulo lo anota porque es la forma más fácil de abrir de más sin
    darse cuenta."""
    yo = uuid4()
    _cuenta(db, tenant_id, "Una", owner_id=uuid4())
    _cuenta(db, tenant_id, "Otra", owner_id=uuid4())
    db.add(
        ReglaComparticion(
            tenant_id=tenant_id,
            nombre="Todo a dirección",
            objeto="cuenta",
            destino_tipo="rol",
            destino_id="direccion",
            acceso="lectura",
            condiciones=[],
            activa=True,
        )
    )
    db.flush()

    assert _visibles(db, _quien(tenant_id, yo, roles=frozenset({"direccion"}))) == {"Una", "Otra"}


@pytest.mark.db
def test_un_objeto_sin_propietario_no_se_filtra(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La visibilidad la decide el permiso, y ya está comprobado antes de llegar
    aquí. Filtrar por un `owner_id` que no existe dejaría la lista vacía."""
    from services.party.modelos import Direccion

    assert (
        filtro_visibilidad(
            db,
            Direccion,
            tenant_id=tenant_id,
            usuario_id=uuid4(),
            objeto="direccion",
        )
        is None
    )
