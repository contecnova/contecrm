"""API de modelos entrenados, transcripción, variantes y sugerencia en el caso
(CRM-02.01.01.08, CRM-02.01.02.02, CRM-02.01.02.06, CRM-01.02.01.05,
CRM-01.02.01.06, CRM-02.04.01.04, CRM-04.03.01.04).

Todo lo de aquí devuelve **el número y el porqué**, y nada crea nada por su
cuenta: lo que sale son propuestas que confirma una persona.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, exige_permiso
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from services.intelligence import caso_semantico as sem
from services.intelligence import entrenamiento as ent
from services.intelligence import transcripcion as trs
from services.intelligence import variantes as var
from services.intelligence import voz

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
    caso: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "La ficha del caso tal cual está. Qué parte de ella se le manda al "
            "modelo **lo decide el servidor**: recibir el contexto ya compuesto "
            "deja en cada pantalla la decisión de qué datos personales salen "
            "hacia un proveedor de inferencia, y esa decisión se toma en un "
            "sitio o se toma en catorce"
        ),
    )
    incluir_datos_personales: bool = Field(
        False,
        description=(
            "Por defecto no sale nada personal: para encontrar casos parecidos "
            "hace falta el problema, no el nombre de quien lo tiene"
        ),
    )


class IndexarIn(BaseModel):
    """Lo que se quiere meter en el índice semántico, antes de meterlo."""

    elementos: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Cada uno con su `objeto` y el `permiso` que hace falta para verlo. "
            "Sin permiso declarado no entra"
        ),
    )


class UsoDeSugerenciasIn(BaseModel):
    sugerencias: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Cada una con `abierta` y `usada`: se mide por lo que se usa",
    )


class ParticionIn(BaseModel):
    casos: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Cada uno con su `cerrado_el` en ISO: sin fecha no se puede partir",
    )
    # El porcentaje por omisión es el del módulo. Repetir aquí el número
    # significa que el día que se cambie allí, esta puerta sigue partiendo como
    # antes y no lo nota nadie.
    # `None` = el del despliegue. Antes aquí había la constante del módulo,
    # que además congelaba el valor en el esquema publicado: el OpenAPI decía
    # «25» aunque la instalación usara otro.
    pct_validacion: int | None = Field(None, ge=5, le=50)


class CosteTranscribirIn(BaseModel):
    minutos_totales: int = Field(..., ge=0)
    coste_por_minuto: float = Field(..., ge=0)
    presupuesto: float | None = None


class CalidadExtraccionIn(BaseModel):
    confirmadas: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Cada una con `hubo_correccion`: lo que hubo que tocar a mano",
    )


class RamasIn(BaseModel):
    ramas: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Cada rama con su `texto`, sus `enviados` y sus `respuestas`",
    )


class AprobacionesIn(BaseModel):
    aprobaciones: list[dict[str, Any]] = Field(
        default_factory=list, description="Cada una con `hubo_reescritura`"
    )


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


@router_modelos.post(
    "/particion",
    dependencies=[Depends(exige_permiso("intelligence:read"))],
    summary="Cómo se parte el histórico para entrenar y para comprobar",
    description=(
        "**Por fecha, no al azar.** Repartir aleatoriamente mete casos "
        "posteriores en el entrenamiento, y entonces el modelo ha visto cómo "
        "acabó lo que tiene que predecir: el acierto sale magnífico y no "
        "significa nada, porque en producción no existe el futuro.\n\n"
        "Es el error que no se ve en ninguna gráfica —todas salen bien— y que "
        "aparece el primer mes, cuando el modelo que acertaba el 92 % en la "
        "presentación acierta la mitad con casos de verdad.\n\n"
        "Un caso sin fecha de cierre **para la partición**: sin ella no se puede "
        "separar por tiempo, y separar al azar es exactamente lo que se evita."
    ),
)
def particion(cuerpo: ParticionIn, principal: AutenticadoDep) -> Any:
    # Las fechas llegan como texto ISO porque esto entra por JSON. Lo que no se
    # puede leer se deja tal cual **a propósito**: así falla la comprobación de
    # `particion_temporal`, que dice cuántos casos no tienen fecha, en vez de
    # fallar aquí con un error de formato que no explica por qué importa.
    casos: list[dict[str, Any]] = []
    for caso in cuerpo.casos:
        copia = dict(caso)
        crudo = copia.get("cerrado_el")
        if isinstance(crudo, str):
            try:
                copia["cerrado_el"] = date.fromisoformat(crudo[:10])
            except ValueError:
                pass
        casos.append(copia)
    return ent.particion_temporal(casos=casos, pct_validacion=cuerpo.pct_validacion)


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


@router_transcripcion.post(
    "/coste",
    dependencies=[Depends(exige_permiso("intelligence:read"))],
    summary="Cuánto cuesta transcribir esto, antes de hacerlo",
    description=(
        "Una biblioteca de tres años de llamadas es una **factura**, no un "
        "botón. Y la factura llega al mes siguiente, cuando ya no hay nada que "
        "decidir.\n\n"
        "No ejecuta nada: devuelve el importe para que alguien lo confirme. Si "
        "no cabe en el presupuesto lo dice antes, que es cuando todavía se puede "
        "elegir **qué** se transcribe en vez de empezar y quedarse a medias."
    ),
)
def coste_transcripcion(cuerpo: CosteTranscribirIn, principal: AutenticadoDep) -> Any:
    return trs.coste_de_transcribir(
        minutos_totales=cuerpo.minutos_totales,
        coste_por_minuto=cuerpo.coste_por_minuto,
        presupuesto=cuerpo.presupuesto,
    )


@router_transcripcion.post(
    "/calidad",
    dependencies=[Depends(exige_permiso("intelligence:read"))],
    summary="Cuánto hay que corregir de lo que propone el modelo",
    description=(
        "Es el número que decide si esto se sigue usando. Si hay que corregir la "
        "mitad **no ahorra tiempo**: lo cambia de sitio —de escribir a revisar, "
        "que cansa más— y eso se nota en que la gente deja de abrirlo sin decir "
        "nada.\n\n"
        "Sin confirmaciones no se dice que funcione: se dice que no se ha usado, "
        "que es una respuesta distinta y la que toca."
    ),
)
def calidad_extraccion(cuerpo: CalidadExtraccionIn, principal: AutenticadoDep) -> Any:
    return trs.calidad_de_la_extraccion(confirmadas=cuerpo.confirmadas)


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


@router_variantes.post(
    "/ganadora",
    dependencies=[Depends(exige_permiso("intelligence:read"))],
    summary="Qué variante gana, o que todavía no se sabe",
    description=(
        "Con doscientos envíos por rama, la diferencia entre un 4,1 % y un 4,4 % "
        "**es ruido**. Declararla ganadora convierte el azar en una decisión de "
        "marca que luego se repite durante dos años porque «los datos lo "
        "decían».\n\n"
        "Así que hay dos respuestas posibles y la segunda es «todavía no»: se "
        "dice cuántos envíos tiene la rama más pequeña y cuántos harían falta, "
        "en vez de enseñar un ganador que no lo es."
    ),
)
def ganadora(cuerpo: RamasIn, principal: AutenticadoDep) -> Any:
    return var.elegir_ganadora(ramas=cuerpo.ramas)


@router_variantes.post(
    "/rendimiento",
    dependencies=[Depends(exige_permiso("intelligence:read"))],
    summary="Cuánto se reescribe de lo que propone el modelo",
    description=(
        "Es el número que dice si esto ahorra tiempo de verdad. Si se reescribe "
        "casi todo, lo que hace el modelo es **dar un punto de partida** —que "
        "también vale— pero no es lo que se vendió, y conviene no confundirlo al "
        "contarlo.\n\n"
        "Sale del par que se guarda al aprobar: lo que propuso el modelo y lo "
        "que salió. Sin ese par esto no se puede medir, solo opinar."
    ),
)
def rendimiento_generacion(cuerpo: AprobacionesIn, principal: AutenticadoDep) -> Any:
    return var.rendimiento_de_la_generacion(aprobaciones=cuerpo.aprobaciones)


@router_sugerencias.post(
    "/indexables",
    dependencies=[Depends(exige_permiso("intelligence:write"))],
    summary="Qué puede entrar en el índice semántico",
    description=(
        "**Los permisos se aplican antes de indexar, no después.** Indexar "
        "primero y filtrar al buscar ya ha metido el contenido en un sitio del "
        "que sale por otros caminos: basta con que un fragmento aparezca en un "
        "resumen para que un agente lea el caso de un cliente que no le toca, y "
        "entonces el resultado descartado ya se ha leído.\n\n"
        "Por eso nada entra sin declarar **qué permiso hace falta para verlo**. "
        "Se comprueba aquí, antes de que el texto salga hacia el índice, y lo "
        "que no lo declara no se indexa: se dice cuál es y se para."
    ),
)
def indexables(cuerpo: IndexarIn, principal: AutenticadoDep) -> Any:
    for elemento in cuerpo.elementos:
        sem.exigir_permiso_de_indexacion(
            objeto=str(elemento.get("objeto") or ""), permiso=elemento.get("permiso")
        )
    return {
        "indexables": len(cuerpo.elementos),
        "porque": (
            "Todos declaran con qué permiso se ven. Lo que entra en el índice sale "
            "por los caminos del índice, así que el permiso viaja con el contenido."
        ),
    }


@router_sugerencias.post(
    "/aprovechamiento",
    dependencies=[Depends(exige_permiso("intelligence:read"))],
    summary="Si esto le sirve al agente o solo ocupa sitio en la pantalla",
    description=(
        "Se mide por **lo que usa**, no por lo que abre: abrir una sugerencia es "
        "mirar si sirve, y casi nunca sirve.\n\n"
        "Y si no se usa casi nada el problema **no es del agente**: o el índice "
        "no tiene lo que hace falta, o el umbral de parecido está dejando pasar "
        "ruido. Las dos se arreglan aquí, no insistiendo en que lo miren."
    ),
)
def aprovechamiento(cuerpo: UsoDeSugerenciasIn, principal: AutenticadoDep) -> Any:
    return sem.aprender_de_lo_usado(sugerencias=cuerpo.sugerencias)


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
        "abierto no es una solución, es otro que tiene el mismo problema.\n\n"
        "**Lo que sale hacia el modelo lo recorta el servidor.** Se manda el "
        "problema —asunto, descripción, producto, versión, categoría— y no la "
        "ficha entera: para encontrar casos parecidos no hace falta el nombre de "
        "quien lo tiene, y mandarlo manda datos personales a un proveedor de "
        "inferencia sin ninguna ganancia. La respuesta lleva **exactamente lo "
        "que salió**, para que se pueda mirar."
    ),
)
def sugerir(caso_id: UUID, cuerpo: SugerirIn, principal: AutenticadoDep) -> Any:
    # El contexto se compone AQUÍ y no llega compuesto. Dejar que lo componga
    # quien llama convierte «qué datos personales salen» en una decisión de cada
    # pantalla, y basta con que una la tome mal.
    recorte = sem.contexto_para_el_modelo(
        caso=cuerpo.caso, incluir_datos_personales=cuerpo.incluir_datos_personales
    )
    salida = sem.buscar(
        resultados=cuerpo.resultados,
        contexto_del_caso=recorte["contexto"],
        permisos_del_agente=set(principal.permisos),
    )
    return {
        **sem.sugerir_para(caso_id=caso_id, sugerencias=salida["sugerencias"]),
        **salida,
        "lo_que_se_manda": recorte,
    }


# ── Voz y asistentes conversacionales (CRM-04.02.01.08) ───────────────────

router_voz = APIRouter(prefix="/voz", tags=["voz y asistentes"])


class EntenderIn(BaseModel):
    texto: str = ""
    confianza: float = 0.0
    intento: int = 0
    lo_ya_dicho: list[str] = Field(
        default_factory=list,
        description=(
            "Lo que ya se habló en esta llamada. Viaja con el traspaso: si la "
            "persona empieza de cero, lo que hizo el asistente fue perder tres "
            "minutos del cliente"
        ),
    )
    datos_recogidos: dict[str, Any] = Field(
        default_factory=dict, description="Lo que el asistente ya consiguió que le dijeran"
    )


class AperturaIn(BaseModel):
    nombre_asistente: str
    es_maquina: bool = True
    graba: bool = False
    consentimiento_entrenamiento: bool = Field(
        False,
        description=(
            "Consentimiento **explícito** para usar esta voz en el entrenamiento "
            "del modelo. No es el aviso de grabación: son dos permisos distintos "
            "y por defecto este no está dado"
        ),
    )


class RendimientoVozIn(BaseModel):
    conversaciones: list[dict[str, Any]] = Field(default_factory=list)


@router_voz.post(
    "/entender",
    dependencies=[Depends(exige_permiso("intelligence:read"))],
    summary="Qué hacer con lo que ha entendido el reconocedor",
    description=(
        "**La confianza decide, no el texto.** Un reconocimiento flojo no es una "
        "frase con erratas: puede significar lo contrario —«no quiero cancelar» y "
        "«quiero cancelar» se parecen mucho a bajo volumen—, y actuar sobre eso "
        "es peor que no entender nada.\n\n"
        "A la tercera se pasa a una persona. Pedirlo otra vez no mejora el "
        "reconocimiento: solo confirma al cliente que está hablando con una "
        "máquina que no funciona."
    ),
)
def entender(cuerpo: EntenderIn, principal: AutenticadoDep) -> Any:
    salida = voz.entender(texto=cuerpo.texto, confianza=cuerpo.confianza, intento=cuerpo.intento)
    if not salida.get("pasar_a_persona"):
        return salida
    # El traspaso se arma AQUÍ, en la misma respuesta. Dejarlo para otra llamada
    # significa que la primera implantación con prisa no la hace, y entonces la
    # persona coge el teléfono sin saber qué se habló: el cliente lo cuenta todo
    # otra vez y los tres minutos del asistente fueron tiempo perdido suyo.
    return {
        **salida,
        "traspaso": voz.traspaso_a_persona(
            motivo=str(salida.get("porque") or "El reconocimiento no da para seguir"),
            lo_ya_dicho=cuerpo.lo_ya_dicho,
            datos_recogidos=cuerpo.datos_recogidos,
        ),
    }


@router_voz.get(
    "/puede-hacerse/{accion}",
    dependencies=[Depends(exige_permiso("intelligence:read"))],
    summary="Si esa acción se puede hacer por voz",
    description=(
        "Cambiar unos datos bancarios por teléfono, con reconocimiento de voz de "
        "por medio y sin que nadie más lo mire, es el fraude telefónico más común "
        "que existe.\n\n"
        "No es una limitación técnica: es una decisión que se toma una vez y **no "
        "se deja configurable**, porque configurable significa que alguien la va "
        "a abrir."
    ),
)
def puede_hacerse(accion: str, principal: AutenticadoDep) -> Any:
    voz.exigir_que_se_puede_hacer_por_voz(accion=accion)
    return {"puede": True, "accion": accion, "lo_que_si": list(voz.PUEDE_SOLO)}


@router_voz.post(
    "/apertura",
    dependencies=[Depends(exige_permiso("intelligence:read"))],
    summary="Lo que se dice al empezar la llamada",
    description=(
        "Se avisa de que es una máquina porque la gente habla distinto —más corto "
        "y más claro— cuando lo sabe, así que el sistema funciona mejor; y porque "
        "descubrirlo a los tres minutos sienta francamente mal.\n\n"
        "Y avisar de que se graba **no es** consentimiento para entrenar con esa "
        "voz: son dos permisos distintos, y confundirlos es lo más frecuente en "
        "cualquier proyecto de voz."
    ),
)
def apertura(cuerpo: AperturaIn, principal: AutenticadoDep) -> Any:
    guion = voz.guion_de_apertura(
        nombre_asistente=cuerpo.nombre_asistente,
        es_maquina=cuerpo.es_maquina,
        graba=cuerpo.graba,
    )
    # Los dos permisos se contestan JUNTOS, que es donde se confunden. Quien
    # monta la llamada lee aquí que avisar de la grabación no le habilita a
    # entrenar con esa voz, en vez de descubrirlo cuando el audio ya está dentro
    # de un modelo del que no se puede sacar.
    return {
        **guion,
        "entrenar_con_este_audio": voz.usar_audio_para_entrenar(
            consentimiento_explicito=cuerpo.consentimiento_entrenamiento
        ),
    }


@router_voz.post(
    "/rendimiento",
    dependencies=[Depends(exige_permiso("intelligence:read"))],
    summary="Si el asistente sirve, medido como se mide de verdad",
    description=(
        "No por «llamadas atendidas» —eso lo hace una locución— sino por "
        "**resueltas sin persona y sin que el cliente vuelva a llamar en 48 "
        "horas**. Una llamada que el asistente «resolvió» y que el cliente repite "
        "al día siguiente no se resolvió: se aplazó, y encima con el cliente ya "
        "molesto."
    ),
)
def rendimiento_voz(cuerpo: RendimientoVozIn, principal: AutenticadoDep) -> Any:
    return voz.rendimiento(conversaciones=cuerpo.conversaciones)


ROUTERS_MODELOS = [
    router_modelos,
    router_transcripcion,
    router_variantes,
    router_sugerencias,
    router_voz,
]
