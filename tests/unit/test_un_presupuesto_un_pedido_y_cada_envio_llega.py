"""Del presupuesto aceptado al ERP, sin pedidos dobles ni reenvíos perdidos.

Auditoría del 13-11-2026, tres fallos del mismo flujo:

* **FUN-B-3.** `aceptar` leía el presupuesto sin bloquearlo y nada impedía dos
  pedidos del mismo presupuesto: dos aceptaciones simultáneas daban dos pedidos
  y dos envíos al ERP.
* **FUN-B-4.** El envío al ERP llevaba la clave de deduplicación `erp:{id}`
  fija. Tras un rechazo se permite reenviar, pero el buzón del consumidor veía
  la misma clave y lo descartaba como repetido: el pedido se quedaba en
  «enviado_erp» para siempre.
* **FUN-B-5.** `confirmar_desde_erp` no miraba el estado: un rechazo tardío
  pisaba un pedido ya confirmado.

Las decisiones puras se prueban sin base; el bloqueo, la restricción y el
buzón, con ella, porque son justo lo que la base decide.
"""

from __future__ import annotations

import inspect
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.datos.estados import estado_de
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto
from sqlalchemy import event, func, select

from services.sales import catalogo as cat
from services.sales import presupuestos as pre

# ── Sin base de datos ─────────────────────────────────────────────────────


def test_el_modelo_declara_un_pedido_por_presupuesto() -> None:
    restricciones = {
        c.name: tuple(col.name for col in c.columns)
        for c in pre.Pedido.__table__.constraints
        if c.name
    }
    assert restricciones.get(pre.UQ_PEDIDO_PRESUPUESTO) == ("tenant_id", "presupuesto_id")


@pytest.mark.parametrize("estado", ["confirmado", "conciliado"])
@pytest.mark.parametrize("aceptado", [True, False])
def test_un_pedido_cerrado_no_lo_mueve_ninguna_respuesta(estado: str, aceptado: bool) -> None:
    pedido = pre.Pedido(estado=estado, envios_erp=1)
    assert pre._respuesta_erp_fuera_de_turno(pedido, {}, aceptado=aceptado)


def test_un_rechazo_de_un_intento_superado_no_cuenta() -> None:
    pedido = pre.Pedido(estado="enviado_erp", envios_erp=2)
    assert pre._respuesta_erp_fuera_de_turno(pedido, {"intento": 1}, aceptado=False)
    assert pre._respuesta_erp_fuera_de_turno(pedido, {"intento": "1"}, aceptado=False)
    assert not pre._respuesta_erp_fuera_de_turno(pedido, {"intento": 2}, aceptado=False)
    # Sin intento no se sabe a qué envío contesta, y no se inventa.
    assert not pre._respuesta_erp_fuera_de_turno(pedido, {}, aceptado=False)
    # Una confirmación tardía vale: si el ERP tiene el pedido, lo tiene.
    assert not pre._respuesta_erp_fuera_de_turno(pedido, {"intento": 1}, aceptado=True)


def test_integration_devuelve_el_intento_y_lo_mete_en_sus_claves() -> None:
    """La vuelta tiene el mismo problema que la ida: con `erp-rechazo:{pedido}`
    fijo, el rechazo del reenvío se descartaba en ventas como repetido del
    primero. Se lee del código del consumidor porque ejecutarlo pide un ERP."""
    from services.integration import pedidos_erp

    fuente = inspect.getsource(pedidos_erp.consumir_pedido)
    assert 'f"erp-rechazo:{pedido_id}{sufijo}"' in fuente
    assert 'f"erp-confirmacion:{pedido_id}{sufijo}"' in fuente
    assert fuente.count('"intento": datos.get("intento")') == 2


# ── Con base de datos ─────────────────────────────────────────────────────


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.fixture
def presupuesto(db: Any, tenant_id: UUID, uow: UnidadDeTrabajo) -> pre.Presupuesto:
    caja = cat.Producto(
        tenant_id=tenant_id,
        sku="CAJA-10",
        nombre="Caja de diez",
        familia="embalaje",
        precio_base=Decimal("100.00"),
        coste=Decimal("60.00"),
    )
    db.add(caja)
    db.flush()
    fila = pre.crear(uow, lineas=[{"producto_id": str(caja.id)}], cuenta_id=uuid4())
    pre.enviar(uow, fila.id)
    return fila


def _pedidos_de(db: Any, presupuesto_id: UUID) -> int:
    return int(
        db.execute(
            select(func.count())
            .select_from(pre.Pedido)
            .where(pre.Pedido.presupuesto_id == presupuesto_id)
        ).scalar_one()
    )


def test_aceptar_bloquea_la_fila_del_presupuesto(
    uow: UnidadDeTrabajo, db: Any, presupuesto: Any
) -> None:
    """Medido sobre el SQL que sale: sin `FOR UPDATE` dos aceptaciones a la vez
    leen las dos «enviado»."""
    sentencias: list[str] = []

    def _anotar(_c: Any, _cur: Any, sql: str, *_a: Any) -> None:
        sentencias.append(sql)

    conexion = db.connection()
    event.listen(conexion, "before_cursor_execute", _anotar)
    try:
        pre.aceptar(uow, presupuesto.id)
    finally:
        event.remove(conexion, "before_cursor_execute", _anotar)
    assert any("FROM presupuestos" in s and "FOR UPDATE" in s for s in sentencias), sentencias


def test_la_segunda_aceptacion_es_un_409_que_lo_dice(
    uow: UnidadDeTrabajo, db: Any, presupuesto: Any
) -> None:
    pre.aceptar(uow, presupuesto.id)
    with pytest.raises(Conflicto) as e:
        pre.aceptar(uow, presupuesto.id)
    assert e.value.error_code == "presupuesto.ya_aceptado"
    assert _pedidos_de(db, presupuesto.id) == 1


def test_una_aceptacion_que_leyo_enviado_no_crea_un_segundo_pedido(
    uow: UnidadDeTrabajo, db: Any, presupuesto: Any
) -> None:
    """**Esta es la del agujero.** Se reproduce lo que veía la segunda de dos
    aceptaciones simultáneas sin bloqueo: el presupuesto aún «enviado» con el
    pedido de la primera ya escrito. La restricción única es el suelo, y tiene
    que salir como el mismo 409 claro, no como un 500."""
    pre.aceptar(uow, presupuesto.id)
    presupuesto.estado = estado_de("presupuesto", "enviado", db)
    db.flush()

    with pytest.raises(Conflicto) as e:
        pre.aceptar(uow, presupuesto.id)
    assert e.value.error_code == "presupuesto.ya_aceptado"
    assert _pedidos_de(db, presupuesto.id) == 1


def _enviados(uow: UnidadDeTrabajo) -> list[dict[str, Any]]:
    return [p for p in uow._pendientes if p["tipo"] == "order.submitted"]


def test_el_reenvio_tras_un_rechazo_llega_al_consumidor(
    uow: UnidadDeTrabajo, db: Any, presupuesto: Any, tenant_id: UUID
) -> None:
    """**FUN-B-4.** Cada envío lleva su clave, y el buzón del consumidor —el
    mismo `marcar_si_nuevo` que usa `idempotente`— deja pasar el reenvío y sigue
    descartando el reintento del relevo del mismo envío."""
    from crmcore.bus.inbox import marcar_si_nuevo
    from crmcore.events.envelope import crear_evento

    pedido = pre.aceptar(uow, presupuesto.id)
    pre.enviar_a_erp(uow, pedido.id)
    pre.confirmar_desde_erp(
        uow, pedido.id, aceptado=False, error="sin stock", respuesta={"intento": 1}
    )
    salida = pre.enviar_a_erp(uow, pedido.id)
    assert salida["intento"] == 2

    envios = _enviados(uow)
    claves = [e["dedup_key"] for e in envios]
    assert claves == [f"erp:{pedido.id}:1", f"erp:{pedido.id}:2"]
    assert [e["data"]["intento"] for e in envios] == [1, 2]

    def _llega(clave: str) -> bool:
        evento = crear_evento(
            "order.submitted",
            tenant_id=tenant_id,
            subject=("pedido", pedido.id),
            data={},
            dedup_key=clave,
        )
        return marcar_si_nuevo(db, evento, consumidor="integration-pedidos")

    assert _llega(claves[0]) is True
    assert _llega(claves[1]) is True, "el reenvío se descarta como repetido"
    assert _llega(claves[1]) is False, "el reintento del relevo ya no se deduplica"


def test_un_rechazo_tardio_no_pisa_un_pedido_confirmado(
    uow: UnidadDeTrabajo, presupuesto: Any
) -> None:
    """**FUN-B-5.**"""
    pedido = pre.aceptar(uow, presupuesto.id)
    pre.enviar_a_erp(uow, pedido.id)
    pre.confirmar_desde_erp(uow, pedido.id, aceptado=True, referencia_erp="SO-1")

    salida = pre.confirmar_desde_erp(uow, pedido.id, aceptado=False, error="duplicado")
    assert salida["ignorada"] is True
    assert pedido.estado == "confirmado"
    assert pedido.referencia_erp == "SO-1"
    assert pedido.error_erp is None


def test_el_rechazo_de_un_intento_anterior_no_tumba_el_reenvio(
    uow: UnidadDeTrabajo, presupuesto: Any
) -> None:
    pedido = pre.aceptar(uow, presupuesto.id)
    pre.enviar_a_erp(uow, pedido.id)
    # Anotado a mano, sin intento: se aplica como siempre.
    pre.confirmar_desde_erp(uow, pedido.id, aceptado=False, error="cliente bloqueado")
    pre.enviar_a_erp(uow, pedido.id)

    salida = pre.confirmar_desde_erp(
        uow, pedido.id, aceptado=False, error="cliente bloqueado", respuesta={"intento": 1}
    )
    assert salida["ignorada"] is True
    assert pedido.estado == "enviado_erp"

    pre.confirmar_desde_erp(
        uow, pedido.id, aceptado=True, referencia_erp="SO-2", respuesta={"intento": 2}
    )
    assert pedido.estado == "confirmado"
    assert pedido.referencia_erp == "SO-2"
