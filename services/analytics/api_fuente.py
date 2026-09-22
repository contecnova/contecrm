"""API del registro de fuente, las preguntas guardadas y el diagnóstico
(CRM-05.01.04.04, CRM-05.01.04.05, CRM-05.01.04.06, CRM-05.01.04.08)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from services.analytics import fuente as fte

router = APIRouter(prefix="/explotacion", tags=["explotación"])


@router.post(
    "/registrar-fuente",
    dependencies=[Depends(exige_permiso("analitica:administrar"))],
    summary="Publicar la descripción del CRM en contecintelligence",
    description=(
        "Va el **esquema descrito**, nunca el dato: ni una fila. Quien pregunte "
        "recibe los datos con su propio token y con sus propios permisos.\n\n"
        "No se reenvía si no ha cambiado nada —lo decide una huella—: un registro "
        "que se reenvía por reloj gasta en cada tenant sin que nadie haya tocado "
        "un campo, y lo que importa (que el campo nuevo esté) no depende del "
        "reloj sino del cambio."
    ),
)
def registrar_fuente(uow: UowDep, principal: AutenticadoDep, forzar: bool = False) -> Any:
    from sqlalchemy import select

    from services.analytics.modelos import OrganizacionExterna

    organizacion = uow.db.execute(
        select(OrganizacionExterna).where(OrganizacionExterna.tenant_id == principal.tenant_id)
    ).scalar_one_or_none()
    if organizacion is None:
        from crmcore.errors import Conflicto

        raise Conflicto(
            "Este tenant no tiene organización asignada en contecintelligence, "
            "así que no hay dónde registrar la fuente.",
            error_code="analytics.sin_organizacion",
        )
    return fte.registrar_fuente(
        uow, principal.tenant_id, organizacion=organizacion.organizacion, forzar=forzar
    )


@router.get(
    "/descripcion",
    dependencies=[Depends(exige_permiso("analitica:consultar"))],
    summary="Cómo se describe este CRM para poder preguntarle",
    description=(
        "Es lo que se manda al registrar, sin mandarlo. Sirve para ver qué campos "
        "de la implantación están disponibles como dimensión o como métrica antes "
        "de preguntar, y para entender por qué una pregunta no encuentra algo."
    ),
)
def descripcion(db: DbDep, principal: AutenticadoDep) -> Any:
    return fte.describir(db, principal.tenant_id)


@router.get(
    "/diagnostico",
    dependencies=[Depends(exige_permiso("analitica:consultar"))],
    summary="Qué funciona y qué no ahora mismo",
    description=(
        "«Servicio no disponible» deja a quien lo lee sin saber si su CRM está "
        "roto. No lo está: lo que no funciona es **preguntar**, y el CRM entero "
        "sigue operativo. Esta llamada lo dice por su nombre, con la lista de lo "
        "que sí sigue funcionando."
    ),
)
def diagnostico(db: DbDep, principal: AutenticadoDep) -> Any:
    return fte.diagnostico(db, principal.tenant_id)


class GuardarPregunta(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    titulo: str = Field(..., min_length=1, max_length=200)
    pregunta: str = Field(..., min_length=1)
    publicada: bool = Field(
        False,
        description=(
            "Nace sin publicar: una pregunta a medio afinar que aparece en la "
            "lista de todos se usa como si estuviera bien, y su autor ni se entera"
        ),
    )
    roles: list[str] = Field(default_factory=list)


@router.post(
    "/preguntas",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("analitica:consultar"))],
    summary="Guardar una pregunta",
)
def guardar(datos: GuardarPregunta, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = fte.guardar_pregunta(uow, autor_id=principal.id, **datos.model_dump())
    return {"id": str(fila.id), "clave": fila.clave}


@router.get(
    "/preguntas",
    dependencies=[Depends(exige_permiso("analitica:consultar"))],
    summary="Las preguntas que puedo ver: las publicadas y las mías",
)
def listar(db: DbDep, principal: AutenticadoDep) -> Any:
    return fte.preguntas_de(
        db,
        principal.tenant_id,
        usuario_id=principal.id,
        roles=frozenset(principal.roles or []),
    )


class PublicarComoInforme(BaseModel):
    definicion: dict[str, Any] = Field(
        ...,
        description=(
            "La definición estructurada del informe. Se pide estructurada y no el "
            "texto de la pregunta: una pregunta en lenguaje natural puede dar dos "
            "consultas distintas en dos días —el modelo cambia—, y un informe "
            "programado que cambia solo de significado es peor que no tenerlo"
        ),
        examples=[
            {
                "objeto": "oportunidad",
                "tipo": "agrupado",
                "agrupaciones": [{"campo": "cerrada_el", "periodo": "mes"}],
                "metricas": [{"campo": "importe", "agregado": "suma", "como": "total"}],
            }
        ],
    )


@router.post(
    "/preguntas/{pregunta_id}/publicar",
    dependencies=[Depends(exige_permiso("informe:write"))],
    summary="Convertir la pregunta en un informe del tenant",
    description=(
        "Cierra el círculo: se pregunta en lenguaje natural hasta dar con la "
        "respuesta buena, y entonces esa respuesta **se congela como informe**, "
        "con su programación y su distribución. Sin este paso, lo que funciona "
        "vive en la cabeza de quien supo preguntar, y cuando se va se va con él."
    ),
)
def publicar(pregunta_id: UUID, datos: PublicarComoInforme, uow: UowDep) -> Any:
    return fte.publicar_como_informe(uow, pregunta_id, definicion=datos.definicion)


ROUTERS_FUENTE = [router]
