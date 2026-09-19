"""Worker de trabajos asíncronos de `party`.

    python -m services.party.trabajos_worker

El bucle está en `crmcore`; aquí solo se importa lo que registra los ejecutores
y se arranca. **El import no es decorativo**: el worker es un proceso distinto
del de la API, así que nada de lo que la API importa está importado aquí, y sin
esta línea el worker arrancaría sin conocer un solo tipo de trabajo y los dejaría
encolados para siempre.
"""

from __future__ import annotations

from crmcore.datos.trabajos_worker import run

import services.party.masivo  # noqa: F401 — registra los ejecutores

if __name__ == "__main__":
    run(nombre="party-trabajos")
