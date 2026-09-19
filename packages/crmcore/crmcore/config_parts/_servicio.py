"""Compromisos de servicio por tier: RPO, RTO y disponibilidad.

Están en la configuración y no en un documento porque un compromiso que solo
vive en un PDF no lo comprueba nadie. Aquí los lee el sistema —para avisar
cuando la última copia pasa del RPO— y la API los publica, así que el número que
se le enseña al cliente es el mismo que el que se vigila.

**Los valores por defecto son deliberadamente conservadores.** Un RPO de cinco
minutos escrito sin la infraestructura que lo sostenga es una promesa incumplida
el día que haga falta; uno de veinticuatro horas con copia diaria es cierto, y
subirlo es una decisión de negocio con coste, que es como debe tomarse.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class _ServicioSettings(BaseSettings):
    # ── RPO: cuánto dato se puede perder ──────────────────────────────────
    # Minutos de datos en riesgo. Con copia diaria, el RPO real es de hasta
    # 24 h; bajarlo exige archivado continuo del WAL, que es otra
    # infraestructura y otro coste.
    rpo_minutos_estandar: int = Field(1_440, ge=1, le=10_080)
    rpo_minutos_premium: int = Field(240, ge=1, le=10_080)
    rpo_minutos_enterprise: int = Field(15, ge=1, le=10_080)

    # ── RTO: cuánto se tarda en volver ────────────────────────────────────
    # Minutos hasta el servicio restablecido. Incluye restaurar los datos Y
    # levantar el sistema: medir solo la restauración es la trampa clásica —el
    # `pg_restore` tarda diez minutos y el servicio vuelve a la hora.
    rto_minutos_estandar: int = Field(480, ge=1, le=10_080)
    rto_minutos_premium: int = Field(120, ge=1, le=10_080)
    rto_minutos_enterprise: int = Field(30, ge=1, le=10_080)

    # ── Disponibilidad comprometida ───────────────────────────────────────
    # Porcentaje mensual. 99,5 % son 3 h 39 min de parada al mes; 99,9 %, 43 min.
    # Prometer 99,99 % (4 min) exige multi-región activo-activo: si no está
    # montado, el número es falso.
    disponibilidad_estandar: float = Field(99.5, ge=90.0, le=100.0)
    disponibilidad_premium: float = Field(99.9, ge=90.0, le=100.0)
    disponibilidad_enterprise: float = Field(99.95, ge=90.0, le=100.0)

    # Aviso cuando la última copia supera este porcentaje del RPO. Al 80 % queda
    # margen para reaccionar; al 100 % el aviso llega cuando ya se ha incumplido.
    rpo_aviso_pct: int = Field(80, ge=10, le=100)
