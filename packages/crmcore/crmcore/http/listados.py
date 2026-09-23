"""Listados estándar, montados desde el modelo (CRM-00.02.01.10).

Existe por un agujero medido, no por gusto de abstraer: **cuarenta colecciones
del sistema se podían crear y no se podían leer**. Tenían su `POST` y no tenían
`GET`, así que un canal de entrada, una cola de casos o una lista de precios se
daban de alta y desaparecían: la API respondía 405 y el front —que declara esos
recursos como listables— enseñaba un error en la consola y una pantalla vacía.

Un listado siempre hace lo mismo: pagina por cursor, ordena por fecha de alta
descendente, exige un permiso y proyecta lo que quien mira puede ver. Escribirlo
cuarenta veces a mano garantiza que unas cuantas se queden sin proyección o sin
cursor, y esas no fallan: devuelven de más, o devuelven mal, en silencio.

    montar_listado(
        router_colas,
        modelo=ColaCasos,
        objeto="cola",
        permiso="case:read",
        nombre="Colas de casos",
    )

**Lo que NO hace.** Filtros propios de cada recurso. Un listado que intenta
servir a todos acaba con veinte parámetros que nadie usa; cuando un recurso
necesita filtrar por estado o por dueño, se le escribe su endpoint a mano —como
ya lo tienen leads, cuentas u oportunidades— y este deja de usarse para él.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, Query

from crmcore.http.deps import AutenticadoDep, DbDep, exige_permiso, proyectar_para
from crmcore.http.pagination import ParametrosPagina, aplicar_orden_y_cursor, construir_pagina


def montar_listado(
    router: Any,
    *,
    modelo: type,
    objeto: str,
    permiso: str,
    nombre: str,
    ruta: str = "",
    descripcion: str = "",
    orden: str = "-created_at",
    columnas_orden: frozenset[str] = frozenset({"created_at"}),
    filtro: Callable[[Any], Any] | None = None,
) -> None:
    """Registra en `router` el listado paginado de `modelo`.

    `filtro` acota la consulta cuando una tabla guarda más de una cosa —los
    perfiles de suite viven en la tabla de conexiones, junto a las demás—. Sin
    él, ese listado devolvería registros que no son de ese recurso.

    `objeto` es el nombre con el que este registro se conoce en las políticas de
    acceso: de él salen la proyección de campos y las excepciones. Se pide
    aparte del permiso porque no son lo mismo —el permiso dice si puedes leer la
    colección, la proyección qué columnas ves de cada fila—, y confundirlos es
    cómo se acaba dando el maestro entero a quien solo tenía que ver el nombre.
    """
    from sqlalchemy import select

    tiene_borrado = hasattr(modelo, "deleted_at")

    @router.get(
        ruta,
        response_model=dict,
        dependencies=[Depends(exige_permiso(permiso))],
        summary=f"Listar {nombre.lower()}",
        description=descripcion
        or (
            f"Paginado por cursor. Devuelve {nombre.lower()} del tenant en curso, "
            "de lo más reciente a lo más antiguo."
        ),
    )
    def listar(
        db: DbDep,
        principal: AutenticadoDep,
        limite: int = Query(50, ge=1, le=200),
        cursor: str = Query(""),
    ) -> Any:
        params = ParametrosPagina.desde_query(limite=limite, cursor=cursor, orden=orden)
        consulta = select(modelo)
        if filtro is not None:
            consulta = filtro(consulta)
        if tiene_borrado:
            # Lo borrado no se lista. Sigue estando —el borrado es lógico— pero
            # devolverlo haría que una papelera se pareciera a un listado.
            consulta = consulta.where(modelo.deleted_at.is_(None))
        consulta = aplicar_orden_y_cursor(
            consulta,
            modelo,
            params,
            columnas_permitidas=set(columnas_orden),
            objeto=objeto,
            principal=principal,
            db=db,
        )
        # Una fila de más: es cómo se sabe si hay página siguiente sin un
        # `count` que recorra la tabla entera.
        filas = list(db.execute(consulta.limit(params.limite + 1)).scalars().all())
        pagina = construir_pagina(filas, params, campos_orden=[orden])
        proyecta = proyectar_para(principal, db, objeto=objeto, modelo=modelo)
        return pagina.a_dict(proyecta)

    # El nombre de la función es lo que FastAPI usa como `operationId`, y dos
    # operaciones con el mismo id hacen que un generador de clientes produzca
    # métodos que se pisan.
    listar.__name__ = f"listar_{objeto.replace('-', '_').replace('.', '_')}"

    # La ruta se adelanta al principio del router. FastAPI casa **en orden de
    # declaración**, y estos listados se montan al final del módulo, después de
    # las rutas con parámetro. Con `/conocimiento/articulos` declarado después
    # de `/conocimiento/{articulo_id}`, la petición encajaba en la segunda y el
    # servidor contestaba «"articulos" no es un UUID» — un 422 que no tiene
    # nada que ver con lo que se estaba pidiendo.
    if ruta and "{" not in ruta:
        router.routes.insert(0, router.routes.pop())
