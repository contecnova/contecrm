"""El índice de conocimiento por API (CRM-04.03.01.04, CRM-05.02.02.03).

Qué hay indexado, indexar un texto y buscar lo parecido. Lo que se devuelve al
buscar se recorta a lo que quien pregunta puede ver: cada fragmento lleva el
permiso de su fuente y se comprueba aquí, antes de que salga.
"""

from __future__ import annotations

from typing import Any

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from services.intelligence import indice

router_indice = APIRouter(prefix="/ia/indice", tags=["ia"])


class IndexarIn(BaseModel):
    fuente: str = Field(..., description="«articulo» o «caso_resuelto»")
    referencia: str = Field(..., min_length=1, max_length=80)
    titulo: str = ""
    texto: str = Field(..., min_length=1)


class BuscarIn(BaseModel):
    texto: str = Field(..., min_length=2, max_length=4_000)
    fuentes: list[str] = Field(default_factory=lambda: list(indice.FUENTES))
    tope: int | None = Field(None, ge=1, le=200)


@router_indice.get(
    "",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Qué hay en el índice de conocimiento",
    description="Cuántos artículos y casos resueltos hay indexados, y con qué modelo.",
)
def estado(db: DbDep, principal: AutenticadoDep) -> Any:
    return indice.estado(db, principal.tenant_id)


@router_indice.post(
    "/indexar",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Indexar un artículo o un caso resuelto",
    description=(
        "Calcula su vector con el proveedor declarado para `embeddings` y lo guarda. "
        "Si el texto y el modelo no han cambiado, no se recalcula ni se paga."
    ),
)
def indexar(datos: IndexarIn, uow: UowDep) -> Any:
    return indice.indexar(
        uow,
        fuente=datos.fuente,
        referencia=datos.referencia,
        titulo=datos.titulo,
        texto=datos.texto,
    )


@router_indice.post(
    "/buscar",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Lo más parecido en el índice, por significado",
    description=(
        "Con su parecido entre 0 y 1. Lo que quien pregunta no puede ver no sale, "
        "y no se dice que existe."
    ),
)
def buscar(datos: BuscarIn, db: DbDep, principal: AutenticadoDep) -> Any:
    fuentes = tuple(f for f in datos.fuentes if f in indice.FUENTES) or indice.FUENTES
    resultados = indice.buscar(
        db, principal.tenant_id, texto=datos.texto, fuentes=fuentes, tope=datos.tope
    )
    return {"items": [r for r in resultados if principal.tiene(r["permiso"])]}


ROUTERS_INDICE = [router_indice]
