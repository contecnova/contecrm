"""API de los modelos entrenados con el histórico y del asistente que actúa
(CRM-02.01.02.02, CRM-05.02.01.02, CRM-05.02.01.03, CRM-02.01.01.08,
CRM-04.03.02.02).

Entrenar es de quien administra la IA; puntuar un registro es de quien usa la
IA y además puede ver ese registro —se lee con su identidad—. Ninguna ruta de
aquí escribe en el CRM salvo dos, y las dos lo hacen por su API con los
permisos de quien pide: crear el segmento en marketing y ejecutar la acción
que el asistente propuso y la persona confirmó.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from services.intelligence import acciones_asistente as acc
from services.intelligence import predictivo as pre

router_predictivo = APIRouter(prefix="/ia/predictivo", tags=["ia"])
router_asistente = APIRouter(prefix="/ia/asistente", tags=["ia"])


class Programar(BaseModel):
    activa: bool = True


class Segmento(BaseModel):
    criterio: str = Field("propension", description="propension · valor_esperado · scoring_lead")
    minimo: float = Field(
        0.5, ge=0, description="Puntuación mínima (probabilidad, o importe en valor esperado)"
    )
    tope: int | None = Field(None, ge=1, le=100_000)
    nombre: str = Field("", max_length=200)


class Confirmar(BaseModel):
    confirmar: bool
    argumentos: dict[str, Any] = Field(default_factory=dict)


@router_predictivo.post(
    "/{tipo}/entrenar",
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Entrenar con el histórico del CRM, medir y publicar si supera el mínimo",
    description=(
        "Lee el histórico por la API del CRM —leads convertidos y descartados, "
        "oportunidades ganadas y perdidas, líneas de lo ganado—, entrena, mide "
        "contra el periodo más reciente que el modelo no ha visto y **sólo "
        "publica si supera el mínimo configurado** (AUC para clasificar, mejora "
        "sobre la mediana para importe y días). Si no hay bastantes datos, lo dice "
        "y no entrena. Tipos: `scoring_lead`, `cierre`, `importe`, "
        "`fecha_cierre`, `propension`, `siguiente_oferta`."
    ),
)
def entrenar(tipo: str, uow: UowDep, principal: AutenticadoDep) -> Any:
    return pre.entrenar(uow, tipo=tipo, usuario_id=principal.id)


@router_predictivo.get(
    "/versiones",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Las versiones de cada modelo, con sus métricas y su estado",
)
def versiones(db: DbDep, principal: AutenticadoDep, tipo: str = Query("")) -> Any:
    return {
        "versiones": pre.versiones(db, principal.tenant_id, tipo or None),
        "entrenables": pre.ENTRENABLES,
        # Cada cuántos días se reentrena lo programado, para decirlo antes de
        # que haya ninguna programación.
        "reentreno_dias": int(pre._ajuste("ia_reentreno_dias", db)),
    }


@router_predictivo.get(
    "/programaciones",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Qué modelos se reentrenan solos, cuándo toca y qué salió la última vez",
)
def programaciones(db: DbDep, principal: AutenticadoDep) -> Any:
    return pre.programaciones(db, principal.tenant_id)


@router_predictivo.put(
    "/{tipo}/programacion",
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Activar o parar el reentreno programado de un modelo",
)
def programar(tipo: str, cuerpo: Programar, uow: UowDep, principal: AutenticadoDep) -> Any:
    return pre.programar(uow, tipo=tipo, activa=cuerpo.activa, usuario_id=principal.id)


@router_predictivo.post(
    "/segmento",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Crear un segmento con los mejor puntuados (CRM-02.01.01.08)",
    description=(
        "Puntúa todas las cuentas (propensión o valor esperado) o los leads "
        "abiertos con el modelo publicado, y crea **en marketing** un segmento "
        "con los que pasan del mínimo, congelado ese día. Se crea con tus "
        "permisos: hace falta `segment:write`."
    ),
)
def segmento(cuerpo: Segmento, uow: UowDep, principal: AutenticadoDep) -> Any:
    return pre.segmento(
        uow,
        principal=principal,
        criterio=cuerpo.criterio,
        minimo=cuerpo.minimo,
        tope=cuerpo.tope,
        nombre=cuerpo.nombre,
    )


@router_predictivo.get(
    "/{objeto}/{objeto_id}",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Las predicciones de un registro real, con sus factores",
    description=(
        "`lead` → probabilidad de convertir; `oportunidad` → probabilidad de "
        "ganarla, importe y fecha real de cierre con su intervalo; `cuenta` → "
        "propensión a comprar y siguiente mejor oferta. El registro se lee con "
        "**tus** permisos. Cada número va con lo que lo sube y lo que lo baja, y "
        "si no hay modelo publicado se dice por qué. Se guarda con su caducidad; "
        "`recalcular=true` la ignora."
    ),
)
def puntuar(
    objeto: str,
    objeto_id: UUID,
    uow: UowDep,
    principal: AutenticadoDep,
    recalcular: bool = Query(False),
) -> Any:
    return pre.puntuar_registro(
        uow, objeto=objeto, objeto_id=objeto_id, principal=principal, recalcular=recalcular
    )


@router_asistente.get(
    "/acciones",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Las acciones que el asistente te ha propuesto, y qué pasó con ellas",
)
def mis_acciones(db: DbDep, principal: AutenticadoDep) -> Any:
    return {
        "acciones": acc.mias(db, principal.tenant_id, principal.id),
        "disponibles": acc.disponibles(principal),
    }


@router_asistente.post(
    "/acciones/{accion_id}",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Confirmar (y ejecutar) o descartar una acción propuesta (CRM-04.03.02.02)",
    description=(
        "Sólo quien hizo la pregunta, y antes de que caduque. Al confirmar se "
        "ejecuta por la API del CRM **con tu identidad y tus permisos**; se "
        "pueden corregir los argumentos, pero sólo los que la acción declara."
    ),
)
def confirmar(accion_id: UUID, cuerpo: Confirmar, uow: UowDep, principal: AutenticadoDep) -> Any:
    return acc.ejecutar(
        uow,
        accion_id=accion_id,
        principal=principal,
        confirmar=cuerpo.confirmar,
        argumentos=cuerpo.argumentos,
    )


ROUTERS_PREDICTIVO = [router_predictivo, router_asistente]
