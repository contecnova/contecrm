"""Un plan de mantenimiento que sólo genera órdenes si alguien pulsa
(`CRM-07.04.03.20`, `CRM-04.04.02.01`).

Auditado el 05-10-2026. `generar_preventivas` estaba completa y probada, y tenía
**ruta y nada más**: ningún reloj detrás. Un plan mensual existe precisamente
para que nadie tenga que acordarse; si la orden sólo sale cuando alguien entra
en la pantalla y pulsa, el plan es una anotación y la máquina se revisa cuando
se rompe.

Y el síntoma es el peor de todos: no hay error. El panel enseña los planes, las
fechas de vencimiento salen bien calculadas, y no hay órdenes.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo

from services.service import campo


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _activo(uow: UnidadDeTrabajo) -> Any:
    """El plan cuelga de un activo instalado de verdad: la clave ajena lo exige,
    y es correcto — un plan de mantenimiento sin máquina no mantiene nada."""
    from services.service.activos import ActivoInstalado

    fila = ActivoInstalado(
        tenant_id=uow.tenant_id, nombre=f"Máquina {uuid4().hex[:6]}", cuenta_id=uuid4()
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def _plan(uow: UnidadDeTrabajo, *, vence: date) -> Any:
    fila = campo.PlanPreventivo(
        tenant_id=uow.tenant_id,
        nombre=f"Revisión {uuid4().hex[:6]}",
        activo_id=_activo(uow).id,
        cada_dias=30,
        proxima_fecha=vence,
        activo=True,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def test_lo_vencido_genera_su_orden(uow: UnidadDeTrabajo) -> None:
    _plan(uow, vence=date.today() - timedelta(days=1))
    salida = campo.generar_preventivas(uow)
    assert salida["creadas"], "el plan venció y no ha salido ninguna orden"


def test_un_plan_desatendido_no_genera_seis_ordenes_iguales(uow: UnidadDeTrabajo) -> None:
    """Lo que se hace con seis órdenes idénticas es cerrarlas todas sin mirar,
    y entonces se cierra también la que había que atender."""
    _plan(uow, vence=date.today() - timedelta(days=180))
    primera = campo.generar_preventivas(uow)
    segunda = campo.generar_preventivas(uow)
    assert len(primera["creadas"]) == 1
    assert not segunda["creadas"], "ha creado una segunda orden con la primera abierta"


def test_el_servicio_lo_corre_solo() -> None:
    """**Esta es la del agujero.**

    Con ruta y sin reloj, el plan mensual depende de que alguien se acuerde — y
    si alguien se acuerda, el plan sobra.
    """
    import os

    from crmcore.config import limpiar_cache_settings

    previo = os.environ.get("SERVICE_NAME")
    os.environ["SERVICE_NAME"] = "service"
    limpiar_cache_settings()
    try:
        import importlib

        main = importlib.import_module("services.service.main")
        nombres = [t.nombre for t in main._tareas()]
    finally:
        if previo is None:
            os.environ.pop("SERVICE_NAME", None)
        else:
            os.environ["SERVICE_NAME"] = previo
        limpiar_cache_settings()

    assert "service.preventivas" in nombres, (
        "el servicio no genera las preventivas solo: el plan depende de que "
        "alguien pulse, y si alguien pulsa el plan sobra"
    )
