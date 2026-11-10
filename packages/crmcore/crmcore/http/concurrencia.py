"""`If-Match` en toda escritura sobre un registro, no sólo en el PATCH genérico.

**Medido el 10-11-2026.** El control de concurrencia optimista
(CRM-00.02.01.09) sólo lo aplicaba la edición genérica de `listados.py`. El
borrado genérico no lo miraba, y ninguna ruta escrita a mano —el PATCH y el
DELETE de cuentas y contactos, las acciones sobre un registro— lo llamaba: un
cliente que mandaba `If-Match` con una versión vieja borraba o pisaba el cambio
de otro sin enterarse. Lo cazó el modo sin conexión, que encola el borrado con
su versión y esperaba un 409 que no llegaba.

Arreglarlo ruta a ruta deja fuera la siguiente que se escriba. Aquí se arregla
la familia: **el registro al que apunta una petición es el que lleva su
identificador en la ruta.** Si la petición trae `If-Match`, justo antes de
escribir se compara la versión de cada registro versionado que se modifica o se
borra y cuyo identificador va en la ruta. Lo demás que toque la petición —la
actividad que se registra al lado, el contador que sube— no se compara: el
cliente no leyó su versión.

Cada registro se compara **una sola vez por petición**: tras la primera
escritura su versión ya ha subido, y una segunda escritura en la misma ruta
daría un conflicto con el propio cambio.

Sin `If-Match` no cambia nada, como hasta ahora: exigirlo rompería a todo el
que integra sin mandarlo.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

from crmcore.http.etag import comprobar_if_match

METODOS_QUE_ESCRIBEN = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass
class _Peticion:
    if_match: str
    segmentos: frozenset[str]
    comprobados: set[str] = field(default_factory=set)


_actual: ContextVar[_Peticion | None] = ContextVar("crm_if_match", default=None)


def fijar(metodo: str, ruta: str, if_match: str) -> Token[_Peticion | None] | None:
    """Lo llama el middleware de contexto. Sin cabecera, no fija nada."""
    if not if_match or metodo.upper() not in METODOS_QUE_ESCRIBEN:
        return None
    segmentos = frozenset(s for s in ruta.split("/") if s)
    return _actual.set(_Peticion(if_match=if_match, segmentos=segmentos))


def soltar(token: Token[_Peticion | None] | None) -> None:
    if token is not None:
        _actual.reset(token)


def _versionado(objeto: Any) -> bool:
    from crmcore.db.base import VersionMixin

    return isinstance(objeto, VersionMixin) and not getattr(objeto, "VERSION_ES_DE_NEGOCIO", False)


@event.listens_for(Session, "before_flush")
def _comprobar_antes_de_escribir(session: Session, _contexto: Any, _instancias: Any) -> None:
    peticion = _actual.get()
    if peticion is None:
        return
    for objeto in [*session.dirty, *session.deleted]:
        if not _versionado(objeto):
            continue
        clave = str(getattr(objeto, "id", ""))
        if not clave or clave not in peticion.segmentos or clave in peticion.comprobados:
            continue
        if objeto in session.dirty and not session.is_modified(objeto):
            continue
        peticion.comprobados.add(clave)
        comprobar_if_match(objeto, peticion.if_match)
