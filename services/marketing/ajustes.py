"""Ajustes propios del servicio de marketing."""

from __future__ import annotations

from functools import lru_cache

from crmcore.config import Settings
from crmcore.runtime.keys import ClaveAjuste, registrar_claves
from crmcore.runtime.settings import registrar_ajustes_servicio
from pydantic import Field


class AjustesMarketing(Settings):
    """Configuración del servicio `marketing`."""

    # ── Separación transaccional / promocional (CRM-02.03.01.07) ──────────
    # Dominios de envío. Van separados porque comparten reputación: una campaña
    # con muchas quejas hunde la entrega de las facturas, y mezclarlos hace que
    # darse de baja de la newsletter parezca que apaga los avisos de servicio.
    # Vacíos por defecto **a propósito**: así el sistema dice que no están
    # separados en vez de fingir que sí con un valor inventado.
    dominio_promocional: str = ""
    dominio_transaccional: str = ""

    # ── Recorridos (CRM-02.02.02) ─────────────────────────────────────────
    # Mínimo de personas por variante para declarar ganadora una prueba A/B. Con
    # menos, la diferencia que se ve es ruido y elegir por ella consolida una
    # variante peor con la confianza de haberla medido.
    prueba_minimo_por_variante: int = 100

    # ── Fondos de marketing del canal (CRM-03.04.01.04) ───────────────────
    # Plazo para justificar una acción aprobada con MDF. Sin plazo, las facturas
    # llegan contra un presupuesto que ya cerró y no las paga nadie.
    mdf_dias_para_justificar: int = Field(60, ge=1, le=365)
    # Exigir evidencia documental para justificar. Encendido: lo que se paga sin
    # factura ni material no se puede defender en una auditoría. Se puede apagar
    # en programas donde la evidencia la lleva otro sistema.
    mdf_exigir_evidencia: bool = True


registrar_claves(
    [
        ClaveAjuste(
            clave="dominio_promocional",
            tipo="str",
            descripcion="Dominio de envío de lo promocional",
            campo_settings="dominio_promocional",
        ),
        ClaveAjuste(
            clave="dominio_transaccional",
            tipo="str",
            descripcion="Dominio de envío de lo transaccional (facturas, avisos)",
            campo_settings="dominio_transaccional",
        ),
        ClaveAjuste(
            clave="mdf_dias_para_justificar",
            tipo="int",
            descripcion="Plazo para justificar una acción aprobada con fondos de marketing",
            minimo=1,
            maximo=365,
            campo_settings="mdf_dias_para_justificar",
            sensible=True,
        ),
        ClaveAjuste(
            clave="mdf_exigir_evidencia",
            tipo="bool",
            descripcion="Exigir evidencia documental para justificar un gasto de MDF",
            campo_settings="mdf_exigir_evidencia",
            sensible=True,
        ),
        ClaveAjuste(
            clave="prueba_minimo_por_variante",
            tipo="int",
            descripcion="Personas mínimas por variante para declarar ganadora una prueba A/B",
            minimo=10,
            maximo=100000,
            campo_settings="prueba_minimo_por_variante",
        ),
    ]
)


@lru_cache(maxsize=1)
def ajustes() -> AjustesMarketing:
    return AjustesMarketing()


registrar_ajustes_servicio(ajustes)
