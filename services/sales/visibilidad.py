"""Cómo resuelve `sales` las vías de compartición que solo él conoce.

La **jerarquía de mando** ya aplica en los listados de este servicio
(`CRM-00.05.02.12`). Vive en la membresía del tenant, que es de `identity`, así
que no se consulta: se **replica** por evento a este esquema, igual que los
ajustes en caliente y la clave del tenant. Un responsable ve, además de sus
oportunidades, las de quien depende de él.

Y los **territorios condicionan la visibilidad** (`CRM-00.05.02.07`): quien lleva
un territorio ve lo de ese territorio y lo de los que cuelgan de él. Hacia abajo
y no hacia arriba — al revés es el error clásico, y se nota tarde: cuando alguien
pregunta por qué un comercial veía la cartera entera.

La réplica puede ir con retraso si el evento no llega. El retraso es molesto y es
el lado correcto en el que equivocarse: lo grave sería lo contrario, que alguien
que ya no lleva un territorio siguiera viendo su cartera. Por eso salir de un
territorio se aplica por su propio camino y no espera a que llegue un alta que lo
sustituya.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.authz.jerarquia import registrar_resolutores, territorios_de
from crmcore.authz.visibilidad import registrar_resolutor
from sqlalchemy import select
from sqlalchemy.orm import Session


def equipos(db: Session, principal: Any, objeto: str) -> dict[UUID, str]:
    """Oportunidades de las cuentas cuyo territorio lleva este usuario.

    El territorio se asigna a la **cuenta**, no a la oportunidad: una empresa
    está en una zona y sus negocios van detrás. Filtrar por un territorio en la
    oportunidad habría sido más cómodo y habría dejado fuera exactamente las
    oportunidades que importan — las de las cuentas que uno lleva.

    Se devuelve por la vía de «equipos» porque es la que el filtro sabe traducir
    a un `IN` sobre identificadores de registro, y lo que hace falta es
    justamente eso: acotar el listado sin una consulta por fila.

    Solo para `oportunidad`: una lista de precios no tiene territorio, y devolver
    identificadores de oportunidad para otro objeto los filtraría contra la
    columna equivocada — la clase de error que enseña registros de otro.
    """
    if objeto != "oportunidad":
        return {}
    if principal is None or principal.id is None or principal.tenant_id is None:
        return {}

    territorios = territorios_de(db, principal.tenant_id, principal.id)
    if not territorios:
        return {}

    from services.sales.modelos import Oportunidad
    from services.sales.territorios import AsignacionTerritorio

    cuentas = (
        select(AsignacionTerritorio.cuenta_id)
        .where(
            AsignacionTerritorio.tenant_id == principal.tenant_id,
            AsignacionTerritorio.territorio_id.in_(territorios),
        )
        .scalar_subquery()
    )
    filas = (
        db.execute(
            select(Oportunidad.id).where(
                Oportunidad.tenant_id == principal.tenant_id,
                Oportunidad.cuenta_id.in_(cuentas),
            )
        )
        .scalars()
        .all()
    )
    # Lectura y no escritura: llevar un territorio deja ver lo que pasa en él;
    # decidir sobre una oportunidad concreta sigue siendo de su dueño.
    return {fila: "lectura" for fila in filas}


registrar_resolutor("equipos", equipos)
registrar_resolutores()
