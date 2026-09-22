"""Compartimentos estancos dentro de un mismo tenant (CRM-03.04.01.03).

El aislamiento entre tenants lo resuelve la base de datos con RLS y nadie puede
saltárselo desde el código. Pero hay un aislamiento más fino que la RLS no cubre
y que hace falta en cuanto entra gente de fuera en el CRM del cliente: **dos
partners del mismo fabricante no pueden verse entre sí**. Comparten tenant,
comparten tablas y comparten hasta cuentas —el mismo cliente final puede estar
trabajado por dos—, y sin embargo lo que uno registra no puede existir para el
otro.

Tres decisiones, y las tres son lo contrario de lo cómodo:

**El compartimento vive en el principal, no en el parámetro de la petición.** Si
el filtro saliera de un `partner_id` que manda el cliente, colarse sería cambiar
un número en la URL. Sale del token: quien entra por el portal de partner lleva
su compartimento dentro y no hay nada que pueda mandar para cambiarlo.

**Un registro sin compartimento no se ve desde dentro de uno.** Es la parte que
se olvida: el filtro natural (`columna == mi_partner`) ya lo hace, pero la
tentación es escribir `columna == mio OR columna IS NULL` para que el partner vea
«lo general». Lo general es la cartera directa del fabricante, que es justo lo que
no puede ver. Aquí, ante la duda, no se enseña.

**Cruzar el compartimento devuelve 404, no 403.** Un 403 confirma que ese
registro existe. Para un competidor que también es partner, la existencia *es* la
información: saber que hay una oportunidad registrada en ese cliente ya le dice
que vaya a por ella. Es el mismo criterio que se usa entre tenants.

El mecanismo es **genérico**: el compartimento se llama `partner` porque ese es
el primer uso, pero nada de aquí sabe qué es un partner. Sirve igual para una
franquicia, un concesionario o un despacho colaborador.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import Select, false

from crmcore.logging import get_logger

logger = get_logger(__name__)

# Clave bajo la que viaja el compartimento en los atributos del principal. Un
# atributo y no un campo propio de `Principal` porque el mecanismo es abierto: el
# día que haga falta un segundo eje (partner *y* delegación) se añade otra clave
# sin tocar la identidad.
ATRIBUTO = "compartimento"


@dataclass(frozen=True, slots=True)
class Compartimento:
    """A qué compartimento pertenece quien pregunta."""

    tipo: str
    id: UUID

    def __str__(self) -> str:  # pragma: no cover - solo para trazas
        return f"{self.tipo}:{self.id}"


def compartimento_de(principal: Any) -> Compartimento | None:
    """El compartimento del principal, o `None` si no está acotado.

    Devolver `None` significa «ve todo lo que le permitan sus permisos»: es el
    caso del empleado. La ausencia de compartimento **no** es un compartimento
    vacío, y por eso no se representa con uno: confundir «sin acotar» con «acotado
    a nada» dejaría a los empleados sin ver nada el día que alguien escriba el
    filtro al revés.
    """
    crudo = getattr(principal, "atributos", {}).get(ATRIBUTO)
    if not crudo:
        return None
    try:
        return Compartimento(tipo=str(crudo["tipo"]), id=UUID(str(crudo["id"])))
    except (KeyError, TypeError, ValueError):
        # Un compartimento ilegible es un token manipulado o un despliegue a
        # medias. En los dos casos se acota a nada: seguir sin filtrar sería
        # abrirlo todo justo cuando algo va mal.
        logger.warning("estanco.compartimento_ilegible", valor=str(crudo))
        return Compartimento(tipo="desconocido", id=UUID(int=0))


def atributos_de(tipo: str, id_: UUID) -> dict[str, Any]:
    """Cómo se escribe un compartimento en los atributos de un principal.

    Existe para que quien emite el token no tenga que conocer la forma interna:
    si la escribe a mano y se equivoca en una letra, el principal sale **sin**
    compartimento y ve el tenant entero.
    """
    return {ATRIBUTO: {"tipo": tipo, "id": str(id_)}}


def aplicar_estanco(consulta: Select, columna: Any, *, principal: Any, tipo: str) -> Select:
    """Acota una consulta al compartimento de quien pregunta.

    Se llama **siempre**, tenga o no compartimento el principal: un listado que
    solo filtra «cuando hay partner» acaba teniendo una rama sin filtrar que
    nadie prueba.
    """
    comp = compartimento_de(principal)
    if comp is None:
        return consulta
    if comp.tipo != tipo:
        # Tiene compartimento, pero de otro eje. No se le enseña nada de este:
        # ignorarlo dejaría pasar a un partner por un listado de franquicias.
        logger.info("estanco.tipo_distinto", esperado=tipo, recibido=comp.tipo)
        return consulta.where(false())
    return consulta.where(columna == comp.id)


def exigir_propio(fila: Any, *, atributo: str, principal: Any, tipo: str) -> None:
    """Corta el acceso a un registro de otro compartimento, como si no existiera.

    `NoEncontrado` y no `Prohibido`: un 403 confirma que ese registro existe, y
    entre competidores que comparten fabricante la existencia ya es la
    información.
    """
    comp = compartimento_de(principal)
    if comp is None:
        return
    from crmcore.errors import NoEncontrado

    valor = getattr(fila, atributo, None)
    if comp.tipo != tipo or valor is None or UUID(str(valor)) != comp.id:
        logger.info(
            "estanco.acceso_cruzado",
            tipo=tipo,
            compartimento=str(comp),
            registro=str(getattr(fila, "id", "")),
        )
        raise NoEncontrado("No encontrado", error_code="estanco.no_encontrado")


def dueno_forzado(principal: Any, *, tipo: str, pedido: UUID | None) -> UUID | None:
    """Con qué compartimento se guarda lo que se crea.

    Quien está dentro de un compartimento **no puede elegir**: lo que registre es
    suyo aunque mande otro identificador. Aceptar el que viene en el cuerpo de la
    petición permitiría registrar una oportunidad a nombre de otro partner —y
    robársela, porque el registro es lo que da la protección.
    """
    comp = compartimento_de(principal)
    if comp is None:
        return pedido
    if comp.tipo != tipo:
        from crmcore.errors import Prohibido

        raise Prohibido(
            "Esta operación no corresponde a tu ámbito",
            error_code="estanco.ambito_distinto",
        )
    return comp.id
