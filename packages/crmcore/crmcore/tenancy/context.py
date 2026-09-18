"""Contexto de ejecución: tenant, usuario, petición y traza.

Es el hilo que atraviesa todo el stack (CRM-00.01.02.02): la cabecera o el token
que entra por el gateway acaba, sin que nadie lo vaya pasando de función en
función, en el filtro de la consulta, en la etiqueta de la métrica, en el apunte
de auditoría y en el `SET app.current_tenant` de la conexión.

── Dónde se fija, y por qué importa tanto ────────────────────────────────────

Se fija en un **middleware ASGI puro**, nunca en una dependencia de FastAPI ni
en un `BaseHTTPMiddleware`. La razón es concreta y se paga cara si se ignora:

  * `BaseHTTPMiddleware` de Starlette ejecuta la aplicación de debajo en OTRA
    tarea de asyncio. Una tarea nueva hereda una COPIA del contexto, así que lo
    que el middleware fije después no se ve en el endpoint, y lo que fije antes
    se pierde al volver. El contextvar quedaría vacío justo donde hace falta.
  * Una dependencia `def` (síncrona) de FastAPI corre en un hilo del pool, con
    su propia copia del contexto: lo mismo.

Un middleware ASGI puro corre en la MISMA tarea que el endpoint, así que lo que
fija aquí se ve allí. Esto no es una preferencia de estilo: es la diferencia
entre que el aislamiento por tenant funcione o que sea decorativo.

── La segunda red ────────────────────────────────────────────────────────────

Aun así, el contextvar NO es la fuente autoritativa para la base de datos. La
sesión de SQLAlchemy lleva el tenant en `session.info["tenant_id"]`, fijado al
abrirla, y es eso lo que miran el guard ORM y el GUC de RLS. El contextvar sirve
para lo demás (logs, métricas, auditoría) y para el código sin petición
(trabajos de fondo, consumidores del bus), que abren la sesión declarando el
tenant explícitamente.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field, replace
from typing import Any, Iterator
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ContextoPeticion:
    """Quién pregunta, por cuenta de qué tenant y con qué correlación.

    Inmutable a propósito: se sustituye entero, no se muta. Así no puede pasar
    que una función intermedia cambie el tenant «solo un momento» y se olvide
    de devolverlo.
    """

    tenant_id: UUID | None = None
    # Slug legible del tenant. Se lleva además del id porque los logs y las
    # métricas son mucho más útiles con `acme` que con un UUID.
    tenant_slug: str = ""
    # Unidad de negocio dentro del tenant (CRM-00.01.03.08). Acota la
    # visibilidad por debajo del tenant sin ser otro tenant.
    business_unit_id: UUID | None = None
    user_id: UUID | None = None
    # Identidad efectiva cuando alguien de soporte está suplantando: `user_id`
    # es a quién se suplanta y esto es quién lo hace de verdad. La auditoría
    # registra los dos, que es lo que hace la suplantación aceptable.
    actor_real_id: UUID | None = None
    request_id: str = ""
    trace_id: str = ""
    # api | ui | automatizacion | orquestador | bus | cli | sistema.
    # Es lo que rellena el «origen» del historial de campo (CRM-00.05.04.02):
    # sin esto, un cambio hecho por una automatización parece hecho a mano.
    origen: str = "api"
    # Ámbitos concedidos al token o a la clave de API.
    scopes: frozenset[str] = field(default_factory=frozenset)
    # `True` cuando quien pregunta es personal de la plataforma, no del tenant.
    # Un administrador de sistema puede no llevar tenant, y eso NO es lo mismo
    # que un contexto sin resolver: uno puede ver todo a propósito y el otro no
    # debe ver nada.
    es_admin_plataforma: bool = False
    # Extras que un servicio quiera arrastrar (IP, dispositivo, país) para las
    # políticas contextuales. Es un dict normal para no acoplar el núcleo a lo
    # que cada servicio necesite.
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def tiene_tenant(self) -> bool:
        return self.tenant_id is not None

    @property
    def descripcion_actor(self) -> str:
        """Texto corto para logs y auditoría."""
        if self.actor_real_id and self.actor_real_id != self.user_id:
            return f"{self.user_id} (suplantado por {self.actor_real_id})"
        if self.user_id:
            return str(self.user_id)
        return "sistema" if self.es_admin_plataforma else "anónimo"


_VACIO = ContextoPeticion()

_contexto: ContextVar[ContextoPeticion] = ContextVar("crm_contexto", default=_VACIO)


def contexto_actual() -> ContextoPeticion:
    """Contexto en curso. Nunca es `None`: sin petición devuelve uno vacío."""
    return _contexto.get()


def fijar_contexto(ctx: ContextoPeticion) -> Token[ContextoPeticion]:
    """Fija el contexto y devuelve el testigo para restaurarlo.

    Solo debería llamarlo el middleware ASGI o el arranque de un trabajo de
    fondo. Para todo lo demás está `con_contexto`, que restaura solo.
    """
    return _contexto.set(ctx)


def restaurar_contexto(token: Token[ContextoPeticion]) -> None:
    _contexto.reset(token)


@contextmanager
def con_contexto(**cambios: Any) -> Iterator[ContextoPeticion]:
    """Ejecuta un bloque con el contexto modificado, y lo restaura al salir.

    Es lo que usan los trabajos de fondo y los consumidores del bus, que no
    tienen petición pero sí tenant:

        with con_contexto(tenant_id=tid, origen="bus"):
            procesar(evento)

    Restaura siempre, incluso si el bloque lanza. Un contexto que se queda
    pegado es exactamente cómo se produce una fuga entre tenants en un worker
    que reutiliza el hilo para el siguiente mensaje.
    """
    token = _contexto.set(replace(_contexto.get(), **cambios))
    try:
        yield _contexto.get()
    finally:
        _contexto.reset(token)


@contextmanager
def contexto_sistema(origen: str = "sistema") -> Iterator[ContextoPeticion]:
    """Contexto sin tenant y con permisos de plataforma.

    Para migraciones, tareas de mantenimiento y arranque. Es explícito y ruidoso
    a propósito: saltarse el filtro de tenant tiene que costar escribirlo.
    """
    token = _contexto.set(
        ContextoPeticion(origen=origen, es_admin_plataforma=True)
    )
    try:
        yield _contexto.get()
    finally:
        _contexto.reset(token)


def exigir_tenant() -> UUID:
    """Tenant en curso o error. Para código que no tiene sentido sin tenant.

    Lanza `Prohibido` y no `ErrorInterno` porque el caso real más frecuente no
    es un bug: es una petición que llegó sin resolver el tenant.
    """
    from crmcore.errors import Prohibido

    ctx = contexto_actual()
    if ctx.tenant_id is None:
        raise Prohibido(
            "La operación exige un tenant y la petición no lo ha resuelto",
            error_code="tenancy.sin_tenant",
        )
    return ctx.tenant_id
