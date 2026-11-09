"""Ajustes propios del servicio de casos y SLA.

El primero que hubo que sacar de aquí no estaba en el servidor: estaba escrito
en el navegador. La bandeja de casos separa lo que **va a incumplir** de lo que
ya incumplió, y el corte entre las dos cosas eran cuatro horas puestas a mano en
una expresión —`4 * 3600_000`—.

Cuatro horas no significa lo mismo en todas partes. En un soporte con SLA de
cuatro horas, «quedan cuatro» es todo el plazo y la bandeja entera sale en
riesgo; en uno de cinco días, cuatro horas es tarde para reaccionar. Un umbral
así tiene que poder afinarlo quien opera, y afinarlo **por tenant**, porque dos
clientes del mismo despliegue compran niveles de servicio distintos.
"""

from __future__ import annotations

from functools import lru_cache

from crmcore.config import Settings
from crmcore.runtime.keys import ClaveAjuste, registrar_claves
from crmcore.runtime.settings import registrar_ajustes_servicio
from pydantic import Field


class AjustesService(Settings):
    """Configuración del servicio `service`."""

    # ── Bandeja de casos (CRM-07.04.03.17) ────────────────────────────────
    # Con cuánta antelación un caso pasa a «en riesgo» en la bandeja.
    #
    # Por defecto 4 h, que es lo que había escrito en el navegador: se conserva
    # para no cambiarle la pantalla a nadie al desplegar esto. Lo que cambia es
    # que ahora se puede mover sin tocar código, y por tenant.
    #
    # El rango llega a una semana porque hay soportes con SLA de días, donde
    # avisar con cuatro horas es avisar cuando ya no da tiempo a nada.
    sla_riesgo_horas: float = Field(4.0, ge=0.25, le=168.0)

    # ── SLA del proveedor frente al prometido (CRM-09.01.01.08) ───────────
    # Lo que tardamos NOSOTROS entre que el cliente avisa y el proveedor se
    # entera: recibir, diagnosticar, abrirle el parte. Se suma a los tiempos
    # del proveedor; prometer su mismo tiempo es prometer uno que solo
    # existiría si nosotros no hiciéramos nada. Una hora era la constante que
    # había escrita; cada soporte tiene la suya.
    sla_proveedor_horas_propias: float = Field(1.0, ge=0.0, le=168.0)
    # Cuánto se espera a que `integration` diga qué proveedores hay. Si no
    # contesta, la revisión sigue con los acuerdos guardados y lo dice.
    sla_proveedor_espera_s: float = Field(5.0, ge=0.5, le=60.0)


registrar_claves(
    [
        ClaveAjuste(
            clave="sla_riesgo_horas",
            tipo="float",
            descripcion=(
                "Antelación con la que un caso aparece «en riesgo» en la bandeja, " "en horas"
            ),
            minimo=0.25,
            maximo=168.0,
            campo_settings="sla_riesgo_horas",
        ),
        ClaveAjuste(
            clave="sla_proveedor_horas_propias",
            tipo="float",
            descripcion=(
                "Horas nuestras que se suman a los tiempos del proveedor al "
                "compararlos con lo prometido al cliente"
            ),
            minimo=0.0,
            maximo=168.0,
            campo_settings="sla_proveedor_horas_propias",
        ),
        ClaveAjuste(
            clave="sla_proveedor_espera_s",
            tipo="float",
            descripcion="Segundos que se espera la lista de proveedores de integración",
            minimo=0.5,
            maximo=60.0,
            campo_settings="sla_proveedor_espera_s",
        ),
    ]
)


@lru_cache(maxsize=1)
def ajustes() -> AjustesService:
    return AjustesService()


# Se le dice al núcleo de dónde salen estos ajustes, para que `rt.efectivo()`
# resuelva sus valores por defecto cuando nadie los ha fijado en la base.
registrar_ajustes_servicio(ajustes)
