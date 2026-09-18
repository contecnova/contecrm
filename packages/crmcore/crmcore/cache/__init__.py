"""Caché con aislamiento por tenant (CRM-00.01.01.07).

Una caché compartida es la vía más silenciosa que existe para que un cliente vea
el dato de otro: basta una clave construida sin el tenant —`cuenta:{id}`,
`ajustes:activos`, `conteo:leads`— para que la respuesta del primero que pregunte
se le sirva al siguiente, sin error, sin log y sin forma de notarlo hasta que
alguien lo cuenta.

Por eso aquí **el que llama no construye claves**. Se pide un espacio de nombres
y unas partes, y la clave la fabrica este módulo poniendo el tenant delante.
Saltarse el aislamiento no es difícil: es que no hay manera de expresarlo, salvo
pidiendo explícitamente una entrada global, que es una llamada distinta y
auditable.

**La purga por tenant es O(1), no un barrido.** La clave incluye un número de
generación del tenant; purgar es incrementarlo, con lo que todas sus entradas
anteriores dejan de ser alcanzables de golpe y el propio TTL las recoge. La
alternativa —recorrer el espacio de claves buscando un prefijo— es O(N) sobre
toda la instancia y, con `KEYS`, además bloquea a Redis entero: un cliente
dándose de baja congelaría el sistema para todos los demás.

De ahí sale la otra regla: **toda entrada caduca**. Sin TTL, lo que la purga
deja inalcanzable seguiría ocupando memoria para siempre.
"""

from crmcore.cache.base import (
    Cache,
    CacheMemoria,
    CacheRedis,
    clave_de,
    get_cache,
    purgar_tenant,
    reset_cache,
)
from crmcore.cache.registro import (
    instantanea,
    invalidar_todos,
    limpiar_registro,
    registrar,
    restaurar,
)

__all__ = [
    "Cache",
    "instantanea",
    "invalidar_todos",
    "limpiar_registro",
    "registrar",
    "restaurar",
    "CacheMemoria",
    "CacheRedis",
    "clave_de",
    "get_cache",
    "purgar_tenant",
    "reset_cache",
]
