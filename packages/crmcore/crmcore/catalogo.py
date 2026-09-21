"""El catálogo funcional, disponible en ejecución.

`docs/catalogo/catalogo.yaml` es la fuente de verdad del alcance del producto:
631 capacidades con identificador estable, y de ahí salen el manual, la matriz
de trazabilidad y los gates. Hasta ahora solo se leía en las pruebas y en los
generadores.

Hace falta **en ejecución** por el GRC (CRM-07.03.02.04): cada control se ancla
a capacidades por su identificador, y eso exige poder comprobar que el
identificador existe y decir a qué se refiere. Sin esta comprobación, «control
sobre CRM-99.99.99.99» se guardaría tan tranquilo y el informe de cobertura
contaría un control que no cubre nada.

Se lee del fichero y no de una copia generada a propósito: una copia son dos
verdades, y la que se queda vieja siempre es la copia.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from crmcore.logging import get_logger

logger = get_logger(__name__)

# El sitio del fichero en el repositorio y en la imagen. Configurable porque un
# despliegue puede montarlo en otro sitio, y sin `Settings` porque esto se lee
# una vez al arrancar y no es un ajuste de negocio.
RUTA = Path(
    os.environ.get("CATALOGO_PATH")
    or Path(__file__).resolve().parents[3] / "docs" / "catalogo" / "catalogo.yaml"
)


@lru_cache(maxsize=1)
def capacidades() -> dict[str, dict[str, Any]]:
    """Todas las capacidades por identificador. Vacío si el fichero no está.

    Devolver vacío y no lanzar es deliberado: un servicio no puede negarse a
    arrancar porque falte un fichero de catálogo. Lo que pasa sin él es que el
    GRC no puede validar los anclajes, y eso lo dice quien lo necesita en vez de
    tumbar el arranque de todos.
    """
    if not RUTA.exists():
        logger.warning("catalogo.no_encontrado", ruta=str(RUTA))
        return {}
    import yaml

    datos = yaml.safe_load(RUTA.read_text(encoding="utf-8")) or {}
    salida: dict[str, dict[str, Any]] = {}
    for modulo in datos.get("modulos", []):
        for seccion in modulo.get("secciones", []):
            for funcion in seccion.get("funciones", []):
                for cap in funcion.get("capacidades", []):
                    salida[cap["id"]] = {
                        "id": cap["id"],
                        "titulo": cap.get("t", ""),
                        "criticidad": cap.get("c", ""),
                        "fase": cap.get("fase"),
                        "servicio": cap.get("svc", ""),
                        "estado": cap.get("estado", "pendiente"),
                        "modulo": f"{modulo['id']} · {modulo['nombre']}",
                        "seccion": f"{seccion['id']} · {seccion['nombre']}",
                        "seccion_id": seccion["id"],
                    }
    return salida


def existe(capacidad_id: str) -> bool:
    return capacidad_id in capacidades()


def descripcion(capacidad_id: str) -> str:
    return capacidades().get(capacidad_id, {}).get("titulo", "")


def disponible() -> bool:
    """Si el catálogo se ha podido leer. Lo consulta quien depende de él."""
    return bool(capacidades())


def invalidar() -> None:
    capacidades.cache_clear()
