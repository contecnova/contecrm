"""Tenants anómalos y throttling adaptativo (CRM-00.01.06.05).

El límite de tasa fijo protege del abuso y no protege de lo que de verdad tumba
un sistema multi-tenant: **un cliente que hace lo de siempre, pero diez veces
más**. Su importación nocturna se vuelve diurna, o alguien monta un bucle en su
integración, y el resto de clientes empieza a esperar sin que nadie haya pasado
de su límite.

Las decisiones:

**Se compara con lo que hace ese tenant, no con un número global.** Un cliente
grande hace mil peticiones por minuto y es normal; uno pequeño haciendo cien es
una anomalía. Un umbral único castiga al grande y deja pasar al pequeño.

**Sin historia no se frena.** Con cuatro minutos de observación cualquier pico es
una anomalía. Antes del mínimo se observa y se dice, pero no se actúa: frenar por
ruido es peor que no frenar, porque se frena a quien está trabajando.

**El freno es gradual y temporal.** Se ralentiza, no se corta: cortar a un
cliente porque su importación va rápida convierte un problema de reparto en una
incidencia. Y se suelta solo, porque un freno que hay que quitar a mano se queda
puesto.

**Y se dice al que frena que está frenado.** Un `429` sin explicación hace que la
integración reintente más fuerte, que es exactamente lo contrario de lo que hace
falta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.logging import get_logger

logger = get_logger(__name__)

# Cuántas ventanas hacen falta antes de poder decir que algo es anómalo. Con
# menos, lo que se detecta es que el tenant acaba de empezar a usar el sistema.
MINIMO_VENTANAS = 10

# Cuánto por encima de su propia media se considera anómalo. Tres veces es mucho
# y pasa: una importación, un informe pesado, una campaña. Por eso no se corta.
FACTOR_ANOMALIA = 3.0

# Cuánto se ralentiza y cuánto dura. Gradual y temporal: el freno que hay que
# quitar a mano se queda puesto para siempre.
ESCALONES = (0.75, 0.5, 0.25)
MINUTOS_FRENO = 5


@dataclass
class Observacion:
    """Lo que lleva hecho un tenant, por ventanas."""

    ventanas: list[int] = field(default_factory=list)
    frenado_hasta: datetime | None = None
    escalon: int = 0
    motivo: str = ""


_observado: dict[str, Observacion] = {}


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def anotar(tenant_id: UUID | str, peticiones: int) -> None:
    """Anota lo que ha hecho un tenant en la ventana que acaba de cerrarse."""
    clave = str(tenant_id)
    obs = _observado.setdefault(clave, Observacion())
    obs.ventanas.append(max(0, int(peticiones)))
    # Solo se guarda una hora de historia: comparar con lo de hace tres días
    # haría que un cambio real de uso pareciera una anomalía durante días.
    del obs.ventanas[:-60]


def evaluar(tenant_id: UUID | str) -> dict[str, Any]:
    """Si este tenant se está saliendo de lo suyo, y qué hacer.

    Devuelve siempre **por qué**: un freno sin explicación hace que la
    integración reintente más fuerte, que es lo contrario de lo que hace falta.
    """
    clave = str(tenant_id)
    obs = _observado.get(clave)
    if obs is None or len(obs.ventanas) < MINIMO_VENTANAS:
        observadas = len(obs.ventanas) if obs else 0
        return {
            "anomalo": False,
            "medible": False,
            "factor": None,
            "observadas": observadas,
            "porque": (
                f"Solo {observadas} ventanas observadas y hacen falta "
                f"{MINIMO_VENTANAS}. Antes de eso, cualquier pico es que el tenant "
                "acaba de empezar a usar el sistema, y frenar por ruido es frenar a "
                "quien está trabajando."
            ),
        }

    ultima = obs.ventanas[-1]
    previas = obs.ventanas[:-1]
    media = sum(previas) / len(previas) if previas else 0
    if media <= 0:
        return {
            "anomalo": False,
            "medible": True,
            "factor": None,
            "porque": "No hay actividad previa con la que comparar.",
        }

    factor = ultima / media
    anomalo = factor >= FACTOR_ANOMALIA
    return {
        "anomalo": anomalo,
        "medible": True,
        "factor": round(factor, 2),
        "ultima_ventana": ultima,
        # Su propia media, no un número global: un cliente grande hace mil
        # peticiones por minuto y es normal; uno pequeño haciendo cien no lo es.
        "su_media": round(media, 1),
        "porque": (
            f"Está haciendo {factor:.1f} veces lo que hace habitualmente "
            f"({ultima} frente a {media:.0f} de media)."
            if anomalo
            else f"Dentro de lo suyo ({factor:.1f}× su media)."
        ),
    }


def frenar(tenant_id: UUID | str, *, motivo: str, ahora: datetime | None = None) -> dict[str, Any]:
    """Ralentiza a un tenant un rato, subiendo un escalón cada vez.

    Se ralentiza y **no se corta**: cortar a un cliente porque su importación va
    rápida convierte un problema de reparto en una incidencia. Y si vuelve a
    pasar mientras sigue frenado, se aprieta un escalón más en vez de cortar.
    """
    momento = ahora or _ahora()
    obs = _observado.setdefault(str(tenant_id), Observacion())
    sigue_frenado = obs.frenado_hasta is not None and obs.frenado_hasta > momento
    obs.escalon = min(obs.escalon + 1, len(ESCALONES)) if sigue_frenado else 1
    obs.frenado_hasta = momento + timedelta(minutes=MINUTOS_FRENO)
    obs.motivo = motivo
    factor = ESCALONES[obs.escalon - 1]
    logger.warning(
        "gateway.tenant_frenado", tenant=str(tenant_id), escalon=obs.escalon, factor=factor
    )
    return {
        "tenant_id": str(tenant_id),
        "factor_de_cuota": factor,
        "escalon": obs.escalon,
        "hasta": obs.frenado_hasta.isoformat(),
        "motivo": motivo,
        # Lo que se le dice a quien llama. Sin esto, la integración reintenta más
        # fuerte y empeora justo lo que se estaba intentando arreglar.
        "mensaje_para_el_cliente": (
            f"Estás haciendo muchas más peticiones de lo habitual. Tu cuota está "
            f"temporalmente al {int(factor * 100)} % durante {MINUTOS_FRENO} minutos. "
            "No hace falta hacer nada: se restablece solo. Reintentar más rápido lo "
            "empeora."
        ),
    }


def estado(tenant_id: UUID | str, *, ahora: datetime | None = None) -> dict[str, Any]:
    """Si este tenant está frenado ahora mismo y cuánto le queda.

    El freno **se suelta solo**: uno que hay que quitar a mano se queda puesto,
    y entonces el cliente lleva semanas a un cuarto de cuota sin que nadie sepa
    por qué.
    """
    momento = ahora or _ahora()
    obs = _observado.get(str(tenant_id))
    if obs is None or obs.frenado_hasta is None or obs.frenado_hasta <= momento:
        return {"frenado": False, "factor_de_cuota": 1.0}
    return {
        "frenado": True,
        "factor_de_cuota": ESCALONES[max(0, obs.escalon - 1)],
        "hasta": obs.frenado_hasta.isoformat(),
        "quedan_segundos": int((obs.frenado_hasta - momento).total_seconds()),
        "motivo": obs.motivo,
    }


def reiniciar() -> None:
    """Vacía lo observado. Para las pruebas y para un reinicio en caliente."""
    _observado.clear()
