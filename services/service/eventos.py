"""Eventos del servicio de campo y de los activos (Anexo B del catálogo).

Se declaran aquí y no en cada módulo porque el contrato es del servicio: quien
consume `workorder.completed` no sabe —ni tiene por qué— en qué fichero se emite.
"""

from __future__ import annotations

from crmcore.events.catalogo import TipoEvento, registrar

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
