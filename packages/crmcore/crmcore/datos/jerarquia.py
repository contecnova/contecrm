"""Reglas de los árboles: impedir ciclos.

Vive en el núcleo y no en un servicio porque la usan varios —`party` para la
jerarquía de cuentas, `metadata` para declarar la semántica de las relaciones
jerárquicas— y un servicio no puede importar de otro: el gate de arquitectura lo
impide, y con razón, porque ese import ata sus despliegues.

Tenerla escrita dos veces garantizaría que un día una de las dos se corrigiera y
la otra no.
"""

from __future__ import annotations

from typing import Callable
from uuid import UUID

from crmcore.errors import Conflicto


def comprobar_ciclo(
    padre_de: Callable[[UUID], UUID | None], *, hijo: UUID, nuevo_padre: UUID
) -> None:
    """Impide que un enlace jerárquico cierre un ciclo.

    Recibe **cómo resolver el padre** en vez del árbol entero: el árbol vive en
    el servicio dueño del objeto, y cargarlo completo para comprobar un enlace
    sería traer miles de filas para mirar tres.

    Un ciclo hace que consolidar importes o calcular visibilidad no termine
    nunca, y el síntoma es una petición colgada, no un error claro — que es
    exactamente el fallo más caro de diagnosticar.

    El conjunto de visitados no es solo una optimización: si el árbol **ya**
    tuviera un ciclo —metido por una carga que se saltó esta comprobación—,
    subir por los padres no terminaría nunca y este método colgaría en vez de
    informar.
    """
    if hijo == nuevo_padre:
        raise Conflicto(
            "Un registro no puede colgar de sí mismo",
            error_code="jerarquia.ciclo",
        )
    actual: UUID | None = nuevo_padre
    visitados: set[UUID] = set()
    while actual is not None and actual not in visitados:
        if actual == hijo:
            raise Conflicto(
                "Ese enlace crearía un ciclo en la jerarquía",
                error_code="jerarquia.ciclo",
            )
        visitados.add(actual)
        actual = padre_de(actual)
