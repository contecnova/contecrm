"""Multi-tenancy: contexto, resolución y las dos redes de aislamiento."""

from crmcore.tenancy.context import (
    ContextoPeticion,
    con_contexto,
    contexto_actual,
    contexto_sistema,
    exigir_tenant,
)

__all__ = [
    "ContextoPeticion",
    "con_contexto",
    "contexto_actual",
    "contexto_sistema",
    "exigir_tenant",
]
