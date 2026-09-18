"""El sobre de un evento de dominio (Anexo B del catálogo).

Todo evento que sale de contecrm lleva **siempre** los mismos diez campos:

    id           identificador único de ESTA publicación (UUIDv7)
    type         `opportunity.won`, en minúsculas y con puntos
    version      versión del esquema de `data`; empieza en 1 y solo sube
    tenant_id    de quién son los datos
    occurred_at  cuándo pasó el hecho, no cuándo se publicó
    actor        quién lo provocó (usuario, servicio, automatización)
    subject      qué entidad cambió: tipo + id
    data         la carga, cuya forma depende de `type` y `version`
    trace_id     correlación con la petición que lo originó
    dedup_key    clave de deduplicación para el consumidor

Las tres decisiones que más se pagan si se hacen mal:

**`occurred_at` es cuándo pasó, no cuándo se publicó.** Con outbox pueden ser
momentos muy distintos: si el broker estuvo caído diez minutos, el evento se
publica diez minutos tarde. Un consumidor que ordene por la hora de publicación
reconstruye una historia falsa.

**`dedup_key` la pone el productor, no el transporte.** La entrega es
at-least-once, así que el mismo hecho puede llegar dos veces. Si la clave fuera
el id de la publicación, los dos intentos serían «distintos» y el consumidor
aplicaría el cambio dos veces. Por defecto se deriva de `(tipo, subject, hecho)`,
que es lo que de verdad identifica al hecho.

**`version` va en el sobre, no dentro de `data`.** Así un consumidor puede
decidir si sabe leer el evento ANTES de mirar la carga, y un cambio rompedor se
publica como versión nueva conviviendo con la anterior.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.ids import nuevo_id

# Versión del propio formato del sobre, distinta de la versión de cada evento.
# Solo cambiaría si se añadiera o quitara un campo del sobre.
VERSION_SOBRE = 1


@dataclass(frozen=True, slots=True)
class Actor:
    """Quién provocó el hecho.

    `tipo` distingue una persona de un servicio de una automatización. Sin esa
    distinción, la auditoría de un cambio hecho por una regla aparece a nombre
    del usuario que disparó la regla sin querer, y no hay forma de saberlo.
    """

    tipo: str = "sistema"  # usuario | servicio | automatizacion | agente | sistema
    id: str = ""
    nombre: str = ""

    def a_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"tipo": self.tipo}
        if self.id:
            d["id"] = self.id
        if self.nombre:
            d["nombre"] = self.nombre
        return d


@dataclass(frozen=True, slots=True)
class Subject:
    """Qué entidad cambió."""

    tipo: str
    id: str

    def a_dict(self) -> dict[str, Any]:
        return {"tipo": self.tipo, "id": self.id}


@dataclass(frozen=True, slots=True)
class Evento:
    """Sobre completo."""

    type: str
    tenant_id: UUID
    subject: Subject
    data: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    id: UUID = field(default_factory=nuevo_id)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    actor: Actor = field(default_factory=Actor)
    trace_id: str = ""
    dedup_key: str = ""
    # Sobre del propio formato, para que un consumidor viejo pueda rechazar un
    # sobre de un formato que no conoce en vez de leerlo a medias.
    envelope_version: int = VERSION_SOBRE

    def __post_init__(self) -> None:
        if not self.dedup_key:
            # `object.__setattr__` porque la clase es frozen: el valor se
            # calcula una vez, al construir, y después ya es inmutable.
            object.__setattr__(self, "dedup_key", self._clave_derivada())

    def _clave_derivada(self) -> str:
        """Clave estable a partir de lo que identifica el HECHO.

        Incluye `occurred_at` porque el mismo tipo de hecho sobre la misma
        entidad puede repetirse legítimamente —una oportunidad puede cambiar de
        etapa dos veces— y esas dos veces son hechos distintos que el consumidor
        debe procesar los dos.
        """
        material = "|".join(
            [
                self.type,
                str(self.version),
                str(self.tenant_id),
                self.subject.tipo,
                self.subject.id,
                self.occurred_at.isoformat(),
            ]
        )
        return hashlib.sha256(material.encode()).hexdigest()[:32]

    # ── Serialización ────────────────────────────────────────────────────

    def a_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "type": self.type,
            "version": self.version,
            "envelope_version": self.envelope_version,
            "tenant_id": str(self.tenant_id),
            "occurred_at": self.occurred_at.isoformat(),
            "actor": self.actor.a_dict(),
            "subject": self.subject.a_dict(),
            "data": self.data,
            "trace_id": self.trace_id,
            "dedup_key": self.dedup_key,
        }

    def a_json(self) -> str:
        return json.dumps(self.a_dict(), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def desde_dict(cls, d: dict[str, Any]) -> Evento:
        actor = d.get("actor") or {}
        subject = d.get("subject") or {}
        return cls(
            id=UUID(d["id"]),
            type=d["type"],
            version=int(d.get("version", 1)),
            envelope_version=int(d.get("envelope_version", VERSION_SOBRE)),
            tenant_id=UUID(d["tenant_id"]),
            occurred_at=datetime.fromisoformat(d["occurred_at"]),
            actor=Actor(
                tipo=actor.get("tipo", "sistema"),
                id=actor.get("id", ""),
                nombre=actor.get("nombre", ""),
            ),
            subject=Subject(tipo=subject.get("tipo", ""), id=subject.get("id", "")),
            data=d.get("data") or {},
            trace_id=d.get("trace_id", ""),
            dedup_key=d.get("dedup_key", ""),
        )

    @classmethod
    def desde_json(cls, texto: str) -> Evento:
        return cls.desde_dict(json.loads(texto))

    # ── Enrutado ─────────────────────────────────────────────────────────

    def subject_bus(self, prefijo: str) -> str:
        """Subject del bus: `contecrm.<tenant>.<tipo.de.evento>`.

        El tenant va en el subject, no solo en la carga, y eso da dos cosas a la
        vez: un consumidor puede suscribirse a un tenant concreto, y JetStream
        puede repartir por tenant para que una avalancha de uno no bloquee la
        entrega de los demás (CRM-00.01.01.10).
        """
        return f"{prefijo}.{self.tenant_id}.{self.type}"


def crear_evento(
    tipo: str,
    *,
    tenant_id: UUID,
    subject: tuple[str, Any],
    data: dict[str, Any] | None = None,
    version: int = 1,
    dedup_key: str | None = None,
) -> Evento:
    """Crea un evento tomando actor y traza del contexto en curso.

    Que el actor se tome del contexto y no se pase a mano es lo que hace que la
    trazabilidad no dependa de acordarse: quien emite un evento no tiene que
    saber quién estaba autenticado.
    """
    from crmcore.tenancy.context import contexto_actual

    ctx = contexto_actual()
    if ctx.user_id:
        actor = Actor(tipo="usuario", id=str(ctx.user_id))
    elif ctx.origen in ("automatizacion", "orquestador", "agente"):
        actor = Actor(tipo=ctx.origen)
    else:
        from crmcore.config import get_settings

        actor = Actor(tipo="servicio", nombre=get_settings().service_name or "desconocido")

    return Evento(
        type=tipo,
        tenant_id=tenant_id,
        subject=Subject(tipo=subject[0], id=str(subject[1])),
        data=data or {},
        version=version,
        actor=actor,
        trace_id=ctx.trace_id or ctx.request_id,
        dedup_key=dedup_key or "",
    )
