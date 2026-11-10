"""Rutas de los controles de serie del GRC (CRM-07.03.02.12 a .15). La lógica, en `grc_serie.py`."""

from __future__ import annotations

from typing import Any

from crmcore.errors import NoEncontrado
from crmcore.fechas import hoy
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from services.tenancy import grc, grc_serie
from services.tenancy.api_grc import _control

router_grc_serie = APIRouter(prefix="/grc", tags=["GRC"])


class ActivoIn(BaseModel):
    activo: bool


@router_grc_serie.get(
    "/de-serie",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Qué controles de serie tiene este tenant y cuáles faltan",
)
def estado_de_serie(db: DbDep, principal: AutenticadoDep) -> Any:
    return grc_serie.estado_de_serie(db, principal.tenant_id)


@router_grc_serie.post(
    "/de-serie",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Instalar o poner al día los controles de serie",
    description=(
        "Uno por familia del catálogo, anclado a sus capacidades hechas; uno por "
        "regla de segregación, con su riesgo; uno por requisito TCSEC, y el de la "
        "revisión periódica de accesos. **Se puede repetir**: trae los nuevos y "
        "no pisa los que la empresa ha ajustado o desactivado."
    ),
)
def instalar(uow: UowDep, principal: AutenticadoDep) -> Any:
    return grc_serie.instalar_de_serie(uow.db, principal.tenant_id, por=principal.id)


@router_grc_serie.post(
    "/controles/evaluar-automaticos",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Evaluar todos los controles que tienen fuente de evidencia",
    description=(
        "La evidencia y el resultado los pone el sistema. Lo que no se ha podido "
        "medir **no se evalúa** y sale con su motivo: una comprobación que no "
        "mira parece verde."
    ),
)
def evaluar_automaticos(
    uow: UowDep,
    principal: AutenticadoDep,
    origen: str = Query("", description="familia, segregacion, tcsec o recertificacion"),
) -> Any:
    return grc_serie.evaluar_automaticos(
        uow.db, principal.tenant_id, por=principal.id, origen=origen
    )


@router_grc_serie.post(
    "/controles/{codigo}/evaluar-automatico",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Evaluar un control con su fuente de evidencia",
)
def evaluar_automatico(codigo: str, uow: UowDep, principal: AutenticadoDep) -> Any:
    return grc_serie.evaluar_automatico(uow.db, principal.tenant_id, codigo, por=principal.id)


@router_grc_serie.post(
    "/controles/{codigo}/activo",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Activar o desactivar un control",
    description=(
        "Un control de serie desactivado queda **ajustado**: reinstalar los de "
        "serie ya no lo vuelve a encender."
    ),
)
def activar(codigo: str, datos: ActivoIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = _buscar(uow.db, principal.tenant_id, codigo)
    fila.activo = datos.activo
    if fila.origen:
        fila.ajustado = True
    uow.db.flush()
    return _control(fila)


@router_grc_serie.get(
    "/controles/{codigo}",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Un control con sus evaluaciones, hallazgos y evidencias",
    description=(
        "Del control a todo lo que lo sostiene: las últimas evaluaciones con su "
        "evidencia, los hallazgos abiertos y cerrados, y las evidencias con su "
        "caducidad. El `origen` y la `referencia` dicen a qué regla, requisito o "
        "familia está enlazado."
    ),
)
def detalle(codigo: str, db: DbDep, principal: AutenticadoDep) -> Any:
    fila = _buscar(db, principal.tenant_id, codigo)
    evaluaciones = (
        db.execute(
            select(grc.EvaluacionControl)
            .where(
                grc.EvaluacionControl.tenant_id == principal.tenant_id,
                grc.EvaluacionControl.control_codigo == codigo,
            )
            .order_by(grc.EvaluacionControl.created_at.desc())
            .limit(10)
        )
        .scalars()
        .all()
    )
    return {
        **_control(fila),
        "evaluaciones": [
            {
                "fecha": e.fecha.isoformat(),
                "resultado": e.resultado,
                "evidencia": e.evidencia,
                "plan_accion": e.plan_accion,
                "observaciones": e.observaciones,
                "proxima_at": e.proxima_at.isoformat() if e.proxima_at else None,
            }
            for e in evaluaciones
        ],
        "hallazgos": _hallazgos(db, principal.tenant_id, control=codigo, estado=""),
        "evidencias": _evidencias(db, principal.tenant_id, control=codigo),
    }


@router_grc_serie.post(
    "/segregacion/sincronizar",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Llevar la segregación de funciones al GRC",
    description=(
        "Cada regla, un control preventivo con su riesgo; cada conflicto sin "
        "excepción, un hallazgo abierto; cada excepción aprobada, una evidencia "
        "que caduca con ella. Se pregunta a identidad por HTTP y se puede repetir."
    ),
)
def sincronizar(uow: UowDep, principal: AutenticadoDep) -> Any:
    return grc_serie.sincronizar_segregacion(uow.db, principal.tenant_id, principal.id)


@router_grc_serie.get(
    "/hallazgos",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Lo que los controles han encontrado mal",
)
def hallazgos(
    db: DbDep,
    principal: AutenticadoDep,
    estado: str = Query("abierto", description="abierto, cerrado o vacío para todos"),
    control: str = Query("", max_length=40),
) -> Any:
    return _hallazgos(db, principal.tenant_id, control=control, estado=estado)


@router_grc_serie.get(
    "/evidencias",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Las evidencias con caducidad que sostienen los controles",
)
def evidencias(
    db: DbDep,
    principal: AutenticadoDep,
    control: str = Query("", max_length=40),
) -> Any:
    return _evidencias(db, principal.tenant_id, control=control)


def _buscar(db: Any, tenant_id: Any, codigo: str) -> grc.Control:
    fila = db.execute(
        select(grc.Control).where(grc.Control.tenant_id == tenant_id, grc.Control.codigo == codigo)
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("Ese control no existe", error_code="grc.control_no_existe")
    return fila


def _hallazgos(db: Any, tenant_id: Any, *, control: str, estado: str) -> list[dict[str, Any]]:
    consulta = select(grc.Hallazgo).where(grc.Hallazgo.tenant_id == tenant_id)
    if control:
        consulta = consulta.where(grc.Hallazgo.control_codigo == control)
    if estado:
        consulta = consulta.where(grc.Hallazgo.estado == estado)
    return [
        {
            "codigo": h.codigo,
            "control": h.control_codigo,
            "origen": h.origen,
            "referencia": h.referencia,
            "sujeto_id": str(h.sujeto_id) if h.sujeto_id else None,
            "titulo": h.titulo,
            "detalle": h.detalle,
            "riesgo": h.riesgo_codigo,
            "estado": h.estado,
            "motivo_cierre": h.motivo_cierre,
            "detectado_at": h.detectado_at.isoformat(),
            "cerrado_at": h.cerrado_at.isoformat() if h.cerrado_at else None,
        }
        for h in db.execute(consulta.order_by(grc.Hallazgo.detectado_at.desc())).scalars()
    ]


def _evidencias(db: Any, tenant_id: Any, *, control: str) -> list[dict[str, Any]]:
    dia = hoy(db)
    consulta = select(grc.Evidencia).where(grc.Evidencia.tenant_id == tenant_id)
    if control:
        consulta = consulta.where(grc.Evidencia.control_codigo == control)
    return [
        {
            "control": e.control_codigo,
            "origen": e.origen,
            "referencia": e.referencia,
            "descripcion": e.descripcion,
            "datos": e.datos,
            "caduca_at": e.caduca_at.isoformat() if e.caduca_at else None,
            # Pasada la fecha ya no prueba nada, y se dice en vez de esconderla.
            "vigente": e.caduca_at is None or e.caduca_at >= dia,
        }
        for e in db.execute(consulta.order_by(grc.Evidencia.caduca_at.desc())).scalars()
    ]


ROUTERS_GRC_SERIE = [router_grc_serie]
