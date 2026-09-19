"""Router de búsqueda reutilizable por cada servicio (CRM-00.01.01.09).

Fábrica, como las de adjuntos, comentarios y retención, y por el mismo motivo:
el índice vive **en el esquema del servicio dueño de los datos**, que es lo que
hace que RLS lo cubra igual que a todo lo demás. Un índice central compartido
tendría que reimplementar el aislamiento por su cuenta, y sería la única pieza
del sistema donde el aislamiento no viene de donde viene en todas las demás.

La búsqueda **global** —la que mira en todos los servicios a la vez— la compone
el gateway preguntando a cada uno. Así ningún servicio necesita leer el esquema
de otro, y añadir un servicio nuevo a la búsqueda es añadirlo a la lista del
gateway, no tocar un índice compartido.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from crmcore.busqueda import buscar
from crmcore.http.deps import AutenticadoDep, DbDep


def crear_router_busqueda(objetos: set[str], prefijo: str = "/buscar") -> APIRouter:
    """Construye el router de búsqueda para los objetos del servicio."""
    router = APIRouter(prefix=prefijo, tags=["búsqueda"])

    @router.get(
        "",
        response_model=dict,
        summary="Buscar en los registros de este servicio",
        description=(
            "Texto libre sobre el índice del tenant. Acepta lo que la gente "
            "escribe de verdad —comillas para una frase exacta, `-palabra` para "
            "excluir— y no falla con un paréntesis suelto: un error de sintaxis "
            "delante de quien solo estaba buscando un cliente no tiene sentido."
        ),
    )
    def buscar_aqui(
        db: DbDep,
        principal: AutenticadoDep,
        q: str = Query(..., min_length=1, max_length=300, description="Qué buscar"),
        objeto: list[str] | None = Query(None, description="Acotar a estos tipos"),
        limite: int | None = Query(None, ge=1, le=200),
    ) -> Any:
        from crmcore.runtime import settings as rt

        pedidos = [o for o in (objeto or []) if o in objetos] or sorted(objetos)
        tope = limite or int(rt.efectivo("busqueda_max_resultados", db) or 20)
        resultados = buscar(
            db, tenant_id=principal.tenant_id, texto=q, objetos=pedidos, limite=tope
        )
        return {
            "consulta": q,
            "objetos": pedidos,
            "total": len(resultados),
            "resultados": [r.a_dict() for r in resultados],
        }

    @router.get(
        "/objetos",
        response_model=list[str],
        summary="Qué se puede buscar en este servicio",
    )
    def objetos_buscables() -> Any:
        return sorted(objetos)

    return router
