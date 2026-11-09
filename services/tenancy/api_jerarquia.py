"""Rutas de la jerarquía de empresas (CRM-00.01.03.07) y del consumo a
facturación (CRM-00.01.06.07). La lógica, en `jerarquia.py` y `facturacion.py`."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from crmcore.errors import NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, PlataformaDep, exige_permiso
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from services.tenancy import facturacion, jerarquia

router_jerarquia = APIRouter(prefix="/tenants", tags=["tenants"])
router_facturacion = APIRouter(prefix="/facturacion", tags=["consumo"])


class ColgarIn(BaseModel):
    tenant_padre_id: UUID | None = Field(
        None, description="La empresa de la que cuelga; vacío, ninguna"
    )
    relacion: Literal["matriz_filial", "franquicia", "holding"] | None = Field(
        None, description="Obligatoria si hay padre"
    )


class CompartirIn(BaseModel):
    comparte: list[Literal["consumo", "indicadores"]] = Field(
        default_factory=list,
        description="Lo que esta empresa deja ver a su matriz. Vacío, nada",
    )


class TomarCorteIn(BaseModel):
    enviar: bool = Field(False, description="Mandarlo además al sistema de facturación")


def _propia_o_plataforma(principal: Any, tenant_id: UUID) -> None:
    # 404 y no 403, como en la ficha: un 403 confirmaría que el id existe.
    if not principal.es_admin_plataforma and principal.tenant_id != tenant_id:
        raise NoEncontrado("El tenant no existe", error_code="tenant.no_encontrado")


@router_jerarquia.get(
    "/{tenant_id}/jerarquia",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="El árbol de empresas de este tenant",
    description=(
        "Su línea hacia arriba y lo que cuelga de él, con la relación de cada "
        "una y lo que cada hija comparte con su matriz. Las hermanas no salen: "
        "compartir matriz no da derecho a saber de la otra filial."
    ),
)
def ver_jerarquia(tenant_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    _propia_o_plataforma(principal, tenant_id)
    return jerarquia.arbol(db, tenant_id, es_plataforma=principal.es_admin_plataforma)


@router_jerarquia.put(
    "/{tenant_id}/jerarquia",
    response_model=dict,
    summary="Colgar esta empresa de otra, con su relación",
    description=(
        "Matriz–filial, franquicia u holding. Sólo la plataforma. Un cambio de "
        "padre BORRA lo que la hija compartía: lo autorizó para aquella matriz."
    ),
)
def colgar(tenant_id: UUID, datos: ColgarIn, db: DbDep, _: PlataformaDep) -> Any:
    return jerarquia.colgar(db, tenant_id, padre_id=datos.tenant_padre_id, relacion=datos.relacion)


@router_jerarquia.put(
    "/{tenant_id}/jerarquia/comparticion",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Qué deja ver esta empresa a su matriz",
    description=(
        "Lo decide la propia empresa y sólo ella —ni la matriz ni la plataforma "
        "pueden concederlo en su nombre—. Sólo agregados: el consumo y los "
        "indicadores configurados, nunca registros."
    ),
)
def compartir(tenant_id: UUID, datos: CompartirIn, db: DbDep, principal: AutenticadoDep) -> Any:
    jerarquia.exigir_propia(principal, tenant_id)
    return jerarquia.compartir(db, tenant_id, que=list(datos.comparte), por=principal.id)


@router_jerarquia.get(
    "/{tenant_id}/jerarquia/agregado",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Lo que la matriz ve de sus empresas hijas",
    description=(
        "De cada empresa que cuelga de esta, sólo lo que ELLA ha compartido: su "
        "consumo y los indicadores configurados (`jerarquia_indicadores`), "
        "sumados. Lo no compartido sale como tal, no como cero."
    ),
)
def agregado(tenant_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    _propia_o_plataforma(principal, tenant_id)
    return jerarquia.agregado(db, tenant_id)


# ── Consumo a facturación ─────────────────────────────────────────────────


@router_facturacion.get(
    "/destino",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="A dónde se manda el consumo y cómo",
    description=(
        "Si hay sistema de facturación configurado, en qué formato y si se "
        "exporta solo. La URL no se devuelve entera: sólo su máquina."
    ),
)
def destino(db: DbDep, _: AutenticadoDep) -> Any:
    from urllib.parse import urlparse

    from crmcore.runtime import settings as rt

    url = str(rt.efectivo("facturacion_destino_url", db) or "")
    return {
        "configurado": bool(url),
        "maquina": (urlparse(url).hostname or "") if url else "",
        "formato": rt.efectivo("facturacion_formato_envio", db),
        "periodica": bool(rt.efectivo("facturacion_exportar_periodicamente", db)),
        "max_intentos": rt.efectivo("facturacion_max_intentos", db),
        "columnas": list(facturacion.COLUMNAS),
    }


@router_facturacion.get(
    "/cortes",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Cortes de consumo tomados, con su estado de envío",
)
def cortes(db: DbDep, principal: AutenticadoDep, limite: int = Query(50, ge=1, le=500)) -> Any:
    return {"cortes": facturacion.listar(db, principal.tenant_id, limite=limite)}


@router_facturacion.post(
    "/cortes",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Tomar ahora el corte de consumo del periodo",
    description=(
        "Pregunta a cada módulo cuánto lleva consumido este tenant y lo guarda "
        "en formato neutro (periodo, módulo, métrica, cantidad, unidad, tope). "
        "Un módulo que no contesta queda en `no_leidos` y el corte sale "
        "incompleto, nunca con un cero inventado. Con `enviar`, se manda."
    ),
)
def tomar(datos: TomarCorteIn, db: DbDep, principal: AutenticadoDep) -> Any:
    c = facturacion.tomar_corte(db, principal.tenant_id, origen="manual", pedido_por=principal.id)
    if datos.enviar:
        return facturacion.enviar(db, c)
    return facturacion.a_dict(c)


@router_facturacion.get(
    "/cortes/{corte_id}/exportar",
    response_model=dict,
    summary="Exportar un corte de consumo en CSV o JSON",
    description=(
        "Devuelve el nombre del fichero y su contenido en el formato neutro "
        "(periodo, tenant, módulo, métrica, cantidad, unidad, tope), igual que "
        "el informe TCSEC: la pantalla lo guarda como fichero."
    ),
    dependencies=[Depends(exige_permiso("tenant:read"))],
)
def exportar(
    corte_id: UUID,
    db: DbDep,
    principal: AutenticadoDep,
    formato: Literal["csv", "json"] = Query("csv"),
) -> Any:
    c = facturacion.corte(db, principal.tenant_id, corte_id)
    contenido, tipo = facturacion.descargar(c, formato)
    return {"fichero": f"consumo-{c.periodo}.{formato}", "tipo": tipo, "contenido": contenido}


@router_facturacion.post(
    "/cortes/{corte_id}/enviar",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:write"))],
    summary="Mandar (o reenviar) un corte al sistema de facturación",
)
def enviar(corte_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    c = facturacion.corte(db, principal.tenant_id, corte_id)
    return facturacion.enviar(db, c)


ROUTERS_JERARQUIA = [router_jerarquia, router_facturacion]
