"""API de las lecciones aprendidas de las oportunidades cerradas."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_listado
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from services.sales import consejos
from services.sales import lecciones as lec

router_lecciones = APIRouter(prefix="/lecciones", tags=["lecciones aprendidas"])
router_expediente = APIRouter(prefix="/opportunities", tags=["oportunidades"])


def _a_dict(fila: lec.LeccionOportunidad) -> dict[str, Any]:
    return {
        "id": str(fila.id),
        "oportunidad_id": str(fila.oportunidad_id),
        "cuenta_id": str(fila.cuenta_id) if fila.cuenta_id else None,
        "titulo": fila.titulo,
        "resultado": fila.resultado,
        "motivo": fila.motivo,
        "estado": fila.estado,
        "obligatoria": fila.obligatoria,
        "cerrada_el": fila.cerrada_el.isoformat() if fila.cerrada_el else None,
        "importe": float(fila.importe) if fila.importe is not None else None,
        "que_paso": fila.que_paso,
        "senal_temprana": fila.senal_temprana,
        "que_hariamos_distinto": fila.que_hariamos_distinto,
        "factores": fila.factores or [],
        "propuesta_ia": fila.propuesta_ia,
        "responsable_id": str(fila.responsable_id) if fila.responsable_id else None,
        "firmada_por": str(fila.firmada_por) if fila.firmada_por else None,
        "firmada_at": fila.firmada_at.isoformat() if fila.firmada_at else None,
        "created_at": fila.created_at.isoformat() if fila.created_at else None,
    }


@router_lecciones.get(
    "/patrones",
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Lo que se repite en las lecciones firmadas",
    description=(
        "Qué factores pesan en las perdidas y en las ganadas, en qué etapa se pierde "
        "más y cuántos post-mortem obligatorios quedan por firmar."
    ),
)
def patrones(db: DbDep, principal: AutenticadoDep) -> Any:
    return lec.patrones(db, principal.tenant_id)


@router_lecciones.post(
    "/crear-de-las-cerradas",
    dependencies=[Depends(exige_permiso("opportunity:write"))],
    summary="Crear la lección de las oportunidades que se cerraron antes",
    description=(
        "Cada oportunidad ganada o perdida que no la tenga recibe su lección, sin "
        "obligar: son históricas. Se puede pedir más de una vez."
    ),
)
def crear_de_las_cerradas(uow: UowDep) -> Any:
    return lec.crear_de_las_cerradas(uow)


@router_lecciones.post(
    "/indexar",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Mandar todas las lecciones firmadas al índice de conocimiento",
    description=(
        "Las de antes de que existiera el índice y las que no llegaron al "
        "firmarlas. Sin esto, las oportunidades parecidas no las encuentran."
    ),
)
def indexar(db: DbDep, principal: AutenticadoDep) -> Any:
    return consejos.indexar_firmadas(db, principal.tenant_id, principal)


@router_lecciones.post(
    "/resumen",
    dependencies=[Depends(exige_permiso("opportunity:write"))],
    summary="Generar ahora el resumen de lecciones",
    description=(
        "El del periodo que va desde el último. Sale solo cada "
        "`lecciones_resumen_dias`; esto lo adelanta. Sin nada que contar no se "
        "genera, y no se repite el mismo día."
    ),
)
def generar_resumen(uow: UowDep) -> Any:
    from crmcore.fechas import hoy

    fila = consejos.resumen(uow, hoy=hoy(uow.db), forzar=True)
    if fila is None:
        return {"generado": False, "porque": "No hay nada nuevo que contar, o ya hay uno de hoy."}
    return {"generado": True, "id": str(fila.id), "detalle": fila.detalle}


montar_listado(
    router_lecciones,
    modelo=lec.LeccionOportunidad,
    objeto="leccion",
    permiso="opportunity:read",
    nombre="Lecciones aprendidas",
    orden="-cerrada_el",
    columnas_orden=frozenset({"cerrada_el", "created_at"}),
    ficha=False,
)


@router_lecciones.get(
    "/{leccion_id}",
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Una lección, con el expediente de su oportunidad",
    description=(
        "Si está firmada, el expediente es el que había al firmarla; si está "
        "pendiente, el de ahora, para poder escribirla con todo delante."
    ),
)
def ficha(leccion_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    fila = lec.leccion(db, leccion_id)
    hechos = (
        fila.hechos
        if fila.estado == "firmada" and fila.hechos
        else lec.expediente(db, fila.oportunidad_id, principal)
    )
    return {**_a_dict(fila), "expediente": hechos, "factores_posibles": list(lec.FACTORES)}


@router_lecciones.post(
    "/{leccion_id}/proponer",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Que la IA proponga el post-mortem con los hechos",
    description=(
        "Lee el expediente —etapas y días, presupuestos y descuentos, competencia, "
        "decisores, actividad y la comparación con las ganadas— y propone qué pasó, "
        "qué señal temprana no se vio y qué haríamos distinto. No firma nada."
    ),
)
def proponer(leccion_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return lec.proponer_con_ia(db, lec.leccion(db, leccion_id), principal)


class FirmarIn(BaseModel):
    que_paso: str = Field(..., min_length=1, max_length=8_000)
    senal_temprana: str = Field("", max_length=4_000)
    que_hariamos_distinto: str = Field("", max_length=8_000)
    factores: list[str] = Field(default_factory=list, description=" · ".join(lec.FACTORES))


@router_lecciones.post(
    "/{leccion_id}/firmar",
    dependencies=[Depends(exige_permiso("opportunity:write"))],
    summary="Firmar el post-mortem",
    description=(
        "Queda con tu nombre y con el expediente congelado. Desde ese momento lo "
        "leen las oportunidades parecidas."
    ),
)
def firmar(leccion_id: UUID, datos: FirmarIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = lec.firmar(
        uow,
        leccion_id,
        que_paso=datos.que_paso,
        senal_temprana=datos.senal_temprana,
        que_hariamos_distinto=datos.que_hariamos_distinto,
        factores=datos.factores,
        principal=principal,
    )
    # Al índice, para que la lean las oportunidades parecidas. Si no se puede,
    # la firma vale igual y la respuesta lo dice.
    return {**_a_dict(fila), "indice": consejos.indexar(fila, principal)}


@router_expediente.get(
    "/{oportunidad_id}/expediente",
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Por qué se ganó o se perdió: todo lo que pasó",
    description=(
        "El recorrido por etapas con los días en cada una, lo que se movieron la fecha "
        "y el importe, los presupuestos con su descuento y su margen, la competencia, "
        "los decisores, la actividad y en qué se aparta de las ganadas del mismo embudo."
    ),
)
def expediente(oportunidad_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    from sqlalchemy import select

    hechos = lec.expediente(db, oportunidad_id, principal)
    fila = db.execute(
        select(lec.LeccionOportunidad).where(
            lec.LeccionOportunidad.oportunidad_id == oportunidad_id
        )
    ).scalar_one_or_none()
    return {**hechos, "leccion": _a_dict(fila) if fila else None}


@router_expediente.get(
    "/{oportunidad_id}/consejos",
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Lo que dicen las lecciones de esta oportunidad",
    description=(
        "Las lecciones firmadas del mismo cliente y las parecidas por significado "
        "de cualquier otro, ganadas y perdidas, y los avisos que han salido en sus "
        "momentos clave. Las parecidas se buscan con tu identidad: lo que no "
        "puedes ver no sale."
    ),
)
def ver_consejos(oportunidad_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return consejos.consejos(db, oportunidad_id, principal)


@router_expediente.post(
    "/{oportunidad_id}/consejos/ia",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Qué hacer y qué no, según las lecciones, con la IA",
    description=(
        "Resume las lecciones que vienen a cuento en «haz esto / no hagas esto». "
        "Cada consejo dice de qué lección sale; los que no salen de ninguna se "
        "descartan y se cuentan. Sin lecciones no se llama al modelo."
    ),
)
def consejos_con_ia(oportunidad_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return consejos.consejos_ia(db, oportunidad_id, principal)


router_avisos = APIRouter(prefix="/avisos-lecciones", tags=["lecciones aprendidas"])
montar_listado(
    router_avisos,
    modelo=consejos.AvisoLeccion,
    objeto="aviso_leccion",
    permiso="opportunity:read",
    nombre="Avisos de las lecciones",
    orden="-updated_at",
    columnas_orden=frozenset({"updated_at", "created_at"}),
    ficha=False,
)

router_resumenes = APIRouter(prefix="/resumenes-lecciones", tags=["lecciones aprendidas"])
montar_listado(
    router_resumenes,
    modelo=consejos.ResumenLecciones,
    objeto="resumen_lecciones",
    permiso="opportunity:read",
    nombre="Resúmenes de lecciones",
    orden="-hasta",
    columnas_orden=frozenset({"hasta", "created_at"}),
    ficha=False,
)


ROUTERS_LECCIONES = [router_lecciones, router_expediente, router_avisos, router_resumenes]
