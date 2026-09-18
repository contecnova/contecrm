"""Punto de entrada del motor de procesos."""

from __future__ import annotations

from crmcore.service import crear_servicio

from services.orchestrator.api import ROUTERS

app = crear_servicio(
    nombre="orchestrator",
    descripcion=(
        "Motor de procesos duradero: sagas con compensación, tareas humanas "
        "con SLA, temporizadores, subprocesos, simulación y límites de "
        "ejecución. El estado vive en la base, así que un proceso sobrevive a "
        "la caída del worker que lo ejecutaba."
    ),
    routers=ROUTERS,
)
