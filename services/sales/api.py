"""API HTTP del servicio de ventas."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.http.adjuntos_router import crear_router_adjuntos
from crmcore.http.busqueda_router import crear_router_busqueda
from crmcore.http.comentarios_router import crear_router_comentarios
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.pagination import ParametrosPagina, aplicar_orden_y_cursor, construir_pagina
from crmcore.http.retencion_router import crear_router_retencion
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.sales import enrutamiento as enr
from services.sales import origen as org
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


# ── Reglas de enrutamiento de leads (CRM-01.01.03.04) ─────────────────────

router_enrutamiento = APIRouter(prefix="/lead-routing", tags=["enrutamiento de leads"])


class CondicionEntrada(BaseModel):
    atributo: str = Field(..., description="Ruta: lead.pais, lead.utm.source, lead.campos.sector")
    operador: str = Field(
        ..., description="=, !=, >, >=, <, <=, en, no_en, contiene, vacio, no_vacio"
    )
    valor: Any = None


class CrearRegla(BaseModel):
    nombre: str = Field(..., max_length=150)
    descripcion: str = ""
    prioridad: int = Field(100, ge=0, le=10_000)
    condiciones: list[CondicionEntrada]
    combinacion: str = Field("todas", pattern="^(todas|alguna)$")
    estrategia: str = Field("round_robin")
    candidatos: list[UUID] = Field(default_factory=list)
    cola: str | None = Field(None, max_length=80)
    activa: bool = True


class ReglaOut(BaseModel):
    id: UUID
    nombre: str
    descripcion: str
    prioridad: int
    activa: bool
    condiciones: list[Any]
    combinacion: str
    estrategia: str
    candidatos: list[Any]
    cola: str | None

    model_config = {"from_attributes": True}


@router_enrutamiento.get(
    "/estrategias",
    response_model=dict,
    summary="Estrategias de reparto disponibles",
)
def estrategias() -> Any:
    return enr.ESTRATEGIAS


@router_enrutamiento.get("/reglas", response_model=list[ReglaOut], summary="Listar reglas")
def listar_reglas(db: DbDep, _: AutenticadoDep) -> Any:
    return (
        db.execute(
            select(enr.ReglaEnrutamiento).order_by(
                enr.ReglaEnrutamiento.prioridad, enr.ReglaEnrutamiento.nombre
            )
        )
        .scalars()
        .all()
    )


@router_enrutamiento.post(
    "/reglas",
    response_model=ReglaOut,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una regla de enrutamiento",
    description=(
        "Valida la regla antes de guardarla: operadores, estrategia y que "
        "tenga a quién asignar. Una regla mal formada no se puede rechazar "
        "cuando entra el lead —allí no hay nadie delante—, así que se rechaza aquí."
    ),
    dependencies=[Depends(exige_permiso("lead:configurar"))],
)
def crear_regla(datos: CrearRegla, uow: UowDep) -> Any:
    bruto = datos.model_dump(mode="json")
    enr.validar_regla(bruto)
    fila = enr.ReglaEnrutamiento(tenant_id=uow.tenant_id, **bruto)
    uow.db.add(fila)
    uow.db.flush()
    return fila


@router_enrutamiento.patch(
    "/reglas/{regla_id}",
    response_model=ReglaOut,
    summary="Editar una regla",
    dependencies=[Depends(exige_permiso("lead:configurar"))],
)
def editar_regla(regla_id: UUID, datos: dict, uow: UowDep) -> Any:
    fila = uow.db.get(enr.ReglaEnrutamiento, regla_id)
    if fila is None:
        raise NoEncontrado("Regla no encontrada", error_code="sales.regla_no_existe")
    permitidos = {
        "nombre",
        "descripcion",
        "prioridad",
        "condiciones",
        "combinacion",
        "estrategia",
        "candidatos",
        "cola",
        "activa",
    }
    cambios = {k: v for k, v in datos.items() if k in permitidos}
    # Se valida la regla RESULTANTE, no el parche: cambiar solo la estrategia
    # puede dejarla sin destino, y validar el parche aislado no lo vería.
    resultante = {
        "estrategia": fila.estrategia,
        "combinacion": fila.combinacion,
        "condiciones": fila.condiciones,
        "candidatos": fila.candidatos,
        "cola": fila.cola,
        **cambios,
    }
    enr.validar_regla(resultante)
    for campo, valor in cambios.items():
        setattr(fila, campo, valor)
    return fila


@router_enrutamiento.get(
    "/leads/{lead_id}/explicacion",
    response_model=list[dict],
    summary="Por qué este lead cayó donde cayó",
    description=(
        "Devuelve las decisiones de reparto del lead con las reglas evaluadas "
        "y el motivo por el que cada una no encajó. Es la respuesta a «¿por qué "
        "no me llegó a mí?»."
    ),
)
def explicacion(lead_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return enr.explicar(db, lead_id, principal.tenant_id)


@router_enrutamiento.post(
    "/reglas/probar",
    response_model=dict,
    summary="Probar las reglas contra un lead de ejemplo, sin guardar nada",
    description=(
        "Simula el reparto sobre datos inventados y devuelve qué regla ganaría. "
        "No escribe: es para ajustar las reglas antes de que entren leads de "
        "verdad, que es cuando equivocarse cuesta caro."
    ),
    dependencies=[Depends(exige_permiso("lead:configurar"))],
)
def probar_reglas(ejemplo: dict, db: DbDep, principal: AutenticadoDep) -> Any:
    from types import SimpleNamespace
    from uuid import uuid4

    campos = {
        "id": uuid4(),
        "pais": None,
        "origen": None,
        "estado": "nuevo",
        "empresa": None,
        "email": None,
        "cargo": None,
        "campana_id": None,
        "utm": {},
        "campos": {},
        "owner_id": None,
        "asignado_at": None,
    }
    campos.update({k: v for k, v in ejemplo.items() if k in campos})
    falso = SimpleNamespace(**campos)

    # Se evalúa dentro de un savepoint que se deshace siempre: `enrutar` escribe
    # la traza y avanza el cursor del round-robin, y una prueba que mueve el
    # turno real haría que probar cambiara el reparto de los leads siguientes.
    punto = db.begin_nested()
    try:
        registro = enr.enrutar(db, falso, tenant_id=principal.tenant_id)
        salida = {
            "regla": registro.regla_nombre,
            "asignaria_a": str(registro.asignado_a) if registro.asignado_a else None,
            "cola": registro.cola,
            "estrategia": registro.estrategia,
            "evaluadas": registro.evaluadas,
        }
    finally:
        punto.rollback()
    return salida


router_adjuntos = crear_router_adjuntos({"lead", "oportunidad", "linea_oportunidad"})


# ── Trazabilidad de origen (CRM-01.01.03.06) ──────────────────────────────

router_origen = APIRouter(prefix="/origen", tags=["origen"])


class RegistrarToque(BaseModel):
    lead_id: UUID | None = None
    visitante_id: str | None = Field(
        None,
        max_length=80,
        description=(
            "Identificador propio del visitante (cookie de primera parte). Es el "
            "hilo que une lo que pasó antes de identificarse con lo que pasó "
            "después; sin él, el primer toque se pierde siempre."
        ),
    )
    canal: str = Field("web", max_length=40)
    ocurrio_at: datetime | None = None
    # Los `utm_*` y cualquier otro parámetro. Lo que no se reconoce no se tira:
    # se guarda como identificador de clic, sin lista de redes conocidas.
    parametros: dict[str, Any] = Field(
        default_factory=dict,
        examples=[
            {
                "utm_source": "google",
                "utm_medium": "cpc",
                "utm_campaign": "obra-2026",
                "gclid": "Cj0KC...",
                "landing": "https://ejemplo.es/precios",
            }
        ],
    )


@router_origen.post(
    "/toques",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="Anotar un toque",
    # Permiso propio y estrecho: quien anota toques suele ser el script del
    # sitio web o el sistema de campañas, no una persona. Con `lead:write` haría
    # falta darle a ese script permiso para escribir leads, que es muchísimo más
    # de lo que necesita.
    dependencies=[Depends(exige_permiso("toque:registrar"))],
    description=(
        "Un toque es una interacción atribuible: una visita, un clic, la "
        "apertura de un correo, una feria. Se anota con lead o con visitante "
        "anónimo; el anónimo se enlaza solo cuando esa persona se identifica."
    ),
)
def anotar_toque(datos: RegistrarToque, uow: UowDep, principal: AutenticadoDep) -> Any:
    if datos.lead_id is None and not datos.visitante_id:
        raise ErrorValidacion(
            "Un toque necesita un lead o un identificador de visitante",
            error_code="sales.toque_sin_sujeto",
        )
    toque = org.registrar_toque(
        uow.db,
        tenant_id=principal.tenant_id,
        lead_id=datos.lead_id,
        visitante_id=datos.visitante_id,
        ocurrio_at=datos.ocurrio_at,
        canal=datos.canal,
        **datos.parametros,
    )
    return {"id": str(toque.id), "lead_id": str(toque.lead_id) if toque.lead_id else None}


@router_origen.get(
    "/leads/{lead_id}/recorrido",
    response_model=dict,
    summary="El recorrido completo de un lead",
    description=(
        "En orden cronológico, porque se lee como una historia: «llegó por un "
        "anuncio, volvió por un correo, cerró buscando la marca». Se devuelven "
        "además el primer y el último toque por separado: el primero explica "
        "cómo llegó y el último qué lo cerró, y ninguno de los dos se puede "
        "reconstruir después."
    ),
)
def ver_recorrido(lead_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    lead = svc._lead(db, lead_id)
    toques = org.recorrido(db, tenant_id=principal.tenant_id, lead_id=lead_id)
    return {
        "lead_id": str(lead_id),
        "toques": toques,
        "primer_toque": lead.primer_toque or None,
        "ultimo_toque": lead.ultimo_toque or None,
        "total": len(toques),
    }


@router_origen.get(
    "/campanas",
    response_model=list[dict],
    summary="Leads por campaña, por primer y por último toque",
    description=(
        "Las **dos** cifras, a propósito. Con solo la del último toque, la "
        "búsqueda de marca se lleva todo el mérito y las campañas que "
        "descubrieron al cliente parecen no servir para nada. No es un modelo "
        "de atribución: no reparte el mérito, lo cuenta desde dos puntos de "
        "vista. Los modelos llegan con marketing."
    ),
)
def leads_por_campana(
    db: DbDep,
    principal: AutenticadoDep,
    dias: int = Query(90, ge=1, le=3650, description="Ventana hacia atrás, en días"),
) -> Any:
    desde = datetime.now(timezone.utc) - timedelta(days=dias)
    return org.por_campana(db, tenant_id=principal.tenant_id, desde=desde)


router_comentarios = crear_router_comentarios({"lead", "oportunidad"})


# Las clases de dato de este servicio se declaran al importar su módulo.
from services.sales import retencion as _retencion  # noqa: E402,F401

router_retencion = crear_router_retencion()


from services.sales.indexacion import OBJETOS as _OBJETOS_BUSCABLES  # noqa: E402

router_busqueda = crear_router_busqueda(_OBJETOS_BUSCABLES)


ROUTERS = [
    router_leads,
    router_pipelines,
    router_oportunidades,
    router_pipeline_vista,
    router_enrutamiento,
    router_adjuntos,
    router_origen,
    router_comentarios,
    router_retencion,
    router_busqueda,
]
