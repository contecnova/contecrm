"""API omnicanal: canales, conversación, macros y consola
(CRM-04.02.01, CRM-04.02.02, CRM-04.03.02.03).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.service import omnicanal as omni

router_canales = APIRouter(prefix="/canales-servicio", tags=["omnicanal"])
router_conversaciones = APIRouter(prefix="/conversaciones", tags=["omnicanal"])
router_macros = APIRouter(prefix="/macros", tags=["omnicanal"])
router_consola = APIRouter(prefix="/consola-agente", tags=["omnicanal"])

# Router público: lo llaman el navegador de un desconocido, la pasarela de
# WhatsApp o el buzón de correo. Va **sin el prefijo de versión** por el mismo
# motivo que la captura de leads: la URL se pega en configuraciones ajenas y una
# versión dentro invita a cambiarla el día que exista `v2`.
router_entrada = APIRouter(prefix="/servicio/entrada", tags=["omnicanal"])


class CrearCanal(BaseModel):
    clave: str = Field(max_length=80)
    nombre: str = Field(max_length=200)
    tipo: str = Field("formulario", description=" | ".join(omni.CANALES))
    mapeo: dict[str, Any] = Field(default_factory=dict)
    fijos: dict[str, Any] = Field(default_factory=dict)
    obligatorios: list[str] = Field(default_factory=list)
    campo_trampa: str = ""
    max_por_hora: int = Field(300, ge=1, le=100_000)
    direccion_propia: str = ""


@router_canales.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Declarar un canal de entrada",
    description=(
        "Un canal declarado y no un endpoint por integración: el formulario de la "
        "web manda `nombre_completo`, el chat manda `visitor_name` y WhatsApp "
        "manda `profile.name`. Con un endpoint por cada uno, cada cliente nuevo "
        "es código nuevo; con un mapa declarado, es una fila.\n\n"
        "El secreto se devuelve **una sola vez**: se guarda hasheado para que una "
        "fuga de la base no lleve dentro las claves de los canales de todos los "
        "tenants.\n\n"
        "Los valores fijos van en el canal y no en la petición porque vienen del "
        "canal: si no, quien escribe podría abrir todos sus casos como críticos."
    ),
)
def crear_canal(datos: CrearCanal, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila, secreto = omni.crear_canal(
        uow.db,
        tenant_id=principal.tenant_id,
        clave=datos.clave,
        nombre=datos.nombre,
        tipo=datos.tipo,
        mapeo=datos.mapeo,
        fijos=datos.fijos,
        obligatorios=datos.obligatorios,
        campo_trampa=datos.campo_trampa,
        max_por_hora=datos.max_por_hora,
        direccion_propia=datos.direccion_propia,
    )
    return {
        "id": str(fila.id),
        "clave": fila.clave,
        "secreto": secreto,
        "aviso": (
            "Guarda el secreto: no se vuelve a enseñar."
            + (
                " Este canal es público y no tiene campo trampa: se llenará de basura."
                if not fila.campo_trampa and fila.tipo in ("formulario", "portal")
                else ""
            )
        ),
    }


class Entrada(BaseModel):
    canal: str = Field(max_length=80)
    secreto: str = Field(max_length=200)
    entrada: dict[str, Any] = Field(default_factory=dict)
    cabeceras: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Cabeceras del correo, si las hay. De aquí sale el anti-bucle y el "
            "hilo: `Auto-Submitted`, `In-Reply-To`, `References`"
        ),
    )


@router_entrada.post(
    "",
    summary="Entrada de un mensaje por cualquier canal",
    description=(
        "Endpoint público **pero no anónimo**: cada canal lleva su clave.\n\n"
        "El anti-bucle va **antes del tope**: un bucle de respuestas automáticas "
        "agota el tope en minutos y dejaría fuera a los clientes de verdad. Se "
        "mira `Auto-Submitted`, `Precedence`, `List-Id` y si el remitente es "
        "nuestra propia dirección — el buzón contestándose a sí mismo.\n\n"
        "Lo que cae en la trampa se descarta **con un 200**: devolver un error le "
        "dice al robot qué cambiar para la próxima.\n\n"
        "Un reintento de la pasarela **no abre un caso duplicado**: el "
        "identificador externo lo hace idempotente. Y se abre **un caso por "
        "conversación**, no uno por mensaje: si no, seis correos serían seis "
        "casos y el cliente recibiría seis respuestas de seis personas."
    ),
)
def entrada(datos: Entrada, uow: UowDep) -> Any:
    return omni.recibir(
        uow,
        canal_clave=datos.canal,
        secreto=datos.secreto,
        entrada=datos.entrada,
        cabeceras=datos.cabeceras,
    )


# ── Conversación ──────────────────────────────────────────────────────────


@router_conversaciones.get(
    "/historial",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Todo lo que este cliente ha hablado con nosotros",
    description=(
        "Por cualquier canal y ordenado por tiempo, **no agrupado por canal**: "
        "agrupar reproduce exactamente el problema que esto viene a resolver.\n\n"
        "Quien escribe por correo el lunes, llama el martes y abre un chat el "
        "miércoles está teniendo **una** conversación. Tres hilos separados hacen "
        "que el agente pregunte tres veces lo mismo, que es lo que el cliente "
        "resume como «no os enteráis de nada»."
    ),
)
def historial(
    db: DbDep,
    principal: AutenticadoDep,
    contacto_id: UUID | None = Query(None),
    identidad: str = Query("", max_length=320),
    limite: int = Query(200, ge=1, le=1000),
    incluir_internos: bool = Query(
        True,
        description=(
            "Cierto por defecto porque esta vista es la del agente y las notas "
            "internas son justo lo que le ahorra releerse el caso. Quien pinte "
            "esto en un portal de cliente tiene que pasarlo en **falso**"
        ),
    ),
) -> Any:
    return omni.historial(
        db,
        principal.tenant_id,
        contacto_id=contacto_id,
        identidad=identidad,
        limite=limite,
        incluir_internos=incluir_internos,
    )


class Responder(BaseModel):
    cuerpo: str = Field(min_length=1)
    canal: str = ""
    interno: bool = Field(
        False,
        description=(
            "Una nota interna **no** cuenta como primera respuesta: el indicador "
            "mide cuándo contestó una persona al cliente, y si contaran las notas "
            "saldría siempre magnífico sin medir nada"
        ),
    )


@router_conversaciones.post(
    "/{conversacion_id}/responder",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Responder al cliente o dejar una nota interna",
)
def responder(
    conversacion_id: UUID, datos: Responder, uow: UowDep, principal: AutenticadoDep
) -> Any:
    mensaje = omni.responder(
        uow,
        conversacion_id,
        cuerpo=datos.cuerpo,
        canal=datos.canal,
        interno=datos.interno,
        autor_id=principal.usuario_id,
    )
    return {"id": str(mensaje.id), "interno": mensaje.interno}


class Transferir(BaseModel):
    canal: str = Field(description=" | ".join(omni.CANALES))
    motivo: str = ""


@router_conversaciones.post(
    "/{conversacion_id}/transferir",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Cambiar de canal conservando el hilo",
    description=(
        "Cambiar de canal **no abre una conversación nueva**. Si la abriera, "
        "pasar de chat a correo haría perder todo lo hablado y el cliente tendría "
        "que explicarse otra vez — que es lo que se siente como «me habéis pasado "
        "con otro y no sabe nada»."
    ),
)
def transferir(
    conversacion_id: UUID, datos: Transferir, uow: UowDep, principal: AutenticadoDep
) -> Any:
    fila = omni.transferir_canal(uow, conversacion_id, canal=datos.canal, motivo=datos.motivo)
    return {"id": str(fila.id), "canal_actual": fila.canal_actual}


class Escalar(BaseModel):
    motivo: str = Field(min_length=1, max_length=1000)
    resumen: str = ""


@router_conversaciones.post(
    "/{conversacion_id}/escalar-a-humano",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Pasar del bot a una persona con todo el contexto",
    description=(
        "Lo que se traspasa es **el contexto completo**, no un aviso. Escalar "
        "diciendo solo «el cliente quiere hablar con alguien» obliga a la persona "
        "a leerse la conversación entera mientras el cliente espera, y eso hace "
        "que el cliente repita todo lo que acaba de contarle al bot — la peor "
        "experiencia posible, porque acaba de invertir cinco minutos en ello.\n\n"
        "El contexto va **en la respuesta** y no solo en un evento: quien recoge "
        "la conversación tiene que verlo ahí mismo, sin buscar."
    ),
)
def escalar(conversacion_id: UUID, datos: Escalar, uow: UowDep, principal: AutenticadoDep) -> Any:
    return omni.escalar_a_humano(uow, conversacion_id, motivo=datos.motivo, resumen=datos.resumen)


# ── Macros ────────────────────────────────────────────────────────────────


class CrearMacro(BaseModel):
    clave: str = Field(max_length=80)
    nombre: str = Field(max_length=200)
    cuerpo: str = ""
    acciones: dict[str, Any] = Field(default_factory=dict)
    canales: list[str] = Field(default_factory=list)


@router_macros.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Crear una respuesta rápida o acción compuesta",
    description=(
        "Una macro puede escribir **y hacer**: contestar, cambiar el estado, "
        "poner categoría y cerrar, todo de una vez. Que sea una sola acción es el "
        "punto: partida en cuatro clics, la mitad de las veces se queda a medias "
        "y el caso acaba contestado pero sin clasificar."
    ),
)
def crear_macro(datos: CrearMacro, uow: UowDep, principal: AutenticadoDep) -> Any:
    fila = omni.Macro(tenant_id=principal.tenant_id, **datos.model_dump())
    uow.db.add(fila)
    uow.db.flush()
    return {"id": str(fila.id), "clave": fila.clave}


class AplicarMacro(BaseModel):
    conversacion_id: UUID
    contexto: dict[str, dict[str, Any]] = Field(default_factory=dict)
    forzar: bool = False


@router_macros.post(
    "/{clave}/aplicar",
    dependencies=[Depends(exige_permiso("case:write"))],
    summary="Aplicar la macro a una conversación",
    description=(
        "Si quedan **variables sin resolver no se manda**, salvo que se fuerce: "
        "es la diferencia entre una macro que ahorra tiempo y una que manda «Hola "
        "{contacto.nombre}» a un cliente — el error más visible y más barato de "
        "evitar que hay en un servicio de atención.\n\n"
        "Una acción que no se puede aplicar **no se ignora en silencio**: "
        "ignorarla haría que la macro pareciera funcionar y el caso quedara a "
        "medias sin que nadie lo notara."
    ),
)
def aplicar_macro(clave: str, datos: AplicarMacro, uow: UowDep, principal: AutenticadoDep) -> Any:
    return omni.aplicar_macro(
        uow,
        macro_clave=clave,
        conversacion_id=datos.conversacion_id,
        contexto=datos.contexto,
        autor_id=principal.usuario_id,
        forzar=datos.forzar,
    )


@router_macros.get(
    "",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Macros disponibles, las más usadas primero",
)
def listar_macros(db: DbDep, principal: AutenticadoDep) -> Any:
    filas = (
        db.execute(
            select(omni.Macro)
            .where(omni.Macro.tenant_id == principal.tenant_id, omni.Macro.activa.is_(True))
            .order_by(omni.Macro.usos.desc(), omni.Macro.nombre)
        )
        .scalars()
        .all()
    )
    return [
        {"clave": m.clave, "nombre": m.nombre, "canales": m.canales, "usos": m.usos} for m in filas
    ]


# ── Consola embebible (CRM-04.02.02.08) ───────────────────────────────────


@router_consola.get(
    "",
    dependencies=[Depends(exige_permiso("case:read"))],
    summary="Todo lo que necesita una consola de agente, en una llamada",
    description=(
        "Una sola llamada y no seis a propósito: una consola que abre seis "
        "peticiones para pintar una pantalla tarda lo que tarde la más lenta, y "
        "el agente lo ve como un producto lento aunque cinco vayan rápido.\n\n"
        "Devuelve **datos y no pantallas**: es lo que permite empotrarla en el "
        "front oficial, en el portal del cliente o en el producto del propio "
        "cliente sin reimplementar nada."
    ),
)
def consola(db: DbDep, principal: AutenticadoDep) -> Any:
    return omni.consola(db, principal.tenant_id, principal.usuario_id)


ROUTERS_OMNICANAL = [
    router_canales,
    router_conversaciones,
    router_macros,
    router_consola,
]
ROUTERS_SIN_PREFIJO = [router_entrada]
