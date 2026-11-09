"""API de la transcripción de reuniones, las variantes de copy generadas y el
dictado del asistente de voz (CRM-01.02.01.05, CRM-01.02.01.06,
CRM-02.04.01.04, CRM-04.02.01.08).

Lo de aquí sí llama al proveedor y al modelo y sí guarda; las rutas de
`api_modelos` con los mismos prefijos siguen siendo las reglas puras que esto
usa por dentro.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field

from services.intelligence import reuniones as reu
from services.intelligence import variantes_copy as vc

router_reuniones = APIRouter(prefix="/transcripciones", tags=["transcripción y compromisos"])
router_variantes_ia = APIRouter(prefix="/variantes", tags=["variantes de texto"])
router_dictado = APIRouter(prefix="/voz", tags=["voz y asistentes"])


class InstalarPlantillaIn(BaseModel):
    plantilla: str = Field(..., description="deepgram · google_stt")
    url_base: str = Field(
        "",
        description="Otra dirección con la misma forma de petición: un proxy, un compatible",
    )


class DecidirCompromisoIn(BaseModel):
    confirmar: bool
    asunto: str = Field("", max_length=300, description="Corregido; vacío deja el propuesto")
    vence_at: str = Field("", description="ISO 8601")


class GenerarVariantesIn(BaseModel):
    base: str = Field(..., min_length=1, max_length=10_000)
    objetivo: str = Field("", max_length=1_000)
    canal: str = "email"
    cuantas: int = Field(3, ge=1, le=50)
    objeto: str = Field("", max_length=60)
    objeto_ref: str = Field("", max_length=200)
    idioma: str = Field("es", max_length=10)


class DecidirVarianteIn(BaseModel):
    aprobar: bool
    texto_final: str = Field("", max_length=10_000)
    motivo: str = Field("", max_length=2_000)


@router_reuniones.get(
    "/proveedor",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Qué proveedor transcribe en esta empresa, o por qué ninguno",
)
def proveedor_transcripcion(db: DbDep, principal: AutenticadoDep) -> Any:
    return reu.proveedor(db)


@router_reuniones.post(
    "/proveedor",
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Instalar una plantilla de proveedor de transcripción",
    description=(
        "Da de alta en Integraciones la conexión y su operación —URL, "
        "autenticación, forma de la petición y de la respuesta— y la deja en "
        "uso. La credencial se pone después en la ficha de la conexión: aquí no "
        "viaja ningún secreto."
    ),
)
def instalar_proveedor(cuerpo: InstalarPlantillaIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    return reu.instalar_plantilla(
        uow, clave=cuerpo.plantilla, principal=principal, url_base=cuerpo.url_base
    )


@router_reuniones.post(
    "/reuniones/transcribir",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Transcribir, resumir y proponer compromisos de una llamada o reunión",
    description=(
        "Una de tres fuentes: el **fichero** de audio (se guarda como adjunto "
        "del registro), un **enlace** a la grabación o el **texto** ya "
        "transcrito. Primero se comprueba la base para grabar; después se "
        "transcribe con el proveedor configurado, se resume con el modelo y se "
        "guarda con los compromisos como propuestas. **No se crea ninguna "
        "tarea**: eso lo hace una persona al confirmar."
    ),
)
async def procesar_reunion(
    uow: UowDep,
    principal: AutenticadoDep,
    objeto: str = Form(..., max_length=60),
    objeto_id: UUID = Form(...),
    base_para_grabar: str = Form(...),
    participantes_avisados: bool = Form(False),
    participantes_externos: bool = Form(True),
    idioma: str = Form("es", max_length=10),
    enlace: str = Form("", max_length=2_000),
    texto: str = Form("", max_length=500_000),
    guardar_audio: bool = Form(True),
    fichero: UploadFile | None = File(None),
) -> Any:
    audio = await fichero.read() if fichero is not None else None
    return reu.procesar(
        uow,
        principal=principal,
        objeto=objeto,
        objeto_id=objeto_id,
        base_para_grabar=base_para_grabar,
        participantes_avisados=participantes_avisados,
        participantes_externos=participantes_externos,
        idioma=idioma,
        audio=audio or None,
        nombre_fichero=(fichero.filename or "") if fichero is not None else "",
        mime=(fichero.content_type or "") if fichero is not None else "",
        enlace=enlace,
        texto=texto,
        guardar_audio=guardar_audio,
    )


@router_reuniones.get(
    "/reuniones",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Las transcripciones de un registro, con su resumen y compromisos",
)
def transcripciones_de(
    db: DbDep,
    principal: AutenticadoDep,
    objeto: str = Query(..., max_length=60),
    objeto_id: UUID = Query(...),
) -> Any:
    return {"items": reu.listar(db, principal.tenant_id, objeto=objeto, objeto_id=objeto_id)}


@router_reuniones.post(
    "/reuniones/{transcripcion_id}/compromisos/{n}",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Confirmar (y crear la tarea) o descartar un compromiso",
    description=(
        "Al confirmar se crea la tarea en el CRM **con tu identidad**, colgada del "
        "mismo registro que la reunión. Se guarda lo que propuso el modelo y lo "
        "que quedó: de las correcciones se aprende si la extracción sirve."
    ),
)
def decidir_compromiso(
    transcripcion_id: UUID,
    n: int,
    cuerpo: DecidirCompromisoIn,
    uow: UowDep,
    principal: AutenticadoDep,
) -> Any:
    return reu.decidir_compromiso(
        uow,
        transcripcion_id=transcripcion_id,
        n=n,
        principal=principal,
        confirmar=cuerpo.confirmar,
        asunto=cuerpo.asunto,
        vence_at=cuerpo.vence_at,
    )


@router_variantes_ia.post(
    "/generar",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Generar variantes de un texto con el modelo, como propuestas",
)
def generar_variantes(cuerpo: GenerarVariantesIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    return vc.generar(uow, principal=principal, **cuerpo.model_dump())


@router_variantes_ia.get(
    "/generadas",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Las variantes generadas para lo que se está escribiendo",
)
def variantes_generadas(
    db: DbDep,
    principal: AutenticadoDep,
    objeto: str = Query(..., max_length=60),
    objeto_ref: str = Query(..., max_length=200),
) -> Any:
    return {"items": vc.listar(db, principal.tenant_id, objeto=objeto, objeto_ref=objeto_ref)}


@router_variantes_ia.post(
    "/generadas/{variante_copy_id}/decidir",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Aprobar (se puede reescribir) o rechazar una variante",
)
def decidir_variante(
    variante_copy_id: UUID, cuerpo: DecidirVarianteIn, uow: UowDep, principal: AutenticadoDep
) -> Any:
    return vc.decidir(
        uow,
        variante_id=variante_copy_id,
        principal=principal,
        aprobar=cuerpo.aprobar,
        texto_final=cuerpo.texto_final,
        motivo=cuerpo.motivo,
    )


@router_variantes_ia.post(
    "/generadas/{variante_copy_id}/ganadora",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Elegir la ganadora de su lote",
)
def ganadora_variante(variante_copy_id: UUID, uow: UowDep, principal: AutenticadoDep) -> Any:
    return vc.elegir_ganadora(uow, variante_id=variante_copy_id, principal=principal)


@router_dictado.post(
    "/dictado",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Audio a texto para el asistente de voz (sin guardar nada)",
    description=(
        "Para los navegadores sin reconocimiento de voz: el audio va al mismo "
        "proveedor de transcripción y vuelve el texto. No se guarda la voz."
    ),
)
async def dictado(
    db: DbDep,
    principal: AutenticadoDep,
    fichero: UploadFile = File(...),
    idioma: str = Form("es", max_length=10),
) -> Any:
    audio = await fichero.read()
    return reu.dictar(
        db,
        principal=principal,
        audio=audio,
        idioma=idioma,
        nombre=fichero.filename or "",
        mime=fichero.content_type or "",
    )


ROUTERS_REUNIONES = [router_reuniones, router_variantes_ia, router_dictado]
