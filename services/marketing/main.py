"""Punto de entrada del servicio de marketing."""

from __future__ import annotations

from typing import Any

from crmcore.service import crear_servicio

from services.marketing import (
    ajustes,  # noqa: F401  (registra las claves de ajuste)
)
from services.marketing.api import ROUTERS
from services.marketing.api_canales import ROUTERS_CANALES
from services.marketing.api_canales_externos import ROUTERS_CANALES_EXTERNOS
from services.marketing.api_consentimiento import ROUTERS_CONSENTIMIENTO
from services.marketing.api_envios import ROUTERS_ENVIOS
from services.marketing.api_fondos import ROUTERS_FONDOS
from services.marketing.api_momento import ROUTERS_MOMENTO
from services.marketing.api_recorridos import ROUTERS_RECORRIDOS
from services.marketing.proyeccion import consumir

_relevo: Any = None
_tarea_relevo: Any = None


def _intervalo(clave: str) -> float:
    """El intervalo efectivo global: el de Admin si lo han tocado, si no el del `.env`.

    Se lee al arrancar: cambiarlo en Admin vale desde el siguiente arranque. Si
    la base no contesta al arrancar, el del fichero; no arrancar las tareas por
    eso sería peor que arrancarlas con el valor de siempre.
    """
    from crmcore.db.session import sesion

    from services.marketing.ajustes import ajustes as ajustes_marketing
    from services.marketing.ajustes import valor

    try:
        with sesion(sistema=True) as db:
            return float(valor(clave, db))
    except Exception:  # noqa: BLE001 — sin base, el del fichero
        return float(getattr(ajustes_marketing(), clave))


def _tareas() -> list[Any]:
    """Lo que este servicio hace solo, cada tanto.

    Hasta el 09-11-2026 los envíos programados y los pasos de los recorridos
    sólo corrían cuando alguien pulsaba el botón: un envío «a su mejor hora» no
    salía a ninguna hora. Ahora salen solos, cada uno con la identidad de quien
    lo programó o publicó (foto de sus permisos al hacerlo); lo que no la tiene
    no sale y dice por qué.

    Al arrancar SÍ: lo que venció con el servicio parado es lo primero que toca.
    Y primero el avance, para que lo que programe un paso salga en esta vuelta.
    """
    from crmcore.tareas import Tarea, por_tenant

    from services.marketing.envios import despachar_vencidos, tenants_con_envios_vencidos
    from services.marketing.recorridos import avanzar_solos, tenants_con_recorridos_pendientes

    return [
        Tarea(
            "marketing.avanzar_recorridos",
            _intervalo("recorridos_avanzar_cada_s"),
            por_tenant(tenants_con_recorridos_pendientes, avanzar_solos),
        ),
        Tarea(
            "marketing.despachar_envios",
            _intervalo("envios_despachar_cada_s"),
            por_tenant(tenants_con_envios_vencidos, despachar_vencidos),
        ),
    ]


async def _al_arrancar() -> None:
    global _relevo, _tarea_relevo
    import asyncio

    from crmcore.config import get_settings
    from crmcore.tareas import RelevoDeTareas

    if get_settings().tareas_fondo_enabled:
        _relevo = RelevoDeTareas(_tareas())
        _tarea_relevo = asyncio.create_task(_relevo.correr(), name="marketing-tareas")


async def _al_parar() -> None:
    if _relevo is not None:
        _relevo.parar()
    if _tarea_relevo is not None:
        _tarea_relevo.cancel()


app = crear_servicio(
    nombre="marketing",
    descripcion=(
        "Segmentos con condiciones anidadas y operadores temporales, dinámicos o "
        "congelados, con supresiones que se aplican siempre por encima; y "
        "puntuación de leads en dos ejes —encaje e interés— con decaimiento y "
        "umbrales que exigen los dos. Encima, los recorridos: el lienzo es la "
        "definición, las salidas se comprueban antes de cada paso y la "
        "supresión manda sobre lo que diga el recorrido."
    ),
    routers=[
        *ROUTERS,
        *ROUTERS_RECORRIDOS,
        *ROUTERS_CANALES,
        *ROUTERS_FONDOS,
        *ROUTERS_CONSENTIMIENTO,
        *ROUTERS_MOMENTO,
        *ROUTERS_CANALES_EXTERNOS,
        *ROUTERS_ENVIOS,
    ],
    # El perfil de marketing se alimenta por evento: este servicio no puede leer
    # el esquema de `party` ni el de `sales`, y calcular un segmento no puede
    # depender de que estén en pie. El patrón es ancho porque el propio
    # consumidor filtra por tipo conocido.
    consumidores=[("*", consumir, "marketing-perfiles")],
    al_arrancar=_al_arrancar,
    al_parar=_al_parar,
)
