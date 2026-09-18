"""Router de retención y bloqueos legales, reutilizable por cada servicio.

Fábrica, como las de adjuntos y comentarios, y por el mismo motivo: la política
de retención y los bloqueos tienen que vivir **en el esquema del servicio que
guarda el dato**, porque los permisos de base de datos impiden que uno escriba
en el de otro. Un bloqueo que cubre todo el tenant se pone en cada servicio, y
de coordinarlo se encarga quien llama — igual que con la papelera.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from crmcore.datos.retencion import (
    CLASES,
    BloqueoLegal,
    PoliticaRetencion,
    bloquear,
    dias_efectivos,
    levantar,
    purgar,
    purgar_todo,
)
from crmcore.errors import ErrorValidacion
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso


class FijarPolitica(BaseModel):
    clase: str
    dias: int = Field(
        ...,
        ge=0,
        le=36_500,
        description=(
            "Días que se conserva. **0 = indefinidamente**, y es el valor por "
            "defecto a propósito: una política mal puesta destruye datos, así "
            "que no decidir no puede significar destruir."
        ),
    )
    motivo: str | None = None
    activa: bool = True


class PoliticaOut(BaseModel):
    clase: str
    dias: int
    activa: bool
    motivo: str | None

    model_config = {"from_attributes": True}


class PonerBloqueo(BaseModel):
    motivo: str = Field(
        ...,
        min_length=3,
        description=(
            "Por qué. Un bloqueo puede durar años y sobrevivir a quien lo puso, "
            "y «¿por qué no se puede borrar esto?» es una pregunta que alguien "
            "hará cuando esa persona ya no esté."
        ),
    )
    objeto: str | None = Field(
        None, description="Tipo de objeto. Vacío = todo lo de este servicio."
    )
    objeto_id: UUID | None = Field(None, description="Un registro concreto")
    referencia: str | None = Field(None, max_length=120, description="Número de expediente")


class LevantarBloqueo(BaseModel):
    motivo: str = Field(..., min_length=3)


class BloqueoOut(BaseModel):
    id: UUID
    objeto: str | None
    objeto_id: UUID | None
    motivo: str
    referencia: str | None
    activo: bool
    motivo_levantamiento: str | None

    model_config = {"from_attributes": True}


def crear_router_retencion(prefijo: str = "/retencion") -> APIRouter:
    """Construye el router de retención y bloqueos para un servicio."""
    router = APIRouter(prefix=prefijo, tags=["retención"])

    @router.get(
        "/clases",
        response_model=list[dict],
        summary="Qué datos de este servicio tienen retención",
        description=(
            "Cada clase dice desde cuándo se cuenta el plazo, que **no siempre "
            "es la fecha de creación**: una actividad se retiene desde que se "
            "completó. Contar desde la creación borraría una tarea abierta de "
            "hace tres años que sigue pendiente."
        ),
    )
    def clases(db: DbDep, principal: AutenticadoDep) -> Any:
        return [
            {
                "clave": c.clave,
                "descripcion": c.descripcion,
                "desde": c.campo_fecha,
                "dias_defecto": c.dias_defecto,
                "borrado": c.borrado,
                "dias_efectivos": dias_efectivos(db, tenant_id=principal.tenant_id, clase=c.clave),
            }
            for c in sorted(CLASES.values(), key=lambda x: x.clave)
        ]

    @router.get("/politicas", response_model=list[PoliticaOut], summary="Políticas del tenant")
    def listar_politicas(db: DbDep, _: AutenticadoDep) -> Any:
        return list(
            db.execute(select(PoliticaRetencion).order_by(PoliticaRetencion.clase)).scalars().all()
        )

    @router.put(
        "/politicas",
        response_model=PoliticaOut,
        summary="Fijar cuánto se conserva una clase de dato",
        dependencies=[Depends(exige_permiso("retencion:configurar"))],
    )
    def fijar_politica(datos: FijarPolitica, uow: UowDep, principal: AutenticadoDep) -> Any:
        if datos.clase not in CLASES:
            raise ErrorValidacion(
                f"Este servicio no guarda datos de la clase «{datos.clase}»",
                error_code="retencion.clase_desconocida",
                detalle={"declaradas": sorted(CLASES)},
            )
        fila = uow.db.execute(
            select(PoliticaRetencion).where(PoliticaRetencion.clase == datos.clase)
        ).scalar_one_or_none()
        if fila is None:
            fila = PoliticaRetencion(tenant_id=principal.tenant_id, clase=datos.clase)
            uow.db.add(fila)
        fila.dias = datos.dias
        fila.activa = datos.activa
        fila.motivo = datos.motivo
        uow.db.flush()
        return fila

    @router.post(
        "/purgar",
        response_model=list[dict],
        summary="Aplicar la retención",
        description=(
            "**Simula por defecto**, como la importación masiva y por el mismo "
            "motivo: lo que enseña cuántas filas se llevaría por delante hay que "
            "poder verlo antes, no después. Se abstiene entera si hay un bloqueo "
            "legal activo."
        ),
        dependencies=[Depends(exige_permiso("retencion:purgar"))],
    )
    def ejecutar_purga(
        uow: UowDep,
        principal: AutenticadoDep,
        clase: str | None = Query(None, description="Solo esta clase; vacío = todas"),
        simular: bool = Query(True),
    ) -> Any:
        if clase:
            return [
                purgar(
                    uow.db,
                    tenant_id=principal.tenant_id,
                    clase=clase,
                    simular=simular,
                    por=principal.id,
                ).a_dict()
            ]
        return [
            i.a_dict()
            for i in purgar_todo(
                uow.db, tenant_id=principal.tenant_id, simular=simular, por=principal.id
            )
        ]

    # ── Bloqueos legales ──────────────────────────────────────────────────

    @router.get("/bloqueos", response_model=list[BloqueoOut], summary="Bloqueos legales")
    def listar_bloqueos(db: DbDep, _: AutenticadoDep, solo_activos: bool = Query(True)) -> Any:
        consulta = select(BloqueoLegal).order_by(BloqueoLegal.created_at.desc())
        if solo_activos:
            consulta = consulta.where(BloqueoLegal.activo.is_(True))
        return list(db.execute(consulta).scalars().all())

    @router.post(
        "/bloqueos",
        response_model=BloqueoOut,
        status_code=status.HTTP_201_CREATED,
        summary="Bloquear la eliminación por litigio",
        description=(
            "Mientras esté activo, la purga por retención se abstiene. El ámbito "
            "va de lo general a lo concreto: sin objeto cubre todo lo de este "
            "servicio; con objeto, ese tipo; con objeto e identificador, ese "
            "registro."
        ),
        dependencies=[Depends(exige_permiso("retencion:bloquear"))],
    )
    def poner_bloqueo(datos: PonerBloqueo, uow: UowDep, principal: AutenticadoDep) -> Any:
        return bloquear(
            uow.db,
            tenant_id=principal.tenant_id,
            motivo=datos.motivo,
            objeto=datos.objeto,
            objeto_id=datos.objeto_id,
            referencia=datos.referencia,
            por=principal.id,
        )

    @router.post(
        "/bloqueos/{bloqueo_id}/levantar",
        response_model=BloqueoOut,
        summary="Levantar un bloqueo",
        description=(
            "Exige motivo, y la fila no se borra. A partir de aquí lo que cubría "
            "vuelve a ser purgable, así que levantarlo es una decisión tan seria "
            "como ponerlo."
        ),
        dependencies=[Depends(exige_permiso("retencion:bloquear"))],
    )
    def levantar_bloqueo(
        bloqueo_id: UUID, datos: LevantarBloqueo, uow: UowDep, principal: AutenticadoDep
    ) -> Any:
        return levantar(uow.db, bloqueo_id, motivo=datos.motivo, por=principal.id)

    return router
