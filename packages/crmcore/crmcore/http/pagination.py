"""Paginación por cursor, filtrado, ordenación y proyección (CRM-00.02.01.10).

**Por qué cursor y no `offset`.** Con `offset`, insertar o borrar una fila entre
dos páginas desplaza el resto: el cliente ve un registro dos veces o se salta
otro, y no hay forma de que lo note. Además `OFFSET 50000` obliga a Postgres a
recorrer y descartar cincuenta mil filas en cada página. El cursor apunta a una
posición concreta del orden, así que ni se salta ni se repite, y la consulta usa
el índice.

El cursor es opaco por fuera (base64url) y estable por dentro: lleva los valores
de las columnas de orden de la última fila servida más el identificador, que
desempata. Que sea opaco no es decoración: si el cliente pudiera fabricarlo,
podría pedir una posición arbitraria del orden de OTRO tenant.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy import Select, and_, literal, or_

from crmcore.errors import ErrorValidacion

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Cursor:
    """Posición en el orden. Se serializa en base64url."""

    # Valores de las columnas de orden de la última fila entregada.
    valores: list[Any] = field(default_factory=list)
    # Identificador de esa fila: desempata cuando el orden no es único. Sin él,
    # diez oportunidades con la misma fecha de cierre harían que la página
    # siguiente empezara en cualquiera de las diez.
    id: str = ""
    # Orden con el que se emitió. Si el cliente cambia el orden y reutiliza el
    # cursor, el resultado no tendría sentido: se detecta y se rechaza.
    orden: str = ""

    def codificar(self) -> str:
        crudo = json.dumps(
            {"v": self.valores, "id": self.id, "o": self.orden},
            default=str,
            separators=(",", ":"),
        )
        return base64.urlsafe_b64encode(crudo.encode()).decode().rstrip("=")

    @classmethod
    def decodificar(cls, texto: str) -> Cursor:
        try:
            relleno = "=" * (-len(texto) % 4)
            d = json.loads(base64.urlsafe_b64decode(texto + relleno))
            return cls(valores=d.get("v", []), id=d.get("id", ""), orden=d.get("o", ""))
        except Exception:
            # Sin `from`: el detalle del fallo de base64 no le dice nada al
            # cliente y sí filtra cómo está construido el cursor.
            raise ErrorValidacion(
                "El cursor no es válido. Vuelve a empezar la paginación sin cursor.",
                error_code="paginacion.cursor_invalido",
            )


@dataclass(slots=True)
class Pagina(Generic[T]):
    """Una página de resultados."""

    items: list[T]
    siguiente: str | None = None
    # Total aproximado, y solo si el cliente lo pide: contar exacto en una tabla
    # grande cuesta un recorrido completo, y casi nadie necesita el número
    # exacto — necesita saber si hay más.
    total_aprox: int | None = None

    def a_dict(self, serializar: Any) -> dict[str, Any]:
        d: dict[str, Any] = {
            "items": [serializar(i) for i in self.items],
            "siguiente": self.siguiente,
            "hay_mas": self.siguiente is not None,
        }
        if self.total_aprox is not None:
            d["total_aprox"] = self.total_aprox
        return d


class PaginaDeListado(BaseModel):
    """El contrato de una página, para declararlo en la API.

    Existe porque los listados genéricos declaraban `response_model=dict`, y eso
    tenía dos consecuencias que no se veían juntas:

      * En el contrato publicado, `dict` no dice nada. Un cliente generado desde
        el OpenAPI no sabía que la respuesta trae `items` ni que hay cursor.
      * `/api/v1/superficie` decide si una operación devuelve una COLECCIÓN
        mirando el modelo de respuesta. Con `dict` decía que no, así que de las
        casi doscientas listas del CRM la superficie reconocía 39 —las que
        declaran su modelo a mano— y el front no podía distinguir una
        sub-colección de una vista en todas las demás.

    `items` va como lista de diccionarios y no de un modelo concreto porque cada
    listado proyecta campos distintos según quién pregunta (enmascarado por rol),
    y fijar un modelo aquí recortaría esa proyección.
    """

    items: list[dict[str, Any]]
    siguiente: str | None = None
    hay_mas: bool = False
    total_aprox: int | None = None


@dataclass(frozen=True, slots=True)
class ParametrosPagina:
    """Lo que el cliente pide."""

    limite: int
    cursor: str = ""
    orden: str = "-created_at"
    # Proyección: qué campos quiere. Vacío = todos. Sirve para que un cliente
    # móvil no se traiga cincuenta campos para pintar una lista de tres.
    campos: tuple[str, ...] = ()

    @classmethod
    def desde_query(
        cls,
        *,
        limite: int | None = None,
        cursor: str = "",
        orden: str = "-created_at",
        campos: str = "",
    ) -> ParametrosPagina:
        from crmcore.config import get_settings

        s = get_settings()
        pedido = limite or s.page_default_size
        if pedido > s.page_max_size:
            raise ErrorValidacion(
                f"El máximo por página es {s.page_max_size}",
                error_code="paginacion.limite_excesivo",
                detalle={"maximo": s.page_max_size, "pedido": pedido},
            )
        if pedido < 1:
            raise ErrorValidacion(
                "El tamaño de página debe ser al menos 1",
                error_code="paginacion.limite_invalido",
            )
        return cls(
            limite=pedido,
            cursor=cursor,
            orden=orden,
            campos=tuple(c.strip() for c in campos.split(",") if c.strip()),
        )


def aplicar_orden_y_cursor(
    consulta: Select,
    modelo: type,
    params: ParametrosPagina,
    *,
    columnas_permitidas: set[str],
    objeto: str | None = None,
    principal: Any = None,
    db: Any = None,
) -> Select:
    """Aplica orden y posición del cursor a la consulta.

    `columnas_permitidas` es una lista blanca, no una comprobación de que la
    columna existe: ordenar por una columna sin índice convierte una lista en un
    recorrido completo, y hay columnas (una contraseña hasheada) por las que
    directamente no se ordena. La lista la declara cada recurso.

    Con `objeto` y `principal` se aplica además la **proyección**
    (CRM-00.05.02.03): ordenar por un campo que no se puede ver lo reconstruye
    entero — basta pedir la lista ascendente y descendente y comparar. Con un
    filtro de rango, por búsqueda binaria, en una docena de peticiones. Así que
    para ordenar por un campo hay que poder verlo **en claro**; enmascarado no
    basta, porque quien ve `·····7890` no lee el número pero sí lo adivina si
    puede ordenar por él.

    Los tres argumentos son opcionales para no romper a quien ya llamaba, pero
    hay un gate que exige pasarlos en todo listado de un objeto con campos
    sensibles: la compatibilidad no puede convertirse en la puerta de atrás.
    """
    if objeto is not None and principal is not None:
        from crmcore.authz.proyeccion import columnas_usables

        columnas_permitidas = columnas_usables(
            columnas_permitidas,
            modelo=modelo,
            objeto=objeto,
            roles=frozenset(getattr(principal, "roles", frozenset())),
            es_admin=bool(getattr(principal, "es_admin_plataforma", False)),
            tenant_id=getattr(principal, "tenant_id", None),
            db=db,
        )

    campos_orden = [c.strip() for c in params.orden.split(",") if c.strip()]
    if not campos_orden:
        campos_orden = ["-created_at"]

    columnas = []
    for campo in campos_orden:
        desc = campo.startswith("-")
        nombre = campo.lstrip("-+")
        if nombre not in columnas_permitidas:
            raise ErrorValidacion(
                f"No se puede ordenar por «{nombre}»",
                error_code="paginacion.orden_no_permitido",
                detalle={"permitidas": sorted(columnas_permitidas)},
            )
        col = getattr(modelo, nombre)
        columnas.append((col.desc() if desc else col.asc(), col, desc, nombre))

    # El identificador siempre al final del orden: sin él, dos filas con el
    # mismo valor pueden salir en distinto orden entre dos consultas y el cursor
    # se salta o repite justo ahí.
    col_id = modelo.id
    consulta = consulta.order_by(*[c[0] for c in columnas], col_id.asc())

    if not params.cursor:
        return consulta

    cursor = Cursor.decodificar(params.cursor)
    if cursor.orden and cursor.orden != params.orden:
        raise ErrorValidacion(
            "El cursor pertenece a otra ordenación. Empieza de nuevo sin cursor.",
            error_code="paginacion.cursor_de_otro_orden",
        )

    # Comparación lexicográfica de la tupla de orden: para (a, b) descendente en
    # la primera, la condición es `a < a0 OR (a = a0 AND (b, id) > (b0, id0))`.
    # Se construye a mano porque la tupla de SQLAlchemy no mezcla direcciones.
    condiciones = []
    iguales: list[Any] = []
    for (_orden_sql, col, desc, _nombre), valor in zip(columnas, cursor.valores, strict=False):
        # El valor se compara CON EL TIPO DE SU COLUMNA, no como venga del JSON.
        #
        # El cursor viaja en base64 de un JSON, y JSON no tiene fechas: una marca
        # de tiempo sale de ahí como cadena. Comparar `timestamptz < varchar` es
        # un error de Postgres —«operator does not exist»— que sale como 500.
        #
        # Con el orden por defecto (`-created_at`, que es una marca de tiempo)
        # eso significa que **la segunda página de cualquier listado devolvía
        # 500**, y llevaba así desde siempre. No se veía porque el front pide
        # cincuenta filas y casi nadie llega a la segunda página; salió al
        # recorrer los listados enteros para llenar el almacén analítico.
        #
        # `literal(valor, col.type)` deja que sea el tipo de la columna quien
        # decida cómo se adapta el valor, así que vale igual para fechas,
        # números, identificadores y texto.
        atado = literal(valor, col.type)
        comparacion = col < atado if desc else col > atado
        condiciones.append(and_(*iguales, comparacion) if iguales else comparacion)
        iguales.append(col == atado)
    condiciones.append(and_(*iguales, col_id > cursor.id) if iguales else col_id > cursor.id)
    return consulta.where(or_(*condiciones))


# El texto del parámetro `?contar=true`, en un sitio. Son ocho listados los que
# lo ofrecen —uno por la fábrica y siete escritos a mano— y la misma explicación
# copiada ocho veces se queda vieja en siete en cuanto alguien la mejore en una.
CONTAR_TOTAL_DESCRIPCION = (
    "Devolver también `total_aprox`: cuántas hay en total con estos filtros. "
    "**Sólo si se pide**, porque contarlas cuesta un recorrido completo de la "
    "tabla y casi nadie necesita el número — necesita saber si hay más, y eso "
    "ya lo dice `hay_mas` sin coste. Se cuenta lo que ve quien pregunta, no lo "
    "que hay en la tabla."
)


def contar_consulta(db: Any, consulta: Any) -> int:
    """Cuántas filas devolvería esta consulta, sin traerlas.

    **Sólo cuando alguien lo pide.** Contar exacto en una tabla grande cuesta
    un recorrido completo, y casi nadie necesita el número: necesita saber si
    hay más, que ya lo dice el cursor pidiendo una fila de más.

    Pero cuando SÍ hace falta, no había forma. `total_aprox` estaba declarado
    en el contrato de toda página —así que un cliente generado del OpenAPI lo
    esperaba— y **no lo rellenaba nadie**: un campo publicado que nunca llega.
    Medido el 29-10-2026 preguntándole al asistente «cuántas cuentas no tienen
    web»: supo listarlas y no pudo contarlas, porque la API no lo ofrece.

    Se cuenta sobre la consulta YA FILTRADA, con sus permisos y su compartición
    aplicados: un total que no pase por lo mismo que la página diría cuántas
    hay en la tabla y no cuántas ve quien pregunta, que es un número distinto y
    además una filtración.
    """
    from sqlalchemy import func, select

    return int(db.execute(select(func.count()).select_from(consulta.subquery())).scalar() or 0)


def construir_pagina(
    filas: list[Any],
    params: ParametrosPagina,
    *,
    campos_orden: list[str],
    total_aprox: int | None = None,
) -> Pagina:
    """Recorta al tamaño pedido y calcula el cursor siguiente.

    Se consulta con `limite + 1` y aquí se descarta el sobrante: esa fila de más
    es cómo se sabe si hay página siguiente sin hacer una segunda consulta ni un
    `count`.
    """
    # `total_aprox` lo calcula quien llama —tiene la consulta— y se pasa aquí
    # para que la página lo lleve. Ver `contar_consulta`.
    hay_mas = len(filas) > params.limite
    items = filas[: params.limite]
    siguiente = None
    if hay_mas and items:
        ultima = items[-1]
        siguiente = Cursor(
            valores=[getattr(ultima, c.lstrip("-+")) for c in campos_orden],
            id=str(ultima.id),
            orden=params.orden,
        ).codificar()
    return Pagina(items=items, siguiente=siguiente, total_aprox=total_aprox)


def paginar_consulta(
    db: Any,
    modelo: type,
    consulta: Any,
    *,
    limite: int,
    cursor: str = "",
    orden: str = "-created_at",
    fila_a_dict: Callable[[Any], dict[str, Any]] | None = None,
    modelo_salida: type | None = None,
    contar: bool = False,
) -> dict[str, Any]:
    """Convierte una consulta ya filtrada en una PÁGINA con cursor.

    Existe para los listados escritos a mano. `montar_listado` pagina solo, pero
    hay listados con su propia consulta —filtros raros, campos compuestos, dos
    tablas— que devolvían una lista pelada con un `limite`.

    **Y una lista pelada no es la tabla: es su primera página**, sin nada que lo
    diga. Quien la lee cree que la tiene entera. Medido cuando la explotación
    empezó a dar cifras: la métrica «casos abiertos» contestaba 50 habiendo 153,
    con su unidad y su cara de cifra buena. Un número así es peor que un error,
    porque nadie lo comprueba. Y el front hacía lo mismo en pantalla.

    Se pide una fila de más y se descarta: así se sabe si hay siguiente sin un
    `count` que recorra la tabla entera.

    `fila_a_dict` es la proyección que ya tenía cada ruta. Se pasa en vez de
    imponer una: cada uno de estos listados compone campos que no son columnas
    —un nombre completo, un contador— y quitárselos al paginar sería cambiar lo
    que devuelve.

    `modelo_salida` es el atajo para el caso normal: el modelo Pydantic que la
    ruta declaraba antes en su `response_model`. **Hay que pasar uno de los
    dos.** Una página lleva diccionarios, no objetos del ORM, y sin proyección
    salían las filas crudas: eso no solo rompe la validación de la respuesta —es
    lo que se nota— sino que publicaría columnas que el modelo de salida no
    exponía, que es lo que no se nota.
    """
    params = ParametrosPagina.desde_query(limite=limite, cursor=cursor, orden=orden)
    # El total sólo si se pide: contarlo cuesta un recorrido completo y casi
    # nadie lo necesita. Pero `total_aprox` está en el contrato de toda página,
    # así que cuando hace falta tiene que poder llegar — y antes no llegaba
    # nunca.
    #
    # **Se cuenta ANTES del cursor, no después.** El cursor añade un «y de aquí
    # en adelante»: contar con él puesto daría cuántas quedan desde esta
    # página, un número que encoge según avanzas y que se lee como el total.
    total = contar_consulta(db, consulta) if contar else None
    consulta = aplicar_orden_y_cursor(
        consulta,
        modelo,
        params,
        columnas_permitidas={orden.lstrip("-+")},
    )
    filas = list(db.execute(consulta.limit(params.limite + 1)).scalars().all())
    pagina = construir_pagina(filas, params, campos_orden=[orden], total_aprox=total)
    if fila_a_dict is None and modelo_salida is not None:

        def fila_a_dict(fila: Any) -> dict[str, Any]:
            return dict(modelo_salida.model_validate(fila).model_dump())

    if fila_a_dict is None:
        raise RuntimeError(
            "paginar_consulta necesita `fila_a_dict` o `modelo_salida`: una "
            "página lleva diccionarios, no filas del ORM."
        )
    # Por `a_dict` y no a mano: el diccionario escrito aquí se olvidaba de
    # `total_aprox`, así que pedirlo hacía el recorrido completo de la tabla y
    # tiraba el número en la puerta. Un campo que se calcula y no se devuelve.
    return pagina.a_dict(fila_a_dict)
