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


def clave(tipo: str | TipoEvento) -> str:
    """El nombre del tipo, venga como cadena o como la constante declarada.

    **Las dos formas se usan y las dos tienen que valer**, y hasta hoy sólo
    valía una. Medido el 12-10-2026 con la sonda: emitir con la constante
    —`uow.emitir(ALTA_CONFIRMADA, ...)`, que es justo lo que hace que un
    recorrido de «declarado y sin emisor» dé el arreglo por bueno— llegaba
    entera a la tabla de salida y reventaba al escribirla:

        TypeError: sequence item 0: expected str instance, TipoEvento found

    Y antes de reventar hacía algo peor y callado: `comprobar_emision` busca el
    tipo en este registro, que está indexado por cadena, así que con la
    constante no encontraba nada y **devolvía que no falta ningún campo**. El
    contrato dejaba de comprobarse precisamente en las emisiones escritas de la
    forma más cuidadosa.

    Se normaliza en la puerta y no en cada sitio: los sitios son catorce y
    «funciona donde alguien se acordó» no es una garantía.
    """
    return tipo.tipo if isinstance(tipo, TipoEvento) else str(tipo)


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
        # Lo emite CUALQUIER servicio, no `tenancy`: los medidores de consumo se
        # registran por proceso y cada servicio mide lo suyo sobre su propio
        # esquema. Un emisor central tendría que leer las tablas de los catorce.
        productor="core",
        descripcion=(
            "Un tenant ha alcanzado el umbral de aviso de una cuota. Lo emite el "
            "barrido del núcleo, una vez por métrica y periodo — la clave de "
            "deduplicación lleva el periodo, así que seguir por encima del umbral "
            "no repite el aviso"
        ),
        campos=("tenant_id", "cuota", "consumido", "limite", "pct", "metrica", "periodo"),
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
USER_ORG_CHANGED = registrar(
    TipoEvento(
        tipo="user.org.changed",
        version=1,
        productor="identity",
        descripcion=(
            "La posición de una persona en la organización: sus roles, quién es "
            "su superior y en qué unidad está. Va aparte de `user.provisioned` "
            "porque cambia mucho más a menudo que el alta —un ascenso, una "
            "reorganización, un cambio de equipo— y porque quien lo necesita no "
            "es quien da la bienvenida: es quien tiene que decidir a QUIÉN le "
            "toca aprobar algo"
        ),
        campos=("user_id", "roles", "superior_id", "unidad_id", "activa"),
    )
)
USER_PASSWORD_RESET_REQUESTED = registrar(
    TipoEvento(
        tipo="user.password.reset_requested",
        version=1,
        productor="identity",
        descripcion=(
            "Alguien ha pedido restablecer su contraseña. Lo consume quien manda "
            "el correo: el enlace se emite aquí y se entrega fuera, porque el "
            "canal de correo lo pone cada instalación"
        ),
        campos=("usuario_id", "email"),
        # Interno: lleva el correo de una persona y el aviso de que su cuenta
        # está en juego. Eso no sale del sistema por el bus público.
        publico=False,
    )
)
USER_PASSKEY_REGISTERED = registrar(
    TipoEvento(
        tipo="user.passkey.registered",
        version=1,
        productor="identity",
        descripcion=(
            "Alguien ha registrado una passkey. Interesa a quien vigila la "
            "seguridad de las cuentas: una llave nueva que no reconoce su dueño "
            "es una cuenta comprometida"
        ),
        campos=("usuario_id", "passkey_id", "nombre"),
    )
)
USER_PASSKEY_REVOKED = registrar(
    TipoEvento(
        tipo="user.passkey.revoked",
        version=1,
        productor="identity",
        descripcion="Se ha quitado una passkey de una cuenta",
        campos=("usuario_id", "passkey_id"),
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
RECORD_COMMENTED = registrar(
    TipoEvento(
        tipo="record.commented",
        version=1,
        # Productor `core` porque lo emite el router compartido de comentarios,
        # montado por el servicio dueño de cada registro. Atribuirlo a `party` o
        # a `sales` sería mentir en la mitad de los casos.
        productor="core",
        descripcion=(
            "Alguien ha comentado un registro. Lleva las menciones resueltas "
            "para que quien avisa no tenga que volver a leer el texto"
        ),
        campos=("comentario_id", "objeto_tipo", "objeto_id", "hilo_id", "autor_id", "menciones"),
    )
)
SCHEMA_CHANGED = registrar(
    TipoEvento(
        tipo="metadata.schema.changed",
        version=1,
        productor="metadata",
        descripcion=(
            "Ha cambiado el esquema de un objeto: campos, validaciones o layout. "
            "Lo consumen TODOS los servicios para replicarlo y poder validar, "
            "filtrar e indexar los campos propios del tenant"
        ),
        # Va la lista ENTERA de campos y no el delta. Un delta obliga a que el
        # consumidor tenga el estado anterior correcto, y con entrega
        # at-least-once y sin orden garantizado eso no se puede afirmar: un
        # evento perdido dejaría la réplica desalineada para siempre y nadie lo
        # vería hasta que alguien no pudiera guardar un campo.
        campos=("objeto", "cambio", "campos", "version"),
    )
)
