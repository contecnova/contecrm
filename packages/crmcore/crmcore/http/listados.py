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


# Columnas que nunca se editan desde la ficha: las pone el sistema y dejarlas
# escribibles es cómo un registro acaba cambiando de tenant o de fecha de alta.
NO_EDITABLES = frozenset(
    {"id", "tenant_id", "created_at", "updated_at", "deleted_at", "deleted_by", "version"}
)


def montar_ficha(
    router: Any,
    *,
    modelo: type,
    objeto: str,
    permiso_leer: str,
    permiso_escribir: str,
    nombre: str,
    ruta: str = "",
    parametro: str = "registro_id",
    permiso_borrar: str = "",
    editable: frozenset[str] | None = None,
    con_lectura: bool = True,
) -> None:
    """Registra ver, editar y borrar un registro de `modelo`.

    Existe por la misma clase de agujero que `montar_listado`, medido igual:
    **de veintidós recursos que el front deja crear, uno solo se podía abrir,
    editar y borrar**. Trece no tenían ni ficha —se creaba una plantilla de
    correo y no había forma de volver a verla, ni de corregirle una errata— y
    ocho se abrían en modo lectura. Un CRM en el que solo se puede añadir no es
    un CRM: es un formulario con memoria.

    Los campos editables salen del modelo, no de una lista escrita a mano, por
    lo mismo que el formulario sale del contrato: una lista a mano se queda
    corta al primer campo nuevo y ese campo ya no se puede corregir desde
    ninguna pantalla.

    `con_lectura=False` registra solo editar y borrar, para los recursos que ya
    tienen su ficha escrita a mano —contactos, leads, casos— con sus reglas
    propias de visibilidad. Se les añade lo que les faltaba sin tocar lo que ya
    funciona, en vez de reescribir su lectura para uniformar.

    El borrado es **lógico** cuando el modelo tiene `deleted_at` —así se puede
    deshacer desde la papelera— y no se registra cuando no lo tiene: un borrado
    definitivo sin vuelta atrás es una decisión de cada recurso, no algo que
    deba aparecer por usar un ayudante.
    """
    from pydantic import create_model
    from sqlalchemy import inspect as sa_inspect

    from crmcore.errors import NoEncontrado

    mapeo = sa_inspect(modelo)
    columnas = {c.key: c for c in mapeo.mapper.column_attrs}  # type: ignore[union-attr]
    campos = {
        nombre_campo: columna
        for nombre_campo, columna in columnas.items()
        if nombre_campo not in NO_EDITABLES
        and (editable is None or nombre_campo in editable)
        # Las claves ajenas al dueño del registro no se cambian por aquí: mover
        # un contacto de cuenta tiene consecuencias —visibilidad, territorio,
        # consentimiento— y cada servicio lo resuelve con su propia operación.
        and nombre_campo != "objeto_id"
    }
    tiene_borrado = hasattr(modelo, "deleted_at")

    # El esquema del PATCH, generado del modelo. Todos los campos opcionales:
    # un PATCH describe lo que cambia, no el registro entero.
    Parche = create_model(  # noqa: N806 - es un tipo, y se lee mejor así
        f"Editar{objeto.title().replace('_', '').replace('-', '')}",
        __doc__=f"Campos editables de {nombre.lower()}. Se cambia solo lo que se envía.",
        **{
            nombre_campo: (_tipo_de(columna) | None, None)  # type: ignore[misc]
            for nombre_campo, columna in campos.items()
        },
    )

    ruta_registro = f"{ruta}/{{{parametro}}}"

    def _buscar(db: Any, registro_id: Any) -> Any:
        fila = db.get(modelo, registro_id)
        if fila is None or (tiene_borrado and fila.deleted_at is not None):
            raise NoEncontrado(
                f"No existe ese registro de {nombre.lower()}",
                error_code=f"{objeto}.no_encontrado",
            )
        return fila

    if con_lectura:

        @router.get(
            ruta_registro,
            response_model=dict,
            dependencies=[Depends(exige_permiso(permiso_leer))],
            summary=f"Ver un registro de {nombre.lower()}",
        )
        def ver(registro_id: Any, db: DbDep, principal: AutenticadoDep) -> Any:
            fila = _buscar(db, registro_id)
            return proyectar_para(principal, db, objeto=objeto, modelo=modelo)(fila)

        ver.__name__ = f"ver_{objeto.replace('-', '_').replace('.', '_')}"

    def editar(registro_id: Any, datos: Any, db: DbDep, principal: AutenticadoDep) -> Any:
        fila = _buscar(db, registro_id)
        # `exclude_unset`: distingue «no lo toco» de «déjalo vacío». Sin esto,
        # editar el nombre borraría todos los demás campos del registro.
        for campo, valor in datos.model_dump(exclude_unset=True).items():
            setattr(fila, campo, valor)
        db.flush()
        return proyectar_para(principal, db, objeto=objeto, modelo=modelo)(fila)

    # El tipo del cuerpo se asigna y la ruta se registra después, en vez de
    # escribirlo en la firma con un decorador: este módulo usa anotaciones
    # aplazadas, así que una anotación escrita arriba le llegaría a FastAPI
    # como el texto «Parche» —un nombre local que no puede resolver— y el
    # servicio no arrancaba.
    editar.__annotations__["datos"] = Parche
    editar.__name__ = f"editar_{objeto.replace('-', '_').replace('.', '_')}"
    router.patch(
        ruta_registro,
        response_model=dict,
        dependencies=[Depends(exige_permiso(permiso_escribir))],
        summary=f"Editar {nombre.lower()}",
        description=(
            "Se cambia **solo lo que se envía**. Lo que no aparece en el cuerpo "
            "se queda como está, que es distinto de mandarlo vacío."
        ),
    )(editar)

    if tiene_borrado:

        @router.delete(
            ruta_registro,
            status_code=204,
            dependencies=[Depends(exige_permiso(permiso_borrar or permiso_escribir))],
            summary=f"Borrar {nombre.lower()}",
            description=(
                "Borrado **lógico**: el registro deja de listarse y se puede "
                "recuperar desde la papelera. Lo que se borra por error se "
                "descubre siempre más tarde que el borrado."
            ),
        )
        def borrar(registro_id: Any, db: DbDep, _: AutenticadoDep) -> None:
            from datetime import datetime, timezone

            fila = _buscar(db, registro_id)
            fila.deleted_at = datetime.now(timezone.utc)
            db.flush()

        borrar.__name__ = f"borrar_{objeto.replace('-', '_').replace('.', '_')}"


def _tipo_de(columna: Any) -> Any:
    """El tipo Python de una columna, para construir el esquema del PATCH.

    Se cae del lado de `str` cuando no lo sabe: un campo con tipo desconocido
    editado como texto es corregible; un campo que no aparece en el formulario
    no hay forma de arreglarlo desde ninguna pantalla.
    """
    try:
        tipo = columna.expression.type.python_type
    except (NotImplementedError, AttributeError):
        return Any
    return tipo if tipo in (str, int, float, bool) else Any
