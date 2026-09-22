"""Publicar la posición de una persona en la organización (CRM-00.03.05.07).

Quién manda sobre quién y quién tiene qué rol vive en `membresias`, dentro del
esquema de `identity`. Quien lo necesita para decidir **a quién le toca aprobar**
es el orquestador, y ningún servicio lee el esquema de otro: por eso se publica.

Se emite desde **todos** los sitios que tocan una membresía —alta manual, alta
JIT desde el IdP, SCIM, cambio de roles, baja—, y no solo desde el alta. Un
organigrama que se publica en el alta y no en el ascenso es peor que no tenerlo:
las aprobaciones seguirían yendo al jefe anterior, con toda la apariencia de
funcionar.
"""

from __future__ import annotations

from uuid import UUID

from crmcore.db.uow import UnidadDeTrabajo
from sqlalchemy import select

from services.identity.modelos import Membresia


def publicar(uow: UnidadDeTrabajo, tenant_id: UUID, usuario_id: UUID) -> None:
    """Emite la posición actual de la persona, tal como está en la base.

    Se lee de la base en vez de recibirla por parámetro **a propósito**: quien
    llama acaba de cambiar un campo y conoce ese, no los otros tres. Pasarlos a
    mano es cómo se publica un organigrama con el rol nuevo y el superior viejo.
    """
    membresia = uow.db.execute(
        select(Membresia).where(
            Membresia.tenant_id == tenant_id, Membresia.usuario_id == usuario_id
        )
    ).scalar_one_or_none()
    if membresia is None:
        return

    uow.emitir(
        "user.org.changed",
        subject=("usuario", usuario_id),
        data={
            "user_id": str(usuario_id),
            "roles": list(membresia.roles or []),
            "superior_id": str(membresia.superior_id) if membresia.superior_id else "",
            "unidad_id": str(membresia.business_unit_id) if membresia.business_unit_id else "",
            "activa": bool(membresia.activa),
            # Los atributos de ABAC viajan porque de ellos salen las reglas de
            # aprobación por territorio o por país: sin ellos, «que lo apruebe
            # el responsable de la zona» habría que resolverlo llamando a
            # identity en mitad de una transacción de otro servicio.
            "atributos": dict(membresia.atributos or {}),
        },
        dedup_key=f"org:{tenant_id}:{usuario_id}",
    )
