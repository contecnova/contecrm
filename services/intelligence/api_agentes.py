"""API de agentes de IA y de asistencia (CRM-05.02.03, CRM-04.02.02.05,
CRM-04.03.02.02, CRM-01.01.05.05, CRM-03.01.02.04).

Ninguna de estas rutas ejecuta nada por su cuenta. El agente planifica, espera lo
que tiene que esperar y avanza **un paso por llamada**: es entre paso y paso
donde caben el apagado, el tope y la aprobación, y un endpoint que los ejecutara
todos de golpe convertiría esos tres controles en decoración.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_listado
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from services.intelligence import agentes as ag
from services.intelligence import asistencia as asis
from services.intelligence import herramientas as herr
from services.intelligence.agentes import Agente

router_agentes = APIRouter(prefix="/ia/agentes-autonomos", tags=["ia"])
router_asistencia = APIRouter(prefix="/ia/asistencia", tags=["ia"])


class DeclararAgente(BaseModel):
    clave: str = Field(..., min_length=1, max_length=80)
    tipo: str = Field(..., description="calificacion_leads · respuesta_soporte · …")
    descripcion: str = ""
    permisos: list[str] = Field(default_factory=list)
    herramientas: list[dict[str, Any]] = Field(default_factory=list)
    principal_id: UUID | None = None
    max_acciones: int = Field(10, ge=1, le=200)
    presupuesto_tokens_dia: int = Field(200_000, ge=1_000)
    aprobacion_por_riesgo: list[str] | None = None
    aprobacion_desde_importe: Decimal | None = None


class Apagar(BaseModel):
    motivo: str = Field(..., min_length=3)


class Lanzar(BaseModel):
    objetivo: str = Field(..., min_length=3)
    contexto: dict[str, Any] = Field(default_factory=dict)


class Aprobar(BaseModel):
    aprobado: bool
    motivo: str = ""


class HerramientasDesdeContrato(BaseModel):
    contrato: dict[str, Any] = Field(..., description="El OpenAPI del servicio")
    permisos: list[str] = Field(default_factory=list)
    riesgos_admitidos: list[str] | None = None
    solo_rutas: list[str] | None = None


@router_agentes.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Declarar un agente con sus herramientas y sus límites",
    description=(
        "Los agentes concretos —calificar leads, contestar soporte, actualizar "
        "datos— son **configuración y no código** (CRM-05.02.03.06): lo que "
        "cambia entre uno y otro es qué herramientas tiene y cuándo para.\n\n"
        "`aprobacion_por_riesgo` vacío **no es «ninguno»**: es el valor por "
        "defecto, que incluye lo destructivo. Leerlo como «ninguno» haría que "
        "declarar un agente sin pensar quitara justo el control que más falta hace."
    ),
)
def declarar_agente(cuerpo: DeclararAgente, uow: UowDep) -> Any:
    fila = ag.declarar(uow, **cuerpo.model_dump())
    return {
        "id": str(fila.id),
        "clave": fila.clave,
        "tipo": fila.tipo,
        "herramientas": len(fila.herramientas or []),
        "max_acciones": fila.max_acciones,
        "aprobacion_por_riesgo": fila.aprobacion_por_riesgo,
    }


@router_agentes.post(
    "/herramientas-desde-contrato",
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Derivar las herramientas del agente de la API del CRM (CRM-05.02.03.02)",
    description=(
        "Las herramientas **son la API**: una ruta nueva es una herramienta nueva "
        "sin que nadie la transcriba, y una retirada deja de existir para el "
        "agente el mismo día.\n\n"
        "Lo destructivo no entra por defecto: una herramienta de borrado "
        "disponible «porque la API la tiene» es la que acaba usándose por una "
        "instrucción mal entendida.\n\n"
        "Devuelve también **lo que ha quedado fuera y por qué**, separando «no "
        "puede» de «no se le ha querido dar»."
    ),
)
def herramientas_desde_contrato(cuerpo: HerramientasDesdeContrato) -> Any:
    return herr.desde_openapi(
        cuerpo.contrato,
        permisos=frozenset(cuerpo.permisos),
        riesgos_admitidos=tuple(cuerpo.riesgos_admitidos or herr.RIESGOS_POR_DEFECTO),
        solo_rutas=cuerpo.solo_rutas,
    )


@router_agentes.post(
    "/{clave}/apagar",
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Kill switch del agente (CRM-05.02.03.04)",
    description=(
        "Detiene también sus ejecuciones en vuelo: apagar un agente que sigue "
        "terminando lo que empezó no es apagarlo. El motivo es obligatorio, "
        "porque el siguiente que lo encienda tiene que saber qué pasó."
    ),
)
def apagar_agente(clave: str, cuerpo: Apagar, uow: UowDep) -> Any:
    fila = ag.apagar(uow, clave=clave, motivo=cuerpo.motivo)
    return {"clave": fila.clave, "activo": fila.activo, "motivo": fila.motivo_apagado}


@router_agentes.post(
    "/{clave}/lanzar",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Poner el agente a trabajar: planifica y guarda el plan",
    description=(
        "**No ejecuta nada.** Planifica, guarda el plan y deja esperando lo que "
        "necesita aprobación. Sin plan previo, la auditoría es una lista de cosas "
        "que pasaron y no hay forma de ver dónde se torció."
    ),
)
def lanzar(clave: str, cuerpo: Lanzar, uow: UowDep, principal: AutenticadoDep) -> Any:
    return ag.lanzar(
        uow, clave=clave, objetivo=cuerpo.objetivo, contexto=cuerpo.contexto, por=principal.id
    )


@router_agentes.post(
    "/ejecuciones/{ejecucion_id}/avanzar",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Ejecutar el siguiente paso, uno solo",
    description=(
        "Uno y no todos: entre paso y paso es donde caben el apagado, el tope de "
        "acciones y la aprobación humana."
    ),
)
def avanzar(ejecucion_id: UUID, uow: UowDep) -> Any:
    return ag.avanzar(uow, ejecucion_id=ejecucion_id)


@router_agentes.post(
    "/pasos/{paso_id}/aprobar",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Autorizar o rechazar un paso que esperaba a una persona",
)
def aprobar(paso_id: UUID, cuerpo: Aprobar, uow: UowDep, principal: AutenticadoDep) -> Any:
    return ag.aprobar(
        uow, paso_id=paso_id, aprobado=cuerpo.aprobado, por=principal.id, motivo=cuerpo.motivo
    )


@router_agentes.get(
    "/ejecuciones/{ejecucion_id}",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Qué hizo el agente, por qué y qué se puede deshacer",
    description=(
        "El plan y lo ejecutado se enseñan **juntos**: ver solo lo que pasó no "
        "dice dónde se torció, y ver solo el plan no dice qué llegó a hacerse."
    ),
)
def actuacion(ejecucion_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    return ag.actuacion(db, principal.tenant_id, ejecucion_id)


@router_agentes.post(
    "/ejecuciones/{ejecucion_id}/revertir",
    dependencies=[Depends(exige_permiso("ia:administrar"))],
    summary="Deshacer lo que el agente hizo (CRM-05.02.03.05)",
    description=(
        "En orden inverso, porque los pasos se apoyan unos en otros. Lo "
        "irreversible **no se toca y se dice**: un correo enviado no se "
        "«des-envía», y fingir que la reversión es total sería peor que no "
        "tenerla porque alguien confiaría."
    ),
)
def revertir(ejecucion_id: UUID, uow: UowDep, principal: AutenticadoDep) -> Any:
    return ag.revertir(uow, ejecucion_id=ejecucion_id, por=principal.id)


# ── Asistencia a la persona ───────────────────────────────────────────────


class SugerirRespuesta(BaseModel):
    caso_id: UUID
    pregunta: str
    fragmentos: list[dict[str, Any]] = Field(default_factory=list)


class Conversar(BaseModel):
    conversacion_id: UUID
    pregunta: str
    fragmentos: list[dict[str, Any]] = Field(default_factory=list)
    acciones_posibles: list[dict[str, Any]] = Field(default_factory=list)


class ResumenCuenta(BaseModel):
    cuenta_id: UUID
    hechos: dict[str, Any] = Field(default_factory=dict)


class ProximosPasos(BaseModel):
    senales: dict[str, Any] = Field(default_factory=dict)
    contenido_disponible: list[dict[str, Any]] = Field(default_factory=list)


@router_asistencia.post(
    "/respuesta-soporte",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Proponer respuesta y artículos al agente de soporte (CRM-04.02.02.05)",
    description=(
        "Si no hay con qué contestar, **no contesta**. Un agente que recibe una "
        "sugerencia sin fuentes la manda igual, porque tiene al cliente esperando "
        "— y el que responde de la respuesta es él."
    ),
)
def sugerir_respuesta(cuerpo: SugerirRespuesta, uow: UowDep, principal: AutenticadoDep) -> Any:
    return asis.sugerir_respuesta(
        uow,
        caso_id=cuerpo.caso_id,
        pregunta=cuerpo.pregunta,
        fragmentos=cuerpo.fragmentos,
        principal=principal,
    )


@router_asistencia.post(
    "/conversar",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Asistente con conocimiento y acciones (CRM-04.03.02.02)",
    description=(
        "La parte transaccional **no se ejecuta aquí**: devuelve qué acción "
        "propone, para que la ejecute el agente con su tope, su aprobación y su "
        "reversión. Un chatbot que escribe directamente en el CRM es un chatbot "
        "sin ninguno de esos controles."
    ),
)
def conversar(cuerpo: Conversar, uow: UowDep, principal: AutenticadoDep) -> Any:
    return asis.conversar(
        uow,
        conversacion_id=cuerpo.conversacion_id,
        pregunta=cuerpo.pregunta,
        fragmentos=cuerpo.fragmentos,
        acciones_posibles=cuerpo.acciones_posibles,
        principal=principal,
    )


@router_asistencia.post(
    "/resumen-cuenta",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Resumen de cuenta con puntos clave y riesgos (CRM-01.01.05.05)",
    description=(
        "Separa **lo que consta de lo que interpreta**: los hechos son del CRM y "
        "el texto es una lectura del modelo sobre esos hechos. Un riesgo "
        "inventado en un resumen de cuenta acaba en una reunión con el cliente."
    ),
)
def resumen_cuenta(cuerpo: ResumenCuenta, uow: UowDep, principal: AutenticadoDep) -> Any:
    return asis.resumen_de_cuenta(
        uow, cuenta_id=cuerpo.cuenta_id, hechos=cuerpo.hechos, principal=principal
    )


@router_asistencia.post(
    "/proximos-pasos",
    dependencies=[Depends(exige_permiso("ia:usar"))],
    summary="Qué hacer ahora con esta oportunidad (CRM-03.01.02.04)",
    description=(
        "Sale de señales del propio negocio, no de una plantilla de manual de "
        "ventas, y por eso cada paso lleva el dato que lo justifica. Con menos de "
        "tres señales **no se recomienda nada**: lo que saldría es el orden por "
        "defecto del producto disfrazado de consejo."
    ),
)
def proximos_pasos(cuerpo: ProximosPasos, db: DbDep, principal: AutenticadoDep) -> Any:
    return asis.proximos_pasos(
        db,
        principal.tenant_id,
        senales=cuerpo.senales,
        contenido_disponible=cuerpo.contenido_disponible,
    )


# ── Listados ──────────────────────────────────────────────────────────────
# Estas colecciones se podían crear y no se podían leer: tenían `POST` y no
# tenían `GET`, así que lo que se daba de alta desaparecía de la vista. La API
# contestaba 405 y el front —que las declara listables— enseñaba una pantalla
# vacía sin decir por qué.

montar_listado(
    router_agentes,
    modelo=Agente,
    objeto="agente_autonomo",
    permiso="ia:administrar",
    nombre="Agentes autónomos",
)


ROUTERS_AGENTES = [router_agentes, router_asistencia]
