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
    permiso_escribir: str = "",
    ficha: bool = True,
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

    **Monta también la ficha**, salvo que el router ya tenga una. Una colección
    y su registro son la misma cosa, y tenerlas separadas fue el agujero de
    siempre: treinta y cuatro recursos publicaban acciones sobre un registro
    —enviar una oferta, aceptarla, inscribir en una cadencia— y no había ninguna
    ficha desde la que llegar a ellas, así que ochenta acciones existían y no se
    alcanzaban desde ninguna pantalla.

    El permiso de escritura se deduce del de lectura (`x:read` → `x:write`)
    cuando no se dice: es la convención de todo el sistema y escribirlo en las
    cincuenta y nueve llamadas solo garantiza que alguna se quede sin él.
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

    if not ficha:
        return
    # No se pisa una ficha escrita a mano: si ya hay una ruta con parámetro
    # colgando de esta colección, esa manda —tendrá sus reglas propias— y aquí
    # no se monta nada.
    prefijo = f"{getattr(router, 'prefix', '')}{ruta}/"
    if any(
        getattr(r, "path", "").startswith(prefijo)
        and "{" in getattr(r, "path", "")[len(prefijo) :]
        and getattr(r, "path", "")[len(prefijo) :].count("/") == 0
        for r in router.routes
    ):
        return
    montar_ficha(
        router,
        modelo=modelo,
        objeto=objeto,
        permiso_leer=permiso,
        permiso_escribir=permiso_escribir or permiso.replace(":read", ":write"),
        nombre=nombre,
        ruta=ruta,
    )


# Columnas que nunca se editan desde la ficha: las pone el sistema y dejarlas
# escribibles es cómo un registro acaba cambiando de tenant o de fecha de alta.
NO_EDITABLES = frozenset(
    {"id", "tenant_id", "created_at", "updated_at", "deleted_at", "deleted_by", "version"}
)


def _con_parametro(funcion: Any, parametro: str, cuerpo: type | None = None) -> Any:
    """Deja el parámetro de ruta con el nombre que usa la ruta.

    FastAPI empareja los parámetros de ruta **por nombre**: con la ruta
    declarando `{contacto_id}` y la función recibiendo `registro_id`, no los
    relaciona y pide el identificador por query. El síntoma era un `DELETE` que
    contestaba «falta el campo query.registro_id» sobre una URL que lo llevaba
    dentro.

    El nombre lo decide quien monta la ficha —porque cada recurso ya tiene el
    suyo en las rutas que escribió a mano— así que se ajusta la firma aquí en
    vez de obligar a que todos se llamen igual.
    """
    import inspect
    from uuid import UUID

    original = inspect.signature(funcion)
    parametros = []
    for nombre_par, par in original.parameters.items():
        if nombre_par == "registro_id":
            parametros.append(par.replace(name=parametro, annotation=UUID))
        elif nombre_par == "datos" and cuerpo is not None:
            parametros.append(par.replace(annotation=cuerpo))
        else:
            parametros.append(par)

    def envoltorio(*args: Any, **kwargs: Any) -> Any:
        kwargs["registro_id"] = kwargs.pop(parametro)
        return funcion(*args, **kwargs)

    envoltorio.__signature__ = original.replace(parameters=parametros)  # type: ignore[attr-defined]
    envoltorio.__name__ = funcion.__name__
    envoltorio.__doc__ = funcion.__doc__
    return envoltorio


def montar_ficha(
    router: Any,
    *,
    modelo: type,
    objeto: str,
    permiso_leer: str,
    permiso_escribir: str,
    nombre: str,
    ruta: str = "",
    parametro: str = "",
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

    # El nombre del parámetro sale del objeto —`toque` → `toque_id`— y no de un
    # genérico. No es cosmético: la prueba de aislamiento entre tenants resuelve
    # el modelo **por el nombre del parámetro**, así que con `registro_id` no lo
    # encontraba y esas rutas se quedaban sin probar, en silencio.
    parametro = parametro or f"{objeto}_id"
    ruta_registro = f"{ruta}/{{{parametro}}}"

    def _buscar(db: Any, registro_id: Any) -> Any:
        fila = db.get(modelo, registro_id)
        if fila is None or (tiene_borrado and fila.deleted_at is not None):
            raise NoEncontrado(
                f"No existe ese registro de {nombre.lower()}",
                error_code=f"{objeto}.no_encontrado",
            )
        return fila

    def ver(registro_id: Any, db: DbDep, principal: AutenticadoDep) -> Any:
        fila = _buscar(db, registro_id)
        return proyectar_para(principal, db, objeto=objeto, modelo=modelo)(fila)

    ver.__name__ = f"ver_{objeto.replace('-', '_').replace('.', '_')}"

    if con_lectura:
        router.get(
            ruta_registro,
            response_model=dict,
            dependencies=[Depends(exige_permiso(permiso_leer))],
            summary=f"Ver un registro de {nombre.lower()}",
        )(_con_parametro(ver, parametro))

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
    )(_con_parametro(editar, parametro, Parche))

    if tiene_borrado:
        # Se declara qué modelo hay detrás de este nombre de objeto: la entrada
        # de papelera lo guarda por su nombre de negocio y restaurar tiene que
        # poder volver al modelo.
        from crmcore.datos.papelera import registrar_objeto

        registrar_objeto(objeto, modelo)

        def borrar(registro_id: Any, db: DbDep, principal: AutenticadoDep) -> None:
            from crmcore.datos import papelera

            fila = _buscar(db, registro_id)
            # Por la papelera y no marcando `deleted_at` a mano: marcarlo
            # esconde el registro y no crea la entrada, así que no se puede ni
            # restaurar ni purgar. Un borrado sin vuelta atrás disfrazado de
            # borrado lógico es peor que uno definitivo, porque nadie lo sabe.
            papelera.borrar(
                db,
                fila,
                objeto=objeto,
                etiqueta=str(getattr(fila, "nombre", "") or getattr(fila, "clave", "")),
                por=principal.id,
            )
            db.flush()

        borrar.__name__ = f"borrar_{objeto.replace('-', '_').replace('.', '_')}"
        router.delete(
            ruta_registro,
            status_code=204,
            dependencies=[Depends(exige_permiso(permiso_borrar or permiso_escribir))],
            summary=f"Borrar {nombre.lower()}",
            description=(
                "Borrado **lógico**: el registro va a la papelera, deja de "
                "listarse y se puede restaurar desde ahí. Lo que se borra por "
                "error se descubre siempre más tarde que el borrado."
            ),
        )(_con_parametro(borrar, parametro))


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
