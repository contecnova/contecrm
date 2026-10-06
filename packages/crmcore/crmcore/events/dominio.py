"""Los eventos de negocio, declarados donde el contrato se ve entero.

Estaban en `services/<servicio>/eventos.py`, «donde vive el productor», que
suena bien y no funciona: **ningún proceso importa los ocho módulos a la vez**.
El servicio de eventos, que es quien valida a qué se puede suscribir un
webhook y quien publica el AsyncAPI a los integradores, solo veía los quince
del núcleo. Los ochenta y seis de negocio existían, se emitían y viajaban por
el bus, pero dar de alta un webhook sobre `opportunity.stage.changed`
contestaba «hay tipos de evento que no existen», y el documento que se entrega
a quien integra describía el quince por ciento del sistema.

No es una cesión del principio: un contrato de evento **es** compartido por
definición —lo consume otro servicio o alguien de fuera—, y cada declaración
sigue diciendo quién lo produce, que es lo que de verdad da dueño al contrato.
Los de plataforma ya se declaraban aquí con `productor="tenancy"` sin que eso
los hiciera de nadie.

El gate `tests/unit/test_catalogo_eventos.py` comprueba que lo que el código
emite está declarado aquí, para que el desfase no pueda volver en silencio.
"""

from __future__ import annotations

from crmcore.events.catalogo import TipoEvento, registrar

# ─────────────────────────────── analytics ────────────────────────────────
# Eventos de informes (Anexo B del catálogo).
#
# Los dos son públicos, y el de fallo especialmente: un informe que deja de llegar
# no se echa de menos —la gente supone que no había nada que contar—, así que el
# fallo tiene que salir del sistema y llegar a alguien.

REPORT_DELIVERED = registrar(
    TipoEvento(
        tipo="report.delivered",
        version=1,
        productor="analytics",
        descripcion=(
            "Un informe programado se ha ejecutado y sale hacia sus destinatarios. "
            "Lleva si el resultado está INCOMPLETO —el objeto se lee a medias, o "
            "el motor no aplica los campos calculados— porque un informe que "
            "llega por correo se lee como el total y nadie va a preguntar"
        ),
        campos=("informe_id", "programacion_id", "formato", "filas", "incompleto"),
    )
)
REPORT_FAILED = registrar(
    TipoEvento(
        tipo="report.failed",
        version=1,
        productor="analytics",
        descripcion=(
            "Un informe programado ha fallado. Lleva cuántas veces seguidas: "
            "distinguir un fallo puntual de uno que lleva una semana es lo que "
            "decide si alguien va a mirarlo"
        ),
        campos=("informe_id", "programacion_id", "error", "fallos_seguidos"),
    )
)

ANALYTICS_SOURCE_REGISTERED = registrar(
    TipoEvento(
        tipo="analytics.source.registered",
        version=1,
        productor="analytics",
        descripcion=(
            "El CRM se ha registrado (o re-registrado) como fuente consultable. "
            "Se emite al cambiar el esquema y no cada noche: un registro que se "
            "refresca por reloj está desfasado justo después de que alguien "
            "añada un campo, que es cuando lo va a buscar"
        ),
        campos=("organizacion", "objetos", "campos"),
    )
)

DASHBOARD_ALERT_FIRED = registrar(
    TipoEvento(
        tipo="dashboard.alert.fired",
        version=1,
        productor="analytics",
        descripcion=(
            "Una métrica ha cruzado su umbral. Lleva el valor y el umbral para "
            "que quien avise no tenga que volver a consultarlos"
        ),
        campos=("alerta_id", "nombre", "valor", "umbral"),
    )
)
DASHBOARD_ALERT_CLEARED = registrar(
    TipoEvento(
        tipo="dashboard.alert.cleared",
        version=1,
        productor="analytics",
        descripcion=(
            "Una alerta vuelve al verde. Se emite porque quien recibió el aviso "
            "merece saber que ya está: sin el cierre, cada alerta deja una "
            "preocupación abierta que nadie retira"
        ),
        campos=("alerta_id", "nombre", "valor"),
    )
)


# ────────────────────────────── integration ───────────────────────────────
# Eventos del seguimiento de encargos externos (Anexo B del catálogo).
#
# Los cuatro son **públicos**: el sentido de seguir un encargo es que alguien
# reaccione —avisar al cliente, abrir un caso, reclamar al proveedor—, y eso pasa
# casi siempre fuera del CRM. Un evento interno aquí obligaría a sondear la API
# para enterarse de lo que ya sabemos.

INTEGRATION_RECORDS_RECEIVED = registrar(
    TipoEvento(
        tipo="integration.records.received",
        version=1,
        productor="integration",
        descripcion=(
            "Una operación programada ha traído registros nuevos de un sistema "
            "externo y han aterrizado. Es público porque el sentido de leer un "
            "maestro ajeno es que alguien haga algo con él, y quien lo hace casi "
            "nunca es este servicio: sin evento habría que sondear la API para "
            "enterarse de lo que ya sabemos. Lleva el recuento de nuevos y de "
            "repetidos —no los registros— porque una vuelta puede traer diez mil "
            "y un evento no es un medio de transporte de datos."
        ),
        campos=("operacion", "nuevos", "repetidos"),
    )
)

ORDER_TRACKED_CREATED = registrar(
    TipoEvento(
        tipo="order.tracked.created",
        version=1,
        productor="integration",
        descripcion="Se ha encargado algo a un tercero y empieza a seguirse",
        campos=("encargo_id", "referencia", "proveedor"),
    )
)
ORDER_TRACKED_UPDATED = registrar(
    TipoEvento(
        tipo="order.tracked.updated",
        version=1,
        productor="integration",
        descripcion="El proveedor ha movido el encargo a otro estado",
        campos=("encargo_id", "referencia", "estado"),
    )
)
ORDER_TRACKED_INCIDENT = registrar(
    TipoEvento(
        tipo="order.tracked.incident",
        version=1,
        productor="integration",
        descripcion=(
            "Algo ha ido mal en el encargo. Se emite tanto si lo dice el "
            "proveedor como si lo abre una persona: quien escucha quiere "
            "enterarse igual, y distinguir el origen solo le obligaría a "
            "suscribirse a dos cosas para hacer lo mismo"
        ),
        campos=("encargo_id", "referencia", "proveedor"),
    )
)
ORDER_TRACKED_SILENT = registrar(
    TipoEvento(
        tipo="order.tracked.silent",
        version=1,
        productor="integration",
        descripcion=(
            "El proveedor lleva demasiado sin decir nada de un encargo abierto. "
            "Es un evento y no un informe porque el silencio hay que empujarlo: "
            "nadie entra a mirar una lista de encargos que parecen ir bien"
        ),
        campos=("encargo_id", "referencia", "proveedor", "horas_sin_novedad"),
    )
)


# ── Firma electrónica (CRM-06.01.02) ──────────────────────────────────────

SIGNATURE_ENVELOPE_SENT = registrar(
    TipoEvento(
        tipo="signature.envelope.sent",
        version=1,
        productor="integration",
        descripcion="Un documento ha salido a firmar",
        campos=("sobre_id", "referencia", "proveedor", "nivel"),
    )
)
SIGNATURE_ENVELOPE_COMPLETED = registrar(
    TipoEvento(
        tipo="signature.envelope.completed",
        version=1,
        productor="integration",
        descripcion=(
            "Han firmado todos. Lleva el registro que lo originó porque lo que "
            "desbloquea una firma vive fuera de aquí: la oportunidad avanza, el "
            "contrato entra en vigor, el pedido sale"
        ),
        campos=("sobre_id", "referencia", "objeto_origen", "objeto_origen_id"),
    )
)
SIGNATURE_ENVELOPE_REJECTED = registrar(
    TipoEvento(
        tipo="signature.envelope.rejected",
        version=1,
        productor="integration",
        descripcion="Alguien ha rechazado firmar, con su motivo",
        campos=("sobre_id", "referencia", "objeto_origen", "motivo"),
    )
)
SIGNATURE_ENVELOPE_CANCELLED = registrar(
    TipoEvento(
        tipo="signature.envelope.cancelled",
        version=1,
        productor="integration",
        descripcion="Se ha cancelado un sobre en curso, con su motivo",
        campos=("sobre_id", "referencia", "motivo"),
    )
)
SIGNATURE_ENVELOPE_EXPIRED = registrar(
    TipoEvento(
        tipo="signature.envelope.expired",
        version=1,
        productor="integration",
        descripcion=(
            "Un sobre ha pasado su plazo sin completarse. Es un evento y no una "
            "lista porque lo que caduca hay que empujarlo: nadie entra a mirar "
            "una pantalla de sobres que parecen en curso"
        ),
        campos=("sobre_id", "referencia", "objeto_origen"),
    )
)
SIGNATURE_REMINDER_SENT = registrar(
    TipoEvento(
        tipo="signature.reminder.sent",
        version=1,
        productor="integration",
        descripcion="Se ha recordado a quien tiene la firma pendiente",
        campos=("sobre_id", "referencia", "destinatarios"),
    )
)

DEVICE_ALERT = registrar(
    TipoEvento(
        tipo="device.alert",
        version=1,
        productor="integration",
        descripcion=(
            "Una lectura de dispositivo ha cruzado el umbral de una regla "
            "(CRM-04.04.02.05). El caso, si lo hay, lo abre el servicio dueño por "
            "comando: este evento dice que saltó, no que exista un caso"
        ),
        campos=("dispositivo_id", "regla", "severidad"),
    )
)

CONNECTOR_INSTALLED = registrar(
    TipoEvento(
        tipo="connector.installed",
        version=1,
        productor="integration",
        descripcion=(
            "Un tenant ha instalado un conector del catálogo (CRM-00.03.04.10). "
            "Lleva la versión porque es lo que decide con qué está funcionando ese "
            "tenant, que no tiene por qué ser la última publicada"
        ),
        campos=("clave", "version"),
    )
)
INTERACTION_RECORDED = registrar(
    TipoEvento(
        tipo="interaction.recorded",
        version=1,
        productor="integration",
        descripcion=(
            "Se ha registrado una interacción llegada por un canal sin interfaz "
            "(CRM-01.02.01.04). `atribuida` dice si se pudo colgar de alguien: lo "
            "que no se atribuye no es basura, es un contacto que falta"
        ),
        campos=("interaccion_id", "canal", "atribuida"),
    )
)


# ────────────────────────────── intelligence ──────────────────────────────
# Eventos del servicio de inteligencia (Anexo B del catálogo).

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
ACCOUNT_HEALTH_SCORED = registrar(
    TipoEvento(
        tipo="account.health.scored",
        version=1,
        productor="intelligence",
        descripcion=(
            "Se ha medido la salud de una cuenta (CRM-01.01.05.07). Lo consume "
            "`party` para poder enseñarlo en la ficha sin leer el esquema de "
            "este servicio. Va con su fiabilidad dentro: una salud calculada con "
            "la mitad de las señales no es un dato y quien la pinte tiene que "
            "poder decirlo"
        ),
        campos=("cuenta_id", "puntuacion", "nivel", "fiable", "motivo", "medida_at"),
    )
)


# ─────────────────────────────── marketing ────────────────────────────────
# Eventos de recorridos y preferencias (Anexo B del catálogo).
#
# `journey.entered` y `journey.exited` estaban prometidos en el Anexo B desde el
# principio y no los declaraba nadie: un evento prometido y no emitido es una
# integración que nunca recibe nada y un equipo buscando el fallo en su lado.

JOURNEY_ENTERED = registrar(
    TipoEvento(
        tipo="journey.entered",
        version=1,
        productor="marketing",
        descripcion="Alguien ha entrado en un recorrido",
        campos=("recorrido", "en_recorrido_id", "objeto_id"),
    )
)
JOURNEY_EXITED = registrar(
    TipoEvento(
        tipo="journey.exited",
        version=1,
        productor="marketing",
        descripcion=(
            "Alguien sale de un recorrido, con su motivo. El motivo importa más "
            "que la salida: «conversión» y «caducado» son el éxito y el fracaso "
            "del mismo recorrido"
        ),
        campos=("en_recorrido_id", "recorrido_id", "objeto_id", "motivo"),
    )
)
JOURNEY_ACTION_DUE = registrar(
    TipoEvento(
        tipo="journey.action.due",
        version=1,
        productor="marketing",
        descripcion=(
            "Toca ejecutar una acción de un recorrido. Quien la ejecute recibe ya "
            "comprobadas la supresión y la fatiga: si tuviera que comprobarlas él, "
            "cada canal las comprobaría a su manera"
        ),
        campos=("en_recorrido_id", "recorrido", "nodo", "objeto_id"),
    )
)
PREFERENCES_CHANGED = registrar(
    TipoEvento(
        tipo="preferences.changed",
        version=1,
        productor="marketing",
        descripcion=(
            "Alguien ha cambiado lo que quiere recibir. Es público porque quien "
            "manda correos desde fuera del CRM tiene que enterarse en el momento, "
            "no en la próxima sincronización"
        ),
        campos=("email", "guardadas", "origen"),
    )
)

CHANNEL_OPTOUT = registrar(
    TipoEvento(
        tipo="channel.optout",
        version=1,
        productor="marketing",
        descripcion=(
            "Alguien se ha dado de baja por el propio canal —una palabra en un "
            "SMS, un bloqueo en WhatsApp—. Es público porque quien manda desde "
            "fuera tiene que dejar de mandar en el momento, no en la próxima "
            "sincronización"
        ),
        campos=("canal", "destino"),
    )
)


# ────────────────────────────── orchestrator ──────────────────────────────
# Eventos de aprobación (Anexo B del catálogo).
#
# Públicos: quien integra quiere enterarse de que algo está esperando su firma o de
# que ya se decidió, y casi siempre desde fuera del CRM —un correo, una app de
# mensajería, el ERP que espera el visto bueno para emitir el pedido—.

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


# ───────────────────────────────── party ──────────────────────────────────
# Eventos de dominio que publica el servicio `party` (Anexo B del catálogo).
#
# Se declaran aquí, en el servicio que los produce, y no en el núcleo: el dueño
# del evento es quien lo emite, y un evento publicado desde dos sitios deja de
# tener dueño y nadie se atreve a cambiarlo.
#
# La forma de `data` solo puede **crecer**. Añadir un campo opcional es compatible;
# quitarlo, renombrarlo o cambiarle el tipo exige publicar una versión nueva que
# conviva con la anterior. Un consumidor que se rompe porque el productor le quitó
# un campo es el fallo más caro de un sistema de eventos: aparece en producción, en
# otro equipo y días después del cambio.

ACCOUNT_CREATED = registrar(
    TipoEvento(
        tipo="account.created",
        version=1,
        productor="party",
        descripcion="Se ha dado de alta una cuenta",
        campos=("cuenta_id", "nombre"),
    )
)
CONTACT_PROCESSING_LIMITED = registrar(
    TipoEvento(
        tipo="contact.processing_limited",
        version=1,
        productor="party",
        descripcion=(
            "Una persona ha ejercido su derecho de limitación u oposición "
            "(CRM-02.04.02.05, CRM-02.04.02.04). Quien envíe algo en su nombre "
            "tiene que dejar de hacerlo: la limitación no sirve de nada si se "
            "queda en el servicio que la anotó"
        ),
        campos=("contacto_id", "tratamientos", "destinos", "motivo"),
    )
)
CONTACT_PROCESSING_LIFTED = registrar(
    TipoEvento(
        tipo="contact.processing_lifted",
        version=1,
        productor="party",
        descripcion=(
            "Se ha levantado la limitación. Va con su motivo: una limitación que "
            "desaparece sin rastro deja a nadie pudiendo decir desde cuándo se "
            "volvió a tratar"
        ),
        campos=("contacto_id", "destinos", "motivo"),
    )
)
ACCOUNT_MERGED = registrar(
    TipoEvento(
        tipo="account.merged",
        version=1,
        productor="party",
        descripcion=(
            "Dos cuentas se han fusionado. Quien guarde el identificador "
            "absorbido debe apuntar al superviviente: el absorbido sigue "
            "existiendo pero ya no se usa"
        ),
        campos=("superviviente_id", "absorbido_id"),
    )
)
CONTACT_CREATED = registrar(
    TipoEvento(
        tipo="contact.created",
        version=1,
        productor="party",
        descripcion="Se ha dado de alta un contacto",
        campos=("contacto_id", "nombre"),
    )
)
CONTACT_CONSENT_CHANGED = registrar(
    TipoEvento(
        tipo="contact.consent.changed",
        version=1,
        productor="party",
        descripcion=(
            "Ha cambiado el consentimiento de un contacto. **Hay que actuar "
            "sobre él**: una baja tiene que propagarse a todas las campañas en "
            "curso, no solo a las futuras"
        ),
        campos=("contacto_id", "finalidad", "canal", "concedido"),
    )
)
RECORD_MERGED = registrar(
    TipoEvento(
        tipo="record.merged",
        version=1,
        productor="party",
        descripcion="Se han fusionado dos registros de cualquier objeto de party",
        campos=("objeto", "superviviente_id", "absorbido_id"),
    )
)
ACTIVITY_COMPLETED = registrar(
    TipoEvento(
        tipo="activity.completed",
        version=1,
        productor="party",
        descripcion="Se ha completado una actividad (tarea, llamada, reunión o visita)",
        campos=("actividad_id", "tipo", "resultado"),
        # Interno: el volumen es alto y a un integrador rara vez le interesa cada
        # llamada registrada. Se puede abrir por tenant si alguien lo pide.
        publico=False,
    )
)
ACCOUNT_TEAM_ADDED = registrar(
    TipoEvento(
        tipo="account.team.added",
        version=1,
        productor="party",
        descripcion=(
            "Alguien entra en el equipo de una cuenta. Importa fuera de este "
            "servicio porque pertenecer al equipo DA VISIBILIDAD sobre la "
            "cuenta: quien audite quién puede ver qué necesita este hecho"
        ),
        campos=("cuenta_id", "usuario_id", "rol"),
    )
)
ACCOUNT_TEAM_REMOVED = registrar(
    TipoEvento(
        tipo="account.team.removed",
        version=1,
        productor="party",
        descripcion="Alguien sale del equipo de una cuenta y deja de verla",
        campos=("cuenta_id", "usuario_id", "rol"),
    )
)
ACTIVITY_ASSIGNED = registrar(
    TipoEvento(
        tipo="activity.assigned",
        version=1,
        productor="party",
        descripcion=(
            "Una actividad pasa a la lista de alguien. Importa avisar: una tarea "
            "que aparece en la lista de alguien sin que se entere se hace tarde"
        ),
        campos=("actividad_id", "asunto", "asignada_a", "vence_at"),
    )
)
ACTIVITY_DELEGATED = registrar(
    TipoEvento(
        tipo="activity.delegated",
        version=1,
        productor="party",
        descripcion=(
            "Una actividad se delega. Distinto de asignar: quien delega sigue "
            "siendo responsable de que se haga"
        ),
        campos=("actividad_id", "asunto", "asignada_a", "delegada_por"),
    )
)
ACTIVITY_REMINDER = registrar(
    TipoEvento(
        tipo="activity.reminder",
        version=1,
        productor="party",
        descripcion="Ha llegado la hora del recordatorio de una actividad",
        campos=("actividad_id", "asunto", "asignada_a", "vence_at"),
    )
)
ACTIVITY_RESCHEDULED = registrar(
    TipoEvento(
        tipo="activity.rescheduled",
        version=1,
        productor="party",
        descripcion=(
            "El sistema ha empujado la fecha de una tarea que nadie atendió "
            "(CRM-01.02.01.09). Va aparte del vencimiento a propósito: primero "
            "se avisa de que venció y luego de que se movió, porque moverla en "
            "silencio haría que no constara vencida nunca"
        ),
        campos=("actividad_id", "asunto", "asignada_a", "vencia_at", "vence_at", "veces"),
    )
)
ACTIVITY_OVERDUE = registrar(
    TipoEvento(
        tipo="activity.overdue",
        version=1,
        productor="party",
        descripcion=(
            "Una actividad ha pasado de plazo. Se emite UNA sola vez: un aviso "
            "diario de la misma tarea vencida enseña a ignorarlos todos"
        ),
        campos=("actividad_id", "asunto", "asignada_a", "delegada_por", "vence_at"),
    )
)

IDENTITY_LINKED = registrar(
    TipoEvento(
        tipo="identity.linked",
        version=1,
        productor="party",
        descripcion=(
            "Dos identidades se han declarado la misma persona (CRM-01.01.05.02). "
            "`modo` dice si lo decidió alguien o una regla: unir mal enseña a uno "
            "el historial de otro, y saber quién lo decidió es lo que permite "
            "revisarlo"
        ),
        campos=("principal_id", "secundario_id", "modo"),
    )
)


# ───────────────────────────────── sales ──────────────────────────────────
# Eventos de dominio de ventas (Anexo B del catálogo).

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
ORDER_ERP_CONFIRMED = registrar(
    TipoEvento(
        tipo="order.erp.confirmed",
        version=1,
        productor="integration",
        descripcion=(
            "El ERP ha aceptado el pedido y ha devuelto su referencia. Vuelve a "
            "ventas porque el estado del pedido es suyo: dejarlo en una traza de "
            "integración daría un pedido que figura «enviado» en ventas y "
            "confirmado en un sitio que nadie mira."
        ),
        campos=("pedido_id", "referencia_erp"),
    )
)
ORDER_ERP_REJECTED = registrar(
    TipoEvento(
        tipo="order.erp.rejected",
        version=1,
        productor="integration",
        descripcion=(
            "El ERP ha rechazado el pedido. Es público y vuelve a ventas por lo "
            "mismo: un traspaso que se cierra al enviar es cómo se descubre en el "
            "cierre de mes que faltan pedidos."
        ),
        campos=("pedido_id", "error"),
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


# ──────────────────────────────── service ─────────────────────────────────
# Eventos del servicio de campo y de los activos (Anexo B del catálogo).
#
# Se declaran aquí y no en cada módulo porque el contrato es del servicio: quien
# consume `workorder.completed` no sabe —ni tiene por qué— en qué fichero se emite.

ASSET_INSTALLED = registrar(
    TipoEvento(
        tipo="asset.installed",
        version=1,
        productor="service",
        descripcion=(
            "Se ha dado de alta un activo instalado. `cuenta_id` viaja con él "
            "cuando se conoce, pero no está entre los campos prometidos: hay "
            "altas hechas en casa del cliente sin cuenta todavía, y prometerlo "
            "para mandarlo vacío haría que el consumidor se fiara de un dato "
            "que a veces no está"
        ),
        campos=("activo_id",),
    )
)
WORKORDER_CREATED = registrar(
    TipoEvento(
        tipo="workorder.created",
        version=1,
        productor="service",
        descripcion="Se ha creado una orden de trabajo de campo",
        campos=("orden_id", "tipo"),
    )
)
WORKORDER_ASSIGNED = registrar(
    TipoEvento(
        tipo="workorder.assigned",
        version=1,
        productor="service",
        descripcion=(
            "Una orden tiene técnico. Es el evento con el que se avisa al móvil "
            "de que tiene trabajo nuevo que descargarse antes de salir"
        ),
        campos=("orden_id", "tecnico_id"),
    )
)
WORKORDER_COMPLETED = registrar(
    TipoEvento(
        tipo="workorder.completed",
        version=1,
        productor="service",
        descripcion=(
            "El trabajo está hecho. Lo escucha quien factura y quien reclama al "
            "fabricante: la orden ya trae repartido lo cubierto y lo no cubierto"
        ),
        campos=("orden_id", "tipo"),
    )
)

RETURN_REQUESTED = registrar(
    TipoEvento(
        tipo="return.requested",
        version=1,
        productor="service",
        descripcion="Un cliente ha pedido devolver algo; todavía no está autorizado",
        campos=("devolucion_id", "motivo"),
    )
)
RETURN_AUTHORIZED = registrar(
    TipoEvento(
        tipo="return.authorized",
        version=1,
        productor="service",
        descripcion=(
            "Devolución autorizada, con su número de RMA: es lo que el almacén "
            "necesita para reconocer el paquete cuando llegue"
        ),
        campos=("devolucion_id", "codigo"),
    )
)
RETURN_CLOSED = registrar(
    TipoEvento(
        tipo="return.closed",
        version=1,
        productor="service",
        descripcion="Devolución cerrada, con la disposición del material",
        campos=("devolucion_id", "disposicion"),
    )
)
REFUND_REQUESTED = registrar(
    TipoEvento(
        tipo="refund.requested",
        version=1,
        productor="service",
        descripcion=(
            "Se ha decidido un abono. Lo **emite quien factura**: este evento pide, "
            "no afirma que el dinero haya salido"
        ),
        campos=("devolucion_id", "resolucion_id", "importe"),
    )
)
COMPLAINT_OPENED = registrar(
    TipoEvento(
        tipo="complaint.opened",
        version=1,
        productor="service",
        descripcion="Expediente de reclamación abierto, con su fecha de vencimiento legal",
        campos=("expediente_id", "tipo", "vence_at"),
    )
)
COMPLAINT_ANSWERED = registrar(
    TipoEvento(
        tipo="complaint.answered",
        version=1,
        productor="service",
        descripcion="Expediente contestado, diciendo si se llegó dentro del plazo",
        campos=("expediente_id", "en_plazo"),
    )
)
PROBLEM_OPENED = registrar(
    TipoEvento(
        tipo="problem.opened",
        version=1,
        productor="service",
        descripcion="Se ha abierto un problema: una causa que produce casos",
        campos=("problema_id", "severidad"),
    )
)
PROBLEM_RESOLVED = registrar(
    TipoEvento(
        tipo="problem.resolved",
        version=1,
        productor="service",
        descripcion="Problema resuelto con solución definitiva, y cuántos casos se cerraron con él",
        campos=("problema_id", "casos_cerrados"),
    )
)
PROBLEM_COMMUNICATED = registrar(
    TipoEvento(
        tipo="problem.communicated",
        version=1,
        productor="service",
        descripcion=(
            "Se ha comunicado algo a los afectados por un problema, con su alcance: "
            "«ya avisamos» sin fecha ni alcance es lo mismo que no haber avisado"
        ),
        campos=("problema_id", "tipo", "casos_alcanzados"),
    )
)


# ───────────────────── los que se emitían sin declarar ─────────────────────
# Quince tipos que el código publica y que no estaban en ningún `eventos.py`:
# entre ellos, la familia `case.*` entera, que es el ciclo de vida de un caso.
# Se emitían, viajaban por el bus y llegaban a los consumidores internos, pero
# no existían para quien mira desde fuera: ni suscribibles por webhook, ni en
# el AsyncAPI. Los encontró el gate `test_catalogo_eventos.py` el día que se
# escribió, que es exactamente para lo que está.

CASE_CREATED = registrar(
    TipoEvento(
        tipo="case.created",
        version=1,
        productor="service",
        descripcion="Se ha abierto un caso, venga del canal que venga",
        campos=("caso_id", "codigo", "prioridad", "cuenta_id", "campos"),
    )
)
CASE_ASSIGNED = registrar(
    TipoEvento(
        tipo="case.assigned",
        version=1,
        productor="service",
        descripcion="Un caso ha quedado asignado, con la regla de reparto que lo decidió",
        campos=("caso_id", "asignado_a", "regla"),
    )
)
CASE_FIRST_RESPONSE = registrar(
    TipoEvento(
        tipo="case.first_response",
        version=1,
        productor="service",
        descripcion=(
            "Primera respuesta al cliente, y si llegó dentro del plazo "
            "comprometido. Es el dato que mide el compromiso de servicio, no "
            "el cierre: un caso contestado en diez minutos y resuelto en tres "
            "días se vive de forma muy distinta a uno al revés"
        ),
        campos=("caso_id", "a_tiempo"),
    )
)
CASE_ESCALATED = registrar(
    TipoEvento(
        tipo="case.escalated",
        version=1,
        productor="service",
        descripcion="Una regla de escalado ha subido el caso de nivel o de prioridad",
        campos=("caso_id", "regla", "motivo", "avisar_a"),
    )
)
CASE_ESCALATED_HUMAN = registrar(
    TipoEvento(
        tipo="case.escalated.human",
        version=1,
        productor="service",
        descripcion=(
            "Una conversación atendida automáticamente pasa a una persona. Va "
            "aparte de `case.escalated` porque no es un problema de plazo: es "
            "que la máquina no ha sabido, y quien integra suele querer "
            "reaccionar distinto"
        ),
        campos=("conversacion_id", "caso_id", "motivo", "mensajes"),
    )
)
CASE_MESSAGE_RECEIVED = registrar(
    TipoEvento(
        tipo="case.message.received",
        version=1,
        productor="service",
        descripcion="Ha entrado un mensaje del cliente por un canal de servicio",
        campos=("conversacion_id", "caso_id", "canal", "nueva"),
    )
)
CASE_CLOSED = registrar(
    TipoEvento(
        tipo="case.closed",
        version=1,
        productor="service",
        descripcion="Se ha cerrado un caso, y si se incumplió el plazo de resolución",
        campos=("caso_id", "motivo", "incumplio_resolucion", "cuenta_id"),
    )
)
CASE_SURVEY_SENT = registrar(
    TipoEvento(
        tipo="case.survey.sent",
        version=1,
        productor="service",
        descripcion="Se ha enviado la encuesta de satisfacción de un caso",
        campos=("caso_id", "tipo", "encuesta_id"),
    )
)
CASE_SURVEY_ANSWERED = registrar(
    TipoEvento(
        tipo="case.survey.answered",
        version=1,
        productor="service",
        descripcion=(
            "El cliente ha contestado la encuesta. Lleva `detractor` resuelto "
            "para que quien reacciona no tenga que conocer el umbral de cada "
            "tipo de encuesta"
        ),
        campos=("caso_id", "tipo", "puntuacion", "detractor"),
    )
)
KNOWLEDGE_PUBLISHED = registrar(
    TipoEvento(
        tipo="knowledge.published",
        version=1,
        productor="service",
        descripcion="Un artículo de conocimiento queda publicado para una audiencia",
        campos=("articulo_id", "clave", "idioma", "version", "audiencia"),
    )
)
TERRITORY_PUBLISHED = registrar(
    TipoEvento(
        tipo="territory.published",
        version=1,
        productor="sales",
        descripcion="Se ha publicado una versión nueva del mapa de territorios",
        # Con la clave y la versión NO SE PUEDE REPLICAR NADA: quien lo recibe no
        # sabe ni el identificador, ni de quién cuelga, ni quién lo trabaja. El
        # evento se amplió y esta declaración se quedó atrás, con lo que el
        # contrato decía que `party` pedía tres campos que nadie publicaba.
        campos=("territorio", "version", "territorio_id", "padre_id", "usuarios"),
    )
)
MODULE_INSTALLED = registrar(
    TipoEvento(
        tipo="module.installed",
        version=1,
        productor="metadata",
        descripcion="Se ha instalado un módulo de extensión en el tenant",
        campos=("modulo", "version", "elementos", "conectores"),
    )
)
MODULE_UPDATED = registrar(
    TipoEvento(
        tipo="module.updated",
        version=1,
        productor="metadata",
        descripcion="Un módulo instalado ha pasado a otra versión",
        campos=("modulo", "version", "desde", "conectores"),
    )
)
MODULE_UNINSTALLED = registrar(
    TipoEvento(
        tipo="module.uninstalled",
        version=1,
        productor="metadata",
        descripcion="Se ha desinstalado un módulo, y si se borraron sus datos",
        campos=("modulo", "datos_borrados", "objetos"),
    )
)
AUTOMATIZACION_AVISO = registrar(
    TipoEvento(
        tipo="automatizacion.aviso",
        version=1,
        productor="automation",
        descripcion=(
            "Una automatización pide que se avise a alguien. Lo consume el "
            "servicio de identidad, que es quien sabe a quién llega según el "
            "seguimiento del registro"
        ),
        campos=("titulo", "cuerpo", "objeto_tipo", "objeto_id", "menciones"),
        # Interno: es el mecanismo por el que se construye la bandeja, no un
        # hecho de negocio. Sacarlo fuera ataría la implementación del aviso al
        # código de quien integra.
        publico=False,
    )
)
