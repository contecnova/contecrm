"""El traspaso a ventas cuando marketing califica un lead (CRM-02.01.02.05).

`lead.qualified` no lo escuchaba nadie hasta el 10-11-2026: el lead llegaba a
SQL en la puntuación y en ventas seguía «nuevo», sin puntuación.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest

from services.sales.modelos import Lead


class _Uow:
    def __init__(self, db: Any, tenant_id: UUID) -> None:
        self.db, self.tenant_id = db, tenant_id

    def __enter__(self) -> "_Uow":
        return self

    def __exit__(self, *_: Any) -> None:
        self.db.flush()


def _consumir(db: Any, tenant_id: UUID, monkeypatch: Any, **data: Any) -> None:
    from crmcore.db import uow as uow_mod

    from services.sales.consumidores import consumir_cualificacion

    monkeypatch.setattr(uow_mod, "unidad_de_trabajo", lambda t: _Uow(db, t))
    asyncio.run(
        consumir_cualificacion(
            {"tipo": "lead.qualified", "tenant_id": str(tenant_id), "data": data}
        )
    )


@pytest.mark.db
def test_un_sql_pasa_a_cualificado_con_su_puntuacion(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    lead = Lead(tenant_id=tenant_id, estado="nuevo", nombre="ZZ")
    db.add(lead)
    db.flush()
    _consumir(db, tenant_id, monkeypatch, lead_id=str(lead.id), calificacion="sql", interes=80)
    assert (lead.estado, lead.puntuacion) == ("cualificado", 80)


@pytest.mark.db
def test_un_mql_deja_la_puntuacion_y_no_mueve_el_estado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    lead = Lead(tenant_id=tenant_id, estado="nuevo", nombre="ZZ")
    db.add(lead)
    db.flush()
    _consumir(db, tenant_id, monkeypatch, lead_id=str(lead.id), calificacion="mql", interes=45)
    assert (lead.estado, lead.puntuacion) == ("nuevo", 45)
