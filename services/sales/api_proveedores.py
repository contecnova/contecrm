"""API del contrato con el proveedor y su alcance comercial
(CRM-09.01.01.07, CRM-09.01.01.09).

El módulo que hay detrás estaba **completo y sin ninguna puerta**: tres
decisiones escritas, probadas y que no podía pedir nadie. No daba ningún error
—un módulo sin llamante nunca lo da—: hacía que el producto se comportara como si
el contrato del proveedor no se mirase nunca.

Y lo que se comportaba como si no existiera es justo lo caro. Un contrato que
vence en marzo no avisa de que lo que se firmó en febrero con entrega en abril no
está cubierto por nada; un proveedor que no llega a Canarias se lleva igualmente
el encargo de un cliente de Las Palmas; y un plazo de preaviso que pasa renueva el
contrato solo, que se descubre con la factura.

Las rutas son de cálculo, como las de coste e ingresos: reciben lo que hay y
contestan qué significa. Guardar aquí el contrato sería un maestro de proveedores
nuevo al lado del que ya tiene `party`, y dos sitios donde está el mismo dato es
cómo se consulta el que no se actualizó.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from crmcore import fechas
from crmcore.http.deps import AutenticadoDep, DbDep, exige_permiso
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from services.sales import proveedores_comercial as pcom

router_proveedores = APIRouter(
    prefix="/proveedores-comerciales", tags=["proveedores: contrato y alcance"]
)


class ContratoIn(BaseModel):
    vigente_hasta: date | None = Field(
        None,
        description=(
            "Sin fecha no se da por indefinido: se dice que nadie la ha escrito, "
            "que es otra cosa y la que hay que arreglar"
        ),
    )
    renovacion_automatica: bool = False
    dias_preaviso: int = Field(0, ge=0, le=365)
    compromisos_con_clientes: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Lo vendido con este proveedor detrás, cada uno con su `referencia` y "
            "su `fecha`. Es lo que decide si hay un problema, no el calendario"
        ),
    )


class AlcanceIn(BaseModel):
    alcance: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Por eje: categoría, geografía, cliente y canal",
    )


@router_proveedores.post(
    "/contrato",
    dependencies=[Depends(exige_permiso("sales:read"))],
    summary="Qué hay que hacer con este contrato y cuándo, mirando lo vendido",
    description=(
        "**Un contrato de proveedor avisa por lo que hay vendido, no por su "
        "fecha.** El aviso a treinta días de la renovación es lo que hace todo "
        "el mundo y llega tarde: lo que decide si hay un problema es si hay "
        "compromisos con clientes **más allá** del fin del contrato. Esos son "
        "los que se quedan sin nadie detrás, y son los que hay que poner encima "
        "de la mesa al negociar.\n\n"
        "**El preaviso es una fecha límite real.** Pasada, el contrato se renueva "
        "solo aunque nadie lo quisiera, y eso se descubre con la factura — "
        "cuando ya no es una decisión, es un hecho.\n\n"
        "Y un contrato **sin fecha de fin no es indefinido**: es que nadie la ha "
        "escrito. La respuesta lo dice y se marca como no fiable, porque el día "
        "que el proveedor diga que terminó no habrá con qué discutirlo."
    ),
)
def contrato(cuerpo: ContratoIn, db: DbDep, principal: AutenticadoDep) -> Any:
    compromisos = []
    for compromiso in cuerpo.compromisos_con_clientes:
        copia = dict(compromiso)
        crudo = copia.get("fecha")
        if isinstance(crudo, str):
            try:
                copia["fecha"] = date.fromisoformat(crudo[:10])
            except ValueError:
                # Se deja como está: un compromiso con una fecha ilegible no
                # cuenta como descubierto, y eso es lo honesto. Inventarle una
                # fecha lo metería o lo sacaría de la lista según el formato.
                pass
        compromisos.append(copia)
    return pcom.estado_del_contrato(
        vigente_hasta=cuerpo.vigente_hasta,
        renovacion_automatica=cuerpo.renovacion_automatica,
        dias_preaviso=cuerpo.dias_preaviso,
        compromisos_con_clientes=compromisos,
        # El día lo pone quien tiene la sesión. Un «quedan cero días para el
        # preaviso» calculado en UTC se adelanta un día para media Europa de
        # madrugada, y aquí el día de diferencia es el que renueva el contrato.
        hoy=fechas.hoy(db),
    )


@router_proveedores.post(
    "/alcance",
    dependencies=[Depends(exige_permiso("sales:write"))],
    summary="Declarar qué puede servir un proveedor, en positivo",
    description=(
        "**Lo que no está declarado no se puede comprometer.** Al revés "
        "—declarar lo que NO puede y dar por hecho el resto— es lo que hace que "
        "se le encargue algo que no hace: la lista de exclusiones nunca está "
        "completa, porque nadie piensa en lo que todavía no ha pasado.\n\n"
        "Se contesta además **qué ejes han quedado sin acotar**, porque un eje "
        "vacío significa «cualquiera» y eso es una decisión: conviene que sea "
        "deliberada y no el resultado de no haber rellenado el campo."
    ),
)
def alcance(cuerpo: AlcanceIn, principal: AutenticadoDep) -> Any:
    return pcom.declarar_alcance(alcance=cuerpo.alcance)


@router_proveedores.post(
    "/puede-servir",
    dependencies=[Depends(exige_permiso("sales:read"))],
    summary="Si este proveedor puede atender este caso, y por qué no",
    description=(
        "**El «por qué no» es lo que hace útil la respuesta.** Quien está "
        "montando una oferta necesita saber si es por la zona o por el tipo de "
        "trabajo: en un caso busca otro proveedor y en el otro cambia lo que "
        "ofrece, y son dos tardes distintas.\n\n"
        "Encargar algo fuera del alcance no falla en el momento —falla en la "
        "entrega—, así que la oferta sale igual y lo que queda es una promesa "
        "sin nadie detrás."
    ),
)
def puede_servir(
    cuerpo: AlcanceIn,
    principal: AutenticadoDep,
    categoria: str = Query("", description="Qué tipo de trabajo"),
    geografia: str = Query("", description="Dónde hay que servirlo"),
    cliente_id: str | None = Query(None),
) -> Any:
    return pcom.puede_servir(
        alcance=cuerpo.alcance,
        categoria=categoria,
        geografia=geografia,
        cliente_id=cliente_id,
    )


ROUTERS_PROVEEDORES = [router_proveedores]
