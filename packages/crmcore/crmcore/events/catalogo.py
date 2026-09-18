"""Catálogo de tipos de evento (CRM-00.02.02.07).

Un evento sin catálogo es un contrato que solo existe en la cabeza de quien lo
publicó. Aquí cada tipo está declarado con su versión, su dueño, la forma de su
carga y si es público (lo pueden recibir los webhooks del tenant) o interno.

De este registro salen tres cosas, y por eso no es documentación sino código:

  * el documento **AsyncAPI** que se publica a los integradores,
  * la lista de tipos que necesita el backend de Redis para resolver un patrón
    con comodines,
  * el gate que comprueba que lo declarado aquí y lo planificado en
    `docs/catalogo/catalogo.yaml` (Anexo B) no divergen.

**Regla de compatibilidad**: la forma de `data` solo puede crecer. Añadir un
campo opcional es compatible; quitarlo, renombrarlo o cambiarle el tipo NO lo
es, y exige publicar una versión nueva conviviendo con la anterior
(CRM-00.02.01.06). Un consumidor que se rompe porque el productor le quitó un
campo es el fallo más caro de un sistema de eventos: aparece en producción, en
otro equipo y días después del cambio.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TipoEvento:
    """Declaración de un tipo de evento."""

    tipo: str
    version: int
    # Servicio que lo publica. Solo él puede publicarlo: el gate de capas
    # comprueba que nadie emita un evento ajeno, porque un evento publicado por
    # dos sitios deja de tener dueño y nadie se atreve a cambiarlo.
    productor: str
    descripcion: str
    # Campos de `data` que van siempre. Sirven para documentar y para que el
    # gate compruebe que un productor no publica un evento incompleto.
    campos: tuple[str, ...] = ()
    # Si se puede entregar a los webhooks del tenant. Los internos (mecánica del
    # motor de procesos, reintentos) no salen: son ruido para el integrador y
    # además atarían nuestra implementación a su código.
    publico: bool = True


_REGISTRO: dict[str, TipoEvento] = {}


def registrar(tipo: TipoEvento) -> TipoEvento:
    """Da de alta un tipo. Rechaza duplicados con productor distinto."""
    existente = _REGISTRO.get(tipo.tipo)
    if existente and existente.productor != tipo.productor:
        raise ValueError(
            f"El evento «{tipo.tipo}» ya lo declara el servicio "
            f"«{existente.productor}»; dos productores del mismo evento dejan "
            "el contrato sin dueño"
        )
    _REGISTRO[tipo.tipo] = tipo
    return tipo


def obtener(tipo: str) -> TipoEvento | None:
    return _REGISTRO.get(tipo)


def todos() -> list[TipoEvento]:
    return sorted(_REGISTRO.values(), key=lambda t: t.tipo)


def publicos() -> list[TipoEvento]:
    return [t for t in todos() if t.publico]


def tipos_que_encajan(patron: str) -> list[str]:
    """Tipos que casan con un patrón de subject.

    El patrón viene en la forma del bus (`*.opportunity.*`, `>`), donde el
    primer segmento es el tenant. Se descarta ese segmento y se compara el
    resto contra los tipos declarados.
    """
    if patron.strip() in (">", "*", "**"):
        return [t.tipo for t in todos()]
    resto = patron.split(".", 1)[1] if patron.startswith(("*.", ">.")) else patron
    glob = resto.replace(">", "*")
    return [t.tipo for t in todos() if fnmatch.fnmatchcase(t.tipo, glob)]


def a_asyncapi(titulo: str, version: str) -> dict:
    """Documento AsyncAPI 3 con los eventos públicos.

    Se genera desde el registro, nunca a mano: una especificación mantenida a
    mano describe lo que alguien creía que el sistema publicaba el día que la
    escribió.
    """
    canales = {}
    for t in publicos():
        canales[t.tipo] = {
            "address": f"contecrm.{{tenant_id}}.{t.tipo}",
            "messages": {
                t.tipo: {
                    "name": t.tipo,
                    "title": t.descripcion,
                    "contentType": "application/json",
                    "payload": {
                        "type": "object",
                        "required": [
                            "id",
                            "type",
                            "version",
                            "tenant_id",
                            "occurred_at",
                            "actor",
                            "subject",
                            "data",
                            "dedup_key",
                        ],
                        "properties": {
                            "type": {"const": t.tipo},
                            "version": {"const": t.version},
                            "data": {
                                "type": "object",
                                "required": list(t.campos),
                            },
                        },
                    },
                }
            },
            "parameters": {"tenant_id": {"description": "Identificador del tenant"}},
        }
    return {
        "asyncapi": "3.0.0",
        "info": {
            "title": titulo,
            "version": version,
            "description": (
                "Eventos de dominio de contecrm. La entrega es at-least-once: "
                "deduplica siempre por `dedup_key`. El orden está garantizado "
                "por entidad, no globalmente."
            ),
        },
        "channels": canales,
    }


def limpiar_registro() -> None:
    """Vacía el registro. Solo para pruebas."""
    _REGISTRO.clear()


# ── Eventos de plataforma (los publica el propio núcleo) ──────────────────
# Los de negocio los declara cada servicio en su módulo `eventos.py`, que es
# donde vive el productor. Aquí solo van los que produce la plataforma.

TENANT_PROVISIONED = registrar(
    TipoEvento(
        tipo="tenant.provisioned",
        version=1,
        productor="tenancy",
        descripcion="Se ha dado de alta un tenant y su configuración inicial",
        campos=("tenant_id", "slug", "plan", "region"),
    )
)
TENANT_SUSPENDED = registrar(
    TipoEvento(
        tipo="tenant.suspended",
        version=1,
        productor="tenancy",
        descripcion="Un tenant ha quedado suspendido; sus credenciales dejan de operar",
        campos=("tenant_id", "motivo"),
    )
)
TENANT_REACTIVATED = registrar(
    TipoEvento(
        tipo="tenant.reactivated",
        version=1,
        productor="tenancy",
        descripcion="Un tenant suspendido vuelve a estar operativo",
        campos=("tenant_id",),
    )
)
QUOTA_THRESHOLD_REACHED = registrar(
    TipoEvento(
        tipo="quota.threshold.reached",
        version=1,
        productor="tenancy",
        descripcion="Un tenant ha alcanzado el umbral de aviso de una cuota",
        campos=("tenant_id", "cuota", "consumido", "limite", "pct"),
    )
)
USER_PROVISIONED = registrar(
    TipoEvento(
        tipo="user.provisioned",
        version=1,
        productor="identity",
        descripcion="Alta de usuario (manual, JIT desde el IdP o por SCIM)",
        campos=("user_id", "email", "via"),
    )
)
USER_DEPROVISIONED = registrar(
    TipoEvento(
        tipo="user.deprovisioned",
        version=1,
        productor="identity",
        descripcion="Baja de usuario; sus sesiones y credenciales quedan revocadas",
        campos=("user_id", "via"),
    )
)
RECORD_DELETED = registrar(
    TipoEvento(
        tipo="record.deleted",
        version=1,
        productor="core",
        descripcion="Se ha borrado un registro (a la papelera o definitivamente)",
        campos=("objeto", "registro_id", "definitivo"),
    )
)
SCHEMA_CHANGED = registrar(
    TipoEvento(
        tipo="metadata.schema.changed",
        version=1,
        productor="metadata",
        descripcion="Ha cambiado el esquema de un objeto: campos, validaciones o layout",
        campos=("objeto", "cambio"),
    )
)
