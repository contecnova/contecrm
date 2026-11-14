"""El relevo del outbox publica de verdad, con lo bloqueante fuera del bucle.

FUN-A-11 (auditoría 13-11-2026): la consulta y el commit del relevo, el aviso
de empuje de eventing y el guardado de idempotencia eran síncronos dentro de
código async. Van en `asyncio.to_thread`. No había ninguna prueba que pasara
por `_una_vuelta` contra la base: ésta comprueba que sigue publicando.
"""

from __future__ import annotations

import inspect
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from crmcore.bus.outbox import EventoSaliente, Relevo, encolar


class _Bus:
    def __init__(self) -> None:
        self.publicados: list[Any] = []

    async def publicar(self, evento: Any) -> None:
        self.publicados.append(evento)


async def test_una_vuelta_publica_lo_pendiente(db: Any, tenant_id: UUID) -> None:
    fila = encolar(
        db,
        tenant_id=tenant_id,
        tipo="account.created",
        subject_tipo="cuenta",
        subject_id=uuid4(),
        data={"cuenta_id": str(uuid4()), "nombre": "X"},
    )
    db.flush()
    bus = _Bus()

    publicados = await Relevo(bus, sesion_factory=lambda: db)._una_vuelta()

    assert publicados >= 1
    assert any(e.type == "account.created" for e in bus.publicados)
    pendiente = db.execute(
        sa.select(EventoSaliente.publicado_at).where(EventoSaliente.id == fila.id)
    ).scalar_one()
    assert pendiente is not None


def test_lo_bloqueante_va_en_un_hilo() -> None:
    from crmcore.http import middleware

    from services.eventing import consumidores

    assert "asyncio.to_thread(" in inspect.getsource(Relevo._una_vuelta)
    assert "asyncio.to_thread(" in inspect.getsource(middleware._guardar_respuesta)
    assert "asyncio.to_thread(" in inspect.getsource(consumidores.consumir_evento)
