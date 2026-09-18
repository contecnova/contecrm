"""API HTTP del servicio de tenancy.

Los routers solo traducen HTTP: validan la entrada, llaman a `servicio.py` y
serializan. Cualquier decisión de negocio que aparezca aquí es un error de
capa, y hay un gate que lo comprueba (`test_layering_contract.py`).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.errors import NoEncontrado
from crmcore.http.deps import (
    AutenticadoDep,
    DbDep,
    PlataformaDep,
    UowDep,
    exige_permiso,
)
from crmcore.http.pagination import ParametrosPagina, construir_pagina
from crmcore.runtime import settings as rt
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select

from services.tenancy import servicio as svc
from services.tenancy.esquemas import (
    CambiarEstado,
    ConsumoOut,
    CrearTenant,
    CrearUnidad,
    FijarAjuste,
    FijarFlag,
    PlanOut,
    TenantOut,
    UnidadOut,
)
from services.tenancy.modelos import FeatureFlag, Plan, Tenant, UnidadNegocio

router = APIRouter(prefix="/tenants", tags=["tenants"])


# ── Ciclo de vida ─────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=TenantOut,
    status_code=status.HTTP_201_CREATED,
    summary="Dar de alta un tenant",
    description=(
        "Provisiona un tenant con su configuración inicial. Es una operación de "
        "plataforma: un tenant no puede crear otros."
    ),
)
def crear_tenant(datos: CrearTenant, uow: UowDep, _: PlataformaDep) -> Any:
    return svc.crear_tenant(uow, **datos.model_dump())


@router.get("", response_model=dict, summary="Listar tenants")
def listar_tenants(
    db: DbDep,
    _: PlataformaDep,
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
    estado: str = Query("", description="Filtra por estado"),
) -> Any:
    params = ParametrosPagina.desde_query(limite=limite, cursor=cursor, orden="-created_at")
    consulta = select(Tenant)
    if estado:
        consulta = consulta.where(Tenant.estado == estado)
    from crmcore.http.pagination import aplicar_orden_y_cursor

    consulta = aplicar_orden_y_cursor(
        consulta, Tenant, params, columnas_permitidas={"created_at", "slug", "nombre"}
    )
    # Se pide uno más de los que se van a devolver: esa fila de sobra es cómo se
    # sabe si hay página siguiente sin un `count` que recorra la tabla.
    filas = list(db.execute(consulta.limit(params.limite + 1)).scalars().all())
    pagina = construir_pagina(filas, params, campos_orden=["-created_at"])
    return pagina.a_dict(lambda t: TenantOut.model_validate(t).model_dump(mode="json"))


@router.get("/{tenant_id}", response_model=TenantOut, summary="Ficha del tenant")
def obtener_tenant(tenant_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    tenant = db.get(Tenant, tenant_id)
    # 404 y no 403 cuando se pregunta por un tenant ajeno (CRM-00.01.02.05): un
    # 403 confirmaría que ese identificador existe, y eso ya es información.
    if tenant is None or (not principal.es_admin_plataforma and principal.tenant_id != tenant_id):
        raise NoEncontrado("El tenant no existe", error_code="tenant.no_encontrado")
    return tenant


@router.post(
    "/{tenant_id}/estado",
    response_model=TenantOut,
    summary="Cambiar el estado del tenant",
    description=(
        "Suspende, congela en solo lectura, reactiva o inicia la baja. Exige "
        "motivo escrito en todo lo que degrada el servicio."
    ),
)
def cambiar_estado(tenant_id: UUID, datos: CambiarEstado, uow: UowDep, _: PlataformaDep) -> Any:
    return svc.cambiar_estado(uow, tenant_id, nuevo=datos.estado, motivo=datos.motivo)


# ── Unidades de negocio ───────────────────────────────────────────────────


@router.post(
    "/{tenant_id}/unidades",
    response_model=UnidadOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Crear una unidad de negocio",
)
def crear_unidad(tenant_id: UUID, datos: CrearUnidad, db: DbDep) -> Any:
    return svc.crear_unidad(db, tenant_id, **datos.model_dump())


@router.get(
    "/{tenant_id}/unidades",
    response_model=list[UnidadOut],
    summary="Unidades de negocio del tenant",
)
def listar_unidades(tenant_id: UUID, db: DbDep, _: AutenticadoDep) -> Any:
    return list(
        db.execute(
            select(UnidadNegocio)
            .where(UnidadNegocio.tenant_id == tenant_id)
            .order_by(UnidadNegocio.codigo)
        )
        .scalars()
        .all()
    )


# ── Planes y capacidades ──────────────────────────────────────────────────

router_planes = APIRouter(prefix="/planes", tags=["planes"])


@router_planes.get("", response_model=list[PlanOut], summary="Planes disponibles")
def listar_planes(db: DbDep, _: AutenticadoDep) -> Any:
    return list(
        db.execute(select(Plan).where(Plan.activo.is_(True)).order_by(Plan.codigo)).scalars().all()
    )


@router.get(
    "/{tenant_id}/capacidades",
    response_model=dict,
    summary="Capacidades activas del tenant",
    description=(
        "Lo que el plan del tenant tiene activado. Un frontend headless lo "
        "consulta para no ofrecer lo que no está contratado."
    ),
)
def capacidades(tenant_id: UUID, db: DbDep, _: AutenticadoDep) -> Any:
    return svc.capacidades_de(db, tenant_id)


# ── Feature flags ─────────────────────────────────────────────────────────

router_flags = APIRouter(prefix="/flags", tags=["feature flags"])


@router_flags.get("/{clave}", response_model=dict, summary="Estado de un flag")
def estado_flag(clave: str, db: DbDep, principal: AutenticadoDep) -> Any:
    return {
        "clave": clave,
        "activo": svc.flag_activo(db, clave, tenant_id=principal.tenant_id, user_id=principal.id),
    }


@router_flags.put(
    "/{clave}",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Fijar un flag para el tenant",
)
def fijar_flag(clave: str, datos: FijarFlag, db: DbDep, principal: AutenticadoDep) -> Any:
    flag = db.execute(
        select(FeatureFlag).where(
            FeatureFlag.clave == clave,
            FeatureFlag.tenant_id == principal.tenant_id,
            FeatureFlag.user_id.is_(None),
        )
    ).scalar_one_or_none()
    if flag is None:
        flag = FeatureFlag(clave=clave, tenant_id=principal.tenant_id)
        db.add(flag)
        db.flush()
    flag.activo = datos.activo
    flag.porcentaje = datos.porcentaje
    flag.descripcion = datos.descripcion
    return {"clave": clave, "activo": flag.activo, "porcentaje": flag.porcentaje}


# ── Ajustes en caliente ───────────────────────────────────────────────────

router_ajustes = APIRouter(prefix="/ajustes", tags=["ajustes"])


@router_ajustes.get(
    "",
    response_model=dict,
    summary="Ajustes efectivos",
    description=(
        "Cada ajuste con su valor efectivo y **de qué ámbito sale**. Sin la "
        "procedencia, un administrador no entiende por qué lo que acaba de "
        "guardar no se aplica (lo sobrescribe un ámbito más específico)."
    ),
)
def listar_ajustes(db: DbDep, _: AutenticadoDep) -> Any:
    return rt.valores_efectivos(db)


@router_ajustes.put(
    "/{clave}",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Fijar un ajuste",
)
def fijar_ajuste(clave: str, datos: FijarAjuste, db: DbDep, principal: AutenticadoDep) -> Any:
    ambito_id = datos.ambito_id or (str(principal.tenant_id) if datos.ambito == "tenant" else "")
    valor = rt.fijar(
        db, clave, datos.valor, ambito=datos.ambito, ambito_id=ambito_id, por=principal.id
    )
    return {"clave": clave, "valor": valor, "ambito": datos.ambito}


# ── Consumo y cuotas ──────────────────────────────────────────────────────


@router.get(
    "/{tenant_id}/consumo",
    response_model=list[ConsumoOut],
    summary="Consumo del periodo frente a los topes",
    description=(
        "Alimenta el panel de consumo del tenant y los avisos de aproximación " "al límite."
    ),
)
def consumo(tenant_id: UUID, db: DbDep, _: AutenticadoDep) -> Any:
    umbral = int(rt.efectivo("quota_aviso_pct", db) or 80)
    salida = []
    # Pares (métrica medida, clave de la cuota que la limita). Se declaran aquí
    # y no se derivan por nombre porque no siempre coinciden: la métrica es lo
    # que se cuenta y la cuota es lo que se contrata.
    for metrica, clave in (
        ("api_calls", "quota_api_calls_por_minuto"),
        ("registros", "quota_registros"),
        ("almacenamiento_mb", "quota_almacenamiento_mb"),
        ("correos", "quota_correos_por_dia"),
        ("tokens_ia", "quota_tokens_ia_por_dia"),
    ):
        consumido = svc.consumo_actual(db, tenant_id, metrica)
        limite = svc.limite_de(db, tenant_id, clave)
        pct = round(consumido / limite * 100, 1) if limite > 0 else 0.0
        salida.append(
            ConsumoOut(
                metrica=metrica,
                periodo="actual",
                consumido=consumido,
                limite=limite,
                pct=pct,
                en_aviso=limite > 0 and pct >= umbral,
            )
        )
    return salida


ROUTERS = [router, router_planes, router_flags, router_ajustes]
