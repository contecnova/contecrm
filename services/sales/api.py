"""API HTTP del servicio de ventas."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore import vocabulario
from crmcore.authz.proyeccion import exigir_campo_usable
from crmcore.authz.visibilidad import aplicar_visibilidad
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.http.adjuntos_router import crear_router_adjuntos
from crmcore.http.busqueda_router import crear_router_busqueda
from crmcore.http.comentarios_router import crear_router_comentarios
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.documental_router import crear_router_documental
from crmcore.http.listados import aplicar_filtros_de_la_url
from crmcore.http.pagination import (
    CONTAR_TOTAL_DESCRIPCION,
    PaginaDeListado,
    ParametrosPagina,
    aplicar_orden_y_cursor,
    construir_pagina,
    contar_consulta,
    paginar_consulta,
)
from crmcore.http.parametros import admite_parametros_abiertos
from crmcore.http.retencion_router import crear_router_retencion
from fastapi import APIRouter, Depends, Header, Query, Request, status
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
    response_model=PaginaDeListado,
    dependencies=[Depends(exige_permiso("lead:read"))],
    summary="Listar leads",
)
def listar_leads(
    request: Request,
    db: DbDep,
    principal: AutenticadoDep,
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
    contar: bool = Query(False, description=CONTAR_TOTAL_DESCRIPCION),
    estado: str = Query(""),
    mios: bool = Query(False),
    sla_en_riesgo: bool = Query(False, description="Sin responder y con el SLA vencido o cerca"),
) -> Any:
    from datetime import datetime, timezone

    params = ParametrosPagina.desde_query(limite=limite, cursor=cursor, orden="-created_at")
    consulta = aplicar_visibilidad(
        select(Lead).where(Lead.deleted_at.is_(None)),
        Lead,
        db=db,
        principal=principal,
        objeto="lead",
        permiso_ver_todo="lead:admin",
    )
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
    # Los filtros comunes, con sus rangos: `?created_at__desde=2026-10-01`.
    #
    # Este listado está escrito a mano porque tiene filtros propios que la
    # fábrica no sabe expresar. Eso no es motivo para que además le falten los
    # comunes: si no, el mismo producto admite rangos o no según cómo montó
    # cada listado quien lo escribió, y eso lo descubre el integrador probando.
    consulta = aplicar_filtros_de_la_url(
        request, Lead, consulta, principal=principal, db=db, objeto="lead"
    )
    # El total sólo si se pide, y **antes del cursor**: con el cursor puesto
    # contaría cuántas quedan desde esta página, que encoge al avanzar y se
    # lee como el total. Sale de la consulta ya acotada por compartición y
    # filtros: es cuántas ve quien pregunta, no cuántas hay en la tabla.
    total = contar_consulta(db, consulta) if contar else None
    consulta = aplicar_orden_y_cursor(
        consulta,
        Lead,
        params,
        columnas_permitidas={"created_at", "sla_primera_respuesta_at", "estado"},
        objeto="lead",
        principal=principal,
        db=db,
    )
    filas = list(db.execute(consulta.limit(params.limite + 1)).scalars().all())
    pagina = construir_pagina(filas, params, campos_orden=["-created_at"], total_aprox=total)
    return pagina.a_dict(
        proyectar_con_esquema(proyectar_para(principal, db, objeto="lead", modelo=Lead), LeadOut)
    )


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
    description=(
        "Los que tiene esta empresa, que se gestionan en "
        "`/sales/vocabularios/motivos_descarte`. Mientras no toque ninguno son "
        "los que trae el producto."
    ),
)
def motivos_descarte(db: DbDep, _: AutenticadoDep) -> Any:
    return sorted(vocabulario.valores(db, "motivos_descarte"))


@router_leads.get(
    "/{lead_id}",
    response_model=dict,
    dependencies=[Depends(exige_permiso("lead:read"))],
    summary="Ficha de un lead",
    description=(
        "Faltaba, y el efecto era que se podía descartar o convertir un lead "
        "que no se podía abrir: todas las acciones sobre `/leads/{lead_id}` "
        "existían y el `GET` que lo enseña, no."
    ),
)
def obtener_lead(lead_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    lead = db.get(Lead, lead_id)
    # 404 y no 403 cuando es de otro tenant o está borrado: un 403 confirmaría
    # que ese identificador existe, y eso ya es información.
    if lead is None or lead.deleted_at is not None:
        raise NoEncontrado("El lead no existe", error_code="sales.lead_no_encontrado")
    # El permiso dice si puedes leer leads; la decisión dice si puedes leer
    # ESTE. Sin ella, dar `lead:read` sería dar la cartera entera.
    exigir(db, objeto="lead", accion="leer", registro=lead)
    proyecta = proyectar_para(principal, db, objeto="lead", modelo=Lead)
    return proyecta(lead)


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
    response_model=PaginaDeListado,
    dependencies=[Depends(exige_permiso("pipeline:read"))],
    summary="Pipelines con sus etapas",
)
def listar_pipelines(
    request: Request,
    db: DbDep,
    principal: AutenticadoDep,
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
    contar: bool = Query(False, description=CONTAR_TOTAL_DESCRIPCION),
) -> Any:
    def con_etapas(pipeline: Any) -> dict[str, Any]:
        # Las etapas se piden por pipeline y no de una vez: son pocas por
        # pipeline y traerlas todas para repartirlas después obliga a cargar en
        # memoria las de los pipelines que esta página no enseña.
        etapas = (
            db.execute(select(Etapa).where(Etapa.pipeline_id == pipeline.id).order_by(Etapa.orden))
            .scalars()
            .all()
        )
        return PipelineOut(
            id=pipeline.id,
            clave=pipeline.clave,
            nombre=pipeline.nombre,
            descripcion=pipeline.descripcion,
            ambito=pipeline.ambito,
            activo=pipeline.activo,
            por_defecto=pipeline.por_defecto,
            etapas=[EtapaOut.model_validate(e) for e in etapas],
        ).model_dump()

    consulta = select(Pipeline).where(Pipeline.tenant_id == principal.tenant_id)
    # Y los filtros comunes, con sus rangos. Estar escrito a mano no es motivo
    # para quedarse sin ellos: entonces el mismo producto admite
    # `?vence_at__hasta=…` o no según quién escribió cada listado, y eso lo
    # descubre el integrador probando.
    consulta = aplicar_filtros_de_la_url(
        request, Pipeline, consulta, principal=principal, db=db, objeto="pipeline"
    )
    return paginar_consulta(
        db,
        Pipeline,
        consulta,
        limite=limite,
        cursor=cursor,
        orden="nombre",
        fila_a_dict=con_etapas,
        contar=contar,
    )


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


def _una_oportunidad(db: Any, oportunidad: Any) -> Any:
    """Una oportunidad con el nombre de su etapa y su pipeline resueltos."""
    nombres_pipeline, nombres_etapa = _nombres_de_etapa(db, [oportunidad])
    return OportunidadOut.model_validate(
        {
            **oportunidad.__dict__,
            "importe_ponderado": oportunidad.importe_ponderado,
            "pipeline": nombres_pipeline.get(oportunidad.pipeline_id),
            "etapa": nombres_etapa.get(oportunidad.etapa_id),
        }
    )


def _nombres_de_etapa(db: Any, filas: list[Any]) -> tuple[dict, dict]:
    """Nombre de cada pipeline y de cada etapa que aparecen en estas filas.

    Dos consultas para la página entera, no una por oportunidad: con cincuenta
    filas, resolverlo fila a fila son cien consultas para pintar dos columnas.
    """
    from services.sales.modelos import Etapa, Pipeline

    etapas = {o.etapa_id for o in filas if o.etapa_id}
    pipelines = {o.pipeline_id for o in filas if o.pipeline_id}
    nombres_etapa = (
        {e.id: e.nombre for e in db.execute(select(Etapa).where(Etapa.id.in_(etapas))).scalars()}
        if etapas
        else {}
    )
    nombres_pipeline = (
        {
            p.id: p.nombre
            for p in db.execute(select(Pipeline).where(Pipeline.id.in_(pipelines))).scalars()
        }
        if pipelines
        else {}
    )
    return nombres_pipeline, nombres_etapa


@router_oportunidades.get(
    "",
    response_model=PaginaDeListado,
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Listar oportunidades",
)
def listar_oportunidades(
    request: Request,
    db: DbDep,
    principal: AutenticadoDep,
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
    contar: bool = Query(False, description=CONTAR_TOTAL_DESCRIPCION),
    estado: str = Query("abierta"),
    cuenta_id: UUID | None = Query(None),
    mias: bool = Query(False),
) -> Any:
    params = ParametrosPagina.desde_query(limite=limite, cursor=cursor, orden="-created_at")
    consulta = aplicar_visibilidad(
        select(Oportunidad).where(Oportunidad.deleted_at.is_(None)),
        Oportunidad,
        db=db,
        principal=principal,
        objeto="oportunidad",
        permiso_ver_todo="opportunity:admin",
    )
    if estado:
        consulta = consulta.where(Oportunidad.estado == estado)
    if cuenta_id:
        consulta = consulta.where(Oportunidad.cuenta_id == cuenta_id)
    if mias:
        consulta = consulta.where(Oportunidad.owner_id == principal.id)
    # Los filtros comunes, con sus rangos: `?cierre_previsto__hasta=2026-11-02`.
    #
    # Este listado está escrito a mano porque tiene filtros propios que la
    # fábrica no sabe expresar. Eso no es motivo para que además le falten los
    # comunes: si no, el mismo producto admite rangos o no según cómo montó
    # cada listado quien lo escribió, y eso lo descubre el integrador probando.
    consulta = aplicar_filtros_de_la_url(
        request, Oportunidad, consulta, principal=principal, db=db, objeto="oportunidad"
    )
    # El total sólo si se pide, y **antes del cursor**: con el cursor puesto
    # contaría cuántas quedan desde esta página, que encoge al avanzar y se
    # lee como el total. Sale de la consulta ya acotada por compartición y
    # filtros: es cuántas ve quien pregunta, no cuántas hay en la tabla.
    total = contar_consulta(db, consulta) if contar else None
    consulta = aplicar_orden_y_cursor(
        consulta,
        Oportunidad,
        params,
        columnas_permitidas={"created_at", "fecha_cierre", "importe", "nombre"},
        objeto="oportunidad",
        principal=principal,
        db=db,
    )
    filas = list(db.execute(consulta.limit(params.limite + 1)).scalars().all())
    pagina = construir_pagina(filas, params, campos_orden=["-created_at"], total_aprox=total)
    nombres_pipeline, nombres_etapa = _nombres_de_etapa(db, filas)
    # POR LA PROYECCIÓN, igual que la ficha. Serializar con el esquema de salida
    # se saltaba el enmascaramiento por rol: la ficha tapaba el importe y el
    # listado de la misma fila lo enseñaba.
    proyecta = proyectar_para(principal, db, objeto="oportunidad", modelo=Oportunidad)

    def _fila(o: Any) -> dict[str, Any]:
        visto = proyecta(o)
        # Lo añadido —el importe ponderado y los nombres de embudo y etapa— sale
        # de campos ya proyectados o de catálogos, no de columnas sensibles.
        # Si el importe viene tapado, el ponderado no se calcula: enseñar el
        # derivado de un dato tapado es enseñar el dato.
        extra: dict[str, Any] = {
            "pipeline": nombres_pipeline.get(o.pipeline_id),
            "etapa": nombres_etapa.get(o.etapa_id),
        }
        if "importe" in visto:
            extra["importe_ponderado"] = o.importe_ponderado
        return {k: v for k, v in {**visto, **extra}.items() if k in OportunidadOut.model_fields}

    return pagina.a_dict(_fila)


@router_oportunidades.get(
    "/{oportunidad_id}",
    response_model=OportunidadOut,
    dependencies=[Depends(exige_permiso("opportunity:read"))],
    summary="Ficha de la oportunidad",
)
def obtener_oportunidad(oportunidad_id: UUID, db: DbDep) -> Any:
    oportunidad = svc._oportunidad(db, oportunidad_id)
    return _una_oportunidad(db, oportunidad)


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
    return _una_oportunidad(uow.db, oportunidad)


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
    return _una_oportunidad(uow.db, oportunidad)


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
    return _una_oportunidad(uow.db, oportunidad)


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
    # El padre se comprueba antes: un subrecurso de algo que no existe —o que
    # no es tuyo— tiene que responder 404 igual que el recurso padre. No
    # filtraba datos (el guard vacía la lista), pero el mismo identificador
    # daba 404 en un sitio y 200 en otro, y esa incoherencia es por donde se
    # cuela una fuga el día que el subrecurso incluya algo que no cuelgue de
    # una tabla con `tenant_id`. Lo encontró el fuzzing sistemático de rutas.
    svc.exigir_oportunidad(db, oportunidad_id)
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
    svc.exigir_oportunidad(db, oportunidad_id)
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
        "cuánto hay sobre la mesa y el ponderado cuánto se espera cerrar.\n\n"
        "Exige poder ver el importe **en claro**: un agregado sobre un campo "
        "oculto es el campo oculto cuando el grupo tiene un elemento."
    ),
)
def resumen(db: DbDep, principal: AutenticadoDep, pipeline_id: UUID | None = Query(None)) -> Any:
    # Un agregado es la vía más directa de todas para sacar un campo que no se
    # puede ver: la suma de una etapa con una sola oportunidad **es** el importe
    # de esa oportunidad. Por eso se exige verlo en claro, no enmascarado.
    exigir_campo_usable(
        "importe",
        modelo=Oportunidad,
        objeto="oportunidad",
        roles=frozenset(principal.roles),
        es_admin=principal.es_admin_plataforma,
        tenant_id=principal.tenant_id,
        db=db,
    )
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
    description=(
        "Los que tiene esta empresa, que se gestionan en "
        "`/sales/vocabularios/motivos_perdida`. Mientras no toque ninguno son "
        "los que trae el producto."
    ),
)
def motivos_perdida(db: DbDep, _: AutenticadoDep) -> Any:
    return sorted(vocabulario.valores(db, "motivos_perdida"))


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


class EditarRegla(BaseModel):
    """Los campos de la regla que se pueden cambiar, todos opcionales.

    Con esquema y no como `dict`: el formulario de edición se genera del
    contrato, y un cuerpo sin esquema lo dejaba en blanco. Se podía crear una
    regla de enrutado con su formulario y luego no había forma de cambiarla
    desde ninguna pantalla.
    """

    nombre: str | None = Field(None, max_length=150)
    descripcion: str | None = None
    prioridad: int | None = Field(None, ge=0, le=10_000)
    condiciones: list[CondicionEntrada] | None = None
    combinacion: str | None = Field(None, pattern="^(todas|alguna)$")
    estrategia: str | None = None
    candidatos: list[UUID] | None = None
    cola: str | None = Field(None, max_length=80)
    activa: bool | None = None


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


@router_enrutamiento.delete(
    "/reglas/{regla_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borrar una regla de enrutamiento",
    description=(
        "A la papelera, como todo: una regla de reparto quitada sin querer deja "
        "los leads cayendo en otra parte, y eso se nota tarde.\n\n"
        "Si hay algo que la use no se borra: responde 409 diciendo qué."
    ),
    dependencies=[Depends(exige_permiso("lead:configurar"))],
)
def borrar_regla(regla_id: UUID, uow: UowDep, principal: AutenticadoDep) -> None:
    from crmcore.datos import integridad, papelera

    fila = uow.db.get(enr.ReglaEnrutamiento, regla_id)
    if fila is None or fila.deleted_at is not None:
        raise NoEncontrado("Regla no encontrada", error_code="sales.regla_no_existe")
    integridad.exigir_sin_dependencias(uow.db, fila, objeto="regla_enrutamiento")
    papelera.borrar(
        uow.db, fila, objeto="regla_enrutamiento", etiqueta=fila.nombre, por=principal.id
    )


@router_enrutamiento.patch(
    "/reglas/{regla_id}",
    response_model=ReglaOut,
    summary="Editar una regla",
    dependencies=[Depends(exige_permiso("lead:configurar"))],
)
def editar_regla(regla_id: UUID, datos: EditarRegla, uow: UowDep) -> Any:
    fila = uow.db.get(enr.ReglaEnrutamiento, regla_id)
    if fila is None:
        raise NoEncontrado("Regla no encontrada", error_code="sales.regla_no_existe")
    # `exclude_unset` y no `exclude_none`: así se distingue «no lo toco» de
    # «déjalo vacío», que en `cola` son cosas distintas.
    cambios = datos.model_dump(exclude_unset=True, mode="json")
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
    svc.exigir_lead(db, lead_id)
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


# Con presupuestos, pedidos y contratos: son justo los registros a los que se
# les cuelga un PDF firmado, y no poder hacerlo obliga a guardarlo fuera —donde
# nadie lo encuentra el día que hay que demostrar qué se firmó.
router_adjuntos = crear_router_adjuntos(
    {"lead", "oportunidad", "linea_oportunidad", "presupuesto", "pedido", "contrato"}
)


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


router_comentarios = crear_router_comentarios(
    {"lead", "oportunidad", "presupuesto", "pedido", "contrato"}
)


# Las clases de dato de este servicio se declaran al importar su módulo.
from services.sales import retencion as _retencion  # noqa: E402,F401

# ── Recursos transversales, bajo el nombre del servicio ───────────────────
# Retención, búsqueda y trabajos los monta la misma fábrica en varios servicios.
# Con el camino corto —`/api/v1/trabajos/{id}`— el gateway no puede saber a cuál
# va: el identificador no delata al dueño. El resultado era que estas tres
# familias, escritas y probadas, devolvían 404 desde fuera. Con el nombre del
# servicio delante la ruta es inequívoca y además se lee.
router_retencion = crear_router_retencion("/sales/retencion")


from services.sales.indexacion import OBJETOS as _OBJETOS_BUSCABLES  # noqa: E402

router_busqueda = crear_router_busqueda(_OBJETOS_BUSCABLES, "/sales/buscar")


# Operaciones masivas y sus trabajos diferidos. El import de `masivo` registra
# los ejecutores; el worker hace ese mismo import por su cuenta, porque es otro
# proceso.
from crmcore.authz.decision import exigir  # noqa: E402
from crmcore.http.deps import proyectar_para  # noqa: E402
from crmcore.http.listados import (  # noqa: E402
    montar_exportacion,
    montar_ficha,
    montar_listado,
    proyectar_con_esquema,  # noqa: E402
)
from crmcore.http.masivo_router import crear_router_masivo  # noqa: E402
from crmcore.http.trabajos_router import crear_router_trabajos  # noqa: E402

from services.sales.masivo import RECURSOS as _RECURSOS_MASIVOS  # noqa: E402

routers_masivos = [crear_router_masivo(r) for r in _RECURSOS_MASIVOS]

# Un trabajo de `sales` guarda el lote de leads u oportunidades que se importó,
# así que verlo pide el mismo permiso que escribirlos, no uno de lectura.
router_trabajos = crear_router_trabajos(
    permiso_ver="lead:write", permiso_cancelar="lead:write", prefijo="/sales/trabajos"
)


# ── Captura de leads desde fuera (CRM-01.01.03.02) ────────────────────────

router_captura = APIRouter(prefix="/captura", tags=["captura de leads"])


class CrearCanalCaptura(BaseModel):
    clave: str = Field(max_length=80, description="Identificador del canal en la URL pública")
    nombre: str = Field(max_length=200)
    tipo: str = Field("formulario", description="formulario | chat | lista | otro")
    mapeo: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "De qué campo de entrada sale cada campo del lead: "
            '`{"email": "correo", "nombre": "nombre_completo"}`. Solo se pueden '
            "mapear campos de contacto: un canal público no puede escribir el "
            "propietario ni la campaña."
        ),
    )
    fijos: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Valores que pone siempre el canal: el origen, la campaña. Van aquí "
            "y no en la petición porque vienen del canal, no de quien rellena el "
            "formulario — que podría poner cualquier cosa."
        ),
    )
    obligatorios: list[str] = Field(default_factory=list)
    campo_trampa: str = Field(
        "",
        max_length=60,
        description=(
            "Campo que un humano nunca rellena porque no lo ve. Si viene con "
            "contenido, se descarta con un 200: un error le diría al robot qué "
            "cambiar para la próxima."
        ),
    )
    max_por_hora: int = Field(200, ge=1, le=100_000)


@router_captura.post(
    "/canales",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("lead:configurar"))],
    summary="Declarar un canal de captura",
    description=(
        "Un canal es la definición de **cómo se traduce lo que llega a un "
        "lead**. El formulario de la web manda `nombre_completo`, el chat manda "
        "`visitor_name` y la tablet de la feria manda `NOMBRE`: con un endpoint "
        "por cada uno, cada cliente nuevo es código nuevo; con un mapa "
        "declarado, es una fila.\\n\\n"
        "**El secreto se devuelve una sola vez.** Se guarda hasheado: si la base "
        "se filtra, las claves de los formularios de todos los tenants no vienen "
        "en ella. Si se pierde, se rota."
    ),
)
def crear_canal_captura(datos: CrearCanalCaptura, uow: UowDep, principal: AutenticadoDep) -> Any:
    from services.sales import captura

    canal, secreto = captura.crear_canal(
        uow.db, tenant_id=principal.tenant_id, **datos.model_dump()
    )
    return {
        "id": str(canal.id),
        "clave": canal.clave,
        "secreto": secreto,
        "aviso": (
            "Guárdalo ahora: no se conserva en claro y no se puede volver a "
            "consultar. Si se pierde, se rota."
        ),
    }


@router_captura.post(
    "/canales/{canal_id}/rotar",
    dependencies=[Depends(exige_permiso("lead:configurar"))],
    summary="Rotar el secreto del canal",
    description=(
        "El secreto viaja en el HTML de una página pública, así que se filtra: "
        "rotarlo es una operación normal, no una emergencia. Lo anterior deja de "
        "valer inmediatamente."
    ),
)
def rotar_secreto_captura(canal_id: UUID, uow: UowDep) -> Any:
    from services.sales import captura

    return {"secreto": captura.rotar_secreto(uow.db, canal_id)}


@router_captura.get(
    "/recepciones",
    dependencies=[Depends(exige_permiso("lead:read"))],
    summary="Qué ha entrado por los canales, incluido lo descartado",
    description=(
        "Es lo que convierte «no me llegó el lead del formulario» en una "
        "pregunta contestable: o no llegó, o llegó y se descartó por el motivo "
        "que dice aquí. Sin esto, la respuesta es mirar el log del servidor web."
    ),
)
def listar_recepciones(
    db: DbDep,
    _: AutenticadoDep,
    canal_id: UUID | None = Query(None),
    solo_descartadas: bool = Query(False),
    limite: int = Query(100, ge=1, le=500),
) -> Any:
    from services.sales import captura

    return captura.recepciones(
        db, canal_id=canal_id, solo_descartadas=solo_descartadas, limite=limite
    )


# ── El endpoint público ───────────────────────────────────────────────────
#
# Va SIN el prefijo de versión y sin autenticación de usuario, porque lo llama
# el navegador de un desconocido desde la web del cliente. Lo que lo protege es
# la clave del canal, la trampa y el tope — ver `services/sales/captura.py`.

router_publico = APIRouter(prefix="/captura", tags=["captura pública"])


@router_publico.post(
    "/{tenant_id}/{clave}",
    summary="Recibir un lead desde un formulario, un chat o una tablet",
    description=(
        "Endpoint **público**: lo llama el navegador de un desconocido. No es "
        "anónimo — lleva la clave del canal— pero esa clave viaja en el HTML de "
        "una página pública y por tanto se filtra. Lo que acota el daño es el "
        "tope por hora que declara el canal.\\n\\n"
        "Devuelve **siempre la misma forma**, también al descartar: una "
        "respuesta distinta por cada motivo le enseñaría a un robot qué tiene "
        "que cambiar.\n\n"
        "El tenant va por **identificador y no por slug**: traducir un slug "
        "exige leer la tabla de tenants, que es de `tenancy`, y eso ataría la "
        "captura de leads a que ese servicio esté en pie justo cuando un "
        "desconocido rellena el formulario. El identificador no es un secreto — "
        "lo que autoriza es la clave del canal."
    ),
    include_in_schema=True,
)
async def recibir_lead(
    tenant_id: UUID,
    clave: str,
    peticion: Request,
    x_captura_secreto: str = Header("", alias="X-Captura-Secreto"),
) -> Any:
    """El tenant va por **identificador y no por slug**, y es deliberado.

    Traducir un slug a identificador exige leer la tabla de tenants, que es de
    `tenancy`, y ningún servicio lee el esquema de otro. La alternativa sería
    una llamada entre servicios en cada envío de formulario: ataría la captura
    de leads a que `tenancy` esté en pie, justo en el momento en que un
    desconocido está rellenando un formulario en la web del cliente.

    El identificador no es un secreto —lo que autoriza es la clave del canal— y
    quien monta el formulario lo pega una vez en el HTML.
    """
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.http.cuerpo import cuerpo_json
    from crmcore.tenancy.context import con_contexto

    from services.sales import captura

    # Por el lector común y no con `await peticion.json()` a pelo: ahí, un
    # cuerpo que no es JSON —un formulario mal montado, un robot, una petición
    # vacía— reventaba con un **500**. Y es la peor respuesta posible en una
    # ruta pública: dice «me has roto» en vez de «esto no vale», que es una
    # invitación a insistir.
    entrada = await cuerpo_json(peticion)

    with con_contexto(tenant_id=tenant_id, origen="api"), unidad_de_trabajo(tenant_id) as uow:
        return captura.recibir(
            uow,
            tenant_id=tenant_id,
            clave=clave,
            secreto=x_captura_secreto,
            entrada=entrada,
        )


# Corpus documental delegado en contecmind (RT-5). La lista blanca impide que
# este servicio enlace documentos a objetos que no son suyos.
router_documental = crear_router_documental(
    {"lead", "oportunidad", "presupuesto", "pedido", "contrato"}
)


from services.sales.api_forecast import ROUTERS_FORECAST  # noqa: E402
from services.sales.captura import CanalCaptura  # noqa: E402
from services.sales.origen import Toque  # noqa: E402

# ── Listados ──────────────────────────────────────────────────────────────
# Colecciones que se podían crear y no se podían leer. La API contestaba 405
# —o, en el caso de los artículos, un 422 confuso porque `/conocimiento/articulos`
# encajaba en `/conocimiento/{articulo_id}` y «articulos» no es un UUID— y el
# front enseñaba una pantalla vacía sin decir por qué.

montar_listado(
    router_origen,
    modelo=Toque,
    objeto="toque",
    permiso="lead:read",
    ruta="/toques",
    nombre="Toques de origen",
)
montar_listado(
    router_captura,
    modelo=CanalCaptura,
    objeto="canal_captura",
    permiso="lead:read",
    ruta="/canales",
    nombre="Canales de captura",
)


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
    router_documental,
    router_trabajos,
    router_captura,
    *routers_masivos,
    *ROUTERS_FORECAST,
]

# El endpoint público de captura va aparte y **sin el prefijo de versión**: lo
# pega un cliente en el HTML de su web, y una URL con `/api/v1/` dentro invita a
# que alguien la cambie a `/api/v2/` el día que exista y se le rompa el
# formulario sin avisar.
ROUTERS_SIN_PREFIJO = [router_publico]


# ── Lo que a la ficha le faltaba: corregir y borrar ───────────────────────
# Estos tres ya se podían abrir —tienen su lectura escrita a mano, con sus
# reglas de visibilidad— y no se podían ni corregir ni borrar desde ninguna
# pantalla. Un contacto con el correo mal escrito se quedaba así para siempre.
montar_ficha(
    router_leads,
    modelo=Lead,
    objeto="lead",
    permiso_leer="lead:read",
    permiso_escribir="lead:write",
    nombre="Leads",
    parametro="lead_id",
    con_lectura=False,
)


# ── Lo que a la ficha le faltaba: corregir y borrar ───────────────────────
# Se podían abrir —tienen su lectura escrita a mano— y no se podían ni
# corregir ni borrar desde ninguna pantalla.
montar_ficha(
    router_oportunidades,
    modelo=Oportunidad,
    objeto="oportunidad",
    permiso_leer="opportunity:read",
    permiso_escribir="opportunity:write",
    nombre="Oportunidades",
    parametro="oportunidad_id",
    con_lectura=False,
)


# ── La ficha del registro ─────────────────────────────────────────────────
# Sin ella, las acciones que cuelgan de un registro no se alcanzan desde
# ninguna pantalla: existen, se prueban y nadie las usa.
montar_ficha(
    router_pipelines,
    modelo=Pipeline,
    objeto="pipeline",
    permiso_leer="pipeline:read",
    permiso_escribir="pipeline:write",
    nombre="Procesos de venta",
    parametro="pipeline_id",
)


# La exportación de las colecciones con listado escrito a mano. `montar_listado`
# la monta sola; estas no se montan con él, y son justo las que alguien quiere
# exportar de verdad: dejarlas fuera habría dado un producto con exportación en
# las sesenta colecciones secundarias y sin ella en las cinco principales.
montar_exportacion(router_leads, modelo=Lead, objeto="lead", permiso="lead:read", nombre="Leads")
montar_exportacion(
    router_oportunidades,
    modelo=Oportunidad,
    objeto="oportunidad",
    permiso="opportunity:read",
    nombre="Oportunidades",
)
montar_exportacion(
    router_enrutamiento,
    modelo=enr.ReglaEnrutamiento,
    objeto="regla_enrutamiento",
    permiso="lead:read",
    nombre="Reglas de enrutamiento",
    ruta="/reglas",
)


# Esta ruta acepta además los filtros comunes, cuyos nombres son columnas del
# modelo y cambian con él: no se pueden declarar. Los valida
# `aplicar_filtros_de_la_url`, que rechaza lo que no es columna o lo que este
# principal no ve en claro.
admite_parametros_abiertos(
    listar_leads, "llama a `aplicar_filtros_de_la_url`, que valida los filtros por columna"
)


# Esta ruta acepta además los filtros comunes, cuyos nombres son columnas del
# modelo y cambian con él: no se pueden declarar. Los valida
# `aplicar_filtros_de_la_url`, que rechaza lo que no es columna o lo que este
# principal no ve en claro.
admite_parametros_abiertos(
    listar_oportunidades, "llama a `aplicar_filtros_de_la_url`, que valida los filtros por columna"
)


# Estas rutas aceptan además los filtros comunes, cuyos nombres son columnas
# del modelo y cambian con él: no se pueden declarar. Los valida
# `aplicar_filtros_de_la_url`, que rechaza lo que no es columna o lo que este
# principal no ve en claro. Las dos mitades van juntas: con el filtro y sin la
# marca, la ruta contesta 422 a sus propios filtros.
admite_parametros_abiertos(
    listar_pipelines, "llama a `aplicar_filtros_de_la_url`, que valida los filtros por columna"
)
