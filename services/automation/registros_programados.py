"""Los registros sobre los que corre una regla programada (CRM-00.03.03.05).

Una regla programada sobre «lead» no trae registro: la dispara el reloj. Hasta
el 09-11-2026 corría una vez, sin lead, y la sembrada «Lead sin atender en 48
horas» habría mandado cada mañana un aviso que no decía de qué lead. Ahora, al
llegar su hora, se piden los registros de su objetivo al servicio que los
guarda —con la identidad de quien activó la regla, que es con la que actúa—, se
quedan los que cumplen sus condiciones y se deja en la cola una ejecución por
cada uno. La cola ya da idempotencia, reintentos y traza.

La colección se pregunta, no se escribe: cada servicio dice en
`GET /{servicio}/filtros` qué objetos guarda y en qué ruta. Una tabla «objeto →
ruta» aquí se quedaría atrás el primer día que un servicio añada uno.
"""

from __future__ import annotations

from typing import Any

from crmcore.logging import get_logger

logger = get_logger(__name__)

# Objeto → colección, por proceso: no cambia mientras el despliegue no cambie.
_COLECCIONES: dict[str, str] = {}


def _llamar(ruta: str, identidad: dict[str, Any], tenant_id: Any, **parametros: Any) -> Any:
    from crmcore.http.interno import invocar

    respuesta = invocar(
        metodo="GET",
        ruta=ruta,
        parametros=parametros or None,
        tenant_id=tenant_id,
        principal_id=identidad["principal_id"],
        permisos=identidad.get("permisos") or [],
        roles=identidad.get("roles") or [],
    )
    return respuesta["datos"] if respuesta.get("estado") == 200 else None


def coleccion_de(objeto: str, *, tenant_id: Any, identidad: dict[str, Any]) -> str | None:
    """La ruta de la colección de este objeto, preguntando a los servicios."""
    if objeto in _COLECCIONES:
        return _COLECCIONES[objeto]
    from crmcore.config import get_settings
    from crmcore.rutas_de_api import cargar_destinos

    for servicio in sorted(cargar_destinos(get_settings().rutas_servicios)):
        try:
            datos = _llamar(f"/api/v1/{servicio}/filtros", identidad, tenant_id)
        except Exception:  # noqa: BLE001 — un servicio caído no tapa a los demás
            continue
        ruta = ((datos or {}).get("colecciones") or {}).get(objeto)
        if ruta:
            _COLECCIONES[objeto] = str(ruta)
            return _COLECCIONES[objeto]
    return None


def registros_de(
    objeto: str, *, tenant_id: Any, identidad: dict[str, Any], maximo: int
) -> list[dict[str, Any]] | None:
    """Hasta `maximo` registros del objeto, por páginas. `None` si no es una colección."""
    ruta = coleccion_de(objeto, tenant_id=tenant_id, identidad=identidad)
    if ruta is None:
        return None
    salida: list[dict[str, Any]] = []
    cursor = ""
    while len(salida) < maximo:
        parametros: dict[str, Any] = {"limite": min(200, maximo - len(salida))}
        if cursor:
            parametros["cursor"] = cursor
        datos = _llamar(ruta, identidad, tenant_id, **parametros)
        if not isinstance(datos, dict):
            break
        salida.extend(f for f in datos.get("items") or [] if isinstance(f, dict))
        cursor = str(datos.get("siguiente") or "")
        if not cursor:
            break
    if len(salida) >= maximo:
        # Se dice: una regla que recorre sólo los primeros mil sin avisarlo
        # deja fuera al resto en silencio.
        logger.warning("automatizacion.programada_tope", objeto=objeto, maximo=maximo)
    return salida[:maximo]
