"""Objetivos de servicio y presupuesto de error (CRM-00.06.01.04).

Un SLA le dice al cliente qué se le promete. Un **SLO** le dice al equipo cuándo
parar de añadir cosas y arreglar las que hay. Sin él, la conversación «¿podemos
desplegar el viernes?» se decide por intuición y por quién habla más alto.

La pieza que lo hace útil es el **presupuesto de error**: si el objetivo es
99,9 % mensual, el presupuesto es el 0,1 % restante — unos 43 minutos. Mientras
quede presupuesto, se despliega; cuando se agota, se para y se arregla. Convierte
una discusión de opiniones en una cuenta.

Dos decisiones:

**Por servicio y por tier**, porque prometer lo mismo a todos obliga a prometer
lo del más exigente o a incumplir al que paga por ello. El tier sale del plan
contratado, igual que RPO y RTO.

**Se mide sobre lo que el cliente nota**, no sobre lo que es fácil de medir. La
disponibilidad de un proceso que nadie usa no es disponibilidad; lo que cuenta
son las peticiones servidas correctamente frente al total.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from crmcore.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Objetivo:
    """Lo que se compromete de un servicio en un tier."""

    servicio: str
    tier: str
    # Porcentaje de peticiones que deben salir bien, mensual.
    disponibilidad_pct: float
    # Percentil 95 de latencia, en milisegundos. El p95 y no la media: la media
    # la arregla un montón de respuestas rápidas mientras el 5 % de los usuarios
    # espera cuatro segundos, y son esos los que llaman.
    latencia_p95_ms: int


@dataclass
class Consumo:
    """Lo gastado del presupuesto en el periodo."""

    peticiones: int = 0
    fallidas: int = 0
    lentas: int = 0


_consumo: dict[tuple[str, str], Consumo] = {}


def anotar(servicio: str, tier: str, *, ok: bool, ms: float, objetivo: Objetivo) -> None:
    """Apunta una petición contra el presupuesto.

    Se cuenta **lenta** aparte de **fallida**: una respuesta que llega en cuatro
    segundos es un error para quien la espera aunque devuelva 200, y mezclarlas
    escondería el problema más común detrás del más raro.
    """
    consumo = _consumo.setdefault((servicio, tier), Consumo())
    consumo.peticiones += 1
    if not ok:
        consumo.fallidas += 1
    elif ms > objetivo.latencia_p95_ms:
        consumo.lentas += 1


def presupuesto(objetivo: Objetivo, *, dias_del_periodo: int = 30) -> dict[str, Any]:
    """Cuánto presupuesto de error queda, y qué significa.

    Se devuelve en **minutos equivalentes** además de en porcentaje: «te queda el
    37 % del presupuesto» no le dice nada a nadie, y «te quedan 16 minutos de
    caída este mes» se entiende a la primera.
    """
    consumo = _consumo.get((objetivo.servicio, objetivo.tier), Consumo())
    permitido_pct = 100.0 - objetivo.disponibilidad_pct
    minutos_del_periodo = dias_del_periodo * 24 * 60
    presupuesto_minutos = minutos_del_periodo * permitido_pct / 100

    if consumo.peticiones == 0:
        # Sin tráfico no hay medición, y decir «100 % disponible» sería mentir
        # con la verdad: un servicio que nadie usa no ha demostrado nada.
        return {
            "servicio": objetivo.servicio,
            "tier": objetivo.tier,
            "medible": False,
            "motivo": "No ha habido peticiones en el periodo",
            "presupuesto_minutos": round(presupuesto_minutos),
        }

    malas = consumo.fallidas + consumo.lentas
    consumido_pct = malas / consumo.peticiones * 100
    gastado = min(1.0, consumido_pct / permitido_pct) if permitido_pct else 1.0

    return {
        "servicio": objetivo.servicio,
        "tier": objetivo.tier,
        "medible": True,
        "objetivo_pct": objetivo.disponibilidad_pct,
        "real_pct": round(100 - consumido_pct, 3),
        "peticiones": consumo.peticiones,
        "fallidas": consumo.fallidas,
        # Las lentas se enseñan aparte: quien lee esto necesita saber si el
        # problema es que se cae o que va lento, porque se arreglan distinto.
        "lentas": consumo.lentas,
        "presupuesto_gastado_pct": round(gastado * 100, 1),
        "minutos_restantes": round(presupuesto_minutos * (1 - gastado)),
        "agotado": gastado >= 1.0,
        "que_significa": (
            "Presupuesto agotado: toca parar de añadir y arreglar lo que falla"
            if gastado >= 1.0
            else "Queda margen: se puede seguir desplegando"
        ),
    }


def ventana(dias: int = 30) -> tuple[datetime, datetime]:
    hasta = datetime.now(timezone.utc)
    return hasta - timedelta(days=dias), hasta


def reiniciar() -> None:
    _consumo.clear()
