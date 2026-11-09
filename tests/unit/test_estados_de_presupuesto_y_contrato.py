"""Presupuesto y contrato con estados configurables, y la aprobación que cierra el circuito.

Pedido el 09-11-2026 y decidido por formulario: además de nombre, color y
orden, **estados propios**. Las acciones con efectos —enviar, aceptar, la
versión nueva, renovar— siguen teniendo su camino y reconocen los estados
propios por lo que significan.

Y un defecto que salió al hacerlo: un presupuesto parado por la matriz de
descuentos se quedaba en «en aprobación» para siempre —el aviso salía y nadie
abría la aprobación—. Ahora orchestrator la abre y sales aplica lo decidido.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.datos import estados as est
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion
from crmcore.fechas import hoy

from services.sales import presupuestos as pre
from services.sales import servicio as svc
from services.sales.consumidores import consumir_aprobacion
from tests.unit.test_cotizacion import caja, uow  # noqa: F401

pytestmark = pytest.mark.db


def _decision(tenant_id: UUID, presupuesto_id: UUID, estado: str, **extra: Any) -> Any:
    return SimpleNamespace(
        tipo="approval.decided",
        tenant_id=str(tenant_id),
        data={
            "solicitud_id": str(uuid4()),
            "objeto": "presupuesto",
            "objeto_id": str(presupuesto_id),
            "estado": estado,
            **extra,
        },
    )


def test_aprobado_ya_se_puede_enviar(
    uow: UnidadDeTrabajo,  # noqa: F811
    caja: Any,  # noqa: F811
    contexto_tenant: UUID,
) -> None:
    fila = pre.crear(uow, lineas=[{"producto_id": str(caja.id), "descuento_pct": 40}])
    assert pre.enviar(uow, fila.id)["estado"] == "en_aprobacion"
    uow.db.flush()

    asyncio.run(consumir_aprobacion(_decision(uow.tenant_id, fila.id, "aprobada")))
    uow.db.refresh(fila)
    assert fila.estado == "aprobado"
    # Aprobado, enviar ya no lo vuelve a parar.
    assert pre.enviar(uow, fila.id)["enviado"] is True


def test_sin_quien_lo_apruebe_vuelve_a_borrador_y_lo_dice(
    uow: UnidadDeTrabajo,  # noqa: F811
    caja: Any,  # noqa: F811
    contexto_tenant: UUID,
) -> None:
    fila = pre.crear(uow, lineas=[{"producto_id": str(caja.id), "descuento_pct": 40}])
    pre.enviar(uow, fila.id)
    uow.db.flush()
    asyncio.run(
        consumir_aprobacion(
            _decision(uow.tenant_id, fila.id, "sin_aprobadores", motivo="Nadie por encima")
        )
    )
    uow.db.refresh(fila)
    assert fila.estado == "borrador"
    assert "No hay quién lo apruebe" in fila.motivo_aprobacion


def test_lo_que_tiene_su_accion_no_se_hace_desde_el_estado(
    uow: UnidadDeTrabajo,  # noqa: F811
    caja: Any,  # noqa: F811
) -> None:
    fila = pre.crear(uow, lineas=[{"producto_id": str(caja.id)}], cuenta_id=uuid4())
    pre.enviar(uow, fila.id)
    with pytest.raises(Conflicto) as exc:
        svc.cambiar_estado(uow, "presupuesto", fila, estado="aceptado")
    assert exc.value.error_code == "estados.con_su_camino"
    # Que el cliente lo rechace sí, con su motivo.
    with pytest.raises(ErrorValidacion):
        svc.cambiar_estado(uow, "presupuesto", fila, estado="rechazado")
    svc.cambiar_estado(uow, "presupuesto", fila, estado="rechazado", motivo="Precio")
    assert fila.estado == "rechazado"


def test_un_estado_propio_de_enviado_se_puede_aceptar(
    db: Any,
    tenant_id: UUID,
    contexto_tenant: UUID,
    uow: UnidadDeTrabajo,  # noqa: F811
    caja: Any,  # noqa: F811
) -> None:
    from crmcore.runtime.settings import fijar, invalidar

    conf = est.a_configuracion(est.MAQUINAS["presupuesto"], de_fabrica=True)
    conf["estados"].append(
        {"clave": "en_negociacion", "nombre": "En negociación", "significado": "enviado"}
    )
    conf["transiciones"]["enviado"] = [*conf["transiciones"]["enviado"], "en_negociacion"]
    conf["transiciones"]["en_negociacion"] = ["aceptado", "rechazado"]
    fijar(db, "maquinas_de_estado", {"presupuesto": conf}, ambito_id=str(tenant_id))
    invalidar()
    try:
        fila = pre.crear(uow, lineas=[{"producto_id": str(caja.id)}], cuenta_id=uuid4())
        pre.enviar(uow, fila.id)
        svc.cambiar_estado(uow, "presupuesto", fila, estado="en_negociacion")
        pedido = pre.aceptar(uow, fila.id)
        assert pedido is not None and fila.estado == "aceptado"
    finally:
        invalidar()


def test_un_contrato_se_suspende_y_termina_con_motivo(
    uow: UnidadDeTrabajo,  # noqa: F811
) -> None:
    contrato = pre.crear_contrato(uow, cuenta_id=uuid4(), inicio=hoy(uow.db))
    assert contrato.estado == "vigente"
    with pytest.raises(ErrorValidacion):
        svc.cambiar_estado(uow, "contrato", contrato, estado="suspendido")
    svc.cambiar_estado(uow, "contrato", contrato, estado="suspendido", motivo="Impago")
    svc.cambiar_estado(uow, "contrato", contrato, estado="terminado", motivo="Baja")
    assert contrato.estado == "terminado"
    with pytest.raises(Conflicto):
        svc.cambiar_estado(uow, "contrato", contrato, estado="renovado")


def test_orchestrator_sin_aprobadores_no_aprueba_solo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from crmcore.bus.modelos import EventoSaliente
    from sqlalchemy import select

    from services.orchestrator.aprobacion_de_presupuestos import consumir

    pid = uuid4()
    asyncio.run(
        consumir(
            SimpleNamespace(
                tipo="quote.approval.needed",
                tenant_id=str(tenant_id),
                data={
                    "presupuesto_id": str(pid),
                    "numero": "PRE-1",
                    "motivos": ["descuento 40 %"],
                    # Alguien que no está en el organigrama: no hay superior.
                    "solicitante_id": str(uuid4()),
                },
            )
        )
    )
    salientes = (
        db.execute(select(EventoSaliente).where(EventoSaliente.tipo == "approval.decided"))
        .scalars()
        .all()
    )
    assert any(
        e.sobre.get("data", e.sobre).get("estado") == "sin_aprobadores"
        and e.sobre.get("data", e.sobre).get("objeto_id") == str(pid)
        for e in salientes
    ), [e.sobre for e in salientes]
