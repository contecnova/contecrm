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
