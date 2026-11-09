"""La configuración de los estados de cada objeto, por servicio (CRM-00.04.01.07).

Cada servicio publica las máquinas que declara —`/{servicio}/estados`—, igual
que publica su papelera: así el gateway las enruta por el servicio dueño sin
una tabla aparte, y una pantalla de Administrar las recorre todas.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from crmcore.errors import NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, exige_permiso


class ConfiguracionIn(BaseModel):
    estados: list[dict[str, Any]] = Field(
        ...,
        description=(
            "Cada estado: `clave`, `nombre`, `color`, `orden`, `significado`, "
            "`final` y `activo`. Los de fábrica tienen que estar todos."
        ),
    )
    inicial: str = ""
    transiciones: dict[str, list[str]] = Field(default_factory=dict)
    exigen_motivo: list[str] = Field(default_factory=list)


def crear_router_estados(servicio: str) -> APIRouter:
    from crmcore.datos import estados as est

    router = APIRouter(prefix=f"/{servicio}/estados", tags=["estados"])

    def _de_este_servicio(objeto: str) -> est.Maquina:
        maquina = est.MAQUINAS.get(objeto)
        if maquina is None or not maquina.configurable:
            raise NoEncontrado(
                f"«{objeto}» no tiene estados configurables en {servicio}",
                error_code="estados.no_configurable",
            )
        return maquina

    @router.get(
        "",
        dependencies=[Depends(exige_permiso("tenant:read"))],
        summary=f"Los objetos de «{servicio}» con estados configurables",
    )
    def listar(db: DbDep) -> Any:
        return {
            "items": [
                {
                    "objeto": m.objeto,
                    "estados": len(est.maquina_efectiva(m.objeto, db).estados),
                    "de_fabrica": est.maquina_efectiva(m.objeto, db) is m,
                }
                for m in est.MAQUINAS.values()
                if m.configurable
            ]
        }

    @router.get(
        "/{objeto}",
        dependencies=[Depends(exige_permiso("tenant:read"))],
        summary="Los estados de un objeto, como los tiene configurados esta empresa",
        description="Con los de fábrica al lado, para poder ver qué se ha cambiado.",
    )
    def ver(objeto: str, db: DbDep) -> Any:
        fabrica = _de_este_servicio(objeto)
        efectiva = est.maquina_efectiva(objeto, db)
        return {
            **est.a_configuracion(efectiva, de_fabrica=efectiva is fabrica),
            "fabrica": est.a_configuracion(fabrica, de_fabrica=True),
        }

    @router.put(
        "/{objeto}",
        dependencies=[Depends(exige_permiso("tenant:write"))],
        summary="Configurar los estados de un objeto",
        description=(
            "Nombres, orden, colores, estados propios —cada uno con lo que "
            "significa— y transiciones. Los de fábrica no se borran, se "
            "desactivan. Se valida antes de guardar y queda auditado."
        ),
    )
    def configurar(
        objeto: str, datos: ConfiguracionIn, db: DbDep, principal: AutenticadoDep
    ) -> Any:
        from crmcore.runtime import settings as rt

        fabrica = _de_este_servicio(objeto)
        conf = datos.model_dump()
        maquina = est.construir(fabrica, conf)  # valida; lanza con el motivo
        todas = dict(rt.efectivo("maquinas_de_estado", db) or {})
        todas[objeto] = conf
        rt.fijar(
            db, "maquinas_de_estado", todas, ambito_id=str(principal.tenant_id), por=principal.id
        )
        return est.a_configuracion(maquina, de_fabrica=False)

    @router.delete(
        "/{objeto}",
        dependencies=[Depends(exige_permiso("tenant:write"))],
        summary="Volver a los estados de fábrica",
    )
    def a_fabrica(objeto: str, db: DbDep, principal: AutenticadoDep) -> Any:
        from crmcore.runtime import settings as rt

        fabrica = _de_este_servicio(objeto)
        todas = dict(rt.efectivo("maquinas_de_estado", db) or {})
        todas.pop(objeto, None)
        rt.fijar(
            db, "maquinas_de_estado", todas, ambito_id=str(principal.tenant_id), por=principal.id
        )
        return est.a_configuracion(fabrica, de_fabrica=True)

    return router
