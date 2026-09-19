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

    return router
