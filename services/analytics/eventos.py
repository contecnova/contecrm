"""Eventos de informes (Anexo B del catálogo).

Los dos son públicos, y el de fallo especialmente: un informe que deja de llegar
no se echa de menos —la gente supone que no había nada que contar—, así que el
fallo tiene que salir del sistema y llegar a alguien.
"""

from __future__ import annotations

from crmcore.events.catalogo import TipoEvento, registrar

REPORT_DELIVERED = registrar(
    TipoEvento(
        tipo="report.delivered",
        version=1,
        productor="analytics",
        descripcion="Un informe programado se ha ejecutado y sale hacia sus destinatarios",
        campos=("informe_id", "programacion_id", "formato", "filas"),
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
