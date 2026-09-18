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
