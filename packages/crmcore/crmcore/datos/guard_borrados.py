"""Lo que está en la papelera no sale en los listados. Por construcción.

El borrado lógico solo funciona si **nadie se olvida de filtrarlo**, y en este
sistema hay más de cuarenta sitios que consultan modelos con papelera. Cuarenta
sitios donde hay que acordarse de escribir `deleted_at IS NULL`, y el día que
alguien no se acuerde no falla nada: sale una fila de más. Una plantilla
borrada que se sigue ofreciendo, un canal retirado que sigue enviando, un
contacto en la papelera que vuelve a aparecer en un segmento.

Así que se filtra en un solo sitio, igual que el aislamiento por tenant y por
la misma razón: un escuchador de `do_orm_execute` inyecta
`with_loader_criteria(Modelo, deleted_at IS NULL)` en toda consulta de un modelo
con papelera.

**Cómo se ve lo borrado cuando hace falta.** Hay tres cosas que tienen que
verlo —restaurar, purgar y el archivado— y se declaran con `con_borrados(db)`.
Es explícito a propósito: que mirar la papelera exija escribirlo es lo que
impide que se mire por descuido.

Lo que no cubre, dicho claro: sentencias Core o `text()` crudas, que no pasan
por el hook. Ahí sigue haciendo falta el `WHERE` a mano.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from crmcore.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.orm import ORMExecuteState

logger = get_logger(__name__)

_modelos: list[type] | None = None
_lock = threading.Lock()


def _con_papelera() -> list[type]:
    """Los modelos mapeados que tienen `deleted_at`. Se descubre una vez."""
    global _modelos
    if _modelos is not None:
        return _modelos
    with _lock:
        if _modelos is not None:
            return _modelos
        from crmcore.db.base import Base

        encontrados: list[type] = []
        for mapeador in Base.registry.mappers:
            clase = mapeador.class_
            if "deleted_at" in mapeador.columns:
                encontrados.append(clase)
        _modelos = encontrados
        logger.info(
            "guard_borrados.descubierto",
            total=len(encontrados),
            modelos=sorted(c.__name__ for c in encontrados),
        )
        return _modelos


def olvidar_modelos() -> None:
    """Vacía el descubrimiento. Solo para pruebas que registran modelos nuevos."""
    global _modelos
    _modelos = None


@contextmanager
def con_borrados(db: Session) -> Iterator[Session]:
    """Dentro de este bloque, las consultas también ven lo que está borrado.

    Lo usan restaurar, purgar y el archivado, que es todo lo que tiene motivo
    para mirar la papelera. Cualquier otro uso hay que justificarlo: enseñar un
    registro borrado donde no se espera es exactamente el fallo que este guard
    existe para no tener.
    """
    previo = db.info.get("ver_borrados")
    db.info["ver_borrados"] = True
    try:
        yield db
    finally:
        if previo is None:
            db.info.pop("ver_borrados", None)
        else:
            db.info["ver_borrados"] = previo


def instalar_guard_borrados() -> None:
    """Instala el escuchador. Idempotente; lo llama la factoría de servicio."""
    if event.contains(Session, "do_orm_execute", _al_ejecutar):
        return
    event.listen(Session, "do_orm_execute", _al_ejecutar)
    logger.info("guard_borrados.instalado")


def _al_ejecutar(estado: ORMExecuteState) -> None:
    """Inyecta `deleted_at IS NULL` en la sentencia a punto de ejecutarse."""
    # Solo lecturas. Un UPDATE tiene que poder tocar lo borrado —restaurar lo
    # hace— y un DELETE masivo es cosa de la purga.
    if not estado.is_select or estado.is_column_load or estado.is_relationship_load:
        return
    if estado.session.info.get("ver_borrados"):
        return

    for modelo in _con_papelera():
        estado.statement = estado.statement.options(
            with_loader_criteria(
                modelo,
                # Sin variables de cierre: el criterio es constante, así que
                # cachearlo compilado no puede filtrar valores entre consultas
                # —que es el fallo que sí acecha en el guard de tenant—.
                lambda cls: cls.deleted_at.is_(None),
                include_aliases=True,
            )
        )


def modelos_cubiertos() -> list[str]:
    """Nombres de los modelos con papelera. Lo usa el gate de contrato."""
    return sorted(c.__name__ for c in _con_papelera())


__all__: list[str] = [
    "con_borrados",
    "instalar_guard_borrados",
    "modelos_cubiertos",
    "olvidar_modelos",
]
