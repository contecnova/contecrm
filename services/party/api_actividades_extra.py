"""API de plantillas de actividad, visitas y recurrencias
(CRM-01.02.01.07, CRM-01.02.01.08, CRM-01.02.01.09)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.party import actividades_extra as ax

router = APIRouter(prefix="/plantillas-actividad", tags=["actividades"])
router_visitas = APIRouter(prefix="/visitas", tags=["actividades"])
router_recurrencias = APIRouter(prefix="/recurrencias", tags=["actividades"])


class CrearPlantilla(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    nombre: str = Field(..., min_length=1, max_length=200)
    proceso: str = Field("", examples=["implantacion"])
    descripcion: str = ""
    actividades: list[dict[str, Any]] = Field(
        ...,
        min_length=1,
        description="Cada una con su asunto, su desfase en días y de quién es",
        examples=[
            [
                {"asunto": "Reunión de arranque", "dias": 0, "rol": "consultor"},
                {"asunto": "Entregar el plan", "dias": 5, "rol": "consultor"},
            ]
        ],
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("activity:write"))],
    summary="Crear una plantilla de actividades",
    description=(
        "Es lo que convierte «hay que hacer una implantación» en catorce tareas con "
        "fechas. Sin ellas, cada persona inventa su lista y la mitad se olvida de "
        "lo mismo."
    ),
)
def crear(datos: CrearPlantilla, db: DbDep, principal: AutenticadoDep) -> Any:
    avisos = ax.validar_plantilla(datos.actividades)
    fila = ax.PlantillaActividades(tenant_id=principal.tenant_id, **datos.model_dump())
    db.add(fila)
    db.flush()
    return {"id": str(fila.id), "clave": fila.clave, "avisos": avisos}


@router.get(
    "",
    dependencies=[Depends(exige_permiso("activity:read"))],
    summary="Plantillas del tenant",
)
def listar(db: DbDep, principal: AutenticadoDep) -> Any:
    filas = (
        db.execute(
            select(ax.PlantillaActividades)
            .where(ax.PlantillaActividades.tenant_id == principal.tenant_id)
            .order_by(ax.PlantillaActividades.clave)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "clave": f.clave,
            "nombre": f.nombre,
            "proceso": f.proceso,
            "actividades": len(f.actividades or []),
            "activa": f.activa,
        }
        for f in filas
    ]


class Aplicar(BaseModel):
    objeto: str = Field(..., examples=["cuenta", "oportunidad"])
    objeto_id: UUID
    cuenta_id: UUID | None = None
    desde: date | None = Field(
        None,
        description=(
            "Fecha de arranque. Los desfases cuentan desde aquí y no desde hoy: si no, "
            "una implantación que empieza el mes que viene nace con todo vencido"
        ),
    )
    asignaciones: dict[str, UUID] = Field(
        default_factory=dict, description="Qué persona cubre cada rol de la plantilla"
    )


@router.post(
    "/{clave}/aplicar",
    dependencies=[Depends(exige_permiso("activity:write"))],
    summary="Crear de golpe las actividades de la plantilla",
    description=(
        "Devuelve cuántas cayeron en quien la lanzó por no decir de quién eran "
        "(`sin_dueno_declarado`). Sin ese número, una plantilla mal repartida "
        "parece bien repartida y la implantación acaba siendo la lista de tareas de "
        "una sola persona."
    ),
)
def aplicar(clave: str, datos: Aplicar, uow: UowDep, principal: AutenticadoDep) -> Any:
    return ax.aplicar_plantilla(uow, clave, por=principal.id, **datos.model_dump())


class CheckIn(BaseModel):
    lat: float
    lon: float
    cuenta_id: UUID | None = None
    actividad_id: UUID | None = None
    lat_esperada: float | None = None
    lon_esperada: float | None = None
    precision_m: int | None = Field(
        None,
        description="La que informa el dispositivo. Sin ella no se sabe si la distancia dice algo",
    )
    tope_m: int = Field(500, ge=10, le=100000)
    notas: str = ""


@router_visitas.post(
    "/check-in",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("activity:write"))],
    summary="Registrar la llegada a una visita",
    description=(
        "**La distancia se calcula en el servidor**: un check-in cuya distancia la "
        "manda el móvil se falsifica cambiando un número.\n\n"
        "Estar lejos **no bloquea**: se marca. Hay polígonos donde el GPS falla cien "
        "metros y direcciones mal geocodificadas, y rechazarlo deja sin registrar "
        "una visita que sí ocurrió — que es peor que registrarla con un aviso."
    ),
)
def check_in(datos: CheckIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    return ax.check_in(uow, usuario_id=principal.id, **datos.model_dump())


class CheckOut(BaseModel):
    notas: str = ""


@router_visitas.post(
    "/{visita_id}/check-out",
    dependencies=[Depends(exige_permiso("activity:write"))],
    summary="Cerrar la visita",
    description=(
        "Una visita de dos minutos no se rechaza, **se señala**: puede ser un error "
        "al pulsar y puede ser que no le recibieran, y son cosas distintas."
    ),
)
def check_out(visita_id: UUID, datos: CheckOut, uow: UowDep) -> Any:
    return ax.check_out(uow, visita_id, notas=datos.notas)


class CrearRecurrencia(BaseModel):
    asunto: str = Field(..., min_length=1, max_length=300)
    desde: datetime
    patron: str = Field(
        "mensual", description="diaria · semanal · mensual · anual · dias_laborables"
    )
    cada: int = Field(1, ge=1, le=365)
    tipo: str = "tarea"
    cuerpo: str = ""
    objeto: str | None = None
    objeto_id: UUID | None = None
    cuenta_id: UUID | None = None
    asignada_a: UUID | None = None
    hasta: datetime | None = None
    repeticiones: int | None = Field(
        None, description="Hace falta esto o una fecha de fin: una recurrencia sin fin no para"
    )
    una_a_una: bool = Field(
        True,
        description=(
            "La siguiente no se crea hasta cerrar la anterior. Crear las 52 de golpe "
            "llena la bandeja de tareas de dentro de un año"
        ),
    )


@router_recurrencias.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("activity:write"))],
    summary="Declarar una actividad que se repite",
)
def crear_recurrencia(datos: CrearRecurrencia, uow: UowDep) -> Any:
    fila = ax.crear_recurrencia(uow, **datos.model_dump())
    return {"id": str(fila.id), "proxima_at": fila.proxima_at.isoformat()}


@router_recurrencias.post(
    "/generar",
    dependencies=[Depends(exige_permiso("activity:write"))],
    summary="Crear las recurrentes que tocan",
    description=(
        "Una recurrente que venció sin cerrarse **se reprograma, no se acumula**: "
        "una lista de vencidas es una lista que se deja de mirar.\n\n"
        "Las que esperan a que se cierre la anterior salen aparte: no son un fallo, "
        "y confundirlas con uno lleva a apagar el `una_a_una`."
    ),
)
def generar(uow: UowDep, principal: AutenticadoDep) -> Any:
    return ax.generar_pendientes(uow, principal.tenant_id)


ROUTERS_ACTIVIDADES_EXTRA = [router, router_visitas, router_recurrencias]
