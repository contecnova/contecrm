"""Compromisos de servicio, publicados junto a lo medido (CRM-07.04.03.30).

Los números de RPO, RTO y disponibilidad viven en la configuración y no en un
documento —eso ya estaba, y es lo que permite que el sistema avise cuando la
última copia se acerca al RPO—. Lo que faltaba es **publicarlos**: un compromiso
que solo existe en un manual no lo comprueba nadie, y el cliente al que se le
prometió no tiene forma de ver si se cumple.

Se devuelve lo prometido **y lo medido al lado**. Enseñar solo lo prometido
convierte esta pantalla en el mismo PDF de antes; enseñar solo lo medido esconde
contra qué hay que compararlo. Y lo que **no** se puede medir se dice, en vez de
devolver un cero que se leería como «se cumple».
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.config import get_settings
from crmcore.http.deps import AutenticadoDep, DbDep, exige_permiso
from fastapi import APIRouter, Depends
from sqlalchemy import select

router_compromisos = APIRouter(prefix="/compromisos", tags=["compromisos de servicio"])

TIERS = ("estandar", "premium", "enterprise")


@router_compromisos.get(
    "",
    response_model=dict,
    dependencies=[Depends(exige_permiso("tenant:read"))],
    summary="Lo prometido a este tenant, y lo medido al lado",
    description=(
        "RPO, RTO y disponibilidad del tier contratado, con lo que el sistema "
        "puede medir hoy junto a cada número. Lo que no se puede medir se dice: "
        "un cero se leería como «se cumple»."
    ),
)
def compromisos(db: DbDep, principal: AutenticadoDep) -> Any:
    from services.tenancy.modelos import Plan, Tenant

    s = get_settings()
    tenant = db.get(Tenant, principal.tenant_id) if principal.tenant_id else None
    tier = "estandar"
    if tenant is not None and tenant.plan:
        plan = db.execute(select(Plan).where(Plan.codigo == tenant.plan)).scalar_one_or_none()
        # El tier sale del plan contratado. Si el plan no declara ninguno se usa
        # el estándar: prometer de más por un dato que falta sería prometer lo
        # que no se puede cumplir.
        candidato = str((plan.capacidades or {}).get("tier", "")) if plan else ""
        if candidato in TIERS:
            tier = candidato

    return {
        "tier": tier,
        "compromisos": [
            {
                "metrica": "RPO",
                "que_es": "Cuántos minutos de datos se pueden perder como máximo",
                "comprometido": getattr(s, f"rpo_minutos_{tier}"),
                "unidad": "minutos",
                **_medido_rpo(db, principal.tenant_id),
            },
            {
                "metrica": "RTO",
                "que_es": "Cuántos minutos se tarda en volver, incluido levantar el sistema",
                "comprometido": getattr(s, f"rto_minutos_{tier}"),
                "unidad": "minutos",
                # El RTO solo se sabe ensayando una restauración: el sistema no
                # puede medirlo solo, y decir que sí sería mentir sobre la única
                # cifra que importa el día que haga falta.
                "medido": None,
                "como_se_mide": "Ensayando una restauración completa; no se deduce de la operación diaria",
            },
            {
                "metrica": "Disponibilidad",
                "que_es": "Porcentaje mensual de servicio disponible",
                "comprometido": getattr(s, f"disponibilidad_{tier}"),
                "unidad": "%",
                "medido": None,
                "como_se_mide": "Con la sonda externa del despliegue; este servicio no se mide a sí mismo",
            },
        ],
        "aviso_al_pct": s.rpo_aviso_pct,
    }


def _medido_rpo(db: Any, tenant_id: UUID | None) -> dict[str, Any]:
    """Cuánto hace de la última copia verificada de este tenant.

    Se mira la **exportación verificada** y no la última lanzada: una copia que
    no se ha releído del almacén no prueba nada, y contarla como cumplimiento
    del RPO es exactamente la trampa que hace que la restauración falle el día
    que hace falta.
    """
    from datetime import datetime, timezone

    if tenant_id is None:
        return {"medido": None, "como_se_mide": "Sin tenant en el contexto"}
    from services.tenancy.baja import Exportacion

    ultima = db.execute(
        select(Exportacion)
        .where(Exportacion.tenant_id == tenant_id, Exportacion.estado == "verificada")
        .order_by(Exportacion.verificada_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if ultima is None or ultima.verificada_at is None:
        return {
            "medido": None,
            "como_se_mide": "No hay ninguna copia verificada de este tenant todavía",
        }
    minutos = int((datetime.now(timezone.utc) - ultima.verificada_at).total_seconds() // 60)
    return {
        "medido": minutos,
        "como_se_mide": "Minutos desde la última exportación VERIFICADA, releída del almacén",
    }


ROUTERS_COMPROMISOS = [router_compromisos]
