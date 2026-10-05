"""Agregados sobre los hijos de un registro (CRM-00.04.01.04).

«Importe total de las líneas», «número de contactos activos», «fecha de la
última actividad». Son la otra mitad de los campos calculados: una fórmula mira
el propio registro y un rollup mira los que cuelgan de él.

Tres decisiones, y las tres van en la misma dirección:

**Se calcula en SQL, no en Python.** Traer las líneas para sumarlas en el
proceso son N filas por cada registro de un listado: veinte cuentas con
cincuenta contactos cada una son mil filas para pintar una columna. Un
`SELECT sum(...) GROUP BY` es una consulta y la hace el motor.

**No se guarda.** Guardarlo obliga a recalcular cada vez que cambia un hijo, y
el día que falle un recálculo el padre queda con un número viejo que parece
bueno. Un total que miente es peor que uno que cuesta una consulta.

**El hijo lo resuelve el servicio dueño.** `party` sabe que los contactos
cuelgan de una cuenta y `sales` que las líneas cuelgan de una oportunidad;
`crmcore` no lo sabe ni tiene por qué. Aquí está el mecanismo, y cada servicio
declara sus rollups con sus modelos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from crmcore.errors import ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Funciones de agregación admitidas. Cerrada a propósito: la alternativa es
# dejar pasar el nombre de una función de SQL desde la configuración del tenant,
# que es ejecutar SQL arbitrario con otro nombre.
FUNCIONES = {
    "suma": func.sum,
    "cuenta": func.count,
    "maximo": func.max,
    "minimo": func.min,
    "media": func.avg,
}


@dataclass(frozen=True, slots=True)
class Rollup:
    """Un agregado declarado sobre los hijos de un objeto.

    `filtro` son condiciones ya construidas por el servicio dueño —no texto que
    haya que interpretar aquí— porque el único que sabe qué significa «activo»
    para un contacto es quien tiene ese modelo delante.
    """

    nombre: str
    modelo_hijo: type
    campo_padre: str
    funcion: str
    campo: str | None = None
    filtro: Any = None

    def __post_init__(self) -> None:
        if self.funcion not in FUNCIONES:
            raise ErrorValidacion(
                f"«{self.funcion}» no es una función de agregación admitida",
                error_code="rollup.funcion_desconocida",
                detalle={"admitidas": sorted(FUNCIONES)},
            )
        if self.funcion != "cuenta" and not self.campo:
            raise ErrorValidacion(
                f"«{self.nombre}» agrega con «{self.funcion}» y no dice sobre qué campo",
                error_code="rollup.sin_campo",
            )


# Los rollups declarados, por objeto. Un registro y no una lista escrita a mano
# en el listado: los declara el servicio dueño del modelo hijo —el único que sabe
# qué significa «activo» para un contacto— y los consume el camino de lectura,
# que es común. Sin registro, cada listado tendría que conocer los agregados de
# su objeto y el que se olvidara saldría sin ellos y sin decirlo.
_DECLARADOS: dict[str, list["Rollup"]] = {}


def declarar(objeto: str, *rollups: "Rollup") -> None:
    """Declara los agregados de un objeto. Se llama al importar el servicio."""
    _DECLARADOS.setdefault(objeto, []).extend(rollups)


def declarados(objeto: str) -> list["Rollup"]:
    return list(_DECLARADOS.get(objeto) or [])


def calcular(db: Session, rollups: list[Rollup], padres: list[UUID]) -> dict[UUID, dict[str, Any]]:
    """Calcula todos los rollups de una lista de padres, de golpe.

    De golpe y no uno a uno: pedirlos por registro haría una consulta por fila y
    por rollup, que es el patrón N+1 con otro nombre. Con esto, un listado de
    doscientas cuentas con tres rollups son **tres** consultas.

    Un padre sin hijos no aparece en el resultado de la agregación, así que se
    rellena: `suma` y `cuenta` valen 0 —«ninguna línea» suma cero— y `maximo`,
    `minimo` y `media` valen `None`, porque el máximo de un conjunto vacío no es
    cero, no existe. Devolver cero ahí haría que un listado ordenado por «última
    actividad» pusiera arriba a quien no tiene ninguna.
    """
    if not padres or not rollups:
        return {}

    salida: dict[UUID, dict[str, Any]] = {p: {} for p in padres}
    for rollup in rollups:
        columna_padre = getattr(rollup.modelo_hijo, rollup.campo_padre)
        agregacion = FUNCIONES[rollup.funcion]
        objetivo = (
            columna_padre
            if rollup.funcion == "cuenta"
            else getattr(rollup.modelo_hijo, rollup.campo)
        )

        consulta = select(columna_padre, agregacion(objetivo)).where(columna_padre.in_(padres))
        if rollup.filtro is not None:
            consulta = consulta.where(rollup.filtro)
        consulta = consulta.group_by(columna_padre)

        try:
            filas = db.execute(consulta).all()
        except Exception as exc:  # noqa: BLE001 — un rollup roto no tumba el listado
            # Se deja el valor sin calcular y se dice en el log. Propagar
            # convertiría un rollup mal declarado en un listado que no se puede
            # abrir, y el listado es lo que la gente usa todo el día.
            logger.error("rollup.fallo", rollup=rollup.nombre, error=str(exc)[:200])
            continue

        por_padre = {fila[0]: fila[1] for fila in filas}
        vacio = 0 if rollup.funcion in ("suma", "cuenta") else None
        for padre in padres:
            salida[padre][rollup.nombre] = por_padre.get(padre, vacio)

    return salida


def aplicar(fila: dict[str, Any], calculados: dict[str, Any]) -> dict[str, Any]:
    """Añade los rollups al diccionario de una fila, sin pisar lo que ya hay.

    No se pisa a propósito: si un rollup se llama como una columna real, lo que
    manda es la columna. Al revés, un campo de configuración podría tapar un
    dato del registro y el síntoma sería que la ficha enseña un número que no
    está en la base.
    """
    return {**calculados, **fila}
