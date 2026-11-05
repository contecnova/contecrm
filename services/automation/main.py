"""Punto de entrada del servicio de automatizaciones."""

from __future__ import annotations

from crmcore.service import crear_servicio

from services.automation.api import ROUTERS
from services.automation.api_codigo import ROUTERS_CODIGO
from services.automation.consumidores import consumir_evento


def _al_arrancar() -> None:
    """Declara al panel de consumo que este módulo cuenta ejecuciones de código propio."""
    from crmcore.consumo import registrar_medidor

    from services.automation.codigo_tenant import _ejecuciones_del_mes

    def _medir(db: object, tenant_id: object) -> tuple[int, str]:
        return _ejecuciones_del_mes(db, tenant_id), "cuota_extensiones_mes"  # type: ignore[arg-type]

    registrar_medidor("extensiones", _medir)


app = crear_servicio(
    nombre="automation",
    descripcion=(
        "Automatizaciones declarativas «cuando X, si Y, entonces Z», con orden "
        "determinista entre reglas, corte de cascada, prueba en seco y traza de "
        "por qué una regla no se disparó."
    ),
    routers=[*ROUTERS, *ROUTERS_CODIGO],
    # Las reglas se disparan con los eventos de dominio de los demás servicios.
    # El patrón es ancho y filtra la tabla `DISPARADORES`: mantener una lista de
    # suscripciones al día con esa tabla sería una segunda fuente de verdad.
    consumidores=[("*", consumir_evento, "automation-reglas")],
    al_arrancar=_al_arrancar,
)
