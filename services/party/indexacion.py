"""Qué de `party` se puede encontrar buscando (CRM-00.01.01.09).

Se indexa **al escribir**, no con una tarea que recorra las tablas cada noche:
un comercial que acaba de crear una cuenta la busca a los diez segundos, y un
índice que va con un día de retraso se percibe, con razón, como que la búsqueda
no funciona.

Lo que entra en el cuerpo es lo que la gente **teclea para encontrar algo**, que
no es lo mismo que lo que la ficha enseña. Se busca por el nombre comercial, por
el NIF, por la ciudad o por el correo de alguien; casi nunca por la fecha de
creación ni por el identificador interno. Meterlo todo hace el índice grande y
los resultados peores, porque diluye la relevancia.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.busqueda import desindexar, indexar
from sqlalchemy.orm import Session

# Los tipos de objeto que este servicio indexa. Es la lista blanca del router:
# fuera de ella no se busca, para que un tipo nuevo no aparezca en la búsqueda
# antes de que alguien haya decidido qué se enseña de él.
OBJETOS = {"cuenta", "contacto", "actividad"}


def indexar_cuenta(db: Session, cuenta: Any) -> None:
    identificadores = " ".join(
        str(i.valor) for i in getattr(cuenta, "identificadores", []) or [] if i.valor
    )
    indexar(
        db,
        tenant_id=cuenta.tenant_id,
        objeto="cuenta",
        registro_id=cuenta.id,
        titulo=cuenta.nombre,
        subtitulo=" · ".join(x for x in (cuenta.sector_codigo, cuenta.web) if x),
        cuerpo=" ".join(
            x
            for x in (
                cuenta.nombre_comercial,
                cuenta.telefono,
                cuenta.email,
                cuenta.dominio,
                identificadores,
                cuenta.clave_canonica,
            )
            if x
        ),
        owner_id=cuenta.owner_id,
        extra={"estado": cuenta.estado, "ciclo_vida": cuenta.ciclo_vida},
    )


def indexar_contacto(db: Session, contacto: Any) -> None:
    nombre = " ".join(x for x in (contacto.nombre, contacto.apellidos) if x)
    indexar(
        db,
        tenant_id=contacto.tenant_id,
        objeto="contacto",
        registro_id=contacto.id,
        titulo=nombre or contacto.email or "(sin nombre)",
        subtitulo=contacto.cargo or "",
        cuerpo=" ".join(
            x for x in (contacto.email, contacto.telefono, contacto.movil, contacto.cargo) if x
        ),
        owner_id=contacto.owner_id,
        extra={"departamento": contacto.departamento or ""},
    )


def quitar(db: Session, *, tenant_id: UUID, objeto: str, registro_id: UUID) -> None:
    """Saca un registro del índice al borrarlo.

    Lo que se borra lógicamente tiene que salir: si no, sigue saliendo en los
    resultados y al pincharlo da un 404 — que es peor que no encontrarlo, porque
    confirma que existe.
    """
    desindexar(db, tenant_id=tenant_id, objeto=objeto, registro_id=registro_id)
