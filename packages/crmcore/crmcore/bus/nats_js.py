"""Bus sobre NATS JetStream. Es el backend de producción.

JetStream aporta lo que el catálogo pide y un pub/sub simple no da:

  * **Persistencia y reentrega** (CRM-00.02.02.05): lo publicado mientras un
    consumidor estaba caído sigue ahí cuando vuelve.
  * **Consumidores durables**: cada servicio recuerda por dónde iba, y varias
    réplicas del mismo servicio se reparten el trabajo en vez de duplicarlo.
  * **Replay desde un punto en el tiempo** (CRM-00.02.02.09): reprocesar una
    semana de eventos es crear un consumidor con `deliver_policy=by_start_time`,
    no un script que relea la base.
  * **Orden por clave de agregado** (CRM-00.02.02.08): dentro de un mismo
    subject el orden se respeta, y como el subject lleva tenant y tipo, los
    eventos de una misma entidad llegan en orden.

El flujo se crea si no existe, con un subject por tenant
(`contecrm.<tenant>.<tipo>`), que es lo que permite aislar el consumo por tenant
y evitar que una avalancha de uno bloquee a los demás (CRM-00.01.01.10).
"""

from __future__ import annotations

from typing import Any

from crmcore.bus.base import Bus, Manejador, Suscripcion
from crmcore.events.envelope import Evento, subject_patron
from crmcore.logging import get_logger

logger = get_logger(__name__)


class BusNats(Bus):
    backend = "nats"

    def __init__(self, url: str, *, prefijo: str, servicio: str) -> None:
        self._url = url
        self._prefijo = prefijo
        self._servicio = servicio or "servicio"
        self._nc: Any = None
        self._js: Any = None

    async def conectar(self) -> None:
        import nats

        # Reconexión indefinida a propósito: un bus que se rinde tras N intentos
        # deja el servicio vivo pero sordo, que es la peor combinación — parece
        # sano en el healthcheck y no procesa nada.
        self._nc = await nats.connect(
            servers=[self._url],
            name=f"contecrm-{self._servicio}",
            max_reconnect_attempts=-1,
            reconnect_time_wait=2,
            error_cb=self._al_error,
            disconnected_cb=self._al_desconectar,
            reconnected_cb=self._al_reconectar,
        )
        self._js = self._nc.jetstream()
        await self._asegurar_flujo()
        logger.info("bus_nats.conectado", url=self._url, servicio=self._servicio)

    async def _asegurar_flujo(self) -> None:
        """Crea el flujo si no existe. Idempotente."""
        from nats.js.api import RetentionPolicy, StorageType, StreamConfig

        nombre = self._prefijo.upper()
        config = StreamConfig(
            name=nombre,
            subjects=[f"{self._prefijo}.>"],
            # `limits` y no `workqueue`: varios servicios distintos consumen el
            # mismo evento (auditoría, automatizaciones, webhooks). Con
            # `workqueue` el primero que lo coge se lo lleva y los demás no lo
            # ven nunca.
            retention=RetentionPolicy.LIMITS,
            storage=StorageType.FILE,
            # 30 días de retención: cubre de sobra una reentrega tras una caída
            # larga y deja margen para un replay de incidencia. El histórico de
            # verdad está en la base, no aquí.
            max_age=30 * 24 * 3600,
            # Deduplicación en el propio flujo, además de la del consumidor: si
            # el relevo del outbox publica dos veces el mismo evento en un
            # intervalo corto, JetStream lo descarta por `Nats-Msg-Id`.
            duplicate_window=120,
        )
        try:
            await self._js.add_stream(config)
        except Exception as exc:  # noqa: BLE001 — casi siempre "ya existe"
            try:
                await self._js.update_stream(config)
            except Exception:  # noqa: BLE001 — sin permiso para tocarlo: seguimos
                logger.debug("bus_nats.flujo_existente", detalle=str(exc)[:160])

    async def publicar(self, evento: Evento) -> None:
        subject = evento.subject_bus(self._prefijo)
        await self._js.publish(
            subject,
            evento.a_json().encode(),
            # `Nats-Msg-Id` activa la deduplicación del servidor dentro de la
            # ventana configurada. Es la primera de las dos redes contra el
            # doble procesamiento; la segunda es el inbox del consumidor.
            headers={"Nats-Msg-Id": evento.dedup_key},
        )

    async def suscribir(
        self,
        patron: str,
        manejador: Manejador,
        *,
        grupo: str,
        durable: bool = True,
    ) -> Suscripcion:
        # Con el segmento del tenant. Ver `subject_patron`: sin él no casaba
        # ningún subject y el bus no entregaba nada.
        subject = subject_patron(self._prefijo, patron)

        async def _al_mensaje(msg: Any) -> None:
            try:
                evento = Evento.desde_json(msg.data.decode())
            except Exception as exc:  # noqa: BLE001 — un mensaje ilegible no se puede reintentar
                # `term` y no `nak`: reintentar un JSON corrupto lo repetiría
                # para siempre y acabaría bloqueando el consumidor.
                await msg.term()
                logger.error("bus_nats.mensaje_ilegible", error=str(exc)[:200])
                return
            try:
                await manejador(evento)
                await msg.ack()
            except Exception as exc:  # noqa: BLE001 — fallo del manejador: se reintenta
                await msg.nak()
                logger.warning(
                    "bus_nats.manejador_fallido",
                    tipo=evento.type,
                    error=str(exc)[:200],
                )

        # Un consumidor DURABLE conserva el filtro con el que nació, y JetStream
        # no lo cambia al volver a suscribirse: se queda escuchando lo que ya no
        # se publica, sin error y sin un solo mensaje. Es lo que pasó al añadir
        # el segmento del tenant al subject — el código quedó correcto y los
        # consumidores siguieron con el filtro viejo, así que el arreglo no se
        # notó hasta borrarlos a mano.
        #
        # Así que se comprueba y, si no coincide, se rehace. Perder la posición
        # de un consumidor cuyo filtro ha cambiado no es una pérdida: lo que
        # tenía pendiente era de otro subject.
        if durable:
            await self._rehacer_si_cambio_el_filtro(grupo, subject)

        sub = await self._js.subscribe(
            subject,
            # El durable lleva el nombre del grupo, no el de la réplica: así N
            # réplicas comparten posición y se reparten, en vez de procesar cada
            # una todo.
            durable=grupo if durable else None,
            queue=grupo,
            cb=_al_mensaje,
            manual_ack=True,
        )

        async def _cancelar() -> None:
            await sub.unsubscribe()

        logger.info("bus_nats.suscrito", subject=subject, grupo=grupo)
        return Suscripcion(patron=patron, grupo=grupo, cancelar=_cancelar)

    async def _rehacer_si_cambio_el_filtro(self, durable: str, subject: str) -> None:
        """Borra el consumidor durable si escucha algo distinto de lo que toca."""
        try:
            info = await self._js.consumer_info(self._prefijo.upper(), durable)
        except Exception:  # noqa: BLE001 — no existe todavía: se creará al suscribir
            return
        actual = getattr(info.config, "filter_subject", "") or ""
        if actual == subject:
            return
        logger.warning(
            "bus_nats.consumidor_rehecho",
            durable=durable,
            filtro_viejo=actual,
            filtro_nuevo=subject,
        )
        try:
            await self._js.delete_consumer(self._prefijo.upper(), durable)
        except Exception as exc:  # noqa: BLE001 — si no se puede, se dice y se sigue
            logger.error("bus_nats.consumidor_no_rehecho", durable=durable, error=str(exc)[:200])

    async def ping(self) -> bool:
        try:
            return bool(self._nc and self._nc.is_connected)
        except Exception:  # noqa: BLE001 — el readiness nunca debe lanzar
            return False

    async def cerrar(self) -> None:
        if self._nc:
            # `drain` y no `close`: termina de procesar lo que ya se recibió
            # antes de cortar. Cerrar en seco deja mensajes a medias que se
            # reentregan y se procesan dos veces sin necesidad.
            await self._nc.drain()

    # ── Callbacks de conexión ────────────────────────────────────────────

    async def _al_error(self, exc: Exception) -> None:
        logger.warning("bus_nats.error", error=str(exc)[:200])

    async def _al_desconectar(self) -> None:
        logger.warning("bus_nats.desconectado", url=self._url)

    async def _al_reconectar(self) -> None:
        logger.info("bus_nats.reconectado", url=self._url)
