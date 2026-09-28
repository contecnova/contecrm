"""Punto de entrada del motor de procesos."""

from __future__ import annotations

from crmcore.service import crear_servicio

from services.orchestrator.api import ROUTERS
from services.orchestrator.api_aprobaciones import ROUTERS_APROBACIONES
from services.orchestrator.organizacion import consumir as consumir_organigrama


def _al_arrancar() -> None:
    """Declara al panel que este módulo sabe contar ejecuciones de proceso.

    Va aquí y no en el núcleo porque quien sabe contarlas es este servicio: las
    instancias viven en su esquema y nadie más las ve.
    """
    from crmcore.consumo import registrar_medidor
    from crmcore.db.session import sesion  # noqa: F401 — documenta de dónde sale la sesión

    from services.orchestrator.motor import Motor

    def _medir(db: object, tenant_id: object) -> tuple[int, str]:
        return Motor(db)._ejecuciones_del_periodo(tenant_id), "cuota_workflows_mes"

    registrar_medidor("workflows", _medir)


app = crear_servicio(
    nombre="orchestrator",
    descripcion=(
        "Motor de procesos duradero: sagas con compensación, tareas humanas "
        "con SLA, temporizadores, subprocesos, simulación y límites de "
        "ejecución. El estado vive en la base, así que un proceso sobrevive a "
        "la caída del worker que lo ejecutaba. Encima, las aprobaciones: "
        "quórum configurable, resolución del aprobador por regla, delegación "
        "con vigencia, escalado que avisa antes, reaprobación cuando cambia lo "
        "aprobado y decisión desde el correo."
    ),
    routers=[*ROUTERS, *ROUTERS_APROBACIONES],
    # El organigrama del tenant, replicado. Sin él no se puede resolver a quién
    # le toca aprobar por jerarquía, y pedírselo a `identity` en mitad de una
    # transacción de aquí ataría una decisión de negocio a que otro servicio
    # esté en pie.
    al_arrancar=_al_arrancar,
    consumidores=[("user.org.changed", consumir_organigrama, "orchestrator-organigrama")],
)
