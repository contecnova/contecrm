"""API de audiencias publicitarias, canales offline, personalización web,
biblioteca de activos, aprobación y redes sociales
(CRM-02.01.01.09, CRM-02.03.02.04, .05, .07 · CRM-02.04.01.01, .02 ·
CRM-04.02.01.06).

Lo que tienen en común: todo sale **fuera** —a una plataforma, a un buzón físico,
a un hilo público— y eso no se puede deshacer.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_listado
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from services.marketing import activos as act
from services.marketing import audiencias_externas as aud
from services.marketing import social as soc
from services.marketing.activos import Activo, Aprobacion

router_audiencias = APIRouter(prefix="/audiencias-externas", tags=["publicidad y audiencias"])
# `/activos-marketing` y no `/activos`: ese prefijo ya lo usa el servicio de
# campo para los equipos instalados en casa del cliente, y compartirlo habría
# mandado las llamadas de la biblioteca al servicio equivocado.
router_activos = APIRouter(prefix="/activos-marketing", tags=["biblioteca de activos"])
router_social = APIRouter(prefix="/social", tags=["redes sociales"])


class AudienciaIn(BaseModel):
    personas: list[dict[str, Any]] = Field(default_factory=list)
    plataforma: str
    finalidad: str


class RetargetingIn(BaseModel):
    visitas: list[dict[str, Any]] = Field(default_factory=list)
    excluir_clientes: bool = True


class OfflineIn(BaseModel):
    canal: str
    destinatarios: list[dict[str, Any]] = Field(default_factory=list)
    coste_unitario: float = 0.0
    fecha_lanzamiento: date


class WebIn(BaseModel):
    visitante: dict[str, Any] = Field(default_factory=dict)
    reglas: list[dict[str, Any]] = Field(default_factory=list)
    anonimo_por_defecto: str = ""


class ActivoIn(BaseModel):
    clave: str
    nombre: str
    referencia: str
    usos_permitidos: list[str] = Field(default_factory=list)
    licencia: str = ""
    licencia_hasta: date | None = None
    vigente_hasta: date | None = None
    tipo: str = "documento"
    idioma: str = "es"
    etiquetas: list[str] = Field(default_factory=list)


class AprobacionIn(BaseModel):
    objeto: str
    objeto_id: UUID
    version: int = 1
    pasos: list[dict[str, Any]] = Field(default_factory=list)


class DecisionIn(BaseModel):
    resultado: str
    comentario: str = ""
    vio_los_cambios: bool = False


class MencionIn(BaseModel):
    mencion: dict[str, Any] = Field(default_factory=dict)
    palabras_de_crisis: list[str] = Field(default_factory=list)


class RespuestaSocialIn(BaseModel):
    tipo: str
    en_publico: bool = True
    texto: str = ""
    escrito_por_persona: bool = True
    pide_datos_personales: bool = False


@router_audiencias.post(
    "",
    dependencies=[Depends(exige_permiso("marketing:write"))],
    summary="Preparar una audiencia para una plataforma publicitaria",
    description=(
        "**Sin base legal para publicidad no sale nadie**, y no vale el "
        "consentimiento del boletín: aceptar correos comerciales no es aceptar "
        "que tu dirección se suba a una red de anuncios. Se comprueba persona a "
        "persona, no por segmento.\n\n"
        "Lo que sale va **troceado**, nunca en claro. Y por debajo de cien "
        "personas no se manda: la plataforma no puede anonimizar nada y el "
        "segmento se convierte en señalar a alguien con el dedo."
    ),
)
def audiencia(cuerpo: AudienciaIn, principal: AutenticadoDep) -> Any:
    return aud.preparar_audiencia(
        personas=cuerpo.personas, plataforma=cuerpo.plataforma, finalidad=cuerpo.finalidad
    )


@router_audiencias.post(
    "/retargeting",
    dependencies=[Depends(exige_permiso("marketing:write"))],
    summary="Audiencia de retargeting a partir de comportamiento",
    description=(
        "Con dos exclusiones que casi nadie pone: **a quien ya compró** no se le "
        "persigue con el anuncio de lo que compró —es la queja más habitual de "
        "cualquier campaña—, y **a quien se dio de baja** tampoco: un anuncio no "
        "es un correo, pero para la persona es la empresa que le sigue después de "
        "haberle dicho que no."
    ),
)
def retargeting(cuerpo: RetargetingIn, principal: AutenticadoDep) -> Any:
    return aud.retargeting(visitas=cuerpo.visitas, excluir_clientes=cuerpo.excluir_clientes)


@router_audiencias.post(
    "/offline",
    dependencies=[Depends(exige_permiso("marketing:write"))],
    summary="Preparar un paso de correo postal o telemarketing",
    description=(
        "Con la diferencia que lo cambia todo: **no se puede cancelar**. Una carta "
        "impresa ya está impresa y una llamada hecha no se deshace, así que la "
        "comprobación va antes del lanzamiento.\n\n"
        "Y cuesta dinero por unidad: mandar diez mil cartas por error no es un "
        "incidente, es una factura."
    ),
)
def offline(cuerpo: OfflineIn, principal: AutenticadoDep) -> Any:
    return aud.preparar_paso_offline(
        canal=cuerpo.canal,
        destinatarios=cuerpo.destinatarios,
        coste_unitario=cuerpo.coste_unitario,
        fecha_lanzamiento=cuerpo.fecha_lanzamiento,
    )


@router_audiencias.post(
    "/contenido-web",
    dependencies=[Depends(exige_permiso("marketing:read"))],
    summary="Qué contenido servir a este visitante",
    description=(
        "Un visitante que no se ha identificado **no es «uno cualquiera»**: es "
        "alguien de quien no se sabe nada, y se le sirve lo genérico. Adivinar "
        "por IP o por el dispositivo produce personalizaciones que dan entre risa "
        "y susto.\n\n"
        "Y la regla aplicada se devuelve: cuando el cliente pregunte por qué a su "
        "director le salió el bloque de «pymes», la respuesta no puede ser «lo "
        "decide el algoritmo»."
    ),
)
def contenido_web(cuerpo: WebIn, principal: AutenticadoDep) -> Any:
    return aud.contenido_para(
        visitante=cuerpo.visitante,
        reglas=cuerpo.reglas,
        anonimo_por_defecto=cuerpo.anonimo_por_defecto,
    )


@router_activos.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("marketing:write"))],
    summary="Dar de alta un activo con sus derechos y su vigencia",
    description=(
        "**Sin usos declarados no entra.** Una foto de banco con licencia para "
        "web no vale para una valla, y esa diferencia la conoce quien la compró y "
        "nadie más: sin ella, la biblioteca es una fuente de problemas legales "
        "con buscador.\n\n"
        "La versión nueva **no borra la anterior**: lo que se mandó al cliente el "
        "martes tiene que poder recuperarse aunque el jueves se corrigiera una "
        "errata."
    ),
)
def alta_activo(cuerpo: ActivoIn, uow: UowDep) -> Any:
    fila = act.registrar_activo(
        uow,
        clave=cuerpo.clave,
        nombre=cuerpo.nombre,
        referencia=cuerpo.referencia,
        usos_permitidos=cuerpo.usos_permitidos,
        licencia=cuerpo.licencia,
        licencia_hasta=cuerpo.licencia_hasta,
        vigente_hasta=cuerpo.vigente_hasta,
        tipo=cuerpo.tipo,
        idioma=cuerpo.idioma,
        etiquetas=cuerpo.etiquetas,
    )
    return {"id": str(fila.id), "clave": fila.clave, "version": fila.version}


@router_activos.get(
    "/revision",
    dependencies=[Depends(exige_permiso("marketing:read"))],
    summary="Qué hay que mirar antes de que dé un problema",
    description=(
        "Lo caducado y lo que va a caducar, con aviso **antes**: renovar un "
        "contrato de imagen o rehacer una pieza lleva semanas.\n\n"
        "Y lo que **no tiene vigencia declarada**, que es lo más peligroso: nunca "
        "va a aparecer en ninguna lista de caducados y por eso se queda ahí para "
        "siempre."
    ),
)
def revision_biblioteca(db: DbDep, principal: AutenticadoDep) -> Any:
    return act.revisar_biblioteca(db, principal.tenant_id)


@router_activos.post(
    "/aprobacion",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("marketing:write"))],
    summary="Abrir la revisión de un contenido o una campaña",
    description=(
        "Un paso **sin aprobador concreto** no es un paso: es una cola donde las "
        "cosas se quedan. «Que lo vea marketing» no lo ve nadie.\n\n"
        "Y se aprueba **antes de publicar**: un flujo donde el contenido sale y "
        "luego alguien revisa es un flujo sin aprobación, porque lo que está "
        "fuera, fuera está."
    ),
)
def abrir_aprobacion(cuerpo: AprobacionIn, uow: UowDep) -> Any:
    return act.pedir_aprobacion(
        uow,
        objeto=cuerpo.objeto,
        objeto_id=cuerpo.objeto_id,
        version=cuerpo.version,
        pasos=cuerpo.pasos,
    )


@router_activos.post(
    "/aprobacion/{aprobacion_id}",
    dependencies=[Depends(exige_permiso("marketing:write"))],
    summary="Aprobar o rechazar un paso",
    description=(
        "**Rechazar exige comentario**: un rechazo sin motivo devuelve el trabajo "
        "al principio sin decir qué cambiar, y la segunda versión suele traer el "
        "mismo problema.\n\n"
        "Y se anota si el aprobador vio **qué cambió**: revisar treinta páginas "
        "enteras cada vez es lo que hace que se apruebe sin leer, y saber cuántas "
        "aprobaciones se dieron sin mirar el diff es el dato que dice si este "
        "flujo sirve o es un trámite."
    ),
)
def decidir(aprobacion_id: UUID, cuerpo: DecisionIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    return act.decidir(
        uow,
        aprobacion_id=aprobacion_id,
        resultado=cuerpo.resultado,
        comentario=cuerpo.comentario,
        aprobador_id=principal.id,
        vio_los_cambios=cuerpo.vio_los_cambios,
    )


@router_social.post(
    "/clasificar",
    dependencies=[Depends(exige_permiso("marketing:read"))],
    summary="Qué es esta mención y si abre caso",
    description=(
        "Lo importante no es acertar siempre: es **no convertir todo en un "
        "caso**. Un «gracias por el envío rápido» no necesita un expediente con "
        "SLA, y meterlo en la cola hace que el agente aprenda a cerrar sin "
        "leer.\n\n"
        "Lo que sí escala solo es lo que se parece a una crisis: no por volumen, "
        "sino porque una sola mención con las palabras equivocadas ya es un "
        "problema distinto."
    ),
)
def clasificar(cuerpo: MencionIn, principal: AutenticadoDep) -> Any:
    return soc.clasificar(mencion=cuerpo.mencion, palabras_de_crisis=cuerpo.palabras_de_crisis)


@router_social.post(
    "/respuesta",
    dependencies=[Depends(exige_permiso("marketing:write"))],
    summary="Comprobar una respuesta antes de publicarla",
    description=(
        "**Lo que sale en nombre de la marca lo escribe una persona.** Una "
        "respuesta automática a una queja pública es lo que convierte a un "
        "cliente enfadado en un hilo viral.\n\n"
        "Y **no se piden datos personales en público**: obligar a alguien a dar "
        "su número de pedido delante de todo el mundo es un problema de "
        "privacidad y una mala respuesta a la vez."
    ),
)
def respuesta_social(cuerpo: RespuestaSocialIn, principal: AutenticadoDep) -> Any:
    return soc.responder(
        tipo=cuerpo.tipo,
        en_publico=cuerpo.en_publico,
        texto=cuerpo.texto,
        escrito_por_persona=cuerpo.escrito_por_persona,
        pide_datos_personales=cuerpo.pide_datos_personales,
    )


# ── Listados ──────────────────────────────────────────────────────────────
# Estas colecciones se podían crear y no se podían leer: tenían `POST` y no
# tenían `GET`, así que lo que se daba de alta desaparecía de la vista. La API
# contestaba 405 y el front —que las declara listables— enseñaba una pantalla
# vacía sin decir por qué.

montar_listado(
    router_activos,
    modelo=Activo,
    objeto="activo_marketing",
    permiso="marketing:read",
    nombre="Activos de marketing",
)


# ── Listados de las sub-colecciones ───────────────────────────────────────
# Mismo agujero que en las colecciones raíz: se podían crear y no se podían
# leer. Un sobre de firma, un subprocesador o una transferencia internacional
# que no se pueden listar no existen para quien tiene que auditarlos.

montar_listado(
    router_activos,
    modelo=Aprobacion,
    objeto="aprobacion_activo",
    permiso="marketing:read",
    ruta="/aprobacion",
    nombre="Aprobaciones de activos",
)


# ── Lo que estaba escrito y no se podía pedir ─────────────────────────────
#
# Medido el 05-10-2026: seis decisiones de este módulo no las alcanzaba ninguna
# ruta. Las dos primeras son las que duelen, porque las dos son promesas hechas
# a una persona que no es cliente nuestra.


class BajasIn(BaseModel):
    bajas_en_el_crm: list[dict[str, Any]] = Field(default_factory=list)
    ultimo_envio: datetime | None = None


@router_audiencias.post(
    "/bajas",
    dependencies=[Depends(exige_permiso("marketing:read"))],
    summary="Quién se dio de baja y sigue en las audiencias de fuera",
    description=(
        "**Es el punto donde todas estas integraciones fallan.** Alguien se da de "
        "baja en el CRM, la audiencia de la plataforma se actualiza «cuando "
        "toque», y mientras tanto sigue viendo anuncios. Es exactamente lo que la "
        "gente denuncia, y tiene razón.\n\n"
        "Por eso la baja no espera al ciclo normal: sale en su propia lista."
    ),
)
def bajas(cuerpo: BajasIn, principal: AutenticadoDep) -> Any:
    return aud.bajas_a_propagar(
        bajas_en_el_crm=cuerpo.bajas_en_el_crm, ultimo_envio=cuerpo.ultimo_envio
    )


class ReglasWebIn(BaseModel):
    reglas: list[dict[str, Any]] = Field(default_factory=list)


@router_audiencias.post(
    "/reglas-web/comprobar",
    dependencies=[Depends(exige_permiso("marketing:read"))],
    summary="Qué le pasa a este conjunto de reglas de personalización",
    description=(
        "Lo que rompe una personalización web no es una regla mal escrita: son "
        "**dos reglas que encajan a la vez** sin prioridad declarada. Entonces el "
        "contenido depende del orden en que lleguen de la base, cambia solo, nadie "
        "puede reproducirlo — y se culpa a la caché.\n\n"
        "Se puede comprobar antes de guardarlas; servir contenido las comprueba "
        "también, y devuelve los empates junto al contenido."
    ),
)
def reglas_web(cuerpo: ReglasWebIn, principal: AutenticadoDep) -> Any:
    return aud.comprobar_reglas_web(reglas=cuerpo.reglas)


class ResultadoOfflineIn(BaseModel):
    envios: list[dict[str, Any]] = Field(default_factory=list)


@router_audiencias.post(
    "/offline/resultado",
    dependencies=[Depends(exige_permiso("marketing:read"))],
    summary="Qué ha pasado con un paso offline, sabiendo lo poco que se puede saber",
    description=(
        "Una carta no tiene apertura ni clic. Lo único medible es lo que vuelve: "
        "una devolución, una llamada al número de la campaña, un código usado. "
        "**Fingir métricas de digital en un canal que no las tiene** es lo que "
        "hace que las comparaciones entre canales no valgan nada — y con ellas se "
        "reparte el presupuesto del año siguiente."
    ),
)
def resultado_offline(cuerpo: ResultadoOfflineIn, principal: AutenticadoDep) -> Any:
    return aud.resultado_offline(envios=cuerpo.envios)


class UsoIn(BaseModel):
    activo: dict[str, Any] = Field(default_factory=dict)
    uso: str = Field(..., min_length=1, examples=["campana_email"])


@router_activos.post(
    "/se-puede-usar",
    dependencies=[Depends(exige_permiso("marketing:read"))],
    summary="Si este activo se puede usar para esto y hoy",
    description=(
        "Las tres respuestas negativas son **distintas** y se distinguen, porque "
        "llevan a acciones distintas: no está aprobado (falta una firma), ha "
        "caducado (hay que renovar o rehacer) y no cubre este uso (hay que "
        "comprar otra licencia o buscar otra pieza).\n\n"
        "Un «no se puede» sin decir cuál de las tres manda a preguntar a tres "
        "sitios."
    ),
)
def se_puede_usar(cuerpo: UsoIn, principal: AutenticadoDep) -> Any:
    return act.se_puede_usar(activo=cuerpo.activo, uso=cuerpo.uso)


@router_activos.get(
    "/aprobaciones/estado",
    dependencies=[Depends(exige_permiso("marketing:read"))],
    summary="Si esto se puede publicar ya, y qué falta",
    description=(
        "Un rechazo vale **para el conjunto**: seguir pidiendo las firmas "
        "siguientes cuando uno ya ha dicho que no es hacer trabajar a gente sobre "
        "algo que va a cambiar."
    ),
)
def estado_aprobacion(
    db: DbDep,
    principal: AutenticadoDep,
    objeto: str,
    objeto_id: UUID,
    version: int = 1,
) -> Any:
    return act.estado_de_la_aprobacion(
        db, principal.tenant_id, objeto=objeto, objeto_id=objeto_id, version=version
    )


class CrisisIn(BaseModel):
    menciones_por_hora: list[int] = Field(default_factory=list)
    umbral_multiplicador: float = Field(
        5.0,
        gt=0,
        description=(
            "Cuántas veces el ritmo normal cuenta como incendio. Se mira el CAMBIO "
            "de ritmo y no el número absoluto: veinte menciones a la hora pueden "
            "ser normales para una marca grande y una señal de incendio para una "
            "pequeña, y un umbral fijo sólo funciona para el tamaño con el que se "
            "escribió"
        ),
    )


@router_social.post(
    "/crisis",
    dependencies=[Depends(exige_permiso("marketing:read"))],
    summary="Si esto ha dejado de ser una queja y es otra cosa",
)
def crisis(cuerpo: CrisisIn, principal: AutenticadoDep) -> Any:
    return soc.escalar_crisis(
        menciones_por_hora=cuerpo.menciones_por_hora,
        umbral_multiplicador=cuerpo.umbral_multiplicador,
    )


ROUTERS_CANALES_EXTERNOS = [router_audiencias, router_activos, router_social]
