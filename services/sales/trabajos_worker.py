"""Worker de trabajos asíncronos de `sales`.

    python -m services.sales.trabajos_worker

El bucle está en `crmcore`. El import de `masivo` es lo que registra los
ejecutores en ESTE proceso, que no es el de la API.
"""

from __future__ import annotations

import crmcore.datos.materializar  # noqa: F401 — el de materializar un campo
from crmcore.datos.trabajos_worker import run

import services.sales.masivo  # noqa: F401 — registra los ejecutores

if __name__ == "__main__":
    run(nombre="sales-trabajos")
