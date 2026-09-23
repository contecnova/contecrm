"""API de las suites de productividad (CRM-06.01.03.01 a .10).

El perfil lo declara un administrador; **autorizar lo hace cada persona**. Esa
separación no es burocracia: un administrador que conecta el correo de su equipo
entero desde una pantalla es exactamente lo que hace que una integración acabe
discutiéndose en el comité de empresa.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from services.integration import suites as su
from services.integration import suites_recursos as sur

router_suites = APIRouter(prefix="/suites", tags=["suites de productividad"])


class PerfilIn(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=200)
    sistema: str = Field("", max_length=80, description="Informativo: no cambia el comportamiento")
    config: dict[str, Any] = Field(default_factory=dict)


class ConsentimientoIn(BaseModel):
    perfil: str
    recursos: list[str]
    sentido: str = "leer"


class SuscripcionIn(BaseModel):
    perfil: str
    recurso: str
    externo_id: str
    caduca_at: datetime | None = None


class ReunionIn(BaseModel):
    perfil: str
    asunto: str
    inicio: datetime
    fin: datetime
    confirmada: bool = False
    asistentes: list[str] = Field(default_factory=list)


@router_suites.post(
    "/perfiles",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integration:write"))],
    summary="Declarar un proveedor de productividad como configuración",
    description=(
        "Outlook y Gmail son el mismo problema con otras URLs. Un proveedor es un "
        "**perfil declarado** —qué recursos ofrece, en qué endpoint, con qué "
        "campos, cómo pide el incremento y qué límites tiene—, no un módulo: en "
        "cuanto se escribe un módulo por casa, cada implantación nueva es una "
        "versión del producto.\n\n"
        "Se rechaza el perfil incompleto y se dicen **todos** los problemas de "
        "una vez. Un perfil sin correspondencia de campos no sustituye a nada, y "
        "uno que declara alcances de recursos que no usa pide permisos de más — "
        "que es justo por lo que a muchas integraciones no las dejan entrar."
    ),
)
def declarar_perfil(cuerpo: PerfilIn, uow: UowDep) -> Any:
    fila = su.declarar_perfil(
        uow, nombre=cuerpo.nombre, sistema=cuerpo.sistema, config=cuerpo.config
    )
    return {"id": str(fila.id), "nombre": fila.nombre, **su.capacidades_de(dict(fila.config))}


@router_suites.post(
    "/perfiles/comprobar",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Qué le falta a este perfil, sin guardarlo",
)
def comprobar_perfil(cuerpo: PerfilIn, principal: AutenticadoDep) -> Any:
    return su.validar_perfil(cuerpo.config)


@router_suites.get(
    "/perfiles/{nombre}/capacidades",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Qué sabe hacer este perfil, antes de conectar nada",
    description=(
        "Con el dato de terceros **marcado**. Quien va a autorizar tiene derecho "
        "a saber que sincronizar sus contactos sube al CRM el teléfono de su "
        "médico, y esa frase tiene que poder ponerse en la pantalla de permiso."
    ),
)
def capacidades(nombre: str, db: DbDep, principal: AutenticadoDep) -> Any:
    return su.capacidades_de(su.perfil(db, principal.tenant_id, nombre))


@router_suites.post(
    "/consentimiento",
    status_code=status.HTTP_201_CREATED,
    summary="Autorizar el acceso a los propios recursos",
    description=(
        "**Lo concede el dueño del buzón, y solo él.** No hay permiso de "
        "administrador que valga: un administrador puede declarar el perfil y "
        "pedirlo; autorizarlo por otra persona, no.\n\n"
        "Se concede **recurso a recurso**, que es lo que permite contestar "
        "después qué se autorizó exactamente — «conectó su Microsoft 365» no es "
        "una respuesta cuando alguien pregunta si el CRM lee sus correos.\n\n"
        "Y se pide el **alcance mínimo**: los alcances de los recursos que se van "
        "a usar y ni uno más."
    ),
)
def conceder(cuerpo: ConsentimientoIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    config = su.perfil(uow.db, uow.tenant_id, cuerpo.perfil)
    alcance = su.alcance_minimo(config=config, recursos=cuerpo.recursos, sentido=cuerpo.sentido)
    salida = su.conceder(
        uow,
        usuario_id=principal.id,
        quien_concede=principal.id,
        perfil_nombre=cuerpo.perfil,
        recursos=cuerpo.recursos,
        alcances=alcance["alcances"],
        sentido=cuerpo.sentido,
    )
    return {**salida, "no_se_piden": alcance["no_se_piden"]}


@router_suites.delete(
    "/consentimiento/{perfil}",
    summary="Retirar el permiso",
    description=(
        "Revocar **no borra lo ya sincronizado**, y se dice: lo que entró son "
        "actividades del CRM que otra gente ha usado. Lo que se para es que entre "
        "más. Borrar lo anterior es otra decisión y se pide aparte."
    ),
)
def revocar(perfil: str, uow: UowDep, principal: AutenticadoDep) -> Any:
    return su.revocar(uow, usuario_id=principal.id, perfil_nombre=perfil)


@router_suites.post(
    "/suscripciones",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("integration:write"))],
    summary="Registrar una suscripción a los cambios del proveedor",
    description=(
        "Se exige el identificador que devolvió el proveedor: sin él no se puede "
        "renovar ni borrar, y queda una suscripción huérfana mandando avisos a "
        "una URL que ya no los atiende.\n\n"
        "Se rechaza una segunda suscripción al mismo recurso desde otro perfil: "
        "con dos, cada cambio entra dos veces y la ficha acaba con la misma "
        "reunión duplicada."
    ),
)
def suscribir(cuerpo: SuscripcionIn, uow: UowDep, principal: AutenticadoDep) -> Any:
    su.exigir_sin_conflicto(
        uow.db,
        uow.tenant_id,
        usuario_id=principal.id,
        recurso=cuerpo.recurso,
        perfil_nombre=cuerpo.perfil,
    )
    fila = su.suscribir(
        uow,
        usuario_id=principal.id,
        perfil_nombre=cuerpo.perfil,
        recurso=cuerpo.recurso,
        externo_id=cuerpo.externo_id,
        caduca_at=cuerpo.caduca_at,
    )
    return {"id": str(fila.id), "recurso": fila.recurso, "estado": fila.estado}


@router_suites.get(
    "/suscripciones/por-renovar",
    dependencies=[Depends(exige_permiso("integration:read"))],
    summary="Qué suscripciones hay que renovar ya",
    description=(
        "Con margen y no en el último momento: renovar justo al caducar deja que "
        "un reintento fallido la mate, y entonces el flujo se para **sin dar "
        "ningún error** — el CRM se queda quieto y el usuario cree que no ha "
        "pasado nada en su buzón.\n\n"
        "Se avisa aparte de las que no declaran caducidad. Todas caducan: la que "
        "no lo dice es la que se muere sin que nadie lo vea venir."
    ),
)
def suscripciones_por_renovar(db: DbDep, principal: AutenticadoDep) -> Any:
    return su.por_renovar(db, principal.tenant_id)


@router_suites.post(
    "/reuniones",
    dependencies=[Depends(exige_permiso("integration:write"))],
    summary="Preparar una reunión en línea con el proveedor del tenant",
    description=(
        "No se crea la sala hasta que la reunión está **confirmada**: crearla al "
        "proponer la hora deja salas abiertas de todas las que no cuajaron, y "
        "alguien acaba entrando a una vacía convencido de que le han dado "
        "plantón.\n\n"
        "El enlace **es una credencial**: quien lo tiene entra. Por eso la "
        "respuesta dice dónde puede ir y dónde no — y un push no es uno de los "
        "sitios donde puede ir."
    ),
)
def reunion(cuerpo: ReunionIn, db: DbDep, principal: AutenticadoDep) -> Any:
    return sur.crear_reunion(
        perfil_config=su.perfil(db, principal.tenant_id, cuerpo.perfil),
        asunto=cuerpo.asunto,
        inicio=cuerpo.inicio,
        fin=cuerpo.fin,
        confirmada=cuerpo.confirmada,
        asistentes=cuerpo.asistentes,
    )


ROUTERS_SUITES = [router_suites]
