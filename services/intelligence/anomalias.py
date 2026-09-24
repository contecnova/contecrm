"""Detección de anomalías en pipeline, actividad y servicio (CRM-05.02.01.05).

Un detector de anomalías mal calibrado es peor que ninguno: avisa treinta veces,
las treinta son normales, y a la trigésimo primera —la que importaba— ya nadie
abre el correo. Por eso aquí la pregunta no es «¿cómo detecto más?» sino «¿qué me
permito avisar sin quemar la confianza?».

Cuatro decisiones:

**Sin línea base no hay anomalía.** Con cuatro observaciones cualquier cosa es un
pico. Por debajo del mínimo se devuelve «no medible» y se dice cuántas faltan, en
vez de un aviso que parece un hallazgo.

**Una desviación no es una causa.** Se avisa de lo que se ve —«las oportunidades
creadas esta semana son la mitad de lo normal»— y no se inventa el porqué. La
explicación la pone quien conoce el negocio.

**Todo aviso lleva su normalidad al lado.** «17» no dice nada; «17 cuando lo
habitual son 40±6» se entiende sin saber estadística.

**Las anomalías buenas también se avisan.** Un detector que solo mira hacia abajo
deja pasar el mes en que alguien metió el pipeline duplicado.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from statistics import mean, pstdev
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

CENTESIMA = Decimal("0.01")

# Ámbitos cerrados: dónde se vigila. Abrirlo a cualquier cadena acabaría con
# treinta series que nadie sabe quién creó ni qué miden.
AMBITOS = ("pipeline", "actividad", "servicio", "ingresos", "datos")

SEVERIDADES = ("leve", "notable", "grave")


class SerieVigilada(Base, TimestampMixin):
    """Una métrica que se vigila, con su historia de valores."""

    __tablename__ = "series_vigiladas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    ambito: Mapped[str] = mapped_column(String(20), nullable=False, info={"opciones": AMBITOS})
    clave: Mapped[str] = mapped_column(String(120), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Cuántas observaciones hacen falta antes de avisar de nada. Configurable:
    # una serie diaria y una mensual no se ganan la confianza al mismo ritmo.
    minimo_observaciones: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    # Cuántas desviaciones típicas se toleran. También configurable, y por serie:
    # el pipeline es más ruidoso que la facturación.
    sigmas: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, default=Decimal("2.5"))
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (Index("ix_series_vigiladas", "tenant_id", "ambito", "clave", unique=True),)


class ObservacionSerie(Base):
    """Un valor de una serie en una fecha."""

    __tablename__ = "observaciones_serie"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    serie_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    valor: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_observaciones_serie", "tenant_id", "serie_id", "fecha"),)


class Anomalia(Base):
    """Un aviso: qué se vio, qué era lo normal y cuánto se apartó."""

    __tablename__ = "anomalias"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    serie_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    valor: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False, default=0)
    esperado: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False, default=0)
    desviacion: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False, default=0)
    # Cuántas sigmas se ha apartado. Es el número que ordena la lista.
    z: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=0)
    # Hacia arriba o hacia abajo: las buenas también se avisan.
    sentido: Mapped[str] = mapped_column(String(10), nullable=False, default="baja")
    severidad: Mapped[str] = mapped_column(String(10), nullable=False, default="leve")
    explicacion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Qué dijo la persona que la miró. Sin esto no hay forma de saber si el
    # detector sirve: una anomalía que nadie confirma ni descarta no enseña nada.
    revisada: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    era_real: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    comentario: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_anomalias", "tenant_id", "serie_id", "fecha"),
        Index("ix_anomalias_revision", "tenant_id", "revisada"),
    )


def _redondear(valor: Decimal | float) -> Decimal:
    return Decimal(str(valor)).quantize(CENTESIMA, rounding=ROUND_HALF_UP)


def vigilar(
    uow: UnidadDeTrabajo,
    *,
    ambito: str,
    clave: str,
    descripcion: str = "",
    minimo_observaciones: int | None = None,
    sigmas: Decimal | float | None = None,
) -> SerieVigilada:
    """Da de alta (o ajusta) una serie vigilada."""
    if ambito not in AMBITOS:
        raise ErrorValidacion(
            f"Ámbito '{ambito}' no reconocido. Los válidos son {list(AMBITOS)}.",
            error_code="anomalias.ambito_desconocido",
        )
    serie = (
        uow.db.execute(
            select(SerieVigilada).where(
                SerieVigilada.tenant_id == uow.tenant_id,
                SerieVigilada.ambito == ambito,
                SerieVigilada.clave == clave,
            )
        )
        .scalars()
        .first()
    )
    if serie is None:
        serie = SerieVigilada(tenant_id=uow.tenant_id, ambito=ambito, clave=clave)
        uow.db.add(serie)
    serie.descripcion = descripcion or serie.descripcion
    if minimo_observaciones is not None:
        serie.minimo_observaciones = max(3, int(minimo_observaciones))
    if sigmas is not None:
        serie.sigmas = Decimal(str(sigmas))
    serie.activa = True
    uow.db.flush()
    return serie


def observar(
    uow: UnidadDeTrabajo,
    *,
    ambito: str,
    clave: str,
    fecha: date,
    valor: Decimal | float,
) -> dict[str, Any]:
    """Registra un valor y, si procede, levanta una anomalía.

    **Sin línea base no hay anomalía**: por debajo del mínimo de observaciones se
    devuelve `medible: False` con cuántas faltan. Avisar con cuatro datos es
    avisar de que la serie es nueva, no de que pase algo.

    Y el aviso, cuando sale, lleva **la normalidad al lado**: «17 cuando lo
    habitual son 40±6» se entiende sin saber estadística; «z=3,8» no.
    """
    serie = vigilar(uow, ambito=ambito, clave=clave)
    previas = (
        uow.db.execute(
            select(ObservacionSerie)
            .where(
                ObservacionSerie.tenant_id == uow.tenant_id,
                ObservacionSerie.serie_id == serie.id,
                ObservacionSerie.fecha < fecha,
            )
            .order_by(ObservacionSerie.fecha.desc())
            .limit(90)
        )
        .scalars()
        .all()
    )

    uow.db.add(
        ObservacionSerie(
            tenant_id=uow.tenant_id,
            serie_id=serie.id,
            fecha=fecha,
            valor=Decimal(str(valor)),
        )
    )
    uow.db.flush()

    if len(previas) < serie.minimo_observaciones:
        return {
            "medible": False,
            "observaciones": len(previas),
            "faltan": serie.minimo_observaciones - len(previas),
            "porque": (
                f"La serie lleva {len(previas)} observaciones y necesita "
                f"{serie.minimo_observaciones} para tener una normalidad con la que "
                "comparar. Hasta entonces no se avisa: un pico sobre cuatro datos "
                "no es un hallazgo."
            ),
        }

    valores = [float(p.valor) for p in previas]
    media = mean(valores)
    desviacion = pstdev(valores)
    actual = float(valor)

    if desviacion == 0:
        # Serie constante: cualquier cambio es «infinitas sigmas», y eso no se
        # puede presentar como una medida. Se avisa solo si cambia de verdad.
        if actual == media:
            return {"medible": True, "anomalia": False, "porque": "Igual que siempre."}
        z = 0.0
        severidad = "notable"
    else:
        z = (actual - media) / desviacion
        severidad = "grave" if abs(z) >= 4 else ("notable" if abs(z) >= 3 else "leve")

    umbral = float(serie.sigmas)
    if desviacion > 0 and abs(z) < umbral:
        return {
            "medible": True,
            "anomalia": False,
            "valor": actual,
            "normal": round(media, 2),
            "margen": round(desviacion, 2),
            "porque": f"Dentro de lo habitual ({media:.1f}±{desviacion:.1f}).",
        }

    sentido = "sube" if actual > media else "baja"
    explicacion = (
        f"{clave}: {actual:g} cuando lo habitual son {media:.1f}±{desviacion:.1f} "
        f"(últimas {len(valores)} observaciones). Es una desviación observada, no "
        "una causa: qué la explica lo sabe quien conoce el negocio."
    )
    anomalia = Anomalia(
        tenant_id=uow.tenant_id,
        serie_id=serie.id,
        fecha=fecha,
        valor=Decimal(str(valor)),
        esperado=_redondear(media),
        desviacion=_redondear(desviacion),
        z=_redondear(z),
        sentido=sentido,
        severidad=severidad,
        explicacion=explicacion,
    )
    uow.db.add(anomalia)
    uow.db.flush()
    logger.info(
        "anomalias.detectada", ambito=ambito, clave=clave, z=float(anomalia.z), sentido=sentido
    )
    return {
        "medible": True,
        "anomalia": True,
        "id": str(anomalia.id),
        "valor": actual,
        "normal": round(media, 2),
        "margen": round(desviacion, 2),
        "sentido": sentido,
        "severidad": severidad,
        # También cuando sube: un detector que solo mira hacia abajo deja pasar
        # el mes en que alguien cargó el pipeline por duplicado.
        "porque": explicacion,
    }


def revisar(
    uow: UnidadDeTrabajo, *, anomalia_id: UUID, era_real: bool, comentario: str = ""
) -> Anomalia:
    """Una persona dice si el aviso valía o no. Es lo único que permite saber
    después si el detector sirve o solo hace ruido."""
    anomalia = uow.db.get(Anomalia, anomalia_id)
    if anomalia is None or anomalia.tenant_id != uow.tenant_id:
        from crmcore.errors import NoEncontrado

        raise NoEncontrado("Anomalía no encontrada.", error_code="anomalias.no_encontrada")
    anomalia.revisada = True
    anomalia.era_real = bool(era_real)
    anomalia.comentario = comentario
    uow.db.flush()
    return anomalia


def utilidad(db: Session, tenant_id: UUID, *, dias: int = 90) -> dict[str, Any]:
    """Cuánto acierta el detector, según quien lo mira.

    Esta es la cifra que decide si hay que apretar o aflojar los umbrales. Sin
    ella, el detector se calibra por sensación: alguien dice «avisa demasiado» y
    se le sube el umbral hasta que deja de avisar de nada.
    """
    desde = datetime.now(timezone.utc) - timedelta(days=dias)
    filas = (
        db.execute(
            select(Anomalia).where(Anomalia.tenant_id == tenant_id, Anomalia.created_at >= desde)
        )
        .scalars()
        .all()
    )
    revisadas = [f for f in filas if f.revisada]
    if len(revisadas) < 10:
        return {
            "concluyente": False,
            "avisos": len(filas),
            "revisados": len(revisadas),
            "porque": (
                f"Solo {len(revisadas)} avisos han sido revisados por una persona. "
                "Con menos de 10 no se puede decir si el detector sirve, y tocar los "
                "umbrales a ciegas es cómo se acaba con un detector que no avisa de nada."
            ),
        }
    reales = len([f for f in revisadas if f.era_real])
    return {
        "concluyente": True,
        "avisos": len(filas),
        "revisados": len(revisadas),
        "sin_revisar": len(filas) - len(revisadas),
        "acertados": reales,
        "falsos": len(revisadas) - reales,
        "precision_pct": round(100 * reales / len(revisadas), 1),
        "que_hacer": (
            "Por debajo del 50 % de aciertos conviene subir las sigmas de las series "
            "que más falsos generan; por encima del 90 % probablemente se están "
            "dejando anomalías fuera."
        ),
    }


def pendientes(db: Session, tenant_id: UUID, *, limite: int = 50) -> list[dict[str, Any]]:
    """Los avisos que nadie ha mirado todavía, los más desviados primero."""
    filas = (
        db.execute(
            select(Anomalia)
            .where(Anomalia.tenant_id == tenant_id, Anomalia.revisada.is_(False))
            .order_by(func.abs(Anomalia.z).desc())
            .limit(max(1, limite))
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "fecha": f.fecha.isoformat(),
            "valor": float(f.valor),
            "esperado": float(f.esperado),
            "sentido": f.sentido,
            "severidad": f.severidad,
            "porque": f.explicacion,
        }
        for f in filas
    ]
