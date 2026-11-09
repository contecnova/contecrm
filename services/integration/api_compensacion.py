"""Motor externo de compensación, de verdad (CRM-03.02.03.04).

Las rutas puras de `api_suites` (`/compensacion/hechos`, `/conciliar`,
`/calculo`, `/cambio`) se quedan: son calculadoras publicadas. Éstas mandan
los hechos al motor conectado, guardan lo enviado y lo devuelto y lo
concilian contra las liquidaciones de la casa.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, exige_permiso
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.integration import compensacion as comp
from services.integration.api_telefonia import identidad_de

router = APIRouter(prefix="/compensacion", tags=["compensación"])


class MotorIn(BaseModel):
    conexion_id: UUID


class Periodo(BaseModel):
    desde: date
    hasta: date


class HechoManualIn(BaseModel):
    tipo: str = Field(..., description=" | ".join(comp.HECHOS))
    referencia: str = Field(..., min_length=1, max_length=200)
    fecha: date
    importe: Decimal
    moneda: str = Field("EUR", min_length=3, max_length=3)
    usuario_id: UUID | None = None
    motivo: str = Field("", max_length=1_000)


@router.get(
    "/motor",
    dependencies=[Depends(exige_permiso("commission:read"))],
    summary="Qué motor de compensación está conectado y qué le falta",
)
def ver_motor(db: DbDep, principal: AutenticadoDep) -> Any:
    return comp.estado_del_perfil(db, principal.tenant_id)


@router.put(
    "/motor",
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Conectar el motor de compensación sobre una conexión de integración",
    description=(
        "El motor es una conexión con dos operaciones declaradas: la que recibe "
        "los hechos y la que devuelve el cálculo. Cambiar de motor es declarar "
        "otras dos, no escribir otro módulo."
    ),
)
def fijar_motor(cuerpo: MotorIn, db: DbDep, principal: AutenticadoDep) -> Any:
    comp.declarar_perfil(db, principal.tenant_id, conexion_id=cuerpo.conexion_id)
    return comp.estado_del_perfil(db, principal.tenant_id)


@router.get(
    "/envios",
    dependencies=[Depends(exige_permiso("commission:read"))],
    summary="Los hechos mandados al motor, con lo que devolvió",
)
def listar_envios(
    db: DbDep,
    principal: AutenticadoDep,
    estado: str = Query(""),
    limite: int = Query(200, ge=1, le=1_000),
) -> Any:
    consulta = select(comp.HechoCompensacion).where(
        comp.HechoCompensacion.tenant_id == principal.tenant_id
    )
    if estado:
        consulta = consulta.where(comp.HechoCompensacion.estado == estado)
    filas = (
        db.execute(consulta.order_by(comp.HechoCompensacion.fecha.desc()).limit(limite))
        .scalars()
        .all()
    )
    return {"hechos": [comp.a_dict(f) for f in filas]}


@router.post(
    "/envios/recoger",
    dependencies=[Depends(exige_permiso("commission:write"))],
    summary="Traer de ventas las ganadas del periodo como hechos por mandar",
    description=(
        "Se piden a `sales` con la identidad de quien pulsa. Una venta ya "
        "mandada cuyo importe cambió **no se reescribe**: se devuelve como "
        "cambio, que es la conversación del clawback y no un ajuste en silencio."
    ),
)
def recoger(cuerpo: Periodo, db: DbDep, principal: AutenticadoDep) -> Any:
    return comp.recoger_ventas(
        db,
        principal.tenant_id,
        desde=cuerpo.desde,
        hasta=cuerpo.hasta,
        identidad=identidad_de(principal),
    )


@router.post(
    "/envios/manual",
    dependencies=[Depends(exige_permiso("commission:write"))],
    summary="Dar de alta un cobro, una devolución o una anulación",
    description=(
        "Lo que no es una venta ganada —un cobro, una devolución (clawback), una "
        "anulación— se da de alta con su referencia y queda por mandar. Nunca "
        "con la comisión dentro: el motor calcula."
    ),
)
def hecho_manual(cuerpo: HechoManualIn, db: DbDep, principal: AutenticadoDep) -> Any:
    fila, que = comp.registrar_hecho(
        db,
        principal.tenant_id,
        tipo=cuerpo.tipo,
        referencia=cuerpo.referencia,
        fecha=cuerpo.fecha,
        importe=cuerpo.importe,
        moneda=cuerpo.moneda,
        usuario_id=cuerpo.usuario_id,
        datos={"motivo": cuerpo.motivo} if cuerpo.motivo else None,
    )
    return {"hecho": comp.a_dict(fila), "que": que}


@router.post(
    "/envios/enviar",
    dependencies=[Depends(exige_permiso("commission:write"))],
    summary="Mandar al motor lo pendiente",
)
def enviar(db: DbDep, principal: AutenticadoDep) -> Any:
    return comp.enviar_pendientes(db, principal.tenant_id)


@router.post(
    "/envios/calculo",
    dependencies=[Depends(exige_permiso("commission:write"))],
    summary="Traer del motor lo calculado en el periodo",
    description=(
        "Se guarda tal cual junto a cada hecho, y se dice qué se mandó y no ha "
        "vuelto, y qué ha vuelto sin que lo mandáramos."
    ),
)
def calculo(cuerpo: Periodo, db: DbDep, principal: AutenticadoDep) -> Any:
    return comp.traer_calculo(db, principal.tenant_id, desde=cuerpo.desde, hasta=cuerpo.hasta)


@router.post(
    "/envios/conciliar",
    dependencies=[Depends(exige_permiso("commission:read"))],
    summary="Conciliar lo del motor contra lo que calcula la casa",
    description=(
        "Pone al lado de cada cálculo del motor la suma de las líneas de las "
        "liquidaciones de `sales` del periodo para esa venta, y enseña las "
        "diferencias. No corrige nada."
    ),
)
def conciliar(cuerpo: Periodo, db: DbDep, principal: AutenticadoDep) -> Any:
    return comp.conciliar_con_la_casa(
        db,
        principal.tenant_id,
        desde=cuerpo.desde,
        hasta=cuerpo.hasta,
        identidad=identidad_de(principal),
    )


ROUTERS_COMPENSACION = [router]
