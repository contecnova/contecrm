"""Cómo resuelve `party` las vías de compartición que solo él conoce.

El equipo de cuenta (`CRM-01.01.01.10`) es una tabla de este servicio, así que
el núcleo no puede consultarla: registra aquí el resolutor y la vía «está en el
equipo de la cuenta» empieza a aplicar en los listados.

Y la **jerarquía de mando** también aplica ya (`CRM-00.05.02.12`). Vive en la
membresía del tenant, que es de `identity`, así que no se consulta: se **replica**
por evento a este esquema, igual que se replican los ajustes en caliente y la
clave del tenant. Un responsable ve ahora, además de lo suyo y de aquello en cuyo
equipo está, lo de quien depende de él.

La réplica puede ir con retraso si el evento no llega, y eso se nota en la
consulta de frescura. El retraso es molesto —un jefe que acaba de heredar un
equipo no lo ve todavía— y es el lado correcto en el que equivocarse: lo grave
sería lo contrario, que alguien que ya no manda siguiera viendo.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.authz.visibilidad import registrar_resolutor
from crmcore.fechas import hoy
from sqlalchemy import select
from sqlalchemy.orm import Session


def equipos(db: Session, principal: Any, objeto: str) -> dict[UUID, str]:
    """Cuentas en cuyo equipo está este usuario, con el acceso que le da cada una.

    Solo para el objeto `cuenta`: un contacto no tiene equipo propio. Devolver
    los identificadores de cuenta para el listado de contactos los filtraría
    contra la columna equivocada, que es la clase de error que enseña registros
    de más sin que nadie lo note.

    **Se respeta la vigencia.** El modelo tiene `desde` y `hasta` desde el
    principio y la primera versión de esto los ignoraba: un miembro que salió
    del equipo hace un año seguía viendo la cuenta. Una pertenencia con fecha de
    fin que no caduca no es una pertenencia temporal, es una permanente con una
    fecha decorativa.
    """
    if objeto != "cuenta":
        return {}

    from sqlalchemy import or_

    from services.party.modelos import MiembroEquipoCuenta

    dia = hoy(db)
    filas = db.execute(
        select(MiembroEquipoCuenta.cuenta_id, MiembroEquipoCuenta.acceso).where(
            MiembroEquipoCuenta.tenant_id == principal.tenant_id,
            MiembroEquipoCuenta.usuario_id == principal.id,
            or_(MiembroEquipoCuenta.desde.is_(None), MiembroEquipoCuenta.desde <= dia),
            or_(MiembroEquipoCuenta.hasta.is_(None), MiembroEquipoCuenta.hasta >= dia),
        )
    ).all()

    # Con varias filas para la misma cuenta —alguien puede ser KAM y técnico—
    # gana el acceso más amplio: las vías de compartición suman, nunca restan.
    acceso_por_cuenta: dict[UUID, str] = {}
    for cuenta_id, acceso in filas:
        if acceso_por_cuenta.get(cuenta_id) != "escritura":
            acceso_por_cuenta[cuenta_id] = acceso
    return acceso_por_cuenta


registrar_resolutor("equipos", equipos)


# La jerarquía replicada, conectada a la visibilidad. Sin esta llamada las tablas
# estarían llenas y los listados seguirían sin aplicar la jerarquía — que es
# exactamente el hueco que esto cierra.
from crmcore.authz.jerarquia import registrar_resolutores  # noqa: E402

registrar_resolutores()
