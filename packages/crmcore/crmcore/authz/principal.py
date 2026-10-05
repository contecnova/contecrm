"""Quién pregunta: el principal y sus permisos efectivos.

Un principal puede ser una persona, una cuenta de servicio, una automatización o
un agente de IA. Los cuatro se tratan igual en la autorización —y eso es
deliberado: un agente que actúa «en nombre de» alguien no puede heredar sus
permisos sin más, porque entonces el kill switch del agente (CRM-05.02.03.04) no
tendría dónde aplicarse. El agente tiene su propio principal, con sus propios
permisos, normalmente un subconjunto.

El permiso se nombra `objeto:accion`, con comodín por partes:

    account:read          leer cuentas
    account:*             todo sobre cuentas
    *:read                leer cualquier objeto
    *:*                   administrador del tenant

El comodín solo se expande a la DERECHA de los dos puntos y por segmento
completo: `acc*:read` no existe. Un comodín parcial sobre el nombre del objeto
sería imposible de auditar («¿qué cubre esto exactamente?») y un objeto nuevo
podría quedar cubierto por accidente el día que alguien lo cree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

# Permiso que lo concede todo dentro del tenant. No cruza tenants: eso lo hace
# `es_admin_plataforma`, que es una propiedad del principal, no un permiso.
TODO = "*:*"


@dataclass(frozen=True, slots=True)
class Principal:
    """Identidad efectiva de una petición."""

    id: UUID | None
    tipo: str = "usuario"  # usuario | servicio | automatizacion | agente | anonimo
    tenant_id: UUID | None = None
    business_unit_id: UUID | None = None
    # Permisos ya resueltos: la unión de los de todos sus roles y conjuntos.
    # Se resuelven al autenticar y se llevan en el contexto, para no consultar
    # la tabla de permisos en cada comprobación.
    permisos: frozenset[str] = field(default_factory=frozenset)
    roles: frozenset[str] = field(default_factory=frozenset)
    # Ámbitos del token OAuth. Acotan POR ENCIMA de los permisos: una aplicación
    # de terceros con scope `account:read` no puede escribir aunque el usuario
    # que la autorizó sea administrador. Vacío = sin acotar (sesión propia).
    scopes: frozenset[str] = field(default_factory=frozenset)
    es_admin_plataforma: bool = False
    # Quién suplanta, si hay suplantación en curso.
    actor_real_id: UUID | None = None
    # La sesión con la que se entró (`sid` del token). Va aquí y no se saca del
    # token en cada sitio que la necesita porque **a los servicios de detrás no
    # les llega el token**: la identidad viaja en cabeceras firmadas desde el
    # gateway. Sin propagarla, el nivel de autenticación multifactor de la
    # sesión —qué factores se superaron y cuándo— no se podía consultar, y los
    # tres sitios que lo intentaban leían un campo inexistente y devolvían 500.
    sesion_id: UUID | None = None
    # Cuándo fue el último factor FUERTE de esta sesión, en ISO. Viaja con la
    # identidad por la misma razón que `sesion_id`: la tabla de sesiones vive en
    # el esquema de `identity` y ningún servicio lee el de otro, así que sin
    # propagarlo las operaciones sensibles que ocurren FUERA de identity
    # —exportar media base, borrar en bloque, restaurar encima de lo actual— no
    # podían exigir la reverificación. La lista de operaciones sensibles existía
    # y se publicaba; lo que no existía era quien la aplicara.
    factor_fuerte_at: str = ""
    # Atributos para las decisiones ABAC (departamento, país, territorio…).
    atributos: dict[str, object] = field(default_factory=dict)

    @property
    def es_anonimo(self) -> bool:
        return self.id is None and not self.es_admin_plataforma

    def tiene(self, permiso: str) -> bool:
        """Si el principal tiene un permiso, contando comodines y scopes."""
        if self.es_admin_plataforma:
            return True
        if not _concede(self.permisos, permiso):
            return False
        # El scope solo acota si hay scopes: un token de sesión normal no los
        # lleva y no debe verse limitado por ello.
        return not self.scopes or _concede(self.scopes, permiso)

    def exigir(self, permiso: str) -> None:
        """Lanza `Prohibido` si falta el permiso."""
        if self.tiene(permiso):
            return
        from crmcore.errors import Prohibido

        raise Prohibido(
            "No tienes permiso para realizar esta operación",
            error_code="authz.permiso_ausente",
            # Se dice QUÉ permiso falta: no es una filtración (el cliente ya
            # sabe qué intentó) y ahorra la mitad de los tickets de soporte,
            # que son «no puedo hacer X» sin saber qué pedirle al administrador.
            detalle={"permiso_requerido": permiso},
        )


ANONIMO = Principal(id=None, tipo="anonimo")


def _concede(concedidos: frozenset[str], permiso: str) -> bool:
    """Si el conjunto concede el permiso pedido, expandiendo comodines."""
    if TODO in concedidos or permiso in concedidos:
        return True
    objeto, _, accion = permiso.partition(":")
    return f"{objeto}:*" in concedidos or f"*:{accion}" in concedidos


def principal_actual() -> Principal:
    """Principal del contexto en curso.

    Lo deja ahí la dependencia de autenticación. Sin autenticar devuelve
    `ANONIMO` en vez de `None`: así el código de permisos no tiene que
    comprobar nulos, y un endpoint que se olvide de exigir autenticación falla
    por falta de permiso en vez de por `AttributeError` — el fallo correcto.
    """
    from crmcore.tenancy.context import contexto_actual

    ctx = contexto_actual()
    guardado = ctx.extra.get("principal")
    if isinstance(guardado, Principal):
        return guardado
    if ctx.es_admin_plataforma:
        return Principal(id=ctx.user_id, tipo="servicio", es_admin_plataforma=True)
    if ctx.user_id is None:
        return ANONIMO
    return Principal(
        id=ctx.user_id,
        tenant_id=ctx.tenant_id,
        business_unit_id=ctx.business_unit_id,
        scopes=ctx.scopes,
        actor_real_id=ctx.actor_real_id,
    )
