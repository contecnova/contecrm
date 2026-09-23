"""Eventos de dominio: sobre, catálogo y contrato con los integradores."""

# El catálogo de negocio se importa aquí para que esté **completo en cualquier
# proceso** que toque eventos. Es la diferencia entre un registro que describe
# el sistema y uno que describe lo que este proceso concreto haya importado por
# casualidad: con lo segundo, el servicio de eventos rechazaba suscripciones a
# eventos que el sistema emite todos los días.
from crmcore.events import dominio  # noqa: F401
from crmcore.events.envelope import Actor, Evento, Subject, crear_evento

__all__ = ["Actor", "Evento", "Subject", "crear_evento"]
