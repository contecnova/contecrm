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
from sqlalchemy.orm import Session


@registrar_componente
def cuotas(db: Session, tenant_id: UUID) -> dict[str, Any] | None:
    """Si este tenant está cerca de alguno de sus topes, o ya se pasó.

    **Esto no podía decir que nadie se hubiera pasado.** Leía una tabla de
    contadores que sólo escribía una función sin llamantes: estaba siempre vacía,
    así que el componente devolvía `None` —«no hay nada que contar»— en todos los
    despliegues y a todas horas. La página de estado de la plataforma no podía
    avisar de una cuota agotada ni queriendo.

    Ahora sale de los medidores registrados, que es de donde sale la cuota que de
    verdad corta.
    """
    from crmcore.consumo import medido_aqui

    filas = [f for f in medido_aqui(db, tenant_id) if f.get("legible")]
    if not filas:
        return None

    cerca: list[str] = []
    pasados: list[str] = []
    for fila in filas:
        if fila.get("sin_limite"):
            # Sin límite contratado para esa métrica: se mide, no se acota.
            continue
        proporcion = float(fila.get("pct") or 0.0) / 100
        if proporcion >= 1:
            pasados.append(fila["metrica"])
        elif proporcion >= 0.9:
            cerca.append(fila["metrica"])

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
