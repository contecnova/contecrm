"""A qué puede apuntar una referencia, comprobado donde se escribe
(CRM-00.04.01.03).

Una relación polimórfica dice que una actividad puede colgar de una cuenta, de
un contacto o de una oportunidad. Lo que **no** puede es colgar de cualquier
cosa: sin esta comprobación, una actividad acaba apuntando a un tipo que nadie
previó, y el día que alguien recorra esas referencias se encontrará con un
identificador que no resuelve a nada. No da error al escribir —el valor cabe— y
no se nota hasta que alguien abre la ficha que dependía.

**Esta regla vive en el núcleo y no en el servicio que define las relaciones.**
La definía `metadata`, que es quien las declara, y por eso no la llamaba nadie:
quien escribe los valores son los otros doce servicios, y ninguno puede leer el
esquema de metadata. Una regla que vive donde se declara y no donde se aplica es
una regla apagada.

Las relaciones llegan a cada servicio **replicadas con el esquema**, por el mismo
camino que los campos propios del tenant: un diccionario por relación, con lo
justo para decidir — cómo se llama, de qué tipo es y a qué admite apuntar.
"""

from __future__ import annotations

from typing import Any

from crmcore.errors import ErrorValidacion


def destinos_admitidos(relacion: dict[str, Any]) -> list[str]:
    """A qué objetos admite apuntar esta relación.

    Una polimórfica enumera los suyos; una normal tiene uno solo. La lista vacía
    significa **sin acotar**, y eso es distinto de «no admite ninguno»: una
    relación que no declara destino acepta cualquiera a propósito, porque
    obligar a enumerarlos antes de saberlos haría que nadie declarara ninguna.
    """
    if str(relacion.get("tipo") or "") == "polimorfica":
        return [str(d) for d in (relacion.get("destinos") or []) if d]
    destino = str(relacion.get("destino") or "")
    return [destino] if destino else []


def validar_destino(relacion: dict[str, Any], objeto_destino: str) -> None:
    """Comprueba que el tipo de destino es uno de los admitidos.

    Sin acotar, pasa: ver arriba por qué eso es una decisión y no un hueco.
    """
    admitidos = destinos_admitidos(relacion)
    if not admitidos or objeto_destino in admitidos:
        return

    nombre = str(relacion.get("nombre") or "la relación")
    if str(relacion.get("tipo") or "") == "polimorfica":
        raise ErrorValidacion(
            f"«{objeto_destino}» no está entre los destinos admitidos de «{nombre}»",
            error_code="metadata.destino_no_admitido",
            detalle={"admitidos": admitidos},
        )
    raise ErrorValidacion(
        f"La relación «{nombre}» apunta a «{admitidos[0]}», no a «{objeto_destino}»",
        error_code="metadata.destino_no_admitido",
        detalle={"admitidos": admitidos},
    )


def relacion_de_campo(
    relaciones: list[dict[str, Any]], definicion: dict[str, Any]
) -> dict[str, Any] | None:
    """La relación que gobierna este campo de referencia, si la hay.

    Se busca por el nombre que el campo declara en sus restricciones, y **no se
    adivina por parecido**: dos relaciones hacia el mismo objeto son dos cosas
    distintas —«cuenta que lo paga» y «cuenta que lo usa»— y elegir la que
    coincida de nombre con el campo acertaría casi siempre, que es la peor clase
    de casi.
    """
    clave = str((definicion.get("restricciones") or {}).get("relacion") or "")
    if not clave:
        return None
    for relacion in relaciones:
        if str(relacion.get("nombre") or "") == clave:
            return relacion
    return None
