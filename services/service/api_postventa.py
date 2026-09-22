"""API de postventa y de problemas (CRM-04.05.01 y CRM-04.01.01.11)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.service import postventa as pv
from services.service import problemas as prb

router = APIRouter(prefix="/devoluciones", tags=["postventa"])
router_exp = APIRouter(prefix="/expedientes", tags=["postventa"])
router_prb = APIRouter(prefix="/problemas", tags=["problemas"])


class Solicitar(BaseModel):
    motivo: str = Field(..., min_length=1, max_length=80, description="Normalizado, no texto libre")
    cuenta_id: UUID | None = None
    contacto_id: UUID | None = None
    caso_id: UUID | None = None
    pedido_id: UUID | None = None
    activo_id: UUID | None = None
    comprado_el: date | None = None
    descripcion: str = ""
    lineas: list[dict[str, Any]] = Field(default_factory=list)


class Autorizar(BaseModel):
    forzar: bool = False
    motivo_excepcion: str = ""


class Recibir(BaseModel):
    recibido: list[dict[str, Any]] = Field(
        default_factory=list, description="{linea_id, cantidad, estado_material}"
    )


class Inspeccionar(BaseModel):
    inspeccion: str = ""
    disposiciones: dict[str, str] = Field(
        default_factory=dict, description="{linea_id: reacondicionar|reparar|chatarra|proveedor}"
    )


class Resolver(BaseModel):
    tipo: str = Field(..., description="reparacion · sustitucion · abono · sin_accion")
    a_cargo_de: str = "cliente"
    importe: Decimal | None = None
    linea_id: UUID | None = None
    orden_trabajo_id: UUID | None = None
    activo_sustituto_id: UUID | None = None
    nota: str = ""


class ConfirmarAbono(BaseModel):
    confirmado: bool
    referencia: str = ""
    motivo: str = ""


class AbrirExpediente(BaseModel):
    asunto: str = Field(..., min_length=1, max_length=300)
    entrada_at: datetime = Field(..., description="Cuándo entró de verdad, no cuándo se graba")
    plazo_dias: int | None = None
    plazo_habiles: bool = False
    tipo: str = "reclamacion"
    via: str = ""
    organismo: str = ""
    referencia_externa: str = ""
    descripcion: str = ""
    cuenta_id: UUID | None = None
    contacto_id: UUID | None = None
    caso_id: UUID | None = None
    devolucion_id: UUID | None = None
    calendario: str = ""


class Responder(BaseModel):
    respuesta: str = Field(..., min_length=1)
    resultado: str = ""
    documento_id: UUID | None = None


class AbrirProblema(BaseModel):
    titulo: str = Field(..., min_length=1, max_length=300)
    descripcion: str = ""
    severidad: str = "media"
    categoria_id: UUID | None = None
    producto_id: UUID | None = None
    responsable_id: UUID | None = None
    caso_maestro_id: UUID | None = None
    casos: list[UUID] = Field(default_factory=list)


class Causa(BaseModel):
    causa_raiz: str = ""
    solucion_temporal: str = ""
    solucion_definitiva: str = ""
    error_conocido: bool | None = None
    articulo_id: UUID | None = None


class ResolverProblema(BaseModel):
    solucion_definitiva: str = Field(..., min_length=1)
    cerrar_casos: bool = False
    motivo_cierre: str = ""


class Comunicar(BaseModel):
    mensaje: str = Field(..., min_length=1)
    tipo: str = "actualizacion"


# ── Devoluciones ──────────────────────────────────────────────────────────


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Solicitar una devolución",
    description="Registra la petición. **Todavía no autoriza nada** ni da número de RMA.",
)
def solicitar(datos: Solicitar, uow: UowDep) -> Any:
    fila, avisos = pv.solicitar(uow, **datos.model_dump())
    return {"id": str(fila.id), "codigo": fila.codigo, "estado": fila.estado, "avisos": avisos}


@router.get(
    "",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Devoluciones",
)
def listar(
    db: DbDep,
    principal: AutenticadoDep,
    estado: str | None = Query(None),
    limite: int = Query(50, ge=1, le=200),
) -> Any:
    consulta = select(pv.Devolucion).where(pv.Devolucion.tenant_id == principal.tenant_id)
    if estado:
        consulta = consulta.where(pv.Devolucion.estado == estado)
    filas = (
        db.execute(consulta.order_by(pv.Devolucion.created_at.desc()).limit(limite)).scalars().all()
    )
    return {
        "devoluciones": [
            {
                "id": str(f.id),
                "codigo": f.codigo,
                "estado": f.estado,
                "motivo": f.motivo,
                "fuera_de_plazo": f.fuera_de_plazo,
                "disposicion": f.disposicion,
            }
            for f in filas
        ]
    }


@router.get(
    "/{devolucion_id}",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Una devolución con sus líneas y resoluciones",
)
def detalle(devolucion_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return pv.resumen_devolucion(db, principal.tenant_id, devolucion_id)


@router.post(
    "/{devolucion_id}/autorizar",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Autorizar y dar número de RMA",
    description=(
        "Fuera de la ventana se puede autorizar con motivo, y queda marcado como "
        "excepción: es una decisión comercial legítima, pero si pasa en silencio "
        "nadie puede medir cuánto se está regalando."
    ),
)
def autorizar(devolucion_id: UUID, datos: Autorizar, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila, ventana = pv.autorizar(uow, devolucion_id, por=principal.id, **datos.model_dump())
    return {"id": str(fila.id), "codigo": fila.codigo, "estado": fila.estado, "ventana": ventana}


@router.post(
    "/{devolucion_id}/rechazar",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Rechazar con motivo",
)
def rechazar(devolucion_id: UUID, uow: UowDep, motivo: str = Query(..., min_length=1)) -> Any:
    fila = pv.rechazar(uow, devolucion_id, motivo=motivo)
    return {"id": str(fila.id), "estado": fila.estado}


@router.post(
    "/{devolucion_id}/recibir",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Anotar lo que ha llegado",
    description=(
        "Devuelve las **diferencias** entre lo autorizado y lo recibido: es el dato "
        "que se pierde siempre y reaparece como un descuadre de inventario."
    ),
)
def recibir(devolucion_id: UUID, datos: Recibir, uow: UowDep) -> Any:
    fila, informe = pv.recibir(uow, devolucion_id, recibido=datos.recibido)
    return {"id": str(fila.id), "estado": fila.estado, **informe}


@router.post(
    "/{devolucion_id}/inspeccionar",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Anotar la inspección y la disposición por línea",
)
def inspeccionar(devolucion_id: UUID, datos: Inspeccionar, uow: UowDep) -> Any:
    fila = pv.inspeccionar(uow, devolucion_id, **datos.model_dump())
    return {"id": str(fila.id), "estado": fila.estado}


@router.post(
    "/{devolucion_id}/resolver",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Reparar, sustituir o abonar",
    description=(
        "El abono queda en **`solicitado`**: lo confirma quien factura. Darlo por "
        "hecho dejaría al cliente esperando un dinero que nadie ha emitido."
    ),
)
def resolver(devolucion_id: UUID, datos: Resolver, uow: UowDep) -> Any:
    fila, avisos = pv.resolver(uow, devolucion_id, **datos.model_dump())
    return {
        "id": str(fila.id),
        "tipo": fila.tipo,
        "estado_abono": fila.estado_abono,
        "avisos": avisos,
    }


@router.post(
    "/resoluciones/{resolucion_id}/abono",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Anotar lo que contestó quien factura",
)
def confirmar_abono(resolucion_id: UUID, datos: ConfirmarAbono, uow: UowDep) -> Any:
    fila = pv.confirmar_abono(uow, resolucion_id, **datos.model_dump())
    return {"id": str(fila.id), "estado_abono": fila.estado_abono}


@router.post(
    "/{devolucion_id}/cerrar",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Cerrar con disposición del material",
    description=(
        "**Exige disposición.** Una devolución cerrada sin ella es una pieza que "
        "consta devuelta y que nadie ha vuelto a ver."
    ),
)
def cerrar(
    devolucion_id: UUID,
    uow: UowDep,
    disposicion: str = Query(..., description="reacondicionar · reparar · chatarra · proveedor"),
) -> Any:
    fila = pv.cerrar(uow, devolucion_id, disposicion=disposicion)
    return {"id": str(fila.id), "estado": fila.estado, "disposicion": fila.disposicion}


# ── Expedientes ───────────────────────────────────────────────────────────


@router_exp.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Abrir un expediente de reclamación",
    description=(
        "El plazo cuenta desde que **entró** la reclamación, no desde que se grabó: "
        "esa diferencia es el tiempo que estuvo en un cajón, y se la come la "
        "empresa, no el cliente."
    ),
)
def abrir_expediente(datos: AbrirExpediente, uow: UowDep) -> Any:
    fila, avisos = pv.abrir_expediente(uow, **datos.model_dump())
    return {
        "id": str(fila.id),
        "codigo": fila.codigo,
        "vence_at": fila.vence_at.isoformat(),
        "avisos": avisos,
    }


@router_exp.get(
    "",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Expedientes",
)
def listar_expedientes(
    db: DbDep,
    principal: AutenticadoDep,
    estado: str | None = Query(None),
    limite: int = Query(50, ge=1, le=200),
) -> Any:
    consulta = select(pv.Expediente).where(pv.Expediente.tenant_id == principal.tenant_id)
    if estado:
        consulta = consulta.where(pv.Expediente.estado == estado)
    filas = db.execute(consulta.order_by(pv.Expediente.vence_at).limit(limite)).scalars().all()
    return {
        "expedientes": [
            {
                "id": str(f.id),
                "codigo": f.codigo,
                "asunto": f.asunto,
                "estado": f.estado,
                "via": f.via,
                "vence_at": f.vence_at.isoformat(),
                "plazo_habiles": f.plazo_habiles,
                "sin_acuse": f.acuse_at is None,
            }
            for f in filas
        ]
    }


@router_exp.get(
    "/vencen",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Los que vencen pronto y los ya vencidos",
    description=(
        "Van en dos listas: mezclarlos hace leer el incumplimiento como cola de "
        "trabajo, y ya no se puede evitar, solo explicar."
    ),
)
def vencen(db: DbDep, principal: AutenticadoDep, horas: int = Query(48, ge=1, le=2400)) -> Any:
    return pv.vencen_pronto(db, principal.tenant_id, horas=horas)


@router_exp.post(
    "/{expediente_id}/acuse",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Dejar constancia del acuse de recibo",
)
def acusar(expediente_id: UUID, uow: UowDep, documento_id: UUID | None = Query(None)) -> Any:
    fila = pv.acusar_recibo(uow, expediente_id, documento_id=documento_id)
    return {"id": str(fila.id), "acuse_at": fila.acuse_at.isoformat() if fila.acuse_at else None}


@router_exp.post(
    "/{expediente_id}/suspender",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Parar el reloj legal",
    description=(
        "Solo por motivo tipificado: con texto libre, el plazo se suspendería por "
        "«mucho trabajo» y dejaría de ser un plazo."
    ),
)
def suspender(expediente_id: UUID, uow: UowDep, motivo: str = Query(...)) -> Any:
    fila = pv.suspender(uow, expediente_id, motivo=motivo)
    return {"id": str(fila.id), "estado": fila.estado, "motivo": fila.motivo_suspension}


@router_exp.post(
    "/{expediente_id}/reanudar",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Reanudar y desplazar el vencimiento",
)
def reanudar(expediente_id: UUID, uow: UowDep) -> Any:
    fila = pv.reanudar(uow, expediente_id)
    return {"id": str(fila.id), "estado": fila.estado, "vence_at": fila.vence_at.isoformat()}


@router_exp.post(
    "/{expediente_id}/responder",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Cerrar con la respuesta dada",
    description=(
        "Dice si se llegó a tiempo, **y si se puede demostrar**: sin acuse de "
        "recibo, «en plazo» es nuestra palabra contra la suya."
    ),
)
def responder(expediente_id: UUID, datos: Responder, uow: UowDep) -> Any:
    return pv.responder(uow, expediente_id, **datos.model_dump())


# ── Problemas ─────────────────────────────────────────────────────────────


@router_prb.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Abrir un problema",
)
def abrir_problema(datos: AbrirProblema, uow: UowDep) -> Any:
    fila = prb.abrir(uow, **datos.model_dump())
    return {"id": str(fila.id), "codigo": fila.codigo, "estado": fila.estado}


@router_prb.get(
    "",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Problemas",
)
def listar_problemas(db: DbDep, principal: AutenticadoDep, estado: str | None = Query(None)) -> Any:
    consulta = select(prb.Problema).where(prb.Problema.tenant_id == principal.tenant_id)
    if estado:
        consulta = consulta.where(prb.Problema.estado == estado)
    filas = db.execute(consulta.order_by(prb.Problema.detectado_at.desc())).scalars().all()
    return {
        "problemas": [
            {
                "id": str(f.id),
                "codigo": f.codigo,
                "titulo": f.titulo,
                "estado": f.estado,
                "severidad": f.severidad,
                "error_conocido": f.error_conocido,
                "solo_apano": bool(f.solucion_temporal and not f.solucion_definitiva),
            }
            for f in filas
        ]
    }


@router_prb.get(
    "/correlacion",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Grupos de casos que parecen la misma causa",
    description=(
        "**Propone, no agrupa.** Agrupar solo cien casos que no eran lo mismo da a "
        "cien clientes una respuesta que no tiene que ver con su problema."
    ),
)
def correlacion(
    db: DbDep,
    principal: AutenticadoDep,
    ventana_horas: int = Query(4, ge=1, le=168),
    minimo: int = Query(3, ge=2, le=100),
) -> Any:
    return prb.correlacionar(db, principal.tenant_id, ventana_horas=ventana_horas, minimo=minimo)


@router_prb.get(
    "/{problema_id}/impacto",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="A cuánta gente le ha pasado",
)
def impacto(problema_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return prb.impacto(db, principal.tenant_id, problema_id)


@router_prb.post(
    "/{problema_id}/casos/{caso_id}",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Atribuir un caso al problema",
)
def vincular(problema_id: UUID, caso_id: UUID, uow: UowDep) -> Any:
    fila = prb.vincular(uow, problema_id, caso_id=caso_id)
    return {"id": str(fila.id)}


@router_prb.delete(
    "/{problema_id}/casos/{caso_id}",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Quitar un caso del problema, con motivo",
)
def desvincular(
    problema_id: UUID, caso_id: UUID, uow: UowDep, motivo: str = Query(..., min_length=1)
) -> Any:
    fila = prb.desvincular(uow, problema_id, caso_id=caso_id, motivo=motivo)
    return {"id": str(fila.id), "desvinculado": True}


@router_prb.post(
    "/{problema_id}/causa",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Anotar causa, apaño y solución",
    description="El apaño va separado de la solución: fundirlos cierra problemas sin resolver.",
)
def causa(problema_id: UUID, datos: Causa, uow: UowDep) -> Any:
    fila = prb.registrar_causa(uow, problema_id, **datos.model_dump())
    return {"id": str(fila.id), "estado": fila.estado, "error_conocido": fila.error_conocido}


@router_prb.post(
    "/{problema_id}/resolver",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Dar el problema por resuelto",
    description=(
        "Exige solución definitiva. Cerrarlo con «reiniciamos el servicio» lo hace "
        "desaparecer de la lista y volver dentro de tres semanas con otro nombre."
    ),
)
def resolver_problema(problema_id: UUID, datos: ResolverProblema, uow: UowDep) -> Any:
    return prb.resolver(uow, problema_id, **datos.model_dump())


@router_prb.post(
    "/{problema_id}/comunicaciones",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Registrar lo comunicado a los afectados",
)
def comunicar(problema_id: UUID, datos: Comunicar, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = prb.comunicar(uow, problema_id, por=principal.id, **datos.model_dump())
    return {"id": str(fila.id), "casos_alcanzados": fila.casos_alcanzados}


ROUTERS_POSTVENTA = [router, router_exp, router_prb]
