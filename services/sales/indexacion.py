"""Qué de `sales` se puede encontrar buscando (CRM-00.01.01.09).

El criterio es el mismo que en `party`: entra lo que la gente teclea para
encontrar algo. En una oportunidad, eso es su código, el nombre del cliente y el
nombre de la operación; en un lead, la empresa y el correo con el que llegó.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.busqueda import desindexar, indexar
from sqlalchemy.orm import Session

OBJETOS = {"lead", "oportunidad"}


def indexar_lead(db: Session, lead: Any) -> None:
    nombre = " ".join(x for x in (lead.nombre, lead.apellidos) if x)
    indexar(
        db,
        tenant_id=lead.tenant_id,
        objeto="lead",
        registro_id=lead.id,
        titulo=lead.empresa or nombre or lead.email or "(lead sin datos)",
        subtitulo=nombre if lead.empresa else (lead.cargo or ""),
        cuerpo=" ".join(
            x for x in (lead.email, lead.telefono, lead.cargo, lead.origen, lead.web) if x
        ),
        owner_id=lead.owner_id,
        extra={"estado": lead.estado},
    )


def indexar_oportunidad(db: Session, oportunidad: Any) -> None:
    indexar(
        db,
        tenant_id=oportunidad.tenant_id,
        objeto="oportunidad",
        registro_id=oportunidad.id,
        titulo=oportunidad.nombre,
        # El código va en el subtítulo Y en el cuerpo: es por lo que más se
        # busca una oportunidad concreta, y tiene que encontrarse tecleándolo
        # entero aunque no se sepa el nombre.
        subtitulo=oportunidad.codigo or "",
        cuerpo=" ".join(x for x in (oportunidad.codigo, oportunidad.descripcion) if x),
        owner_id=oportunidad.owner_id,
        extra={"estado": oportunidad.estado, "etapa_id": str(oportunidad.etapa_id or "")},
    )


def quitar(db: Session, *, tenant_id: UUID, objeto: str, registro_id: UUID) -> None:
    desindexar(db, tenant_id=tenant_id, objeto=objeto, registro_id=registro_id)
