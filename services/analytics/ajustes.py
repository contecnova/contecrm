"""Ajustes propios del servicio de explotación.

Los topes de los análisis sobre el CRM (CRM-05.01.03.04 a .06): cuánto se lee
de cada servicio para calcular una cohorte, un embudo o la relación entre
actividad y resultados. Son decisiones del despliegue —una instalación con
cien mil oportunidades no quiere que un clic las recorra todas— y por eso van
aquí y no escritas en el cálculo.
"""

from __future__ import annotations

from functools import lru_cache

from crmcore.config import Settings
from crmcore.runtime.keys import ClaveAjuste, registrar_claves
from crmcore.runtime.settings import registrar_ajustes_servicio
from pydantic import Field


class AjustesAnalytics(Settings):
    """Configuración del servicio `analytics`."""

    # ── Análisis sobre los datos del CRM (CRM-05.01.03.04, .05, .06) ──────
    # Cuántos registros de cada objeto se leen como mucho para un análisis.
    # Lo que pasa del tope se DICE en la respuesta: un embudo calculado sobre
    # las dos mil más recientes y presentado como «todas» engaña.
    analisis_max_registros: int = Field(2000, ge=50, le=50000)
    # Mínimo de sujetos para dar un coeficiente de correlación. Con cinco
    # comerciales, uno de vacaciones decide el signo. Era un 8 en el cálculo.
    analisis_minimo_correlacion: int = Field(8, ge=3, le=1000)
    # Qué ventana de tiempo miran el embudo y la actividad si no se dice otra.
    # Un año: cubre un ciclo de venta largo sin mezclar el equipo de hace tres.
    analisis_dias_ventana: int = Field(365, ge=7, le=3650)

    # ── Informes programados (CRM-05.01.01.06) ───────────────────────────
    # Fallos seguidos tras los que una programación se desactiva y se dice.
    # Era un 3 escrito en el barrido: con pocos, un corte de una noche apaga
    # un informe sano; con muchos, uno roto llena bandejas con el mismo error.
    informes_tope_fallos_seguidos: int = Field(3, ge=1, le=30)


registrar_claves(
    [
        ClaveAjuste(
            clave="analisis_max_registros",
            tipo="int",
            descripcion="Registros de cada objeto que se leen como mucho para un análisis",
            minimo=50,
            maximo=50000,
            campo_settings="analisis_max_registros",
        ),
        ClaveAjuste(
            clave="analisis_minimo_correlacion",
            tipo="int",
            descripcion="Sujetos mínimos para dar la correlación entre actividad y resultados",
            minimo=3,
            maximo=1000,
            campo_settings="analisis_minimo_correlacion",
        ),
        ClaveAjuste(
            clave="analisis_dias_ventana",
            tipo="int",
            descripcion="Días hacia atrás que miran el embudo y la actividad si no se dice otra cosa",
            minimo=7,
            maximo=3650,
            campo_settings="analisis_dias_ventana",
        ),
        ClaveAjuste(
            clave="informes_tope_fallos_seguidos",
            tipo="int",
            descripcion=(
                "Fallos seguidos tras los que un informe programado se desactiva " "y se avisa"
            ),
            minimo=1,
            maximo=30,
            campo_settings="informes_tope_fallos_seguidos",
        ),
    ]
)


@lru_cache(maxsize=1)
def ajustes() -> AjustesAnalytics:
    return AjustesAnalytics()


registrar_ajustes_servicio(ajustes)
