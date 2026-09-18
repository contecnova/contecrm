"""Punto de entrada del servicio de identidad."""

from __future__ import annotations

from crmcore.service import crear_servicio

from services.identity.api import ROUTERS

app = crear_servicio(
    nombre="identity",
    descripcion=(
        "Usuarios, membresías por tenant, roles y permisos, sesiones "
        "revocables, MFA, claves de API, federación y suplantación auditada."
    ),
    routers=ROUTERS,
)
