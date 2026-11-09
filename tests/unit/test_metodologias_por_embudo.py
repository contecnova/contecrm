"""La metodología de cada embudo, y sus criterios se marcan desde la oportunidad.

Pedido el 09-11-2026 (decidido por formulario): preguntas por etapa con
puntuación —MEDDIC, BANT…—, pasos y playbook por etapa, y varias metodologías
por embudo. La evaluación existía y nadie podía rellenarla: «qué falta para
cerrar» salía siempre igual.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.errors import ErrorValidacion

from tests.unit.test_forecast import pipeline, uow  # noqa: F401

pytestmark = pytest.mark.db


def _oportunidad(db: Any, tenant_id: UUID, pipeline: Any) -> Any:  # noqa: F811
    from sqlalchemy import select

    from services.sales.modelos import Etapa, Oportunidad

    etapa = db.execute(select(Etapa).where(Etapa.pipeline_id == pipeline.id)).scalars().first()
    op = Oportunidad(
        tenant_id=tenant_id,
        nombre="Op",
        pipeline_id=pipeline.id,
        etapa_id=etapa.id,
        importe=Decimal("1000"),
    )
    db.add(op)
    db.flush()
    return op


def test_la_del_embudo_manda_y_sus_criterios_se_marcan(
    db: Any,
    tenant_id: UUID,
    pipeline: Any,  # noqa: F811
) -> None:
    from services.sales import cadencias as cad

    general = cad.Metodologia(tenant_id=tenant_id, clave="general", nombre="BANT", familia="bant")
    propia = cad.Metodologia(
        tenant_id=tenant_id,
        clave="proyecto",
        nombre="MEDDIC de proyecto",
        familia="meddic",
        pipeline=pipeline.clave,
    )
    db.add_all([general, propia])
    db.flush()
    op = _oportunidad(db, tenant_id, pipeline)

    assert cad.metodologia_de(db, tenant_id, op) is propia

    antes = cad.evaluar(db, tenant_id, propia.id, op.id)
    assert antes["cubiertos"] == 0 and len(antes["detalle"]) == 6
    despues = cad.responder(
        db,
        tenant_id,
        propia.id,
        op.id,
        {"comprador_economico": {"cubierto": True, "nota": "La directora financiera"}},
        por=uuid4(),
    )
    assert despues["cubiertos"] == 1 and despues["puntuacion"] == 20.0
    marcado = next(c for c in despues["detalle"] if c["clave"] == "comprador_economico")
    assert marcado["cubierto"] and marcado["nota"] == "La directora financiera"
    # Desmarcar lo quita.
    otra = cad.responder(
        db, tenant_id, propia.id, op.id, {"comprador_economico": {"cubierto": False}}, por=None
    )
    assert otra["cubiertos"] == 0


def test_un_criterio_que_no_es_de_la_metodologia_se_rechaza(
    db: Any,
    tenant_id: UUID,
    pipeline: Any,  # noqa: F811
) -> None:
    from services.sales import cadencias as cad

    met = cad.Metodologia(tenant_id=tenant_id, clave="b", nombre="BANT", familia="bant")
    db.add(met)
    db.flush()
    op = _oportunidad(db, tenant_id, pipeline)
    with pytest.raises(ErrorValidacion) as exc:
        cad.responder(db, tenant_id, met.id, op.id, {"presupuestoo": True}, por=None)
    assert exc.value.error_code == "metodologia.criterio_desconocido"


def test_spin_y_challenger_traen_sus_criterios() -> None:
    from services.sales.cadencias import CRITERIOS_DE_SERIE

    for familia in ("spin", "challenger"):
        criterios = CRITERIOS_DE_SERIE[familia]
        assert criterios and sum(c["peso"] for c in criterios) == 100


def test_criterios_escritos_con_pregunta_y_sin_peso_cuentan_igual() -> None:
    from services.sales.cadencias import Metodologia, criterios_de

    met = Metodologia(
        clave="x",
        nombre="MEDDIC",
        familia="meddic",
        criterios=[
            {"clave": "metricas", "nombre": "Métricas", "pregunta": "¿Qué mejora y cuánto?"},
            {"clave": "campeon", "nombre": "Campeón", "pregunta": "¿Quién nos vende por dentro?"},
        ],
    )
    criterios = criterios_de(met)
    assert criterios[0]["etiqueta"] == "¿Qué mejora y cuánto?"
    assert [c["peso"] for c in criterios] == [50, 50]


def test_el_playbook_se_encuentra_por_la_clave_o_por_el_nombre_de_la_etapa(
    db: Any, tenant_id: UUID
) -> None:
    from services.sales import cadencias as cad

    db.add(
        cad.Playbook(
            tenant_id=tenant_id,
            clave="oem_cualificacion",
            titulo="Qué hacer en Cualificación",
            etapa="cualificacion",
            pasos=["Confirmar quién firma"],
        )
    )
    db.flush()
    for pedida in ("cualificacion", "Cualificación"):
        encontrado = cad.playbook_para(db, tenant_id, etapa=pedida)
        assert encontrado and encontrado["clave"] == "oem_cualificacion", pedida
