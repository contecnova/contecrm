"""Qué de `service` se puede encontrar buscando (CRM-00.01.01.09).

El criterio es el de `party` y `sales`: entra lo que la gente teclea para
encontrar algo. En un caso, eso es **su código** —es lo que el cliente dicta
por teléfono y lo que va en el asunto de su correo— y el asunto.

**Por qué existe.** El buscador de arriba prometía casos y no los tenía: el
gateway sólo preguntaba a `party` y `sales`. Medido el 10-11-2026: buscar
«CS-00777» o el asunto de un caso abierto daba «Nada coincide», y el agente
tenía que ir a la lista y buscar a mano en las cincuenta filas cargadas.
"""

from __future__ import annotations

from typing import Any

from crmcore.busqueda import indexar
from sqlalchemy.orm import Session

OBJETOS = {"caso"}


def indexar_caso(db: Session, caso: Any) -> None:
    indexar(
        db,
        tenant_id=caso.tenant_id,
        objeto="caso",
        registro_id=caso.id,
        # El asunto de título y el código debajo, como la oportunidad: se
        # encuentra por los dos, y se reconoce por el asunto.
        titulo=caso.asunto or caso.codigo or "(caso sin asunto)",
        subtitulo=caso.codigo or "",
        cuerpo=" ".join(x for x in (caso.codigo, caso.descripcion) if x),
        owner_id=caso.owner_id,
        extra={"estado": caso.estado, "prioridad": caso.prioridad},
    )
