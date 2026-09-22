"""Eventos de aprobación (Anexo B del catálogo).

Públicos: quien integra quiere enterarse de que algo está esperando su firma o de
que ya se decidió, y casi siempre desde fuera del CRM —un correo, una app de
mensajería, el ERP que espera el visto bueno para emitir el pedido—.
"""

from __future__ import annotations

from crmcore.events.catalogo import TipoEvento, registrar

APPROVAL_REQUESTED = registrar(
    TipoEvento(
        tipo="approval.requested",
        version=1,
        productor="orchestrator",
        descripcion="Algo se ha puesto a aprobar y hay gente a la que le toca decidir",
        campos=("solicitud_id", "politica", "objeto", "objeto_id"),
    )
)
APPROVAL_STAGE_OPENED = registrar(
    TipoEvento(
        tipo="approval.stage.opened",
        version=1,
        productor="orchestrator",
        descripcion=(
            "La cadena ha avanzado a la siguiente etapa. Va aparte de "
            "`approval.requested` porque quien avisa a los aprobadores necesita "
            "saber que ahora le toca a OTRA gente, y reutilizar el primer evento "
            "obligaría a mirar el estado para saber a quién escribir"
        ),
        campos=("solicitud_id", "etapa", "aprobadores"),
    )
)
APPROVAL_DUE_SOON = registrar(
    TipoEvento(
        tipo="approval.due.soon",
        version=1,
        productor="orchestrator",
        descripcion=(
            "Una etapa se acerca a su plazo. Se avisa ANTES de escalar: un "
            "escalado sin aviso previo se vive como un castigo y la reacción es "
            "discutirlo en vez de decidir"
        ),
        campos=("solicitud_id", "etapa", "vence_at"),
    )
)
APPROVAL_ESCALATED = registrar(
    TipoEvento(
        tipo="approval.escalated",
        version=1,
        productor="orchestrator",
        descripcion="Una etapa ha vencido y se ha añadido al superior de quien tenía que decidir",
        campos=("solicitud_id", "etapa", "anadidos"),
    )
)
APPROVAL_REOPENED = registrar(
    TipoEvento(
        tipo="approval.reopened",
        version=1,
        productor="orchestrator",
        descripcion=(
            "Lo aprobado ha cambiado y la aprobación vuelve a empezar. Quien "
            "ejecutaba lo aprobado tiene que parar, y por eso es un evento y no "
            "un campo que alguien consulte"
        ),
        campos=("solicitud_id", "objeto", "objeto_id", "cambios"),
    )
)
APPROVAL_DECIDED = registrar(
    TipoEvento(
        tipo="approval.decided",
        version=1,
        productor="orchestrator",
        descripcion="La aprobación ha terminado: aprobada, rechazada o con cambios pedidos",
        campos=("solicitud_id", "objeto", "objeto_id", "estado"),
    )
)
