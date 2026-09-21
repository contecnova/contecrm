"""API de segregación de funciones (CRM-07.03.02.06)."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.identity import sod

router_sod = APIRouter(prefix="/segregacion", tags=["roles y permisos"])


class ReglaEntrada(BaseModel):
    nombre: str = Field(max_length=300)
    descripcion: str = ""
    permisos_a: list[str] = Field(min_length=1)
    permisos_b: list[str] = Field(min_length=1)
    nivel: str = "alto"
    activa: bool = True


class ExcepcionEntrada(BaseModel):
    usuario_id: UUID
    motivo: str = Field(min_length=1)
    caduca_at: date


@router_sod.get(
    "/reglas",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Reglas de segregación de funciones",
)
def listar_reglas(db: DbDep, principal: AutenticadoDep) -> Any:
    filas = (
        db.execute(
            select(sod.ReglaSoD)
            .where(sod.ReglaSoD.tenant_id == principal.tenant_id)
            .order_by(sod.ReglaSoD.codigo)
        )
        .scalars()
        .all()
    )
    return [
        {
            "codigo": f.codigo,
            "nombre": f.nombre,
            "descripcion": f.descripcion,
            "permisos_a": list(f.permisos_a or []),
            "permisos_b": list(f.permisos_b or []),
            "nivel": f.nivel,
            "activa": f.activa,
        }
        for f in filas
    ]


@router_sod.put(
    "/reglas/{codigo}",
    response_model=dict,
    dependencies=[Depends(exige_permiso("role:write"))],
    summary="Declarar una incompatibilidad de permisos",
    description=(
        "Los dos lados tienen que ser distintos: un mismo permiso en los dos "
        "no segrega nada, prohíbe. Si eso es lo que se quiere, se quita del rol."
    ),
)
def guardar_regla(codigo: str, datos: ReglaEntrada, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = sod.guardar_regla(
        uow.db, tenant_id=principal.tenant_id, codigo=codigo, **datos.model_dump()
    )
    return {"codigo": fila.codigo, "nombre": fila.nombre, "nivel": fila.nivel}


@router_sod.post(
    "/reglas/{codigo}/excepciones",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("role:write"))],
    summary="Aprobar un conflicto concreto",
    description=(
        "Exige motivo escrito y fecha de caducidad. Sin motivo, dentro de un "
        "año nadie sabe por qué se aprobó; sin caducidad, la excepción "
        "sobrevive a la persona, al puesto y a la razón que la justificaba."
    ),
)
def aprobar_excepcion(
    codigo: str, datos: ExcepcionEntrada, uow: UowDep, principal: AutenticadoDep
) -> Any:
    fila = sod.aprobar_excepcion(
        uow.db,
        tenant_id=principal.tenant_id,
        regla_codigo=codigo,
        por=principal.id,
        **datos.model_dump(),
    )
    return {
        "regla": fila.regla_codigo,
        "usuario_id": str(fila.usuario_id),
        "caduca_at": fila.caduca_at.isoformat(),
    }


@router_sod.get(
    "/violaciones",
    response_model=dict,
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Quién tiene hoy permisos incompatibles",
    description=(
        "Se calcula en vivo sobre los permisos efectivos y no se guarda: una "
        "tabla de violaciones se queda vieja en cuanto alguien cambia de rol, y "
        "una lista de conflictos vieja es peor que ninguna porque se actúa "
        "sobre ella.\n\n"
        "Los conflictos con excepción vigente **salen igual**, marcados. "
        "Esconderlos haría que una excepción caducada pasara de «aprobado» a "
        "«no existe» sin que nadie lo viera."
    ),
)
def violaciones(db: DbDep, principal: AutenticadoDep) -> Any:
    return sod.violaciones(db, principal.tenant_id)


ROUTERS_SOD = [router_sod]
