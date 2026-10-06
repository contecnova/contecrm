"""Interfaz del bus de eventos, con tres implementaciones intercambiables.

El código de negocio publica contra esta interfaz y nunca sabe qué hay debajo.
Eso no es purismo: es lo que permite que la misma prueba corra en memoria en
milisegundos y en NATS cuando se quiere comprobar el comportamiento real, sin
tocar ni una línea del servicio.

    nats     JetStream. Persistencia, consumidores durables, reparto entre
             réplicas y replay desde un punto en el tiempo. Es el de producción.
    redis    Redis Streams con grupos de consumidores. Sirve donde ya hay Redis
             y no se quiere operar una pieza más.
    memoria  En proceso. Solo pruebas.

Y una cosa que **no** hace ninguno de los tres: garantizar que el evento se
publique si el proceso muere. Eso lo da el outbox, que es otra pieza
(`crmcore.bus.outbox`). El bus transporta; el outbox garantiza.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from crmcore.events.envelope import Evento

# Un manejador recibe el evento y devuelve una corrutina. Si lanza, el bus
# reintenta según su política; si vuelve sin lanzar, se da por procesado.
Manejador = Callable[[Evento], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Suscripcion:
    """Suscripción viva, con lo justo para poder cancelarla."""

    patron: str
    grupo: str
    cancelar: Callable[[], Awaitable[None]]


class Bus(ABC):
    """Contrato común."""

    backend: str = "desconocido"

    @abstractmethod
    async def publicar(self, evento: Evento) -> None:
        """Publica un evento. Puede lanzar: el llamante (el relevo del outbox)
        decide si reintenta."""

    @abstractmethod
    async def suscribir(
        self,
        patron: str,
        manejador: Manejador,
        *,
        grupo: str,
        durable: bool = True,
    ) -> Suscripcion:
        """Suscribe un manejador a un patrón de subjects.

        `grupo` es el grupo de consumo: varias réplicas del mismo servicio
        comparten grupo y se reparten los mensajes; dos servicios distintos usan
        grupos distintos y cada uno recibe todos. Sin grupos, tres réplicas
        procesarían tres veces el mismo evento.

        `durable` pide que el consumidor recuerde por dónde iba, para no perder
        lo publicado mientras estuvo caído. En memoria se ignora (no hay dónde
        recordarlo) y por eso ese backend es solo para pruebas.
        """

    @abstractmethod
    async def ping(self) -> bool:
        """Si el transporte responde. Lo usa el readiness del servicio."""

    @abstractmethod
    async def cerrar(self) -> None:
        """Cierra conexiones. Se llama al apagar el servicio."""


async def crear_bus(nombre_servicio: str = "") -> Bus:
    """Construye el bus que diga la configuración.

    Import perezoso de cada backend a propósito: así un despliegue con Redis no
    necesita tener instalado el cliente de NATS ni al revés, y un fallo de
    importación de uno no impide arrancar con el otro.
    """
    from crmcore.config import get_settings

    s = get_settings()
    nombre_servicio = nombre_servicio or s.service_name

    if s.bus_backend == "memoria":
        from crmcore.bus.memoria import BusEnMemoria

        return BusEnMemoria()
    if s.bus_backend == "redis":
        from crmcore.bus.redis_streams import BusRedis
        from crmcore.red import tls_exigido

        tls_exigido.exigir(s.redis_url, tramo="el bus", ajuste="BUS_TLS", exigido=s.bus_tls)
        bus = BusRedis(s.redis_url, prefijo=s.bus_prefix, servicio=nombre_servicio)
        await bus.conectar()
        return bus

    from crmcore.bus.nats_js import BusNats
    from crmcore.red import tls_exigido

    tls_exigido.exigir(s.nats_url, tramo="el bus", ajuste="BUS_TLS", exigido=s.bus_tls)
    bus = BusNats(s.nats_url, prefijo=s.bus_prefix, servicio=nombre_servicio)
    await bus.conectar()
    return bus
