"""Cómo resuelve `party` las vías de compartición que solo él conoce.

El equipo de cuenta (`CRM-01.01.01.10`) es una tabla de este servicio, así que
el núcleo no puede consultarla: registra aquí el resolutor y la vía «está en el
equipo de la cuenta» empieza a aplicar en los listados.

La jerarquía de mando **no** se resuelve aquí, y conviene decir por qué: vive en
la membresía del tenant, que es de `identity`, y ningún servicio lee el esquema
de otro. Hasta que se replique —como se replican los ajustes y la clave del
tenant— un responsable no ve por jerarquía las cuentas de su equipo en este
servicio. Ve las suyas, aquellas en cuyo equipo está, y lo que le compartan.
Está anotado en el manual y no escondido aquí.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.authz.visibilidad import registrar_resolutor
from sqlalchemy import select
from sqlalchemy.orm import Session


def equipos(db: Session, principal: Any, objeto: str) -> set[UUID]:
    """Cuentas en cuyo equipo está este usuario.

    Solo para el objeto `cuenta`: un contacto no tiene equipo propio. Devolver
    los identificadores de cuenta para el listado de contactos los filtraría
    contra la columna equivocada, que es la clase de error que enseña registros
    de más sin que nadie lo note.
    """
    if objeto != "cuenta":
        return set()

    from services.party.modelos import MiembroEquipoCuenta

    return {
        fila
        for fila in db.execute(
            select(MiembroEquipoCuenta.cuenta_id).where(
                MiembroEquipoCuenta.tenant_id == principal.tenant_id,
                MiembroEquipoCuenta.usuario_id == principal.id,
            )
        ).scalars()
    }


registrar_resolutor("equipos", equipos)
