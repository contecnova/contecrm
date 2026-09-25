"""Worker de trabajos asíncronos de `intelligence`.

    python -m services.intelligence.trabajos_worker

El bucle está en `crmcore`; aquí solo se importa lo que registra los ejecutores.
"""

from __future__ import annotations

from crmcore.datos.trabajos_worker import run

import services.intelligence.trabajos_salud  # noqa: F401 — registra el ejecutor

if __name__ == "__main__":
    run(nombre="intelligence-trabajos")
