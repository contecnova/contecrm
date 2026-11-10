"""Abre la aprobación de un presupuesto que se pasa de la matriz de descuentos.

`sales` para el presupuesto en «en aprobación» y avisa con
`quote.approval.needed`; la aprobación la lleva este servicio, que tiene el
motor (quórum, delegaciones, plazos, decidir desde el correo). Hasta el
09-11-2026 nadie escuchaba ese aviso: el presupuesto se quedaba parado para
siempre y no había forma de aprobarlo.

Quién aprueba sale del ajuste `aprobacion_presupuesto_etapas` —de serie, el
superior de quien lo envía—. Si la cadena no resuelve a nadie, **no se
aprueba sola**: se contesta que no hay quién, y `sales` lo devuelve a
borrador con ese motivo.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.errors import CrmError
from crmcore.logging import get_logger

logger = get_logger(__name__)


async def consumir(mensaje: Any) -> None:
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.runtime import settings as rt
    from crmcore.tenancy.context import con_contexto

    from services.orchestrator import aprobaciones as apr

    if str(getattr(mensaje, "tipo", "") or "") != "quote.approval.needed":
        return
    bruto = getattr(mensaje, "tenant_id", None)
    datos = getattr(mensaje, "data", None) or {}
    presupuesto_id = datos.get("presupuesto_id")
    if not bruto or not presupuesto_id:
        logger.warning("aprobacion_presupuesto.evento_incompleto")
        return
    tenant_id = UUID(str(bruto))
    solicitante = datos.get("solicitante_id") or None

    with con_contexto(tenant_id=tenant_id, origen="bus"), unidad_de_trabajo(tenant_id) as uow:
        etapas = rt.efectivo("aprobacion_presupuesto_etapas", uow.db) or []
        motivos = datos.get("motivos") or []
        try:
            # En un punto de guardado: `crear` escribe la aprobación ANTES de
            # resolver quién aprueba, y si eso falla lo escrito se quedaba —el
            # `except` confirma la misma transacción para avisar a sales—.
            # Medido el 10-11-2026 con el bus de verdad: el presupuesto volvía
            # a borrador «sin aprobadores» y en la bandeja quedaba una
            # aprobación pendiente que nadie podía resolver.
            with uow.db.begin_nested():
                apr.crear(
                    uow,
                    politica="presupuesto",
                    objeto="presupuesto",
                    objeto_id=UUID(str(presupuesto_id)),
                    etapas=list(etapas),
                    contexto={k: v for k, v in datos.items() if k != "solicitante_id"},
                    solicitante_id=UUID(str(solicitante)) if solicitante else None,
                    titulo=f"Presupuesto {datos.get('numero', '')}: "
                    + "; ".join(map(str, motivos)),
                )
        except CrmError as exc:
            # Nadie a quien pedírselo —cadena vacía, o quien lo envía no está en
            # el organigrama—: se dice y se devuelve, no se aprueba solo. Dejar
            # que el error suba haría reintentar el mensaje sin fin con el
            # presupuesto parado.
            logger.warning(
                "aprobacion_presupuesto.sin_aprobadores",
                presupuesto_id=str(presupuesto_id),
                motivo=str(exc),
            )
            uow.emitir(
                "approval.decided",
                subject=("presupuesto", UUID(str(presupuesto_id))),
                data={
                    "solicitud_id": "",
                    "objeto": "presupuesto",
                    "objeto_id": str(presupuesto_id),
                    "estado": "sin_aprobadores",
                    "motivo": str(exc),
                },
            )
