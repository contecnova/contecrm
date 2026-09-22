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

# ── Cotización y contratación (CRM-03.03.02) ──────────────────────────────

QUOTE_CREATED = registrar(
    TipoEvento(
        tipo="quote.created",
        version=1,
        productor="sales",
        descripcion="Se ha creado un presupuesto (o una versión nueva de uno)",
        campos=("presupuesto_id", "numero", "version", "total"),
    )
)
QUOTE_APPROVAL_NEEDED = registrar(
    TipoEvento(
        tipo="quote.approval.needed",
        version=1,
        productor="sales",
        descripcion=(
            "El presupuesto se ha parado porque el descuento o el margen pasan "
            "de lo que se puede dar solo. Lleva los motivos: quien abra la "
            "aprobación no tiene que recalcular la matriz para explicarla"
        ),
        campos=("presupuesto_id", "numero", "total", "motivos"),
    )
)
QUOTE_SENT = registrar(
    TipoEvento(
        tipo="quote.sent",
        version=1,
        productor="sales",
        descripcion="El presupuesto ha salido hacia el cliente",
        campos=("presupuesto_id", "numero", "version", "total"),
    )
)
QUOTE_ACCEPTED = registrar(
    TipoEvento(
        tipo="quote.accepted",
        version=1,
        productor="sales",
        descripcion="El cliente ha aceptado el presupuesto y ha nacido el pedido",
        campos=("presupuesto_id", "numero", "pedido_id", "total"),
    )
)
ORDER_SUBMITTED = registrar(
    TipoEvento(
        tipo="order.submitted",
        version=1,
        productor="sales",
        descripcion=(
            "Un pedido sale hacia el ERP. Lleva las líneas dentro para que el "
            "conector no tenga que volver a preguntarlas: pedirlas después "
            "ataría el traspaso a que `sales` esté en pie en ese instante"
        ),
        campos=("pedido_id", "numero", "cuenta_id", "total"),
    )
)
CONTRACT_SIGNED = registrar(
    TipoEvento(
        tipo="contract.signed",
        version=1,
        productor="sales",
        descripcion="Alta de contrato con su vigencia",
        campos=("contrato_id", "numero", "cuenta_id", "importe"),
    )
)
CONTRACT_RENEWAL_DUE = registrar(
    TipoEvento(
        tipo="contract.renewal.due",
        version=1,
        productor="sales",
        descripcion=(
            "Un contrato entra en su periodo de preaviso. Se emite en el "
            "preaviso y no al vencer, porque el día del vencimiento ya es tarde "
            "para no renovar"
        ),
        campos=("contrato_id", "numero", "cuenta_id", "vence", "dias_restantes"),
    )
)
SUBSCRIPTION_CHANGED = registrar(
    TipoEvento(
        tipo="subscription.changed",
        version=1,
        productor="sales",
        descripcion="Alta, baja, pausa o cambio de plan de una suscripción, con su prorrateo",
        campos=("suscripcion_id", "cuenta_id", "tipo", "plan", "importe"),
    )
)


# ── Cadencias (CRM-03.03.01) ──────────────────────────────────────────────

CADENCE_STEP_DUE = registrar(
    TipoEvento(
        tipo="cadence.step.due",
        version=1,
        productor="sales",
        descripcion=(
            "Toca un paso de cadencia. Lleva `manual` dentro: quien lo consuma "
            "tiene que saber si crea una tarea o manda un correo, y adivinarlo "
            "por el canal es cómo se manda un correo donde tocaba llamar"
        ),
        campos=("inscripcion_id", "cadencia", "paso", "canal"),
    )
)
CADENCE_EXITED = registrar(
    TipoEvento(
        tipo="cadence.exited",
        version=1,
        productor="sales",
        descripcion=(
            "Alguien sale de una cadencia, con su motivo. Se emite también cuando "
            "sale por haber contestado un compañero de su cuenta"
        ),
        campos=("inscripcion_id", "cadencia_id", "email", "motivo"),
    )
)

# ── Canal indirecto y retribución variable ────────────────────────────────
PARTNER_ACTIVATED = registrar(
    TipoEvento(
        tipo="partner.activated",
        version=1,
        productor="sales",
        descripcion=(
            "Un partner ha quedado activo. Lo escucha marketing para poder abrir "
            "fondos a su nombre sin leer el esquema de ventas"
        ),
        campos=("partner_id", "clave", "canal"),
    )
)
PARTNER_DEAL_REGISTERED = registrar(
    TipoEvento(
        tipo="partner.deal.registered",
        version=1,
        productor="sales",
        descripcion=(
            "Un partner ha registrado una oportunidad. Trae si hay conflicto "
            "—no con quién—: quien avise al fabricante necesita saber que dos "
            "partners van al mismo cliente"
        ),
        campos=("registro_id", "partner_id", "importe", "hay_conflicto"),
    )
)
PARTNER_DEAL_DECIDED = registrar(
    TipoEvento(
        tipo="partner.deal.decided",
        version=1,
        productor="sales",
        descripcion=(
            "Se ha decidido un registro de oportunidad. `protegido_hasta` viaja "
            "con él **solo cuando se aprueba** y por eso no está entre los campos "
            "prometidos: un rechazo no tiene fecha de protección, y prometerla "
            "para mandarla vacía es la forma de que el consumidor se fíe de un "
            "campo que a veces no significa nada"
        ),
        campos=("registro_id", "partner_id", "estado"),
    )
)
PARTNER_DEAL_EXPIRED = registrar(
    TipoEvento(
        tipo="partner.deal.expired",
        version=1,
        productor="sales",
        descripcion="Ha vencido la protección de un registro de oportunidad",
        campos=("registro_id", "partner_id"),
    )
)
COMMISSION_APPROVAL_NEEDED = registrar(
    TipoEvento(
        tipo="commission.approval.needed",
        version=1,
        productor="sales",
        descripcion=(
            "Una liquidación de comisión pide aprobación. La cadena la resuelve el "
            "motor de aprobaciones del orquestador: montar una segunda aquí daría "
            "dos sitios donde mirar quién aprobó qué"
        ),
        campos=("liquidacion_id", "total", "moneda"),
    )
)
COMMISSION_PAID = registrar(
    TipoEvento(
        tipo="commission.paid",
        version=1,
        productor="sales",
        descripcion=(
            "Una liquidación se ha pagado, con su referencia. Es el evento que "
            "permite cuadrar el CRM con la nómina o la remesa sin abrir las dos"
        ),
        campos=("liquidacion_id", "total", "referencia"),
    )
)
