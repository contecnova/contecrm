"""La actividad tiene estados configurables; vencidas y abiertas los leen por significado.

Pedido el 09-11-2026 («todo configurable por administradores»). Una empresa
añade «Esperando respuesta» como otra forma de «en curso»: tiene que seguir
saliendo en las vencidas y en las abiertas de la cuenta, y no recibir
recordatorios de una tarea ya cancelada.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.datos import estados as est
from crmcore.errors import Conflicto

from services.party import servicio as svc
from services.party.estados import cerradas, vivas
from tests.unit.test_actividades_gestion import _tarea, _Uow

pytestmark = pytest.mark.db


def _con_esperando() -> dict[str, Any]:
    conf = est.a_configuracion(est.MAQUINAS["actividad"], de_fabrica=True)
    conf["estados"].append(
        {"clave": "esperando", "nombre": "Esperando respuesta", "significado": "en_curso"}
    )
    conf["transiciones"]["pendiente"] = [*conf["transiciones"]["pendiente"], "esperando"]
    conf["transiciones"]["esperando"] = ["completada", "cancelada"]
    return conf


@pytest.fixture
def configurado(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> Any:
    from crmcore.runtime.settings import fijar, invalidar

    fijar(db, "maquinas_de_estado", {"actividad": _con_esperando()}, ambito_id=str(tenant_id))
    invalidar()
    yield
    invalidar()


def test_un_estado_propio_vivo_sale_en_las_vencidas(
    db: Any, tenant_id: UUID, configurado: Any
) -> None:
    tarea = _tarea(
        db, tenant_id, estado="esperando", vence_at=datetime.now(timezone.utc) - timedelta(days=1)
    )
    assert "esperando" in vivas(db)
    assert tarea.esta_vencida
    assert tarea.estado_nombre == "Esperando respuesta"
    assert tarea.estado_significa == "en_curso"
    assert tarea.id in {a.id for a in svc.actividades_vencidas(db)}


def test_completar_lleva_al_estado_que_significa_completada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    tarea = _tarea(db, tenant_id)
    svc.completar_actividad(db, tarea.id, resultado="hecho", por=uuid4())
    assert tarea.estado == "completada" and tarea.estado in cerradas(db)
    # Y una cerrada ya no se asigna.
    with pytest.raises(Conflicto):
        svc.asignar_actividad(_Uow(db, tenant_id), tarea.id, usuario_id=uuid4(), por=uuid4())
