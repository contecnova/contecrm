"""Concurrencia optimista con ETag e `If-Match` (CRM-00.02.01.09).

Sin esto, dos usuarios que abren la misma oportunidad y guardan con un minuto de
diferencia producen el clásico «actualización perdida»: el segundo pisa el
cambio del primero y nadie se entera. Es el fallo que más veces acaba en «el
sistema ha borrado lo que escribí».

El ETag es el contador `version` de la fila, que SQLAlchemy incrementa en cada
escritura. El cliente lee (`ETag: "7"`), escribe con `If-Match: "7"`, y si otro
escribió entretanto la fila ya va por 8: se responde 412 y el cliente relee.

`If-Match` **no se exige por defecto**, y es una decisión consciente: exigirlo
rompería a todo integrador que no lo mande y convertiría la protección en una
barrera de entrada. Se puede exigir por recurso donde la escritura concurrente
sea probable y cara (importe de una oportunidad, estado de un caso).
"""

from __future__ import annotations

from typing import Any

from crmcore.errors import ConflictoDeVersion, ErrorValidacion


def etag_de(objeto: Any) -> str:
    """ETag de una entidad con `version`. Débil (`W/`) a propósito.

    Débil porque identifica la versión lógica del recurso, no el byte exacto de
    la representación: dos peticiones con distinta proyección de campos son la
    misma versión del registro.
    """
    version = getattr(objeto, "version", None)
    if version is None:
        raise ErrorValidacion(
            "El recurso no admite control de versión",
            error_code="etag.sin_version",
        )
    return f'W/"{version}"'


def _normalizar(valor: str) -> str:
    return valor.strip().removeprefix("W/").strip('"')


def comprobar_if_match(objeto: Any, if_match: str | None, *, obligatorio: bool = False) -> None:
    """Valida `If-Match` contra la versión actual. Lanza 409 si no coincide.

    `*` significa «solo si existe», que es lo que quiere quien actualiza algo
    que acaba de leer sin haberse quedado la versión.
    """
    if not if_match:
        if obligatorio:
            raise ErrorValidacion(
                "Esta operación exige la cabecera If-Match con el ETag leído",
                error_code="etag.if_match_requerido",
            )
        return

    if if_match.strip() == "*":
        return

    actual = str(getattr(objeto, "version", ""))
    # Un `If-Match` puede traer varias versiones separadas por comas: vale con
    # que una coincida.
    esperadas = {_normalizar(v) for v in if_match.split(",")}
    if actual not in esperadas:
        raise ConflictoDeVersion(
            "El registro ha cambiado desde que lo leíste. Vuelve a leerlo, "
            "reconcilia los cambios y repite la operación.",
            error_code="etag.version_desfasada",
            detalle={"version_actual": actual, "version_enviada": sorted(esperadas)},
        )


def comprobar_if_none_match(objeto: Any, if_none_match: str | None) -> bool:
    """`True` si el cliente ya tiene la versión buena y toca responder 304.

    Ahorra el cuerpo entero en las lecturas repetidas, que en una vista 360 con
    cincuenta campos y relaciones no es poca cosa.
    """
    if not if_none_match:
        return False
    if if_none_match.strip() == "*":
        return True
    actual = str(getattr(objeto, "version", ""))
    return actual in {_normalizar(v) for v in if_none_match.split(",")}
