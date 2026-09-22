"""Eventos del seguimiento de encargos externos (Anexo B del catálogo).

Los cuatro son **públicos**: el sentido de seguir un encargo es que alguien
reaccione —avisar al cliente, abrir un caso, reclamar al proveedor—, y eso pasa
casi siempre fuera del CRM. Un evento interno aquí obligaría a sondear la API
para enterarse de lo que ya sabemos.
"""

from __future__ import annotations

from crmcore.events.catalogo import TipoEvento, registrar

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
