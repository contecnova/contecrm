"""Qué depende de un registro, antes de dejar borrarlo (CRM-00.06.02.05).

    from crmcore.datos import integridad

    integridad.exigir_sin_dependencias(db, fila, objeto="lista_precio")

Borrar algo que otros registros apuntan deja el sistema mintiendo: una lista de
precios borrada con veinte ofertas colgando no desaparece de las ofertas —sigue
ahí, como un identificador que ya no resuelve—, y lo que se rompe no se nota al
borrar sino tres semanas después, al abrir una oferta que ya no sabe a cuánto
vendía.

**Se calcula del modelo, no de una lista escrita a mano.** Las dependencias son
las claves ajenas que SQLAlchemy ya conoce: cualquier tabla nueva que apunte a
esta queda protegida el día que se crea, sin que nadie se acuerde de apuntarla
aquí. Una lista a mano protege lo que alguien recordó, que es otra forma de no
proteger nada.

**Solo cuentan las filas vivas.** Lo que está en la papelera no impide borrar:
si impidiera, un registro quedaría bloqueado para siempre por algo que ya nadie
ve y que nadie va a ir a purgar.

**Y no se propone borrar en cascada.** Un botón que borra el registro y lo que
cuelga de él es la forma más rápida de perder datos sin enterarse: lo que se
ofrece es archivar, que deja de usarse y no rompe nada de lo que ya pasó.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from crmcore.errors import Conflicto

# Campos con los que un registro se puede retirar sin borrarlo, en orden de
# preferencia. `activo` es el más claro; `estado` solo vale si el modelo admite
# un valor de retirada, y eso lo dice cada servicio con `ESTADOS_ARCHIVADO`.
# En femenino también: media base dice `activo` y la otra media `activa`
# —una regla está activa y un canal está activo—, y mirando solo uno de los dos
# la mitad de los modelos parecerían no poder archivarse.
CAMPOS_ACTIVO = ("activo", "activa")
CAMPO_ESTADO = "estado"
ESTADOS_ARCHIVADO = ("archivado", "archivada", "inactivo", "inactiva", "cerrado", "cerrada")


@dataclass(frozen=True)
class Dependencia:
    """Cuántos registros vivos de otra tabla apuntan a este."""

    tabla: str
    columna: str
    cuantos: int


def _nombres_de(modelo: type) -> set[str]:
    """Con qué nombres de objeto se conoce a este modelo.

    Salen del registro de la papelera, que es donde cada ficha declara el suyo
    al montarse. Hacen falta porque **casi ninguna referencia de este sistema es
    una clave ajena**: los servicios tienen esquemas separados, así que una
    oportunidad apunta a su cuenta con un `cuenta_id` suelto y no puede haber
    `FOREIGN KEY` entre ellos. Mirando solo las claves ajenas, la protección
    habría cubierto cinco relaciones de todo el producto.
    """
    from crmcore.datos.papelera import objetos_registrados

    return {nombre for nombre, clase in objetos_registrados().items() if clase is modelo}


def _es_composicion(columna: Any) -> bool:
    """¿La columna dice que esto es *parte de* aquello, y no una referencia?

    `ON DELETE CASCADE` es la forma en que el modelo lo declara: las líneas de
    una oferta son parte de la oferta. Si contaran como dependencia, una oferta
    con líneas no se podría borrar nunca — y una oferta sin líneas no existe.
    """
    return any((ajena.ondelete or "").upper() == "CASCADE" for ajena in columna.foreign_keys)


def _tablas_que_apuntan(modelo: type) -> list[tuple[type, Any]]:
    """Modelos que apuntan a `modelo`, y por qué columna.

    Por las dos vías, porque el sistema usa las dos: la clave ajena declarada
    cuando las dos tablas viven en el mismo esquema, y la columna `<objeto>_id`
    cuando no —que es el caso normal entre servicios—.
    """
    from crmcore.db.base import Base

    tabla = getattr(modelo, "__table__", None)
    if tabla is None:
        return []
    por_convencion = {f"{nombre}_id" for nombre in _nombres_de(modelo)}
    salida: list[tuple[type, Any]] = []
    for mapeador in Base.registry.mappers:
        otro = mapeador.class_
        suya = getattr(otro, "__table__", None)
        if suya is None or suya is tabla:
            continue
        for columna in suya.columns:
            if _es_composicion(columna):
                continue
            apunta = any(ajena.column.table is tabla for ajena in columna.foreign_keys)
            if apunta or columna.key in por_convencion:
                salida.append((otro, columna))
    return salida


def quien_depende(db: Session, fila: Any) -> list[Dependencia]:
    """Qué hay vivo apuntando a este registro.

    Cuenta por tabla y no devuelve las filas: para decidir si se puede borrar
    basta con saber cuántas hay y de qué, y traerlas todas podría ser traerse
    media base para contestar a un botón.
    """
    modelo = type(fila)
    identificador = getattr(fila, "id", None)
    if identificador is None:
        return []
    salida: list[Dependencia] = []
    for otro, columna in _tablas_que_apuntan(modelo):
        consulta = select(func.count()).select_from(otro).where(columna == identificador)
        # Lo que está en la papelera no bloquea: si bloqueara, un registro
        # quedaría preso de algo que ya nadie ve.
        if hasattr(otro, "deleted_at"):
            consulta = consulta.where(otro.deleted_at.is_(None))
        cuantos = int(db.execute(consulta).scalar_one() or 0)
        if cuantos:
            salida.append(
                Dependencia(tabla=otro.__table__.name, columna=columna.key, cuantos=cuantos)
            )
    return salida


def se_puede_archivar(modelo: type) -> str:
    """Con qué campo se retira un registro sin borrarlo. Vacío si no se puede."""
    for campo in CAMPOS_ACTIVO:
        if hasattr(modelo, campo):
            return campo
    if hasattr(modelo, CAMPO_ESTADO):
        return CAMPO_ESTADO
    return ""


def archivar(fila: Any) -> str:
    """Retira el registro sin borrarlo. Devuelve el valor que le ha quedado.

    Es lo que se ofrece cuando algo no se puede borrar: deja de usarse de aquí
    en adelante y no toca nada de lo que ya pasó.
    """
    campo = se_puede_archivar(type(fila))
    if campo in CAMPOS_ACTIVO:
        setattr(fila, campo, False)
        return f"{campo}=false"
    if campo == CAMPO_ESTADO:
        setattr(fila, CAMPO_ESTADO, ESTADOS_ARCHIVADO[0])
        return f"estado={ESTADOS_ARCHIVADO[0]}"
    raise Conflicto(
        "Este registro no se puede archivar: no tiene con qué marcarse como " "retirado.",
        error_code="integridad.no_archivable",
    )


def exigir_sin_dependencias(db: Session, fila: Any, *, objeto: str) -> None:
    """Se niega a borrar lo que otros registros están usando.

    El mensaje dice **qué** depende y **cuántos**: «no se puede borrar» a secas
    obliga a adivinar, y quien adivina acaba borrando las dependencias una a una
    hasta que le deja — que es el borrado en cascada, hecho a mano y sin
    enterarse.
    """
    dependencias = quien_depende(db, fila)
    if not dependencias:
        return
    campo = se_puede_archivar(type(fila))
    detalle: dict[str, Any] = {
        "objeto": objeto,
        "lo_usan": [
            {"tabla": d.tabla, "campo": d.columna, "cuantos": d.cuantos} for d in dependencias
        ],
        "se_puede_archivar": bool(campo),
    }
    resumen = ", ".join(f"{d.cuantos} en {d.tabla}" for d in dependencias)
    salida = (
        " Se puede archivar: deja de ofrecerse de aquí en adelante y no toca " "lo que ya pasó."
        if campo
        else ""
    )
    raise Conflicto(
        f"No se puede borrar: hay registros que lo usan ({resumen}). Borrarlo "
        f"los dejaría apuntando a algo que ya no existe.{salida}",
        error_code="integridad.referenciado",
        detalle=detalle,
    )
