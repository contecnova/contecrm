"""API de GRC: riesgos, controles, evaluaciones y cobertura (CRM-07.03.02.*)."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.tenancy import grc

router_grc = APIRouter(prefix="/grc", tags=["GRC"])


class RiesgoEntrada(BaseModel):
    titulo: str = Field(max_length=300)
    descripcion: str = ""
    categoria: str = Field("", max_length=60)
    probabilidad: int = Field(3, ge=1, le=5)
    impacto: int = Field(3, ge=1, le=5)
    propietario_id: UUID | None = None
    tratamiento: str = "mitigar"
    estado: str = "abierto"
    residual_probabilidad: int | None = Field(None, ge=1, le=5)
    residual_impacto: int | None = Field(None, ge=1, le=5)
    revision_at: date | None = None


class MarcoEntrada(BaseModel):
    marco: str = Field(max_length=60, description="ISO 27001, SOC 2, ENS, GDPR…")
    referencia: str = Field(max_length=60, description="A.9.2.3, CC6.1, op.acc.4…")


class ControlEntrada(BaseModel):
    nombre: str = Field(max_length=300)
    descripcion: str = ""
    tipo: str = "preventivo"
    automatico: bool = False
    frecuencia: str = "trimestral"
    responsable_id: UUID | None = None
    activo: bool = True
    capacidades: list[str] = Field(
        default_factory=list,
        description="Identificadores del catálogo funcional que este control cubre",
    )
    riesgos: list[str] = Field(default_factory=list)
    marcos: list[MarcoEntrada] = Field(default_factory=list)
    fuente_evidencia: str = Field(
        "", max_length=60, description="`audit_trail`, `politicas_abac`, `certificados_destruccion`"
    )


class EvaluacionEntrada(BaseModel):
    resultado: str
    fecha: date | None = None
    observaciones: str = ""
    plan_accion: str = ""
    evidencia: dict[str, Any] | None = None


# ── Riesgos ───────────────────────────────────────────────────────────────


@router_grc.get(
    "/riesgos",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Registro de riesgos",
)
def listar_riesgos(db: DbDep, principal: AutenticadoDep) -> Any:
    filas = (
        db.execute(
            select(grc.Riesgo)
            .where(grc.Riesgo.tenant_id == principal.tenant_id)
            .order_by(grc.Riesgo.codigo)
        )
        .scalars()
        .all()
    )
    return [_riesgo(f) for f in filas]


@router_grc.put(
    "/riesgos/{codigo}",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Registrar o actualizar un riesgo",
    description=(
        "Aceptar un riesgo **exige declarar el residual**: aceptar sin decir "
        "cuánto queda no es una decisión, es archivarlo."
    ),
)
def guardar_riesgo(
    codigo: str, datos: RiesgoEntrada, uow: UowDep, principal: AutenticadoDep
) -> Any:
    return _riesgo(
        grc.guardar_riesgo(
            uow.db, tenant_id=principal.tenant_id, codigo=codigo, **datos.model_dump()
        )
    )


# ── Controles ─────────────────────────────────────────────────────────────


@router_grc.get(
    "/controles",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Catálogo de controles",
)
def listar_controles(db: DbDep, principal: AutenticadoDep) -> Any:
    filas = (
        db.execute(
            select(grc.Control)
            .where(grc.Control.tenant_id == principal.tenant_id)
            .order_by(grc.Control.codigo)
        )
        .scalars()
        .all()
    )
    return [_control(f) for f in filas]


@router_grc.put(
    "/controles/{codigo}",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Crear o actualizar un control",
    description=(
        "Las capacidades se comprueban contra el catálogo funcional: un control "
        "sobre una capacidad que no existe no se guarda, porque contaría en el "
        "informe de cobertura sin cubrir nada."
    ),
)
def guardar_control(
    codigo: str, datos: ControlEntrada, uow: UowDep, principal: AutenticadoDep
) -> Any:
    cuerpo = datos.model_dump()
    cuerpo["marcos"] = [m.model_dump() for m in datos.marcos]
    return _control(
        grc.guardar_control(uow.db, tenant_id=principal.tenant_id, codigo=codigo, **cuerpo)
    )


@router_grc.post(
    "/controles/{codigo}/evaluaciones",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Evaluar un control",
    description=(
        "Un resultado distinto de «efectivo» exige plan de acción, y la fecha "
        "de la próxima evaluación se calcula de la frecuencia del control: una "
        "fecha escrita a mano es la primera que se queda sin poner."
    ),
)
def evaluar_control(
    codigo: str, datos: EvaluacionEntrada, uow: UowDep, principal: AutenticadoDep
) -> Any:
    fila = grc.evaluar_control(
        uow.db,
        tenant_id=principal.tenant_id,
        control_codigo=codigo,
        por=principal.id,
        **datos.model_dump(),
    )
    return {
        "control": fila.control_codigo,
        "fecha": fila.fecha.isoformat(),
        "resultado": fila.resultado,
        "evidencia": fila.evidencia,
        "proxima_at": fila.proxima_at.isoformat() if fila.proxima_at else None,
    }


# ── Informes ──────────────────────────────────────────────────────────────


@router_grc.get(
    "/cobertura",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Qué del producto tiene control y qué no",
    description=(
        "Medido sobre el catálogo funcional, en los dos sentidos: las "
        "capacidades sin control, y **los controles que apuntan a capacidades "
        "que ya no existen** — que es como se detecta un control que lleva un "
        "año cubriendo algo que se quitó del producto."
    ),
)
def cobertura(
    db: DbDep,
    principal: AutenticadoDep,
    solo_hechas: bool = Query(
        False, description="Medir solo sobre lo entregado, que es lo comprobable hoy"
    ),
) -> Any:
    return grc.cobertura(db, principal.tenant_id, solo_hechas=solo_hechas)


@router_grc.get(
    "/marcos",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Del marco normativo a las capacidades que lo sostienen",
    description=(
        "Un auditor pregunta por ISO 27001 A.9 y esto contesta qué controles "
        "responden, qué capacidades del producto los sostienen y cuándo se "
        "evaluaron por última vez."
    ),
)
def marcos(db: DbDep, principal: AutenticadoDep) -> Any:
    return grc.por_marco(db, principal.tenant_id)


@router_grc.get(
    "/capacidades/{capacidad_id}",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="A qué obligaciones responde una capacidad",
    description=(
        "El recorrido de vuelta: antes de tocar una capacidad se puede ver a "
        "qué obligaciones normativas está respondiendo."
    ),
)
def obligaciones(capacidad_id: str, db: DbDep, principal: AutenticadoDep) -> Any:
    return grc.obligaciones_de(db, principal.tenant_id, capacidad_id)


@router_grc.get(
    "/pendiente",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Lo que no cuadra hoy",
    description=(
        "Controles nunca evaluados, fuera de plazo o no efectivos, y riesgos "
        "que se decidió mitigar y no tienen ningún control. Un GRC sin esta "
        "vista es un archivo."
    ),
)
def pendiente(db: DbDep, principal: AutenticadoDep) -> Any:
    return grc.vencidos(db, principal.tenant_id)


def _riesgo(fila: Any) -> dict[str, Any]:
    return {
        "codigo": fila.codigo,
        "titulo": fila.titulo,
        "descripcion": fila.descripcion,
        "categoria": fila.categoria,
        "probabilidad": fila.probabilidad,
        "impacto": fila.impacto,
        "inherente": fila.inherente,
        "residual": fila.residual,
        "tratamiento": fila.tratamiento,
        "estado": fila.estado,
        "propietario_id": str(fila.propietario_id) if fila.propietario_id else None,
        "revision_at": fila.revision_at.isoformat() if fila.revision_at else None,
    }


def _control(fila: Any) -> dict[str, Any]:
    from crmcore.catalogo import descripcion

    return {
        "codigo": fila.codigo,
        "nombre": fila.nombre,
        "descripcion": fila.descripcion,
        "tipo": fila.tipo,
        "automatico": fila.automatico,
        "frecuencia": fila.frecuencia,
        "activo": fila.activo,
        # Se devuelve el título de cada capacidad además del identificador: una
        # lista de códigos no la lee nadie, y quien revisa un control necesita
        # saber qué está cubriendo sin abrir otra pestaña.
        "capacidades": [{"id": c, "titulo": descripcion(c)} for c in (fila.capacidades or [])],
        "riesgos": list(fila.riesgos or []),
        "marcos": list(fila.marcos or []),
        "fuente_evidencia": fila.fuente_evidencia,
    }


ROUTERS_GRC = [router_grc]


@router_grc.get(
    "/anomalias",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Exportaciones que se han salido del patrón",
    description=(
        "Lo que ha disparado el control de fuga de datos: quién, cuándo, cuánto "
        "y por qué (CRM-00.05.03.08).\n\n"
        "Sale del audit trail y no de una tabla de alertas aparte. Una tabla "
        "aparte es un segundo registro de lo mismo que puede discrepar del "
        "primero, y el primero es el que tiene la cadena de hashes."
    ),
)
def anomalias(
    db: DbDep,
    principal: AutenticadoDep,
    dias: int = Query(7, ge=1, le=365, description="Ventana que se mira"),
) -> Any:
    from crmcore.seguridad.dlp import anomalias as leer_anomalias

    return leer_anomalias(db, principal.tenant_id, dias=dias)


@router_grc.get(
    "/auditoria",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Consultar el audit trail (CRM-00.05.04.05)",
    description=(
        "Filtrable por acción, objeto, actor y fechas. Desde la propia "
        "plataforma y no exportando a otro sitio: «¿quién tocó esta cuenta?» se "
        "pregunta mientras se mira la cuenta, y obligar a salir a otra "
        "herramienta significa que casi nunca se responde."
    ),
)
def auditoria(
    db: DbDep,
    principal: AutenticadoDep,
    accion: str = Query("", max_length=80),
    objeto: str = Query("", max_length=80),
    limite: int = Query(100, ge=1, le=1000),
) -> Any:
    from crmcore.seguridad.siem import consultar

    return consultar(db, principal.tenant_id, accion=accion, objeto=objeto, limite=limite)
