"""Lo que un componente incrustado en una web ajena puede leer de party.

**Ninguna ruta recibe un identificador**: lo lee del token (CRM-00.02.03.05).
Ahí está todo el acotamiento — un token de la cuenta A no puede pedir la cuenta
B porque no hay forma de pedirla, no hay parámetro que cambiar en las
herramientas del navegador.

Y devuelve **sólo lo que el componente pinta**, no el registro entero: lo que
viaja a una página pública está a un clic de verse.
"""

from __future__ import annotations

from typing import Annotated, Any

from crmcore.errors import NoEncontrado
from crmcore.http.deps import AccesoComponente, DbDep, exige_componente
from fastapi import APIRouter, Depends
from sqlalchemy import select

from services.party.modelos import Cuenta

router_embebido = APIRouter(prefix="/embebido", tags=["componentes embebibles"])


@router_embebido.get(
    "/ficha-cuenta",
    summary="La ficha reducida de la cuenta del token",
    description=(
        "Sin identificador en la ruta: el del token. Devuelve lo que el "
        "componente pinta —nombre, estado, sector y web—, no la ficha entera."
    ),
)
def ficha_cuenta(
    db: DbDep,
    acceso: Annotated[
        AccesoComponente,
        Depends(exige_componente("ficha-cuenta")),
    ],
) -> Any:
    fila = db.execute(
        select(Cuenta).where(
            Cuenta.id == acceso.objeto_id,
            Cuenta.tenant_id == acceso.tenant_id,
            Cuenta.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("No existe esa cuenta", error_code="embebido.no_encontrado")
    return {
        "nombre": fila.nombre,
        "estado": fila.estado,
        "sector": fila.sector_codigo,
        "web": fila.web,
    }
