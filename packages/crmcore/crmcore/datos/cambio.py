"""Tipos de cambio con histórico, replicados a todos los servicios
(CRM-07.01.01.06, CRM-03.02.01.07).

Estaban en `tenancy`, que es donde se administran. El problema apareció al hacer
la previsión multi-moneda: **`sales` no puede leer el esquema de `tenancy`** —lo
impide el gate de arquitectura, y con razón— así que la conversión histórica no
le llegaba. Las salidas eran tres: que `sales` llamara a `tenancy` por HTTP en
cada línea de un forecast de diez mil oportunidades, que se saltara la regla, o
que la tabla viva en el esquema de cada servicio y se replique por evento.

Se ha elegido la tercera, que es la misma que ya usan los ajustes en caliente y
las claves de tenant. El precio es una copia por servicio; lo que compra es que
una previsión no dependa de que otro servicio esté en pie, y que sumar el
pipeline no sean diez mil llamadas de red.

El histórico es el punto entero: una oportunidad cerrada en marzo tiene que
seguir valiendo lo que valía en marzo. Convertir siempre al cambio de hoy hace
que el histórico de ventas se mueva solo y que dos informes del mismo trimestre
den números distintos según cuándo se sacaron.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Date, DateTime, Index, Numeric, String, UniqueConstraint, func, select
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from crmcore.db.base import Base
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger

logger = get_logger(__name__)

TIPO_CAMBIO_FIJADO = "catalogos.tipo_cambio_fijado"


class TipoCambio(Base):
    """Tipo de cambio con fecha (CRM-03.02.01.07: *dated exchange rates*).

    Con **histórico**, no solo el último: una oportunidad cerrada en marzo tiene
    que seguir valiendo lo que valía en marzo. Convertirla siempre al cambio de
    hoy hace que el histórico de ventas se mueva solo, y que dos informes del
    mismo trimestre den números distintos según cuándo se sacaron.
    """

    __tablename__ = "tipos_cambio"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    desde_moneda: Mapped[str] = mapped_column(String(3), nullable=False)
    hasta_moneda: Mapped[str] = mapped_column(String(3), nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    # Alta precisión: un cambio redondeado a cuatro decimales desvía miles de
    # euros en una conversión de varios millones.
    tasa: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    origen: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "desde_moneda", "hasta_moneda", "fecha", name="uq_tipo_cambio"
        ),
        Index("ix_tipos_cambio_busqueda", "tenant_id", "desde_moneda", "hasta_moneda", "fecha"),
    )


def convertir(
    db: Session,
    *,
    tenant_id: UUID,
    importe: Decimal,
    desde: str,
    hasta: str,
    en_fecha: date | None = None,
) -> Decimal:
    """Convierte un importe con el cambio vigente en una fecha.

    Usa el tipo **más reciente que no sea posterior** a la fecha pedida, no el
    más cercano: un cambio publicado el día después no existía cuando se cerró
    la operación, y usarlo sería reescribir el pasado con información futura.
    """
    from decimal import ROUND_HALF_UP

    desde, hasta = desde.upper(), hasta.upper()
    if desde == hasta:
        return importe

    # Volcado explícito antes de leer. Lo aprendió antes
    # `contecflow-PSA/app/services/exchange_rate_service.py`: con autoflush
    # desactivado —que es como corren varias pruebas y algún proceso por lotes—
    # un tipo de cambio cargado en esta misma transacción todavía no está en la
    # base, así que la conversión que viene justo detrás no lo encuentra y falla
    # con «no hay tipo de cambio» teniéndolo delante.
    db.flush()

    en_fecha = en_fecha or date.today()
    fila = db.execute(
        select(TipoCambio)
        .where(
            TipoCambio.tenant_id == tenant_id,
            TipoCambio.desde_moneda == desde,
            TipoCambio.hasta_moneda == hasta,
            TipoCambio.fecha <= en_fecha,
        )
        .order_by(TipoCambio.fecha.desc())
        .limit(1)
    ).scalar_one_or_none()

    if fila is None:
        # Se busca la inversa antes de rendirse: quien carga EUR→USD rara vez
        # carga también USD→EUR, y calcularla es exacto.
        inversa = db.execute(
            select(TipoCambio)
            .where(
                TipoCambio.tenant_id == tenant_id,
                TipoCambio.desde_moneda == hasta,
                TipoCambio.hasta_moneda == desde,
                TipoCambio.fecha <= en_fecha,
            )
            .order_by(TipoCambio.fecha.desc())
            .limit(1)
        ).scalar_one_or_none()
        if inversa is None or inversa.tasa == 0:
            raise NoEncontrado(
                f"No hay tipo de cambio de {desde} a {hasta} para el {en_fecha.isoformat()}",
                error_code="tenancy.sin_tipo_cambio",
                detalle={"desde": desde, "hasta": hasta, "fecha": en_fecha.isoformat()},
            )
        tasa = Decimal(1) / inversa.tasa
    else:
        tasa = fila.tasa

    return (importe * tasa).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def fijar_tipo_cambio(
    db: Session,
    *,
    tenant_id: UUID,
    desde: str,
    hasta: str,
    tasa: Decimal,
    en_fecha: date | None = None,
    origen: str = "manual",
) -> TipoCambio:
    """Registra un tipo de cambio para una fecha. Idempotente por (par, fecha)."""
    if tasa <= 0:
        raise ErrorValidacion(
            "El tipo de cambio tiene que ser mayor que cero",
            error_code="tenancy.tipo_cambio_invalido",
        )
    en_fecha = en_fecha or date.today()
    existente = db.execute(
        select(TipoCambio).where(
            TipoCambio.tenant_id == tenant_id,
            TipoCambio.desde_moneda == desde.upper(),
            TipoCambio.hasta_moneda == hasta.upper(),
            TipoCambio.fecha == en_fecha,
        )
    ).scalar_one_or_none()
    if existente is not None:
        # Se actualiza en vez de fallar: corregir un cambio mal cargado es una
        # operación normal, y obligar a borrar antes solo añade fricción.
        existente.tasa = tasa
        existente.origen = origen
        propagar(db, existente)
        return existente

    fila = TipoCambio(
        tenant_id=tenant_id,
        desde_moneda=desde.upper(),
        hasta_moneda=hasta.upper(),
        fecha=en_fecha,
        tasa=tasa,
        origen=origen,
    )
    db.add(fila)
    db.flush()
    propagar(db, fila)
    return fila


# ── Réplica a todos los servicios ─────────────────────────────────────────


def declarar_evento() -> None:
    """Declara el evento de cambio de tipo, una sola vez.

    El productor es el núcleo y no `tenancy`: lo emite cualquier servicio en el
    que se escriba un tipo de cambio, y darle dueño a uno concreto sería mentir
    sobre quién lo publica.
    """
    from crmcore.events.catalogo import TipoEvento, obtener, registrar

    if obtener(TIPO_CAMBIO_FIJADO) is not None:
        return
    registrar(
        TipoEvento(
            tipo=TIPO_CAMBIO_FIJADO,
            version=1,
            productor="core",
            descripcion=(
                "Se ha fijado o corregido un tipo de cambio para una fecha. Lo "
                "consumen TODOS los servicios para replicarlo en su esquema"
            ),
            campos=("desde", "hasta", "fecha", "tasa", "origen"),
            # No sale a los webhooks del tenant: es mecánica interna de
            # replicación, y un integrador que se suscribiera a esto recibiría
            # un evento por cada servicio y por cada corrección.
            publico=False,
        )
    )


def propagar(db: Session, fila: "TipoCambio") -> None:
    """Emite el cambio para que el resto de servicios lo repliquen.

    Va por la tabla de salida, en la misma transacción que la escritura: si se
    publicara aparte, un fallo entre las dos dejaría a un servicio convirtiendo
    con un tipo y al resto con otro, y eso son dos informes del mismo trimestre
    que no cuadran sin que nadie sepa por qué.
    """
    from crmcore.db.uow import UnidadDeTrabajo

    uow = UnidadDeTrabajo(db=db, tenant_id=fila.tenant_id)
    uow.emitir(
        TIPO_CAMBIO_FIJADO,
        subject=("tipo_cambio", fila.id),
        data={
            "desde": fila.desde_moneda,
            "hasta": fila.hasta_moneda,
            "fecha": fila.fecha.isoformat(),
            "tasa": str(fila.tasa),
            "origen": fila.origen or "manual",
        },
        # Idempotente por par y fecha: la entrega es at-least-once, y aplicar
        # dos veces el mismo tipo tiene que dejar el mismo estado.
        dedup_key=f"fx:{fila.tenant_id}:{fila.desde_moneda}:{fila.hasta_moneda}:{fila.fecha}",
    )
    uow.volcar()


async def consumir_tipo_cambio(mensaje: Any) -> None:
    """Aplica en ESTE servicio un tipo de cambio fijado en otro.

    Lo registra `crear_servicio` en todos, sin que ninguno tenga que acordarse.
    Un servicio que no lo consumiera convertiría con tipos viejos mientras el
    resto usa los nuevos, y esa divergencia tarda semanas en atribuirse.
    """
    if isinstance(mensaje, dict):
        datos = mensaje.get("data") if isinstance(mensaje.get("data"), dict) else mensaje
        tenant = mensaje.get("tenant_id") or (datos or {}).get("tenant_id")
    else:
        datos = getattr(mensaje, "data", None) or {}
        tenant = getattr(mensaje, "tenant_id", None)
    if not tenant or not datos:
        return

    from crmcore.db.uow import unidad_de_trabajo

    with unidad_de_trabajo(sistema=True) as uow:
        _aplicar_local(
            uow.db,
            tenant_id=UUID(str(tenant)),
            desde=str(datos.get("desde") or ""),
            hasta=str(datos.get("hasta") or ""),
            fecha=date.fromisoformat(str(datos.get("fecha"))),
            tasa=Decimal(str(datos.get("tasa") or "0")),
            origen=str(datos.get("origen") or "replica"),
        )


def _aplicar_local(
    db: Session,
    *,
    tenant_id: UUID,
    desde: str,
    hasta: str,
    fecha: date,
    tasa: Decimal,
    origen: str,
) -> None:
    """Escribe el tipo en el esquema local sin volver a emitirlo.

    Sin este camino aparte, aplicar la réplica emitiría otro evento y el sistema
    se realimentaría: un tipo de cambio cargado una vez daría la vuelta por
    todos los servicios para siempre.
    """
    if not desde or not hasta or tasa <= 0:
        return
    existente = db.execute(
        select(TipoCambio).where(
            TipoCambio.tenant_id == tenant_id,
            TipoCambio.desde_moneda == desde.upper(),
            TipoCambio.hasta_moneda == hasta.upper(),
            TipoCambio.fecha == fecha,
        )
    ).scalar_one_or_none()
    if existente is not None:
        existente.tasa = tasa
        existente.origen = origen
        return
    db.add(
        TipoCambio(
            tenant_id=tenant_id,
            desde_moneda=desde.upper(),
            hasta_moneda=hasta.upper(),
            fecha=fecha,
            tasa=tasa,
            origen=origen,
        )
    )


declarar_evento()

from crmcore.contratos import Consumo, declarar_consumo  # noqa: E402

# Contrato dirigido por el consumidor (CRM-00.03.01.03).
declarar_consumo(
    Consumo(
        consumidor="todos-los-servicios",
        evento=TIPO_CAMBIO_FIJADO,
        campos=("desde", "hasta", "fecha", "tasa"),
        motivo=(
            "Replicar el tipo en el esquema local para convertir importes sin "
            "llamar a otro servicio; sin `fecha` no se puede convertir con el "
            "cambio del día y el histórico se movería solo"
        ),
    )
)
