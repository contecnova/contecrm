"""Bloqueo de tratamiento sin borrado: el derecho de limitación
(CRM-02.04.02.05).

Es el derecho que casi nadie implementa, y el que más problemas evita. Alguien
discute la exactitud de sus datos, o se opone a un tratamiento, y mientras se
resuelve **no se pueden usar** — pero tampoco se pueden borrar, porque si al
final tenía razón hay que poder rectificarlos, y si no la tenía hay que poder
seguir.

Lo que suele pasar en su lugar: se anota en un campo de texto «no contactar», y
tres meses después una importación lo pisa o una campaña no lo mira.

Cuatro decisiones:

**La limitación es una fila, no una casilla en la ficha.** Una casilla se pisa
con la siguiente importación; una fila con su motivo, su fecha y quién la puso
sobrevive y se puede auditar.

**Se comprueba en el punto de decisión, no en cada pantalla.** Si cada envío,
cada campaña y cada automatización tuviera que acordarse de mirarla, funcionaría
en las que alguien se acordó — que nunca son todas.

**Limitar no impide conservar, ni impide lo que la ley obliga.** El RGPD permite
seguir tratando los datos limitados para ejercer o defender reclamaciones y por
razones de interés público. Así que la limitación **no bloquea todo**: bloquea
los tratamientos que se le declaran, y los que no se pueden parar se dicen.

**Se levanta con constancia.** Una limitación que desaparece sin dejar rastro es
peor que no haberla puesto: nadie puede decir desde cuándo se volvió a tratar.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.audit.chain import registrar
from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    String,
    Text,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Qué se puede limitar. Lista cerrada porque es lo que se le promete al
# interesado por escrito: con texto libre, «marketing» y «comercial» serían dos
# limitaciones distintas y una de las dos no la miraría nadie.
TRATAMIENTOS = (
    "marketing",  # campañas, recorridos y cualquier envío comercial
    "perfilado",  # scoring, segmentación y decisiones automatizadas
    "cesion_terceros",  # compartir con partners o proveedores
    "enriquecimiento",  # completar la ficha desde fuentes externas
    "analitica",  # incluirlo en informes y cuadros de mando
)

# Lo que NO se puede parar aunque se limite, con el porqué. El RGPD lo dice
# expresamente: la limitación no impide conservar, ni tratar para ejercer o
# defender reclamaciones, ni cumplir una obligación legal. Decir que se paraba
# todo sería prometer algo que el sistema no puede cumplir — y que la ley
# tampoco quiere que cumpla.
NO_SE_PUEDE_LIMITAR = {
    "conservacion": "La limitación obliga precisamente a conservar: por eso no se borra.",
    "reclamaciones": "Se puede seguir tratando para ejercer o defender reclamaciones (art. 18.2).",
    "obligacion_legal": "Facturación, contabilidad y obligaciones fiscales no dependen del consentimiento.",
    "seguridad": "El registro de auditoría y el control de accesos sostienen la propia protección del dato.",
}

MOTIVOS = (
    "exactitud_discutida",
    "tratamiento_ilicito",
    "oposicion_en_estudio",
    "conservacion_para_reclamaciones",
    "otro",
)


class LimitacionTratamiento(Base, TimestampMixin):
    """Un tratamiento que no se puede hacer sobre una persona, y desde cuándo."""

    __tablename__ = "limitaciones_tratamiento"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    contacto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # Qué se limita. Vacío no significa «nada»: significa TODO lo limitable, que
    # es lo que pide quien invoca el artículo 18 sin más detalle.
    tratamientos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    motivo: Mapped[str] = mapped_column(
        String(40), nullable=False, default="otro", info={"opciones": MOTIVOS}
    )
    detalle: Mapped[str] = mapped_column(Text, nullable=False, default="")
    solicitud_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    desde: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Por qué se levantó. Sin esto, nadie puede decir desde cuándo se volvió a
    # tratar ni con qué justificación, que es la primera pregunta de una
    # inspección.
    motivo_levantamiento: Mapped[str] = mapped_column(Text, nullable=False, default="")
    puesta_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    levantada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (Index("ix_limitaciones_activas", "tenant_id", "contacto_id", "activa"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def limitar(
    uow: UnidadDeTrabajo,
    *,
    contacto_id: UUID,
    tratamientos: list[str] | None = None,
    motivo: str = "otro",
    detalle: str = "",
    solicitud_id: UUID | None = None,
    por: UUID | None = None,
) -> dict[str, Any]:
    """Bloquea el tratamiento de una persona **sin borrar nada**.

    Sin `tratamientos` se limitan **todos** los limitables, que es lo que pide
    quien invoca el artículo 18 sin entrar en detalle. Interpretar la lista vacía
    como «ninguno» sería registrar una limitación que no limita.
    """
    if motivo not in MOTIVOS:
        raise ErrorValidacion(
            f"Motivo de limitación desconocido: «{motivo}»",
            error_code="limitacion.motivo_invalido",
            detalle={"admitidos": list(MOTIVOS)},
        )
    pedidos = list(tratamientos) if tratamientos else list(TRATAMIENTOS)
    desconocidos = [t for t in pedidos if t not in TRATAMIENTOS]
    if desconocidos:
        raise ErrorValidacion(
            f"Tratamientos no reconocidos: {desconocidos}. Limitar algo que el "
            "sistema no sabe comprobar dejaría al interesado creyendo que está "
            "protegido.",
            error_code="limitacion.tratamiento_desconocido",
            detalle={"admitidos": list(TRATAMIENTOS)},
        )

    vigente = _vigente(uow.db, uow.tenant_id, contacto_id)
    if vigente is not None:
        # No se apilan limitaciones: se amplía la que hay. Dos filas activas
        # sobre la misma persona acabarían con una levantada y la otra olvidada.
        vigente.tratamientos = sorted(set(vigente.tratamientos or []) | set(pedidos))
        vigente.detalle = detalle or vigente.detalle
        uow.db.flush()
        fila = vigente
    else:
        fila = LimitacionTratamiento(
            tenant_id=uow.tenant_id,
            contacto_id=contacto_id,
            tratamientos=sorted(set(pedidos)),
            motivo=motivo,
            detalle=detalle,
            solicitud_id=solicitud_id,
            puesta_por=por,
            desde=_ahora(),
        )
        uow.db.add(fila)
        uow.db.flush()

    # Se avisa a quien envía. La limitación que se queda en el servicio que la
    # anotó no limita nada: quien manda los correos es `marketing`, y no puede
    # leer este esquema.
    uow.emitir(
        "contact.processing_limited",
        subject=("contacto", contacto_id),
        data={
            "contacto_id": str(contacto_id),
            "tratamientos": fila.tratamientos,
            "destinos": _destinos(uow.db, contacto_id),
            "motivo": motivo,
        },
    )
    registrar(
        uow.db,
        accion="derechos.limitacion_puesta",
        objeto="contacto",
        objeto_id=contacto_id,
        datos={"tratamientos": fila.tratamientos, "motivo": motivo},
        motivo=detalle or None,
        tenant_id=uow.tenant_id,
    )
    logger.info(
        "party.limitacion_puesta", contacto=str(contacto_id), tratamientos=fila.tratamientos
    )
    return {
        "limitacion_id": str(fila.id),
        "contacto_id": str(contacto_id),
        "limitados": fila.tratamientos,
        # Y lo que sigue pudiéndose hacer, dicho a la cara. Prometer un bloqueo
        # total sería prometer lo que la ley no pide y el sistema no puede dar.
        "no_se_paran": NO_SE_PUEDE_LIMITAR,
        "que_significa": (
            "Los datos se conservan y dejan de usarse para lo limitado. No se "
            "borran: si la exactitud estaba en discusión y el interesado tenía "
            "razón, hay que poder rectificarlos."
        ),
    }


def levantar(
    uow: UnidadDeTrabajo, *, contacto_id: UUID, motivo: str, por: UUID | None = None
) -> LimitacionTratamiento:
    """Quita la limitación, dejando dicho por qué.

    El motivo es obligatorio. Una limitación que desaparece sin rastro es peor
    que no haberla puesto: nadie puede decir desde cuándo se volvió a tratar ni
    con qué justificación.
    """
    if not motivo.strip():
        raise ErrorValidacion(
            "Levantar una limitación exige decir por qué: sin motivo, nadie puede "
            "explicar después desde cuándo se volvió a tratar.",
            error_code="limitacion.sin_motivo",
        )
    fila = _vigente(uow.db, uow.tenant_id, contacto_id)
    if fila is None:
        raise NoEncontrado(
            "Esta persona no tiene ninguna limitación activa",
            error_code="limitacion.no_encontrada",
        )
    fila.activa = False
    fila.hasta = _ahora()
    fila.motivo_levantamiento = motivo
    fila.levantada_por = por
    uow.db.flush()
    uow.emitir(
        "contact.processing_lifted",
        subject=("contacto", contacto_id),
        data={
            "contacto_id": str(contacto_id),
            "destinos": _destinos(uow.db, contacto_id),
            "motivo": motivo,
        },
    )
    registrar(
        uow.db,
        accion="derechos.limitacion_levantada",
        objeto="contacto",
        objeto_id=contacto_id,
        datos={"tratamientos": fila.tratamientos},
        motivo=motivo,
        tenant_id=uow.tenant_id,
    )
    return fila


def _destinos(db: Session, contacto_id: UUID) -> list[dict[str, str]]:
    """Por dónde se le puede escribir a esta persona.

    Van en el evento porque quien suprime lo hace **por dirección y no por
    identificador**: la misma persona puede estar en tres fichas duplicadas, y
    bloquear solo la que ejerció el derecho dejaría que las otras dos le
    siguieran escribiendo — que es justo la queja que acaba en denuncia.
    """
    from services.party.modelos import Contacto

    contacto = db.get(Contacto, contacto_id)
    if contacto is None:
        return []
    salida = []
    for canal, valor in (
        ("email", contacto.email),
        ("email", contacto.email_secundario),
        ("sms", contacto.movil),
        ("telefono", contacto.telefono),
    ):
        if valor:
            salida.append({"canal": canal, "destino": str(valor).strip().lower()})
    return salida


def _vigente(db: Session, tenant_id: UUID, contacto_id: UUID) -> LimitacionTratamiento | None:
    return (
        db.execute(
            select(LimitacionTratamiento).where(
                LimitacionTratamiento.tenant_id == tenant_id,
                LimitacionTratamiento.contacto_id == contacto_id,
                LimitacionTratamiento.activa.is_(True),
            )
        )
        .scalars()
        .first()
    )


def esta_limitado(
    db: Session, tenant_id: UUID, contacto_id: UUID, *, tratamiento: str
) -> dict[str, Any]:
    """Si un tratamiento concreto está bloqueado para esta persona.

    Devuelve **el porqué** además del sí o el no: quien recibe un «no puedes
    enviarle» necesita poder explicárselo a quien pregunte, y «está limitado»
    sin más acaba en alguien levantando la limitación para salir del paso.
    """
    if tratamiento not in TRATAMIENTOS:
        # Un tratamiento que no se sabe comprobar no se puede dar por permitido
        # en silencio: se dice que no se sabe, y quien llame decide.
        return {
            "limitado": False,
            "comprobado": False,
            "porque": (
                f"«{tratamiento}» no es un tratamiento reconocido, así que no se ha "
                f"podido comprobar. Los que se comprueban son {list(TRATAMIENTOS)}."
            ),
        }
    fila = _vigente(db, tenant_id, contacto_id)
    if fila is None or tratamiento not in (fila.tratamientos or []):
        return {"limitado": False, "comprobado": True, "porque": "Sin limitación para esto."}
    return {
        "limitado": True,
        "comprobado": True,
        "desde": fila.desde.isoformat(),
        "motivo": fila.motivo,
        "porque": (
            f"El interesado tiene limitado «{tratamiento}» desde "
            f"{fila.desde.date()} por «{fila.motivo}». Los datos se conservan; "
            "lo que no se puede es usarlos para esto."
        ),
    }


def limitados(db: Session, tenant_id: UUID, *, tratamiento: str = "") -> list[UUID]:
    """Los contactos con limitación activa, para que un envío masivo los aparte
    de una vez en lugar de preguntar uno a uno."""
    filas = (
        db.execute(
            select(LimitacionTratamiento).where(
                LimitacionTratamiento.tenant_id == tenant_id,
                LimitacionTratamiento.activa.is_(True),
            )
        )
        .scalars()
        .all()
    )
    if not tratamiento:
        return [f.contacto_id for f in filas]
    return [f.contacto_id for f in filas if tratamiento in (f.tratamientos or [])]
