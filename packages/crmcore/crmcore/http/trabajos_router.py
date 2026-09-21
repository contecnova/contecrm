"""Superficie HTTP de los trabajos asíncronos (CRM-00.02.01.12).

Es una **fábrica**, como la de adjuntos: cada servicio la monta y expone sus
trabajos, que son los que él ejecuta y los únicos que puede leer, porque la
tabla vive en su esquema.

El contrato que ve el cliente es siempre el mismo, lo monte quien lo monte:

    POST /<algo>/masivo?modo=asincrono  →  202 + Location: /trabajos/{id}
    GET  /trabajos/{id}                 →  200 con progreso (+ Retry-After)
    GET  /trabajos/{id}/errores         →  el informe parcial completo
    POST /trabajos/{id}/cancelar        →  200
    GET  /trabajos                      →  listado paginado

**`Retry-After` mientras no ha terminado.** Sin él, cada cliente elige su
intervalo de sondeo y el que elige «cada 200 ms» convierte una importación en
una denegación de servicio contra su propio CRM. Con él, el servidor dice cada
cuánto merece la pena volver a preguntar.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select

from crmcore.datos.trabajos import (
    ESTADOS,
    ESTADOS_VIVOS,
    Trabajo,
    a_dict,
    cancelar,
    leer,
)
from crmcore.errors import ErrorValidacion
from crmcore.http.deps import AutenticadoDep, DbDep, exige_permiso
from crmcore.http.pagination import ParametrosPagina, aplicar_orden_y_cursor, construir_pagina

# Cada cuánto se le dice al cliente que vuelva a preguntar. No es un ajuste en
# caliente porque no es una política del tenant: es la cadencia con la que este
# servicio quiere que le sondeen, y depende de su despliegue, no de quién pregunta.
RETRY_AFTER_S = 2


def crear_router_trabajos(
    *, permiso_ver: str, permiso_cancelar: str, prefijo: str = "/trabajos"
) -> APIRouter:
    """Construye el router de trabajos del servicio.

    Los permisos los pasa el servicio porque el suyo es el que sabe: en `party`
    un trabajo es una importación de clientes y lo ve quien administra el
    maestro; en `sales` es un recálculo de pipeline y lo ve otro. Un permiso
    genérico «ver trabajos» dejaría que quien puede mirar un recálculo leyera la
    entrada de una importación, que son los datos personales del fichero.
    """
    router = APIRouter(prefix=prefijo, tags=["trabajos"])

    @router.get(
        "",
        summary="Lista los trabajos del tenant",
        dependencies=[Depends(exige_permiso(permiso_ver))],
    )
    def listar(
        principal: AutenticadoDep,
        db: DbDep,
        limite: int = Query(50, ge=1, le=200),
        cursor: str = Query(""),
        estado: str = Query("", description="Filtra por estado"),
        tipo: str = Query("", description="Filtra por tipo de trabajo"),
    ) -> Any:
        if estado and estado not in ESTADOS:
            raise ErrorValidacion(
                f"Estado desconocido: «{estado}»",
                error_code="trabajo.estado_invalido",
                detalle={"admitidos": list(ESTADOS)},
            )
        params = ParametrosPagina.desde_query(limite=limite, cursor=cursor, orden="-created_at")
        consulta = select(Trabajo)
        if estado:
            consulta = consulta.where(Trabajo.estado == estado)
        if tipo:
            consulta = consulta.where(Trabajo.tipo == tipo)
        consulta = aplicar_orden_y_cursor(
            consulta,
            Trabajo,
            params,
            columnas_permitidas={"created_at"},
            objeto="trabajo",
            principal=principal,
            db=db,
        )
        filas = list(db.execute(consulta.limit(params.limite + 1)).scalars().all())
        pagina = construir_pagina(filas, params, campos_orden=["-created_at"])
        return pagina.a_dict(lambda t: a_dict(t))

    @router.get(
        "/{trabajo_id}",
        summary="Progreso de un trabajo",
        dependencies=[Depends(exige_permiso(permiso_ver))],
    )
    def ver(trabajo_id: UUID, db: DbDep, respuesta: Response) -> Any:
        trabajo = leer(db, trabajo_id)
        if trabajo.estado in ESTADOS_VIVOS:
            respuesta.headers["Retry-After"] = str(RETRY_AFTER_S)
        return a_dict(trabajo)

    @router.get(
        "/{trabajo_id}/errores",
        summary="Informe parcial: qué elementos fallaron y por qué",
        dependencies=[Depends(exige_permiso(permiso_ver))],
    )
    def errores(trabajo_id: UUID, db: DbDep) -> Any:
        """El informe completo, aparte de la ficha.

        Separado del progreso a propósito: un cliente que sondea cada dos
        segundos no debe arrastrar quinientos errores en cada respuesta, y quien
        va a corregir el fichero los quiere todos de una vez.
        """
        trabajo = leer(db, trabajo_id)
        return {
            "id": str(trabajo.id),
            "fallidos": trabajo.fallidos,
            "errores_guardados": len(trabajo.errores),
            # Se dice explícitamente cuando la lista está recortada: si no, un
            # fichero con mil errores del que se guardaron quinientos parece un
            # fichero con quinientos errores, y se corrige a medias.
            "recortado": trabajo.fallidos > len(trabajo.errores),
            "errores": trabajo.errores,
        }

    @router.post(
        "/{trabajo_id}/cancelar",
        summary="Pide que un trabajo pare",
        dependencies=[Depends(exige_permiso(permiso_cancelar))],
        status_code=status.HTTP_200_OK,
    )
    def cancelar_trabajo(trabajo_id: UUID, db: DbDep, motivo: str = Query("")) -> Any:
        trabajo = cancelar(db, trabajo_id, motivo=motivo)
        db.commit()
        return a_dict(trabajo)

    return router
