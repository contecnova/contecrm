"""Rutas de la clasificación TCSEC (CRM-07.03.02.11). La lógica, en `tcsec.py`."""

from __future__ import annotations

from typing import Any

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from services.tenancy import tcsec

router_tcsec = APIRouter(prefix="/tcsec", tags=["GRC"])


class AtestiguarIn(BaseModel):
    resultado: str = Field(description="efectivo, parcial, inefectivo o no_aplica")
    evidencia: str = Field(min_length=1, description="Qué se revisó y dónde está la prueba")
    plan_accion: str = ""


@router_tcsec.get(
    "/evaluacion",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Nivel TCSEC de la instalación, requisito a requisito",
    description=(
        "Los requisitos automáticos se **miden en el momento** sobre el sistema "
        "—cadena de auditoría de cada servicio, aislamiento, segundo factor, "
        "segregación, etiquetas—; los demás salen de su atestación en el GRC. "
        "Lo que no se ha podido medir sale `sin_medir`, nunca como cumplido."
    ),
)
def evaluacion(db: DbDep, principal: AutenticadoDep) -> Any:
    return tcsec.evaluar(db, principal.tenant_id, principal.id)


@router_tcsec.put(
    "/requisitos/{clave}/atestacion",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Atestiguar un requisito TCSEC que no se puede medir",
    description=(
        "Sólo los que no se comprueban solos. Queda como evaluación del control "
        "`TCSEC-<clave>` del GRC, con su evidencia y su caducidad anual."
    ),
)
def atestiguar(clave: str, datos: AtestiguarIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    return tcsec.atestiguar(
        uow.db,
        tenant_id=principal.tenant_id,
        requisito=clave,
        resultado=datos.resultado,
        evidencia=datos.evidencia,
        plan_accion=datos.plan_accion,
        por=principal.id,
    )


@router_tcsec.get(
    "/informe",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Informe TCSEC para auditoría",
    description=(
        "El mismo resultado que `/evaluacion`, escrito en Markdown para "
        "adjuntarlo o imprimirlo: `{fichero, contenido}`. Va dentro de JSON, como "
        "las demás exportaciones, para que el cliente no tenga que distinguir."
    ),
)
def informe(db: DbDep, principal: AutenticadoDep) -> Any:
    evaluacion = tcsec.evaluar(db, principal.tenant_id, principal.id)
    return {
        "fichero": f"informe-tcsec-{evaluacion['generado_at'][:10]}.md",
        "nivel": evaluacion["nivel"],
        "contenido": tcsec.informe_markdown(evaluacion),
    }


ROUTERS_TCSEC = [router_tcsec]
