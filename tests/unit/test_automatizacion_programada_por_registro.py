"""Una regla programada sobre un objeto corre una vez por cada registro que cumple.

Decidido por formulario el 09-11-2026 («arreglarla para que avise por lead»):
la sembrada «Lead sin atender en 48 horas» corría una vez al día sin lead y,
con «nuevo» O «sin dueño» y sin edad, habría avisado de cualquier lead nuevo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from services.automation import planificador
from services.automation import registros_programados as rp
from tests.unit.test_automatizacion_momento import _regla

pytestmark = pytest.mark.db

SIN_ATENDER = [
    {"atributo": "estado", "op": "=", "valor": "nuevo"},
    {"atributo": "owner_id", "op": "vacio"},
    {"atributo": "created_at", "op": "hace_mas_de_horas", "valor": 48},
]


def _hace(horas: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=horas)).isoformat()


def test_la_antiguedad_se_puede_preguntar() -> None:
    from services.orchestrator.motor import OPERADORES

    assert OPERADORES["hace_mas_de_horas"](_hace(50), 48)
    assert not OPERADORES["hace_mas_de_horas"](_hace(1), 48)
    assert OPERADORES["hace_menos_de_horas"](_hace(1), 48)
    assert not OPERADORES["hace_mas_de_horas"](None, 48)


def _programada(db: Any, tenant_id: UUID, **extra: Any) -> Any:
    from services.automation.modelos import EjecucionPendiente

    regla = _regla(
        db,
        tenant_id,
        disparador="programada",
        objetivo="lead",
        programacion="0 8 * * *",
        momento="programada",
        condiciones=SIN_ATENDER,
        combinacion="todas",
        **extra,
    )
    fila = EjecucionPendiente(
        tenant_id=tenant_id,
        automatizacion_id=regla.id,
        origen="programada",
        clave=f"programada:{regla.id}:hoy",
        objeto="lead",
        valores={},
        ejecutar_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        estado="pendiente",
        intentos=0,
    )
    db.add(fila)
    db.flush()
    return regla, fila


def test_una_programada_se_reparte_en_los_leads_que_cumplen(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.automation.modelos import EjecucionPendiente

    olvidado, reciente, con_dueno = str(uuid4()), str(uuid4()), str(uuid4())
    leads = [
        {"id": olvidado, "estado": "nuevo", "owner_id": None, "created_at": _hace(60)},
        {"id": reciente, "estado": "nuevo", "owner_id": None, "created_at": _hace(2)},
        {"id": con_dueno, "estado": "nuevo", "owner_id": str(uuid4()), "created_at": _hace(60)},
    ]
    pedidos: list[dict[str, Any]] = []

    def falsos(objeto: str, **kw: Any) -> list[dict[str, Any]]:
        pedidos.append({"objeto": objeto, **kw})
        return leads

    monkeypatch.setattr(rp, "registros_de", falsos)
    regla, fila = _programada(
        db,
        tenant_id,
        activada_por_id=uuid4(),
        activada_con={"tipo": "usuario", "permisos": ["lead:read"], "roles": ["comercial"]},
    )
    planificador.ejecutar_pendientes(tenant_id)
    db.expire_all()

    # Los pide con la identidad de quien la activó.
    assert pedidos and pedidos[0]["identidad"]["permisos"] == ["lead:read"]
    assert db.get(EjecucionPendiente, fila.id).estado == "hecha"
    por_lead = (
        db.query(EjecucionPendiente)
        .filter_by(automatizacion_id=regla.id, origen="programada_registro")
        .all()
    )
    # Sólo el que lleva más de 48 horas, sin dueño.
    assert [f.registro_id for f in por_lead] == [olvidado]


def test_sin_quien_la_activo_falla_una_vez_y_dice_que_hacer(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.automation.modelos import EjecucionPendiente

    monkeypatch.setattr(rp, "registros_de", lambda *a, **k: pytest.fail("no debe leer"))
    _, fila = _programada(db, tenant_id)
    planificador.ejecutar_pendientes(tenant_id)
    db.expire_all()
    vista = db.get(EjecucionPendiente, fila.id)
    assert vista.estado == "fallida" and "vuélvela a encender" in vista.error


def test_una_programada_sin_condiciones_es_de_calendario_y_corre_una_vez(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """«Los lunes, recuerda revisar las oportunidades» no es un aviso por oportunidad."""
    from services.automation.modelos import EjecucionPendiente

    monkeypatch.setattr(rp, "registros_de", lambda *a, **k: pytest.fail("no debe recorrer"))
    regla, fila = _programada(db, tenant_id)
    regla.condiciones = []
    db.flush()
    planificador.ejecutar_pendientes(tenant_id)
    db.expire_all()
    vista = db.get(EjecucionPendiente, fila.id)
    assert vista.estado == "hecha" and vista.ejecucion_id is not None
