"""La calidad del dato del lead (09-11-2026).

CRM-01.01.04.06 ficha buena del lead con su procedencia · CRM-01.01.04.02
umbral de duplicado por objeto en la deduplicación de leads.

Misma forma que `/calidad-dato` de `party` —las mismas rutas colgadas de
`/leads/calidad-dato`, con `lead` como objeto—, para que la pantalla de Calidad
del dato trate el lead como un objeto más y sólo cambie a quién pregunta.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.errors import ErrorValidacion
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso
from crmcore.runtime import settings as rt
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from services.sales import golden_leads as gl

router = APIRouter(prefix="/leads/calidad-dato", tags=["calidad del dato"])


def _solo_lead(objeto: str) -> None:
    if objeto != gl.OBJETO:
        raise ErrorValidacion(
            "Aquí sólo se compone el lead; cuentas y contactos están en /calidad-dato.",
            error_code="golden.objeto_no_soportado",
            detalle={"admitidos": [gl.OBJETO]},
        )


class ReglaIn(BaseModel):
    estrategia: str = Field(..., examples=["mayor_confianza"])
    confianza_por_fuente: dict[str, int] = Field(
        default_factory=dict, examples=[{"feria": 90, "crm": 60, "duplicado": 30}]
    )
    activa: bool = True
    nota: str = Field("", max_length=1000)


class ComponerIn(BaseModel):
    aplicar: bool = Field(
        False,
        description=(
            "Falso: compone y guarda, sin tocar el lead. Verdadero: además escribe "
            "en el lead los valores ganadores"
        ),
    )


@router.get(
    "/golden/reglas/{objeto}",
    dependencies=[Depends(exige_permiso("lead:read"))],
    summary="Las reglas de supervivencia del lead",
    description=(
        "Por campo, con la confianza de cada fuente. El campo `*` es la regla por "
        "defecto del lead. Devuelve también qué campos se componen y qué "
        "estrategias hay, para que la pantalla no las tenga escritas."
    ),
)
def reglas_golden(objeto: str, db: DbDep, principal: AutenticadoDep) -> Any:
    _solo_lead(objeto)
    return gl.reglas(db, principal.tenant_id)


@router.put(
    "/golden/reglas/{objeto}/{campo}",
    dependencies=[Depends(exige_permiso("lead:configurar"))],
    summary="Guardar la regla de supervivencia de un campo del lead",
    description=(
        "Es configuración del tenant: queda en la auditoría. Una fuente que no "
        "aparece en la confianza vale 50. Las fuentes de un lead son `crm`, el "
        "canal de cada captura fusionada y `duplicado`."
    ),
)
def guardar_regla_golden(objeto: str, campo: str, cuerpo: ReglaIn, uow: UowDep) -> Any:
    _solo_lead(objeto)
    return gl.guardar_regla(
        uow,
        campo=campo,
        estrategia=cuerpo.estrategia,
        confianza_por_fuente=cuerpo.confianza_por_fuente,
        activa=cuerpo.activa,
        nota=cuerpo.nota,
    )


@router.delete(
    "/golden/reglas/{objeto}/{campo}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(exige_permiso("lead:configurar"))],
    summary="Quitar la regla de un campo del lead (vuelve a la del objeto)",
)
def borrar_regla_golden(objeto: str, campo: str, uow: UowDep) -> None:
    _solo_lead(objeto)
    gl.borrar_regla(uow, campo)


@router.get(
    "/golden/candidatas",
    dependencies=[Depends(exige_permiso("lead:read"))],
    summary="Leads con más de una versión de la verdad",
    description=(
        "Los que tienen capturas fusionadas o leads señalados como su duplicado: "
        "es donde varias fuentes dicen cosas distintas de la misma persona."
    ),
)
def golden_candidatas(
    db: DbDep, principal: AutenticadoDep, limite: int = Query(50, ge=1, le=200)
) -> Any:
    return gl.con_varias_versiones(db, principal.tenant_id, limite=limite)


@router.post(
    "/golden/{objeto}/{lead_id}/componer",
    dependencies=[Depends(exige_permiso("lead:write"))],
    summary="Componer —y guardar— la ficha buena de un lead",
    description=(
        "Los candidatos salen del CRM: lo que tiene hoy el lead, cada captura "
        "fusionada en él (su canal es la fuente) y cada lead señalado como su "
        "duplicado. Se aplican las reglas guardadas y el resultado se **guarda** "
        "con la procedencia de cada valor. Con `aplicar` se escribe además en el "
        "lead, con el antes en la auditoría."
    ),
)
def componer_golden(
    objeto: str, lead_id: UUID, cuerpo: ComponerIn, uow: UowDep, principal: AutenticadoDep
) -> Any:
    _solo_lead(objeto)
    return gl.componer(uow, lead_id=lead_id, aplicar=cuerpo.aplicar, por=principal.id)


@router.get(
    "/golden/{objeto}/{lead_id}",
    dependencies=[Depends(exige_permiso("lead:read"))],
    summary="La ficha buena guardada de un lead",
)
def golden_guardado(objeto: str, lead_id: UUID, db: DbDep, principal: AutenticadoDep) -> Any:
    _solo_lead(objeto)
    return gl.guardado(db, principal.tenant_id, lead_id)


# ── Umbral por objeto (CRM-01.01.04.02) ───────────────────────────────────


class UmbralesIn(BaseModel):
    por_objeto: dict[str, dict[str, float]] = Field(
        ..., examples=[{"contacto": {"sugerencia": 0.9, "bloqueo": 0.98}}]
    )


@router.get(
    "/umbrales-duplicado",
    dependencies=[Depends(exige_permiso("lead:read"))],
    summary="El umbral con el que un lead se compara con cada objeto",
    description=(
        "`lead` es contra los demás leads; `contacto`, contra los contactos del "
        "maestro. Cada uno dice si es propio o sale del general."
    ),
)
def umbrales_duplicado(db: DbDep, _: AutenticadoDep) -> Any:
    return gl.umbrales_por_objeto(db)


@router.put(
    "/umbrales-duplicado",
    dependencies=[Depends(exige_permiso("lead:configurar"))],
    summary="Fijar el umbral de duplicado del lead por objeto",
    description=(
        "Lo que no se diga para un objeto sale del umbral general del lead. "
        "Queda en el histórico de ajustes con quién lo cambió."
    ),
)
def fijar_umbrales(cuerpo: UmbralesIn, db: DbDep, principal: AutenticadoDep) -> Any:
    rt.fijar(
        db,
        "lead_dedupe_umbral_por_objeto",
        gl.validar_umbrales(cuerpo.por_objeto),
        ambito="tenant",
        ambito_id=str(principal.tenant_id),
        por=principal.id,
    )
    return gl.umbrales_por_objeto(db)


ROUTERS_CALIDAD_LEADS = [router]
