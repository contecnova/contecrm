"""Lo que el ERP contesta de un pedido, anotado donde vive el pedido
(CRM-03.03.02.11).

`enviar_a_erp` deja el pedido **esperando confirmación** a propósito: no se da
por bueno porque la llamada no diera error, porque el ERP puede aceptar el
mensaje y rechazar el pedido después. Lo que faltaba era quien recoge esa
respuesta — hasta el 05-10-2026 el pedido se quedaba en «enviado_erp» para
siempre, y eso se descubre en el cierre de mes, que es cuando ya no se arregla.

Viene por el bus y no por una llamada de `integration` a este esquema: el estado
del pedido es de ventas, y ningún servicio escribe en el de otro.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.logging import get_logger

logger = get_logger(__name__)


async def consumir_respuesta_erp(mensaje: Any) -> None:
    """Anota la confirmación o el rechazo del ERP sobre un pedido."""
    from crmcore.db.uow import unidad_de_trabajo

    from services.sales.presupuestos import confirmar_desde_erp

    tipo = str(getattr(mensaje, "tipo", "") or (mensaje or {}).get("tipo") or "")
    datos = dict(getattr(mensaje, "data", None) or (mensaje or {}).get("data") or {})
    tenant = str(getattr(mensaje, "tenant_id", "") or (mensaje or {}).get("tenant_id") or "")
    pedido_id = str(datos.get("pedido_id") or "")
    if not tenant or not pedido_id or not tipo.startswith("order.erp."):
        return

    aceptado = tipo.endswith(".confirmed")
    with unidad_de_trabajo(UUID(tenant), sistema=True) as uow:
        confirmar_desde_erp(
            uow,
            UUID(pedido_id),
            aceptado=aceptado,
            referencia_erp=str(datos.get("referencia_erp") or ""),
            error=str(datos.get("error") or ""),
            respuesta=datos,
        )
    logger.info("pedido.respuesta_erp", pedido=pedido_id, aceptado=aceptado)
