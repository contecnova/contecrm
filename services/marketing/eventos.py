"""Eventos de recorridos y preferencias (Anexo B del catálogo).

`journey.entered` y `journey.exited` estaban prometidos en el Anexo B desde el
principio y no los declaraba nadie: un evento prometido y no emitido es una
integración que nunca recibe nada y un equipo buscando el fallo en su lado.
"""

from __future__ import annotations

from crmcore.events.catalogo import TipoEvento, registrar

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
