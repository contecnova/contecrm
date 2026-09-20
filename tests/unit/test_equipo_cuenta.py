"""Equipo de cuenta con roles (CRM-01.01.01.10).

El propietario es uno; el equipo es quien más trabaja la cuenta. Sin esta tabla,
el técnico que lleva tres años atendiendo a un cliente no aparece en ningún
sitio y su conocimiento se pierde cuando cambia el comercial.

El modelo existía con `rol`, `acceso`, `desde` y `hasta`. No había API, y —lo
que era peor— **la vigencia y el acceso no los usaba nadie**: un miembro que
salió del equipo hace un año seguía viendo la cuenta, y uno dado de alta con
acceso de escritura solo podía leer.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.authz.comparticion import visibilidad_de
from crmcore.errors import ErrorValidacion, NoEncontrado

from services.party import servicio as svc
from services.party.modelos import Cuenta, MiembroEquipoCuenta


class _Uow:
    def __init__(self, db: Any, tenant_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.emitidos: list[dict[str, Any]] = []

    def emitir(self, tipo: str, *, subject: Any, data: Any, **extra: Any) -> None:
        self.emitidos.append({"tipo": tipo, "data": data})


def _cuenta(db: Any, tenant_id: UUID) -> Cuenta:
    fila = Cuenta(tenant_id=tenant_id, nombre="ACME", clave_canonica="acme")
    db.add(fila)
    db.flush()
    return fila


# ── Alta y validación ─────────────────────────────────────────────────────


@pytest.mark.db
def test_añadir_a_alguien_al_equipo(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    uow = _Uow(db, tenant_id)
    cuenta = _cuenta(db, tenant_id)
    miembro = svc.añadir_al_equipo(
        uow, cuenta_id=cuenta.id, usuario_id=uuid4(), rol="tecnico", acceso="escritura"
    )
    assert miembro.rol == "tecnico" and miembro.acceso == "escritura"


@pytest.mark.db
def test_el_alta_emite_evento_porque_da_visibilidad(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Pertenecer al equipo da visibilidad sobre la cuenta. Quien audite quién
    puede ver qué necesita este hecho, y sin evento solo constaría en una tabla
    que nadie mira."""
    uow = _Uow(db, tenant_id)
    cuenta = _cuenta(db, tenant_id)
    svc.añadir_al_equipo(uow, cuenta_id=cuenta.id, usuario_id=uuid4(), rol="kam")

    assert uow.emitidos[-1]["tipo"] == "account.team.added"


@pytest.mark.db
def test_un_rol_inventado_se_rechaza(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Con texto libre, cada comercial escribe el suyo y a los tres meses hay
    «tecnico», «Técnico» y «tec.» conviviendo — y «¿qué cuentas llevo como
    técnico?» deja de tener respuesta."""
    uow = _Uow(db, tenant_id)
    cuenta = _cuenta(db, tenant_id)
    with pytest.raises(ErrorValidacion, match="Rol de equipo"):
        svc.añadir_al_equipo(uow, cuenta_id=cuenta.id, usuario_id=uuid4(), rol="jefazo")


@pytest.mark.db
def test_una_vigencia_al_reves_se_rechaza(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """No da error al guardar y deja a la persona sin ver nada nunca. Se rechaza
    donde se puede explicar."""
    uow = _Uow(db, tenant_id)
    cuenta = _cuenta(db, tenant_id)
    with pytest.raises(ErrorValidacion, match="anterior"):
        svc.añadir_al_equipo(
            uow,
            cuenta_id=cuenta.id,
            usuario_id=uuid4(),
            rol="kam",
            desde=date(2026, 6, 1),
            hasta=date(2026, 1, 1),
        )


@pytest.mark.db
def test_repetir_el_alta_renueva_en_vez_de_fallar(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es lo que hace quien renueva a alguien en el equipo, y obligarle a borrar
    y volver a crear pierde la fecha de alta original."""
    uow = _Uow(db, tenant_id)
    cuenta = _cuenta(db, tenant_id)
    quien = uuid4()
    primera = svc.añadir_al_equipo(
        uow, cuenta_id=cuenta.id, usuario_id=quien, rol="kam", hasta=date(2026, 1, 1)
    )
    segunda = svc.añadir_al_equipo(
        uow, cuenta_id=cuenta.id, usuario_id=quien, rol="kam", hasta=date(2027, 1, 1)
    )

    assert primera.id == segunda.id
    assert segunda.hasta == date(2027, 1, 1)
    assert db.query(MiembroEquipoCuenta).count() == 1


@pytest.mark.db
def test_el_equipo_de_una_cuenta_que_no_existe_da_404(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    uow = _Uow(db, tenant_id)
    with pytest.raises(NoEncontrado):
        svc.añadir_al_equipo(uow, cuenta_id=uuid4(), usuario_id=uuid4(), rol="kam")


# ── Vigencia ──────────────────────────────────────────────────────────────


@pytest.mark.db
def test_una_pertenencia_caducada_deja_de_dar_visibilidad(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Era el fallo: el modelo tenía `hasta` desde el principio y nadie lo
    miraba, así que quien salió del equipo hace un año seguía viendo la cuenta.
    Una pertenencia con fecha de fin que no caduca no es temporal, es permanente
    con una fecha decorativa."""
    from crmcore.authz.principal import Principal

    from services.party.visibilidad import equipos

    uow = _Uow(db, tenant_id)
    cuenta = _cuenta(db, tenant_id)
    quien = uuid4()
    svc.añadir_al_equipo(
        uow,
        cuenta_id=cuenta.id,
        usuario_id=quien,
        rol="tecnico",
        hasta=date.today() - timedelta(days=1),
    )
    db.flush()

    principal = Principal(id=quien, tenant_id=tenant_id)
    assert equipos(db, principal, "cuenta") == {}


@pytest.mark.db
def test_una_pertenencia_futura_todavia_no_da_visibilidad(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Dar de alta al que entra el mes que viene es normal; que vea la cuenta
    desde hoy, no."""
    from crmcore.authz.principal import Principal

    from services.party.visibilidad import equipos

    uow = _Uow(db, tenant_id)
    cuenta = _cuenta(db, tenant_id)
    quien = uuid4()
    svc.añadir_al_equipo(
        uow,
        cuenta_id=cuenta.id,
        usuario_id=quien,
        rol="kam",
        desde=date.today() + timedelta(days=30),
    )
    db.flush()

    assert equipos(db, Principal(id=quien, tenant_id=tenant_id), "cuenta") == {}


@pytest.mark.db
def test_el_listado_del_equipo_enseña_los_no_vigentes_salvo_que_se_pida(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Quien administra el equipo necesita ver al que entra el mes que viene y
    al que salió ayer, o no puede corregir una fecha mal puesta."""
    uow = _Uow(db, tenant_id)
    cuenta = _cuenta(db, tenant_id)
    svc.añadir_al_equipo(uow, cuenta_id=cuenta.id, usuario_id=uuid4(), rol="kam")
    svc.añadir_al_equipo(
        uow,
        cuenta_id=cuenta.id,
        usuario_id=uuid4(),
        rol="tecnico",
        hasta=date.today() - timedelta(days=1),
    )
    db.flush()

    assert len(svc.equipo_de_cuenta(db, cuenta.id)) == 2
    assert len(svc.equipo_de_cuenta(db, cuenta.id, solo_vigentes=True)) == 1


# ── Acceso ────────────────────────────────────────────────────────────────


@pytest.mark.db
def test_el_equipo_con_acceso_de_escritura_puede_escribir(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El modelo guardaba `acceso` desde el principio y la visibilidad lo
    ignoraba: un miembro dado de alta con escritura solo podía leer, y nadie
    entendía por qué el campo no hacía nada."""
    uow = _Uow(db, tenant_id)
    cuenta = _cuenta(db, tenant_id)
    quien = uuid4()
    svc.añadir_al_equipo(uow, cuenta_id=cuenta.id, usuario_id=quien, rol="kam", acceso="escritura")
    db.flush()

    veredicto = visibilidad_de(
        db,
        tenant_id=tenant_id,
        usuario_id=quien,
        objeto="cuenta",
        registro=cuenta.a_dict(),
        equipos={cuenta.id: "escritura"},
    )
    assert veredicto.puede_leer and veredicto.puede_escribir
    assert any("equipo" in m for m in veredicto.motivos)


@pytest.mark.db
def test_el_equipo_de_solo_lectura_no_puede_escribir(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    cuenta = _cuenta(db, tenant_id)
    veredicto = visibilidad_de(
        db,
        tenant_id=tenant_id,
        usuario_id=uuid4(),
        objeto="cuenta",
        registro=cuenta.a_dict(),
        equipos={cuenta.id: "lectura"},
    )
    assert veredicto.puede_leer and not veredicto.puede_escribir


@pytest.mark.db
def test_con_dos_roles_gana_el_acceso_mas_amplio(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Alguien puede ser KAM y técnico de la misma cuenta. Las vías de
    compartición suman, nunca restan."""
    from crmcore.authz.principal import Principal

    from services.party.visibilidad import equipos

    uow = _Uow(db, tenant_id)
    cuenta = _cuenta(db, tenant_id)
    quien = uuid4()
    svc.añadir_al_equipo(uow, cuenta_id=cuenta.id, usuario_id=quien, rol="kam", acceso="lectura")
    svc.añadir_al_equipo(
        uow, cuenta_id=cuenta.id, usuario_id=quien, rol="tecnico", acceso="escritura"
    )
    db.flush()

    assert equipos(db, Principal(id=quien, tenant_id=tenant_id), "cuenta") == {
        cuenta.id: "escritura"
    }


# ── Baja ──────────────────────────────────────────────────────────────────


@pytest.mark.db
def test_quitar_a_alguien_del_equipo(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    uow = _Uow(db, tenant_id)
    cuenta = _cuenta(db, tenant_id)
    miembro = svc.añadir_al_equipo(uow, cuenta_id=cuenta.id, usuario_id=uuid4(), rol="kam")
    db.flush()

    svc.quitar_del_equipo(uow, cuenta_id=cuenta.id, miembro_id=miembro.id)

    assert db.query(MiembroEquipoCuenta).count() == 0
    assert uow.emitidos[-1]["tipo"] == "account.team.removed"


@pytest.mark.db
def test_no_se_puede_quitar_a_alguien_del_equipo_de_otra_cuenta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El identificador de la ruta no es decorativo: sin esta comprobación se
    podría sacar a alguien del equipo de una cuenta pasando por la ruta de
    otra."""
    uow = _Uow(db, tenant_id)
    una = _cuenta(db, tenant_id)
    otra = Cuenta(tenant_id=tenant_id, nombre="Otra", clave_canonica="otra")
    db.add(otra)
    db.flush()
    miembro = svc.añadir_al_equipo(uow, cuenta_id=una.id, usuario_id=uuid4(), rol="kam")
    db.flush()

    with pytest.raises(NoEncontrado):
        svc.quitar_del_equipo(uow, cuenta_id=otra.id, miembro_id=miembro.id)


# ── Y lo que de verdad importa: se ve en el listado ───────────────────────


@pytest.mark.db
def test_estar_en_el_equipo_hace_que_la_cuenta_salga_en_el_listado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es el punto de todo: el técnico ve la cuenta que atiende sin que nadie
    tenga que compartírsela a mano cada vez que cambia el comercial."""
    from crmcore.authz.principal import Principal
    from crmcore.authz.visibilidad import aplicar_visibilidad
    from sqlalchemy import select

    import services.party.visibilidad  # noqa: F401 — registra el resolutor

    uow = _Uow(db, tenant_id)
    mia = _cuenta(db, tenant_id)
    ajena = Cuenta(tenant_id=tenant_id, nombre="Ajena", clave_canonica="ajena", owner_id=uuid4())
    db.add(ajena)
    db.flush()

    quien = uuid4()
    svc.añadir_al_equipo(uow, cuenta_id=mia.id, usuario_id=quien, rol="tecnico")
    db.flush()

    principal = Principal(id=quien, tenant_id=tenant_id, permisos=frozenset({"account:read"}))
    consulta = aplicar_visibilidad(
        select(Cuenta),
        Cuenta,
        db=db,
        principal=principal,
        objeto="cuenta",
        permiso_ver_todo="account:admin",
    )
    assert {c.nombre for c in db.execute(consulta).scalars()} == {"ACME"}
