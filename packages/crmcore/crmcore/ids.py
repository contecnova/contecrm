"""Identificadores opacos y ordenables (CRM-00.01.02.07).

Todo identificador de negocio es un **UUIDv7**: aleatorio en apariencia pero con
marca de tiempo en los bits altos, así que ordena por antigüedad y no fragmenta
los índices como un UUIDv4.

Por qué no un entero autoincremental, que es lo cómodo: un id secuencial es
enumerable. Quien ve `/accounts/1043` prueba `1044`, y entonces el aislamiento
entre tenants depende por entero de que la comprobación de permisos sea perfecta
en todos y cada uno de los endpoints. Con identificadores opacos, adivinar el de
otro tenant deja de ser una posibilidad práctica, y la comprobación de permisos
pasa a ser la segunda red en vez de la única.

Se responde **404** —no 403— a un id de otro tenant (CRM-00.01.02.05): un 403
confirma que ese registro existe, que es información que no le corresponde.
"""

from __future__ import annotations

import re
from uuid import UUID

from uuid6 import uuid7

# Prefijos legibles por tipo de entidad. No aportan seguridad: aportan que un
# identificador suelto en un log, un ticket de soporte o una URL diga de qué es
# sin tener que buscarlo. El id canónico sigue siendo el UUID.
PREFIJOS: dict[str, str] = {
    "tenant": "ten",
    "user": "usr",
    "account": "acc",
    "contact": "con",
    "lead": "led",
    "opportunity": "opp",
    "quote": "quo",
    "order": "ord",
    "contract": "ctr",
    "case": "cas",
    "campaign": "cmp",
    "segment": "seg",
    "journey": "jny",
    "workflow": "wfl",
    "workflow_instance": "wfi",
    "event": "evt",
    "job": "job",
    "webhook": "whk",
    "apikey": "key",
    "role": "rol",
    "object": "obj",
    "field": "fld",
}

_RE_PREFIJADO = re.compile(r"^(?P<prefijo>[a-z]{2,8})_(?P<uuid>[0-9a-fA-F-]{36})$")


def nuevo_id() -> UUID:
    """UUIDv7 nuevo."""
    return uuid7()


def con_prefijo(tipo: str, valor: UUID) -> str:
    """Representación legible: `acc_0192f3c1-...`.

    Si el tipo no está en el mapa se devuelve el UUID desnudo en vez de
    inventar un prefijo: un prefijo inventado acabaría en una URL pública y ya
    no se podría cambiar.
    """
    prefijo = PREFIJOS.get(tipo)
    return f"{prefijo}_{valor}" if prefijo else str(valor)


def sin_prefijo(valor: str) -> UUID:
    """Lee un identificador con o sin prefijo.

    Acepta las dos formas a propósito: la prefijada es la que se enseña, pero un
    integrador que guardó el UUID desnudo en su sistema tiene que seguir
    pudiendo usarlo. Lanza `ValueError` si no es ninguna de las dos.
    """
    m = _RE_PREFIJADO.match(valor.strip())
    return UUID(m.group("uuid")) if m else UUID(valor.strip())


def es_id_valido(valor: str) -> bool:
    """Si la cadena es un identificador legible, sin lanzar."""
    try:
        sin_prefijo(valor)
        return True
    except (ValueError, AttributeError):
        return False
