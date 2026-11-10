"""API de la revisión periódica de accesos (CRM-07.03.02.15). La lógica, en `recertificacion.py`."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from services.identity import recertificacion as rec

router_recert = APIRouter(prefix="/recertificacion", tags=["roles y permisos"])


class LanzarIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=200)
    plazo_dias: int | None = Field(
        None, ge=1, le=365, description="Sin él, el de la empresa (recertificacion_plazo_dias)"
    )
    revisor_por_defecto: UUID | None = Field(
        None, description="Quién revisa a las personas sin superior; sin él, quien la lanza"
    )


class DecisionIn(BaseModel):
    decision: str = Field(description="confirmado o retirado")
    comentario: str = Field("", max_length=2000)


@router_recert.get(
    "/campanas",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Campañas de revisión de accesos, con su avance",
)
def listar(db: DbDep, principal: AutenticadoDep) -> Any:
    return rec.campanas(db, principal.tenant_id)


@router_recert.post(
    "/campanas",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("user:write"))],
    summary="Lanzar una campaña de revisión de accesos",
    description=(
        "Una revisión por cada rol y conjunto de permisos de cada persona activa, "
        "asignada a su **superior**; quien no lo tiene va al revisor por defecto "
        "o a quien la lanza. Cada responsable recibe un aviso con el plazo."
    ),
)
def lanzar(datos: LanzarIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    campana = rec.lanzar(
        uow,
        tenant_id=principal.tenant_id,
        nombre=datos.nombre,
        por=principal.id,
        plazo_dias=datos.plazo_dias,
        revisor_por_defecto=datos.revisor_por_defecto,
    )
    return rec.resumen_de(uow.db, campana)


@router_recert.get(
    "/campanas/{campana_id}",
    response_model=dict,
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Una campaña con cada acceso revisado",
)
def detalle(campana_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return rec.detalle(db, principal.tenant_id, campana_id)


@router_recert.post(
    "/campanas/{campana_id}/cerrar",
    response_model=dict,
    dependencies=[Depends(exige_permiso("user:write"))],
    summary="Cerrar una campaña",
    description=(
        "Lo que nadie contestó se marca como vencido, o se retira si la empresa "
        "lo ha decidido así (`recertificacion_al_cerrar`)."
    ),
)
def cerrar(campana_id: UUID, uow: UowDep, principal: AutenticadoDep) -> Any:
    return rec.cerrar(uow, tenant_id=principal.tenant_id, campana_id=campana_id, por=principal.id)


@router_recert.post(
    "/vencidas",
    response_model=dict,
    dependencies=[Depends(exige_permiso("user:write"))],
    summary="Marcar ya lo que está fuera de plazo y avisar",
    description="Lo mismo que hace la tarea periódica, sin esperarla.",
)
def vencidas(uow: UowDep, principal: AutenticadoDep) -> Any:
    return rec.marcar_vencidas(uow.db, principal.tenant_id)


@router_recert.get(
    "/mias",
    response_model=list[dict],
    summary="Lo que me toca revisar",
    description=(
        "Las revisiones de las campañas abiertas en las que soy el responsable. "
        "Va con el token de quien pregunta: nadie ve lo que le toca a otro."
    ),
)
def mias(db: DbDep, principal: AutenticadoDep) -> Any:
    return rec.mias(db, principal.tenant_id, principal.id)


@router_recert.post(
    "/revisiones/{revision_id}/decision",
    response_model=dict,
    summary="Confirmar o retirar un acceso",
    description=(
        "Sólo el responsable de la revisión. **Retirar quita el acceso en el "
        "momento**: el rol sale de la membresía, se cierran sus sesiones en esta "
        "empresa y queda en la auditoría. Retirar exige motivo."
    ),
)
def decidir(revision_id: UUID, datos: DecisionIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = rec.decidir(
        uow,
        tenant_id=principal.tenant_id,
        revision_id=revision_id,
        decision=datos.decision,
        comentario=datos.comentario,
        por=principal.id,
    )
    return {"id": str(fila.id), "decision": fila.decision, "valor": fila.valor}


@router_recert.get(
    "/resumen",
    response_model=dict,
    dependencies=[Depends(exige_permiso("user:read"))],
    summary="Resumen para el GRC: la última campaña cerrada y las abiertas",
    description=(
        "Es la evidencia del control de accesos `REC-ACCESOS` del GRC, que la "
        "pide por HTTP al evaluarse."
    ),
)
def resumen(db: DbDep, principal: AutenticadoDep) -> Any:
    return rec.resumen(db, principal.tenant_id)


ROUTERS_RECERTIFICACION = [router_recert]
