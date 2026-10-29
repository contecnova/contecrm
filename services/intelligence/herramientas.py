"""Herramientas de agente derivadas de las propias APIs del CRM
(CRM-05.02.03.02).

Un agente sirve para lo que puede hacer, y lo que puede hacer se define casi
siempre a mano: alguien escribe quince herramientas, las mantiene un tiempo y
luego el CRM crece por otro lado. A los seis meses el agente sabe hacer lo que
alguien recordó declarar y no sabe hacer lo que se añadió después.

Aquí las herramientas **son la API**. Se derivan del contrato que cada servicio
ya publica —el mismo que consume un integrador—, así que una ruta nueva es una
herramienta nueva sin que nadie la transcriba, y una ruta retirada deja de
existir para el agente el mismo día.

Las decisiones:

**Solo lo que su principal puede.** El catálogo se cruza con los permisos del
agente, que son suyos y normalmente un subconjunto de los de quien lo puso en
marcha. Un agente que hereda los permisos del jefe convierte cualquier error suyo
en un error con los permisos del jefe.

**Lo peligroso no entra por defecto.** Borrar no se ofrece salvo que alguien lo
declare expresamente: una herramienta de borrado disponible «porque la API la
tiene» es la que acaba usándose por una instrucción mal entendida.

**Cada herramienta lleva su permiso y su riesgo a la vista.** El riesgo es lo que
después decide si hace falta que una persona lo apruebe, y calcularlo en el
momento de ejecutar significaría calcularlo con prisa.
"""

from __future__ import annotations

import re
from typing import Any

from crmcore.logging import get_logger

logger = get_logger(__name__)

# Qué riesgo tiene cada método. No es cosmético: de aquí sale si un paso necesita
# aprobación humana, y por eso se decide al construir el catálogo y no al
# ejecutar, que es cuando hay prisa.
RIESGO_POR_METODO = {
    "GET": "lectura",
    "POST": "escritura",
    "PUT": "escritura",
    "PATCH": "escritura",
    "DELETE": "destructivo",
}

# Lo destructivo no se ofrece salvo que se pida. Una herramienta de borrado
# disponible «porque la API la tiene» es la que acaba usándose por una
# instrucción mal entendida, y entonces la conversación ya no es sobre el agente.
RIESGOS_POR_DEFECTO = ("lectura", "escritura")


def _nombre_de(metodo: str, ruta: str) -> str:
    """Un nombre estable y legible para la herramienta.

    Estable importa: si cambiara entre arranques, las aprobaciones y la auditoría
    apuntarían a herramientas que ya no se llaman así.
    """
    limpio = re.sub(r"\{([a-z_]+)\}", r"por_\1", ruta.strip("/"))
    limpio = re.sub(r"[^a-zA-Z0-9]+", "_", limpio).strip("_")
    return f"{metodo.lower()}_{limpio}"[:80]


def desde_openapi(
    contrato: dict[str, Any],
    *,
    permisos: frozenset[str] | set[str],
    riesgos_admitidos: tuple[str, ...] = RIESGOS_POR_DEFECTO,
    solo_rutas: list[str] | None = None,
) -> dict[str, Any]:
    """Construye el catálogo de herramientas de un agente desde un OpenAPI.

    Devuelve también **lo que ha quedado fuera y por qué**. Sin eso, un agente
    que no sabe hacer algo parece tonto cuando en realidad está bien acotado, y
    quien lo configuró no tiene forma de saber cuál de las dos cosas pasa.
    """
    from crmcore.authz.matriz import _cubre

    herramientas: list[dict[str, Any]] = []
    fuera: dict[str, list[str]] = {"sin_permiso": [], "riesgo_no_admitido": [], "sin_declarar": []}

    for ruta, operaciones in (contrato.get("paths") or {}).items():
        if solo_rutas and not any(ruta.startswith(p) for p in solo_rutas):
            continue
        for metodo, operacion in (operaciones or {}).items():
            metodo = metodo.upper()
            if metodo not in RIESGO_POR_METODO:
                continue
            riesgo = RIESGO_POR_METODO[metodo]
            exigido = _permiso_de(operacion)
            if exigido and not any(_cubre(p, exigido) for p in permisos):
                fuera["sin_permiso"].append(f"{metodo} {ruta}")
                continue
            if riesgo not in riesgos_admitidos:
                fuera["riesgo_no_admitido"].append(f"{metodo} {ruta}")
                continue
            herramientas.append(
                {
                    "nombre": _nombre_de(metodo, ruta),
                    "metodo": metodo,
                    "ruta": ruta,
                    "descripcion": _descripcion_de(operacion, metodo, ruta),
                    "riesgo": riesgo,
                    "permiso": exigido,
                    "parametros": _parametros_de(operacion),
                }
            )

    return {
        "herramientas": sorted(herramientas, key=lambda h: h["nombre"]),
        "cuantas": len(herramientas),
        # Las dos listas no son lo mismo y confundirlas lleva a conceder permisos
        # que no hacían falta: una dice «no puede», la otra «no se le ha querido
        # dar».
        "fuera": fuera,
        "riesgos_admitidos": list(riesgos_admitidos),
        "aviso": (
            ""
            if herramientas
            else "El agente no tiene ninguna herramienta: con este principal y "
            "estos riesgos admitidos no puede hacer nada, y eso no es un fallo "
            "del modelo."
        ),
    }


def _permiso_de(operacion: dict[str, Any]) -> str:
    """El permiso que exige una operación, si el contrato lo declara.

    Cuando el contrato no lo dice, se devuelve vacío y la herramienta **entra**:
    el permiso real lo sigue comprobando el servicio al recibir la llamada. Aquí
    el filtro es una comodidad —no ofrecer lo que se sabe que va a fallar—, no un
    control de seguridad; tratarlo como control sería poner la puerta en el sitio
    donde el agente decide qué pedir.
    """
    extension = operacion.get("x-permiso") or operacion.get("x-permiso-exigido")
    return str(extension or "")


# Lo que se le añade a la descripción de un LISTADO, y por qué no basta con el
# resumen de la operación.
#
# **Medido el 29-10-2026.** El contrato de un listado declara siete parámetros y
# el servidor acepta filtros sobre treinta columnas con nueve operadores. El
# agente no tenía cómo enterarse: a «hay contactos sin teléfono» se traía cien
# contactos y los miraba uno a uno —y avisaba de que la lista venía cortada—
# cuando `?telefono__vacio=true` lo contesta de una.
#
# Se dice aquí y no en el resumen de cada ruta porque es verdad de TODOS los
# listados: escribirlo ruta por ruta son ciento y pico sitios, y el que se
# olvide deja al agente adivinando en ése.
_COMO_SE_FILTRA = (
    " · Admite filtrar por columna: `?campo=valor`, y con sufijo "
    "`?campo__desde=…`, `__hasta`, `__mayor`, `__menor`, `__distinto`, `__en`, "
    "`__vacio=true`, `__no_vacio=true`. **Para saber por qué campos**, usa la "
    "herramienta de filtros de este servicio antes de traerte la lista entera: "
    "filtrar contesta de una lo que mirando fila a fila sale cortado."
    " · **Para contar, `?contar=true`**: devuelve `total_aprox` con los filtros "
    "puestos, sin traerse las filas. Contar paginando da el número de la "
    "primera página y lo cuenta como si fuera el total."
)


def _es_un_listado(metodo: str, ruta: str) -> bool:
    """Un `GET` de colección: sin parámetro en el último tramo."""
    return metodo == "GET" and not ruta.rstrip("/").endswith("}")


def _descripcion_de(operacion: dict[str, Any], metodo: str, ruta: str) -> str:
    """Qué hace la herramienta, y —si es un listado— cómo se le acota."""
    base = str(operacion.get("summary") or operacion.get("description") or "")[:400]
    if _es_un_listado(metodo, ruta) and "/filtros" not in ruta:
        return base + _COMO_SE_FILTRA
    return base


def _parametros_de(operacion: dict[str, Any]) -> dict[str, Any]:
    """Qué acepta la herramienta, en el esquema que entiende un modelo."""
    propiedades: dict[str, Any] = {}
    obligatorios: list[str] = []
    for parametro in operacion.get("parameters") or []:
        nombre = str(parametro.get("name") or "")
        if not nombre:
            continue
        esquema = parametro.get("schema") or {}
        tipo = str(esquema.get("type") or "string")
        propiedades[nombre] = {
            "type": tipo,
            "description": str(parametro.get("description") or "")[:200],
            "in": str(parametro.get("in") or "query"),
        }
        # **Una lista tiene que decir de qué.** Un `{"type": "array"}` a secas
        # no es un JSON Schema completo: dos familias de proveedor lo aceptan y
        # **Gemini rechaza la llamada entera** —«parameters.properties[x].items:
        # missing field»—, con lo que una sola herramienta mal descrita deja al
        # agente sin ninguna. Se toma lo que diga el contrato y, si no lo dice,
        # cadena: un parámetro de lista en una URL viaja como texto.
        if tipo == "array":
            propiedades[nombre]["items"] = dict(esquema.get("items") or {"type": "string"})
        # Y si el contrato declara los valores admitidos, viajan. No es adorno:
        # sin la lista cerrada delante, el modelo escribe un valor plausible y
        # el servicio contesta 422 — un intento gastado para enterarse de algo
        # que ya estaba escrito en el contrato.
        if esquema.get("enum"):
            propiedades[nombre]["enum"] = list(esquema["enum"])
        if parametro.get("required"):
            obligatorios.append(nombre)

    cuerpo = ((operacion.get("requestBody") or {}).get("content") or {}).get(
        "application/json"
    ) or {}
    if cuerpo.get("schema"):
        propiedades["cuerpo"] = {"type": "object", "description": "Cuerpo de la petición"}
        if (operacion.get("requestBody") or {}).get("required"):
            obligatorios.append("cuerpo")

    return {"type": "object", "properties": propiedades, "required": sorted(set(obligatorios))}
