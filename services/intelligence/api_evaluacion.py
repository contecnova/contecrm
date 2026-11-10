"""API de la evaluación de la IA.

Leer el resultado es de quien usa la IA; lanzar una evaluación y cambiar el
banco es de quien la administra —cuesta llamadas al modelo de verdad—.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from services.intelligence import evaluacion as ev

router_evaluacion = APIRouter(prefix="/ia/evaluacion", tags=["ia"])


class Evaluar(BaseModel):
    funciones: list[str] = Field(
        default_factory=list,
        description="Sólo estas funciones; vacío evalúa todo el banco activo",
    )


class CasoNuevo(BaseModel):
    clave: str = Field(..., min_length=1, max_length=120)
    funcion: str = Field(..., description="Una de las funciones evaluables")
    nombre: str = Field("", max_length=200)
    entrada: dict[str, Any]
    criterios: list[dict[str, Any]] = Field(..., min_length=1)


class CambioCaso(BaseModel):
    activo: bool | None = None
    nombre: str | None = Field(None, max_length=200)
    entrada: dict[str, Any] | None = None
    criterios: list[dict[str, Any]] | None = None


@router_evaluacion.get(
    "",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Acierto de la IA por función: la última evaluación, su tendencia y lo que falla",
)
def panel(db: DbDep, principal: AutenticadoDep) -> Any:
    return ev.panel(db, principal.tenant_id)


@router_evaluacion.post(
    "/ejecutar",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Evaluar ahora: pasa el banco contra el modelo real, en diferido",
    description=(
        "Abre una ejecución con los casos activos del banco (la primera vez guarda "
        "los de serie como del tenant); la tarea de fondo del servicio los pasa "
        "por tandas por el mismo puerto que las funciones reales. Cuesta llamadas al modelo: "
        "se apuntan en el uso y el gasto de IA como cualquier otra. 409 si ya hay "
        "una en curso."
    ),
)
def ejecutar(cuerpo: Evaluar, uow: UowDep, principal: AutenticadoDep) -> Any:
    return ev.lanzar(
        uow, origen="manual", pedida_por=principal.id, funciones=cuerpo.funciones or None
    )


@router_evaluacion.get(
    "/ejecuciones",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Las evaluaciones pasadas, con el acierto por función de cada una",
)
def ejecuciones(db: DbDep, principal: AutenticadoDep, limite: int = Query(20, ge=1, le=200)) -> Any:
    return {"ejecuciones": ev.ejecuciones(db, principal.tenant_id, limite=limite)}


@router_evaluacion.get(
    "/ejecuciones/{ejecucion_id}",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Una evaluación caso a caso, con el porqué de cada fallo",
)
def ejecucion(ejecucion_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return ev.detalle(db, principal.tenant_id, ejecucion_id)


@router_evaluacion.get(
    "/casos",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="El banco de evaluación del tenant: entrada y criterios de cada caso",
)
def casos(db: DbDep, principal: AutenticadoDep) -> Any:
    return ev.casos(db, principal.tenant_id)


@router_evaluacion.post(
    "/casos",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Añadir un caso propio al banco",
)
def crear_caso(cuerpo: CasoNuevo, uow: UowDep) -> Any:
    return ev.crear_caso(
        uow,
        clave=cuerpo.clave,
        funcion=cuerpo.funcion,
        nombre=cuerpo.nombre,
        entrada=cuerpo.entrada,
        criterios=cuerpo.criterios,
    )


@router_evaluacion.patch(
    "/casos/{clave}",
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Activar, desactivar o corregir un caso del banco",
)
def cambiar_caso(clave: str, cuerpo: CambioCaso, uow: UowDep) -> Any:
    return ev.cambiar_caso(
        uow,
        clave=clave,
        activo=cuerpo.activo,
        nombre=cuerpo.nombre,
        entrada=cuerpo.entrada,
        criterios=cuerpo.criterios,
    )


ROUTERS_EVALUACION = [router_evaluacion]
