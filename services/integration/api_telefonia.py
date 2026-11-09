"""Telefonía de verdad: perfil, avisos de la centralita, click-to-call, ficha
emergente, transferencia y registro (CRM-04.02.01.05, CRM-03.03.01.05).

Las rutas puras de `api_suites` (`/telefonia/pantalla`, `/identificar`,
`/transferir`, `POST /llamadas`) se quedan: son calculadoras publicadas en el
contrato y hay integradores que las usan con sus propios datos. Éstas son las
que llaman a la centralita, guardan la llamada y la registran en `party`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.errors import NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, exige_permiso
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from services.integration import telefonia as tel

router = APIRouter(prefix="/telefonia", tags=["telefonía"])


def identidad_de(principal: Any) -> dict[str, Any]:
    """La identidad con la que se pregunta a otros servicios: la de quien pide.

    Con sus permisos y sus roles, no con los de «la casa»: si quien manda el
    aviso no puede ver una ficha, la ficha emergente tampoco la enseña.
    """
    tipo = str(getattr(principal, "tipo", "") or "usuario")
    return {
        "tenant_id": principal.tenant_id,
        "principal_id": principal.id,
        "permisos": sorted(principal.permisos),
        "roles": sorted(principal.roles),
        "tipo": tipo if tipo in ("usuario", "agente", "automatizacion") else "agente",
    }


class PerfilIn(BaseModel):
    conexion_id: UUID
    webhook: dict[str, Any] = Field(
        ...,
        description=(
            "Cómo se lee el aviso de la centralita, con el mapeo del conector: "
            "`mapeo` de los campos (" + ", ".join(tel.CAMPOS_AVISO) + ") y, si hace "
            "falta, `transformar` (por ejemplo un `mapa` que traduzca sus nombres "
            "de evento a los de aquí: " + ", ".join(tel.EVENTOS) + ")"
        ),
        examples=[
            {
                "mapeo": {
                    "id_externo": "call_id",
                    "evento": "event",
                    "numero": ["from", "caller"],
                    "duracion_s": "duration",
                    "grabacion": "recording_url",
                    "ivr": "ivr_data",
                    "agente": "agent",
                },
                "transformar": {
                    "evento": [
                        {"f": "mapa", "arg": {"RINGING": "entrante", "ANSWERED": "contestada"}}
                    ]
                },
            }
        ],
    )


@router.get(
    "/perfil",
    dependencies=[Depends(exige_permiso("activity:read"))],
    summary="Qué telefonía está conectada y qué le falta",
    description=(
        "La conexión marcada como telefonía, si tiene declaradas las operaciones "
        "de originar y transferir, y si el aviso de la centralita se puede leer. "
        "Lo que falta se dice antes de la primera llamada, no en ella."
    ),
)
def ver_perfil(db: DbDep, principal: AutenticadoDep) -> Any:
    return tel.estado_del_perfil(db, principal.tenant_id)


@router.put(
    "/perfil",
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Conectar la telefonía sobre una conexión de integración",
    description=(
        "Marca la conexión como la telefonía del tenant y guarda cómo se lee el "
        "aviso que manda la centralita. Originar y transferir son operaciones "
        "declaradas en la propia conexión: cambiar de proveedor es configuración, "
        "no código."
    ),
)
def fijar_perfil(cuerpo: PerfilIn, db: DbDep, principal: AutenticadoDep) -> Any:
    tel.declarar_perfil(
        db, principal.tenant_id, conexion_id=cuerpo.conexion_id, webhook=cuerpo.webhook
    )
    return tel.estado_del_perfil(db, principal.tenant_id)


@router.post(
    "/avisos",
    dependencies=[Depends(exige_permiso("integracion:write"))],
    summary="Recibir un aviso de la centralita (webhook)",
    description=(
        "La centralita manda aquí cada cambio de una llamada —suena, se coge, se "
        "transfiere, se cuelga— con una clave de API del tenant. Se traduce con "
        "el mapeo del perfil, se identifica al llamante contra los contactos y "
        "cuentas de `party` (con la identidad de esa clave) y, al colgar, la "
        "llamada se registra sola como actividad con su duración y su resultado.\n\n"
        "Idempotente por el identificador de la llamada: un aviso repetido no "
        "crea otra llamada ni otra actividad."
    ),
)
def recibir_aviso(cuerpo: dict[str, Any], db: DbDep, principal: AutenticadoDep) -> Any:
    conexion = tel.perfil(db, principal.tenant_id)
    webhook = dict(dict(dict(conexion.config or {}).get("telefonia") or {}).get("webhook") or {})
    aviso = tel.traducir_aviso(webhook, cuerpo)
    llamada = tel.ingerir(
        db,
        principal.tenant_id,
        conexion=conexion,
        aviso=aviso,
        identidad=identidad_de(principal),
    )
    return tel.a_dict(llamada)


class LlamarIn(BaseModel):
    numero: str = Field(..., min_length=3, max_length=40)
    contacto_id: UUID | None = None
    cuenta_id: UUID | None = None
    grabar: bool = False
    agente: str = Field("", max_length=200, description="Extensión o usuario en la centralita")


@router.post(
    "/llamar",
    dependencies=[Depends(exige_permiso("activity:write"))],
    summary="Click-to-call: pedir a la centralita que marque",
    description=(
        "Origina la llamada en el proveedor con la operación declarada en el "
        "perfil y la guarda. Si la centralita no la acepta, la llamada queda "
        "guardada con el error: un «Llamar» que falla sin dejar rastro es el que "
        "se repite diez veces.\n\n"
        "Las comprobaciones previas —exclusión y grabación— las hace el marcador "
        "(`POST /marcador/llamar`), que es quien llama aquí."
    ),
)
def llamar(cuerpo: LlamarIn, db: DbDep, principal: AutenticadoDep) -> Any:
    llamada = tel.originar(
        db,
        principal.tenant_id,
        usuario_id=principal.id,
        numero=cuerpo.numero,
        contacto_id=cuerpo.contacto_id,
        cuenta_id=cuerpo.cuenta_id,
        grabar=cuerpo.grabar,
        agente=cuerpo.agente,
    )
    return tel.a_dict(llamada)


@router.get(
    "/sonando",
    dependencies=[Depends(exige_permiso("activity:read"))],
    summary="Las llamadas entrantes que le suenan a quien pregunta",
    description=(
        "Lo que pinta la ficha emergente: quién llama (o los candidatos si el "
        "número lo comparten varias fichas), lo que tecleó en el IVR y lo último "
        "que le pasó. Con tope de vida configurable: una llamada cuyo colgado se "
        "perdió no se queda en la pantalla para siempre."
    ),
)
def llamadas_sonando(db: DbDep, principal: AutenticadoDep) -> Any:
    from services.integration.ajustes import valor

    return {
        "llamadas": [
            tel.a_dict(x) for x in tel.sonando(db, principal.tenant_id, usuario_id=principal.id)
        ],
        "sondeo_s": int(valor("telefonia_sondeo_s", db)),
    }


@router.get(
    "/llamadas",
    dependencies=[Depends(exige_permiso("activity:read"))],
    summary="Las llamadas registradas",
    description="Las más recientes primero; de un contacto o de una cuenta si se pide.",
)
def listar_llamadas(
    db: DbDep,
    principal: AutenticadoDep,
    contacto_id: UUID | None = Query(None),
    cuenta_id: UUID | None = Query(None),
    limite: int = Query(50, ge=1, le=200),
) -> Any:
    consulta = select(tel.LlamadaTelefonica).where(
        tel.LlamadaTelefonica.tenant_id == principal.tenant_id
    )
    if contacto_id:
        consulta = consulta.where(tel.LlamadaTelefonica.contacto_id == contacto_id)
    if cuenta_id:
        consulta = consulta.where(tel.LlamadaTelefonica.cuenta_id == cuenta_id)
    filas = (
        db.execute(consulta.order_by(tel.LlamadaTelefonica.created_at.desc()).limit(limite))
        .scalars()
        .all()
    )
    return {"llamadas": [tel.a_dict(x) for x in filas]}


@router.get(
    "/llamadas/{llamada_telefonica_id}",
    dependencies=[Depends(exige_permiso("activity:read"))],
    summary="Una llamada con su historia",
)
def ver_llamada(llamada_telefonica_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    fila = db.get(tel.LlamadaTelefonica, llamada_telefonica_id)
    if fila is None or fila.tenant_id != principal.tenant_id:
        raise NoEncontrado("La llamada no existe", error_code="telefonia.llamada_no_encontrada")
    return tel.a_dict(fila)


class TransferirIn(BaseModel):
    a: str = Field(..., min_length=1, max_length=200, description="Persona, extensión o cola")
    resumen: str = Field(..., max_length=2_000)
    lo_ya_hablado: list[str] = Field(default_factory=list)


@router.post(
    "/llamadas/{llamada_telefonica_id}/transferir",
    dependencies=[Depends(exige_permiso("activity:write"))],
    summary="Transferir la llamada con el contexto dentro",
    description=(
        "Pide la transferencia a la centralita y guarda el resumen en la "
        "llamada: quien la recibe abre la misma ficha emergente y lee lo que ya "
        "se habló. Sin resumen no se transfiere."
    ),
)
def transferir(
    llamada_telefonica_id: UUID, cuerpo: TransferirIn, db: DbDep, principal: AutenticadoDep
) -> Any:
    fila = tel.transferir_llamada(
        db,
        principal.tenant_id,
        llamada_id=llamada_telefonica_id,
        a=cuerpo.a,
        resumen=cuerpo.resumen,
        lo_ya_hablado=cuerpo.lo_ya_hablado,
        por=principal.id,
    )
    return tel.a_dict(fila)


class ResultadoIn(BaseModel):
    resultado_comercial: str = Field(..., min_length=1, max_length=40)
    nota: str = Field("", max_length=10_000)


@router.post(
    "/llamadas/{llamada_telefonica_id}/resultado",
    dependencies=[Depends(exige_permiso("activity:write"))],
    summary="Anotar cómo fue la llamada y qué se habló",
    description=(
        "Lo que sólo sabe la persona. La nota va a la actividad que se creó al "
        "colgar: no se inventa, y si no se escribe se queda vacía."
    ),
)
def anotar(
    llamada_telefonica_id: UUID, cuerpo: ResultadoIn, db: DbDep, principal: AutenticadoDep
) -> Any:
    fila = tel.anotar_resultado(
        db,
        principal.tenant_id,
        llamada_id=llamada_telefonica_id,
        resultado_comercial=cuerpo.resultado_comercial,
        nota=cuerpo.nota,
        invocar=tel._invocar,
        identidad=identidad_de(principal),
    )
    return tel.a_dict(fila)


ROUTERS_TELEFONIA = [router]
