"""La rotación del refresco detecta la copia robada (FUN-A-3, auditoría 13-11-2026).

La documentación de `/auth/refresh` prometía que presentar un refresco ya rotado
revoca todas las sesiones. No pasaba: el token rotado no encontraba fila y salía
«no válido» sin revocar nada; y donde sí se revocaba, la excepción deshacía la
transacción y la revocación con ella. Además, dos renovaciones a la vez se
pisaban.

Ahora se guarda el refresco anterior: presentarlo fuera del margen de gracia
revoca todo y queda escrito; dentro del margen —dos pestañas renovando a la
vez— se rechaza sin revocar.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest
from crmcore.errors import NoAutenticado


@pytest.fixture
def sesion_viva(db: Any, tenant_id: UUID) -> tuple[Any, str]:
    from services.identity import servicio as svc
    from services.identity.modelos import Membresia, Usuario

    usuario = Usuario(email="rota@empresa.example", nombre="Rota", activo=True)
    db.add(usuario)
    db.flush()
    db.add(Membresia(tenant_id=tenant_id, usuario_id=usuario.id, activa=True))
    db.flush()
    sesion, _, refresco = svc.crear_sesion(
        db, usuario=usuario, tenant_id=tenant_id, ip="", user_agent=""
    )
    db.flush()
    return sesion, refresco


def _vivas(db: Any, usuario_id: UUID) -> int:
    import sqlalchemy as sa

    from services.identity.modelos import Sesion

    return len(
        db.execute(
            sa.select(Sesion).where(Sesion.usuario_id == usuario_id, Sesion.revocada_at.is_(None))
        )
        .scalars()
        .all()
    )


def test_rotar_entrega_otro_y_el_nuevo_vale(db: Any, sesion_viva: tuple[Any, str]) -> None:
    from services.identity import servicio as svc

    sesion, primero = sesion_viva
    _, segundo = svc.renovar(db, primero)
    db.flush()  # cada renovación es una petición con su commit
    assert segundo != primero
    _, tercero = svc.renovar(db, segundo)
    assert tercero not in (primero, segundo)


def test_dos_renovaciones_a_la_vez_no_revocan_nada(db: Any, sesion_viva: tuple[Any, str]) -> None:
    """Dentro del margen: la otra pestaña ya tiene el nuevo en la cookie."""
    from services.identity import servicio as svc

    sesion, primero = sesion_viva
    svc.renovar(db, primero)
    db.flush()  # cada renovación es una petición con su commit
    with pytest.raises(NoAutenticado) as fallo:
        svc.renovar(db, primero)
    assert fallo.value.error_code == "auth.refresco_ya_rotado"
    assert _vivas(db, sesion.usuario_id) == 1


def test_un_refresco_rotado_fuera_del_margen_revoca_todo_y_queda(
    db: Any, sesion_viva: tuple[Any, str]
) -> None:
    """La copia robada: se revocan TODAS las sesiones y no se deshace con el error."""
    from services.identity import servicio as svc

    sesion, primero = sesion_viva
    svc.renovar(db, primero)
    sesion.refresco_rotado_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.flush()

    with pytest.raises(NoAutenticado) as fallo:
        svc.renovar(db, primero)
    assert fallo.value.error_code == "auth.sesion_caducada"
    db.expire_all()
    assert _vivas(db, sesion.usuario_id) == 0


def test_un_refresco_que_nunca_existio_no_vale(db: Any, sesion_viva: tuple[Any, str]) -> None:
    from services.identity import servicio as svc

    with pytest.raises(NoAutenticado) as fallo:
        svc.renovar(db, "esto-no-es-ningun-refresco")
    assert fallo.value.error_code == "auth.refresco_invalido"
