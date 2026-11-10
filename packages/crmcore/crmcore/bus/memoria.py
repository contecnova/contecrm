"""Bus en proceso. Solo para pruebas.

No hay sockets, ni servidor, ni nada que limpiar: productor y consumidor viven
en el mismo proceso. Una prueba puede publicar y afirmar sobre lo recibido en el
mismo `await`.

Lo que **no** tiene, y por eso no vale para producción:

  * Sin persistencia: lo publicado mientras un consumidor no está, se pierde.
  * Sin reparto entre procesos: solo existe este.
  * Sin reintentos: si el manejador lanza, el evento se anota y se descarta.

El registro de suscriptores es de módulo, no de instancia, para que dos buses
creados por dos servicios distintos dentro de la misma prueba se vean entre sí —
que es justo lo que hace falta para probar una coreografía completa sin levantar
infraestructura.
"""

from __future__ import annotations

import re
from collections import defaultdict

from crmcore.bus.base import Bus, Manejador, Suscripcion
from crmcore.events.envelope import Evento, subject_patron
from crmcore.logging import get_logger

logger = get_logger(__name__)

_suscriptores: dict[str, list[tuple[str, Manejador]]] = defaultdict(list)
# Todo lo publicado, para que una prueba pueda afirmar sobre ello sin suscribirse.
_publicados: list[Evento] = []


class BusEnMemoria(Bus):
    backend = "memoria"

    async def publicar(self, evento: Evento) -> None:
        subject = evento.subject_bus("mem")
        _publicados.append(evento)
        entregas = [
            manejador
            for patron, suscritos in _suscriptores.items()
            if _coincide(subject, patron)
            for _grupo, manejador in suscritos
        ]
        if not entregas:
            return
        # Se entrega en serie y se esperan todos: en una prueba interesa que al
        # volver de `publicar` ya haya pasado todo, para no tener que dormir.
        for manejador in entregas:
            try:
                from crmcore.obs.metrics import observar_evento_consumido

                try:
                    await manejador(evento)
                except Exception:
                    # Se cuenta el fallo ANTES de propagarlo: un consumidor que revienta
                    # sin dejar métrica es un flujo que, visto desde el panel, dejó de
                    # llegar sin motivo.
                    observar_evento_consumido(evento.tipo, "error")
                    raise
                observar_evento_consumido(evento.tipo, "ok")
            except Exception as exc:  # noqa: BLE001 — en pruebas, anotar y seguir
                logger.warning(
                    "bus_memoria.manejador_fallido",
                    tipo=evento.type,
                    error=str(exc)[:200],
                )

    async def suscribir(
        self,
        patron: str,
        manejador: Manejador,
        *,
        grupo: str,
        durable: bool = True,
    ) -> Suscripcion:
        # Se guarda el patrón EXPANDIDO, con el segmento del tenant, igual que
        # hace el bus de NATS. Guardarlo crudo era lo que hacía que este backend
        # tampoco entregara nada, y encima con la apariencia contraria: como
        # ninguna prueba cruzaba publicar con recibir, parecía que funcionaba.
        expandido = subject_patron("mem", patron)
        _suscriptores[expandido].append((grupo, manejador))

        async def _cancelar() -> None:
            _suscriptores[expandido] = [
                (g, m) for g, m in _suscriptores[expandido] if m is not manejador
            ]

        return Suscripcion(patron=patron, grupo=grupo, cancelar=_cancelar)

    async def ping(self) -> bool:
        return True

    async def cerrar(self) -> None:
        return None


def _coincide(subject: str, patron: str) -> bool:
    """Compara con los comodines de NATS: `*` un segmento, `>` el resto.

    El backend de memoria acepta exactamente los mismos patrones que el de
    producción, con su mismo significado: si un patrón funciona en la prueba,
    funciona en NATS.
    """
    # Con las reglas EXACTAS de NATS y no con `fnmatch`: allí `*` cruza puntos,
    # así que `contecrm.*.*` casaba en memoria con `contecrm.<t>.account.created`
    # y en NATS no. Eso escondió el 10-11-2026 que los consumidores de «todo»
    # no recibían nada en producción.
    trozos = []
    for parte in patron.split("."):
        if parte == "*":
            trozos.append(r"[^.]+")
        elif parte == ">":
            trozos.append(r".+")
        else:
            trozos.append(re.escape(parte))
    return re.fullmatch(r"\.".join(trozos), subject) is not None


# ── Utilidades de prueba ──────────────────────────────────────────────────


def publicados(tipo: str | None = None) -> list[Evento]:
    """Eventos publicados hasta ahora, opcionalmente filtrados por tipo."""
    return [e for e in _publicados if tipo is None or e.type == tipo]


def limpiar() -> None:
    """Borra suscriptores y publicados. Lo llama el fixture entre pruebas."""
    _suscriptores.clear()
    _publicados.clear()
