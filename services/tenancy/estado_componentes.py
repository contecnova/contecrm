"""El componente de cuotas de la página de estado (CRM-00.06.01.06).

Vive aquí y no en el núcleo porque la tabla de consumo y el plan contratado son
de `tenancy`: ningún otro servicio puede consultarlos, y el gate de arquitectura
lo impide — con razón. La primera versión de esta página los leía desde
`tenancy` junto con los webhooks de `eventing`, y el gate la paró.

Es el componente que más veces explica una lentitud percibida sin avería: el
cliente está tocando su tope y el sistema le está limitando, que es lo que tiene
que hacer. Decírselo aquí evita el ticket.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.datos.estado import registrar_componente
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.tenancy.modelos import Consumo
from services.tenancy.servicio import limite_de


@registrar_componente
def cuotas(db: Session, tenant_id: UUID) -> dict[str, Any] | None:
    filas = db.execute(select(Consumo).where(Consumo.tenant_id == tenant_id)).scalars().all()
    if not filas:
        return None

    cerca: list[str] = []
    pasados: list[str] = []
    for fila in filas:
        # El tope no está en la fila de consumo: sale del plan contratado. Es lo
        # correcto —un cambio de plan cambia el tope sin reescribir el
        # histórico— y obliga a resolverlo aquí.
        tope = limite_de(db, tenant_id, fila.metrica)
        usado = int(fila.valor or 0)
        if tope <= 0:
            # Sin límite contratado para esa métrica: se mide, no se acota.
            continue
        proporcion = usado / tope
        if proporcion >= 1:
            pasados.append(fila.metrica)
        elif proporcion >= 0.9:
            cerca.append(fila.metrica)

    if pasados:
        estado, detalle = "caido", f"Límite superado en: {', '.join(sorted(pasados))}"
    elif cerca:
        estado, detalle = "degradado", f"Por encima del 90 % en: {', '.join(sorted(cerca))}"
    else:
        estado, detalle = "operativo", "Dentro de los límites"
    return {
        "componente": "cuotas",
        "estado": estado,
        "detalle": detalle,
        "al_limite": sorted(pasados),
        "cerca_del_limite": sorted(cerca),
    }
