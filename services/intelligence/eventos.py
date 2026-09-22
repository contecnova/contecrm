"""Eventos del servicio de inteligencia (Anexo B del catálogo)."""

from __future__ import annotations

from crmcore.events.catalogo import TipoEvento, registrar

AI_PROPOSAL_CREATED = registrar(
    TipoEvento(
        tipo="ai.proposal.created",
        version=1,
        productor="intelligence",
        descripcion=(
            "La IA ha dejado un borrador para que alguien lo revise "
            "(CRM-05.02.02.01). No está aplicado en ninguna parte: quien lo "
            "consuma tiene que tratarlo como una propuesta, no como un dato"
        ),
        campos=("propuesta_id", "tarea"),
    )
)
AI_BUDGET_EXHAUSTED = registrar(
    TipoEvento(
        tipo="ai.budget.exhausted",
        version=1,
        productor="intelligence",
        descripcion=(
            "Se ha agotado el presupuesto de IA del mes de un tenant "
            "(CRM-05.02.02.08). Lo escucha quien avisa, porque el usuario solo ve "
            "que la función dejó de estar"
        ),
        campos=("tenant", "gastado"),
    )
)
