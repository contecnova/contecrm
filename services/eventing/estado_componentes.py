"""El componente de webhooks de la página de estado (CRM-00.06.01.06).

Lo aporta `eventing` porque la tabla de suscripciones es suya. Un servicio no
lee las tablas de otro, así que la página se compone: cada servicio publica la
suya y el gateway las junta.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.datos.estado import registrar_componente
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.eventing.modelos import Suscripcion


@registrar_componente
def webhooks(db: Session, tenant_id: UUID) -> dict[str, Any] | None:
    """Devuelve `None` si el tenant no tiene webhooks.

    Un componente que no usa no debe aparecer en su página: una lista con cosas
    que no le importan hace que deje de mirarla.
    """
    filas = (
        db.execute(select(Suscripcion).where(Suscripcion.tenant_id == tenant_id)).scalars().all()
    )
    if not filas:
        return None

    apagadas = [f for f in filas if not f.activa]
    fallando = [f for f in filas if f.activa and (f.fallos_consecutivos or 0) > 0]
    if apagadas:
        estado = "caido"
        detalle = f"{len(apagadas)} suscripción(es) desactivadas por fallos repetidos"
    elif fallando:
        estado = "degradado"
        detalle = f"{len(fallando)} suscripción(es) con entregas fallando"
    else:
        estado, detalle = "operativo", f"{len(filas)} suscripción(es) al día"
    return {
        "componente": "webhooks",
        "estado": estado,
        "detalle": detalle,
        "suscripciones": len(filas),
        "desactivadas": len(apagadas),
    }
