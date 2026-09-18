"""API de las automatizaciones."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from crmcore.audit.chain import registrar
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, exige_permiso
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.automation import motor
from services.automation.modelos import Automatizacion, EjecucionAutomatizacion


class CrearAutomatizacion(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=200)
    descripcion: str = ""
    disparador: Literal[
        "creacion", "modificacion", "eliminacion", "evento", "webhook", "programada", "manual"
    ]
    objetivo: str = Field(
        ..., description="Objeto o tipo de evento", examples=["lead", "opportunity.won"]
    )
    campos_vigilados: list[str] = Field(
        default_factory=list,
        description=(
            "Para `modificacion`. Vacío = cualquier cambio la dispara, que "
            "suele ser más de lo que se quiere"
        ),
        examples=[["etapa", "importe"]],
    )
    programacion: str | None = Field(None, description="Expresión cron, para `programada`")
    condiciones: list[dict[str, Any]] = Field(default_factory=list)
    combinacion: Literal["todas", "alguna"] = "todas"
    acciones: list[dict[str, Any]] = Field(
        ...,
        examples=[[{"tipo": "asignar", "parametros": {"usuario_id": "@territorio.owner_id"}}]],
    )
    prioridad: int = Field(100, ge=0, le=10000)
    momento: Literal["inmediata", "diferida", "programada"] = "inmediata"
    # Nace apagada a propósito: una regla recién creada se prueba antes de
    # dejarla actuar sobre datos reales.
    activa: bool = False


class AutomatizacionOut(BaseModel):
    id: UUID
    nombre: str
    descripcion: str
    disparador: str
    objetivo: str
    campos_vigilados: list[str] = []
    condiciones: list[dict[str, Any]] = []
    combinacion: str
    acciones: list[dict[str, Any]] = []
    activa: bool
    prioridad: int
    momento: str
    ejecuciones: int
    fallos: int

    model_config = {"from_attributes": True}


class ProbarAutomatizacion(BaseModel):
    """Prueba en seco: evalúa condiciones y dice qué haría, sin hacer nada."""

    valores: dict[str, Any]


class EjecucionOut(BaseModel):
    id: UUID
    objeto: str
    registro_id: str | None = None
    resultado: str
    decisiones: list[dict[str, Any]] = []
    acciones_ejecutadas: list[dict[str, Any]] = []
    error: str | None = None
    duracion_ms: int

    model_config = {"from_attributes": True}


router = APIRouter(prefix="/automatizaciones", tags=["automatizaciones"])


@router.post(
    "",
    response_model=AutomatizacionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("automation:write"))],
    summary="Crear una automatización",
    description="Nace **desactivada**: pruébala con `/probar` antes de activarla.",
)
def crear(datos: CrearAutomatizacion, db: DbDep, principal: AutenticadoDep) -> Any:
    for accion in datos.acciones:
        if str(accion.get("tipo", "")) not in motor.ACCIONES:
            raise ErrorValidacion(
                f"Acción no admitida: «{accion.get('tipo')}»",
                error_code="automatizacion.accion_no_admitida",
                detalle={"admitidas": sorted(motor.ACCIONES)},
            )
    if db.execute(
        select(Automatizacion.id).where(
            Automatizacion.tenant_id == principal.tenant_id,
            Automatizacion.nombre == datos.nombre,
        )
    ).first():
        raise Conflicto(
            "Ya existe una automatización con ese nombre",
            error_code="automatizacion.nombre_duplicado",
        )

    regla = Automatizacion(tenant_id=principal.tenant_id, **datos.model_dump())
    db.add(regla)
    db.flush()
    registrar(
        db,
        accion="automatizacion.creada",
        objeto="automatizacion",
        objeto_id=regla.id,
        datos={"nombre": datos.nombre, "disparador": datos.disparador},
    )
    return regla


@router.get(
    "",
    response_model=list[AutomatizacionOut],
    dependencies=[Depends(exige_permiso("automation:read"))],
    summary="Automatizaciones del tenant",
)
def listar(
    db: DbDep,
    principal: AutenticadoDep,
    objetivo: str = Query(""),
    solo_activas: bool = Query(False),
) -> Any:
    consulta = select(Automatizacion).where(Automatizacion.tenant_id == principal.tenant_id)
    if objetivo:
        consulta = consulta.where(Automatizacion.objetivo == objetivo)
    if solo_activas:
        consulta = consulta.where(Automatizacion.activa.is_(True))
    return list(
        db.execute(consulta.order_by(Automatizacion.prioridad, Automatizacion.nombre))
        .scalars()
        .all()
    )


@router.post(
    "/{regla_id}/probar",
    response_model=dict,
    dependencies=[Depends(exige_permiso("automation:read"))],
    summary="Probar una regla sin ejecutarla",
    description=(
        "Evalúa las condiciones con los valores que se le pasen y devuelve la "
        "decisión de cada una y qué acciones se ejecutarían. Nada se ejecuta."
    ),
)
def probar(
    regla_id: UUID, datos: ProbarAutomatizacion, db: DbDep, principal: AutenticadoDep
) -> Any:
    regla = db.get(Automatizacion, regla_id)
    if regla is None or regla.tenant_id != principal.tenant_id:
        raise NoEncontrado("La automatización no existe", error_code="automatizacion.no_encontrada")
    cumple, decisiones = motor.evaluar_condiciones(regla, datos.valores)
    return {
        "se_dispararia": cumple,
        "decisiones": decisiones,
        "acciones": regla.acciones if cumple else [],
    }


@router.post(
    "/{regla_id}/activar",
    response_model=AutomatizacionOut,
    dependencies=[Depends(exige_permiso("automation:write"))],
    summary="Activar o desactivar una regla",
)
def activar(regla_id: UUID, activa: bool, db: DbDep, principal: AutenticadoDep) -> Any:
    regla = db.get(Automatizacion, regla_id)
    if regla is None or regla.tenant_id != principal.tenant_id:
        raise NoEncontrado("La automatización no existe", error_code="automatizacion.no_encontrada")
    regla.activa = activa
    registrar(
        db,
        accion="automatizacion.activada" if activa else "automatizacion.desactivada",
        objeto="automatizacion",
        objeto_id=regla.id,
        datos={"nombre": regla.nombre},
    )
    return regla


@router.get(
    "/{regla_id}/ejecuciones",
    response_model=list[EjecucionOut],
    dependencies=[Depends(exige_permiso("automation:read"))],
    summary="Historial de ejecuciones, con las decisiones tomadas",
    description=(
        "Incluye las veces que **no** se disparó y por qué condición. Es lo que "
        "responde a «¿por qué no se ha asignado este registro?»."
    ),
)
def ejecuciones(
    regla_id: UUID,
    db: DbDep,
    principal: AutenticadoDep,
    limite: int = Query(50, ge=1, le=200),
) -> Any:
    return list(
        db.execute(
            select(EjecucionAutomatizacion)
            .where(
                EjecucionAutomatizacion.automatizacion_id == regla_id,
                EjecucionAutomatizacion.tenant_id == principal.tenant_id,
            )
            .order_by(EjecucionAutomatizacion.created_at.desc())
            .limit(limite)
        )
        .scalars()
        .all()
    )


@router.get(
    "/registro/{objeto}/{registro_id}",
    response_model=list[EjecucionOut],
    dependencies=[Depends(exige_permiso("automation:read"))],
    summary="Qué automatizaciones han tocado este registro",
    description=(
        "Vista desde el registro y no desde la regla. Es la que se necesita "
        "cuando un dato tiene un valor raro y hay que averiguar quién lo puso."
    ),
)
def por_registro(objeto: str, registro_id: str, db: DbDep, principal: AutenticadoDep) -> Any:
    return list(
        db.execute(
            select(EjecucionAutomatizacion)
            .where(
                EjecucionAutomatizacion.tenant_id == principal.tenant_id,
                EjecucionAutomatizacion.objeto == objeto,
                EjecucionAutomatizacion.registro_id == registro_id,
            )
            .order_by(EjecucionAutomatizacion.created_at.desc())
            .limit(100)
        )
        .scalars()
        .all()
    )


ROUTERS = [router]
