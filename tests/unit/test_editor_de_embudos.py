"""El embudo y sus etapas se editan, se ordenan y se quitan sin romper nada.

Pedido el 09-11-2026: «no veo dónde definir los estados o cuántos hay, por
ejemplo en el embudo; todo configurable por administradores». La API sólo
dejaba crear etapas. Lo que se vigila: que un embudo nunca se quede sin una
etapa final ganada y una perdida —sin ellas no se cierra ninguna venta— y que
quitar una etapa con oportunidades no las deje fuera del tablero.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.authz.principal import Principal
from crmcore.errors import Conflicto, ErrorValidacion
from sqlalchemy import select

pytestmark = pytest.mark.db


@pytest.fixture
def embudo(db: Any, tenant_id: UUID) -> tuple[Any, dict[str, Any]]:
    from services.sales.modelos import Etapa, Pipeline

    pipeline = Pipeline(tenant_id=tenant_id, clave=f"p{uuid4().hex[:6]}", nombre="Proyecto")
    db.add(pipeline)
    db.flush()
    etapas = {}
    for i, (clave, terminal, ganada) in enumerate(
        [
            ("cualificacion", False, False),
            ("oferta", False, False),
            ("ganada", True, True),
            ("perdida", True, False),
        ]
    ):
        etapas[clave] = Etapa(
            tenant_id=tenant_id,
            pipeline_id=pipeline.id,
            clave=clave,
            nombre=clave.capitalize(),
            orden=i,
            terminal=terminal,
            ganada=ganada,
        )
        db.add(etapas[clave])
    db.flush()
    return pipeline, etapas


def _quien(tenant_id: UUID) -> Principal:
    return Principal(id=uuid4(), tenant_id=tenant_id, permisos=frozenset({"*:*"}))


def test_una_etapa_se_edita_y_el_embudo_se_reordena(
    db: Any, tenant_id: UUID, embudo: tuple[Any, dict[str, Any]]
) -> None:
    from services.sales import api
    from services.sales.esquemas import EditarEtapa, OrdenEtapas

    pipeline, etapas = embudo
    quien = _quien(tenant_id)
    api.editar_etapa(
        pipeline.id,
        etapas["oferta"].id,
        EditarEtapa(nombre="Oferta enviada", probabilidad=60, criterios_salida=["importe"]),
        db,
        quien,
    )
    assert etapas["oferta"].nombre == "Oferta enviada"
    assert etapas["oferta"].probabilidad == 60
    assert etapas["oferta"].criterios_salida == ["importe"]

    nuevo = [etapas[c].id for c in ("oferta", "cualificacion", "ganada", "perdida")]
    api.ordenar_etapas(pipeline.id, OrdenEtapas(etapas=nuevo), db, quien)
    assert (etapas["oferta"].orden, etapas["cualificacion"].orden) == (0, 1)
    # Un orden que se deja etapas fuera no se aplica a medias.
    with pytest.raises(ErrorValidacion):
        api.ordenar_etapas(pipeline.id, OrdenEtapas(etapas=nuevo[:2]), db, quien)


def test_el_embudo_no_se_queda_sin_cierres(
    db: Any, tenant_id: UUID, embudo: tuple[Any, dict[str, Any]]
) -> None:
    from services.sales import api
    from services.sales.esquemas import EditarEtapa

    pipeline, etapas = embudo
    quien = _quien(tenant_id)
    with pytest.raises(ErrorValidacion) as exc:
        api.editar_etapa(pipeline.id, etapas["ganada"].id, EditarEtapa(terminal=False), db, quien)
    assert exc.value.error_code == "sales.embudo_sin_ganada"
    db.rollback()


def test_quitar_una_etapa_con_oportunidades_pide_a_donde_van(
    db: Any, tenant_id: UUID, embudo: tuple[Any, dict[str, Any]]
) -> None:
    from services.sales import api
    from services.sales.modelos import CambioEtapa, Oportunidad

    pipeline, etapas = embudo
    quien = _quien(tenant_id)
    op = Oportunidad(
        tenant_id=tenant_id,
        nombre="Op",
        pipeline_id=pipeline.id,
        etapa_id=etapas["oferta"].id,
        importe=Decimal("1000"),
    )
    db.add(op)
    db.flush()

    with pytest.raises(Conflicto) as exc:
        api.borrar_etapa(pipeline.id, etapas["oferta"].id, db, quien, mover_a=None)
    assert exc.value.error_code == "sales.etapa_con_oportunidades"

    api.borrar_etapa(
        pipeline.id, etapas["oferta"].id, db, quien, mover_a=etapas["cualificacion"].id
    )
    assert op.etapa_id == etapas["cualificacion"].id
    # Y el paso queda en su historial, con por qué.
    paso = db.execute(select(CambioEtapa).where(CambioEtapa.oportunidad_id == op.id)).scalar_one()
    assert "Se quitó la etapa" in (paso.motivo or "")
