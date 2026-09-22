"""API de fondos de marketing del canal (CRM-03.04.01.04)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.marketing import fondos as mdf

router = APIRouter(prefix="/fondos-mdf", tags=["mdf"])
router_sol = APIRouter(prefix="/solicitudes-mdf", tags=["mdf"])


class CrearFondo(BaseModel):
    partner_id: UUID
    desde: date
    hasta: date
    asignado: Decimal
    nombre: str = ""
    moneda: str = "EUR"


class Solicitar(BaseModel):
    titulo: str = Field(..., min_length=1, max_length=200)
    importe: Decimal
    actividad: str = ""
    descripcion: str = ""
    fecha_actividad: date | None = None


class Decidir(BaseModel):
    aprobar: bool
    importe_aprobado: Decimal | None = Field(
        None, description="Puede ser menor que lo pedido: esa es la decisión real"
    )
    motivo: str = ""
    dias_para_justificar: int | None = None


class Justificar(BaseModel):
    importe: Decimal
    evidencias: list[dict[str, Any]] = Field(
        default_factory=list, description="Referencias al gestor documental, no ficheros"
    )
    resultados: dict[str, Any] = Field(
        default_factory=dict, description="Leads, oportunidades, asistentes… Vacío = sin medir"
    )


class RevisarJustificacion(BaseModel):
    aceptar: bool
    motivo: str = ""


class PagarMdf(BaseModel):
    referencia: str = Field(..., min_length=1)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("campaign:write"))],
    summary="Abrir un fondo de marketing para un partner",
)
def crear_fondo(datos: CrearFondo, uow: UowDep) -> Any:
    fila, avisos = mdf.crear_fondo(uow, **datos.model_dump())
    return {"id": str(fila.id), "asignado": str(fila.asignado), "avisos": avisos}


@router.get(
    "",
    dependencies=[Depends(exige_permiso("campaign:read"))],
    summary="Fondos abiertos",
)
def listar(
    db: DbDep,
    principal: AutenticadoDep,
    partner_id: UUID | None = Query(None),
    limite: int = Query(50, ge=1, le=200),
) -> Any:
    consulta = select(mdf.FondoMdf).where(mdf.FondoMdf.tenant_id == principal.tenant_id)
    if partner_id:
        consulta = consulta.where(mdf.FondoMdf.partner_id == partner_id)
    filas = db.execute(consulta.order_by(mdf.FondoMdf.desde.desc()).limit(limite)).scalars().all()
    return {
        "fondos": [
            {
                "id": str(f.id),
                "partner_id": str(f.partner_id),
                "nombre": f.nombre,
                "desde": str(f.desde),
                "hasta": str(f.hasta),
                "asignado": str(f.asignado),
                "moneda": f.moneda,
                "cerrado": f.cerrado,
            }
            for f in filas
        ]
    }


@router.get(
    "/{fondo_id}/saldo",
    dependencies=[Depends(exige_permiso("campaign:read"))],
    summary="Saldo del fondo",
    description=(
        "**Lo comprometido resta.** Un saldo que solo descuenta lo pagado enseña "
        "dinero que ya tiene dueño, y con ese saldo se aprueban campañas que luego "
        "no se pueden pagar."
    ),
)
def saldo(fondo_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return mdf.saldo(db, principal.tenant_id, fondo_id)


@router.get(
    "/{fondo_id}/retorno",
    dependencies=[Depends(exige_permiso("campaign:read"))],
    summary="Qué salió de lo gastado",
    description=(
        "Con la **cobertura de la medición**: un retorno estupendo calculado sobre "
        "el 10 % del gasto no es el retorno del fondo."
    ),
)
def retorno(fondo_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return mdf.retorno(db, principal.tenant_id, fondo_id)


@router.post(
    "/{fondo_id}/solicitudes",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("campaign:write"))],
    summary="Pedir fondos para una acción",
    description=(
        "No se comprueba el saldo al pedir: impedirlo escondería cuánto se está "
        "pidiendo de más, que es justo lo que hace falta para decidir si se amplía."
    ),
)
def solicitar(fondo_id: UUID, datos: Solicitar, uow: UowDep) -> Any:
    fila = mdf.solicitar(uow, fondo_id, **datos.model_dump())
    return {"id": str(fila.id), "estado": fila.estado}


@router_sol.get(
    "",
    dependencies=[Depends(exige_permiso("campaign:read"))],
    summary="Solicitudes de fondos",
)
def listar_solicitudes(
    db: DbDep,
    principal: AutenticadoDep,
    fondo_id: UUID | None = Query(None),
    estado: str | None = Query(None),
    limite: int = Query(50, ge=1, le=200),
) -> Any:
    consulta = select(mdf.SolicitudMdf).where(mdf.SolicitudMdf.tenant_id == principal.tenant_id)
    if fondo_id:
        consulta = consulta.where(mdf.SolicitudMdf.fondo_id == fondo_id)
    if estado:
        consulta = consulta.where(mdf.SolicitudMdf.estado == estado)
    filas = (
        db.execute(consulta.order_by(mdf.SolicitudMdf.created_at.desc()).limit(limite))
        .scalars()
        .all()
    )
    return {
        "solicitudes": [
            {
                "id": str(f.id),
                "titulo": f.titulo,
                "actividad": f.actividad,
                "estado": f.estado,
                "solicitado": str(f.importe_solicitado),
                "aprobado": str(f.importe_aprobado) if f.importe_aprobado is not None else None,
                "justificado": str(f.importe_justificado)
                if f.importe_justificado is not None
                else None,
                "justificar_antes_de": str(f.justificar_antes_de)
                if f.justificar_antes_de
                else None,
                "motivo": f.motivo,
                "sin_resultados": not bool(f.resultados),
            }
            for f in filas
        ]
    }


@router_sol.post(
    "/{solicitud_id}/decidir",
    dependencies=[Depends(exige_permiso("campaign:write"))],
    summary="Aprobar con importe y plazo, o rechazar con motivo",
    description=(
        "Aprobar por encima del saldo se rechaza: es el momento exacto en que se "
        "sobrecompromete un fondo."
    ),
)
def decidir(solicitud_id: UUID, datos: Decidir, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = mdf.decidir(uow, solicitud_id, decidida_por=principal.id, **datos.model_dump())
    return {
        "id": str(fila.id),
        "estado": fila.estado,
        "importe_aprobado": str(fila.importe_aprobado) if fila.importe_aprobado else None,
        "justificar_antes_de": str(fila.justificar_antes_de) if fila.justificar_antes_de else None,
    }


@router_sol.post(
    "/{solicitud_id}/justificaciones",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("campaign:write"))],
    summary="Presentar la prueba del gasto",
    description=(
        "Sin evidencia no hay justificación. Fuera de plazo se admite **marcado**: "
        "no dejar hace que la factura llegue por correo y se meta a mano sin plazo."
    ),
)
def justificar(solicitud_id: UUID, datos: Justificar, uow: UowDep) -> Any:
    fila, avisos = mdf.justificar(uow, solicitud_id, **datos.model_dump())
    return {"id": str(fila.id), "importe": str(fila.importe), "avisos": avisos}


@router_sol.post(
    "/justificaciones/{justificacion_id}/revisar",
    dependencies=[Depends(exige_permiso("campaign:write"))],
    summary="Aceptar o rechazar la justificación",
    description=(
        "Lo aceptado es **lo menor** de lo aprobado y lo justificado, y lo que sobra "
        "vuelve al fondo."
    ),
)
def revisar(
    justificacion_id: UUID, datos: RevisarJustificacion, uow: UowDep, principal: AutenticadoDep
) -> Any:
    fila = mdf.revisar_justificacion(
        uow, justificacion_id, revisada_por=principal.id, **datos.model_dump()
    )
    return {
        "id": str(fila.id),
        "estado": fila.estado,
        "importe_justificado": str(fila.importe_justificado)
        if fila.importe_justificado is not None
        else None,
    }


@router_sol.post(
    "/{solicitud_id}/pagar",
    dependencies=[Depends(exige_permiso("campaign:write"))],
    summary="Marcar pagada con su referencia",
)
def pagar(solicitud_id: UUID, datos: PagarMdf, uow: UowDep) -> Any:
    fila = mdf.pagar(uow, solicitud_id, **datos.model_dump())
    return {"id": str(fila.id), "estado": fila.estado, "referencia": fila.pago_referencia}


@router_sol.post(
    "/caducar",
    dependencies=[Depends(exige_permiso("campaign:write"))],
    summary="Liberar lo aprobado que nadie justificó en plazo",
    description=(
        "Explícito y auditado: el partner tiene derecho a ver qué día se le cayó la " "reserva."
    ),
)
def caducar(uow: UowDep) -> Any:
    return mdf.caducar_pendientes(uow)


ROUTERS_FONDOS = [router, router_sol]
