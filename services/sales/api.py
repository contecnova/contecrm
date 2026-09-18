"""API HTTP del servicio de ventas."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.errors import Conflicto, NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.pagination import ParametrosPagina, aplicar_orden_y_cursor, construir_pagina
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select

from services.sales import servicio as svc
from services.sales.esquemas import (
    ActualizarOportunidad,
    CambiarEtapa,
    CambioEtapaOut,
    CompetidorEntrada,
    ConvertirLead,
    CrearEtapa,
    CrearLead,
    CrearLinea,
    CrearOportunidad,
    CrearPipeline,
    DescartarLead,
    EtapaOut,
    LeadOut,
    LineaOut,
    OportunidadOut,
    PipelineOut,
    Reabrir,
)
from services.sales.modelos import (
    CambioEtapa,
    CompetidorEnOportunidad,
    Etapa,
    Lead,
    LineaOportunidad,
    Oportunidad,
    Pipeline,
)

# ── Leads ─────────────────────────────────────────────────────────────────

router_leads = APIRouter(prefix="/leads", tags=["leads"])


@router_leads.post(
    "",
    response_model=LeadOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("lead:write"))],
    summary="Capturar un lead",
    description=(
        "El reloj del SLA de primera respuesta empieza **al entrar**, no al "
        "asignarlo: quien rellenó el formulario espera desde que lo envió."
    ),
)
def crear_lead(datos: CrearLead, uow: UowDep) -> Any:
    return svc.crear_lead(uow, **datos.model_dump())


@router_leads.get(
    "",
    response_model=dict,
    dependencies=[Depends(exige_permiso("lead:read"))],
    summary="Listar leads",
)
def listar_leads(
    db: DbDep,
    principal: AutenticadoDep,
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
    estado: str = Query(""),
    mios: bool = Query(False),
    sla_en_riesgo: bool = Query(False, description="Sin responder y con el SLA vencido o cerca"),
) -> Any:
    from datetime import datetime, timezone

    params = ParametrosPagina.desde_query(limite=limite, cursor=cursor, orden="-created_at")
    consulta = select(Lead).where(Lead.deleted_at.is_(None))
    if estado:
        consulta = consulta.where(Lead.estado == estado)
    if mios:
        consulta = consulta.where(Lead.owner_id == principal.id)
    if sla_en_riesgo:
        consulta = consulta.where(
            Lead.primera_respuesta_at.is_(None),
            Lead.sla_primera_respuesta_at < datetime.now(timezone.utc),
            Lead.estado.notin_(("convertido", "descartado")),
        )
    consulta = aplicar_orden_y_cursor(
        consulta,
        Lead,
        params,
        columnas_permitidas={"created_at", "sla_primera_respuesta_at", "estado"},
    )
    filas = list(db.execute(consulta.limit(params.limite + 1)).scalars().all())
    pagina = construir_pagina(filas, params, campos_orden=["-created_at"])
    return pagina.a_dict(lambda lead: LeadOut.model_validate(lead).model_dump(mode="json"))


@router_leads.post(
    "/{lead_id}/primera-respuesta",
    response_model=LeadOut,
    dependencies=[Depends(exige_permiso("lead:write"))],
    summary="Anotar la primera respuesta",
    description=(
        "Idempotente: la primera es la que cuenta. Sobrescribirla con una "
        "posterior maquillaría el incumplimiento del SLA."
    ),
)
def primera_respuesta(lead_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return svc.registrar_primera_respuesta(db, lead_id, por=principal.id)


@router_leads.post(
    "/{lead_id}/descartar",
    response_model=LeadOut,
    dependencies=[Depends(exige_permiso("lead:write"))],
    summary="Descartar un lead",
    description="Con motivo normalizado y fecha de reciclaje: un «ahora no» no es un no para siempre.",
)
def descartar_lead(lead_id: UUID, datos: DescartarLead, uow: UowDep) -> Any:
    return svc.descartar_lead(uow, lead_id, motivo=datos.motivo, nota=datos.nota)


@router_leads.post(
    "/{lead_id}/convertir",
    response_model=dict,
    dependencies=[Depends(exige_permiso("lead:convert"))],
    summary="Convertir el lead en cuenta, contacto y oportunidad",
    description=(
        "El lead **se conserva** apuntando a lo que generó: es lo que permite "
        "responder a «¿de dónde salió este cliente?» y hace posible la atribución."
    ),
)
def convertir_lead(lead_id: UUID, datos: ConvertirLead, uow: UowDep) -> Any:
    lead, oportunidad = svc.convertir_lead(uow, lead_id, **datos.model_dump())
    return {
        "lead_id": str(lead.id),
        "cuenta_id": str(lead.cuenta_id),
        "contacto_id": str(lead.contacto_id) if lead.contacto_id else None,
        "oportunidad_id": str(oportunidad.id) if oportunidad else None,
    }


@router_leads.get(
    "/motivos-descarte",
    response_model=list[str],
    dependencies=[Depends(exige_permiso("lead:read"))],
    summary="Motivos de descarte admitidos",
)
def motivos_descarte() -> Any:
    return sorted(svc.MOTIVOS_DESCARTE)


# ── Pipelines ─────────────────────────────────────────────────────────────

router_pipelines = APIRouter(prefix="/pipelines", tags=["pipelines"])


@router_pipelines.post(
    "",
    response_model=PipelineOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("pipeline:write"))],
    summary="Crear un pipeline",
    description=(
        "Varios por tenant: la venta de proyecto no tiene las mismas etapas que "
        "la de mantenimiento."
    ),
)
def crear_pipeline(datos: CrearPipeline, db: DbDep, principal: AutenticadoDep) -> Any:
    if datos.por_defecto:
        # Solo puede haber uno por defecto y lo garantiza un índice único: hay
        # que bajar el anterior antes de subir este.
        for otro in (
            db.execute(
                select(Pipeline).where(
                    Pipeline.tenant_id == principal.tenant_id, Pipeline.por_defecto.is_(True)
                )
            )
            .scalars()
            .all()
        ):
            otro.por_defecto = False
        db.flush()

    pipeline = Pipeline(tenant_id=principal.tenant_id, **datos.model_dump())
    db.add(pipeline)
    db.flush()
    return PipelineOut(**{**pipeline.__dict__, "etapas": []})


@router_pipelines.get(
    "",
    response_model=list[PipelineOut],
    dependencies=[Depends(exige_permiso("pipeline:read"))],
    summary="Pipelines con sus etapas",
)
def listar_pipelines(db: DbDep, principal: AutenticadoDep) -> Any:
    pipelines = (
        db.execute(
            select(Pipeline)
            .where(Pipeline.tenant_id == principal.tenant_id)
            .order_by(Pipeline.por_defecto.desc(), Pipeline.nombre)
        )
        .scalars()
        .all()
    )
    salida = []
    for pipeline in pipelines:
        etapas = (
            db.execute(select(Etapa).where(Etapa.pipeline_id == pipeline.id).order_by(Etapa.orden))
            .scalars()
            .all()
        )
        salida.append(
            PipelineOut(
                id=pipeline.id,
                clave=pipeline.clave,
                nombre=pipeline.nombre,
                descripcion=pipeline.descripcion,
                ambito=pipeline.ambito,
                activo=pipeline.activo,
                por_defecto=pipeline.por_defecto,
                etapas=[EtapaOut.model_validate(e) for e in etapas],
            )
        )
    return salida


@router_pipelines.post(
    "/{pipeline_id}/etapas",
    response_model=EtapaOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("pipeline:write"))],
    summary="Añadir una etapa",
    description=(
        "Los **criterios de salida** son lo que distingue un pipeline útil de "
        "una lista de colores: obligan a que una oportunidad no avance sin la "
        "información que esa etapa exige."
    ),
)
def crear_etapa(pipeline_id: UUID, datos: CrearEtapa, db: DbDep, principal: AutenticadoDep) -> Any:
    pipeline = db.get(Pipeline, pipeline_id)
    if pipeline is None or pipeline.tenant_id != principal.tenant_id:
        raise NoEncontrado("El pipeline no existe", error_code="sales.pipeline_no_encontrado")
    etapa = Etapa(tenant_id=principal.tenant_id, pipeline_id=pipeline_id, **datos.model_dump())
    db.add(etapa)
    db.flush()
    return etapa


# ── Oportunidades ─────────────────────────────────────────────────────────

router_oportunidades = APIRouter(prefix="/opportunities", tags=["oportunidades"])


@router_oportunidades.post(
    "",
    response_model=OportunidadOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("opportunity:write"))],
    summary="Crear una oportunidad",
)
def crear_oportunidad(datos: CrearOportunidad, uow: UowDep) -> Any:
    return svc.crear_oportunidad_nueva(uow, **datos.model_dump())


@router_oportunidades.get(
    "",
    response_model=dict,
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Listar oportunidades",
)
def listar_oportunidades(
    db: DbDep,
    principal: AutenticadoDep,
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
    estado: str = Query("abierta"),
    cuenta_id: UUID | None = Query(None),
    mias: bool = Query(False),
) -> Any:
    params = ParametrosPagina.desde_query(limite=limite, cursor=cursor, orden="-created_at")
    consulta = select(Oportunidad).where(Oportunidad.deleted_at.is_(None))
    if estado:
        consulta = consulta.where(Oportunidad.estado == estado)
    if cuenta_id:
        consulta = consulta.where(Oportunidad.cuenta_id == cuenta_id)
    if mias:
        consulta = consulta.where(Oportunidad.owner_id == principal.id)
    consulta = aplicar_orden_y_cursor(
        consulta,
        Oportunidad,
        params,
        columnas_permitidas={"created_at", "fecha_cierre", "importe", "nombre"},
    )
    filas = list(db.execute(consulta.limit(params.limite + 1)).scalars().all())
    pagina = construir_pagina(filas, params, campos_orden=["-created_at"])
    return pagina.a_dict(
        lambda o: {
            **OportunidadOut.model_validate(
                {**o.__dict__, "importe_ponderado": o.importe_ponderado}
            ).model_dump(mode="json")
        }
    )


@router_oportunidades.get(
    "/{oportunidad_id}",
    response_model=OportunidadOut,
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Ficha de la oportunidad",
)
def obtener_oportunidad(oportunidad_id: UUID, db: DbDep) -> Any:
    oportunidad = svc._oportunidad(db, oportunidad_id)
    return OportunidadOut.model_validate(
        {**oportunidad.__dict__, "importe_ponderado": oportunidad.importe_ponderado}
    )


@router_oportunidades.patch(
    "/{oportunidad_id}",
    response_model=OportunidadOut,
    dependencies=[Depends(exige_permiso("opportunity:write"))],
    summary="Actualizar una oportunidad",
    description=(
        "Una oportunidad cerrada y bloqueada responde 409: sus números ya están "
        "en un informe que alguien ha mirado. Hay que reabrirla."
    ),
)
def actualizar_oportunidad(oportunidad_id: UUID, datos: ActualizarOportunidad, uow: UowDep) -> Any:
    oportunidad = svc.actualizar_oportunidad(
        uow, oportunidad_id, datos.model_dump(exclude_unset=True, exclude_none=True)
    )
    return OportunidadOut.model_validate(
        {**oportunidad.__dict__, "importe_ponderado": oportunidad.importe_ponderado}
    )


@router_oportunidades.post(
    "/{oportunidad_id}/etapa",
    response_model=OportunidadOut,
    dependencies=[Depends(exige_permiso("opportunity:write"))],
    summary="Mover la oportunidad de etapa",
    description=(
        "Comprueba los criterios de salida de la etapa de origen. Si la etapa "
        "destino es terminal, cierra la oportunidad y emite el evento "
        "correspondiente."
    ),
)
def cambiar_etapa(oportunidad_id: UUID, datos: CambiarEtapa, uow: UowDep) -> Any:
    oportunidad = svc.cambiar_etapa(
        uow,
        oportunidad_id,
        etapa_id=datos.etapa_id,
        motivo=datos.motivo,
        forzar=datos.forzar,
    )
    return OportunidadOut.model_validate(
        {**oportunidad.__dict__, "importe_ponderado": oportunidad.importe_ponderado}
    )


@router_oportunidades.post(
    "/{oportunidad_id}/reabrir",
    response_model=OportunidadOut,
    dependencies=[Depends(exige_permiso("opportunity:reopen"))],
    summary="Reabrir una oportunidad cerrada",
    description=(
        "Acto explícito, con motivo y auditado. Emite `opportunity.reopened` "
        "para que quien consumió el cierre —previsión, comisiones, pedidos— "
        "pueda deshacerlo."
    ),
)
def reabrir(oportunidad_id: UUID, datos: Reabrir, uow: UowDep) -> Any:
    oportunidad = svc.reabrir(uow, oportunidad_id, etapa_id=datos.etapa_id, motivo=datos.motivo)
    return OportunidadOut.model_validate(
        {**oportunidad.__dict__, "importe_ponderado": oportunidad.importe_ponderado}
    )


@router_oportunidades.get(
    "/{oportunidad_id}/historial-etapas",
    response_model=list[CambioEtapaOut],
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Paso por etapas, con importe y fecha en cada cambio",
    description=(
        "Guardar el importe y la fecha de cierre **en el momento del cambio** es "
        "lo que permite medir el deslizamiento, que es el dato que explica por "
        "qué el trimestre no salió como se dijo."
    ),
)
def historial_etapas(oportunidad_id: UUID, db: DbDep) -> Any:
    return list(
        db.execute(
            select(CambioEtapa)
            .where(CambioEtapa.oportunidad_id == oportunidad_id)
            .order_by(CambioEtapa.created_at)
        )
        .scalars()
        .all()
    )


# ── Líneas ────────────────────────────────────────────────────────────────


@router_oportunidades.post(
    "/{oportunidad_id}/lineas",
    response_model=LineaOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("opportunity:write"))],
    summary="Añadir una línea",
    description=(
        "La descripción y el precio se **copian** del producto, no solo se "
        "referencian: si mañana sube el precio de catálogo, esta oportunidad "
        "tiene que seguir diciendo lo que se ofreció."
    ),
)
def crear_linea(
    oportunidad_id: UUID, datos: CrearLinea, db: DbDep, principal: AutenticadoDep
) -> Any:
    oportunidad = svc._oportunidad(db, oportunidad_id)
    svc._exigir_editable(db, oportunidad)

    linea = LineaOportunidad(
        tenant_id=principal.tenant_id,
        oportunidad_id=oportunidad_id,
        total=svc.calcular_linea(datos.cantidad, datos.precio_unitario, datos.descuento_pct),
        **datos.model_dump(),
    )
    db.add(linea)
    db.flush()
    svc.recalcular_total(db, oportunidad)
    return linea


@router_oportunidades.get(
    "/{oportunidad_id}/lineas",
    response_model=list[LineaOut],
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Líneas de la oportunidad",
)
def listar_lineas(oportunidad_id: UUID, db: DbDep) -> Any:
    return list(
        db.execute(
            select(LineaOportunidad)
            .where(LineaOportunidad.oportunidad_id == oportunidad_id)
            .order_by(LineaOportunidad.orden)
        )
        .scalars()
        .all()
    )


@router_oportunidades.delete(
    "/{oportunidad_id}/lineas/{linea_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(exige_permiso("opportunity:write"))],
    summary="Quitar una línea",
)
def borrar_linea(oportunidad_id: UUID, linea_id: UUID, db: DbDep) -> None:
    oportunidad = svc._oportunidad(db, oportunidad_id)
    svc._exigir_editable(db, oportunidad)
    linea = db.get(LineaOportunidad, linea_id)
    if linea is None or linea.oportunidad_id != oportunidad_id:
        raise NoEncontrado("La línea no existe", error_code="sales.linea_no_encontrada")
    db.delete(linea)
    db.flush()
    svc.recalcular_total(db, oportunidad)


@router_oportunidades.post(
    "/{oportunidad_id}/competidores",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("opportunity:write"))],
    summary="Registrar un competidor en la operación",
    description=(
        "Con posicionamiento, no solo el nombre: saber que se perdió contra X "
        "**por precio** y no por producto es lo que cambia la estrategia."
    ),
)
def crear_competidor(
    oportunidad_id: UUID, datos: CompetidorEntrada, db: DbDep, principal: AutenticadoDep
) -> Any:
    oportunidad = svc._oportunidad(db, oportunidad_id)
    existente = db.execute(
        select(CompetidorEnOportunidad).where(
            CompetidorEnOportunidad.oportunidad_id == oportunidad_id,
            CompetidorEnOportunidad.nombre == datos.nombre,
        )
    ).scalar_one_or_none()
    if existente is not None:
        raise Conflicto(
            "Ese competidor ya está registrado en la oportunidad",
            error_code="sales.competidor_duplicado",
        )
    competidor = CompetidorEnOportunidad(
        tenant_id=principal.tenant_id, oportunidad_id=oportunidad_id, **datos.model_dump()
    )
    db.add(competidor)
    if datos.ganador:
        oportunidad.competidor_ganador = datos.nombre
    db.flush()
    return {"id": str(competidor.id), "nombre": competidor.nombre, "ganador": competidor.ganador}


# ── Pipeline agregado ─────────────────────────────────────────────────────

router_pipeline_vista = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router_pipeline_vista.get(
    "/resumen",
    response_model=dict,
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Importe por etapa, bruto y ponderado",
    description=(
        "El ponderado va **además** del bruto, no en su lugar: el bruto dice "
        "cuánto hay sobre la mesa y el ponderado cuánto se espera cerrar."
    ),
)
def resumen(db: DbDep, principal: AutenticadoDep, pipeline_id: UUID | None = Query(None)) -> Any:
    return svc.resumen_pipeline(db, principal.tenant_id, pipeline_id=pipeline_id)


@router_pipeline_vista.get(
    "/estancadas",
    response_model=list[dict],
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Oportunidades estancadas en su etapa",
    description=(
        "El umbral es por etapa: tres semanas en «negociación» puede ser normal "
        "y en «primer contacto» no lo es."
    ),
)
def estancadas(db: DbDep, principal: AutenticadoDep) -> Any:
    return svc.oportunidades_estancadas(db, principal.tenant_id)


@router_pipeline_vista.get(
    "/motivos-perdida",
    response_model=list[str],
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Motivos de pérdida admitidos",
)
def motivos_perdida() -> Any:
    return sorted(svc.MOTIVOS_PERDIDA)


ROUTERS = [router_leads, router_pipelines, router_oportunidades, router_pipeline_vista]
