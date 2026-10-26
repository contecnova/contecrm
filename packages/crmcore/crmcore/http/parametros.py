"""Un parámetro que no se mira es un filtro que no filtra (CRM-00.02.01.10).

FastAPI **se come en silencio** cualquier parámetro de query que la función no
declare. Eso ya costó caro una vez: `/activities?cuenta_id=X` devolvía todas
las filas del tenant como si el filtro existiera, y quien lo leía se llevaba la
actividad de otro cliente creyendo que era la suya. Se arregló en la fábrica de
listados, que desde entonces rechaza con un 422 lo que no es columna.

Pero la fábrica monta 61 listados y hay **29 escritos a mano** con sus filtros
propios —usuarios, roles, políticas, encargos, entornos—, y en esos seguía
pasando exactamente lo mismo. Medido el 26-10-2026.

Así que la comprobación va aquí, como dependencia de la aplicación entera, por
el mismo motivo que la idempotencia: engancharla ruta a ruta significa que
funciona en las que alguien se acordó, y son casi trescientas.

**Lo que no se comprueba, y por qué.** Hay rutas que reciben parámetros que no
pueden declarar:

  * los listados de la fábrica, cuyos filtros son los nombres de las columnas
    del modelo y cambian con él. Ésos ya validan los suyos, mejor de lo que
    podría hacerlo esto, y se marcan con `admite_parametros_abiertos`;
  * las vueltas de un proveedor externo —OAuth, SAML, una pasarela—, que traen
    lo que les da la gana y a las que no se les puede exigir una lista.

Las dos se marcan con la misma función y la marca lleva el motivo al lado.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request

# Lo que gobierna la FORMA de la respuesta y puede llegar a cualquier ruta sin
# que la declare: no cambia qué filas salen, así que ignorarlo no miente.
SIEMPRE_ADMITIDOS = frozenset({"formato", "campos", "total"})

_MARCA = "_admite_parametros_abiertos"


def admite_parametros_abiertos(funcion: Any, motivo: str) -> Any:
    """Marca una ruta que recibe parámetros que no puede declarar.

    El motivo no es decorativo: una marca sin motivo se copia a la siguiente
    ruta que dé guerra, y entonces la comprobación deja de comprobar.
    """
    if not motivo:
        raise ValueError("una ruta con parámetros abiertos tiene que decir por qué")
    setattr(funcion, _MARCA, motivo)
    return funcion


def motivo_de_apertura(funcion: Any) -> str:
    return str(getattr(funcion, _MARCA, "") or "")


def _declarados(dependant: Any, vistos: set[int] | None = None) -> set[str]:
    """Los nombres de query que esta ruta sí mira, con sus dependencias.

    Recursivo a propósito: los parámetros de paginación y de proyección llegan
    por dependencias compartidas, y mirando sólo el primer nivel saldrían como
    desconocidos justo los que todas las rutas aceptan.
    """
    vistos = vistos if vistos is not None else set()
    if id(dependant) in vistos:
        return set()
    vistos.add(id(dependant))
    nombres = {p.alias or p.name for p in getattr(dependant, "query_params", [])}
    for sub in getattr(dependant, "dependencies", []):
        nombres |= _declarados(sub, vistos)
    return nombres


async def dep_parametros_conocidos(request: Request) -> None:
    """Rechaza lo que la ruta no mira. 422, nunca en silencio."""
    ruta = request.scope.get("route")
    dependant = getattr(ruta, "dependant", None)
    if dependant is None:
        return
    if motivo_de_apertura(getattr(ruta, "endpoint", None)):
        return

    sobran = sorted(
        n
        for n in request.query_params.keys()
        if n not in SIEMPRE_ADMITIDOS and n not in _declarados(dependant)
    )
    if not sobran:
        return

    from crmcore.errors import ErrorValidacion

    raise ErrorValidacion(
        "Esta operación no mira " + ", ".join(f"«{n}»" for n in sobran),
        error_code="peticion.parametro_desconocido",
        detalle={"admitidos": sorted(_declarados(dependant) | SIEMPRE_ADMITIDOS)},
    )
