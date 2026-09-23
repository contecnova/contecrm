"""API de doble opt-in, cookies y cumplimiento de contenido
(CRM-02.04.02.02, CRM-07.03.01.08, CRM-02.04.01.03).

Todas estas rutas existen para poder demostrar algo dos años después. Por eso
ninguna devuelve solo «sí» o «no»: devuelven el porqué, la fecha y la versión del
texto, que es lo que se pide cuando llega la reclamación.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.http.listados import montar_listado
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from services.marketing import consentimiento as cons
from services.marketing.consentimiento import ConsentimientoCookies, ReglaContenido

router_optin = APIRouter(prefix="/optin", tags=["consentimiento"])
router_cookies = APIRouter(prefix="/cookies", tags=["consentimiento"])
router_contenido = APIRouter(prefix="/reglas-contenido", tags=["cumplimiento de contenido"])


class PedirConfirmacion(BaseModel):
    destino: str = Field(..., min_length=3, max_length=320)
    canal: str = "email"
    finalidad: str = "comercial"
    texto_aceptado: str = Field(
        ...,
        min_length=1,
        description="El texto que se le enseña. Sin él la prueba es una casilla marcada.",
    )
    ip: str = ""
    horas_validez: int = Field(72, ge=1, le=720)


class Confirmar(BaseModel):
    token: str = Field(..., min_length=10)
    ip: str = ""


class DecisionCookies(BaseModel):
    visitante: str = Field(..., min_length=1, max_length=80)
    categorias: dict[str, bool] = Field(default_factory=dict)
    version_aviso: str = Field(..., min_length=1, max_length=40)
    ip: str = ""
    agente: str = ""
    contacto_id: UUID | None = None
    meses_validez: int = Field(12, ge=1, le=60)


class DeclararRegla(BaseModel):
    marca: str = ""
    pais: str = ""
    idioma: str = ""
    plantillas_bloqueadas: list[str] | None = None
    exige_textos: list[str] | None = None
    prohibe_textos: list[str] | None = None
    notas: str = ""


class ComprobarContenido(BaseModel):
    cuerpo: str
    plantilla: str = ""
    marca: str = ""
    pais: str = ""
    idioma: str = ""
    cuerpo_de_la_plantilla: str = ""


@router_optin.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("campana:write"))],
    summary="Pedir confirmación de un alta (doble opt-in)",
    description=(
        "Mientras no confirme **no es un alta** y no se le escribe. Registrarla "
        "como válida y mandar mientras tanto da apariencia de rigor a lo "
        "contrario, que es peor que no tener doble opt-in."
    ),
)
def pedir_confirmacion(cuerpo: PedirConfirmacion, uow: UowDep) -> Any:
    return cons.pedir_confirmacion(uow, **cuerpo.model_dump())


@router_optin.post(
    "/confirmar",
    dependencies=[Depends(exige_permiso("campana:write"))],
    summary="Confirmar con el enlace recibido",
    description=(
        "El enlace caduca: uno eterno acaba confirmando altas que nadie recuerda "
        "haber pedido. Confirmar dos veces no falla, pero **no mueve la fecha** — "
        "la que prueba el consentimiento es la primera."
    ),
)
def confirmar(cuerpo: Confirmar, uow: UowDep) -> Any:
    return cons.confirmar(uow, token=cuerpo.token, ip=cuerpo.ip)


@router_optin.get(
    "/renovaciones",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="Consentimientos que caducan o han caducado",
    description=(
        "Los ya caducados **no se pueden usar**: el envío lo comprueba solo. Esta "
        "lista sirve para renovarlos a tiempo, no para seguir enviando mientras "
        "alguien la revisa."
    ),
)
def renovaciones(
    db: DbDep, principal: AutenticadoDep, dias_aviso: int = Query(30, ge=1, le=365)
) -> Any:
    return cons.renovaciones_pendientes(db, principal.tenant_id, dias_aviso=dias_aviso)


@router_cookies.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("campana:write"))],
    summary="Guardar la decisión de cookies de un visitante (CRM-07.03.01.08)",
    description=(
        "Por **categoría** y con la **versión del aviso**: un «acepto» sobre un "
        "texto que después cambió no prueba nada sobre el texto nuevo, y es "
        "exactamente lo que se discute cuando llega una reclamación.\n\n"
        "Cada decisión es una fila nueva: actualizar la anterior borraría la "
        "prueba de lo que se aceptó cuando se puso la cookie."
    ),
)
def registrar_cookies(cuerpo: DecisionCookies, uow: UowDep) -> Any:
    return cons.registrar_cookies(uow, **cuerpo.model_dump())


@router_cookies.get(
    "/puede-rastrear",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="Si se puede activar una categoría para este visitante",
    description=(
        "Sin decisión previa la respuesta es **no**. El silencio no es un sí: "
        "tratarlo como tal es la infracción más común de todas."
    ),
)
def puede_rastrear(
    db: DbDep,
    principal: AutenticadoDep,
    visitante: str = Query(...),
    categoria: str = Query(...),
    version_aviso: str = Query(""),
) -> Any:
    return cons.puede_rastrear(
        db,
        principal.tenant_id,
        visitante=visitante,
        categoria=categoria,
        version_aviso=version_aviso,
    )


@router_contenido.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(exige_permiso("campana:write"))],
    summary="Declarar qué se puede mandar por marca, país e idioma",
    description=(
        "El campo vacío es **comodín**: una regla sin país vale para todos. Así "
        "la regla general se escribe una vez y las excepciones se añaden encima."
    ),
)
def declarar_regla(cuerpo: DeclararRegla, uow: UowDep) -> Any:
    fila = cons.declarar_regla(uow, **cuerpo.model_dump())
    return {
        "id": str(fila.id),
        "marca": fila.marca,
        "pais": fila.pais,
        "idioma": fila.idioma,
        "plantillas_bloqueadas": fila.plantillas_bloqueadas,
    }


@router_contenido.post(
    "/comprobar",
    dependencies=[Depends(exige_permiso("campana:read"))],
    summary="Comprobar un contenido antes de mandarlo (CRM-02.04.01.03)",
    description=(
        "**Una plantilla bloqueada no se puede editar.** Si el bloqueo fuese un "
        "aviso, se ignoraría el día que hay prisa — justo el día en que se manda "
        "a otro país el texto que allí no cumple.\n\n"
        "Y que no haya reglas declaradas **no es cumplir**: la respuesta lo dice, "
        "para que nadie lea un «se puede mandar» como una aprobación."
    ),
)
def comprobar_contenido(cuerpo: ComprobarContenido, db: DbDep, principal: AutenticadoDep) -> Any:
    return cons.comprobar_contenido(db, principal.tenant_id, **cuerpo.model_dump())


# ── Listados ──────────────────────────────────────────────────────────────
# Estas colecciones se podían crear y no se podían leer: tenían `POST` y no
# tenían `GET`, así que lo que se daba de alta desaparecía de la vista. La API
# contestaba 405 y el front —que las declara listables— enseñaba una pantalla
# vacía sin decir por qué.

montar_listado(
    router_cookies,
    modelo=ConsentimientoCookies,
    objeto="consentimiento_cookies",
    permiso="campana:read",
    nombre="Decisiones de cookies",
)
montar_listado(
    router_contenido,
    modelo=ReglaContenido,
    objeto="regla_contenido",
    permiso="campana:read",
    nombre="Reglas de contenido",
)


ROUTERS_CONSENTIMIENTO = [router_optin, router_cookies, router_contenido]
