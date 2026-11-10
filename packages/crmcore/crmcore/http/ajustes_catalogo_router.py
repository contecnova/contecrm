"""Los ajustes que declara cada servicio, publicados para la consola.

La consola de ajustes vive en `tenancy`, y `tenancy` no puede importar el
`ajustes.py` de otro servicio (CRM-00.03.01.02). Hasta el 10-11-2026 eso dejaba
la consola sabiendo sólo de las claves del núcleo: las 166 que declaran los
servicios con `registrar_claves` no salían y fijarlas daba «clave desconocida».
Sólo se cambiaban por `.env`.

Cada servicio publica aquí las suyas —con el valor por defecto tal y como él lo
resuelve— y la consola las agrega por HTTP. La declaración sigue en un solo
sitio, el `ajustes.py` del dueño; el valor fijado le llega por la réplica de
siempre (`configuracion.ajuste_cambiado`).

Interna: no la enruta el gateway y exige la firma de la casa.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from crmcore.http.deps import exige_firma_interna


def crear_router_catalogo_ajustes(servicio: str) -> APIRouter:
    router = APIRouter(prefix="/interno/ajustes", tags=["interno"])

    @router.get(
        "/catalogo",
        response_model=dict,
        dependencies=[Depends(exige_firma_interna)],
        include_in_schema=False,
        summary=f"Los ajustes que declara «{servicio}»",
    )
    def catalogo() -> Any:
        from crmcore.runtime import settings as rt
        from crmcore.runtime.keys import a_dict, claves_del_servicio

        claves = []
        for decl in claves_del_servicio():
            fila = a_dict(decl)
            # Sin sesión: el valor de `.env` del DUEÑO, que es el que aplica
            # cuando nadie lo ha fijado. La consola no puede calcularlo, porque
            # no tiene la configuración de este servicio.
            fila["por_defecto"] = rt.efectivo(decl.clave)
            claves.append(fila)
        return {"servicio": servicio, "claves": claves}

    return router
