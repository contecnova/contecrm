"""API de modelos entrenados, transcripción, variantes y sugerencia en el caso
(CRM-02.01.01.08, CRM-02.01.02.02, CRM-02.01.02.06, CRM-01.02.01.05,
CRM-01.02.01.06, CRM-02.04.01.04, CRM-04.03.01.04).

Todo lo de aquí devuelve **el número y el porqué**, y nada crea nada por su
cuenta: lo que sale son propuestas que confirma una persona.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, exige_permiso
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from services.intelligence import caso_semantico as sem
from services.intelligence import entrenamiento as ent
from services.intelligence import transcripcion as trs
from services.intelligence import variantes as var

router_modelos = APIRouter(prefix="/modelos", tags=["modelos entrenados"])
router_transcripcion = APIRouter(prefix="/transcripciones", tags=["transcripción y compromisos"])
router_variantes = APIRouter(prefix="/variantes", tags=["variantes de texto"])
router_sugerencias = APIRouter(prefix="/sugerencias-caso", tags=["sugerencia en el caso"])


class EntrenarIn(BaseModel):
    casos: list[dict[str, Any]] = Field(default_factory=list)
    variables: list[str] = Field(default_factory=list)


class EvaluarModeloIn(BaseModel):
    predicciones: list[dict[str, Any]] = Field(default_factory=list)
    umbral: float = 0.5


class FactoresIn(BaseModel):
    contribuciones: dict[str, float] = Field(default_factory=dict)
    cuantos: int = 5


class SegmentoIn(BaseModel):
    candidatos: list[dict[str, Any]] = Field(default_factory=list)
    minimo_puntuacion: float = 0.5
    tope: int | None = None


class TranscribirIn(BaseModel):
    referencia: str
    texto: str
    confianza: float
    idioma: str = "es"
    minutos: int = 0
    hablantes: list[dict[str, Any]] = Field(default_factory=list)
    base_para_grabar: str
    participantes_avisados: bool = False
    participantes_externos: bool = True


class ExtraerIn(BaseModel):
    elementos: list[dict[str, Any]] = Field(default_factory=list)
    confianza_transcripcion: float


class VariantesIn(BaseModel):
    base: str
    textos: list[str] = Field(default_factory=list)
    canal: str = "email"


class AprobarIn(BaseModel):
    texto_propuesto: str
    texto_final: str


class SugerirIn(BaseModel):
    resultados: list[dict[str, Any]] = Field(default_factory=list)
    contexto_del_caso: dict[str, Any] = Field(default_factory=dict)


@router_modelos.post(
    "/se-puede-entrenar",
    dependencies=[Depends(exige_permiso("intelligence:read"))],
    summary="Si hay histórico suficiente, y qué sesgo trae el que hay",
    description=(
        "Un modelo entrenado con el histórico **aprende lo que hizo el equipo "
        "comercial, no lo que funciona**. Si durante tres años solo se llamó a "
        "las empresas grandes de Madrid, concluirá que esas convierten: tendrá "
        "razón en los datos y estará equivocado en el mundo.\n\n"
        "Con cuarenta casos y tres ganados no sale un modelo, sale una "
        "superstición con decimales — y decirlo antes es lo único que evita que "
        "alguien decida con ella durante un año.\n\n"
        "Se rechazan además las variables que no pueden entrar: sexo, edad, "
        "nacionalidad y el código postal como sustituto de todo lo anterior."
    ),
)
def se_puede_entrenar(cuerpo: EntrenarIn, principal: AutenticadoDep) -> Any:
    return ent.se_puede_entrenar(casos=cuerpo.casos, variables=cuerpo.variables)


@router_modelos.post(
    "/evaluar",
    dependencies=[Depends(exige_permiso("intelligence:read"))],
    summary="Qué tal acierta, comparado con no tener modelo",
    description=(
        "La comparación que nadie hace: si solo se gana el 15 %, decir «todos "
        "pierden» acierta el 85 % de las veces, y un modelo con un 86 % suena "
        "bien y no aporta nada — con ese número se justifica un proyecto "
        "entero.\n\n"
        "Se enseñan los **falsos negativos**, que son los que duelen: las "
        "oportunidades que el modelo descartó y se ganaron son las que nadie "
        "habría llamado."
    ),
)
def evaluar(cuerpo: EvaluarModeloIn, principal: AutenticadoDep) -> Any:
    return ent.evaluar_modelo(predicciones=cuerpo.predicciones, umbral=cuerpo.umbral)


@router_modelos.post(
    "/factores",
    dependencies=[Depends(exige_permiso("intelligence:read"))],
    summary="Por qué puntúa lo que puntúa",
    description=(
        "«Esto puntúa 78 porque han abierto tres presupuestos y porque llevan dos "
        "semanas sin contestar» es accionable. «Esto puntúa 78» no lo es, y "
        "además no se cree: el comercial estuvo en la reunión y el modelo no.\n\n"
        "Se enseñan también **los factores que restan**: un panel que solo cuenta "
        "lo que suma hace pensar que la puntuación es baja por falta de datos."
    ),
)
def factores(cuerpo: FactoresIn, principal: AutenticadoDep) -> Any:
    return ent.factores(contribuciones=cuerpo.contribuciones, cuantos=cuerpo.cuantos)


@router_modelos.post(
    "/segmento",
    dependencies=[Depends(exige_permiso("intelligence:read"))],
    summary="Un segmento por propensión en vez de por filtros",
    description=(
        "Con la advertencia que lo hace honesto: un segmento predictivo **cambia "
        "solo**. La lista de hoy no es la de la semana que viene, y comparar "
        "resultados de dos ejecuciones es comparar dos audiencias distintas "
        "creyendo que son la misma."
    ),
)
def segmento(cuerpo: SegmentoIn, principal: AutenticadoDep) -> Any:
    return ent.segmento_predictivo(
        candidatos=cuerpo.candidatos,
        minimo_puntuacion=cuerpo.minimo_puntuacion,
        tope=cuerpo.tope,
    )


@router_transcripcion.post(
    "",
    dependencies=[Depends(exige_permiso("intelligence:write"))],
    summary="Registrar una transcripción, con permiso y con su confianza",
    description=(
        "**Primero el permiso.** Grabar a alguien sin decírselo es ilegal en "
        "media Europa y una ruptura de confianza en la otra media, y el cliente "
        "que se entera después no vuelve a hablar con soltura delante de "
        "nadie.\n\n"
        "Y una transcripción **no es un acta**: el modelo confunde nombres, se "
        "pierde con dos personas hablando a la vez y traduce mal las cifras. Se "
        "guarda con su confianza, y la atribución de quién dijo qué se marca "
        "como lo menos fiable de todo."
    ),
)
def transcribir(cuerpo: TranscribirIn, principal: AutenticadoDep) -> Any:
    trs.exigir_permiso_para_grabar(
        base=cuerpo.base_para_grabar,
        participantes_avisados=cuerpo.participantes_avisados,
        participantes_externos=cuerpo.participantes_externos,
    )
    return trs.registrar_transcripcion(
        referencia=cuerpo.referencia,
        texto=cuerpo.texto,
        confianza=cuerpo.confianza,
        idioma=cuerpo.idioma,
        minutos=cuerpo.minutos,
        hablantes=cuerpo.hablantes,
    )


@router_transcripcion.post(
    "/compromisos",
    dependencies=[Depends(exige_permiso("intelligence:read"))],
    summary="Los compromisos y próximos pasos, como propuestas",
    description=(
        "«Te mando la oferta el jueves» y «si me la mandas el jueves, la miro» se "
        "parecen mucho en un texto y significan lo contrario. Crear la tarea "
        "directamente llena la agenda de compromisos que nadie adquirió, y "
        "entonces se deja de mirar la agenda.\n\n"
        "Lo que viene de una transcripción poco fiable **no se propone siquiera**: "
        "una propuesta mala también cuesta el tiempo de leerla y descartarla. Y un "
        "compromiso sin dueño no se asigna «por defecto» al comercial."
    ),
)
def compromisos(cuerpo: ExtraerIn, principal: AutenticadoDep) -> Any:
    return trs.proponer_extraidos(
        elementos=cuerpo.elementos, confianza_transcripcion=cuerpo.confianza_transcripcion
    )


@router_variantes.post(
    "",
    dependencies=[Depends(exige_permiso("intelligence:write"))],
    summary="Registrar variantes de texto como propuestas",
    description=(
        "Ninguna sale sin que una persona la apruebe. No es desconfianza en el "
        "modelo: el texto lleva el nombre de la empresa y quien lo firma tiene "
        "que haberlo leído.\n\n"
        "Las **afirmaciones comprobables se marcan** —«un 40 % más rápido», «el "
        "más rápido del mercado»—: un modelo las escribe con la misma "
        "naturalidad con la que escribe «buenos días», y el revisor que lee "
        "deprisa no distingue lo uno de lo otro."
    ),
)
def variantes(cuerpo: VariantesIn, principal: AutenticadoDep) -> Any:
    return var.proponer_variantes(base=cuerpo.base, textos=cuerpo.textos, canal=cuerpo.canal)


@router_variantes.post(
    "/aprobar",
    dependencies=[Depends(exige_permiso("intelligence:write"))],
    summary="Aprobar o reescribir una variante",
    description=(
        "Se guarda **lo que propuso el modelo y lo que salió**: sin ese par no se "
        "puede saber si esto ayuda o si se reescribe todo igualmente."
    ),
)
def aprobar(cuerpo: AprobarIn, principal: AutenticadoDep) -> Any:
    return var.aprobar(
        texto_propuesto=cuerpo.texto_propuesto,
        texto_final=cuerpo.texto_final,
        aprobada_por=principal.id,
    )


@router_sugerencias.post(
    "/{caso_id}",
    dependencies=[Depends(exige_permiso("intelligence:read"))],
    summary="Qué ponerle delante al agente con este caso abierto",
    description=(
        "Un resultado **sin cita no vale**: el agente tendría que creerse un "
        "párrafo generado y responder con él, y cuando esté mal no habrá forma de "
        "saber si falló el dato o el modelo.\n\n"
        "**Lo parecido no es lo aplicable**: dos casos pueden hablar de lo mismo "
        "y ser de productos o versiones distintas, así que se enseña en qué "
        "coinciden y en qué no.\n\n"
        "Y **no se sugiere lo que no se ha resuelto**: un caso parecido que sigue "
        "abierto no es una solución, es otro que tiene el mismo problema."
    ),
)
def sugerir(caso_id: UUID, cuerpo: SugerirIn, principal: AutenticadoDep) -> Any:
    salida = sem.buscar(
        resultados=cuerpo.resultados,
        contexto_del_caso=cuerpo.contexto_del_caso,
        permisos_del_agente=set(principal.permisos),
    )
    return {**sem.sugerir_para(caso_id=caso_id, sugerencias=salida["sugerencias"]), **salida}


ROUTERS_MODELOS = [router_modelos, router_transcripcion, router_variantes, router_sugerencias]
