"""API de los catálogos de configuración: plantillas, calendarios y monedas.

Separada de `api.py` porque son tres superficies con vida propia y ninguna
relación con el ciclo de vida del tenant más allá de colgar de él. Juntarlas
haría de `api.py` el fichero al que todo el mundo teme entrar.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.errors import Conflicto, NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.tenancy.catalogos import (
    CalendarioLaboral,
    Festivo,
    Plantilla,
    TipoCambio,
    convertir,
    es_laborable,
    fijar_tipo_cambio,
    render,
    sumar_horas_laborables,
    variables_sin_resolver,
)

# ── Plantillas (CRM-07.01.01.04) ──────────────────────────────────────────

router_plantillas = APIRouter(prefix="/plantillas", tags=["plantillas"])


class CrearPlantilla(BaseModel):
    clave: str = Field(..., max_length=120)
    nombre: str = Field(..., max_length=200)
    tipo: str = Field("correo", pattern="^(correo|documento|notificacion|sms)$")
    idioma: str = Field("es", max_length=10)
    asunto: str | None = Field(None, max_length=300)
    cuerpo: str = ""
    variables: list[str] = Field(default_factory=list)


class EditarPlantilla(BaseModel):
    nombre: str | None = None
    asunto: str | None = None
    cuerpo: str | None = None
    variables: list[str] | None = None
    activa: bool | None = None
    bloqueada: bool | None = None


class PlantillaOut(BaseModel):
    id: UUID
    clave: str
    idioma: str
    tipo: str
    nombre: str
    asunto: str | None
    cuerpo: str
    variables: list[Any]
    activa: bool
    bloqueada: bool

    model_config = {"from_attributes": True}


@router_plantillas.get("", response_model=list[PlantillaOut], summary="Listar plantillas")
def listar_plantillas(
    db: DbDep,
    _: AutenticadoDep,
    tipo: str | None = Query(None, description="correo | documento | notificacion | sms"),
    idioma: str | None = Query(None),
) -> Any:
    consulta = select(Plantilla)
    if tipo:
        consulta = consulta.where(Plantilla.tipo == tipo)
    if idioma:
        consulta = consulta.where(Plantilla.idioma == idioma)
    return db.execute(consulta.order_by(Plantilla.clave, Plantilla.idioma)).scalars().all()


@router_plantillas.post(
    "",
    response_model=PlantillaOut,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una plantilla",
    dependencies=[Depends(exige_permiso("plantilla:crear"))],
)
def crear_plantilla(datos: CrearPlantilla, uow: UowDep) -> Any:
    ya = uow.db.execute(
        select(Plantilla).where(Plantilla.clave == datos.clave, Plantilla.idioma == datos.idioma)
    ).scalar_one_or_none()
    if ya is not None:
        raise Conflicto(
            f"Ya hay una plantilla «{datos.clave}» en idioma «{datos.idioma}»",
            error_code="tenancy.plantilla_duplicada",
        )
    fila = Plantilla(tenant_id=uow.tenant_id, **datos.model_dump())
    uow.db.add(fila)
    uow.db.flush()
    return fila


@router_plantillas.patch(
    "/{plantilla_id}",
    response_model=PlantillaOut,
    summary="Editar una plantilla",
    dependencies=[Depends(exige_permiso("plantilla:editar"))],
)
def editar_plantilla(plantilla_id: UUID, datos: EditarPlantilla, uow: UowDep) -> Any:
    fila = uow.db.get(Plantilla, plantilla_id)
    if fila is None:
        raise NoEncontrado("Plantilla no encontrada", error_code="tenancy.plantilla_no_existe")
    cambios = datos.model_dump(exclude_unset=True)
    # `bloqueada` protege el CONTENIDO, no la propia marca: si bloqueara también
    # quitarse a sí misma, una plantilla bloqueada por error no se podría
    # recuperar nunca por API.
    if fila.bloqueada and set(cambios) - {"bloqueada", "activa"}:
        raise Conflicto(
            "La plantilla está bloqueada: desbloquéala antes de editar su contenido",
            error_code="tenancy.plantilla_bloqueada",
        )
    for campo, valor in cambios.items():
        setattr(fila, campo, valor)
    return fila


class PruebaPlantilla(BaseModel):
    datos: dict[str, Any] = Field(default_factory=dict)


@router_plantillas.post(
    "/{plantilla_id}/previsualizar",
    response_model=dict,
    summary="Previsualizar una plantilla con datos de prueba",
    description=(
        "Devuelve el asunto y el cuerpo ya sustituidos, y la lista de variables "
        "que quedarían sin resolver. Es lo que hay que mirar ANTES de un envío "
        "masivo: un hueco sin resolver en 20.000 correos no se deshace."
    ),
)
def previsualizar(plantilla_id: UUID, cuerpo: PruebaPlantilla, db: DbDep, _: AutenticadoDep) -> Any:
    fila = db.get(Plantilla, plantilla_id)
    if fila is None:
        raise NoEncontrado("Plantilla no encontrada", error_code="tenancy.plantilla_no_existe")
    asunto, texto = render(fila, cuerpo.datos)
    faltan = sorted(
        set(variables_sin_resolver(fila.asunto or "", cuerpo.datos))
        | set(variables_sin_resolver(fila.cuerpo or "", cuerpo.datos))
    )
    return {"asunto": asunto, "cuerpo": texto, "sin_resolver": faltan}


# ── Calendarios laborales (CRM-07.01.01.05) ───────────────────────────────

router_calendarios = APIRouter(prefix="/calendarios", tags=["calendarios"])


class CrearCalendario(BaseModel):
    clave: str = Field(..., max_length=60)
    nombre: str = Field(..., max_length=150)
    zona_horaria: str = Field("Europe/Madrid", max_length=60)
    pais: str = Field("ES", min_length=2, max_length=2)
    horario: dict[str, list[dict[str, str]]] = Field(
        default_factory=dict,
        description='Por día de la semana, 0=lunes: {"0":[{"desde":"09:00","hasta":"18:00"}]}',
    )
    por_defecto: bool = False


class CalendarioOut(BaseModel):
    id: UUID
    clave: str
    nombre: str
    zona_horaria: str
    pais: str
    horario: dict[str, Any]
    por_defecto: bool

    model_config = {"from_attributes": True}


class CrearFestivo(BaseModel):
    fecha: date
    nombre: str = Field(..., max_length=150)
    anual: bool = False


class FestivoOut(BaseModel):
    id: UUID
    fecha: date
    nombre: str
    anual: bool

    model_config = {"from_attributes": True}


@router_calendarios.get("", response_model=list[CalendarioOut], summary="Listar calendarios")
def listar_calendarios(db: DbDep, _: AutenticadoDep) -> Any:
    return db.execute(select(CalendarioLaboral).order_by(CalendarioLaboral.clave)).scalars().all()


@router_calendarios.post(
    "",
    response_model=CalendarioOut,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un calendario laboral",
    dependencies=[Depends(exige_permiso("calendario:crear"))],
)
def crear_calendario(datos: CrearCalendario, uow: UowDep) -> Any:
    if datos.por_defecto:
        # Solo puede haber uno por defecto, y lo garantiza además un índice
        # único parcial: esto quita el anterior para que la escritura no falle.
        for otro in (
            uow.db.execute(select(CalendarioLaboral).where(CalendarioLaboral.por_defecto.is_(True)))
            .scalars()
            .all()
        ):
            otro.por_defecto = False
        uow.db.flush()
    fila = CalendarioLaboral(tenant_id=uow.tenant_id, **datos.model_dump())
    uow.db.add(fila)
    uow.db.flush()
    return fila


@router_calendarios.post(
    "/{calendario_id}/festivos",
    response_model=FestivoOut,
    status_code=status.HTTP_201_CREATED,
    summary="Añadir un festivo",
    dependencies=[Depends(exige_permiso("calendario:editar"))],
)
def anadir_festivo(calendario_id: UUID, datos: CrearFestivo, uow: UowDep) -> Any:
    cal = uow.db.get(CalendarioLaboral, calendario_id)
    if cal is None:
        raise NoEncontrado("Calendario no encontrado", error_code="tenancy.calendario_no_existe")
    fila = Festivo(tenant_id=uow.tenant_id, calendario_id=calendario_id, **datos.model_dump())
    uow.db.add(fila)
    uow.db.flush()
    return fila


@router_calendarios.get(
    "/{calendario_id}/festivos", response_model=list[FestivoOut], summary="Festivos del calendario"
)
def listar_festivos(calendario_id: UUID, db: DbDep, _: AutenticadoDep) -> Any:
    return (
        db.execute(
            select(Festivo).where(Festivo.calendario_id == calendario_id).order_by(Festivo.fecha)
        )
        .scalars()
        .all()
    )


@router_calendarios.get(
    "/{calendario_id}/vencimiento",
    response_model=dict,
    summary="Calcular un vencimiento en horas laborables",
    description=(
        "Suma horas **laborables** —saltando noches, fines de semana y "
        "festivos— a un instante. Es el cálculo que usan los relojes de SLA y "
        "los vencimientos de tarea, y se expone para que cualquier servicio lo "
        "use en vez de reimplementarlo."
    ),
)
def vencimiento(
    calendario_id: UUID,
    db: DbDep,
    _: AutenticadoDep,
    horas: float = Query(..., gt=0, le=8760, description="Horas laborables a sumar"),
    desde: datetime | None = Query(None, description="Instante de partida (por defecto, ahora)"),
) -> Any:
    from datetime import timezone

    cal = db.get(CalendarioLaboral, calendario_id)
    if cal is None:
        raise NoEncontrado("Calendario no encontrado", error_code="tenancy.calendario_no_existe")
    partida = desde or datetime.now(timezone.utc)
    fin = sumar_horas_laborables(db, cal, partida, horas)
    return {
        "desde": partida.isoformat(),
        "horas_laborables": horas,
        "vence": fin.isoformat(),
        "partida_en_horario": es_laborable(db, cal, partida),
        "zona_horaria": cal.zona_horaria,
    }


# ── Monedas y tipos de cambio (CRM-07.01.01.06) ───────────────────────────

router_monedas = APIRouter(prefix="/monedas", tags=["monedas"])


class FijarCambio(BaseModel):
    desde: str = Field(..., min_length=3, max_length=3)
    hasta: str = Field(..., min_length=3, max_length=3)
    tasa: Decimal = Field(..., gt=0)
    fecha: date | None = None
    origen: str = Field("manual", max_length=60)


class CambioOut(BaseModel):
    id: UUID
    desde_moneda: str
    hasta_moneda: str
    fecha: date
    tasa: Decimal
    origen: str | None

    model_config = {"from_attributes": True}


@router_monedas.get("/cambios", response_model=list[CambioOut], summary="Histórico de cambios")
def listar_cambios(
    db: DbDep,
    _: AutenticadoDep,
    desde: str | None = Query(None, min_length=3, max_length=3),
    hasta: str | None = Query(None, min_length=3, max_length=3),
    limite: int = Query(100, ge=1, le=1000),
) -> Any:
    consulta = select(TipoCambio)
    if desde:
        consulta = consulta.where(TipoCambio.desde_moneda == desde.upper())
    if hasta:
        consulta = consulta.where(TipoCambio.hasta_moneda == hasta.upper())
    return db.execute(consulta.order_by(TipoCambio.fecha.desc()).limit(limite)).scalars().all()


@router_monedas.put(
    "/cambios",
    response_model=CambioOut,
    summary="Fijar un tipo de cambio para una fecha",
    dependencies=[Depends(exige_permiso("moneda:editar"))],
)
def poner_cambio(datos: FijarCambio, uow: UowDep) -> Any:
    fila = fijar_tipo_cambio(
        uow.db,
        tenant_id=uow.tenant_id,
        desde=datos.desde,
        hasta=datos.hasta,
        tasa=datos.tasa,
        en_fecha=datos.fecha,
        origen=datos.origen,
    )
    uow.db.flush()
    return fila


@router_monedas.get(
    "/convertir",
    response_model=dict,
    summary="Convertir un importe",
    description=(
        "Usa el cambio vigente **en la fecha pedida**, no el de hoy: una "
        "oportunidad cerrada en marzo tiene que seguir valiendo lo de marzo."
    ),
)
def convertir_importe(
    db: DbDep,
    principal: AutenticadoDep,
    importe: Decimal = Query(...),
    desde: str = Query(..., min_length=3, max_length=3),
    hasta: str = Query(..., min_length=3, max_length=3),
    en_fecha: date | None = Query(None),
) -> Any:
    resultado = convertir(
        db,
        tenant_id=principal.tenant_id,
        importe=importe,
        desde=desde,
        hasta=hasta,
        en_fecha=en_fecha,
    )
    return {
        "importe": str(importe),
        "desde": desde.upper(),
        "hasta": hasta.upper(),
        "fecha": (en_fecha or date.today()).isoformat(),
        "resultado": str(resultado),
    }


ROUTERS_CATALOGOS = [router_plantillas, router_calendarios, router_monedas]
