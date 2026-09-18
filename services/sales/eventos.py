"""Eventos de dominio de ventas (Anexo B del catálogo)."""

from __future__ import annotations

from crmcore.events.catalogo import TipoEvento, registrar

LEAD_CREATED = registrar(
    TipoEvento(
        tipo="lead.created",
        version=1,
        productor="sales",
        descripcion="Ha entrado un lead por cualquiera de los canales de captación",
        campos=("lead_id", "origen"),
    )
)
LEAD_QUALIFIED = registrar(
    TipoEvento(
        tipo="lead.qualified",
        version=1,
        productor="sales",
        descripcion="Un lead ha pasado la cualificación y está listo para convertirse",
        campos=("lead_id",),
    )
)
LEAD_CONVERTED = registrar(
    TipoEvento(
        tipo="lead.converted",
        version=1,
        productor="sales",
        descripcion=(
            "Un lead se ha convertido. Trae los identificadores de lo que "
            "generó, que es lo que permite atribuir el negocio a su origen"
        ),
        campos=("lead_id", "cuenta_id", "contacto_id", "oportunidad_id"),
    )
)
OPPORTUNITY_CREATED = registrar(
    TipoEvento(
        tipo="opportunity.created",
        version=1,
        productor="sales",
        descripcion="Se ha creado una oportunidad",
        campos=("oportunidad_id", "cuenta_id", "importe", "moneda"),
    )
)
OPPORTUNITY_STAGE_CHANGED = registrar(
    TipoEvento(
        tipo="opportunity.stage.changed",
        version=1,
        productor="sales",
        descripcion="Una oportunidad ha cambiado de etapa",
        campos=("oportunidad_id", "etapa_desde", "etapa_hasta", "probabilidad"),
    )
)
OPPORTUNITY_WON = registrar(
    TipoEvento(
        tipo="opportunity.won",
        version=1,
        productor="sales",
        descripcion=(
            "Oportunidad ganada. Es el disparador natural del proceso "
            "order-to-cash: quien crea pedidos se suscribe aquí"
        ),
        campos=("oportunidad_id", "cuenta_id", "importe", "moneda"),
    )
)
OPPORTUNITY_LOST = registrar(
    TipoEvento(
        tipo="opportunity.lost",
        version=1,
        productor="sales",
        descripcion="Oportunidad perdida, con su motivo normalizado",
        campos=("oportunidad_id", "cuenta_id", "importe", "motivo"),
    )
)
OPPORTUNITY_REOPENED = registrar(
    TipoEvento(
        tipo="opportunity.reopened",
        version=1,
        productor="sales",
        descripcion=(
            "Se ha reabierto una oportunidad cerrada. Quien haya consumido el "
            "cierre —previsión, comisiones, pedidos— tiene que deshacerlo"
        ),
        campos=("oportunidad_id", "estado_previo", "motivo"),
    )
)
LEAD_ASSIGNED = registrar(
    TipoEvento(
        tipo="lead.assigned",
        version=1,
        productor="sales",
        descripcion=(
            "El enrutamiento ha asignado un lead a alguien. Lleva la regla que "
            "ganó: quien reciba el evento puede explicar el reparto sin "
            "volver a preguntar"
        ),
        campos=("lead_id", "asignado_a", "regla"),
    )
)
