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

from crmcore.http.deps import AutenticadoDep, DbDep, UowDep, exige_permiso, proyectar_para
from crmcore.http.pagination import (
    PaginaDeListado,
    ParametrosPagina,
    aplicar_orden_y_cursor,
    construir_pagina,
)


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
        response_model=PaginaDeListado,
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
    {
        "id",
        "tenant_id",
        "created_at",
        "updated_at",
        "deleted_at",
        "deleted_by",
        "version",
        # Enlaces que pone el sistema, no una persona. Ofrecerlos en el
        # formulario es pedir que alguien teclee un identificador de treinta y
        # seis caracteres para «arreglar» algo que se arregla desde la acción
        # que lo creó: se fusiona desde la fusión, se deshace un duplicado
        # desde la cola de duplicados, y la papelera apunta al registro que
        # guardó. Escribirlos a mano solo sirve para romperlos.
        "fusionado_en_id",
        "fusionada_en_id",
        "duplicado_de_id",
        "registro_id",
        "vinculo_id",
        "instancia_id",
        "caso_origen_id",
        "respuesta_aceptada_id",
        "ultima_creada_id",
        # Identificadores del gestor documental y de la firma: los pone el
        # propio flujo al generar o al firmar. Escribirlos a mano solo sirve
        # para apuntar a un documento que no es.
        "documento_id",
        "documento_firmado_id",
        "certificado_id",
        "acuse_documento_id",
        "respuesta_documento_id",
        "firma_documento_id",
        "objeto_origen_id",
        # Y estos otros: la etapa se mueve con su propia acción —que valida los
        # criterios de salida—, la aprobación la crea el flujo de aprobación, y
        # el modelo de una predicción lo pone quien la calcula.
        "etapa_id",
        "aprobacion_id",
        "modelo_id",
        # La unidad de negocio y el encargo no tienen dónde elegirse: las
        # unidades cuelgan de su tenant y el encargo lo fija quien crea la
        # devolución. Una caja para teclear su identificador es peor que no
        # ofrecerlo — se cambia desde donde se asigna.
        "business_unit_id",
        "encargo_id",
    }
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
            nombre_campo: (_tipo_de(columna) | None, _anotacion(columna))  # type: ignore[misc]
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

        def borrar(registro_id: Any, uow: UowDep, principal: AutenticadoDep) -> None:
            from crmcore.datos import integridad, papelera

            db = uow.db
            fila = _buscar(db, registro_id)
            # Antes de nada, quién lo está usando. Borrar algo que otros
            # registros apuntan no da error: los deja señalando a un
            # identificador que ya no resuelve, y eso no se nota al borrar sino
            # semanas después, al abrir el que dependía.
            integridad.exigir_sin_dependencias(db, fila, objeto=objeto)
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
            # Y se cuenta. El hecho estaba declarado en el catálogo y con
            # consumidores esperándolo —la proyección de marketing lo usa para
            # retirar lo borrado— y **no lo emitía nadie**: el borrado usaba una
            # sesión de base y no la unidad de trabajo, que es quien publica.
            # Así que lo borrado seguía contando en los segmentos.
            uow.emitir(
                "record.deleted",
                subject=(objeto, getattr(fila, "id", registro_id)),
                data={
                    "objeto": objeto,
                    "registro_id": str(getattr(fila, "id", registro_id)),
                    "definitivo": False,
                },
            )

        borrar.__name__ = f"borrar_{objeto.replace('-', '_').replace('.', '_')}"
        router.delete(
            ruta_registro,
            status_code=204,
            dependencies=[Depends(exige_permiso(permiso_borrar or permiso_escribir))],
            summary=f"Borrar {nombre.lower()}",
            description=(
                "Borrado **lógico**: el registro va a la papelera, deja de "
                "listarse y se puede restaurar desde ahí. Lo que se borra por "
                "error se descubre siempre más tarde que el borrado.\n\n"
                "Si hay registros que lo usan **no se borra**: responde 409 "
                "diciendo qué depende y cuántos. Para eso está archivar."
            ),
        )(_con_parametro(borrar, parametro))

    # Archivar: retirar sin borrar. Se monta cuando el modelo tiene con qué
    # marcarse como retirado, y es la salida de lo que no se puede borrar
    # porque otros lo usan — que es la mayoría de lo que se quiere quitar de
    # enmedio: una lista de precios vieja no se borra, se deja de ofrecer.
    from crmcore.datos.integridad import se_puede_archivar

    if se_puede_archivar(modelo):

        def archivar(registro_id: Any, db: DbDep, principal: AutenticadoDep) -> Any:
            from crmcore.datos import integridad

            fila = _buscar(db, registro_id)
            integridad.archivar(fila)
            db.flush()
            return proyectar_para(principal, db, objeto=objeto, modelo=modelo)(fila)

        archivar.__name__ = f"archivar_{objeto.replace('-', '_').replace('.', '_')}"
        router.post(
            f"{ruta_registro}/archivar",
            response_model=dict,
            dependencies=[Depends(exige_permiso(permiso_escribir))],
            summary=f"Archivar {nombre.lower()}",
            description=(
                "Lo retira sin borrarlo: deja de ofrecerse de aquí en adelante "
                "y no toca nada de lo que ya pasó. Es lo que hay que hacer con "
                "lo que no se puede borrar porque hay registros que lo usan, y "
                "casi siempre es también lo que se quería hacer."
            ),
        )(_con_parametro(archivar, parametro))


def _anotacion(columna: Any) -> Any:
    """Qué más sabe la columna de sí misma, para que llegue al contrato.

    De momento, **a qué objeto apunta** cuando es una referencia. El front lo
    usa para enseñar un buscador con nombres en vez de una caja donde teclear un
    identificador, y no siempre puede adivinarlo del nombre: `origen_id` y
    `destino_id` del mapa de personas apuntan a contactos, y `anotada_por_id` a
    un usuario. Sin decirlo, esos tres campos salían como tres UUID que nadie
    puede leer ni escribir.
    """
    from pydantic.fields import FieldInfo

    try:
        info = dict(columna.expression.info or {})
    except AttributeError:
        info = {}
    apunta = info.get("referencia")
    if not apunta:
        return None
    return FieldInfo(default=None, json_schema_extra={"referencia": str(apunta)})


def _opciones_de(columna: Any) -> tuple[str, ...]:
    """Los valores que admite una columna, si los declara.

    Se busca en `info` de la columna y también en el `Enum` de su tipo, por si
    alguien lo modeló así: las dos formas dicen lo mismo y quien lee el modelo
    no tiene por qué saber cuál se usó.
    """
    try:
        info = dict(columna.expression.info or {})
    except AttributeError:
        info = {}
    declaradas = info.get("opciones")
    if declaradas:
        return tuple(str(v) for v in declaradas)
    valores = getattr(getattr(columna.expression, "type", None), "enums", None)
    return tuple(str(v) for v in valores) if valores else ()


def _tipo_de(columna: Any) -> Any:
    """El tipo Python de una columna, para construir el esquema del PATCH.

    **Si la columna declara sus valores, se devuelven como lista cerrada.** Es
    lo que convierte el campo en un desplegable en vez de una caja de texto: sin
    esto, un campo que el servicio valida contra cinco valores se editaba
    escribiéndolo a mano, y quien lo rellenaba tenía que saberse los cinco de
    memoria y escribirlos sin erratas. La lista se declara en la propia columna
    —`info={"opciones": RELACIONES}`— porque es donde vive la verdad y donde se
    ve al leer el modelo.

    Se cae del lado de `str` cuando no lo sabe: un campo con tipo desconocido
    editado como texto es corregible; un campo que no aparece en el formulario
    no hay forma de arreglarlo desde ninguna pantalla.
    """
    opciones = _opciones_de(columna)
    if opciones:
        from typing import Literal

        return Literal[tuple(opciones)]  # type: ignore[valid-type]

    try:
        tipo = columna.expression.type.python_type
    except (NotImplementedError, AttributeError):
        return Any
    return tipo if tipo in (str, int, float, bool) else Any
