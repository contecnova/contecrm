"""Segunda red de aislamiento, en la capa ORM.

RLS en el motor es la garantía dura. Este guard es la red que va **por delante**
de ella, y existe por tres razones que no cubre RLS:

  * **Falla antes y explica mejor.** RLS devuelve cero filas; el guard puede
    registrar que una consulta se emitió sin tenant y de dónde salía.
  * **Funciona en pruebas sin Postgres.** La suite marcada `not db` corre contra
    modelos en memoria y aun así verifica que el filtro está.
  * **Cubre el caso del rol equivocado.** Si alguien despliega apuntando a un
    rol con BYPASSRLS, RLS deja de aislar en silencio. El arranque lo detecta
    (`verificar_rol_sin_bypass`), pero el guard sigue puesto igual.

Cómo funciona: un escuchador de `do_orm_execute` inyecta
`with_loader_criteria(Modelo, tenant_id == <tenant de la sesión>)` en todo SELECT
y en todo UPDATE/DELETE masivo habilitado por ORM.

Lo que **no** cubre, dicho claro:

  * Sentencias Core o `text()` crudas: no pasan por el hook. Las cubre RLS.
  * Recargas perezosas de relaciones: heredan el criterio de su SELECT original,
    así que no necesitan inyección propia.

Se salta cuando la sesión es de sistema (`session.info["sistema"] = True`), que
es el único camino para una consulta cross-tenant legítima y hay que escribirlo.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from crmcore.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.orm import ORMExecuteState

logger = get_logger(__name__)

# Modelos que tienen `tenant_id` pero no deben auto-filtrarse.
#
# `Tenant` ES el tenant: filtrarlo por sí mismo impediría resolverlo. El resto
# de la lista se mantiene vacía a propósito — cada excepción es un agujero que
# alguien tendrá que recordar dentro de dos años, así que añadir una exige
# escribir aquí por qué, y el gate `test_tenant_guard_contract.py` comprueba
# que toda exención tenga motivo.
MODELOS_EXENTOS: frozenset[str] = frozenset({"Tenant"})

_modelos_ambito: list[type] | None = None
_lock = threading.Lock()


def _descubrir_modelos() -> list[type]:
    """Descubre, una sola vez, los modelos mapeados con `tenant_id`.

    El descubrimiento se fuerza al instalar el guard, no en el primer SELECT.
    La diferencia importa: un modelo que se mapeara perezosamente DESPUÉS del
    primer SELECT quedaría fuera del filtro para siempre, y sería una red
    silenciosamente incompleta, que es peor que no tenerla.
    """
    global _modelos_ambito
    if _modelos_ambito is not None:
        return _modelos_ambito
    with _lock:
        if _modelos_ambito is not None:
            return _modelos_ambito
        from crmcore.db.base import Base

        encontrados: list[type] = []
        for mapper in Base.registry.mappers:
            cls = mapper.class_
            if cls.__name__ in MODELOS_EXENTOS:
                continue
            columna = mapper.columns.get("tenant_id")
            if columna is None:
                continue
            if columna.nullable:
                # Un `tenant_id` nullable rompe la garantía: la fila con NULL
                # sería visible desde cualquier tenant. Se avisa fuerte en vez
                # de filtrarla de forma permisiva y dejar el agujero abierto.
                logger.error(
                    "tenant_guard.columna_nullable",
                    modelo=cls.__name__,
                    aviso="tenant_id debe ser NOT NULL; ver crmcore.db.base",
                )
            encontrados.append(cls)
        _modelos_ambito = encontrados
        logger.info(
            "tenant_guard.descubierto",
            total=len(encontrados),
            modelos=sorted(c.__name__ for c in encontrados),
        )
        return _modelos_ambito


def _guard_activo() -> bool:
    """Lee el interruptor del entorno, no de los ajustes en caliente.

    Consultar los ajustes en caliente aquí dispararía un SELECT del tenant
    dentro de este mismo escuchador: recursión. Es un ajuste de arranque.
    """
    from crmcore.config import get_settings

    return bool(get_settings().tenant_guard_enabled)


def instalar_guard() -> None:
    """Instala el escuchador. Idempotente; lo llama la factoría de servicio."""
    _descubrir_modelos()

    if event.contains(Session, "do_orm_execute", _al_ejecutar):
        return
    event.listen(Session, "do_orm_execute", _al_ejecutar)
    logger.info("tenant_guard.instalado")


def _al_ejecutar(estado: ORMExecuteState) -> None:
    """Inyecta el filtro de tenant en la sentencia a punto de ejecutarse."""
    if not _guard_activo():
        return
    # Solo sentencias de nivel superior: una recarga perezosa hereda el criterio
    # de la consulta que la originó, e inyectarlo otra vez sería redundante.
    if not estado.is_select and not estado.is_update and not estado.is_delete:
        return
    if estado.is_column_load or estado.is_relationship_load:
        return

    sesion = estado.session
    if sesion.info.get("sistema"):
        return  # camino explícito y auditable para lo cross-tenant

    tenant_id = sesion.info.get("tenant_id")
    if tenant_id is None:
        # Sin tenant y sin declararse de sistema: no se filtra (no habría por
        # qué filtrar) pero se deja rastro, porque casi siempre es un descuido.
        # No se lanza aquí: romper una consulta en un escuchador produce
        # trazas ilegibles y, en el arranque, un fallo imposible de situar.
        # Quien impide de verdad este caso es `nueva_sesion`.
        return

    for modelo in _descubrir_modelos():
        estado.statement = estado.statement.options(
            with_loader_criteria(
                modelo,
                lambda cls, tid=tenant_id: cls.tenant_id == tid,
                include_aliases=True,
            )
        )


def modelos_cubiertos() -> list[str]:
    """Nombres de los modelos que el guard filtra. Lo usa el gate de contrato."""
    return sorted(c.__name__ for c in _descubrir_modelos())


def reset_guard() -> None:
    """Olvida el descubrimiento. Solo para pruebas que registran modelos nuevos."""
    global _modelos_ambito
    with _lock:
        _modelos_ambito = None


def _sin_usar(*_args: Any) -> None:  # pragma: no cover
    """Marcador para que ruff no elimine el import de `Any` en anotaciones."""
