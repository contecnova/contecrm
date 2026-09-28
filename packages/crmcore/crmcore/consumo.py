"""Cuánta cuota lleva gastada un tenant **en este módulo**.

Lo publica cada servicio y lo suma el gateway, igual que la página de estado. No
hay un contador central que mantener entre trece esquemas: cada uno cuenta lo
suyo, que es lo que permite cuadrar el número con lo que el cliente ve.

**Y el que no contesta no es un cero.** Esa regla vive en el gateway, que es
quien compone: un cero es una afirmación falsa —«no has gastado nada»— y «no se
ha podido leer» es verdad. Un cliente que ve ceros llega al tope sin haber visto
subir el número nunca, y eso convierte la cuota en una encerrona.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from crmcore.logging import get_logger

logger = get_logger(__name__)

# Qué mide este proceso. Cada entrada devuelve `(consumido, clave_de_ajuste)`.
_MEDIDORES: dict[str, Callable[[Any, UUID], tuple[int, str]]] = {}


def registrar_medidor(nombre: str, fn: Callable[[Any, UUID], tuple[int, str]]) -> None:
    """Declara que este módulo sabe medir esta métrica.

    Registrar dos veces la misma es inocuo: en un proceso que importe varios
    servicios —las pruebas— pasaría, y fallar ahí no protegería de nada.
    """
    _MEDIDORES[nombre] = fn


def medidores_registrados() -> list[str]:
    return sorted(_MEDIDORES)


def limpiar_medidores() -> None:
    """Para las pruebas: el registro es del proceso y vive entre casos."""
    _MEDIDORES.clear()


def medido_aqui(db: Any, tenant_id: UUID) -> list[dict[str, Any]]:
    """Lo que este módulo mide para este tenant, con su tope al lado.

    **El tope va dentro**: un consumo sin su límite no dice si son muchos o
    pocos, y obliga a quien lo lee a buscarlo en otro sitio.

    Si un medidor revienta se dice **en su fila** y no se tumba el resto: una
    métrica rota no puede dejar sin panel a las otras cinco.
    """
    from crmcore.cuotas import tope

    salida: list[dict[str, Any]] = []
    for nombre, medir in sorted(_MEDIDORES.items()):
        try:
            consumido, clave = medir(db, tenant_id)
        except Exception as exc:  # noqa: BLE001 — una métrica rota no tumba el panel
            logger.warning("consumo.medidor_roto", metrica=nombre, error=str(exc)[:200])
            salida.append(
                {
                    "metrica": nombre,
                    "legible": False,
                    "porque": "no se ha podido medir en este módulo",
                }
            )
            continue
        limite = tope(db, tenant_id, clave)
        salida.append(
            {
                "metrica": nombre,
                "legible": True,
                "consumido": consumido,
                "limite": limite,
                "sin_limite": limite <= 0,
                "pct": round(consumido / limite * 100, 1) if limite > 0 else None,
                "ajuste": clave,
            }
        )
    return salida
