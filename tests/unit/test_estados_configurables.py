"""Los estados los configura la empresa; el código pregunta por lo que significan.

Pedido el 09-11-2026: «definir los estados, cómo se llaman, qué tipos hay o
cuántos hay; todo configurable por administradores». Lo que lo hace seguro es
el significado: una empresa añade «En pausa» como otro estado abierto o llama
«Adjudicada» a la ganada, y la previsión sigue sabiendo qué cuenta como
ganado. Los de fábrica no se borran: se renombran o se desactivan.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from crmcore.datos import estados as est
from crmcore.errors import Conflicto, ErrorValidacion

import services.sales.estados  # noqa: F401 — registra las máquinas de sales
from tests.unit.test_forecast import pipeline, uow  # noqa: F401


def _de_fabrica() -> dict[str, Any]:
    return est.a_configuracion(est.MAQUINAS["oportunidad"], de_fabrica=True)


def _con_pausa() -> dict[str, Any]:
    conf = _de_fabrica()
    conf["estados"].append(
        {"clave": "en_pausa", "nombre": "En pausa", "significado": "abierto", "orden": 1}
    )
    conf["transiciones"]["abierta"] = [*conf["transiciones"]["abierta"], "en_pausa"]
    conf["transiciones"]["en_pausa"] = ["abierta", "perdida"]
    for e in conf["estados"]:
        if e["clave"] == "ganada":
            e["nombre"] = "Adjudicada"
    return conf


def test_un_estado_propio_cuenta_por_lo_que_significa() -> None:
    maquina = est.construir(est.MAQUINAS["oportunidad"], _con_pausa())
    assert maquina.significado("en_pausa") == "abierto"
    assert maquina.presentacion["ganada"]["nombre"] == "Adjudicada"
    assert "en_pausa" in maquina.transiciones["abierta"]


@pytest.mark.parametrize(
    ("cambio", "codigo"),
    [
        # Un estado de fábrica no se borra: hay registros con él.
        (lambda c: c["estados"].pop(), "estados.falta_de_fabrica"),
        # Ni cambia lo que es: «ganada» sigue siendo ganada aunque se llame distinto.
        (
            lambda c: next(e for e in c["estados"] if e["clave"] == "ganada").update(
                significado="perdido"
            ),
            "estados.significado_de_fabrica",
        ),
        # Un estado nuevo significa algo que el producto sabe tratar.
        (
            lambda c: c["estados"].append({"clave": "rara", "significado": "inventado"}),
            "estados.significado_desconocido",
        ),
        # Sin un «ganado» activo no hay previsión ni comisión.
        (
            lambda c: next(e for e in c["estados"] if e["clave"] == "ganada").update(activo=False),
            "estados.falta_significado",
        ),
        (
            lambda c: c["transiciones"].update(abierta=["no_existe"]),
            "estados.transicion_desconocida",
        ),
        (lambda c: c["estados"].append({"clave": "Con Espacios"}), "estados.clave_invalida"),
    ],
)
def test_lo_que_no_se_puede_configurar_se_dice(cambio: Any, codigo: str) -> None:
    conf = _de_fabrica()
    cambio(conf)
    with pytest.raises(ErrorValidacion) as exc:
        est.construir(est.MAQUINAS["oportunidad"], conf)
    assert exc.value.error_code == codigo


@pytest.mark.db
def test_la_configuracion_de_la_empresa_es_la_que_manda(db: Any, tenant_id: UUID) -> None:
    from crmcore.runtime.settings import fijar, invalidar
    from crmcore.tenancy.context import con_contexto

    with con_contexto(tenant_id=tenant_id, origen="prueba"):
        # Sin configuración, la de fábrica.
        assert est.maquina_efectiva("oportunidad", db) is est.MAQUINAS["oportunidad"]
        assert est.con_significado("oportunidad", "abierto", db) == {"abierta"}

        conf = _con_pausa()
        # Y desactivar «cancelada»: deja de ser un destino.
        next(e for e in conf["estados"] if e["clave"] == "cancelada")["activo"] = False
        fijar(db, "maquinas_de_estado", {"oportunidad": conf}, ambito_id=str(tenant_id))
        invalidar()

        assert est.con_significado("oportunidad", "abierto", db) == {"abierta", "en_pausa"}
        assert est.significa("oportunidad", "en_pausa", "abierto", db)
        # Se puede ir al estado propio, y desde él a donde dice la empresa.
        est.comprobar("oportunidad", desde="abierta", hasta="en_pausa", db=db)
        est.comprobar("oportunidad", desde="en_pausa", hasta="perdida", motivo="precio", db=db)
        with pytest.raises(Conflicto):
            est.comprobar("oportunidad", desde="en_pausa", hasta="ganada", db=db)
        with pytest.raises(ErrorValidacion) as exc:
            est.comprobar("oportunidad", desde="abierta", hasta="cancelada", motivo="x", db=db)
        assert exc.value.error_code == "estados.estado_inactivo"


def test_la_vida_del_tenant_no_la_configura_la_empresa() -> None:
    import services.tenancy.servicio  # noqa: F401

    assert est.MAQUINAS["tenant"].configurable is False


@pytest.mark.db
def test_a_un_estado_propio_se_llega_y_ganar_tiene_su_camino(
    db: Any,
    tenant_id: UUID,
    pipeline: Any,  # noqa: F811
) -> None:
    from crmcore.db.uow import UnidadDeTrabajo
    from crmcore.runtime.settings import fijar, invalidar
    from crmcore.tenancy.context import con_contexto

    from services.sales import servicio as svc
    from tests.unit.test_lecciones_aprendidas import _op

    with con_contexto(tenant_id=tenant_id, origen="prueba"):
        fijar(db, "maquinas_de_estado", {"oportunidad": _con_pausa()}, ambito_id=str(tenant_id))
        invalidar()
        op = _op(db, tenant_id, pipeline, "abierta", dias=5)
        trabajo = UnidadDeTrabajo(db=db, tenant_id=tenant_id)

        svc.cambiar_estado(trabajo, "oportunidad", op, estado="en_pausa")
        assert op.estado == "en_pausa"
        # Sigue contando como abierta: la previsión y las listas la ven.
        assert est.significa("oportunidad", op.estado, "abierto", db)

        with pytest.raises(Conflicto) as exc:
            svc.cambiar_estado(trabajo, "oportunidad", op, estado="ganada")
        assert exc.value.error_code == "estados.con_su_camino"
