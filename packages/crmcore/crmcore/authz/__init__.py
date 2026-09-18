"""Autorización: quién es, qué puede y por qué."""

from crmcore.authz.principal import ANONIMO, Principal, principal_actual
from crmcore.authz.rbac import ROLES_BASE, ConjuntoPermisos, Rol, resolver_permisos

__all__ = [
    "ANONIMO",
    "ROLES_BASE",
    "ConjuntoPermisos",
    "Principal",
    "Rol",
    "principal_actual",
    "resolver_permisos",
]
