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
