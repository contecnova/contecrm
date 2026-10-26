"""Firma presencial en tableta, con captura de trazo (CRM-06.01.02.09).

Es la firma de toda la vida: el cliente está delante, firma con el dedo o con un
lápiz y se lleva el papel. Lo que cambia respecto a la firma remota es que **no
hay que identificar a nadie por correo** —está ahí— y que lo que se captura es
**dato biométrico**, con todo lo que eso arrastra.

Casi todas las implementaciones guardan una imagen PNG de la rúbrica y la llaman
firma. Eso no sostiene nada: una imagen se copia y se pega en otro documento, y
quien la niegue tiene razón.

Las decisiones:

**El trazo es dato biométrico del artículo 9, y se trata como tal.** Velocidad,
presión y tiempos identifican a una persona; por eso va cifrado, se declara en el
registro de tratamiento y exige que alguien haya dicho que sí. Guardarlo «porque
lo da la tableta» es recoger categoría especial sin base legal.

**Lo que ata la firma al documento es la huella, no la imagen.** Se guarda el
SHA-256 de lo firmado: si mañana el documento cambia una coma, la huella no
cuadra y se ve. Sin eso, la rúbrica vale para cualquier documento.

**Se guarda quién sostenía la tableta.** En la firma presencial, la
identificación la hace una persona mirando un DNI, no un sistema. Si no consta
quién fue, no hay identificación: hay una rúbrica.

**Un trazo de dos puntos no es una firma.** Un toque accidental produce una
rúbrica válida a los ojos del sistema, y eso es peor que no capturar nada.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.db.base import Base, SoftDeleteMixin
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger

logger = get_logger(__name__)


# Mínimos para que un trazo sea una firma y no un toque. No son un umbral de
# calidad: son la diferencia entre algo que alguien dibujó y algo que pasó
# porque la tableta estaba en la mesa.
def _firma_puntos_minimos() -> int:
    """Tope del núcleo, antes `_firma_puntos_minimos() = 12`.

    Era una constante de módulo. Sale del `.env`, no de los ajustes en
    caliente: es un tope operativo del despliegue y «por cliente» no
    significaría nada.
    """
    from crmcore.config import get_settings

    return get_settings().firma_puntos_minimos


def _firma_duracion_minima_ms() -> int:
    """Tope del núcleo, antes `_firma_duracion_minima_ms() = 300`.

    Era una constante de módulo. Sale del `.env`, no de los ajustes en
    caliente: es un tope operativo del despliegue y «por cliente» no
    significaría nada.
    """
    from crmcore.config import get_settings

    return get_settings().firma_duracion_minima_ms


class FirmaPresencial(Base, SoftDeleteMixin):
    """Una firma hecha delante, con su trazo y su testigo."""

    __tablename__ = "firmas_presenciales"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    objeto: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    objeto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # A quién se le atribuye y cómo se comprobó que era quien decía.
    firmante_nombre: Mapped[str] = mapped_column(
        String(200), nullable=False, default="", info={"sensibilidad": "personal"}
    )
    documento_identidad: Mapped[str | None] = mapped_column(
        String(60), nullable=True, info={"sensibilidad": "personal", "cifrado": True}
    )
    # Quién sostenía la tableta y miró el documento de identidad. En presencial,
    # la identificación la hace una persona: sin su nombre, esto es una rúbrica.
    testigo_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # El trazo: puntos con tiempo y presión. Es BIOMÉTRICO —categoría especial
    # del artículo 9— y por eso va cifrado y declarado en el RAT.
    trazo: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
        info={"sensibilidad": "especial", "cifrado": True},
    )
    puntos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duracion_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Lo que ata la firma al documento. Si el documento cambia, esto no cuadra.
    huella_documento: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    documento_id: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    # Que el firmante supo que se guardaba su biometría. Sin esto, la firma vale
    # y la recogida del trazo no.
    consentimiento_biometrico: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    texto_consentimiento: Mapped[str] = mapped_column(Text, nullable=False, default="")

    firmado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    dispositivo: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    __table_args__ = (
        Index("ix_firmas_presenciales", "tenant_id", "objeto", "objeto_id"),
        Index("ix_firmas_presenciales_huella", "tenant_id", "huella_documento"),
    )


def huella_de(contenido: bytes) -> str:
    """SHA-256 de lo que se firma."""
    return hashlib.sha256(contenido).hexdigest()


def _medir(trazo: dict[str, Any]) -> tuple[int, int]:
    """Cuántos puntos tiene el trazo y cuánto duró."""
    puntos = list(trazo.get("puntos") or [])
    if not puntos:
        return 0, 0
    tiempos = [int(p.get("t") or 0) for p in puntos if isinstance(p, dict)]
    duracion = (max(tiempos) - min(tiempos)) if tiempos else 0
    return len(puntos), max(0, duracion)


def capturar(
    db: Session,
    *,
    tenant_id: UUID,
    trazo: dict[str, Any],
    contenido_firmado: bytes,
    firmante_nombre: str,
    consentimiento_biometrico: bool,
    texto_consentimiento: str = "",
    documento_identidad: str = "",
    testigo_id: UUID | None = None,
    objeto: str = "",
    objeto_id: UUID | None = None,
    documento_id: str = "",
    dispositivo: str = "",
) -> FirmaPresencial:
    """Guarda una firma hecha delante.

    Se rechaza si falta cualquiera de las tres cosas que la sostienen: el
    consentimiento para recoger biometría, un trazo que parezca una firma y un
    testigo. Ninguna de las tres es burocracia — sin la primera, la recogida es
    ilícita; sin la segunda, un toque accidental queda como firma; sin la
    tercera, nadie comprobó que quien firmaba era quien decía.
    """
    if not consentimiento_biometrico:
        raise ErrorValidacion(
            "El trazo de una firma es dato biométrico del artículo 9: sin que el "
            "firmante sepa que se recoge y lo acepte, no se puede guardar. La "
            "firma se puede hacer igual sin capturar el trazo.",
            error_code="firma_presencial.sin_consentimiento",
        )
    if not texto_consentimiento.strip():
        raise ErrorValidacion(
            "Hace falta el texto que se le enseñó al firmante: sin él, el "
            "consentimiento es una casilla y no prueba nada.",
            error_code="firma_presencial.sin_texto",
        )
    if testigo_id is None:
        raise ErrorValidacion(
            "En una firma presencial la identificación la hace una persona "
            "mirando un documento. Sin constancia de quién fue, esto no es una "
            "firma identificada: es una rúbrica.",
            error_code="firma_presencial.sin_testigo",
        )

    puntos, duracion = _medir(trazo)
    if puntos < _firma_puntos_minimos() or duracion < _firma_duracion_minima_ms():
        raise ErrorValidacion(
            f"El trazo tiene {puntos} puntos en {duracion} ms: un toque "
            "accidental produce una rúbrica que el sistema daría por válida.",
            error_code="firma_presencial.trazo_insuficiente",
            detalle={
                "minimo_puntos": _firma_puntos_minimos(),
                "minima_duracion_ms": _firma_duracion_minima_ms(),
            },
        )
    if not contenido_firmado:
        raise ErrorValidacion(
            "Hace falta el documento que se firma: sin su huella, la rúbrica vale "
            "para cualquier documento.",
            error_code="firma_presencial.sin_documento",
        )

    fila = FirmaPresencial(
        tenant_id=tenant_id,
        objeto=objeto,
        objeto_id=objeto_id,
        firmante_nombre=firmante_nombre,
        documento_identidad=documento_identidad or None,
        testigo_id=testigo_id,
        trazo=trazo,
        puntos=puntos,
        duracion_ms=duracion,
        huella_documento=huella_de(contenido_firmado),
        documento_id=documento_id,
        consentimiento_biometrico=True,
        texto_consentimiento=texto_consentimiento,
        dispositivo=dispositivo[:200],
        firmado_at=datetime.now(timezone.utc),
    )
    db.add(fila)
    db.flush()
    logger.info("firma_presencial.capturada", objeto=objeto, puntos=puntos, duracion_ms=duracion)
    return fila


def comprobar(db: Session, tenant_id: UUID, *, firma_id: UUID, contenido: bytes) -> dict[str, Any]:
    """Si lo que hay ahora es lo que se firmó.

    Es la única pregunta que importa cuando alguien dice «yo no firmé eso»: no si
    la rúbrica se parece, sino si el documento es el mismo. Una coma cambiada
    rompe la huella y se ve.
    """
    fila = db.get(FirmaPresencial, firma_id)
    if fila is None or fila.tenant_id != tenant_id:
        raise NoEncontrado("Esa firma no existe", error_code="firma_presencial.no_encontrada")
    actual = huella_de(contenido)
    cuadra = actual == fila.huella_documento
    return {
        "firma_id": str(firma_id),
        "cuadra": cuadra,
        "huella_firmada": fila.huella_documento,
        "huella_actual": actual,
        "firmado_at": fila.firmado_at.isoformat(),
        "testigo_id": str(fila.testigo_id) if fila.testigo_id else None,
        "que_significa": (
            "El documento es exactamente el que se firmó."
            if cuadra
            else "El documento NO es el que se firmó: ha cambiado desde entonces. "
            "La firma no lo ampara."
        ),
    }


def firmas_de(
    db: Session, tenant_id: UUID, *, objeto: str, objeto_id: UUID
) -> list[dict[str, Any]]:
    """Las firmas presenciales de un registro, **sin el trazo**.

    El trazo no sale en los listados: es biometría, y devolverla en una consulta
    de rutina la reparte por los registros de acceso, las cachés y los navegadores
    de quien mire la ficha.
    """
    filas = (
        db.execute(
            select(FirmaPresencial)
            .where(
                FirmaPresencial.tenant_id == tenant_id,
                FirmaPresencial.objeto == objeto,
                FirmaPresencial.objeto_id == objeto_id,
            )
            .order_by(FirmaPresencial.firmado_at.desc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "firmante": f.firmante_nombre,
            "firmado_at": f.firmado_at.isoformat(),
            "testigo_id": str(f.testigo_id) if f.testigo_id else None,
            "puntos": f.puntos,
            "duracion_ms": f.duracion_ms,
            "huella_documento": f.huella_documento,
            "trazo": "no se devuelve en listados: es dato biométrico",
        }
        for f in filas
    ]
