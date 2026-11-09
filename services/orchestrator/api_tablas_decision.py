"""Probar una tabla de decisión SIN guardarla (CRM-00.03.02.10).

La API de las tablas evaluaba sólo la guardada (`POST /{clave}/evaluar`), y eso
deja al editor sin lo que más necesita: ver qué saldría con unos datos ANTES de
publicar el cambio. Probar sobre lo publicado obliga a publicar para probar, y
publicar es justo lo que no se quiere hacer con una tabla que aún no se sabe si
está bien —la usan los procesos en marcha—.

`decision.evaluar` ya aceptaba un diccionario «para simular una tabla antes de
guardarla»; sólo le faltaba la puerta.
"""

from __future__ import annotations

from typing import Any

from crmcore.http.deps import exige_permiso
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from services.orchestrator.esquemas import TablaEditada

router_probar_tabla = APIRouter(prefix="/tablas-decision", tags=["tablas de decisión"])


class ProbarTabla(BaseModel):
    tabla: TablaEditada
    variables: dict[str, Any] = Field(
        default_factory=dict,
        description="Los datos de entrada, con la forma que leen las expresiones de las columnas",
        examples=[{"oportunidad": {"importe": 60000, "descuento_pct": 12}}],
    )


@router_probar_tabla.post(
    "/probar",
    dependencies=[Depends(exige_permiso("proceso:read"))],
    summary="Probar una tabla con unos datos, sin guardarla",
    description=(
        "Devuelve lo mismo que evaluar la guardada —qué salió, qué reglas "
        "casaron y en qué condición falló cada una de las demás— pero sobre la "
        "tabla que se manda. No guarda nada ni ejecuta nada."
    ),
)
def probar_tabla(cuerpo: ProbarTabla) -> Any:
    from crmcore.errors import ErrorValidacion

    from services.orchestrator import decision as dec

    tabla = cuerpo.tabla.model_dump(exclude_none=True)
    problemas = dec.validar(tabla)
    if problemas:
        # Evaluar una tabla mal formada daría una respuesta que no significa
        # nada —reglas que comparan contra columnas que no existen—. Se dice qué
        # le falta, igual que al guardar.
        raise ErrorValidacion(
            "La tabla de decisión tiene problemas",
            error_code="decision.tabla_invalida",
            detalle={"problemas": problemas},
        )
    return dec.evaluar(tabla, cuerpo.variables).a_dict()
