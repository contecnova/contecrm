"""API de componentes, filtros, alertas y embebido (CRM-05.01.02)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, Header, status
from pydantic import BaseModel, Field

from services.analytics import cuadros as cua

router = APIRouter(prefix="/cuadros-mando", tags=["informes"])


@router.get(
    "/componentes",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="Los tipos de componente que existen, con lo que necesita cada uno",
    description=(
        "Se publica para que la pantalla de montaje ofrezca lo que existe en vez "
        "de una lista escrita a mano en el front: dos listas que tienen que "
        "coincidir acaban no coincidiendo, y la que se queda corta es siempre la "
        "del front."
    ),
)
def componentes() -> Any:
    return cua.catalogo_componentes()


class FiltrosGlobales(BaseModel):
    componentes: list[dict[str, Any]]
    filtros: list[dict[str, Any]] = Field(default_factory=list)


@router.post(
    "/aplicar-filtros",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="Pasar los filtros del cuadro a sus componentes",
    description=(
        "El filtro es **del cuadro**, no de cada componente: si cada uno llevara "
        "el suyo, cambiar el trimestre exigiría tocar ocho sitios y siempre "
        "quedaría uno sin cambiar — y nadie se daría cuenta, porque un número "
        "plausible no se cuestiona.\n\n"
        "Un componente puede declararse inmune (`ignora_filtros`) para los que "
        "enseñan contexto, como «total del año pasado». Se declara, no se adivina."
    ),
)
def aplicar_filtros(datos: FiltrosGlobales) -> Any:
    return {"componentes": cua.aplicar_filtros_globales(datos.componentes, datos.filtros)}


class Detalle(BaseModel):
    componente: dict[str, Any]
    punto: dict[str, Any] = Field(
        default_factory=dict, description="Los valores del punto pulsado: la barra, el sector"
    )
    filtros: list[dict[str, Any]] = Field(default_factory=list)


@router.post(
    "/detalle",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="A qué lista lleva pulsar un punto",
    description=(
        "Baja **hasta el registro**, no hasta otra agregación. Un cuadro del que "
        "no se puede bajar al detalle obliga a rehacer la consulta a mano en otra "
        "pantalla, y ahí ya no coinciden los números — y entonces se deja de creer "
        "al cuadro.\n\n"
        "Lleva los filtros del cuadro **y el del punto**: sin lo segundo, pulsar "
        "en la barra de marzo llevaría a la lista del año entero."
    ),
)
def detalle(datos: Detalle) -> Any:
    return cua.enlace_al_detalle(datos.componente, datos.punto, datos.filtros)


class CrearAlerta(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=200)
    informe_id: UUID
    metrica: str = Field("filas", description="Una métrica del informe, o «filas»")
    comparacion: str = Field(
        "mayor", description="mayor · mayor_igual · menor · menor_igual · igual · cambia_mas_de"
    )
    umbral: Decimal = Decimal(0)
    histeresis: Decimal = Field(
        Decimal(0),
        description=(
            "Margen para volver al verde. Sin él, un indicador que baila alrededor "
            "del umbral manda cuarenta avisos en una tarde y al día siguiente la "
            "regla está desactivada"
        ),
    )
    silencio_horas: int = Field(12, ge=1, le=720)
    destinatarios: list[str] = Field(..., min_length=1)


@router.post(
    "/alertas",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("informe:write"))],
    summary="Avisar cuando una métrica cruza una línea",
)
def crear_alerta(datos: CrearAlerta, uow: UowDep) -> Any:
    fila = cua.crear_alerta(uow, **datos.model_dump())
    return {"id": str(fila.id), "nombre": fila.nombre, "estado": fila.estado}


@router.post(
    "/alertas/comprobar",
    dependencies=[Depends(exige_permiso("informe:write"))],
    summary="Ejecutar las alertas activas",
    description=(
        "Lo que no se ha podido medir sale aparte (`no_medibles`) y **no cuenta "
        "como verde**: dar por bueno lo que no se ha medido es la forma más "
        "silenciosa de perder una alerta."
    ),
)
def comprobar_alertas(uow: UowDep, principal: AutenticadoDep) -> Any:
    return cua.comprobar_alertas(uow, principal.tenant_id)


class CrearEmbebido(BaseModel):
    cuadro_id: UUID
    dominios: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Desde dónde se puede incrustar. Vacío NO significa «desde cualquier "
            "sitio»: significa que no se sirve, porque un cuadro embebible desde "
            "cualquier parte es un cuadro público"
        ),
        examples=[["intranet.cliente.com"]],
    )
    nombre: str = ""
    minutos_validez: int = Field(10, ge=1, le=1440)


@router.post(
    "/embebidos",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("informe:write"))],
    summary="Habilitar un cuadro para incrustarlo fuera",
    description=(
        "El secreto se devuelve **una sola vez**; en la base queda su hash.\n\n"
        "El enlace **actúa como una persona concreta** —quien lo crea— y se dice "
        "cuál: el embebido no autentica a quien está delante de la pantalla ajena, "
        "así que fijar a quién representa es lo que impide que un cuadro "
        "incrustado enseñe más de lo que ve quien lo montó."
    ),
)
def crear_embebido(datos: CrearEmbebido, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila, secreto = cua.crear_embebido(
        uow,
        cuadro_id=datos.cuadro_id,
        actua_como_id=principal.id,
        dominios=datos.dominios,
        nombre=datos.nombre,
        minutos_validez=datos.minutos_validez,
    )
    return {
        "id": str(fila.id),
        "secreto": secreto,
        "actua_como": str(fila.actua_como_id),
        "dominios": list(fila.dominios),
    }


@router.post(
    "/embebidos/{enlace_id}/revocar",
    dependencies=[Depends(exige_permiso("informe:write"))],
    summary="Revocar un enlace embebido",
    description="No se borra: su uso queda en el histórico, que es lo que permite auditarlo.",
)
def revocar(enlace_id: UUID, uow: UowDep) -> Any:
    return cua.revocar_embebido(uow, enlace_id)


class Suscribirse(BaseModel):
    cuadro_id: UUID
    periodicidad: str = Field("semanal", description="diaria · semanal · mensual")
    hora: int = Field(8, ge=0, le=23)


@router.post(
    "/suscripciones",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="Que el cuadro llegue solo",
    description=(
        "Uno se suscribe **a sí mismo**. Suscribir a otro convierte un cuadro en "
        "correo no deseado que el receptor no sabe cómo parar, y lo que hace es "
        "marcarlo como basura — y con él, todo lo que mande el CRM."
    ),
)
def suscribirse(datos: Suscribirse, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = cua.suscribirse(
        uow,
        cuadro_id=datos.cuadro_id,
        usuario_id=principal.id,
        periodicidad=datos.periodicidad,
        hora=datos.hora,
    )
    return {
        "id": str(fila.id),
        "proxima_at": fila.proxima_at.isoformat() if fila.proxima_at else None,
    }


@router.get(
    "/embebido",
    dependencies=[Depends(exige_permiso("informe:read"))],
    summary="Resolver un cuadro incrustado",
    description=(
        "Un secreto inexistente, desactivado o de otro dominio dan **el mismo "
        "error**: distinguirlos le diría a quien prueba si ese cuadro existe y "
        "desde dónde se sirve.\n\n"
        "La comprobación del dominio es por coincidencia exacta o de subdominio, "
        "nunca «contiene»: con «contiene», `micrm.com.ataque.net` pasaría por "
        "`micrm.com`."
    ),
)
def embebido(
    secreto: str,
    db: DbDep,
    principal: AutenticadoDep,
    origin: str = Header("", alias="Origin"),
) -> Any:
    fila = cua.resolver_embebido(db, principal.tenant_id, secreto, origen=origin)
    return {
        "cuadro_id": str(fila.cuadro_id),
        "actua_como": str(fila.actua_como_id),
        "usos": fila.usos,
    }


ROUTERS_CUADROS = [router]
