"""API de hora y canal por destinatario (CRM-02.02.02.05).

Optimizar por destinatario suena mejor que «los martes a las diez» y tiene una
trampa grande: con pocos datos, lo que se optimiza es el ruido. Por eso todo lo de
aquí dice **cuándo no se puede personalizar**.
"""

from __future__ import annotations

from typing import Any

from crmcore.http.deps import AutenticadoDep, exige_permiso
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from services.marketing import momento as mom

router_momento = APIRouter(prefix="/momento", tags=["hora y canal"])


class FranjaIn(BaseModel):
    interacciones: list[dict[str, Any]] = Field(default_factory=list)
    huso: str = "UTC"


class CanalIn(BaseModel):
    interacciones: list[dict[str, Any]] = Field(default_factory=list)
    prohibidos: list[str] = Field(default_factory=list)


class PlanIn(BaseModel):
    destinatarios: list[dict[str, Any]] = Field(default_factory=list)
    hora_por_defecto: int = 10


class CompararIn(BaseModel):
    con_optimizacion: dict[str, Any] = Field(default_factory=dict)
    sin_optimizacion: dict[str, Any] = Field(default_factory=dict)


@router_momento.post(
    "/franja",
    dependencies=[Depends(exige_permiso("marketing:read"))],
    summary="A qué hora contesta esta persona, si es que se puede saber",
    description=(
        "Con menos de un puñado de respuestas **no se personaliza**: concluir que "
        "alguien prefiere las tardes porque abrió dos correos por la tarde es "
        "echar una moneda dos veces y creerse el resultado.\n\n"
        "Y la franja es **la suya**: la campaña «a las nueve» llega a las tres de "
        "la mañana a quien está en otro huso."
    ),
)
def franja(cuerpo: FranjaIn, principal: AutenticadoDep) -> Any:
    return mom.franja_preferida(
        interacciones=cuerpo.interacciones, huso_del_destinatario=cuerpo.huso
    )


@router_momento.post(
    "/canal",
    dependencies=[Depends(exige_permiso("marketing:read"))],
    summary="Por dónde contesta y por dónde no se le puede escribir",
    description=(
        "Se mide por **respuesta, no por apertura**: abrir un correo no significa "
        "nada, y optimizar por aperturas lleva a escribir más a quien los abre y "
        "nunca contesta.\n\n"
        "Lo que la persona pidió manda sobre lo que dice el modelo: si dijo que "
        "no se le llame, eso no es una preferencia estimada, es una instrucción."
    ),
)
def canal(cuerpo: CanalIn, principal: AutenticadoDep) -> Any:
    return mom.canal_preferido(interacciones=cuerpo.interacciones, prohibidos=cuerpo.prohibidos)


@router_momento.post(
    "/plan",
    dependencies=[Depends(exige_permiso("marketing:write"))],
    summary="Repartir el envío por destinatario",
    description=(
        "Devuelve **cuántos van a la hora general**, que es el número que "
        "importa: si el 90 % va por defecto, la personalización no está haciendo "
        "nada y conviene saberlo antes de contarlo como una mejora."
    ),
)
def plan(cuerpo: PlanIn, principal: AutenticadoDep) -> Any:
    return mom.planificar_envio(
        destinatarios=cuerpo.destinatarios, hora_por_defecto=cuerpo.hora_por_defecto
    )


@router_momento.post(
    "/comparar",
    dependencies=[Depends(exige_permiso("marketing:read"))],
    summary="Si personalizar la hora ha servido de algo",
    description=(
        "Contra mandar a hora fija, que es la alternativa real. Sin esa "
        "comparación cualquier resultado se atribuye a la optimización, incluida "
        "la mejora que venía del asunto del correo."
    ),
)
def comparar(cuerpo: CompararIn, principal: AutenticadoDep) -> Any:
    return mom.comparar_con_hora_fija(
        con_optimizacion=cuerpo.con_optimizacion, sin_optimizacion=cuerpo.sin_optimizacion
    )


ROUTERS_MOMENTO = [router_momento]
