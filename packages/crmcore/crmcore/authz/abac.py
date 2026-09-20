"""ABAC: decisiones por atributos, y sobre todo, **explicables** (CRM-00.05.02.05).

RBAC responde «¿puede leer cuentas?». ABAC responde lo que de verdad pregunta un
CRM: «¿puede leer ESTA cuenta?». La diferencia son los atributos —del que
pregunta, del registro y del contexto— y por eso el permiso no basta: dos
comerciales con el mismo rol no ven las mismas cuentas.

Las reglas son **datos, no código**: una política es una estructura que se guarda,
se versiona y se puede enseñar. Eso es lo que hace posible el explicador de
permisos (CRM-00.05.02.11), que responde «ves este registro porque eres su
propietario y la política *propias_y_del_equipo* lo permite». Con las
condiciones escritas en Python, esa respuesta habría que reconstruirla a mano y
acabaría siendo aproximada.

Las políticas se evalúan **después** del RBAC y solo pueden restringir, nunca
ampliar. Un usuario sin `account:read` no lee cuentas por muy permisiva que sea
la política. Así la pregunta «¿qué puede hacer como máximo?» se responde
mirando solo los roles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

# Operadores admitidos en una condición. Es una lista cerrada a propósito: si
# una política pudiera llamar a cualquier función, evaluarla sería ejecutar
# código del tenant dentro del motor de permisos.
OPERADORES: dict[str, Callable[[Any, Any], bool]] = {
    "=": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a is not None and b is not None and a > b,
    ">=": lambda a, b: a is not None and b is not None and a >= b,
    "<": lambda a, b: a is not None and b is not None and a < b,
    "<=": lambda a, b: a is not None and b is not None and a <= b,
    "en": lambda a, b: a in (b or []),
    "no_en": lambda a, b: a not in (b or []),
    "contiene": lambda a, b: b in (a or []),
    "vacio": lambda a, _b: a in (None, "", [], {}),
    "no_vacio": lambda a, _b: a not in (None, "", [], {}),
}


def a_sql(columna: Any, operador: str, valor: Any) -> Any:
    """La misma comparación, pero como `WHERE` de SQL. `None` si no se puede.

    Existe porque una regla de compartición tiene que decidir dos cosas con la
    **misma** gramática: si este registro concreto se ve —en Python, sobre un
    diccionario— y cuáles se ven de todos —en SQL, sobre una tabla—. Dos
    gramáticas distintas para lo mismo es cómo se acaba con un listado que
    enseña un registro que la ficha luego niega.

    Devuelve `None` para lo que no tiene traducción honesta:

      * Un valor con prefijo `@`, que apunta a otro atributo del ámbito. En SQL
        no hay ámbito: quien llama resuelve esa parte antes.
      * `contiene`, que en Python mira dentro de una lista y en SQL depende del
        tipo de la columna —un JSONB, un array, una relación— y traducirlo mal
        es peor que no traducirlo.

    Nunca se inventa una traducción aproximada. Una condición traducida «casi
    igual» produce un listado que casi acierta, y eso no se detecta mirándolo.
    """
    if isinstance(valor, str) and valor.startswith("@"):
        return None

    if operador == "=":
        return columna == valor
    if operador == "!=":
        return columna != valor
    if operador == ">":
        return columna > valor
    if operador == ">=":
        return columna >= valor
    if operador == "<":
        return columna < valor
    if operador == "<=":
        return columna <= valor
    if operador == "en":
        return columna.in_(list(valor or []))
    if operador == "no_en":
        return columna.not_in(list(valor or []))
    if operador == "vacio":
        return columna.is_(None)
    if operador == "no_vacio":
        return columna.is_not(None)
    return None


@dataclass(frozen=True, slots=True)
class Condicion:
    """Una comparación entre un atributo y un valor.

    El atributo se nombra con ruta: `registro.owner_id`, `usuario.territorio`,
    `contexto.hora`. El valor puede ser literal o, con el prefijo `@`, otro
    atributo — que es lo que permite la regla más usada de todas:
    `registro.owner_id = @usuario.id`.
    """

    atributo: str
    operador: str
    valor: Any = None

    def evaluar(self, ambito: dict[str, Any]) -> bool:
        izquierda = _leer(ambito, self.atributo)
        derecha = (
            _leer(ambito, self.valor[1:])
            if isinstance(self.valor, str) and self.valor.startswith("@")
            else self.valor
        )
        fn = OPERADORES.get(self.operador)
        if fn is None:
            # Operador desconocido = política corrupta. Se deniega: en
            # seguridad, ante la duda, no.
            return False
        try:
            return fn(izquierda, derecha)
        except TypeError:
            # Comparar una fecha con un número es un error de la política, no
            # una autorización. Se deniega y se sigue.
            return False

    def explicar(self, ambito: dict[str, Any]) -> str:
        return (
            f"{self.atributo} ({_leer(ambito, self.atributo)!r}) " f"{self.operador} {self.valor!r}"
        )


@dataclass(frozen=True, slots=True)
class Politica:
    """Un conjunto de condiciones que se aplica a un objeto y unas acciones."""

    nombre: str
    objeto: str
    acciones: frozenset[str]
    condiciones: tuple[Condicion, ...] = ()
    # `todas` = AND, `alguna` = OR. Sin anidamiento a propósito: una política
    # que necesita paréntesis se parte en dos políticas, y así cada una se puede
    # explicar en una frase.
    combinacion: str = "todas"
    # Orden de evaluación. Las más baratas primero, porque la primera que
    # deniega corta.
    prioridad: int = 100
    activa: bool = True
    descripcion: str = ""

    def aplica_a(self, objeto: str, accion: str) -> bool:
        return (
            self.activa
            and self.objeto in (objeto, "*")
            and (accion in self.acciones or "*" in self.acciones)
        )

    def evaluar(self, ambito: dict[str, Any]) -> bool:
        if not self.condiciones:
            return True
        resultados = [c.evaluar(ambito) for c in self.condiciones]
        return all(resultados) if self.combinacion == "todas" else any(resultados)


@dataclass(slots=True)
class Decision:
    """Resultado de evaluar las políticas, con su porqué."""

    permitido: bool
    # Políticas que se evaluaron y qué dijo cada una. Es lo que consume el
    # explicador: sin esto, la respuesta a «¿por qué no lo veo?» sería «porque
    # no», que es la razón por la que estos sistemas generan tantos tickets.
    razones: list[str] = field(default_factory=list)
    politica_decisiva: str = ""

    def explicacion(self) -> str:
        if self.permitido and not self.politica_decisiva:
            return "Sin políticas aplicables: decide solo el permiso del rol"
        cabecera = "Permitido" if self.permitido else "Denegado"
        return f"{cabecera} por «{self.politica_decisiva}». " + " | ".join(self.razones)


def evaluar(
    politicas: list[Politica],
    *,
    objeto: str,
    accion: str,
    ambito: dict[str, Any],
) -> Decision:
    """Evalúa las políticas aplicables. Todas deben permitir.

    Conjunción y no disyunción: si dos políticas aplican —una de territorio y
    otra de confidencialidad— tienen que pasar las dos. Con disyunción, añadir
    una política permisiva anularía en silencio a una restrictiva ya existente,
    y nadie revisa las políticas viejas al crear una nueva.
    """
    aplicables = sorted(
        (p for p in politicas if p.aplica_a(objeto, accion)), key=lambda p: p.prioridad
    )
    if not aplicables:
        return Decision(permitido=True)

    razones: list[str] = []
    for politica in aplicables:
        if politica.evaluar(ambito):
            razones.append(f"«{politica.nombre}» permite")
            continue
        detalle = " y ".join(c.explicar(ambito) for c in politica.condiciones)
        return Decision(
            permitido=False,
            razones=[*razones, f"«{politica.nombre}» deniega: no se cumple {detalle}"],
            politica_decisiva=politica.nombre,
        )
    return Decision(permitido=True, razones=razones, politica_decisiva=aplicables[-1].nombre)


def _leer(ambito: dict[str, Any], ruta: str) -> Any:
    """Lee `registro.owner.id` del ámbito, sin lanzar si falta algo.

    Devolver `None` ante un atributo ausente y no lanzar es lo correcto aquí:
    una política que mira un campo que este objeto no tiene debe no cumplirse,
    no romper la petición.
    """
    actual: Any = ambito
    for parte in ruta.split("."):
        if isinstance(actual, dict):
            actual = actual.get(parte)
        else:
            actual = getattr(actual, parte, None)
        if actual is None:
            return None
    return actual


def ambito_estandar(*, registro: Any = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ámbito con usuario, contexto y registro, listo para evaluar."""
    from datetime import datetime, timezone

    from crmcore.authz.principal import principal_actual
    from crmcore.tenancy.context import contexto_actual

    p = principal_actual()
    ctx = contexto_actual()
    ahora = datetime.now(timezone.utc)
    return {
        "usuario": {
            "id": p.id,
            "tipo": p.tipo,
            "roles": list(p.roles),
            "business_unit_id": p.business_unit_id,
            **p.atributos,
        },
        "contexto": {
            "tenant_id": ctx.tenant_id,
            "origen": ctx.origen,
            "hora": ahora.hour,
            "dia_semana": ahora.weekday(),
            "ip": ctx.extra.get("ip", ""),
            "pais": ctx.extra.get("pais", ""),
        },
        "registro": registro,
        **(extra or {}),
    }


# ── Políticas de ejemplo ──────────────────────────────────────────────────
# Se incluyen porque son las tres que pide casi todo despliegue, y porque sirven
# de plantilla de cómo se escribe una. Un tenant las activa, las modifica o las
# ignora: no están activas de serie.

POLITICAS_EJEMPLO: list[Politica] = [
    Politica(
        nombre="solo_propias",
        objeto="opportunity",
        acciones=frozenset({"write", "delete"}),
        condiciones=(Condicion("registro.owner_id", "=", "@usuario.id"),),
        descripcion="Un comercial solo modifica las oportunidades de las que es propietario",
        activa=False,
    ),
    Politica(
        nombre="misma_unidad_de_negocio",
        objeto="account",
        acciones=frozenset({"read", "write"}),
        condiciones=(Condicion("registro.business_unit_id", "=", "@usuario.business_unit_id"),),
        descripcion="Cada unidad de negocio ve solo sus cuentas",
        activa=False,
    ),
    Politica(
        nombre="horario_laboral",
        objeto="*",
        acciones=frozenset({"export"}),
        condiciones=(
            Condicion("contexto.hora", ">=", 7),
            Condicion("contexto.hora", "<=", 21),
        ),
        descripcion=(
            "Las exportaciones masivas, solo en horario laboral: una descarga "
            "a las tres de la mañana casi nunca es un informe"
        ),
        activa=False,
    ),
]
