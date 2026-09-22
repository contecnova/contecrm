"""Restauración selectiva de registros (CRM-00.06.02.03).

La lógica vive en `crmcore.datos.restaurar` desde hace tiempo, y hasta ahora no
la podía llamar nadie: no había una sola ruta que llegara hasta ella. Una
recuperación que existe en el código y no se puede pedir es una recuperación que
no existe el día que hace falta, que es el único día que importa.

Se monta sola en `crear_servicio`, como la página de estado. Si dependiera de que
cada servicio se acuerde, faltaría precisamente en el que guarde lo que alguien
acabe borrando.

Cada servicio restaura **lo suyo**. Los objetos restaurables se leen del propio
mapeo del servicio, no de una lista escrita a mano: una lista se queda corta al
primer modelo nuevo, y ese modelo sería justo el que no se puede recuperar.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from crmcore.errors import NoEncontrado
from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso


class Previsualizar(BaseModel):
    exportacion: str = Field(..., description="URI o clave de la exportación verificada")
    objeto: str = Field(..., description="Tabla a restaurar, tal como sale en /objetos")
    ids: list[str] = Field(..., min_length=1, max_length=1000)
    desde: datetime | None = Field(
        None,
        description=(
            "Punto de restauración. Lo modificado después se marca aparte: es "
            "trabajo que alguien hizo a sabiendas."
        ),
    )


class Restaurar(Previsualizar):
    forzar_modificados: bool = Field(
        False,
        description=(
            "Pisar también lo modificado después del punto de restauración. Es "
            "una decisión, y por eso hay que decirla: por defecto no se toca."
        ),
    )


def objetos_restaurables() -> dict[str, type]:
    """Los modelos con `tenant_id` de este servicio, por nombre de tabla.

    Salen del mapeo y no de una lista: en un proceso solo están cargados los
    modelos del servicio que corre, así que esto es exactamente lo suyo y no
    puede quedarse viejo.

    Los que no llevan `tenant_id` quedan fuera a propósito: son catálogos de
    instalación, y restaurarlos «para un tenant» no significa nada.
    """
    from crmcore.db.base import Base

    salida: dict[str, type] = {}
    for mapper in Base.registry.mappers:
        modelo = mapper.class_
        tabla = getattr(modelo, "__table__", None)
        if tabla is None or "tenant_id" not in tabla.columns:
            continue
        salida[tabla.name] = modelo
    return salida


def crear_router_restauracion(servicio: str) -> APIRouter:
    # Cuelga del nombre del servicio, como la retención y los trabajos: todos
    # publican la misma ruta, y sin el segmento del servicio el gateway no
    # sabría a cuál de los doce mandar la petición.
    router = APIRouter(prefix=f"/{servicio}/restauracion", tags=["restauración selectiva"])

    @router.get(
        "/objetos",
        dependencies=[Depends(exige_permiso("datos:restaurar"))],
        summary=f"Qué objetos de «{servicio}» se pueden restaurar",
        description=(
            "Se leen del mapeo del servicio, no de una lista: una lista se queda "
            "corta al primer modelo nuevo, y ese sería justo el que no se puede "
            "recuperar el día que alguien lo borre."
        ),
    )
    def objetos(principal: AutenticadoDep) -> Any:
        return {"servicio": servicio, "objetos": sorted(objetos_restaurables())}

    @router.post(
        "/previsualizar",
        dependencies=[Depends(exige_permiso("datos:restaurar"))],
        summary="Qué cambiaría, antes de cambiar nada",
        description=(
            "Quien restaura casi nunca sabe exactamente qué va a sobrescribir, y "
            "descubrirlo después es cambiar un problema por otro. Lo modificado "
            "después del punto de restauración sale marcado aparte."
        ),
    )
    def previsualizar(cuerpo: Previsualizar, db: DbDep, principal: AutenticadoDep) -> Any:
        from crmcore.datos import restaurar as rest

        modelo = _modelo(cuerpo.objeto)
        origen = rest.leer_exportacion(cuerpo.exportacion, cuerpo.objeto)
        diferencias = rest.previsualizar(
            db, modelo, origen=origen, ids=cuerpo.ids, desde=cuerpo.desde
        )
        encontrados = {d.id for d in diferencias}
        return {
            "objeto": cuerpo.objeto,
            "diferencias": [
                {
                    "id": d.id,
                    "estado": d.estado,
                    "campos_distintos": d.campos_distintos,
                    "modificado_despues": d.modificado_despues,
                }
                for d in diferencias
            ],
            # Los que no están en la exportación se dicen: sin esto, alguien pide
            # trescientos identificadores, ve doscientos y cree que los otros
            # cien estaban bien.
            "no_estan_en_la_exportacion": [i for i in cuerpo.ids if i not in encontrados],
            "modificados_despues": [d.id for d in diferencias if d.modificado_despues],
        }

    @router.post(
        "",
        dependencies=[Depends(exige_permiso("datos:restaurar"))],
        summary="Devolver registros concretos a como estaban",
        description=(
            "Sin restaurar nada más. Es el hueco entre la papelera —que cubre el "
            "borrado de un usuario— y la restauración de clúster —que cubre el "
            "desastre—, y es donde caen casi todos los casos reales: una "
            "importación que machacó trescientas cuentas, una automatización que "
            "vació un campo.\n\n"
            "Lo modificado después del punto de restauración **no se toca** salvo "
            "que se diga explícitamente. Y todo queda en la auditoría."
        ),
    )
    def restaurar_registros(cuerpo: Restaurar, uow: UowDep, principal: AutenticadoDep) -> Any:
        from crmcore.datos import restaurar as rest

        modelo = _modelo(cuerpo.objeto)
        origen = rest.leer_exportacion(cuerpo.exportacion, cuerpo.objeto)
        return rest.restaurar(
            uow.db,
            modelo,
            origen=origen,
            ids=cuerpo.ids,
            tenant_id=uow.tenant_id,
            objeto=cuerpo.objeto,
            por=principal.id,
            forzar_modificados=cuerpo.forzar_modificados,
            desde=cuerpo.desde,
        )

    return router


def _modelo(objeto: str) -> type:
    modelos = objetos_restaurables()
    modelo = modelos.get(objeto)
    if modelo is None:
        raise NoEncontrado(
            f"Este servicio no guarda «{objeto}»: mira /restauracion/objetos. "
            "Cada servicio restaura lo suyo, porque ninguno escribe en el "
            "esquema de otro.",
            error_code="restaurar.objeto_desconocido",
        )
    return modelo
