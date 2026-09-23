"""API de incentivos y comisiones (CRM-03.02.03)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_ficha  # noqa: E402
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.sales import comisiones as com

router = APIRouter(prefix="/planes-comision", tags=["comisiones"])
router_liq = APIRouter(prefix="/liquidaciones", tags=["comisiones"])


class CrearPlan(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    nombre: str = Field(..., min_length=1, max_length=200)
    desde: date
    hasta: date | None = None
    base: str = Field("importe", description="importe · margen · unidades")
    moneda: str = "EUR"
    periodicidad: str = "mensual"
    devengo: str = Field(
        "cierre",
        description=(
            "cierre o cobro. Se declara: es la primera pregunta de cualquier comercial "
            "y cambia el calendario de pagos entero"
        ),
    )
    tope_periodo: Decimal | None = None


class CrearRegla(BaseModel):
    tipo: str = Field(..., description="porcentaje · escalado · acelerador · spiff")
    nombre: str = ""
    orden: int = 100
    desde_valor: Decimal = Decimal(0)
    hasta_valor: Decimal | None = None
    porcentaje: Decimal = Decimal(0)
    importe_fijo: Decimal = Decimal(0)
    multiplicador: Decimal = Decimal(1)
    modo_tramo: str = Field(
        "marginal",
        description=(
            "marginal o retroactivo. Es la ambigüedad que más disputas causa y aquí "
            "hay que decirla"
        ),
    )
    condiciones: list[dict[str, Any]] = Field(default_factory=list)
    vigente_desde: date | None = None
    vigente_hasta: date | None = None


class Asignar(BaseModel):
    usuario_id: UUID | None = None
    partner_id: UUID | None = None
    desde: date | None = None
    hasta: date | None = None
    cuota: Decimal | None = None


class Simular(BaseModel):
    operaciones: list[dict[str, Any]] = Field(
        ...,
        description="Las trae quien llama: {id, tipo, concepto, importe, margen, unidades, fecha}",
    )
    cuota: Decimal | None = None


class Previsionar(BaseModel):
    cerradas: list[dict[str, Any]] = Field(default_factory=list)
    pipeline: list[dict[str, Any]] = Field(
        default_factory=list, description="Con `probabilidad` en cada una: entra ponderado"
    )
    cuota: Decimal | None = None


class Liquidar(BaseModel):
    plan_id: UUID
    desde: date
    hasta: date
    operaciones: list[dict[str, Any]] = Field(default_factory=list)
    usuario_id: UUID | None = None
    partner_id: UUID | None = None
    cuota: Decimal | None = None


class Disputar(BaseModel):
    motivo: str = Field(..., min_length=1)
    linea_id: UUID | None = None
    importe_reclamado: Decimal | None = None


class ResolverDisputa(BaseModel):
    aceptar: bool
    resolucion: str = Field(..., min_length=1)
    ajuste: Decimal | None = None


class Pagar(BaseModel):
    referencia: str = Field(..., min_length=1, description="Nómina, remesa o factura")
    fecha: date | None = None


class Revertir(BaseModel):
    linea_id: UUID
    motivo: str = Field(..., min_length=1)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("commission:write"))],
    summary="Crear un plan de comisiones",
    description="Nace en **borrador**: un plan activo liquida.",
)
def crear_plan(datos: CrearPlan, uow: UowDep) -> Any:
    fila = com.crear_plan(uow, **datos.model_dump())
    return {"id": str(fila.id), "clave": fila.clave, "estado": fila.estado}


@router.get(
    "",
    dependencies=[Depends(exige_permiso("commission:read"))],
    summary="Planes de comisión",
)
def listar_planes(db: DbDep, principal: AutenticadoDep) -> Any:
    filas = (
        db.execute(
            select(com.PlanComision)
            .where(com.PlanComision.tenant_id == principal.tenant_id)
            .order_by(com.PlanComision.desde.desc())
        )
        .scalars()
        .all()
    )
    return {
        "planes": [
            {
                "id": str(f.id),
                "clave": f.clave,
                "nombre": f.nombre,
                "base": f.base,
                "devengo": f.devengo,
                "estado": f.estado,
                "desde": str(f.desde),
                "hasta": str(f.hasta) if f.hasta else None,
                "tope_periodo": str(f.tope_periodo) if f.tope_periodo is not None else None,
            }
            for f in filas
        ]
    }


@router.post(
    "/{plan_id}/reglas",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("commission:write"))],
    summary="Añadir una regla al plan",
)
def anadir_regla(plan_id: UUID, datos: CrearRegla, uow: UowDep) -> Any:
    fila = com.anadir_regla(uow, plan_id, **datos.model_dump())
    return {"id": str(fila.id), "tipo": fila.tipo, "modo_tramo": fila.modo_tramo}


@router.get(
    "/{plan_id}/revision",
    dependencies=[Depends(exige_permiso("commission:read"))],
    summary="Revisar el plan antes de activarlo",
    description=(
        "Busca huecos y solapes en los tramos. Un hueco entre 50.000 y 60.000 no da "
        "error en ningún sitio: **da cero**, y quien venda 55.000 cobrará menos que "
        "quien vendió 49.000."
    ),
)
def revision(plan_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return com.revisar_plan(db, principal.tenant_id, plan_id)


@router.post(
    "/{plan_id}/activar",
    dependencies=[Depends(exige_permiso("commission:write"))],
    summary="Activar el plan",
)
def activar(plan_id: UUID, uow: UowDep, forzar: bool = Query(False)) -> Any:
    fila = com.activar_plan(uow, plan_id, forzar=forzar)
    return {"id": str(fila.id), "estado": fila.estado}


@router.post(
    "/{plan_id}/asignaciones",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("commission:write"))],
    summary="Asignar el plan a una persona o a un partner",
)
def asignar(plan_id: UUID, datos: Asignar, uow: UowDep) -> Any:
    fila = com.asignar(uow, plan_id, **datos.model_dump())
    return {"id": str(fila.id)}


@router.post(
    "/{plan_id}/simular",
    dependencies=[Depends(exige_permiso("commission:read"))],
    summary="Simular una liquidación",
    description=(
        "Es **la misma función** que liquida. Una simulación calculada por otro "
        "camino acaba no coincidiendo con la nómina."
    ),
)
def simular(plan_id: UUID, datos: Simular, db: DbDep, principal: AutenticadoDep) -> Any:
    return com.calcular(
        db,
        principal.tenant_id,
        plan_id=plan_id,
        operaciones=datos.operaciones,
        cuota=datos.cuota,
    )


@router.post(
    "/{plan_id}/prevision",
    dependencies=[Depends(exige_permiso("commission:read"))],
    summary="Previsión de comisión con el pipeline",
    description=(
        "El pipeline entra **ponderado** y se devuelven los dos números por "
        "separado: lo devengado y lo previsto. Mezclarlos da una cifra que parece "
        "ganada y se acaba gastando."
    ),
)
def prevision(plan_id: UUID, datos: Previsionar, db: DbDep, principal: AutenticadoDep) -> Any:
    return com.previsionar(
        db,
        principal.tenant_id,
        plan_id=plan_id,
        cerradas=datos.cerradas,
        pipeline=datos.pipeline,
        cuota=datos.cuota,
    )


@router_liq.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("commission:write"))],
    summary="Liquidar un periodo",
    description=(
        "Guarda el plan aplicado con la liquidación: quien cobró en marzo tiene "
        "derecho a que marzo siga diciendo lo mismo en junio."
    ),
)
def liquidar(datos: Liquidar, uow: UowDep) -> Any:
    fila = com.liquidar(uow, **datos.model_dump())
    return {"id": str(fila.id), "total": str(fila.total), "estado": fila.estado}


@router_liq.get(
    "",
    dependencies=[Depends(exige_permiso("commission:read"))],
    summary="Liquidaciones",
)
def listar(
    db: DbDep,
    principal: AutenticadoDep,
    estado: str | None = Query(None),
    limite: int = Query(50, ge=1, le=200),
) -> Any:
    consulta = select(com.Liquidacion).where(com.Liquidacion.tenant_id == principal.tenant_id)
    if estado:
        consulta = consulta.where(com.Liquidacion.estado == estado)
    filas = (
        db.execute(consulta.order_by(com.Liquidacion.desde.desc()).limit(limite)).scalars().all()
    )
    return {
        "liquidaciones": [
            {
                "id": str(f.id),
                "estado": f.estado,
                "desde": str(f.desde),
                "hasta": str(f.hasta),
                "total": str(f.total),
                "moneda": f.moneda,
                "usuario_id": str(f.usuario_id) if f.usuario_id else None,
                "partner_id": str(f.partner_id) if f.partner_id else None,
                "pago_referencia": f.pago_referencia,
            }
            for f in filas
        ]
    }


@router_liq.get(
    "/{liquidacion_id}",
    dependencies=[Depends(exige_permiso("commission:read"))],
    summary="Una liquidación con su desglose",
    description="Cada euro con su origen, su regla y su porcentaje.",
)
def detalle(liquidacion_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return com.detalle(db, principal.tenant_id, liquidacion_id)


@router_liq.post(
    "/{liquidacion_id}/aprobacion",
    dependencies=[Depends(exige_permiso("commission:write"))],
    summary="Enviar a aprobación",
    description=(
        "Pide por el motor de aprobaciones del orquestador, el mismo que aprueba "
        "todo lo demás: una segunda cadena aquí daría dos sitios donde mirar."
    ),
)
def enviar_a_aprobacion(liquidacion_id: UUID, uow: UowDep) -> Any:
    fila = com.enviar_a_aprobacion(uow, liquidacion_id)
    return {"id": str(fila.id), "estado": fila.estado}


@router_liq.post(
    "/{liquidacion_id}/aprobar",
    dependencies=[Depends(exige_permiso("commission:approve"))],
    summary="Aprobar la liquidación",
    description="No se aprueba con disputas abiertas.",
)
def aprobar(liquidacion_id: UUID, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = com.aprobar(uow, liquidacion_id, por=principal.id)
    return {"id": str(fila.id), "estado": fila.estado}


@router_liq.post(
    "/{liquidacion_id}/disputas",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("commission:read"))],
    summary="Abrir una disputa",
    description=(
        "Congela el pago mientras esté abierta. Fuera de plazo se registra igual, "
        "marcada: ni se pierde ni se acepta en silencio."
    ),
)
def disputar(liquidacion_id: UUID, datos: Disputar, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = com.disputar(uow, liquidacion_id, abierta_por=principal.id, **datos.model_dump())
    return {"id": str(fila.id), "estado": fila.estado, "resolucion": fila.resolucion}


@router_liq.post(
    "/disputas/{disputa_id}/resolver",
    dependencies=[Depends(exige_permiso("commission:approve"))],
    summary="Resolver una disputa",
    description=(
        "El ajuste entra como **línea nueva**: corregir en sitio deja un número que "
        "ya no coincide con lo comunicado y sin nada que explique la diferencia."
    ),
)
def resolver(
    disputa_id: UUID, datos: ResolverDisputa, uow: UowDep, principal: AutenticadoDep
) -> Any:
    fila = com.resolver_disputa(uow, disputa_id, por=principal.id, **datos.model_dump())
    return {"id": str(fila.id), "estado": fila.estado}


@router_liq.post(
    "/{liquidacion_id}/pagar",
    dependencies=[Depends(exige_permiso("commission:approve"))],
    summary="Marcar pagada",
    description="Exige referencia: «pagada» sin dónde mirarlo no se puede comprobar.",
)
def pagar(liquidacion_id: UUID, datos: Pagar, uow: UowDep) -> Any:
    fila = com.marcar_pagada(uow, liquidacion_id, **datos.model_dump())
    return {"id": str(fila.id), "estado": fila.estado, "referencia": fila.pago_referencia}


@router_liq.post(
    "/{liquidacion_id}/revertir",
    dependencies=[Depends(exige_permiso("commission:write"))],
    summary="Revertir una comisión devengada",
    description=(
        "Línea negativa que apunta a la original, nunca un borrado: una reversión "
        "invisible es la forma más rápida de que alguien no reconozca su nómina."
    ),
)
def revertir(liquidacion_id: UUID, datos: Revertir, uow: UowDep) -> Any:
    fila = com.revertir(uow, liquidacion_id, **datos.model_dump())
    return {"id": str(fila.id), "importe": str(fila.importe)}


ROUTERS_COMISIONES = [router, router_liq]


# ── La ficha del registro ─────────────────────────────────────────────────
# Sin ella, las acciones que cuelgan de un registro no se alcanzan desde
# ninguna pantalla: existen, se prueban y nadie las usa.
montar_ficha(
    router,
    modelo=com.PlanComision,
    objeto="plan_comision",
    permiso_leer="commission:read",
    permiso_escribir="commission:write",
    nombre="Planes de comisión",
    parametro="plan_id",
)
