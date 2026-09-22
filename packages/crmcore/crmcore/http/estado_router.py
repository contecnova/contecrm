"""La página de estado que publica cada servicio (CRM-00.06.01.06).

Se monta sola en `crear_servicio`, como la salud y la superficie. Si dependiera
de que cada servicio se acuerde, faltaría en alguno —precisamente en el que
menos se mira— y la página del cliente tendría un agujero sin decirlo.

Cada servicio publica **lo suyo**. El gateway junta las páginas de todos y
devuelve una sola, que es lo que ve el cliente: `GET /api/v1/estado`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from crmcore.http.deps import AutenticadoDep, DbDep


def crear_router_estado(servicio: str) -> APIRouter:
    router = APIRouter(prefix="/estado", tags=["estado del servicio"])

    @router.get(
        "",
        summary=f"Estado de «{servicio}» para este tenant",
        description=(
            "Los componentes de **este servicio** para el tenant que pregunta, "
            "calculados en vivo. La página completa —con la de todos los "
            "servicios— la sirve el gateway en la misma ruta.\n\n"
            "Se calcula en vivo a propósito: una página de estado cacheada "
            "enseña «todo bien» mientras el cliente mira una pantalla que no "
            "carga, y eso destruye más confianza que no tener página."
        ),
    )
    def estado(db: DbDep, principal: AutenticadoDep) -> Any:
        from crmcore.datos.estado import calcular

        return {"servicio": servicio, **calcular(db, principal.tenant_id)}

    @router.get(
        "/contratos",
        summary=f"Contratos de evento que «{servicio}» consume y cumple",
        description=(
            "Contract testing interno dirigido por el consumidor "
            "(CRM-00.03.01.03): qué campos de qué eventos necesita este "
            "servicio, qué promesas no se sostienen y —lo que más cuesta "
            "encontrar en otros sitios— qué parte del contrato se ha visto "
            "cumplirse de verdad y cuál solo está escrita.\n\n"
            "La cobertura se cuenta sobre emisiones observadas, no sobre "
            "campos declarados: un 100 % de campos declarados sin una sola "
            "emisión observada sería un informe que dice que todo va bien sin "
            "haber mirado."
        ),
    )
    def contratos_de_evento(principal: AutenticadoDep) -> Any:
        from crmcore import contratos

        return {"servicio": servicio, **contratos.informe()}

    @router.get(
        "/slo",
        summary=f"Presupuesto de error de «{servicio}» para este tenant",
        description=(
            "SLO y error budget (CRM-00.06.01.04): cuántas peticiones de este "
            "tenant ha servido este servicio en el periodo, cuántas fallaron y "
            "cuántas llegaron tarde, y cuánto margen queda antes de incumplir "
            "lo prometido.\n\n"
            "El tier se pasa como parámetro porque **este servicio no lo sabe**: "
            "el plan contratado vive en `tenancy` y ningún servicio lee el "
            "esquema de otro. Quien compone la vista completa —el gateway— lo "
            "resuelve una vez y se lo dice a todos. Sin tier se responde con el "
            "estándar, que es lo que se promete por defecto.\n\n"
            "Sin tráfico se responde «no medible» en vez de 100 %: un servicio "
            "que nadie ha usado no ha demostrado nada."
        ),
    )
    async def slo_del_servicio(principal: AutenticadoDep, tier: str = "estandar") -> Any:
        from crmcore.config import get_settings
        from crmcore.obs import slo

        objetivo = slo.objetivo_de(servicio, tier)
        consumo = await slo.consumo_de(servicio, principal.tenant_id, tier=objetivo.tier)
        return slo.presupuesto(objetivo, consumo, dias_del_periodo=get_settings().slo_dias_periodo)

    return router
