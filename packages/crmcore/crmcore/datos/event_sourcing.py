"""Event sourcing opcional en agregados críticos (CRM-00.05.04.06).

La pregunta que resuelve es una sola y llega siempre tarde: **«¿cómo estaba esto
el 3 de marzo?»**. El historial de campos dice qué cambió; no dice cómo era el
conjunto, y reconstruirlo a mano encadenando cambios sale mal en cuanto hay una
fusión o un borrado por medio.

Las decisiones:

**Opcional y por agregado.** Guardar todos los hechos de todos los objetos
multiplica la escritura y el almacenamiento por algo que nadie va a consultar de
la mayoría. Se enciende donde importa —la oportunidad, el contrato, el caso— y se
dice dónde está encendido.

**El estado vivo sigue siendo la verdad para trabajar.** Esto no sustituye la
tabla: reconstruir para pintar una ficha haría lento lo que se usa mil veces al
día para servir lo que se pregunta una vez al año. Son dos cosas con dos usos.

**Un hecho no se corrige: se compensa.** Si se pudiera editar, la reconstrucción
dejaría de ser una prueba y se convertiría en otra tabla que alguien puede tocar.
Para arreglar algo se añade el hecho contrario, y los dos quedan.

**Y una reconstrucción que no cuadra con el estado vivo se dice.** Es la única
forma de saber que alguien escribió en la tabla sin pasar por aquí — que es
exactamente lo que acaba pasando, y en silencio.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.db.base import Base
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Dónde se guarda el rastro completo. Se declara por agregado porque encenderlo
# en todo multiplica la escritura por algo que nadie va a consultar: de una nota
# no se pregunta cómo estaba en marzo.
_AGREGADOS: dict[str, str] = {}


def declarar_agregado(objeto: str, motivo: str) -> None:
    """Enciende el rastro completo para un tipo de objeto.

    El motivo es obligatorio: dentro de dos años, alguien mirará por qué esta
    tabla ocupa lo que ocupa, y «porque sí» no es una respuesta que permita
    apagarlo con tranquilidad.
    """
    if not motivo.strip():
        raise ErrorValidacion(
            "Encender el rastro completo de un agregado exige decir por qué: sin "
            "motivo, nadie sabrá después si se puede apagar.",
            error_code="event_sourcing.sin_motivo",
        )
    _AGREGADOS[objeto] = motivo


def agregados_declarados() -> dict[str, str]:
    return dict(_AGREGADOS)


class HechoAgregado(Base):
    """Un hecho que le pasó a un agregado, en orden y sin editar."""

    __tablename__ = "hechos_agregado"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    objeto: Mapped[str] = mapped_column(String(60), nullable=False)
    objeto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # El orden dentro del agregado. Es lo que permite reconstruir sin depender
    # del reloj: dos hechos del mismo milisegundo se ordenan igual siempre.
    secuencia: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    tipo: Mapped[str] = mapped_column(String(60), nullable=False)
    datos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # Un hecho que compensa a otro. No se edita nada: se añade el contrario, y
    # los dos quedan — si se pudiera editar, esto dejaría de ser una prueba.
    compensa_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    ocurrido_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "objeto", "objeto_id", "secuencia", name="uq_hecho_secuencia"
        ),
        Index("ix_hechos_agregado", "tenant_id", "objeto", "objeto_id", "secuencia"),
    )


def anotar(
    db: Session,
    *,
    tenant_id: UUID,
    objeto: str,
    objeto_id: UUID,
    tipo: str,
    datos: dict[str, Any],
    por: UUID | None = None,
    compensa_id: UUID | None = None,
) -> HechoAgregado:
    """Añade un hecho al final del rastro.

    Al final y con número de secuencia propio: ordenar por reloj falla con dos
    cambios del mismo milisegundo, y entonces la reconstrucción devuelve estados
    distintos según el día.
    """
    if objeto not in _AGREGADOS:
        raise ErrorValidacion(
            f"«{objeto}» no tiene el rastro completo encendido. Encenderlo para todo "
            "multiplica la escritura por algo que casi nunca se consulta.",
            error_code="event_sourcing.agregado_no_declarado",
            detalle={"declarados": sorted(_AGREGADOS)},
        )
    ultima = db.execute(
        select(func.coalesce(func.max(HechoAgregado.secuencia), 0)).where(
            HechoAgregado.tenant_id == tenant_id,
            HechoAgregado.objeto == objeto,
            HechoAgregado.objeto_id == objeto_id,
        )
    ).scalar_one()
    fila = HechoAgregado(
        tenant_id=tenant_id,
        objeto=objeto,
        objeto_id=objeto_id,
        secuencia=int(ultima or 0) + 1,
        tipo=tipo,
        datos=dict(datos or {}),
        por=por,
        compensa_id=compensa_id,
    )
    db.add(fila)
    db.flush()
    return fila


def compensar(
    db: Session,
    *,
    tenant_id: UUID,
    hecho_id: UUID,
    motivo: str,
    por: UUID | None = None,
) -> HechoAgregado:
    """Deshace un hecho **añadiendo el contrario**, sin borrar el original.

    Los dos quedan. Es lo que separa un rastro que sirve de prueba de una tabla
    más que alguien puede maquillar: si el error desapareciera, la reconstrucción
    de marzo saldría como si nunca se hubiera equivocado nadie.
    """
    if not motivo.strip():
        raise ErrorValidacion(
            "Compensar un hecho exige decir por qué", error_code="event_sourcing.sin_motivo"
        )
    original = db.get(HechoAgregado, hecho_id)
    if original is None or original.tenant_id != tenant_id:
        raise NoEncontrado("Ese hecho no existe", error_code="event_sourcing.no_encontrado")
    if original.compensa_id is not None:
        raise Conflicto(
            "Ese hecho ya es una compensación: compensar una compensación deja un "
            "rastro que nadie sabe leer. Añade el hecho que corresponda.",
            error_code="event_sourcing.doble_compensacion",
        )
    return anotar(
        db,
        tenant_id=tenant_id,
        objeto=original.objeto,
        objeto_id=original.objeto_id,
        tipo=f"{original.tipo}.compensado",
        datos={"motivo": motivo, "compensa": str(hecho_id), "original": original.datos},
        por=por,
        compensa_id=hecho_id,
    )


def reconstruir(
    db: Session,
    tenant_id: UUID,
    *,
    objeto: str,
    objeto_id: UUID,
    hasta: datetime | None = None,
) -> dict[str, Any]:
    """Cómo estaba este agregado en un momento dado.

    Es la pregunta que llega siempre tarde —«¿cómo estaba esto el 3 de marzo?»— y
    la que el historial de campos no contesta: dice qué cambió, no cómo era el
    conjunto.

    Los hechos compensados **se aplican y se anulan**, no se saltan: saltarlos
    daría el estado que habría habido si nadie se hubiera equivocado, que no es lo
    que pasó y no sirve para explicar nada.
    """
    consulta = select(HechoAgregado).where(
        HechoAgregado.tenant_id == tenant_id,
        HechoAgregado.objeto == objeto,
        HechoAgregado.objeto_id == objeto_id,
    )
    if hasta is not None:
        consulta = consulta.where(HechoAgregado.ocurrido_at <= hasta)

    hechos = list(db.execute(consulta.order_by(HechoAgregado.secuencia)).scalars().all())
    estado: dict[str, Any] = {}
    compensados = {h.compensa_id for h in hechos if h.compensa_id}

    for hecho in hechos:
        if hecho.compensa_id is not None:
            # Una compensación revierte lo que puso su original: se aplica lo
            # contrario en vez de borrarlo del recorrido.
            for campo in hecho.datos.get("original") or {}:
                estado.pop(campo, None)
            continue
        estado.update(hecho.datos)

    return {
        "objeto": objeto,
        "objeto_id": str(objeto_id),
        "hasta": hasta.isoformat() if hasta else None,
        "hechos": len(hechos),
        "estado": estado,
        "hechos_compensados": len(compensados),
        "porque": (
            "Los hechos compensados se aplican y se anulan, no se saltan: saltarlos "
            "daría el estado que habría habido si nadie se hubiera equivocado."
        ),
    }


def cuadra_con_lo_vivo(
    db: Session,
    tenant_id: UUID,
    *,
    objeto: str,
    objeto_id: UUID,
    estado_vivo: dict[str, Any],
    campos: list[str] | None = None,
) -> dict[str, Any]:
    """Compara la reconstrucción con la tabla viva.

    Es la comprobación que casi nadie hace y la única que detecta lo que de
    verdad pasa: **alguien escribió en la tabla sin pasar por aquí**. Un script
    de corrección, una migración, un arreglo a mano un viernes. A partir de ahí el
    rastro deja de ser una prueba y nadie se entera.
    """
    reconstruido = reconstruir(db, tenant_id, objeto=objeto, objeto_id=objeto_id)["estado"]
    a_comparar = campos or sorted(set(reconstruido) | set(estado_vivo))
    diferencias = [
        {
            "campo": campo,
            "reconstruido": reconstruido.get(campo),
            "vivo": estado_vivo.get(campo),
        }
        for campo in a_comparar
        if reconstruido.get(campo) != estado_vivo.get(campo)
    ]
    if diferencias:
        logger.warning(
            "event_sourcing.no_cuadra",
            objeto=objeto,
            objeto_id=str(objeto_id),
            diferencias=len(diferencias),
        )
    return {
        "cuadra": not diferencias,
        "diferencias": diferencias,
        "que_significa": (
            "El rastro explica el estado actual."
            if not diferencias
            else "Alguien ha escrito en la tabla sin pasar por el rastro: un script de "
            "corrección, una migración o un arreglo a mano. A partir de ahí la "
            "reconstrucción deja de ser una prueba."
        ),
    }
