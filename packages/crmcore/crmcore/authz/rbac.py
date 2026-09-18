"""RBAC: roles, conjuntos de permisos y jerarquía (CRM-00.05.02.01, .02).

Tres piezas, y la diferencia entre ellas es lo que evita el problema clásico de
«tengo que crear un rol nuevo para una persona»:

  * **Rol** — un puesto: comercial, responsable de ventas, agente de soporte.
    Uno por usuario (o pocos).
  * **Conjunto de permisos** — un añadido acumulable: «puede exportar»,
    «puede aprobar descuentos hasta el 15 %». Se suman al rol sin duplicarlo.
  * **Jerarquía** — quién ve los registros de quién. Un responsable ve los de su
    equipo por estar por encima, no por tener un permiso extra.

Los permisos **se suman, nunca se restan**. No hay negaciones, y es a propósito:
en cuanto se mezclan concesiones y denegaciones con herencia, responder «¿por
qué este usuario ve esto?» deja de ser posible sin ejecutar el motor entero.
Para restringir por debajo del rol están los ámbitos del token y las políticas
ABAC, que son condicionales y explicables por separado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ConjuntoPermisos:
    """Grupo acumulable de permisos."""

    nombre: str
    permisos: frozenset[str]
    descripcion: str = ""


@dataclass(frozen=True, slots=True)
class Rol:
    """Puesto, con sus permisos y su posición en la jerarquía."""

    nombre: str
    permisos: frozenset[str] = field(default_factory=frozenset)
    conjuntos: frozenset[str] = field(default_factory=frozenset)
    # Rol del que hereda permisos. La herencia es de permisos, no de visibilidad:
    # quién ve los registros de quién lo decide `superior_id` en el usuario.
    hereda_de: str | None = None
    descripcion: str = ""
    # Los roles de sistema no se pueden borrar ni renombrar desde la consola.
    # Sin esta marca, un administrador puede dejarse a sí mismo sin acceso, y
    # recuperarlo exige tocar la base a mano.
    es_sistema: bool = False


def resolver_permisos(
    rol: str,
    *,
    roles: dict[str, Rol],
    conjuntos: dict[str, ConjuntoPermisos],
    extra: frozenset[str] = frozenset(),
    _vistos: frozenset[str] = frozenset(),
) -> frozenset[str]:
    """Permisos efectivos de un rol: los suyos, los heredados y sus conjuntos.

    `_vistos` corta los ciclos de herencia. Un ciclo es un error de
    configuración, pero si no se corta aquí se manifiesta como una recursión
    infinita al iniciar sesión, que es un fallo mucho peor de diagnosticar.
    """
    if rol in _vistos:
        return extra
    definicion = roles.get(rol)
    if definicion is None:
        return extra

    permisos = set(definicion.permisos) | set(extra)
    for nombre in definicion.conjuntos:
        cj = conjuntos.get(nombre)
        if cj:
            permisos |= set(cj.permisos)
    if definicion.hereda_de:
        permisos |= resolver_permisos(
            definicion.hereda_de,
            roles=roles,
            conjuntos=conjuntos,
            _vistos=_vistos | {rol},
        )
    return frozenset(permisos)


def subordinados(usuario_id: UUID, jerarquia: dict[UUID, UUID | None]) -> set[UUID]:
    """Todos los usuarios por debajo de uno en la jerarquía.

    Es lo que da la visibilidad ascendente (CRM-00.05.02.02): un responsable ve
    los registros de todo su árbol, no solo los de quien le reporta directo.

    Recorrido iterativo y con conjunto de visitados: una jerarquía mal cargada
    con un ciclo (A reporta a B, B reporta a A) es rara pero existe, y con
    recursión ingenua tumbaría el proceso en vez de dar un resultado raro.
    """
    hijos: dict[UUID, list[UUID]] = {}
    for hijo, padre in jerarquia.items():
        if padre is not None:
            hijos.setdefault(padre, []).append(hijo)

    resultado: set[UUID] = set()
    pila = list(hijos.get(usuario_id, []))
    while pila:
        actual = pila.pop()
        if actual in resultado:
            continue
        resultado.add(actual)
        pila.extend(hijos.get(actual, []))
    return resultado


# ── Roles de serie ────────────────────────────────────────────────────────
# Es el mínimo con el que un tenant nuevo es usable desde el minuto uno. No
# pretenden cubrir ninguna organización concreta: cada tenant crea los suyos, y
# estos son el punto de partida y el ejemplo de cómo se escriben.

ROLES_BASE: dict[str, Rol] = {
    "admin": Rol(
        nombre="admin",
        permisos=frozenset({"*:*"}),
        descripcion="Administra todo el tenant, incluida la configuración",
        es_sistema=True,
    ),
    "usuario": Rol(
        nombre="usuario",
        permisos=frozenset(
            {
                "account:read",
                "contact:read",
                "activity:read",
                "activity:write",
                "note:read",
                "note:write",
            }
        ),
        descripcion="Acceso de lectura al CRM y gestión de su propia actividad",
        es_sistema=True,
    ),
    "comercial": Rol(
        nombre="comercial",
        hereda_de="usuario",
        permisos=frozenset(
            {
                "account:write",
                "contact:write",
                "lead:read",
                "lead:write",
                "opportunity:read",
                "opportunity:write",
                "quote:read",
                "quote:write",
            }
        ),
        descripcion="Gestiona sus cuentas, contactos, leads y oportunidades",
        es_sistema=True,
    ),
    "responsable_ventas": Rol(
        nombre="responsable_ventas",
        hereda_de="comercial",
        permisos=frozenset({"forecast:read", "forecast:write", "opportunity:approve"}),
        descripcion="Además, previsión y aprobación sobre su equipo",
        es_sistema=True,
    ),
    "agente_soporte": Rol(
        nombre="agente_soporte",
        hereda_de="usuario",
        permisos=frozenset(
            {"case:read", "case:write", "knowledge:read", "entitlement:read"}
        ),
        descripcion="Atiende casos y consulta el conocimiento",
        es_sistema=True,
    ),
    "solo_lectura": Rol(
        nombre="solo_lectura",
        permisos=frozenset({"*:read"}),
        descripcion="Consulta todo, no modifica nada. Auditores y dirección",
        es_sistema=True,
    ),
    "integracion": Rol(
        nombre="integracion",
        permisos=frozenset({"*:read", "*:write"}),
        descripcion=(
            "Cuenta de servicio para integraciones. No administra configuración "
            "ni usuarios, a propósito: una credencial de máquina filtrada no "
            "debe poder cambiar quién tiene acceso"
        ),
        es_sistema=True,
    ),
}
