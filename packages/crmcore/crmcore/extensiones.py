"""Puntos de extensión del dominio (CRM-00.04.02.02, CRM-00.04.02.03).

Un CRM al que no se le puede enganchar nada obliga a modificarlo para cada
cliente, y a los dos años hay cinco versiones del producto. Dos formas de
engancharse, y la diferencia entre ellas no es de estilo:

**Síncrono (`antes_de` / `despues_de`)**: corre dentro de la transacción del
cambio. Sirve para lo que tiene que decidir —rechazar un guardado, completar un
campo— y por eso mismo es peligroso: lo que falle aquí tumba la operación del
usuario. Va con tope de tiempo y con la regla clara de que un hook que necesita
llamar a un tercero **no es síncrono**.

**Asíncrono (`al_ocurrir`)**: corre fuera, sobre el evento ya publicado. Sirve
para todo lo demás, que es casi todo. No puede rechazar nada porque el cambio ya
pasó, y a cambio no puede romperlo.

La regla, dicha una vez: **si puede esperar, es asíncrono**. La tentación de
hacerlo todo síncrono —«así lo tengo hecho al volver»— es lo que convierte un
guardado de 80 ms en uno de dos segundos que a veces falla por algo que no tiene
nada que ver con guardar.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable

from crmcore.logging import get_logger

logger = get_logger(__name__)

Hook = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class Enganche:
    nombre: str
    objeto: str
    momento: str  # antes | despues
    fn: Hook
    # Un hook lento bloquea el guardado del usuario. El tope no es una
    # optimización: es lo que impide que una extensión mal escrita convierta el
    # CRM en algo que "va lento a veces".
    max_ms: int = 200


_ganchos: dict[tuple[str, str], list[Enganche]] = defaultdict(list)


def registrar_hook(nombre: str, objeto: str, momento: str, fn: Hook, *, max_ms: int = 200) -> None:
    """Engancha una extensión síncrona a un objeto.

    `momento` es `antes` o `despues`. Antes puede **rechazar** lanzando; después
    ya no, porque el cambio está hecho y lanzar ahí solo consigue que el usuario
    vea un error sobre algo que sí se guardó — el peor mensaje posible.
    """
    if momento not in ("antes", "despues"):
        raise ValueError(f"El momento es «antes» o «despues», no «{momento}»")
    _ganchos[(objeto, momento)].append(
        Enganche(nombre=nombre, objeto=objeto, momento=momento, fn=fn, max_ms=max_ms)
    )
    logger.info("extension.registrada", nombre=nombre, objeto=objeto, momento=momento)


def limpiar_hooks() -> None:
    """Vacía el registro. Para las pruebas, que si no se contaminan entre sí."""
    _ganchos.clear()


def antes_de(objeto: str, **contexto: Any) -> None:
    """Corre los hooks previos. Lo que lancen **aborta la operación**.

    Se propaga a propósito: es lo único que distingue un hook `antes` de uno
    `despues`. Si tragara el error, «rechazar un guardado» dejaría de ser
    posible y este punto de extensión no serviría para nada.
    """
    for enganche in _ganchos.get((objeto, "antes"), []):
        _correr(enganche, contexto, propagar=True)


def despues_de(objeto: str, **contexto: Any) -> None:
    """Corre los hooks posteriores. Lo que lancen **no** aborta nada.

    El cambio ya está hecho: propagar aquí haría que el usuario viera un error
    sobre algo que sí se guardó, y la próxima vez lo volvería a intentar
    duplicándolo.
    """
    for enganche in _ganchos.get((objeto, "despues"), []):
        _correr(enganche, contexto, propagar=False)


def _correr(enganche: Enganche, contexto: dict[str, Any], *, propagar: bool) -> None:
    inicio = time.perf_counter()
    try:
        enganche.fn(**contexto)
    except Exception as exc:  # noqa: BLE001 — según el momento, se propaga o no
        logger.error(
            "extension.fallida",
            nombre=enganche.nombre,
            objeto=enganche.objeto,
            momento=enganche.momento,
            error=str(exc)[:300],
        )
        if propagar:
            raise
    finally:
        ms = (time.perf_counter() - inicio) * 1000
        if ms > enganche.max_ms:
            # Se avisa siempre, aunque no se corte: cortar a mitad dejaría la
            # operación en un estado que la extensión no esperaba. Lo que hace
            # falta es que se sepa quién está frenando el guardado.
            logger.warning(
                "extension.lenta",
                nombre=enganche.nombre,
                objeto=enganche.objeto,
                ms=round(ms),
                tope_ms=enganche.max_ms,
            )


# ── Extensiones asíncronas (CRM-00.04.02.03) ──────────────────────────────


@dataclass(frozen=True, slots=True)
class Suscripcion:
    nombre: str
    patron: str
    fn: Hook


_suscripciones: list[Suscripcion] = []


def al_ocurrir(nombre: str, patron: str, fn: Hook) -> None:
    """Engancha una extensión al bus, fuera de la transacción.

    `patron` es un tipo de evento o un prefijo con `*`. Corre después de que el
    cambio esté confirmado y publicado, así que **no puede rechazarlo** — y por
    eso mismo no puede romperlo, que es la razón de que casi todo deba ir aquí.
    """
    _suscripciones.append(Suscripcion(nombre=nombre, patron=patron, fn=fn))
    logger.info("extension.suscrita", nombre=nombre, patron=patron)


def suscripciones_para(tipo_evento: str) -> list[Suscripcion]:
    """Las extensiones que escuchan este evento."""
    return [s for s in _suscripciones if _casa(s.patron, tipo_evento)]


def _casa(patron: str, tipo: str) -> bool:
    if patron == tipo or patron == "*":
        return True
    # `cuenta.*` casa con `cuenta.creada`, y no con `cuentas.creada`: el punto
    # es parte del prefijo a propósito, porque sin él `cuenta.*` casaría también
    # con `cuenta_borrador.creada` y una extensión escucharía objetos que no son
    # el suyo.
    return patron.endswith(".*") and tipo.startswith(patron[:-1])


def consumidor_de_extensiones() -> Callable[[Any], Any]:
    """El consumidor que reparte los eventos entre las extensiones suscritas.

    Una sola suscripción al bus para todas, y no una por extensión: cada
    suscripción es un consumidor durable en NATS, y un tenant con cincuenta
    extensiones tendría cincuenta consumidores compitiendo por el mismo flujo.
    """

    async def repartir(mensaje: Any) -> None:
        tipo = ""
        if isinstance(mensaje, dict):
            tipo = str(mensaje.get("tipo") or mensaje.get("type") or "")
        else:
            tipo = str(getattr(mensaje, "tipo", "") or "")
        for suscripcion in suscripciones_para(tipo):
            try:
                resultado = suscripcion.fn(mensaje)
                if hasattr(resultado, "__await__"):
                    await resultado
            except Exception as exc:  # noqa: BLE001 — una extensión rota no para el bus
                # No se propaga: si lo hiciera, una extensión mal escrita
                # bloquearía la cola para todas las demás y el sistema se
                # pararía entero por algo que es de un tenant.
                logger.error(
                    "extension.asincrona_fallida",
                    nombre=suscripcion.nombre,
                    evento=tipo,
                    error=str(exc)[:300],
                )

    return repartir
