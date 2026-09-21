"""Segregación de funciones (CRM-07.03.02.06).

SoD es la regla más vieja del control interno: quien crea un proveedor no puede
aprobar su pago. Lo que estas pruebas defienden es que el informe siga sirviendo
para algo pasado el primer trimestre, que es donde mueren casi todos:

  * **Se detecta, no se impide.** Bloquear una asignación de rol deja al
    administrador sin poder operar y sin entender por qué.
  * **La excepción se aprueba y caduca.** Sin excepciones, el informe sale
    siempre en rojo y se deja de mirar; con excepciones eternas, el rojo
    desaparece y tampoco se mira.
  * **Un conflicto exceptuado sigue saliendo, marcado.** Esconderlo haría que
    una excepción caducada pasara de «aprobado» a «no existe» sin que nadie lo
    viera.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.errors import ErrorValidacion

from services.identity import sod


def _regla(db: Any, tenant_id: UUID, **kwargs: Any) -> Any:
    base = {
        "codigo": "SOD-1",
        "nombre": "Quien crea usuarios no les asigna roles",
        "permisos_a": ["user:write"],
        "permisos_b": ["role:write"],
    }
    return sod.guardar_regla(db, tenant_id=tenant_id, **{**base, **kwargs})


def _usuario_con(db: Any, tenant_id: UUID, permisos: list[str]) -> UUID:
    """Un usuario con un rol a medida que concede esos permisos."""
    from services.identity.modelos import Membresia, RolTenant, Usuario

    usuario_id = uuid4()
    # El usuario tiene que existir: `membresias` lo referencia, y sin él la
    # prueba no comprobaría nada porque ni llegaría a insertarse.
    db.add(Usuario(id=usuario_id, email=f"{usuario_id.hex[:8]}@ejemplo.test"))
    # Se vuelca antes de la membresía: sin relación declarada, SQLAlchemy no
    # sabe que una depende de la otra y las manda en el orden que le toque.
    db.flush()
    db.add(
        RolTenant(
            tenant_id=tenant_id,
            nombre=f"rol-{usuario_id.hex[:8]}",
            permisos=permisos,
        )
    )
    db.add(
        Membresia(
            tenant_id=tenant_id,
            usuario_id=usuario_id,
            roles=[f"rol-{usuario_id.hex[:8]}"],
        )
    )
    db.flush()
    return usuario_id


@pytest.mark.db
def test_un_permiso_en_los_dos_lados_no_segrega_prohibe(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La regla se dispararía con solo tener el permiso. Si eso es lo que se
    quiere, se quita del rol; no se escribe una regla que miente."""
    with pytest.raises(ErrorValidacion) as e:
        _regla(db, tenant_id, permisos_a=["user:write"], permisos_b=["user:write"])
    assert e.value.error_code == "sod.lados_solapados"


@pytest.mark.db
def test_una_regla_con_un_solo_lado_no_es_una_regla(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    with pytest.raises(ErrorValidacion) as e:
        _regla(db, tenant_id, permisos_b=[])
    assert e.value.error_code in ("sod.regla_incompleta", "sod.lados_solapados")


@pytest.mark.db
def test_se_detecta_quien_tiene_los_dos_lados(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    _regla(db, tenant_id)
    limpio = _usuario_con(db, tenant_id, ["user:write"])
    conflicto = _usuario_con(db, tenant_id, ["user:write", "role:write"])

    salida = sod.violaciones(db, tenant_id)

    afectados = {v["usuario_id"] for v in salida["violaciones"]}
    assert str(conflicto) in afectados
    assert str(limpio) not in afectados


@pytest.mark.db
def test_un_comodin_no_esconde_el_conflicto(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un rol con `*:*` los tiene todos. Una regla que no lo viera daría por
    limpio justo al usuario más peligroso."""
    _regla(db, tenant_id)
    todopoderoso = _usuario_con(db, tenant_id, ["*:*"])

    salida = sod.violaciones(db, tenant_id)
    assert str(todopoderoso) in {v["usuario_id"] for v in salida["violaciones"]}


@pytest.mark.db
def test_una_excepcion_sin_caducidad_futura_se_rechaza(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Una excepción eterna sobrevive a la persona, al puesto y a la razón que
    la justificaba."""
    _regla(db, tenant_id)
    with pytest.raises(ErrorValidacion) as e:
        sod.aprobar_excepcion(
            db,
            tenant_id=tenant_id,
            regla_codigo="SOD-1",
            usuario_id=uuid4(),
            motivo="es todo el departamento",
            caduca_at=datetime.now(timezone.utc).date() - timedelta(days=1),
        )
    assert e.value.error_code == "sod.excepcion_ya_caducada"


@pytest.mark.db
def test_una_excepcion_sin_motivo_se_rechaza(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    _regla(db, tenant_id)
    with pytest.raises(ErrorValidacion) as e:
        sod.aprobar_excepcion(
            db,
            tenant_id=tenant_id,
            regla_codigo="SOD-1",
            usuario_id=uuid4(),
            motivo="   ",
            caduca_at=datetime.now(timezone.utc).date() + timedelta(days=30),
        )
    assert e.value.error_code == "sod.excepcion_sin_motivo"


@pytest.mark.db
def test_el_conflicto_exceptuado_sigue_saliendo_marcado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Esconderlo haría que una excepción caducada pasara de «aprobado» a «no
    existe» sin que nadie lo viera."""
    _regla(db, tenant_id)
    usuario = _usuario_con(db, tenant_id, ["user:write", "role:write"])
    sod.aprobar_excepcion(
        db,
        tenant_id=tenant_id,
        regla_codigo="SOD-1",
        usuario_id=usuario,
        motivo="una sola persona en administración",
        caduca_at=datetime.now(timezone.utc).date() + timedelta(days=30),
    )
    db.flush()

    salida = sod.violaciones(db, tenant_id)
    suyo = [v for v in salida["violaciones"] if v["usuario_id"] == str(usuario)]
    assert len(suyo) == 1
    assert suyo[0]["exceptuado"] is True
    assert salida["sin_exceptuar"] == 0
    assert salida["excepciones_vigentes"] == 1


@pytest.mark.db
def test_una_excepcion_caducada_deja_de_tapar(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from sqlalchemy import select

    _regla(db, tenant_id)
    usuario = _usuario_con(db, tenant_id, ["user:write", "role:write"])
    sod.aprobar_excepcion(
        db,
        tenant_id=tenant_id,
        regla_codigo="SOD-1",
        usuario_id=usuario,
        motivo="temporal",
        caduca_at=datetime.now(timezone.utc).date() + timedelta(days=1),
    )
    db.flush()
    # Se envejece la excepción: es lo que pasa solo con el tiempo, y lo que
    # tiene que hacer reaparecer el conflicto sin que nadie toque nada.
    fila = db.execute(select(sod.ExcepcionSoD)).scalar_one()
    fila.caduca_at = datetime.now(timezone.utc).date() - timedelta(days=1)
    db.flush()

    salida = sod.violaciones(db, tenant_id)
    assert salida["sin_exceptuar"] == 1
    assert salida["excepciones_vigentes"] == 0
