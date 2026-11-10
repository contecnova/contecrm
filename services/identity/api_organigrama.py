"""API del organigrama (CRM-00.03.05.07). La lógica, en `organigrama.py`."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from services.identity import organigrama as org

router_organigrama = APIRouter(prefix="/organigrama", tags=["usuarios"])


class SuperiorIn(BaseModel):
    superior_id: UUID | None = Field(
        None, description="De quién depende; vacío la deja de raíz, sin superior"
    )


class MoverEquipoIn(BaseModel):
    a_id: UUID | None = Field(None, description="Nuevo superior del equipo; vacío los deja de raíz")


@router_organigrama.get(
    "",
    response_model=dict,
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="El organigrama: cada persona con su superior y de dónde salió",
)
def leer(db: DbDep, principal: AutenticadoDep) -> Any:
    return org.arbol(db, principal.tenant_id)


@router_organigrama.put(
    "/{usuario_id}/superior",
    response_model=dict,
    dependencies=[Depends(exige_permiso("user:write"))],
    summary="Fijar o cambiar el superior de una persona",
    description=(
        "La persona se mueve con todo su equipo. Se rechaza (409 "
        "`organigrama.ciclo`) si el superior depende de ella, y queda marcada "
        "como ajustada a mano: con `organigrama_externo_manda`, el próximo "
        "envío del directorio por SCIM la pisa."
    ),
)
def fijar(usuario_id: UUID, datos: SuperiorIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    return org.fijar_superior(
        uow, principal.tenant_id, usuario_id, datos.superior_id, por=principal.id
    )


@router_organigrama.post(
    "/{usuario_id}/equipo",
    response_model=dict,
    dependencies=[Depends(exige_permiso("user:write"))],
    summary="Pasar el equipo directo de una persona a otra",
    description="Todos o ninguno: si uno cerraría un círculo, no se mueve nadie.",
)
def mover_equipo(
    usuario_id: UUID, datos: MoverEquipoIn, uow: UowDep, principal: AutenticadoDep
) -> Any:
    return org.mover_equipo(uow, principal.tenant_id, usuario_id, datos.a_id, por=principal.id)


ROUTERS_ORGANIGRAMA = [router_organigrama]
