"""API de cadencias, cola de trabajo y metodología
(CRM-03.03.01, CRM-03.01.02.01, CRM-03.01.02.02, CRM-03.01.02.03)."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_ficha, montar_listado
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.sales import cadencias as cad
from services.sales.cadencias import Metodologia, PlantillaCorreo

router = APIRouter(prefix="/cadencias", tags=["prospección"])
router_cola = APIRouter(prefix="/mi-cola", tags=["prospección"])
router_plantillas = APIRouter(prefix="/plantillas-correo", tags=["prospección"])
router_agenda = APIRouter(prefix="/agenda", tags=["prospección"])
router_metodologia = APIRouter(prefix="/metodologias", tags=["ventas"])


class CrearCadencia(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    nombre: str = Field(..., min_length=1, max_length=200)
    descripcion: str = ""
    pasos: list[dict[str, Any]] = Field(
        ...,
        min_length=1,
        description="canal (correo · llamada · mensaje · social · tarea), espera_dias y plantilla",
        examples=[
            [
                {"canal": "correo", "espera_dias": 0, "plantilla": "primer-contacto"},
                {"canal": "llamada", "espera_dias": 2},
                {"canal": "correo", "espera_dias": 4, "plantilla": "seguimiento"},
            ]
        ],
    )
    salida_por_cuenta: bool = Field(
        True,
        description=(
            "Al salir uno, salen sus compañeros de cuenta. En B2B contesta uno y "
            "se siguen persiguiendo sus tres compañeros, y el que contestó lo ve"
        ),
    )
    solo_laborable: bool = Field(
        True,
        description=(
            "Un correo automático a las tres de la mañana dice «esto lo manda una "
            "máquina» más alto que cualquier firma"
        ),
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("lead:write"))],
    summary="Crear una cadencia",
    description=(
        "Se valida la secuencia y se separa lo que **rechaza** de lo que solo "
        "**avisa**: dos toques el mismo día o doce pasos no son errores, pero "
        "son las dos cosas que convierten una cadencia en bajas."
    ),
)
def crear(datos: CrearCadencia, uow: UowDep) -> Any:
    fila, avisos = cad.crear_cadencia(uow, **datos.model_dump())
    return {"id": str(fila.id), "clave": fila.clave, "avisos": avisos}


@router.get(
    "",
    dependencies=[Depends(exige_permiso("lead:read"))],
    summary="Cadencias del tenant",
)
def listar(db: DbDep, principal: AutenticadoDep) -> Any:
    filas = (
        db.execute(
            select(cad.Cadencia)
            .where(cad.Cadencia.tenant_id == principal.tenant_id)
            .order_by(cad.Cadencia.nombre)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "clave": f.clave,
            "nombre": f.nombre,
            "pasos": len(f.pasos or []),
            "activa": f.activa,
        }
        for f in filas
    ]


class Inscribir(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    contacto_id: UUID | None = None
    lead_id: UUID | None = None
    cuenta_id: UUID | None = None
    responsable_id: UUID | None = None


@router.post(
    "/{cadencia_id}/inscribir",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("lead:write"))],
    summary="Meter a alguien en la cadencia",
    description=(
        "Si ya está en **otra** cadencia activa se rechaza. Dos secuencias a la "
        "vez sobre la misma persona es la forma más rápida de que pida la baja, y "
        "ocurre sin querer: dos comerciales importan la misma lista."
    ),
)
def inscribir(cadencia_id: UUID, datos: Inscribir, uow: UowDep) -> Any:
    fila = cad.inscribir(uow, cadencia_id, **datos.model_dump())
    return {"id": str(fila.id), "email": fila.email, "proximo_at": fila.proximo_at.isoformat()}


class Salida(BaseModel):
    motivo: str = Field(
        ...,
        description="respondio · reunion · convertido · rebote · baja · manual · terminada",
    )


@router.post(
    "/inscripciones/{inscripcion_id}/salir",
    dependencies=[Depends(exige_permiso("lead:write"))],
    summary="Sacar a alguien de la cadencia",
)
def salir(inscripcion_id: UUID, datos: Salida, uow: UowDep) -> Any:
    return cad.salir(uow, inscripcion_id, motivo=datos.motivo)


class Respuesta(BaseModel):
    email: str = Field(..., min_length=3)
    tipo: str = Field("respondio", description="respondio · reunion · convertido · baja")


@router.post(
    "/respuesta",
    dependencies=[Depends(exige_permiso("lead:write"))],
    summary="Alguien ha contestado",
    description=(
        "**Responder saca del recorrido, siempre.** Es la regla que hace que una "
        "cadencia sea aceptable y no acoso.\n\n"
        "Es **una sola puerta** para todos los canales a propósito: con una por "
        "canal, el que se olvide de llamar deja a alguien recibiendo el siguiente "
        "correo después de haber contestado."
    ),
)
def respuesta(datos: Respuesta, uow: UowDep) -> Any:
    return cad.registrar_respuesta(uow, **datos.model_dump())


@router.post(
    "/avanzar",
    dependencies=[Depends(exige_permiso("lead:write"))],
    summary="Ejecutar los pasos que tocan",
    description=(
        "Los pasos de correo se ejecutan solos; los de llamada, mensaje o tarea "
        "salen marcados como **manuales**. Mandar un correo no es lo mismo que "
        "llamar, y una herramienta que finge que sí acaba con cadencias de cinco "
        "correos que nadie llamó."
    ),
)
def avanzar(uow: UowDep, principal: AutenticadoDep) -> Any:
    return cad.avanzar(uow, principal.tenant_id)


@router_cola.get(
    "",
    dependencies=[Depends(exige_permiso("lead:read"))],
    summary="Lo que me toca hacer hoy",
    description=(
        "**Una cola, no tres.** Un comercial con tres listas —tareas, cadencias, "
        "leads— trabaja la que tiene delante, no la que importa.\n\n"
        "Cada entrada dice **por qué está ahí**. Una prioridad sin explicación se "
        "ignora: si no se dice por qué algo está arriba, la gente baja hasta "
        "encontrar lo que reconoce."
    ),
)
def cola(db: DbDep, principal: AutenticadoDep, limite: int = Query(50, ge=1, le=200)) -> Any:
    return cad.cola_de_trabajo(db, principal.tenant_id, principal.id, limite=limite)


class CrearPlantilla(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    nombre: str = Field(..., min_length=1, max_length=200)
    asunto: str = Field(..., min_length=1, max_length=300)
    cuerpo: str = ""


@router_plantillas.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("lead:write"))],
    summary="Crear una plantilla de correo",
)
def crear_plantilla(datos: CrearPlantilla, db: DbDep, principal: AutenticadoDep) -> Any:
    fila = cad.PlantillaCorreo(tenant_id=principal.tenant_id, **datos.model_dump())
    db.add(fila)
    db.flush()
    return {"id": str(fila.id), "clave": fila.clave}


@router_plantillas.get(
    "/rendimiento",
    dependencies=[Depends(exige_permiso("lead:read"))],
    summary="Qué plantillas funcionan",
    description=(
        "**Lo que se mide es la respuesta, no la apertura.** La apertura la "
        "falsean los filtros de correo que cargan las imágenes por su cuenta, y "
        "optimizar por aperturas lleva a asuntos que se abren y no se contestan — "
        "que es el peor sitio al que llegar, porque parece que va bien.\n\n"
        "Con menos de treinta envíos **no se da una tasa**: con cinco envíos y una "
        "respuesta, el 20 % que saldría no describe nada y se usa para descartar "
        "una plantilla que nunca se probó."
    ),
)
def rendimiento(db: DbDep, principal: AutenticadoDep) -> Any:
    return cad.rendimiento_plantillas(db, principal.tenant_id)


class Disponibilidad(BaseModel):
    tramos: dict[str, Any] = Field(
        ...,
        description="Por día de la semana (0 = lunes)",
        examples=[{"0": [["09:00", "13:00"], ["15:00", "18:00"]]}],
    )
    duracion_min: int = Field(30, ge=5, le=480)
    margen_min: int = Field(
        15, ge=0, le=120, description="Sin margen se encadenan reuniones y la tercera empieza tarde"
    )
    antelacion_horas: int = Field(
        4,
        ge=0,
        le=168,
        description="Proponer un hueco dentro de diez minutos produce la reunión a la que nadie llega",
    )
    equipo: str | None = None


@router_agenda.put(
    "/disponibilidad",
    dependencies=[Depends(exige_permiso("lead:write"))],
    summary="Declarar cuándo me puedo reunir",
)
def disponibilidad(datos: Disponibilidad, db: DbDep, principal: AutenticadoDep) -> Any:
    fila = db.execute(
        select(cad.DisponibilidadAgenda).where(
            cad.DisponibilidadAgenda.tenant_id == principal.tenant_id,
            cad.DisponibilidadAgenda.usuario_id == principal.id,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = cad.DisponibilidadAgenda(
            tenant_id=principal.tenant_id, usuario_id=principal.id, **datos.model_dump()
        )
        db.add(fila)
    else:
        for campo, valor in datos.model_dump().items():
            setattr(fila, campo, valor)
    db.flush()
    return {"id": str(fila.id)}


@router_agenda.get(
    "/huecos",
    dependencies=[Depends(exige_permiso("lead:read"))],
    summary="Huecos para proponer una reunión",
    description=(
        "Los tramos se contrastan con el calendario que traiga quien llama. **No "
        "se inventa**: una disponibilidad calculada sin mirar el calendario "
        "produce la reunión que hay que mover, y moverla cuesta más que no "
        "haberla propuesto. Cada hueco dice si se contrastó."
    ),
)
def ver_huecos(
    db: DbDep,
    principal: AutenticadoDep,
    usuario_id: UUID | None = Query(None),
    desde: date | None = Query(None),
    dias: int = Query(5, ge=1, le=30),
) -> Any:
    return cad.huecos(db, principal.tenant_id, usuario_id or principal.id, desde=desde, dias=dias)


class TurnoDeEquipo(BaseModel):
    equipo: str = Field(..., min_length=1, description="El equipo que atiende estas reuniones")
    desde: date | None = None
    dias: int = Field(5, ge=1, le=30)


@router_agenda.post(
    "/turno",
    dependencies=[Depends(exige_permiso("lead:write"))],
    summary="A quién del equipo le toca la próxima reunión, con sus huecos",
    description=(
        "El reparto va por **quién lleva más tiempo sin recibir una**, no por "
        "orden alfabético ni por identificador: los dos dan siempre la misma "
        "persona primero, y el reparto deja de repartir — que es como se acaba "
        "con un comercial desbordado y otro sin agenda.\n\n"
        "Es `POST` y no `GET` porque **consume el turno**: la vuelta queda "
        "anotada en el momento de preguntar. Preguntar dos veces sin llegar a "
        "citar a nadie salta a una persona de la rueda, así que se pregunta "
        "cuando se va a proponer la reunión, no para mirar.\n\n"
        "Los huecos que acompañan son los de esa persona, contrastados con su "
        "calendario si lo hay: una disponibilidad sin mirar el calendario "
        "produce la reunión que hay que mover, y moverla cuesta más que no "
        "haberla propuesto."
    ),
)
def turno_de_equipo(datos: TurnoDeEquipo, db: DbDep, principal: AutenticadoDep) -> Any:
    from crmcore.errors import NoEncontrado

    usuario_id = cad.siguiente_del_equipo(db, principal.tenant_id, datos.equipo)
    if usuario_id is None:
        raise NoEncontrado(
            f"Nadie del equipo «{datos.equipo}» tiene disponibilidad declarada y activa. "
            "Repartir reuniones entre cero personas no falla: deja la reunión sin "
            "proponer y sin que nadie se entere.",
            error_code="agenda.equipo_sin_disponibilidad",
            detalle={"equipo": datos.equipo},
        )
    return {
        "usuario_id": str(usuario_id),
        "equipo": datos.equipo,
        "turno_consumido": True,
        "huecos": cad.huecos(
            db, principal.tenant_id, usuario_id, desde=datos.desde, dias=datos.dias
        ),
    }


class CrearMetodologia(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    nombre: str = Field(..., min_length=1, max_length=200)
    familia: str = Field("custom", description="meddic · bant · spin · challenger · custom")
    criterios: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Vacío con una familia conocida: se usan los criterios de serie",
    )
    pipeline: str | None = None


@router_metodologia.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("opportunity:write"))],
    summary="Declarar una metodología de venta",
    description=(
        "Con una familia conocida (MEDDIC, BANT) y sin criterios se usan los de "
        "serie: un tenant que elige MEDDIC espera MEDDIC, no una pantalla en "
        "blanco donde teclearlo."
    ),
)
def crear_metodologia(datos: CrearMetodologia, db: DbDep, principal: AutenticadoDep) -> Any:
    if datos.familia not in cad.METODOLOGIAS:
        from crmcore.errors import ErrorValidacion

        raise ErrorValidacion(
            f"Familia «{datos.familia}» no válida.",
            error_code="metodologia.familia_no_valida",
            detalle={"validas": list(cad.METODOLOGIAS)},
        )
    fila = cad.Metodologia(tenant_id=principal.tenant_id, **datos.model_dump())
    db.add(fila)
    db.flush()
    return {"id": str(fila.id), "clave": fila.clave}


@router_metodologia.get(
    "/{metodologia_id}/oportunidad/{oportunidad_id}",
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Qué falta para poder cerrar",
    description=(
        "**Se dice lo que falta, no lo que hay.** Un indicador que sube al "
        "rellenar campos premia rellenar campos; el que sirve devuelve una lista "
        "de cosas que hacer, y por eso `lo_que_falta` va antes que la "
        "puntuación.\n\n"
        "Con la mitad sin contestar se marca como **no cualificada**: la "
        "puntuación entonces no dice si el negocio va bien, dice que no se ha "
        "cualificado, y son cosas distintas."
    ),
)
def evaluar(
    metodologia_id: UUID, oportunidad_id: UUID, db: DbDep, principal: AutenticadoDep
) -> Any:
    return cad.evaluar(db, principal.tenant_id, metodologia_id, oportunidad_id)


@router_metodologia.get(
    "/playbook",
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Qué hacer aquí y ahora",
    description=(
        "Gana el **más específico**: uno que nombra etapa y segmento manda sobre "
        "uno que solo nombra la etapa. Con el orden al revés, el genérico taparía "
        "siempre al que alguien escribió para su caso.\n\n"
        "Y dice **por qué** se eligió ese: un playbook que aparece sin explicación "
        "se cierra sin leerlo."
    ),
)
def playbook(
    db: DbDep,
    principal: AutenticadoDep,
    etapa: str = Query(""),
    segmento: str = Query(""),
) -> Any:
    return cad.playbook_para(db, principal.tenant_id, etapa=etapa, segmento=segmento)


# ── Listados ──────────────────────────────────────────────────────────────
# Estas colecciones se podían crear y no se podían leer: tenían `POST` y no
# tenían `GET`, así que lo que se daba de alta desaparecía de la vista. La API
# contestaba 405 y el front —que las declara listables— enseñaba una pantalla
# vacía sin decir por qué.

montar_listado(
    router_plantillas,
    modelo=PlantillaCorreo,
    objeto="plantilla_correo",
    permiso="lead:read",
    nombre="Plantillas de correo",
)
montar_listado(
    router_metodologia,
    modelo=Metodologia,
    objeto="metodologia",
    permiso="opportunity:read",
    nombre="Metodologías de venta",
)


ROUTERS_CADENCIAS = [
    router,
    router_cola,
    router_plantillas,
    router_agenda,
    router_metodologia,
]


# ── La ficha del registro ─────────────────────────────────────────────────
# Sin ella, las acciones que cuelgan de un registro no se alcanzan desde
# ninguna pantalla: existen, se prueban y nadie las usa.
montar_ficha(
    router,
    modelo=cad.Cadencia,
    objeto="cadencia",
    permiso_leer="lead:read",
    permiso_escribir="lead:write",
    nombre="Cadencias",
    parametro="cadencia_id",
)
