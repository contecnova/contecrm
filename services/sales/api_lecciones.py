"""API de las lecciones aprendidas de las oportunidades cerradas."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_listado
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

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
    return _a_dict(fila)


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


ROUTERS_LECCIONES = [router_lecciones, router_expediente]
