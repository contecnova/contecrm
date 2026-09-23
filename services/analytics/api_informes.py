"""API del motor de informes y de los cuadros de mando
(CRM-05.01.01, CRM-05.01.02.01)."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.analytics import informes as inf

router = APIRouter(prefix="/informes", tags=["informes"])
router_cuadros = APIRouter(prefix="/cuadros-mando", tags=["informes"])


class CrearInforme(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    nombre: str = Field(..., min_length=1, max_length=200)
    objeto: str = Field(..., min_length=1, max_length=40, examples=["oportunidad"])
    tipo: str = Field("tabular", description="tabular · agrupado · matricial · union")
    descripcion: str = ""
    columnas: list[str] = Field(default_factory=list)
    agrupaciones: list[dict[str, Any]] = Field(
        default_factory=list,
        examples=[[{"campo": "cerrada_el", "periodo": "mes"}]],
    )
    metricas: list[dict[str, Any]] = Field(
        default_factory=list,
        description="suma · media · minimo · maximo · cuenta · cuenta_distinta",
        examples=[[{"campo": "importe", "agregado": "suma", "como": "total"}]],
    )
    calculados: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Operación entre dos columnas, no SQL libre: una expresión libre sería "
            "SQL arbitrario de un usuario final sobre la base de producción"
        ),
        examples=[
            [
                {
                    "izquierda": "importe",
                    "operacion": "/",
                    "derecha": "unidades",
                    "como": "precio_medio",
                }
            ]
        ],
    )
    filtros: list[dict[str, Any]] = Field(default_factory=list)
    filtros_ejecucion: list[dict[str, Any]] = Field(
        default_factory=list, description="Los que el usuario rellena al ejecutarlo"
    )
    orden: list[dict[str, Any]] = Field(default_factory=list)
    pivote: str | None = Field(None, description="Para el matricial: qué va en las columnas")
    limite: int | None = None
    roles: list[str] = Field(default_factory=list, description="Vacío: lo ve quien tenga permiso")
    solo_mios: bool = Field(
        False,
        description=(
            "Enseña los datos de quien lo abre. El filtro lo pone el servidor: si "
            "viniera del cliente, bastaría quitarlo para ver los de todos"
        ),
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("informe:write"))],
    summary="Crear un informe",
    description=(
        "Se valida antes de guardar, y se separa lo que **rechaza** de lo que "
        "solo **avisa**: rechazar por un aviso deja a alguien sin poder guardar "
        "un borrador a medias, y aceptar en silencio lo grave produce un informe "
        "que falla delante del cliente."
    ),
)
def crear(datos: CrearInforme, db: DbDep, principal: AutenticadoDep) -> Any:
    avisos = inf.validar(datos.model_dump())
    fila = inf.Informe(
        tenant_id=principal.tenant_id, propietario_id=principal.id, **datos.model_dump()
    )
    db.add(fila)
    db.flush()
    return {"id": str(fila.id), "clave": fila.clave, "avisos": avisos}


@router.post(
    "/validar",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="Comprobar una definición sin guardarla",
)
def validar(datos: CrearInforme) -> Any:
    return {"avisos": inf.validar(datos.model_dump()), "valida": True}


@router.get(
    "",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="Informes del tenant",
)
def listar(db: DbDep, principal: AutenticadoDep, objeto: str = Query("")) -> Any:
    consulta = select(inf.Informe).where(
        inf.Informe.tenant_id == principal.tenant_id, inf.Informe.activo.is_(True)
    )
    if objeto:
        consulta = consulta.where(inf.Informe.objeto == objeto)
    filas = db.execute(consulta.order_by(inf.Informe.nombre)).scalars().all()
    roles = frozenset(principal.roles or [])
    return [
        {
            "id": str(f.id),
            "clave": f.clave,
            "nombre": f.nombre,
            "objeto": f.objeto,
            "tipo": f.tipo,
            "solo_mios": f.solo_mios,
        }
        for f in filas
        if not f.roles or set(f.roles) & set(roles)
    ]


class Ejecutar(BaseModel):
    filtros: list[dict[str, Any]] = Field(
        default_factory=list, description="Los filtros de ejecución que rellena el usuario"
    )
    formato: str = Field("json", description="json · csv · excel · pdf")


@router.post(
    "/{informe_id}/ejecutar",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="Ejecutar un informe",
    description=(
        "La seguridad se resuelve **al compilar, no al pintar**. Un informe que "
        "trae la facturación y la esconde en la pantalla ya la ha sacado de la "
        "base: la respuesta de la API la ve cualquiera que abra las herramientas "
        "del navegador.\n\n"
        "Un campo que quien lo pide no puede usar **se quita y se dice cuál** "
        "(`campos_retirados`), en vez de fallar: fallar deja a media plantilla "
        "sin poder abrir los informes, y quitarlo en silencio hace que dos "
        "personas vean cifras distintas del mismo informe.\n\n"
        "Si el resultado se cortó por el tope, se dice: un informe truncado en "
        "silencio se lee como el total, y con eso se toman decisiones."
    ),
)
def ejecutar(informe_id: UUID, datos: Ejecutar, uow: UowDep, principal: AutenticadoDep) -> Any:
    salida = inf.ejecutar(
        uow,
        informe_id,
        roles=frozenset(principal.roles or []),
        es_admin=principal.es_admin_plataforma,
        usuario_id=principal.id,
        filtros=datos.filtros,
        formato=datos.formato,
    )
    if datos.formato != "json":
        salida["export"] = inf.exportar(
            salida["filas"], formato=datos.formato, nombre=salida["informe"]
        )
    return salida


@router.get(
    "/{informe_id}/plan",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="Qué consulta saldría, sin ejecutarla",
    description=(
        "Es lo que permite revisar un informe antes de lanzarlo sobre producción, "
        "y ver **qué campos se le quitarían** a quien lo pide. Los valores van "
        "como parámetros y nunca interpolados: un filtro es un dato que escribe "
        "un usuario, y concatenarlo es una inyección esperando a que alguien lo "
        "pruebe."
    ),
)
def plan(informe_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    from crmcore.errors import NoEncontrado

    fila = db.execute(
        select(inf.Informe).where(
            inf.Informe.id == informe_id, inf.Informe.tenant_id == principal.tenant_id
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("El informe no existe", error_code="informe.no_encontrado")
    return inf.compilar(
        db,
        principal.tenant_id,
        fila,
        roles=frozenset(principal.roles or []),
        es_admin=principal.es_admin_plataforma,
        usuario_id=principal.id,
    )


class Programar(BaseModel):
    periodicidad: str = Field("semanal", description="diaria · semanal · mensual")
    hora: int = Field(7, ge=0, le=23)
    dia_semana: int | None = Field(None, ge=0, le=6)
    dia_mes: int | None = Field(None, ge=1, le=31)
    formato: str = "csv"
    destinatarios: list[str] = Field(default_factory=list)
    destino_externo: str = ""
    omitir_si_vacio: bool = Field(
        False,
        description=(
            "Apagado por defecto: un informe que deja de llegar no se echa de "
            "menos, y el silencio se lee como «no pasa nada» en vez de como «no "
            "se ejecutó»"
        ),
    )
    nombre: str = ""


@router.post(
    "/{informe_id}/programar",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("informe:write"))],
    summary="Programar el envío",
)
def programar(informe_id: UUID, datos: Programar, uow: UowDep) -> Any:
    fila = inf.programar(uow, informe_id, **datos.model_dump())
    return {"id": str(fila.id), "proxima_at": fila.proxima_at.isoformat()}


@router.post(
    "/correr-programadas",
    dependencies=[Depends(exige_permiso("informe:write"))],
    summary="Ejecutar y mandar lo que toca",
    description=(
        "Un informe programado que falla **avisa**, y a los tres fallos seguidos "
        "se desactiva y se dice: seguir intentándolo cada día contra un informe "
        "roto llena la bandeja de todo el mundo con el mismo error."
    ),
)
def correr(uow: UowDep, principal: AutenticadoDep) -> Any:
    return inf.correr_programadas(uow, principal.tenant_id)


@router.post(
    "/{informe_id}/instantanea",
    dependencies=[Depends(exige_permiso("informe:write"))],
    summary="Guardar lo que dice hoy",
    description=(
        "Es la única forma de contestar «¿cómo íbamos en marzo?»: el dato "
        "operativo ya cambió y recalcular marzo con los datos de hoy da un número "
        "que nunca existió.\n\n"
        "Dos veces el mismo día no crean dos puntos: con dos, un gráfico de "
        "tendencia saldría con un pico que no ocurrió."
    ),
)
def instantanea(informe_id: UUID, uow: UowDep) -> Any:
    return inf.tomar_instantanea(uow, informe_id)


@router.get(
    "/{informe_id}/tendencia",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="La serie histórica",
    description=(
        "Con menos de dos puntos **no se dice que hay tendencia**: una sola "
        "instantánea es una foto, y llamarla tendencia hace que alguien saque una "
        "conclusión de un punto."
    ),
)
def tendencia(
    informe_id: UUID, db: DbDep, principal: AutenticadoDep, desde: date | None = Query(None)
) -> Any:
    return inf.tendencia(db, principal.tenant_id, informe_id, desde=desde)


# ── Cuadros de mando ──────────────────────────────────────────────────────


class CrearCuadro(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    nombre: str = Field(..., min_length=1, max_length=200)
    descripcion: str = ""
    componentes: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Cada uno apunta a un informe y dice cómo se pinta. El «cómo» va aquí "
            "y no en el informe porque el mismo informe se enseña como tabla en un "
            "sitio y como gráfico en otro"
        ),
        examples=[[{"informe": "pipeline-mes", "vista": "grafico_barras", "ancho": 6}]],
    )
    roles: list[str] = Field(default_factory=list)
    equipos: list[str] = Field(default_factory=list)
    por_defecto_para: str = Field(
        "",
        description="Solo uno por rol: con dos, cuál se abre dependería del orden de la consulta",
    )


@router_cuadros.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("informe:write"))],
    summary="Crear un cuadro de mando",
)
def crear_cuadro(datos: CrearCuadro, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = inf.crear_cuadro(uow, propietario_id=principal.id, **datos.model_dump())
    return {"id": str(fila.id), "clave": fila.clave}


@router_cuadros.get(
    "",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="Los cuadros que puede abrir quien pregunta",
    description=(
        "Un cuadro sin roles ni equipos es **de todos**: exigir declarar el "
        "público de cada uno haría que el primero que alguien crea no lo vea "
        "nadie, y la conclusión sería que los cuadros no funcionan."
    ),
)
def listar_cuadros(db: DbDep, principal: AutenticadoDep) -> Any:
    return inf.cuadros_de(
        db,
        principal.tenant_id,
        roles=frozenset(principal.roles or []),
        usuario_id=principal.id,
        es_admin=principal.es_admin_plataforma,
    )


ROUTERS_INFORMES = [router, router_cuadros]
