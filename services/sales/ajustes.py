"""Ajustes propios del servicio de ventas."""

from __future__ import annotations

from functools import lru_cache

from crmcore.config import Settings
from crmcore.runtime.keys import ClaveAjuste, registrar_claves
from crmcore.runtime.settings import registrar_ajustes_servicio
from pydantic import Field


class AjustesSales(Settings):
    """Configuración del servicio `sales`."""

    # ── SLA de primera respuesta (CRM-01.01.03.07) ────────────────────────
    # Horas para responder a un lead nuevo. Cuatro horas laborables es el valor
    # que suele usarse: por encima de eso la probabilidad de contactar cae en
    # picado, y por debajo hace falta un equipo dedicado.
    lead_sla_primera_respuesta_horas: int = Field(4, ge=1, le=720)
    # Reasignar el lead si nadie responde dentro del SLA. Apagado por defecto:
    # reasignar automáticamente puede quitarle un lead a quien ya lo estaba
    # trabajando por teléfono sin registrarlo.
    lead_reasignar_al_incumplir_sla: bool = False

    # ── Ciclo del lead ────────────────────────────────────────────────────
    # Días tras los que un lead descartado vuelve a la cola de reciclaje.
    lead_dias_reciclaje: int = Field(180, ge=0, le=3650)

    # ── Oportunidades ─────────────────────────────────────────────────────
    # Exigir los criterios de salida de la etapa para poder avanzar. Es lo que
    # hace que la previsión signifique algo; se puede apagar durante la carga
    # inicial de datos históricos, que nunca los cumplen.
    exigir_criterios_salida: bool = True
    # Bloquear la edición de una oportunidad cerrada (CRM-03.01.01.14).
    bloquear_al_cerrar: bool = True
    # Exigir motivo de pérdida normalizado al cerrar como perdida. Sin esto, el
    # análisis de pérdidas es una nube de texto libre imposible de agrupar.
    exigir_motivo_perdida: bool = True
    # Días sin actividad tras los que una oportunidad se marca como estancada,
    # cuando su etapa no declara uno propio.
    dias_estancamiento_defecto: int = Field(30, ge=1, le=365)
    # Prefijo y formato del código legible de oportunidad.
    codigo_prefijo: str = "OPP"


registrar_claves(
    [
        ClaveAjuste(
            clave="lead_sla_primera_respuesta_horas",
            tipo="int",
            descripcion="Horas para dar la primera respuesta a un lead",
            minimo=1,
            maximo=720,
            campo_settings="lead_sla_primera_respuesta_horas",
        ),
        ClaveAjuste(
            clave="lead_reasignar_al_incumplir_sla",
            tipo="bool",
            descripcion="Reasignar automáticamente el lead si se incumple el SLA",
            campo_settings="lead_reasignar_al_incumplir_sla",
        ),
        ClaveAjuste(
            clave="lead_dias_reciclaje",
            tipo="int",
            descripcion="Días tras los que un lead descartado vuelve a la cola",
            minimo=0,
            maximo=3650,
            campo_settings="lead_dias_reciclaje",
        ),
        ClaveAjuste(
            clave="exigir_criterios_salida",
            tipo="bool",
            descripcion="Exigir los criterios de la etapa para avanzar una oportunidad",
            campo_settings="exigir_criterios_salida",
            sensible=True,
        ),
        ClaveAjuste(
            clave="bloquear_al_cerrar",
            tipo="bool",
            descripcion="Bloquear la edición de una oportunidad cerrada",
            campo_settings="bloquear_al_cerrar",
            sensible=True,
        ),
        ClaveAjuste(
            clave="exigir_motivo_perdida",
            tipo="bool",
            descripcion="Exigir motivo normalizado al marcar una oportunidad como perdida",
            campo_settings="exigir_motivo_perdida",
        ),
        ClaveAjuste(
            clave="dias_estancamiento_defecto",
            tipo="int",
            descripcion="Días sin movimiento tras los que una oportunidad se marca estancada",
            minimo=1,
            maximo=365,
            campo_settings="dias_estancamiento_defecto",
        ),
    ]
)


@lru_cache(maxsize=1)
def ajustes() -> AjustesSales:
    return AjustesSales()


registrar_ajustes_servicio(ajustes)
