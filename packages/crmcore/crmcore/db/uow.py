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
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from crmcore.events.catalogo import TipoEvento
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
        tipo: str | TipoEvento,
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
        # Contract testing en ejecución (CRM-00.03.01.03). Se comprueba AQUÍ y
        # no al publicar porque aquí todavía se está dentro de la transacción:
        # el error la deshace y no queda un cambio hecho con un evento que
        # nadie podrá interpretar. Comprobarlo en el relevo llegaría tarde.
        from crmcore.contratos import comprobar_emision
        from crmcore.events.catalogo import clave

        # Se admite la constante declarada además de la cadena, y se normaliza
        # ANTES de comprobar el contrato: con el objeto, la comprobación no
        # encontraba el tipo en el registro y daba por bueno cualquier `data`.
        tipo = clave(tipo)

        faltan = comprobar_emision(tipo, data or {})
        if faltan:
            from crmcore.config import get_settings

            aviso = (
                f"El evento «{tipo}» se emite sin {', '.join(faltan)}, que su "
                "contrato promete. Quien lo consume cuenta con esos campos y se "
                "quedará sin ellos sin saber por qué."
            )
            if get_settings().contratos_emision_estricta:
                raise ValueError(aviso)
            import logging

            logging.getLogger(__name__).error(aviso)

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


# La unidad de trabajo del entorno, si alguien de fuera ya abrió una y quiere que
# lo de dentro vaya EN LA MISMA TRANSACCIÓN.
#
# Lo usa la deduplicación del consumo: la marca de «este evento ya lo procesé»
# tiene que escribirse con el efecto o no escribirse. Si fuera antes, un fallo
# posterior dejaría el evento marcado sin haberlo procesado y el reintento lo
# descartaría — el hecho se perdería para siempre. Y si fuera después, dos
# réplicas pueden estar procesando el mismo mensaje a la vez: el bus reclama lo
# que lleva mucho sin confirmar, así que la segunda entrega llega mientras la
# primera sigue dentro, y las dos harían el efecto.
_ambiente: ContextVar[UnidadDeTrabajo | None] = ContextVar("uow_ambiente", default=None)


def compartir(uow: UnidadDeTrabajo) -> Any:
    """Hace que lo de dentro use ESTA transacción. Devuelve el testigo."""
    return _ambiente.set(uow)


def soltar(testigo: Any) -> None:
    """Deja de compartirla.

    Siempre en un `finally`: sin restaurar, la siguiente tarea de este mismo
    hilo seguiría escribiendo en una sesión ya cerrada.
    """
    _ambiente.reset(testigo)


@contextmanager
def unidad_de_trabajo(
    tenant_id: UUID | None = None, *, sistema: bool = False
) -> Iterator[UnidadDeTrabajo]:
    """Abre transacción, vuelca los eventos y hace commit. Rollback si falla.

    **Si hay una unidad de trabajo del entorno, se usa esa y no se abre otra.**
    Ni commit, ni cierre, ni despertar al relevo: manda quien la abrió, que es el
    único que sabe si el conjunto salió bien. Es lo que permite que la marca de
    deduplicación y el efecto del evento sean una sola transacción.
    """
    from crmcore.db.session import nueva_sesion

    compartida = _ambiente.get()
    if compartida is not None:
        yield compartida
        return

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
