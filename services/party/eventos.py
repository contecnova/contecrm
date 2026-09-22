"""Eventos de dominio que publica el servicio `party` (Anexo B del catálogo).

Se declaran aquí, en el servicio que los produce, y no en el núcleo: el dueño
del evento es quien lo emite, y un evento publicado desde dos sitios deja de
tener dueño y nadie se atreve a cambiarlo.

La forma de `data` solo puede **crecer**. Añadir un campo opcional es compatible;
quitarlo, renombrarlo o cambiarle el tipo exige publicar una versión nueva que
conviva con la anterior. Un consumidor que se rompe porque el productor le quitó
un campo es el fallo más caro de un sistema de eventos: aparece en producción, en
otro equipo y días después del cambio.
"""

from __future__ import annotations

from crmcore.events.catalogo import TipoEvento, registrar

ACCOUNT_CREATED = registrar(
    TipoEvento(
        tipo="account.created",
        version=1,
        productor="party",
        descripcion="Se ha dado de alta una cuenta",
        campos=("cuenta_id", "nombre"),
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
