"""La ruta interna con la que `tenancy` pide a cada servicio su parte de la
copia a un sandbox (CRM-07.02.01.02). Ver `crmcore.datos.copia_sandbox`.

Firmada y fuera del contrato público: no es algo que nadie de fuera deba poder
pedir, y con el secreto compartido ya se podría pedir cualquier cosa. Se monta
en todos los servicios con base de datos desde `crear_servicio`, para que
ninguno se quede fuera de la copia sin que nadie lo note.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from crmcore.http.deps import exige_firma_interna


class CopiaSandbox(BaseModel):
    origen: UUID
    destino: UUID
    semilla: str = Field(..., min_length=8)
    porcentaje: int = Field(100, ge=1, le=100)
    anonimizar: bool = True
    conservar: list[str] = Field(
        default_factory=list, description="Identificadores que no se traducen: los usuarios"
    )


def crear_router_sandbox(servicio: str) -> APIRouter:
    router = APIRouter(prefix=f"/{servicio}/sandbox", tags=["sandbox"])

    @router.post(
        "/copiar",
        dependencies=[Depends(exige_firma_interna)],
        include_in_schema=False,
        summary="Copiar lo de este servicio de un tenant a su sandbox (interno)",
    )
    def copiar(datos: CopiaSandbox) -> Any:
        from crmcore.datos.copia_sandbox import copiar_tenant
        from crmcore.db.session import sesion

        with sesion(sistema=True) as db:
            resultado = copiar_tenant(
                db,
                servicio=servicio,
                origen=datos.origen,
                destino=datos.destino,
                semilla=datos.semilla,
                porcentaje=datos.porcentaje,
                anonimizar=datos.anonimizar,
                conservar=set(datos.conservar),
            )
            db.commit()
        return resultado

    return router
