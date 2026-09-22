"""Comandos que atiende este servicio (CRM-00.03.03.03)."""

from __future__ import annotations

from typing import Any

from crmcore.logging import get_logger

logger = get_logger(__name__)


async def consumir_comando(mensaje: Any) -> None:
    """Ejecuta un comando dirigido a un objeto de este servicio.

    Lo que no es para aquí se ignora sin ruido: todos los servicios escuchan el
    mismo bus, y tratar «no es mío» como un error llenaría la cola de fallidos
    con mensajes correctos.
    """
    from uuid import UUID

    from crmcore.bus.comandos import despachar
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto

    import services.service.comandos  # noqa: F401 — registra los manejadores

    bruto = getattr(mensaje, "tenant_id", None) or (
        mensaje.get("tenant_id") if isinstance(mensaje, dict) else None
    )
    if not bruto:
        logger.warning("comando.sin_tenant", tipo=getattr(mensaje, "tipo", "?"))
        return
    tenant_id = UUID(str(bruto))
    with con_contexto(tenant_id=tenant_id), unidad_de_trabajo(tenant_id) as uow:
        await despachar(uow.db, mensaje)
