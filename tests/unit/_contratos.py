"""Los contratos OpenAPI de los catorce servicios, construidos una sola vez.

**Por qué existe este fichero.** Construir el OpenAPI de un servicio obliga a
generar el esquema de cada modelo que publica, y son catorce servicios: medido,
5,6 s en importar las aplicaciones y ~5 s en generar los esquemas. Varios gates
del preflight lo necesitan —el de acciones alcanzables, el de atributos, el de
lo que la pantalla pide— y **cada uno lo pagaba entero**. Peor: el de acciones
lo pagaba DOS veces, una en la parametrización por servicio y otra en el
recuento final que comprueba que el barrido no mira el vacío, así que
construía veintiocho contratos para mirar catorce.

Con la caché, dentro de una misma ejecución de pytest se construye uno por
servicio y lo comparten todas las pruebas del proceso. No es una optimización
cosmética: el nivel «push» del preflight tiene un presupuesto de 200 s de CPU
declarado, y un preflight que se pasa de tres minutos deja de correrse — con lo
que el coste se paga entero y la garantía no llega.

No cachea entre procesos a propósito: un contrato guardado en disco que se
quede viejo daría verde sobre un código que ya no es ése, y eso es peor que
tardar.
"""

from __future__ import annotations

import functools
import importlib
import os
from typing import Any

# Los catorce que publican API. Escrito y no deducido, como en el sellado del
# contrato: un servicio nuevo que no conste aquí quedaría sin mirar en silencio.
SERVICIOS: tuple[str, ...] = (
    "analytics",
    "automation",
    "eventing",
    "gateway",
    "identity",
    "integration",
    "intelligence",
    "marketing",
    "metadata",
    "orchestrator",
    "party",
    "sales",
    "service",
    "tenancy",
)


@functools.cache
def contrato(servicio: str) -> dict[str, Any]:
    """El OpenAPI de ese servicio. Construido una vez por proceso."""
    from crmcore.config import limpiar_cache_settings

    os.environ["SERVICE_NAME"] = servicio
    os.environ.setdefault("OUTBOX_ENABLED", "false")
    limpiar_cache_settings()
    return importlib.import_module(f"services.{servicio}.main").app.openapi()


@functools.cache
def caminos(servicio: str) -> dict[str, Any]:
    """Sólo los caminos, que es lo que casi todo el mundo quiere."""
    return contrato(servicio).get("paths") or {}
