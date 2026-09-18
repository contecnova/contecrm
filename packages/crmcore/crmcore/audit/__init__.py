"""Auditoría: traza encadenada verificable e historial de campo."""

from crmcore.audit.chain import registrar, registrar_cambios, verificar

__all__ = ["registrar", "registrar_cambios", "verificar"]
