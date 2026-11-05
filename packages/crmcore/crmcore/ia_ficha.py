"""La IA desde la ficha: leer y pedir **como quien pulsa el botón**.

Las capacidades de IA vivían en `intelligence` como cálculos a los que había que
darles los hechos —«resume esta cuenta con estos datos»—, y por eso no se podían
poner en ninguna ficha: la pantalla habría tenido que pedirle a alguien que
tecleara lo que el CRM ya sabe. Ahora la ficha de cada registro ofrece la
acción, y el servicio dueño del registro reúne los hechos y se los pasa.

Las dos cosas se hacen **con la identidad de quien lo pide**, por la API:

- leer el registro por su ruta, y no con la función por dentro, para que pase
  por la máscara de campos por rol. Lo que esa persona no ve, el modelo
  tampoco;
- pedir a `intelligence` con sus permisos, que es con lo que sus guardarraíles
  deciden qué contexto sale hacia el proveedor.

Y los errores del otro lado **se devuelven con su estado**: «no hay proveedor
de IA» es un 409 que hay que leer, no un 500.
"""

from __future__ import annotations

from typing import Any

from crmcore.errors import (
    Conflicto,
    CrmError,
    ErrorDependencia,
    ErrorValidacion,
    LimiteExcedido,
    NoEncontrado,
    Prohibido,
)

_POR_ESTADO: dict[int, type[CrmError]] = {
    403: Prohibido,
    404: NoEncontrado,
    409: Conflicto,
    422: ErrorValidacion,
    429: LimiteExcedido,
}


def _identidad(principal: Any) -> dict[str, Any]:
    return {
        "tenant_id": principal.tenant_id,
        "principal_id": principal.id or principal.tenant_id,
        "permisos": sorted(principal.permisos),
        "roles": sorted(principal.roles),
    }


def _contestado(respuesta: dict[str, Any], que: str) -> Any:
    estado = int(respuesta.get("estado") or 0)
    datos = respuesta.get("datos")
    if 200 <= estado < 300:
        return datos
    detalle = datos if isinstance(datos, dict) else {}
    clase = _POR_ESTADO.get(estado, ErrorDependencia)
    raise clase(
        str(detalle.get("detail") or f"{que} ha contestado {estado}"),
        error_code=str(detalle.get("error_code") or "ia.dependencia"),
        detalle={k: v for k, v in detalle.items() if k in ("detalle", "porque")} or None,
    )


def leer(ruta: str, principal: Any, parametros: dict[str, Any] | None = None) -> Any:
    """GET por la API con la identidad de quien pide."""
    from crmcore.http.interno import invocar

    return _contestado(
        invocar(metodo="GET", ruta=ruta, parametros=parametros, **_identidad(principal)),
        ruta,
    )


def pedir(ruta: str, cuerpo: dict[str, Any], principal: Any) -> Any:
    """POST a `intelligence` (o a quien sea) con la identidad de quien pide."""
    from crmcore.http.interno import invocar

    return _contestado(
        invocar(metodo="POST", ruta=ruta, cuerpo=cuerpo, timeout_s=120.0, **_identidad(principal)),
        ruta,
    )
