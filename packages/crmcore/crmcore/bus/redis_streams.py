"""Bus sobre Redis Streams. Alternativa donde ya hay Redis y no se quiere NATS.

Da lo esencial: persistencia, grupos de consumidores con reparto y reentrega de
lo no confirmado. Dos diferencias honestas frente a JetStream:

  * El comodín de subject no existe en Redis: un stream es una clave. Aquí se
    usa **un stream por tipo de evento**, y una suscripción con comodín se
    resuelve leyendo de varios streams. Funciona, pero un patrón muy abierto
    (`>`) obliga a conocer de antemano los tipos, así que el catálogo de tipos
    (`crmcore.events.catalogo`) es obligatorio con este backend.
  * La reentrega de mensajes que quedaron colgados de un consumidor muerto hay
    que reclamarla explícitamente (`XAUTOCLAIM`); aquí lo hace el propio bucle.
"""

from __future__ import annotations

import asyncio
from typing import Any

from crmcore.bus.base import Bus, Manejador, Suscripcion
from crmcore.events.envelope import Evento
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Cada cuánto se reclaman los mensajes que quedaron sin confirmar en un
# consumidor que murió. Configurable vía Settings en el futuro si hiciera falta
# afinarlo por despliegue; de momento el valor es el mismo para todos porque el
# criterio no depende del cliente sino del modo de fallo.
RECLAMO_CADA_S = 30.0
# Tiempo que un mensaje puede estar tomado sin confirmar antes de considerarse
# abandonado. Debe superar con holgura lo que tarda el manejador más lento.
RECLAMO_INACTIVO_MS = 60_000


class BusRedis(Bus):
    backend = "redis"

    def __init__(self, url: str, *, prefijo: str, servicio: str) -> None:
        self._url = url
        self._prefijo = prefijo
        self._servicio = servicio or "servicio"
        self._r: Any = None
        self._tareas: list[asyncio.Task[None]] = []

    async def conectar(self) -> None:
        import redis.asyncio as redis

        self._r = redis.from_url(self._url, decode_responses=True)
        await self._r.ping()
        logger.info("bus_redis.conectado", url=self._url)

    def _clave(self, tipo: str) -> str:
        return f"{self._prefijo}:ev:{tipo}"

    async def publicar(self, evento: Evento) -> None:
        # `maxlen` aproximado acota el crecimiento sin el coste de recortar
        # exacto en cada escritura. El histórico fiable está en la base.
        await self._r.xadd(
            self._clave(evento.type),
            {"evento": evento.a_json(), "tenant": str(evento.tenant_id)},
            maxlen=100_000,
            approximate=True,
        )

    async def suscribir(
        self,
        patron: str,
        manejador: Manejador,
        *,
        grupo: str,
        durable: bool = True,
    ) -> Suscripcion:
        from crmcore.events.catalogo import tipos_que_encajan

        tipos = tipos_que_encajan(patron)
        if not tipos:
            logger.warning("bus_redis.patron_sin_tipos", patron=patron)

        claves = [self._clave(t) for t in tipos]
        for clave in claves:
            try:
                # `mkstream=True` crea el stream vacío: sin esto, suscribirse
                # antes de que exista el primer evento falla.
                await self._r.xgroup_create(clave, grupo, id="0", mkstream=True)
            except Exception:  # noqa: BLE001 — BUSYGROUP: ya existía
                pass

        detener = asyncio.Event()
        tarea = asyncio.create_task(
            self._bucle(claves, grupo, manejador, detener),
            name=f"redis-bus-{grupo}",
        )
        self._tareas.append(tarea)

        async def _cancelar() -> None:
            detener.set()
            tarea.cancel()

        return Suscripcion(patron=patron, grupo=grupo, cancelar=_cancelar)

    async def _bucle(
        self,
        claves: list[str],
        grupo: str,
        manejador: Manejador,
        detener: asyncio.Event,
    ) -> None:
        consumidor = f"{self._servicio}-{id(self)}"
        proximo_reclamo = 0.0
        while not detener.is_set():
            try:
                respuesta = await self._r.xreadgroup(
                    grupo,
                    consumidor,
                    {c: ">" for c in claves},
                    count=10,
                    block=1000,
                )
                for clave, mensajes in respuesta or []:
                    for msg_id, campos in mensajes:
                        await self._procesar(clave, grupo, msg_id, campos, manejador)

                ahora = asyncio.get_event_loop().time()
                if ahora >= proximo_reclamo:
                    proximo_reclamo = ahora + RECLAMO_CADA_S
                    await self._reclamar_abandonados(claves, grupo, consumidor, manejador)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — Redis caído: se reintenta, no se muere
                logger.warning("bus_redis.bucle_error", error=str(exc)[:200])
                await asyncio.sleep(1.0)

    async def _procesar(
        self,
        clave: str,
        grupo: str,
        msg_id: str,
        campos: dict[str, str],
        manejador: Manejador,
    ) -> None:
        try:
            evento = Evento.desde_json(campos["evento"])
        except Exception as exc:  # noqa: BLE001 — ilegible: confirmar para no bloquear el grupo
            await self._r.xack(clave, grupo, msg_id)
            logger.error("bus_redis.mensaje_ilegible", error=str(exc)[:200])
            return
        try:
            await manejador(evento)
            await self._r.xack(clave, grupo, msg_id)
        except Exception as exc:  # noqa: BLE001 — sin ack: se reclamará y reintentará
            logger.warning(
                "bus_redis.manejador_fallido", tipo=evento.type, error=str(exc)[:200]
            )

    async def _reclamar_abandonados(
        self,
        claves: list[str],
        grupo: str,
        consumidor: str,
        manejador: Manejador,
    ) -> None:
        """Recupera mensajes tomados por un consumidor que ya no está.

        Sin esto, lo que estaba procesando una réplica al morir se queda
        pendiente para siempre: ni se procesa ni se pierde, que es el fallo más
        difícil de ver porque no aparece en ningún contador de errores.
        """
        for clave in claves:
            try:
                _cursor, mensajes, _ = await self._r.xautoclaim(
                    clave, grupo, consumidor, min_idle_time=RECLAMO_INACTIVO_MS, count=10
                )
                for msg_id, campos in mensajes or []:
                    await self._procesar(clave, grupo, msg_id, campos, manejador)
            except Exception as exc:  # noqa: BLE001 — reclamar es best-effort
                logger.debug("bus_redis.reclamo_fallido", error=str(exc)[:160])

    async def ping(self) -> bool:
        try:
            return bool(await self._r.ping())
        except Exception:  # noqa: BLE001 — el readiness nunca debe lanzar
            return False

    async def cerrar(self) -> None:
        for t in self._tareas:
            t.cancel()
        if self._r:
            await self._r.aclose()
