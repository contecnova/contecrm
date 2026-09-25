"""Worker de trabajos asíncronos de `analytics`.

    python -m services.analytics.trabajos_worker

El bucle está en `crmcore`; aquí solo se importa lo que registra los ejecutores
y se arranca. **El import no es decorativo**: el worker es otro proceso, así que
nada de lo que importa la API está importado aquí.
"""

from __future__ import annotations

from crmcore.datos.trabajos_worker import run

import services.analytics.trabajos_fuente  # noqa: F401 — registra el ejecutor

if __name__ == "__main__":
    run(nombre="analytics-trabajos")
