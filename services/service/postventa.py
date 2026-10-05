"""Postventa y logística inversa: devoluciones, resoluciones y reclamaciones
(CRM-04.05.01.01, .02, .03).

Lo que devuelve un cliente es la parte del negocio que peor se lleva, y siempre
por lo mismo: **el material vuelve y nadie sabe dónde está, ni quién autorizó
qué, ni qué se le prometió**. Tres decisiones salen de ahí.

**Una devolución se autoriza, y la autorización tiene número.** Sin RMA, el
paquete llega al almacén sin remite reconocible y se queda en una estantería. Con
RMA, el almacén sabe qué espera, de quién y por qué.

**La disposición es obligatoria al cerrar.** Qué se hace con lo devuelto
—reacondicionar, chatarra, devolver al proveedor— es lo único que impide que el
material desaparezca del mundo: una devolución «cerrada» sin disposición es una
pieza que consta devuelta y que nadie ha vuelto a ver.

**El abono lo emite quien factura, no el CRM.** Aquí se registra la decisión y se
espera la confirmación del ERP, igual que con los pedidos. Un CRM que se inventa
un abono deja dos contabilidades, y la que se mira es la otra.

Y las reclamaciones formales tienen **plazos de ley**, que es otra cosa que un
SLA comercial: no se pueden ampliar porque haya mucho trabajo, hay que poder
demostrar cuándo entró la reclamación, y el que vence sin contestar se pierde.
Por eso el plazo se guarda calculado, se dice si es en días naturales o hábiles, y
la suspensión exige un motivo tipificado.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.datos.calendario import CalendarioLaboral, es_laborable
from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from crmcore.runtime import settings as rt
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from services.service import activos as act

logger = get_logger(__name__)

CENTIMO = Decimal("0.01")

# Estados de una devolución.
#
#   solicitada     el cliente la ha pedido; no se ha autorizado nada
#   autorizada     tiene RMA; el almacén sabe que la espera
#   rechazada      con motivo, siempre
#   recibida       el material ha llegado
#   inspeccionada  se ha visto qué llega y en qué estado
#   resuelta       hay reparación, sustitución o abono decidido
#   cerrada        con disposición del material
#   anulada        el cliente no la envió
ESTADOS = (
    "solicitada",
    "autorizada",
    "rechazada",
    "recibida",
    "inspeccionada",
    "resuelta",
    "cerrada",
    "anulada",
)

# Qué se hace con lo que vuelve. Lista cerrada: es lo que decide si el material
# se puede volver a vender, y un valor inventado en una pantalla dejaría fuera
# del inventario algo que sí vale.
#
#   reacondicionar   vuelve al stock tras revisarlo
#   reparar          se arregla y vuelve al cliente
#   chatarra         se destruye; ya no existe
#   proveedor        se devuelve al fabricante
#   pendiente        todavía no se ha decidido
DISPOSICIONES = ("reacondicionar", "reparar", "chatarra", "proveedor", "pendiente")

# Cómo se resuelve. Las tres, y son excluyentes entre sí para una misma línea:
# reparar y abonar a la vez es un error de tramitación que sale en la factura.
RESOLUCIONES = ("reparacion", "sustitucion", "abono", "sin_accion")

# Estados de un expediente de reclamación.
ESTADOS_EXPEDIENTE = ("abierto", "suspendido", "resuelto", "desistido", "caducado")

# Por qué se puede parar el reloj legal. Cerrada **a propósito**: si el tenant
# pudiera inventarse motivos, el plazo se suspendería por «mucho trabajo» y
# dejaría de ser un plazo.
MOTIVOS_SUSPENSION = (
    "subsanacion_solicitada",
    "prueba_pericial",
    "traslado_a_tercero",
    "acuerdo_con_el_cliente",
)


class Devolucion(Base, TimestampMixin, SoftDeleteMixin):
    """Una devolución con su autorización: el RMA (CRM-04.05.01.01)."""

    __tablename__ = "devoluciones"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # El número de RMA es lo que el cliente escribe en la caja. Sin él, el
    # paquete llega al almacén sin remite reconocible y se queda en una
    # estantería hasta que alguien pregunta.
    codigo: Mapped[str | None] = mapped_column(String(30), nullable=True)
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    contacto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    caso_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    pedido_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    activo_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    motivo: Mapped[str] = mapped_column(
        String(80), nullable=False, default="", info={"opciones": MOTIVOS_SUSPENSION}
    )
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Sin `index=True`: el índice compuesto de abajo ya cubre la consulta real
    # —los abiertos por orden de llegada— y los dos se llamarían igual.
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="solicitada")

    comprado_el: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Si se autorizó fuera de la ventana de devolución, y por qué. Se guarda
    # aparte del motivo general: es una excepción comercial y tiene que poder
    # contarse, no quedarse dentro de un texto libre.
    fuera_de_plazo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    motivo_excepcion: Mapped[str] = mapped_column(Text, nullable=False, default="")

    autorizada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    autorizada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motivo_rechazo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recibida_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    inspeccion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    disposicion: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    cerrada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # La recogida se hace con el mismo encargo seguido que cualquier otro envío
    # (CRM-00.04.05): aquí solo se guarda a cuál corresponde.
    encargo_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "codigo", name="uq_devolucion_codigo"),
        Index("ix_devoluciones_estado", "tenant_id", "estado", "created_at"),
        Index("ix_devoluciones_cuenta", "tenant_id", "cuenta_id"),
    )


class LineaDevolucion(Base, TimestampMixin):
    """Qué vuelve, cuánto y en qué estado llegó."""

    __tablename__ = "lineas_devolucion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    devolucion_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("devoluciones.id", ondelete="CASCADE"), nullable=False
    )
    producto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    activo_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    numero_serie: Mapped[str | None] = mapped_column(String(120), nullable=True)
    concepto: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    cantidad: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, default=1)
    # Lo que se esperaba recibir frente a lo que llegó de verdad. Dos campos
    # porque la diferencia es el problema: se autorizan tres y llegan dos.
    cantidad_recibida: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    estado_material: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    importe: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    disposicion: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")

    __table_args__ = (Index("ix_lineas_devolucion", "tenant_id", "devolucion_id"),)


class Resolucion(Base, TimestampMixin):
    """Reparación, sustitución o abono (CRM-04.05.01.02).

    El abono **no se emite aquí**: se registra la decisión y se espera la
    confirmación de quien factura. Un CRM que se inventa un abono deja dos
    contabilidades, y la que se mira es la otra.
    """

    __tablename__ = "resoluciones_postventa"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    devolucion_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("devoluciones.id", ondelete="CASCADE"), nullable=False
    )
    linea_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    # Quién paga: cliente | garantia | cortesia. Es la pregunta que el cliente
    # hace primero, y la que decide si esto va a una factura o a una reclamación
    # al fabricante.
    a_cargo_de: Mapped[str] = mapped_column(String(20), nullable=False, default="cliente")
    importe: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    # Con qué se materializa: una orden de trabajo si es reparación, un activo
    # nuevo si es sustitución, una referencia del ERP si es abono.
    orden_trabajo_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    activo_sustituto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # solicitado | confirmado | rechazado — lo dice el ERP, no este servicio.
    estado_abono: Mapped[str | None] = mapped_column(String(20), nullable=True)
    referencia_externa: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    motivo_rechazo_externo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    nota: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (Index("ix_resoluciones_postventa", "tenant_id", "devolucion_id"),)


class Expediente(Base, TimestampMixin, SoftDeleteMixin):
    """Reclamación formal con plazo de ley (CRM-04.05.01.03).

    El plazo se guarda **calculado**, no derivado de una política que puede
    cambiar: una norma nueva no puede convertir en incumplidos expedientes que se
    contestaron a tiempo con la de entonces. Es el mismo criterio que el reloj de
    SLA de los casos.
    """

    __tablename__ = "expedientes_reclamacion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    codigo: Mapped[str | None] = mapped_column(String(30), nullable=True)
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    contacto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    caso_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    devolucion_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    tipo: Mapped[str] = mapped_column(String(60), nullable=False, default="reclamacion")
    # La vía por la que entró: hoja de reclamaciones, organismo de consumo,
    # burofax, correo. Cambia el plazo y cambia a quién hay que contestar.
    via: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    organismo: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    referencia_externa: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    asunto: Mapped[str] = mapped_column(String(300), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Cuándo entró de verdad, que no es cuándo se grabó. Se guardan las dos: la
    # diferencia entre ellas es el tiempo que la reclamación estuvo en un cajón,
    # y se descuenta del plazo, no del cliente.
    entrada_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    registrada_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # La prueba de que se recibió. Sin acuse, «contestamos a tiempo» no se puede
    # demostrar, que es justo lo que hay que demostrar.
    acuse_documento_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    acuse_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    plazo_dias: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    # Naturales o hábiles: no es lo mismo y la diferencia son semanas.
    plazo_habiles: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    vence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Lo que se ha parado el reloj, en segundos, y por qué.
    suspendido_seg: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    suspendido_desde: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    motivo_suspension: Mapped[str] = mapped_column(String(60), nullable=False, default="")

    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="abierto", index=True)
    respondido_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    respuesta: Mapped[str] = mapped_column(Text, nullable=False, default="")
    respuesta_documento_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    resultado: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    hitos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "codigo", name="uq_expediente_codigo"),
        Index("ix_expedientes_vencimiento", "tenant_id", "estado", "vence_at"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _hoy(db: Any = None) -> date:
    """El día de hoy **donde está el cliente**, si hay sesión con la que saberlo.

    Sin sesión cae a UTC, que es lo que hacía antes: no empeora nada y deja
    claro dónde falta el dato. Quien la tenga a mano está obligado a pasarla —
    hay un gate que lo mira—, porque entre medianoche y las dos de la mañana en
    Madrid la respuesta sin sesión es **la de ayer**.
    """
    from crmcore.fechas import hoy as _hoy_del_cliente

    return _hoy_del_cliente(db)


def _redondear(valor: Decimal) -> Decimal:
    return Decimal(valor).quantize(CENTIMO, rounding=ROUND_HALF_UP)


def _con_tz(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


def _devolucion(db: Session, tenant_id: UUID, devolucion_id: UUID) -> Devolucion:
    fila = db.get(Devolucion, devolucion_id)
    if fila is None or fila.tenant_id != tenant_id:
        raise NoEncontrado("La devolución no existe", error_code="postventa.no_encontrada")
    return fila


def _siguiente_codigo(db: Session, tenant_id: UUID, modelo: Any, prefijo: str) -> str:
    cuantas = (
        db.execute(select(func.count()).select_from(modelo).where(modelo.tenant_id == tenant_id))
    ).scalar_one()
    return f"{prefijo}-{int(cuantas) + 1:06d}"


# ── Devoluciones (CRM-04.05.01.01) ────────────────────────────────────────


def solicitar(
    uow: UnidadDeTrabajo,
    *,
    motivo: str,
    cuenta_id: UUID | None = None,
    contacto_id: UUID | None = None,
    caso_id: UUID | None = None,
    pedido_id: UUID | None = None,
    activo_id: UUID | None = None,
    comprado_el: date | None = None,
    descripcion: str = "",
    lineas: list[dict[str, Any]] | None = None,
) -> tuple[Devolucion, list[str]]:
    """Registra la petición del cliente. **Todavía no autoriza nada.**

    El motivo es obligatorio y se pide **normalizado**: «no me gusta», «llegó
    roto» y «no es lo que pedí» llevan a disposiciones distintas del material, y
    en texto libre no se pueden agrupar ni al cabo de un año.
    """
    if not motivo.strip():
        raise ErrorValidacion(
            "Una devolución sin motivo no se puede analizar ni decidir qué hacer "
            "con el material.",
            error_code="postventa.motivo_obligatorio",
        )
    avisos: list[str] = []
    if comprado_el is None:
        avisos.append(
            "Sin fecha de compra: no se puede comprobar si está dentro de la ventana "
            "de devolución."
        )

    fila = Devolucion(
        tenant_id=uow.tenant_id,
        motivo=motivo.strip(),
        descripcion=descripcion,
        cuenta_id=cuenta_id,
        contacto_id=contacto_id,
        caso_id=caso_id,
        pedido_id=pedido_id,
        activo_id=activo_id,
        comprado_el=comprado_el,
    )
    uow.db.add(fila)
    uow.db.flush()
    fila.codigo = _siguiente_codigo(uow.db, uow.tenant_id, Devolucion, "RMA")

    for linea in lineas or []:
        serie = str(linea.get("numero_serie") or "").strip() or None
        if serie:
            instalado = uow.db.execute(
                select(act.ActivoInstalado).where(
                    act.ActivoInstalado.tenant_id == uow.tenant_id,
                    act.ActivoInstalado.numero_serie == serie,
                )
            ).scalar_one_or_none()
            if instalado is None:
                # No se bloquea: la serie puede ser de material que nunca se dio
                # de alta como activo. Pero se dice, porque también puede ser una
                # serie que no es nuestra.
                avisos.append(
                    f"La serie {serie} no consta como activo instalado: compruébala "
                    "antes de aceptar el material."
                )
        uow.db.add(
            LineaDevolucion(
                tenant_id=uow.tenant_id,
                devolucion_id=fila.id,
                producto_id=(UUID(str(linea["producto_id"])) if linea.get("producto_id") else None),
                activo_id=UUID(str(linea["activo_id"])) if linea.get("activo_id") else None,
                numero_serie=serie,
                concepto=str(linea.get("concepto") or ""),
                cantidad=Decimal(str(linea.get("cantidad") or 1)),
                importe=(
                    Decimal(str(linea["importe"])) if linea.get("importe") is not None else None
                ),
            )
        )
    uow.db.flush()
    uow.emitir(
        "return.requested",
        subject=("devolucion", fila.id),
        data={"devolucion_id": str(fila.id), "motivo": fila.motivo},
    )
    return fila, avisos


def dentro_de_ventana(
    db: Session, devolucion: Devolucion, *, en_fecha: date | None = None
) -> dict[str, Any]:
    """Si la devolución llega dentro del plazo comercial.

    Sin fecha de compra **no se dice que esté fuera**: se dice que no se sabe.
    Tomarlo por fuera de plazo rechaza devoluciones legítimas por un dato que
    falta en nuestro sistema, no en el del cliente.
    """
    hoy = en_fecha or _hoy(db)
    dias = int(rt.efectivo("devolucion_ventana_dias", db) or 30)
    if devolucion.comprado_el is None:
        return {
            "dentro": False,
            "concluyente": False,
            "ventana_dias": dias,
            "motivo": "No consta la fecha de compra: no se puede saber si está en plazo.",
        }
    limite = devolucion.comprado_el + timedelta(days=dias)
    return {
        "dentro": hoy <= limite,
        "concluyente": True,
        "ventana_dias": dias,
        "vencia_el": str(limite),
        "dias_pasados": (hoy - devolucion.comprado_el).days,
        "motivo": (
            f"Compra del {devolucion.comprado_el}; la ventana de {dias} días venció "
            f"el {limite}."
            if hoy > limite
            else ""
        ),
    }


def autorizar(
    uow: UnidadDeTrabajo,
    devolucion_id: UUID,
    *,
    por: UUID | None = None,
    forzar: bool = False,
    motivo_excepcion: str = "",
) -> tuple[Devolucion, dict[str, Any]]:
    """Autoriza la devolución y le da número de RMA.

    Fuera de la ventana **se puede autorizar igualmente con motivo**, y queda
    marcado como excepción. Es una decisión comercial legítima y frecuente; lo que
    no puede es pasar en silencio, porque entonces la ventana no significa nada y
    nadie puede medir cuánto se está regalando.
    """
    fila = _devolucion(uow.db, uow.tenant_id, devolucion_id)
    if fila.estado != "solicitada":
        raise Conflicto(
            "Esa devolución ya está decidida",
            error_code="postventa.ya_decidida",
            detalle={"estado": fila.estado},
        )
    ventana = dentro_de_ventana(uow.db, fila)
    if ventana["concluyente"] and not ventana["dentro"]:
        if not forzar:
            raise Conflicto(
                "La devolución llega fuera de la ventana",
                error_code="postventa.fuera_de_ventana",
                detalle=ventana,
            )
        if not motivo_excepcion.strip():
            raise ErrorValidacion(
                "Autorizar fuera de plazo exige motivo: sin él, nadie puede medir "
                "cuántas excepciones se están haciendo.",
                error_code="postventa.motivo_obligatorio",
            )
        fila.fuera_de_plazo = True
        fila.motivo_excepcion = motivo_excepcion.strip()

    fila.estado = "autorizada"
    fila.autorizada_por = por
    fila.autorizada_at = _ahora()
    uow.db.flush()
    registrar(
        uow.db,
        accion="postventa.autorizada",
        objeto="devolucion",
        objeto_id=fila.id,
        datos={"codigo": fila.codigo, "fuera_de_plazo": fila.fuera_de_plazo, "ventana": ventana},
        tenant_id=uow.tenant_id,
    )
    uow.emitir(
        "return.authorized",
        subject=("devolucion", fila.id),
        data={"devolucion_id": str(fila.id), "codigo": fila.codigo or ""},
    )
    return fila, ventana


def rechazar(uow: UnidadDeTrabajo, devolucion_id: UUID, *, motivo: str) -> Devolucion:
    """Rechaza la devolución. Con motivo, siempre: es lo que el cliente va a
    preguntar y lo que se le tiene que poder contestar."""
    if not motivo.strip():
        raise ErrorValidacion(
            "Rechazar una devolución exige motivo.", error_code="postventa.motivo_obligatorio"
        )
    fila = _devolucion(uow.db, uow.tenant_id, devolucion_id)
    if fila.estado != "solicitada":
        raise Conflicto(
            "Esa devolución ya está decidida",
            error_code="postventa.ya_decidida",
            detalle={"estado": fila.estado},
        )
    fila.estado = "rechazada"
    fila.motivo_rechazo = motivo.strip()
    uow.db.flush()
    return fila


def recibir(
    uow: UnidadDeTrabajo,
    devolucion_id: UUID,
    *,
    recibido: list[dict[str, Any]] | None = None,
    cuando: datetime | None = None,
) -> tuple[Devolucion, dict[str, Any]]:
    """Anota lo que ha llegado de verdad al almacén.

    Devuelve las **diferencias** entre lo autorizado y lo recibido. Es el dato que
    se pierde siempre: se autorizan tres unidades, llegan dos, y la tercera
    aparece meses después en un descuadre de inventario que nadie sabe explicar.
    """
    fila = _devolucion(uow.db, uow.tenant_id, devolucion_id)
    if fila.estado not in ("autorizada", "recibida"):
        raise Conflicto(
            "Solo se recibe lo autorizado",
            error_code="postventa.no_autorizada",
            detalle={"estado": fila.estado},
        )
    lineas = (
        uow.db.execute(
            select(LineaDevolucion).where(
                LineaDevolucion.tenant_id == uow.tenant_id,
                LineaDevolucion.devolucion_id == fila.id,
            )
        )
        .scalars()
        .all()
    )
    por_id = {str(line.id): line for line in lineas}
    for dato in recibido or []:
        linea = por_id.get(str(dato.get("linea_id")))
        if linea is None:
            continue
        linea.cantidad_recibida = Decimal(str(dato.get("cantidad") or 0))
        linea.estado_material = str(dato.get("estado_material") or "")

    diferencias = []
    for linea in lineas:
        esperado = Decimal(linea.cantidad)
        llegado = Decimal(linea.cantidad_recibida) if linea.cantidad_recibida is not None else None
        if llegado is None:
            diferencias.append({"linea_id": str(linea.id), "porque": "no se ha anotado qué llegó"})
        elif llegado != esperado:
            diferencias.append(
                {
                    "linea_id": str(linea.id),
                    "esperado": str(esperado),
                    "recibido": str(llegado),
                    "porque": "llegó una cantidad distinta de la autorizada",
                }
            )
    fila.estado = "recibida"
    fila.recibida_at = cuando or _ahora()
    uow.db.flush()
    return fila, {"diferencias": diferencias, "sin_diferencias": not diferencias}


def inspeccionar(
    uow: UnidadDeTrabajo,
    devolucion_id: UUID,
    *,
    inspeccion: str,
    disposiciones: dict[str, str] | None = None,
) -> Devolucion:
    """Anota qué se ha visto y qué se hace con cada línea."""
    fila = _devolucion(uow.db, uow.tenant_id, devolucion_id)
    if fila.estado not in ("recibida", "inspeccionada"):
        raise Conflicto(
            "Todavía no ha llegado nada que inspeccionar",
            error_code="postventa.no_recibida",
            detalle={"estado": fila.estado},
        )
    for linea_id, disposicion in (disposiciones or {}).items():
        if disposicion not in DISPOSICIONES:
            raise ErrorValidacion(
                f"Disposición «{disposicion}» no válida.",
                error_code="postventa.disposicion_no_valida",
                detalle={"validas": list(DISPOSICIONES)},
            )
        linea = uow.db.get(LineaDevolucion, UUID(linea_id))
        if linea is not None and linea.devolucion_id == fila.id:
            linea.disposicion = disposicion
    fila.inspeccion = inspeccion
    fila.estado = "inspeccionada"
    uow.db.flush()
    return fila


def resolver(
    uow: UnidadDeTrabajo,
    devolucion_id: UUID,
    *,
    tipo: str,
    a_cargo_de: str = "cliente",
    importe: Decimal | None = None,
    linea_id: UUID | None = None,
    orden_trabajo_id: UUID | None = None,
    activo_sustituto_id: UUID | None = None,
    nota: str = "",
) -> tuple[Resolucion, list[str]]:
    """Decide qué se hace: reparar, sustituir o abonar (CRM-04.05.01.02).

    El abono se queda en **`solicitado`**: lo confirma quien factura. Darlo por
    hecho aquí dejaría al cliente esperando un dinero que nadie ha emitido, y
    dejaría dos contabilidades que no cuadran.
    """
    if tipo not in RESOLUCIONES:
        raise ErrorValidacion(
            f"Resolución «{tipo}» no válida.",
            error_code="postventa.resolucion_no_valida",
            detalle={"validas": list(RESOLUCIONES)},
        )
    if a_cargo_de not in ("cliente", "garantia", "cortesia"):
        raise ErrorValidacion(
            "A cargo de: cliente, garantía o cortesía. Es lo que decide si esto va "
            "a una factura o a una reclamación al fabricante.",
            error_code="postventa.a_cargo_no_valido",
        )
    fila = _devolucion(uow.db, uow.tenant_id, devolucion_id)
    if fila.estado in ("solicitada", "rechazada", "anulada"):
        raise Conflicto(
            "Todavía no hay nada que resolver",
            error_code="postventa.no_resoluble",
            detalle={"estado": fila.estado},
        )

    avisos: list[str] = []
    ya = (
        uow.db.execute(
            select(Resolucion).where(
                Resolucion.tenant_id == uow.tenant_id,
                Resolucion.devolucion_id == fila.id,
                Resolucion.linea_id == linea_id,
            )
        )
        .scalars()
        .all()
    )
    if ya:
        # Reparar y abonar la misma línea es un error de tramitación que sale en
        # la factura del cliente. Se avisa aquí, que es donde todavía se puede
        # deshacer.
        avisos.append(
            "Esa línea ya tenía resolución "
            f"({', '.join(sorted({r.tipo for r in ya}))}): reparar y abonar lo mismo "
            "acaba en una factura mal."
        )
    if tipo == "abono" and importe is None:
        raise ErrorValidacion(
            "Un abono sin importe no se puede tramitar.",
            error_code="postventa.importe_obligatorio",
        )
    if tipo == "sustitucion" and activo_sustituto_id is None:
        avisos.append(
            "Sustitución sin activo sustituto: el parque instalado del cliente se "
            "quedará con la máquina antigua."
        )

    resolucion = Resolucion(
        tenant_id=uow.tenant_id,
        devolucion_id=fila.id,
        linea_id=linea_id,
        tipo=tipo,
        a_cargo_de=a_cargo_de,
        importe=importe,
        orden_trabajo_id=orden_trabajo_id,
        activo_sustituto_id=activo_sustituto_id,
        estado_abono="solicitado" if tipo == "abono" else None,
        nota=nota,
    )
    uow.db.add(resolucion)
    fila.estado = "resuelta"
    uow.db.flush()
    if tipo == "abono":
        uow.emitir(
            "refund.requested",
            subject=("devolucion", fila.id),
            data={
                "devolucion_id": str(fila.id),
                "resolucion_id": str(resolucion.id),
                "importe": str(importe),
                "moneda": resolucion.moneda,
            },
        )
    registrar(
        uow.db,
        accion="postventa.resuelta",
        objeto="devolucion",
        objeto_id=fila.id,
        datos={"tipo": tipo, "a_cargo_de": a_cargo_de, "importe": str(importe or "")},
        tenant_id=uow.tenant_id,
    )
    return resolucion, avisos


def confirmar_abono(
    uow: UnidadDeTrabajo,
    resolucion_id: UUID,
    *,
    confirmado: bool,
    referencia: str = "",
    motivo: str = "",
) -> Resolucion:
    """Anota lo que contestó quien factura.

    Igual que el traspaso de un pedido al ERP: el abono no está hecho hasta que
    el sistema que lo emite lo dice. Y si lo rechaza, **se guarda por qué** — sin
    eso, alguien lo vuelve a mandar igual y vuelve a rebotar.
    """
    fila = uow.db.get(Resolucion, resolucion_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado(
            "La resolución no existe", error_code="postventa.resolucion_no_encontrada"
        )
    if fila.tipo != "abono":
        raise Conflicto(
            "Esa resolución no es un abono",
            error_code="postventa.no_es_abono",
            detalle={"tipo": fila.tipo},
        )
    if not confirmado and not motivo.strip():
        raise ErrorValidacion(
            "Un abono rechazado sin motivo se vuelve a mandar igual y vuelve a rebotar.",
            error_code="postventa.motivo_obligatorio",
        )
    fila.estado_abono = "confirmado" if confirmado else "rechazado"
    fila.referencia_externa = referencia.strip()
    fila.motivo_rechazo_externo = motivo.strip()
    # `flush` explícito: la sesión no tiene autoflush, así que sin esto la
    # confirmación se queda en memoria y la comprobación de `cerrar` —que va por
    # SQL— seguiría viendo el abono como pendiente. Es el fallo que hace que el
    # cierre no funcione justo después de confirmar.
    uow.db.flush()
    return fila


def cerrar(uow: UnidadDeTrabajo, devolucion_id: UUID, *, disposicion: str) -> Devolucion:
    """Cierra la devolución. **Exige disposición del material.**

    Una devolución cerrada sin disposición es una pieza que consta devuelta y que
    nadie ha vuelto a ver. El almacén acaba con una estantería de material que no
    está en ningún inventario.
    """
    if disposicion not in DISPOSICIONES or disposicion == "pendiente":
        raise ErrorValidacion(
            "Cerrar exige decir qué se hace con el material: reacondicionar, "
            "reparar, chatarra o devolver al proveedor.",
            error_code="postventa.disposicion_obligatoria",
            detalle={"validas": [d for d in DISPOSICIONES if d != "pendiente"]},
        )
    fila = _devolucion(uow.db, uow.tenant_id, devolucion_id)
    if fila.estado not in ("inspeccionada", "resuelta"):
        raise Conflicto(
            "Todavía no se puede cerrar",
            error_code="postventa.no_cerrable",
            detalle={"estado": fila.estado},
        )
    abonos_pendientes = (
        uow.db.execute(
            select(Resolucion).where(
                Resolucion.tenant_id == uow.tenant_id,
                Resolucion.devolucion_id == fila.id,
                Resolucion.tipo == "abono",
                Resolucion.estado_abono == "solicitado",
            )
        )
        .scalars()
        .all()
    )
    if abonos_pendientes:
        raise Conflicto(
            "Hay un abono pedido que todavía no ha confirmado quien factura: "
            "cerrar ahora dejaría al cliente esperando un dinero que nadie ha emitido.",
            error_code="postventa.abono_pendiente",
            detalle={"resoluciones": [str(r.id) for r in abonos_pendientes]},
        )

    fila.disposicion = disposicion
    fila.estado = "cerrada"
    fila.cerrada_at = _ahora()
    if fila.activo_id and disposicion in ("chatarra", "proveedor"):
        # Si la máquina devuelta era un activo instalado, deja de estarlo. Sin
        # esto, el parque del cliente sigue contando algo que está en nuestro
        # almacén o destruido.
        act.cambiar_estado(
            uow, fila.activo_id, estado="retirado", motivo=f"Devuelto (RMA {fila.codigo})"
        )
    uow.db.flush()
    uow.emitir(
        "return.closed",
        subject=("devolucion", fila.id),
        data={"devolucion_id": str(fila.id), "disposicion": disposicion},
    )
    return fila


def resumen_devolucion(db: Session, tenant_id: UUID, devolucion_id: UUID) -> dict[str, Any]:
    """La devolución con sus líneas y sus resoluciones."""
    fila = _devolucion(db, tenant_id, devolucion_id)
    lineas = (
        db.execute(
            select(LineaDevolucion).where(
                LineaDevolucion.tenant_id == tenant_id,
                LineaDevolucion.devolucion_id == devolucion_id,
            )
        )
        .scalars()
        .all()
    )
    resoluciones = (
        db.execute(
            select(Resolucion).where(
                Resolucion.tenant_id == tenant_id, Resolucion.devolucion_id == devolucion_id
            )
        )
        .scalars()
        .all()
    )
    return {
        "id": str(fila.id),
        "codigo": fila.codigo,
        "estado": fila.estado,
        "motivo": fila.motivo,
        "fuera_de_plazo": fila.fuera_de_plazo,
        "disposicion": fila.disposicion,
        "lineas": [
            {
                "id": str(line.id),
                "concepto": line.concepto,
                "cantidad": str(line.cantidad),
                "cantidad_recibida": (
                    str(line.cantidad_recibida) if line.cantidad_recibida is not None else None
                ),
                "numero_serie": line.numero_serie,
                "estado_material": line.estado_material,
                "disposicion": line.disposicion,
            }
            for line in lineas
        ],
        "resoluciones": [
            {
                "id": str(r.id),
                "tipo": r.tipo,
                "a_cargo_de": r.a_cargo_de,
                "importe": str(r.importe) if r.importe is not None else None,
                "estado_abono": r.estado_abono,
                "referencia_externa": r.referencia_externa,
            }
            for r in resoluciones
        ],
        # Lo pendiente de cobrar/abonar por separado: es lo que hace que una
        # devolución «cerrada» siga teniendo dinero en el aire.
        "abonos_pendientes": len(
            [r for r in resoluciones if r.tipo == "abono" and r.estado_abono == "solicitado"]
        ),
        "lineas_sin_disposicion": len([line for line in lineas if line.disposicion == "pendiente"]),
    }


# ── Expedientes y plazos legales (CRM-04.05.01.03) ────────────────────────


def _sumar_dias_habiles(
    db: Session, tenant_id: UUID, desde: datetime, dias: int, calendario_clave: str = ""
) -> tuple[datetime, bool]:
    """Suma días hábiles con el calendario laboral del tenant.

    Devuelve además si se pudo usar el calendario. Sin calendario se cuentan
    **días naturales y se dice**: no es lo mismo, y dejar que lo parezca es cómo
    un plazo de «diez días hábiles» vence en Navidad sin que nadie lo entienda.
    """
    calendario = db.execute(
        select(CalendarioLaboral)
        .where(CalendarioLaboral.tenant_id == tenant_id)
        .where(
            CalendarioLaboral.clave == calendario_clave
            if calendario_clave
            else CalendarioLaboral.por_defecto.is_(True)
        )
        .limit(1)
    ).scalar_one_or_none()
    if calendario is None:
        logger.warning("postventa.plazo_sin_calendario", tenant=str(tenant_id))
        return desde + timedelta(days=dias), False

    momento = desde
    restantes = dias
    vueltas = 0
    while restantes > 0 and vueltas < dias * 10 + 30:
        momento += timedelta(days=1)
        vueltas += 1
        # Se pregunta por el mediodía: un día es hábil o no lo es, y preguntar a
        # la hora exacta de entrada haría que una reclamación de las 21:00
        # contara ese día como no hábil siempre.
        mediodia = momento.replace(hour=12, minute=0, second=0, microsecond=0)
        if es_laborable(db, calendario, mediodia):
            restantes -= 1
    return momento, True


def abrir_expediente(
    uow: UnidadDeTrabajo,
    *,
    asunto: str,
    entrada_at: datetime,
    plazo_dias: int | None = None,
    plazo_habiles: bool = False,
    tipo: str = "reclamacion",
    via: str = "",
    organismo: str = "",
    referencia_externa: str = "",
    descripcion: str = "",
    cuenta_id: UUID | None = None,
    contacto_id: UUID | None = None,
    caso_id: UUID | None = None,
    devolucion_id: UUID | None = None,
    calendario: str = "",
) -> tuple[Expediente, list[str]]:
    """Abre un expediente con su plazo calculado (CRM-04.05.01.03).

    El plazo cuenta **desde que entró la reclamación**, no desde que se grabó en
    el sistema. Esa diferencia es el tiempo que estuvo en un cajón, y se la come
    la empresa, no el cliente.

    El vencimiento se guarda calculado: una norma nueva no puede convertir en
    incumplidos expedientes que se contestaron a tiempo con la de entonces.
    """
    if not asunto.strip():
        raise ErrorValidacion(
            "Un expediente sin asunto no se puede tramitar.",
            error_code="postventa.asunto_obligatorio",
        )
    entrada = _con_tz(entrada_at) or _ahora()
    if entrada > _ahora() + timedelta(days=1):
        raise ErrorValidacion(
            "La fecha de entrada está en el futuro: el plazo empezaría a correr "
            "cuando ya se ha pasado.",
            error_code="postventa.entrada_futura",
        )
    dias = int(
        plazo_dias
        if plazo_dias is not None
        else (rt.efectivo("expediente_plazo_dias", uow.db) or 30)
    )

    avisos: list[str] = []
    if plazo_habiles:
        vence, con_calendario = _sumar_dias_habiles(
            uow.db, uow.tenant_id, entrada, dias, calendario
        )
        if not con_calendario:
            avisos.append(
                "No hay calendario laboral configurado: el plazo se ha contado en días "
                "naturales y vencerá antes de lo que marca la norma."
            )
    else:
        vence = entrada + timedelta(days=dias)

    retraso = (_ahora() - entrada).days
    if retraso >= 1:
        avisos.append(
            f"La reclamación entró hace {retraso} día(s) y se registra ahora: ese "
            "tiempo ya se ha consumido del plazo."
        )

    fila = Expediente(
        tenant_id=uow.tenant_id,
        asunto=asunto.strip(),
        tipo=tipo,
        via=via,
        organismo=organismo,
        referencia_externa=referencia_externa,
        descripcion=descripcion,
        cuenta_id=cuenta_id,
        contacto_id=contacto_id,
        caso_id=caso_id,
        devolucion_id=devolucion_id,
        entrada_at=entrada,
        plazo_dias=dias,
        plazo_habiles=plazo_habiles,
        vence_at=vence,
        hitos=[{"fecha": entrada.isoformat(), "hito": "entrada", "nota": via or ""}],
    )
    uow.db.add(fila)
    uow.db.flush()
    fila.codigo = _siguiente_codigo(uow.db, uow.tenant_id, Expediente, "EXP")
    uow.emitir(
        "complaint.opened",
        subject=("expediente", fila.id),
        data={
            "expediente_id": str(fila.id),
            "tipo": fila.tipo,
            "vence_at": fila.vence_at.isoformat(),
        },
    )
    return fila, avisos


def acusar_recibo(
    uow: UnidadDeTrabajo,
    expediente_id: UUID,
    *,
    documento_id: UUID | None = None,
    cuando: datetime | None = None,
) -> Expediente:
    """Deja constancia de que se acusó recibo.

    Sin acuse, «contestamos a tiempo» no se puede demostrar — y demostrarlo es
    justo lo que hace falta cuando la reclamación llega por un organismo.
    """
    fila = uow.db.get(Expediente, expediente_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado(
            "El expediente no existe", error_code="postventa.expediente_no_encontrado"
        )
    fila.acuse_at = cuando or _ahora()
    fila.acuse_documento_id = documento_id
    uow.db.flush()
    fila.hitos = [
        *(fila.hitos or []),
        {"fecha": fila.acuse_at.isoformat(), "hito": "acuse", "documento": str(documento_id or "")},
    ]
    uow.db.flush()
    return fila


def suspender(uow: UnidadDeTrabajo, expediente_id: UUID, *, motivo: str) -> Expediente:
    """Para el reloj legal. **Solo por un motivo tipificado.**

    Si el motivo fuera texto libre, el plazo se suspendería por «mucho trabajo» y
    dejaría de ser un plazo. Los cuatro admitidos son los que la norma reconoce:
    pedir subsanación, prueba pericial, traslado a un tercero y acuerdo con el
    cliente.
    """
    if motivo not in MOTIVOS_SUSPENSION:
        raise ErrorValidacion(
            f"Motivo de suspensión «{motivo}» no admitido.",
            error_code="postventa.suspension_no_valida",
            detalle={"validos": list(MOTIVOS_SUSPENSION)},
        )
    fila = uow.db.get(Expediente, expediente_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado(
            "El expediente no existe", error_code="postventa.expediente_no_encontrado"
        )
    if fila.estado != "abierto":
        raise Conflicto(
            "Solo se suspende un expediente abierto",
            error_code="postventa.no_abierto",
            detalle={"estado": fila.estado},
        )
    fila.estado = "suspendido"
    fila.suspendido_desde = _ahora()
    fila.motivo_suspension = motivo
    fila.hitos = [
        *(fila.hitos or []),
        {"fecha": fila.suspendido_desde.isoformat(), "hito": "suspension", "motivo": motivo},
    ]
    uow.db.flush()
    return fila


def reanudar(uow: UnidadDeTrabajo, expediente_id: UUID) -> Expediente:
    """Reanuda el reloj y **desplaza el vencimiento** lo que estuvo parado.

    Desplazarlo es la única forma honesta: dejar el vencimiento donde estaba
    haría que una suspensión legítima de una semana se comiera el plazo de
    respuesta, y quien suspendió no lo sabría hasta que venciera.
    """
    fila = uow.db.get(Expediente, expediente_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado(
            "El expediente no existe", error_code="postventa.expediente_no_encontrado"
        )
    if fila.estado != "suspendido" or fila.suspendido_desde is None:
        raise Conflicto(
            "Ese expediente no está suspendido",
            error_code="postventa.no_suspendido",
            detalle={"estado": fila.estado},
        )
    parado = _ahora() - (_con_tz(fila.suspendido_desde) or _ahora())
    fila.suspendido_seg += int(parado.total_seconds())
    fila.vence_at = (_con_tz(fila.vence_at) or _ahora()) + parado
    fila.estado = "abierto"
    fila.suspendido_desde = None
    fila.hitos = [
        *(fila.hitos or []),
        {
            "fecha": _ahora().isoformat(),
            "hito": "reanudacion",
            "parado_dias": round(parado.total_seconds() / 86400, 2),
        },
    ]
    uow.db.flush()
    return fila


def responder(
    uow: UnidadDeTrabajo,
    expediente_id: UUID,
    *,
    respuesta: str,
    resultado: str = "",
    documento_id: UUID | None = None,
    cuando: datetime | None = None,
) -> dict[str, Any]:
    """Cierra el expediente con la respuesta, y dice **si se llegó a tiempo**.

    El cumplimiento se calcula y se guarda en el momento de responder, no se
    deduce después comparando fechas: la fecha de vencimiento puede desplazarse
    por una suspensión posterior, y entonces un incumplimiento se convertiría en
    cumplimiento sin que nadie lo decidiera.
    """
    if not respuesta.strip():
        raise ErrorValidacion(
            "Cerrar un expediente exige la respuesta que se dio.",
            error_code="postventa.respuesta_obligatoria",
        )
    fila = uow.db.get(Expediente, expediente_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado(
            "El expediente no existe", error_code="postventa.expediente_no_encontrado"
        )
    if fila.estado in ("resuelto", "desistido"):
        raise Conflicto(
            "Ese expediente ya está cerrado",
            error_code="postventa.ya_cerrado",
            detalle={"estado": fila.estado},
        )
    momento = _con_tz(cuando) or _ahora()
    vence = _con_tz(fila.vence_at) or momento
    en_plazo = momento <= vence

    fila.respondido_at = momento
    fila.respuesta = respuesta.strip()
    fila.respuesta_documento_id = documento_id
    fila.resultado = resultado
    fila.estado = "resuelto"
    fila.hitos = [
        *(fila.hitos or []),
        {
            "fecha": momento.isoformat(),
            "hito": "respuesta",
            "en_plazo": en_plazo,
            "resultado": resultado,
        },
    ]
    uow.db.flush()
    registrar(
        uow.db,
        accion="postventa.expediente_respondido",
        objeto="expediente",
        objeto_id=fila.id,
        datos={"en_plazo": en_plazo, "vencia": vence.isoformat(), "resultado": resultado},
        tenant_id=uow.tenant_id,
    )
    uow.emitir(
        "complaint.answered",
        subject=("expediente", fila.id),
        data={"expediente_id": str(fila.id), "en_plazo": en_plazo},
    )
    return {
        "expediente_id": str(fila.id),
        "en_plazo": en_plazo,
        "vencia_at": vence.isoformat(),
        "respondido_at": momento.isoformat(),
        # Sin acuse de recibo no se puede demostrar cuándo entró, y entonces «en
        # plazo» es nuestra palabra contra la suya.
        "demostrable": fila.acuse_at is not None,
    }


def vencen_pronto(
    db: Session, tenant_id: UUID, *, horas: int = 48, ahora: datetime | None = None
) -> dict[str, Any]:
    """Qué expedientes vencen ya, y cuáles han vencido sin contestar.

    Los vencidos van **aparte**: mezclarlos con los que están a punto hace que la
    lista se lea como una cola de trabajo y no como lo que es — un incumplimiento
    que ya no se puede evitar, solo explicar.
    """
    momento = ahora or _ahora()
    limite = momento + timedelta(hours=horas)
    filas = (
        db.execute(
            select(Expediente)
            .where(
                Expediente.tenant_id == tenant_id,
                Expediente.estado.in_(("abierto", "suspendido")),
                Expediente.vence_at <= limite,
            )
            .order_by(Expediente.vence_at)
        )
        .scalars()
        .all()
    )
    pronto, vencidos = [], []
    for fila in filas:
        vence = _con_tz(fila.vence_at) or momento
        dato = {
            "expediente_id": str(fila.id),
            "codigo": fila.codigo,
            "asunto": fila.asunto,
            "estado": fila.estado,
            "vence_at": vence.isoformat(),
            "horas": round((vence - momento).total_seconds() / 3600, 1),
            "suspendido": fila.estado == "suspendido",
            "sin_acuse": fila.acuse_at is None,
        }
        (vencidos if vence < momento else pronto).append(dato)
    return {
        "en_fecha": momento.isoformat(),
        "ventana_horas": horas,
        "vencen_pronto": pronto,
        "ya_vencidos": vencidos,
        # Un expediente suspendido no corre, pero su vencimiento sigue en la
        # lista: quien lo mire tiene que ver que está parado y no asumir que va
        # tarde.
        "suspendidos": len([f for f in filas if f.estado == "suspendido"]),
    }
