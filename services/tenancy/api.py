"""API HTTP del servicio de tenancy.

Los routers solo traducen HTTP: validan la entrada, llaman a `servicio.py` y
serializan. Cualquier decisión de negocio que aparezca aquí es un error de
capa, y hay un gate que lo comprueba (`test_layering_contract.py`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.http.deps import (
    AutenticadoDep,
    DbDep,
    PlataformaDep,
    UowDep,
    exige_firma_interna,
    exige_permiso,
    proyectar_para,
)
from crmcore.http.listados import aplicar_filtros_de_la_url, proyectar_con_esquema
from crmcore.http.pagination import (
    CONTAR_TOTAL_DESCRIPCION,
    PaginaDeListado,
    ParametrosPagina,
    construir_pagina,
    contar_consulta,
    paginar_consulta,
)
from crmcore.http.parametros import admite_parametros_abiertos
from crmcore.runtime import settings as rt
from crmcore.runtime.keys import es_preferencia_personal, preferencias_personales
from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.tenancy import servicio as svc
from services.tenancy.api_aislamiento import ROUTERS_AISLAMIENTO
from services.tenancy.api_alta import ROUTERS_ALTA
from services.tenancy.api_byok import ROUTERS_BYOK
from services.tenancy.api_catalogos import ROUTERS_CATALOGOS
from services.tenancy.api_ciclo_vida import ROUTERS_CICLO_VIDA
from services.tenancy.api_compromisos import ROUTERS_COMPROMISOS
from services.tenancy.api_grc import ROUTERS_GRC
from services.tenancy.api_grc_serie import ROUTERS_GRC_SERIE
from services.tenancy.api_jerarquia import ROUTERS_JERARQUIA
from services.tenancy.api_marca import ROUTERS_MARCA
from services.tenancy.api_sandboxes import ROUTERS_SANDBOXES
from services.tenancy.api_tcsec import ROUTERS_TCSEC
from services.tenancy.esquemas import (
    CambiarEstado,
    ConsumoOut,
    CrearTenant,
    CrearUnidad,
    FijarAjuste,
    FijarFlag,
    FijarMiPreferencia,
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


class EditarTenant(BaseModel):
    """Lo que se puede cambiar de un tenant ya provisionado.

    El `slug` no está: va en subdominios, en URLs y en los identificadores que
    ya tienen fuera, así que cambiarlo rompe enlaces que no controlamos. Para
    cambiar de nombre comercial está `nombre`.

    Faltaba entera: se podía dar de alta una empresa y después no había forma
    de corregirle ni una errata en el nombre desde ninguna pantalla.
    """

    nombre: str | None = Field(None, min_length=1, max_length=200)
    plan: str | None = None
    tier: str | None = None
    idioma: str | None = Field(None, max_length=10)
    zona_horaria: str | None = Field(None, max_length=60)
    moneda: str | None = Field(None, max_length=3)
    marca: dict[str, Any] | None = None


@router.patch(
    "/{tenant_id}",
    response_model=TenantOut,
    summary="Editar un tenant",
    description=(
        "Es de plataforma: un tenant no se edita a sí mismo por aquí. El `slug` "
        "no se toca porque está en URLs y en sistemas de fuera."
    ),
)
def editar_tenant(tenant_id: UUID, datos: EditarTenant, uow: UowDep, _: PlataformaDep) -> Any:
    tenant = uow.db.get(Tenant, tenant_id)
    if tenant is None:
        raise NoEncontrado("Ese tenant no existe", error_code="tenancy.tenant_no_existe")
    cambios = datos.model_dump(exclude_unset=True)
    for campo, valor in cambios.items():
        setattr(tenant, campo, valor)
    uow.db.flush()
    svc.propagar_localizacion(uow.db, tenant, cambios)
    return tenant


@router.get("", response_model=PaginaDeListado, summary="Listar tenants")
def listar_tenants(
    request: Request,
    db: DbDep,
    principal: PlataformaDep,
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
    contar: bool = Query(False, description=CONTAR_TOTAL_DESCRIPCION),
    estado: str = Query("", description="Filtra por estado"),
    slug: str = Query("", description="Busca por identificador corto, entero o por partes"),
    q: str = Query("", description="Busca en el nombre"),
) -> Any:
    params = ParametrosPagina.desde_query(limite=limite, cursor=cursor, orden="-created_at")
    consulta = select(Tenant)
    if estado:
        consulta = consulta.where(Tenant.estado == estado)
    # Buscar por slug o por nombre. Sin esto, dar con una empresa concreta en
    # una instalación con cientos exigía paginar hasta encontrarla, y quien
    # llama por dentro —el arranque, que solo sabe el slug— no tenía forma de
    # preguntarlo.
    if slug:
        consulta = consulta.where(Tenant.slug.ilike(f"%{slug}%"))
    if q:
        consulta = consulta.where(Tenant.nombre.ilike(f"%{q}%"))
    from crmcore.http.pagination import aplicar_orden_y_cursor

    # Y los filtros comunes, con sus rangos. Estar escrito a mano no es motivo
    # para quedarse sin ellos: entonces el mismo producto admite
    # `?vence_at__hasta=…` o no según quién escribió cada listado, y eso lo
    # descubre el integrador probando.
    consulta = aplicar_filtros_de_la_url(
        request, Tenant, consulta, principal=principal, db=db, objeto="tenant"
    )
    # El total sólo si se pide, y **antes del cursor**: con el cursor puesto
    # contaría cuántas quedan desde esta página, que encoge al avanzar y se
    # lee como el total. Sale de la consulta ya acotada por compartición y
    # filtros: es cuántas ve quien pregunta, no cuántas hay en la tabla.
    total = contar_consulta(db, consulta) if contar else None
    consulta = aplicar_orden_y_cursor(
        consulta, Tenant, params, columnas_permitidas={"created_at", "slug", "nombre"}
    )
    # Se pide uno más de los que se van a devolver: esa fila de sobra es cómo se
    # sabe si hay página siguiente sin un `count` que recorra la tabla.
    filas = list(db.execute(consulta.limit(params.limite + 1)).scalars().all())
    pagina = construir_pagina(filas, params, campos_orden=["-created_at"], total_aprox=total)
    # Por la proyección, igual que la ficha: un listado que serializa con el
    # esquema de salida se salta el enmascaramiento por rol, y entonces enseña
    # lo que la ficha de la misma fila tapa.
    return pagina.a_dict(
        proyectar_con_esquema(
            proyectar_para(principal, db, objeto="tenant", modelo=Tenant), TenantOut
        )
    )


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


@router_planes.get("", response_model=PaginaDeListado, summary="Planes disponibles")
def listar_planes(
    request: Request,
    db: DbDep,
    principal: AutenticadoDep,
    limite: int = Query(50, ge=1, le=200),
    cursor: str = Query(""),
    contar: bool = Query(False, description=CONTAR_TOTAL_DESCRIPCION),
) -> Any:
    consulta = select(Plan).where(Plan.activo.is_(True))
    # Y los filtros comunes, con sus rangos. Estar escrito a mano no es motivo
    # para quedarse sin ellos: entonces el mismo producto admite
    # `?vence_at__hasta=…` o no según quién escribió cada listado, y eso lo
    # descubre el integrador probando.
    consulta = aplicar_filtros_de_la_url(
        request, Plan, consulta, principal=principal, db=db, objeto="plan"
    )
    return paginar_consulta(
        db,
        Plan,
        consulta,
        limite=limite,
        cursor=cursor,
        orden="codigo",
        modelo_salida=PlanOut,
        contar=contar,
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
    # `dict` y no `PaginaDeListado`: esto NO es un listado paginado, es el mapa
    # de ajustes con su valor efectivo y su procedencia. Se lo puse al convertir
    # los listados en bloque —el nombre `listar_ajustes` engañaba— y devolvía
    # 500 por validación de la respuesta: «Field required: items».
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


# ── Versiones de la configuración (CRM-00.01.04.02) ───────────────────────
#
# `fijar` guardaba cada cambio con su antes y su después desde septiembre, y
# ninguna ruta lo enseñaba: el historial, el diff y la vuelta atrás estaban
# escritos y probados en `crmcore.runtime.versiones` y sólo se llegaba a ellos
# desde una prueba. Medido el 09-11-2026.


@router_ajustes.get(
    "/versiones",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Historial de cambios de la configuración",
    description=(
        "Los cambios de ajustes de este tenant, del más reciente al más antiguo, "
        "cada uno con el valor de antes y el de después, quién y cuándo. Con "
        "`clave`, sólo los de ese ajuste. Devuelve además qué ajustes tienen "
        "historial, para poder elegir sin saberse la clave."
    ),
)
def versiones_de_ajustes(
    db: DbDep,
    principal: AutenticadoDep,
    clave: str = Query("", max_length=120),
    limite: int = Query(100, ge=1, le=500),
) -> Any:
    from crmcore.runtime import versiones

    tenant_id = principal.tenant_id
    return {
        "claves": versiones.claves_con_historial(db, tenant_id),
        "versiones": versiones.historial(db, tenant_id, clave=clave, limite=limite),
    }


@router_ajustes.get(
    "/versiones/diferencias",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Qué cambió en la configuración entre dos momentos",
    description=(
        "Colapsado por ajuste: de dónde salió y dónde acabó, con cuántos cambios "
        "hubo entre medias y quién los hizo. Lo que acabó igual que empezó no "
        "sale: no cambió nada."
    ),
)
def diferencias_de_ajustes(
    db: DbDep,
    principal: AutenticadoDep,
    desde: datetime = Query(..., description="Inicio, ISO 8601"),
    hasta: datetime | None = Query(None, description="Fin, ISO 8601; sin él, ahora"),
) -> Any:
    from crmcore.runtime import versiones

    return {
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat() if hasta else None,
        "cambios": versiones.diff(db, principal.tenant_id, desde=desde, hasta=hasta),
    }


@router_ajustes.get(
    "/versiones/comparar",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Diferencias entre dos versiones de un ajuste",
)
def comparar_versiones(db: DbDep, principal: AutenticadoDep, a: UUID, b: UUID) -> Any:
    from crmcore.runtime import versiones

    return versiones.comparar(db, principal.tenant_id, a, b)


@router_ajustes.post(
    "/versiones/{version_id}/volver",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Volver al valor de antes de un cambio",
    description=(
        "Deshace ese cambio poniendo el valor que había antes, por el camino "
        "normal —se replica a todos los servicios— y queda en el historial como "
        "una vuelta atrás y en la auditoría como `ajuste.vuelta_atras`. No borra "
        "el apunte original."
    ),
)
def volver_a_version(version_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    from crmcore.runtime import versiones

    return versiones.volver_a(db, version_id, tenant_id=principal.tenant_id, por=principal.id)


# ── Mis preferencias ──────────────────────────────────────────────────────
#
# Fijar un ajuste exige `tenant:write`, y con razón: son las palancas de la
# instalación. Pero eso dejaba SIN SITIO a la preferencia de cada persona —su
# idioma, su formato de fecha, la densidad con la que quiere ver las listas—,
# que son ajustes declarados hasta el ámbito de usuario y que nadie salvo un
# administrador podía tocar. En la práctica no las tocaba nadie: un comercial no
# va a abrir un ticket para que le cambien el formato de fecha.
#
# De ahí estas dos rutas. Son estrechas a propósito: sólo las claves que la
# declaración marca como personales, y siempre en el ámbito de quien llama.

router_preferencias = APIRouter(prefix="/mis-preferencias", tags=["ajustes"])


@router_preferencias.get(
    "",
    response_model=dict,
    summary="Mis preferencias, con su valor efectivo",
    description=(
        "Las preferencias que cada persona puede cambiarse, con el valor que "
        "le aplica **y de dónde sale**: suyo, de su unidad, de su empresa o el "
        "del despliegue. Sin la procedencia, quien ve un valor que no ha puesto "
        "no sabe si es un defecto o algo que le han fijado."
    ),
)
def mis_preferencias(db: DbDep, principal: AutenticadoDep) -> Any:
    efectivos = rt.valores_efectivos(db)
    return {
        c.clave: {
            **efectivos.get(c.clave, {}),
            "descripcion": c.descripcion,
            "tipo": c.tipo,
            "opciones": list(c.opciones),
        }
        for c in preferencias_personales()
    }


@router_preferencias.put(
    "/{clave}",
    response_model=dict,
    summary="Cambiar una preferencia mía",
    description=(
        "Fija el valor **en el ámbito de quien llama**, nunca en otro. No exige "
        "permiso de administración: es su propia preferencia."
    ),
)
def fijar_mi_preferencia(
    clave: str,
    datos: FijarMiPreferencia,
    db: DbDep,
    principal: AutenticadoDep,
) -> Any:
    # Primero la puerta, y con el porqué dentro del mensaje: «no se puede fijar»
    # a secas manda a mirar los permisos cuando el problema es que esa clave no
    # es de nadie en particular.
    if not es_preferencia_personal(clave):
        raise ErrorValidacion(
            f"«{clave}» no es una preferencia personal: la fija quien administra "
            "la instalación, desde la consola de ajustes.",
            error_code="ajustes.no_es_personal",
        )
    # Sin identidad no hay ámbito donde guardarlo. Pasa con un token de servicio
    # o de automatización: no son personas y no tienen preferencias.
    if principal.id is None:
        raise ErrorValidacion(
            "Esta llamada no la hace una persona, así que no tiene preferencias "
            "propias que fijar.",
            error_code="ajustes.sin_usuario",
        )
    # **El ámbito lo pone el servidor.** Viene de quien llama y no del cuerpo:
    # si el cuerpo pudiera decirlo, cualquiera cambiaría el ajuste de todo el
    # tenant desde una cuenta normal.
    valor = rt.fijar(
        db,
        clave,
        datos.valor,
        ambito="usuario",
        ambito_id=str(principal.id),
        por=principal.id,
    )
    return {"clave": clave, "valor": valor, "ambito": "usuario"}


# ── Consumo y cuotas ──────────────────────────────────────────────────────


@router.get(
    "/{tenant_id}/consumo",
    response_model=list[ConsumoOut],
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Consumo del periodo frente a los topes",
    description=(
        "Alimenta el panel de consumo del tenant y los avisos de aproximación " "al límite."
    ),
)
def consumo(tenant_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    """El consumo **medido**, no el apuntado en una tabla que nadie escribía.

    Esto leía una tabla de contadores (`consumos`) que sólo escribía una función
    sin llamantes, así que el panel enseñaba **cero de todo, siempre** — con los
    topes bien puestos al lado, que es lo que lo hacía creíble. «Has usado 0 de
    5.000 correos» el mes que mandaste cuatro mil.

    Ahora sale de los medidores registrados, que es de donde sale la cuota que de
    verdad corta: se cuentan las filas. Un contador aparte se desincroniza el
    primer día que algo se borra por otra vía —una purga, una fusión, una baja— y
    entonces el cliente ve una cuota agotada que no se corresponde con lo que
    tiene.
    """
    # Sólo el de la propia empresa (o la plataforma), y 404 para el ajeno como
    # en la ficha: hasta el 09-11-2026 esta ruta no pedía permiso ni miraba de
    # quién era el tenant, así que cualquiera con sesión leía el consumo de
    # cualquier empresa sabiendo su identificador.
    if not principal.es_admin_plataforma and principal.tenant_id != tenant_id:
        raise NoEncontrado("El tenant no existe", error_code="tenant.no_encontrado")
    from crmcore.consumo import medido_aqui

    # **De todos los módulos, no sólo de éste.** Cada servicio guarda y cuenta
    # lo suyo —y la cuota corta por módulo—, así que lo que medía tenancy en
    # su propio proceso eran sus tablas: «0 registros» con miles de cuentas en
    # party. Se pregunta a cada uno por su `/estado/consumo`, con la identidad
    # del tenant que se mira, y cada fila dice de qué módulo es.
    por_modulo: dict[str, list[dict[str, Any]] | str] = {"tenancy": medido_aqui(db, tenant_id)}
    por_modulo.update(_consumo_de_los_demas(tenant_id, principal.id))

    salida: list[ConsumoOut] = []
    for modulo, filas in sorted(por_modulo.items()):
        if isinstance(filas, str):
            # NO es un cero: «no se ha podido leer» es verdad, un cero no.
            salida.append(
                ConsumoOut(
                    metrica="*",
                    modulo=modulo,
                    periodo="actual",
                    consumido=0,
                    limite=0,
                    pct=0.0,
                    en_aviso=False,
                    medido=False,
                    porque=filas,
                )
            )
            continue
        for fila in filas:
            if not fila.get("legible"):
                # Un medidor roto se dice en su fila y no tumba el panel.
                salida.append(
                    ConsumoOut(
                        metrica=fila["metrica"],
                        modulo=modulo,
                        periodo="actual",
                        consumido=0,
                        limite=0,
                        pct=0.0,
                        en_aviso=False,
                        medido=False,
                        porque=str(fila.get("porque") or ""),
                    )
                )
                continue
            salida.append(
                ConsumoOut(
                    metrica=fila["metrica"],
                    modulo=modulo,
                    periodo=str(fila.get("periodo") or "actual"),
                    consumido=int(fila["consumido"]),
                    limite=int(fila["limite"]),
                    pct=float(fila.get("pct") or 0.0),
                    en_aviso=bool(fila.get("en_aviso")),
                )
            )
    return sorted(salida, key=lambda f: (f.metrica, f.modulo))


def _consumo_de_los_demas(tenant_id: UUID, principal_id: Any) -> dict[str, Any]:
    """Lo que mide cada uno de los otros módulos, o por qué no se ha leído.

    En paralelo y con el plazo de las llamadas internas: en serie, trece
    servicios con su plazo cada uno serían minutos justo cuando algo va mal. El
    texto del error no sale —lleva host y puerto, y esto lo ve el cliente—.
    """
    from concurrent.futures import ThreadPoolExecutor

    import httpx
    from crmcore.config import get_settings
    from crmcore.http.interno import cabeceras_de
    from crmcore.rutas_de_api import cargar_destinos

    s = get_settings()
    destinos = {
        n: d
        for n, d in cargar_destinos(s.rutas_servicios).items()
        if n not in ("tenancy", "gateway")
    }
    cabeceras = cabeceras_de(tenant_id=tenant_id, principal_id=principal_id)

    def _preguntar(nombre: str) -> tuple[str, Any]:
        try:
            r = httpx.get(
                f"{destinos[nombre].url_base}/api/v1/estado/consumo",
                headers=cabeceras,
                timeout=s.http_interno_timeout_s,
            )
            if r.status_code != 200:
                return (
                    nombre,
                    f"El módulo contestó {r.status_code}: su consumo no se ha podido leer",
                )
            return nombre, list(r.json().get("metricas") or [])
        except Exception:  # noqa: BLE001 — un módulo caído es información, no un error
            return nombre, "El módulo no responde: su consumo no se ha podido leer"

    if not destinos:
        return {}
    with ThreadPoolExecutor(max_workers=len(destinos)) as hilos:
        return dict(hilos.map(_preguntar, sorted(destinos)))


# ── Resolución interna ────────────────────────────────────────────────────

router_interno = APIRouter(prefix="/interno/tenants", tags=["interno"])


@router_interno.get(
    "/por-slug/{slug}",
    response_model=dict,
    dependencies=[Depends(exige_firma_interna)],
    include_in_schema=False,
    summary="Traducir el slug de una organización a su identificador",
)
def resolver_slug(slug: str) -> Any:
    """Slug → identificador, solo entre servicios.

    Existe porque quien inicia sesión escribe «demo», no un UUID, y el servicio
    de identidad no puede leer la tabla de tenants: los permisos de Postgres se
    lo impiden, que es el aislamiento funcionando. Sin este extremo la pantalla
    de entrada pedía algo que nadie tiene a mano y la respuesta era «indica el
    identificador del tenant», es decir, la aplicación no se podía usar.

    **No está en el esquema público ni la enruta el gateway**: la lista de
    prefijos del gateway es una lista blanca y `interno` no está en ella. Si
    estuviera, cualquiera podría ir probando nombres para averiguar qué
    organizaciones existen aquí.
    """
    # Sesión de sistema porque la pregunta cruza tenants por definición: quien
    # la hace todavía no está en ninguno. `sistema=True` hay que escribirlo, y
    # por eso se ve aquí en vez de colarse por descuido.
    from crmcore.db.session import sesion

    with sesion(sistema=True) as db:
        tenant = db.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one_or_none()
        datos = (
            None
            if tenant is None
            else {
                "tenant_id": str(tenant.id),
                "slug": tenant.slug,
                "nombre": tenant.nombre,
                "estado": tenant.estado,
            }
        )
    if datos is None or datos["estado"] != "activo":
        # Un tenant suspendido se responde como inexistente: distinguirlos
        # diría desde fuera que la organización existe pero está de baja, y eso
        # ya es información sobre un cliente.
        raise NoEncontrado("El tenant no existe", error_code="tenant.no_encontrado")
    return {k: v for k, v in datos.items() if k != "estado"}


@router.get(
    "/{tenant_id}/puede-operar",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Si este tenant puede leer y escribir ahora, con el corte aplicado",
    description=(
        "La diferencia con `/operatividad` —que es la interna del gateway— es "
        "que **ésta corta**: devuelve 409 con el motivo si el tenant está "
        "suspendido o en solo lectura, en vez de un estado para que lo mire "
        "quien llame.\n\n"
        "Las dos salen de la misma regla, que vive en `tenancy` y en un solo "
        "sitio. Lo que cambia es quién decide qué hacer con ella: el gateway la "
        "cachea y la aplica en cada petición; aquí se pregunta cuando se tiene la "
        "sesión delante y se quiere el corte con su mensaje.\n\n"
        "El estado `solo_lectura` es la razón de ser de esto: permite una ventana "
        "de mantenimiento **sin corte** —quien consulta sigue trabajando y quien "
        "escribe recibe un 409 que dice qué pasa, no una pantalla que no "
        "responde—."
    ),
)
def puede_operar(
    tenant_id: UUID,
    db: DbDep,
    principal: AutenticadoDep,
    escritura: bool = Query(
        False, description="Si lo que se va a hacer escribe. Lectura y escritura se separan"
    ),
) -> Any:
    tenant = svc.exigir_operativo(db, tenant_id, escritura=escritura)
    return {
        "tenant_id": str(tenant.id),
        "estado": tenant.estado,
        "puede_leer": tenant.puede_leer,
        "puede_escribir": tenant.puede_escribir,
        "motivo": tenant.motivo_estado or "",
    }


@router_interno.get(
    "/{tenant_id}/operatividad",
    response_model=dict,
    dependencies=[Depends(exige_firma_interna)],
    include_in_schema=False,
    summary="Si este tenant puede leer y escribir ahora mismo",
)
def operatividad_de(tenant_id: UUID) -> Any:
    """Lo que el gateway necesita saber antes de dejar pasar una petición.

    Existe porque **la suspensión no se aplicaba en ninguna parte**. La
    comprobación estaba escrita en `tenancy` desde el principio y no la llamaba
    nadie, aunque su documentación dijera que «lo llama el gateway en cada
    petición». El 28-09-2026 se montó el caso: un tenant suspendido creó una
    cuenta —201— y uno en solo lectura también.

    La regla de qué estado permite qué se queda **aquí**, que es de quien es el
    tenant; esto sólo la publica para que el único sitio por el que pasa todo
    pueda aplicarla. El gateway no puede leer esta tabla —los permisos de
    Postgres se lo impiden, que es el aislamiento funcionando—.

    Sesión de sistema porque la pregunta es sobre un tenant y la hace un
    servicio, no alguien dentro de él.
    """
    from crmcore.db.session import sesion

    with sesion(sistema=True) as db:
        # Las capacidades del plan viajan con la operatividad y no en otra
        # llamada: el gateway las necesita en la misma petición y con la misma
        # caché, y pedirlas aparte sería doblar el tráfico interno para el mismo
        # dato del mismo tenant.
        # Y las reglas de acceso contextual (CRM-00.05.01.09), por el mismo
        # viaje: el gateway las necesita en la misma petición y con la misma
        # caché. Pedirlas aparte sería doblar el tráfico interno por el mismo
        # dato del mismo tenant — y el módulo que las evalúa llevaba desde que
        # se escribió sin que lo importara nadie, así que no se comprobaban.
        from crmcore.runtime import settings as rt

        return {
            **svc.operatividad(db, tenant_id),
            "capacidades": svc.capacidades_de(db, tenant_id),
            "reglas_contextuales": rt.efectivo("reglas_contextuales", db) or [],
        }


from services.tenancy.api_suite import ROUTERS_SUITE  # noqa: E402

ROUTERS = [
    router,
    *ROUTERS_MARCA,
    router_interno,
    router_planes,
    router_flags,
    router_ajustes,
    router_preferencias,
    *ROUTERS_CATALOGOS,
    *ROUTERS_BYOK,
    *ROUTERS_GRC,
    *ROUTERS_GRC_SERIE,
    *ROUTERS_TCSEC,
    *ROUTERS_COMPROMISOS,
    *ROUTERS_SUITE,
    *ROUTERS_AISLAMIENTO,
    *ROUTERS_SANDBOXES,
    *ROUTERS_CICLO_VIDA,
    *ROUTERS_ALTA,
    *ROUTERS_JERARQUIA,
]


# Estas rutas aceptan además los filtros comunes, cuyos nombres son columnas
# del modelo y cambian con él: no se pueden declarar. Los valida
# `aplicar_filtros_de_la_url`, que rechaza lo que no es columna o lo que este
# principal no ve en claro. Las dos mitades van juntas: con el filtro y sin la
# marca, la ruta contesta 422 a sus propios filtros.
admite_parametros_abiertos(
    listar_tenants, "llama a `aplicar_filtros_de_la_url`, que valida los filtros por columna"
)
admite_parametros_abiertos(
    listar_planes, "llama a `aplicar_filtros_de_la_url`, que valida los filtros por columna"
)
