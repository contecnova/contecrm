"""Registro de invalidadores de caché.

**Portado de `contecmind/app/core/cache_registry.py`.** Allí nació para romper
una dependencia circular: `runtime_settings.invalidate()` tenía que importar, ya
dentro de la función, a cada dueño de caché —y cada uno de ellos importaba
`runtime_settings` para leer su valor efectivo—. El resultado era un ciclo
tapado con `try: from … import …` en el cuerpo de la función.

Aquí resuelve además un agujero concreto de este producto: `purgar_tenant()`
vacía la caché **compartida**, pero no las cachés **en proceso** que cada módulo
mantiene por su cuenta —la de la jerarquía de ajustes es una—. Sin este
registro, dar de baja a un cliente dejaba a cada réplica sirviendo sus ajustes
desde memoria como si nada hubiera pasado.

El registro va en una sola dirección: quien tiene caché depende de este módulo,
que no depende de nadie. El ciclo desaparece.
"""

from __future__ import annotations

from threading import Lock
from typing import Callable

from crmcore.logging import get_logger

logger = get_logger(__name__)

# Recibe el tenant purgado, o `None` cuando se vacía todo. Quien no distinga por
# tenant simplemente lo vacía entero: es correcto, solo menos fino.
Invalidador = Callable[[str | None], None]

_invalidadores: dict[str, Invalidador] = {}
_cerrojo = Lock()


def registrar(nombre: str, invalidador: Invalidador) -> None:
    """Apunta un invalidador. Registrar dos veces el mismo nombre lo sustituye."""
    with _cerrojo:
        _invalidadores[nombre] = invalidador


def invalidar_todos(tenant_id: str | None = None) -> int:
    """Llama a todos los invalidadores. Devuelve cuántos se ejecutaron bien.

    Un invalidador que falle **no detiene a los demás**: si el segundo de cinco
    revienta, los tres siguientes seguirían sirviendo dato purgado, y eso es
    justo lo que esto viene a evitar. Se registra el fallo con su nombre, que es
    lo que hace falta para arreglarlo.
    """
    with _cerrojo:
        actuales = list(_invalidadores.items())

    bien = 0
    for nombre, fn in actuales:
        try:
            fn(tenant_id)
            bien += 1
        except Exception as exc:  # noqa: BLE001 — un fallo aquí no puede propagarse
            logger.error("cache.invalidador_fallido", invalidador=nombre, error=str(exc))
    return bien


def instantanea() -> dict[str, Invalidador]:
    """Copia del registro, para poder restaurarlo. Solo para pruebas."""
    with _cerrojo:
        return dict(_invalidadores)


def restaurar(guardado: dict[str, Invalidador]) -> None:
    """Devuelve el registro a un estado anterior. Solo para pruebas."""
    with _cerrojo:
        _invalidadores.clear()
        _invalidadores.update(guardado)


def limpiar_registro() -> None:
    """Vacía el registro. Solo para pruebas, y con cuidado.

    Los invalidadores se apuntan **al importar** su módulo, y un módulo ya
    importado no vuelve a ejecutarse: vaciar el registro en una prueba lo deja
    vacío para todas las que vengan detrás, y esas pasarían sin estar
    comprobando nada. Para una prueba aislada, `instantanea()` y `restaurar()`.
    """
    with _cerrojo:
        _invalidadores.clear()
