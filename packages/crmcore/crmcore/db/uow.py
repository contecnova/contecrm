"""Unidad de trabajo: una transacción, un evento, una garantía.

El problema que resuelve es el clásico de los sistemas con bus: cerrar una
oportunidad son dos escrituras en sistemas distintos —la fila en Postgres y el
mensaje en el bus— y no hay forma de hacerlas atómicas. Si el proceso muere
entre una y otra, la oportunidad queda ganada y nadie se entera: ni el
orquestador que debía crear el pedido, ni la automatización que avisa al KAM,
ni el ERP.

Con la unidad de trabajo, el evento se guarda en la tabla de salida DENTRO de la
misma transacción que el cambio. O están los dos o no está ninguno. Publicarlo
puede fallar y reintentarse, porque ya no se puede perder.

    with unidad_de_trabajo(tenant_id) as uow:
        oportunidad.estado = "ganada"
        uow.db.add(oportunidad)
        uow.emitir("opportunity.won", subject=("opportunity", oportunidad.id),
                   data={"importe": str(oportunidad.importe)})

El precio es entrega **at-least-once**, y por eso todo consumidor deduplica por
`dedup_key` (`crmcore.bus.inbox`).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from crmcore.logging import get_logger

logger = get_logger(__name__)


@dataclass
class UnidadDeTrabajo:
    """Transacción con los eventos que produce."""

    db: Session
    tenant_id: UUID | None
    _pendientes: list[dict[str, Any]] = field(default_factory=list)

    def emitir(
        self,
        tipo: str,
        *,
        subject: tuple[str, Any],
        data: dict[str, Any] | None = None,
        dedup_key: str | None = None,
        version: int = 1,
    ) -> None:
        """Encola un evento de dominio para publicarlo tras el commit.

        No publica aquí: lo escribe en la tabla de salida al cerrar la
        transacción. Llamarlo dentro del bloque es lo que da la garantía; si se
        llamara después del commit, volvería el estado imposible que esto evita.
        """
        self._pendientes.append(
            {
                "tipo": tipo,
                "subject_tipo": subject[0],
                "subject_id": subject[1],
                "data": data or {},
                "dedup_key": dedup_key,
                "version": version,
            }
        )

    def volcar(self) -> None:
        """Escribe los eventos pendientes sin cerrar la transacción.

        La usa quien controla su propio commit y no puede delegar en el gestor
        de contexto: el ejecutor de un trabajo asíncrono, que hace un commit por
        tanda. Sin esto, los eventos de una importación de cincuenta mil filas
        se quedarían acumulados en memoria hasta el final —o se perderían con el
        proceso—, y las automatizaciones que dependen de ellos no se dispararían.
        """
        self._volcar_eventos()
        self._pendientes.clear()

    def _volcar_eventos(self) -> None:
        """Escribe los eventos pendientes en la tabla de salida."""
        if not self._pendientes:
            return
        from crmcore.bus.outbox import encolar

        for ev in self._pendientes:
            encolar(self.db, tenant_id=self.tenant_id, **ev)


@contextmanager
def unidad_de_trabajo(
    tenant_id: UUID | None = None, *, sistema: bool = False
) -> Iterator[UnidadDeTrabajo]:
    """Abre transacción, vuelca los eventos y hace commit. Rollback si falla."""
    from crmcore.db.session import nueva_sesion

    db = nueva_sesion(tenant_id, sistema=sistema)
    uow = UnidadDeTrabajo(db=db, tenant_id=db.info.get("tenant_id"))
    try:
        yield uow
        uow._volcar_eventos()
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    # Despertar al relevo DESPUÉS del commit: publica antes en vez de esperar al
    # siguiente sondeo. Si falla, no pasa nada — el relevo lo cogerá igual en su
    # vuelta. Por eso va fuera del try y no puede afectar al resultado.
    if uow._pendientes:
        try:
            from crmcore.bus.outbox import despertar_relevo

            despertar_relevo()
        except Exception as exc:  # noqa: BLE001 — el relevo lo publicará en su siguiente vuelta
            logger.debug("outbox.despertar_fallido", error=str(exc)[:160])
