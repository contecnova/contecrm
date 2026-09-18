"""Eventos de dominio: sobre, catálogo y contrato con los integradores."""

from crmcore.events.envelope import Actor, Evento, Subject, crear_evento

__all__ = ["Actor", "Evento", "Subject", "crear_evento"]
