"""Encargos seguidos: lo que se encarga a un tercero y hay que seguir
(CRM-00.04.05.01 a .04, .06 a .10, CRM-00.04.04.06).

Un operador logístico sigue envíos. Un instalador sigue instalaciones. Una
aseguradora sigue peritajes. Los tres necesitan lo mismo: una referencia externa,
un estado que cambia solo, unos hitos con fecha, unas incidencias y una prueba de
que se hizo.

**Por eso el modelo es genérico y no de paquetería.** Un objeto «envío» con bultos
y código postal deja fuera al instalador y al perito; un «encargo seguido» con
estados declarados por el conector sirve a los tres, y el módulo vertical
(CRM-00.04.04) le pone el vocabulario de su sector. Con un modelo por sector,
cada cliente nuevo es una versión del producto.

Cuatro decisiones que gobiernan el módulo:

**El mapa de estados es del conector, no del código.** GLS dice `ENTREGADO`, otro
dice `DELIVERED` y un tercero manda un número. Traducirlo en el código significa
tocar el producto por cada transportista; declararlo significa una fila.

**La ingesta es idempotente y ordenada por encargo.** Las pasarelas reintentan y
los webhooks llegan desordenados. Sin idempotencia, un reintento duplica el hito;
sin orden, «entregado» puede aplicarse antes que «en reparto» y el cliente ve que
su paquete retrocede.

**Un encargo sin novedad no se da por bueno.** El fallo más caro de una
integración de seguimiento no es el error: es el silencio. Un envío del que el
transportista no dice nada durante cuatro días parece que va bien, y no va bien.

**El cliente ve su seguimiento, no el nuestro.** El coste, el proveedor alternativo
y las notas internas no salen — y eso se decide aquí, no en quien pinta la
pantalla.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
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

logger = get_logger(__name__)

# Estados canónicos del sistema. Cerrados a propósito: son a los que cada
# conector traduce los suyos. Con estados libres, dos transportistas reportarían
# «en_ruta» y «EN_RUTA» y ningún informe podría agruparlos.
ESTADOS = (
    "creado",
    "aceptado",
    "recogido",
    "en_curso",
    "en_entrega",
    "completado",
    "incidencia",
    "devuelto",
    "cancelado",
)
TERMINALES = ("completado", "devuelto", "cancelado")

# Quién tiene la culpa de una incidencia. Se declara porque decide dos cosas
# distintas: si se le reclama al proveedor y si cuenta en su cumplimiento.
RESPONSABLES = ("proveedor", "nuestro", "cliente", "tercero", "sin_determinar")


class Proveedor(Base, TimestampMixin):
    """Un tercero al que se le encargan cosas (CRM-00.04.04.06).

    El conector va **dentro** del proveedor y sobre el transporte genérico: lo
    que cambia entre GLS y otro es la dirección, la credencial y el mapa de
    estados, no el código. Un conector por casa haría que cada cliente con un
    transportista distinto fuera una versión del producto.
    """

    __tablename__ = "proveedores_servicio"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(60), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    # Módulo vertical que lo trajo, si vino en uno. Sirve para saber qué se va
    # al desinstalarlo.
    modulo: Mapped[str | None] = mapped_column(String(60), nullable=True)
    conexion_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # Mapa de estados del proveedor a los del sistema (CRM-00.04.05.02).
    # {"ENTREGADO": "completado", "EN_RUTA": "en_curso"}
    mapa_estados: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Plazo prometido en horas. De aquí sale si un encargo va tarde y si el
    # proveedor cumple.
    plazo_horas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Horas sin novedad a partir de las cuales el encargo se marca mudo. El
    # silencio es el fallo más caro de una integración de seguimiento.
    silencio_horas: Mapped[int] = mapped_column(Integer, nullable=False, default=48)
    coste_base: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "clave", name="uq_proveedor_servicio"),)


class ReglaProveedor(Base, TimestampMixin):
    """A qué proveedor le toca cada encargo (CRM-00.04.05.07)."""

    __tablename__ = "reglas_proveedor"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    prioridad: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Condiciones en la gramática de ABAC, como el resto del producto.
    condiciones: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    proveedor: Mapped[str] = mapped_column(String(60), nullable=False)
    # Proveedores a los que ir si el primero falla, en orden. Sin alternativa,
    # una caída del transportista habitual para la operación entera.
    alternativos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "nombre", name="uq_regla_proveedor"),
        Index("ix_reglas_proveedor_orden", "tenant_id", "activa", "prioridad"),
    )


class Encargo(Base, TimestampMixin):
    """Algo encargado a un tercero que hay que seguir (CRM-00.04.05.01)."""

    __tablename__ = "encargos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    proveedor: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    # La referencia del proveedor. Es la que el cliente escribe en su web y la
    # que se dice por teléfono; sin ella, el seguimiento no se puede cruzar.
    referencia_externa: Mapped[str | None] = mapped_column(String(120), nullable=True)
    referencia_propia: Mapped[str] = mapped_column(String(60), nullable=False)

    # De qué registro cuelga. Identificadores opacos: la oportunidad vive en
    # `sales` y el caso en `service`, y ningún servicio lee el esquema de otro.
    objeto_origen: Mapped[str | None] = mapped_column(String(40), nullable=True)
    objeto_origen_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    contacto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="creado", index=True)
    # El estado tal como lo dice el proveedor, sin traducir. Se guarda porque es
    # lo que hay que citar al reclamarle, y porque cuando aparece un estado que
    # no está en el mapa, tenerlo es lo único que permite añadirlo.
    estado_proveedor: Mapped[str | None] = mapped_column(String(80), nullable=True)

    prometido_para: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    completado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ultima_novedad_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # Se marca cuando lleva demasiado sin novedad. No es un estado: un encargo
    # mudo sigue estando «en curso» según el proveedor, y mezclarlo con los
    # estados haría perder el último que sí dijo.
    mudo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    coste_previsto: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    coste_facturado: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")

    # Datos propios del sector, que pone el módulo vertical.
    datos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Lo que no se le enseña al cliente: coste, notas, proveedor alternativo.
    interno: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "referencia_propia", name="uq_encargo_referencia"),
        Index("ix_encargos_externa", "tenant_id", "proveedor", "referencia_externa"),
        Index("ix_encargos_seguimiento", "tenant_id", "estado", "prometido_para"),
    )


class HitoEncargo(Base):
    """Un evento del proveedor sobre el encargo (CRM-00.04.05.03).

    Append-only y con el identificador del evento del proveedor dentro: es lo que
    hace la ingesta idempotente. Las pasarelas reintentan, y sin esto un reintento
    duplicaría el hito y el cliente vería dos veces «salió de almacén».
    """

    __tablename__ = "hitos_encargo"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    encargo_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("encargos.id", ondelete="CASCADE"), nullable=False
    )
    id_externo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    estado: Mapped[str] = mapped_column(String(20), nullable=False)
    estado_proveedor: Mapped[str | None] = mapped_column(String(80), nullable=True)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    lugar: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Cuándo ocurrió **según el proveedor**, que no es cuándo nos enteramos. La
    # diferencia entre las dos es la latencia de la integración, y sin las dos no
    # se puede saber si un retraso fue del transportista o nuestro.
    ocurrio_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recibido_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Si se aplicó al encargo o se descartó por llegar desordenado.
    aplicado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    motivo_descarte: Mapped[str | None] = mapped_column(String(200), nullable=True)
    crudo: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "encargo_id", "id_externo", name="uq_hito_externo"),
        Index("ix_hitos_encargo", "tenant_id", "encargo_id", "ocurrio_at"),
    )


class IncidenciaEncargo(Base, TimestampMixin):
    """Algo que ha ido mal en el encargo (CRM-00.04.05.04)."""

    __tablename__ = "incidencias_encargo"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    encargo_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("encargos.id", ondelete="CASCADE"), nullable=False
    )
    # Tipo del árbol que trae el módulo vertical: «retraso/aduana»,
    # «dano/embalaje». Va como texto y no como clave foránea porque la taxonomía
    # vive en `service` y ningún servicio lee el esquema de otro.
    tipo: Mapped[str] = mapped_column(String(120), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    responsable: Mapped[str] = mapped_column(String(20), nullable=False, default="sin_determinar")
    # Caso de soporte que la atiende. Enlazarla y no duplicarla: el cliente
    # escribe al soporte, no a la integración, y tener dos hilos sobre el mismo
    # problema es cómo se le contesta dos cosas distintas.
    caso_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    abierta: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    resuelta_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    coste_asumido: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    __table_args__ = (Index("ix_incidencias_encargo", "tenant_id", "encargo_id", "abierta"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _con_tz(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


def _proveedor(db: Session, tenant_id: UUID, clave: str) -> Proveedor:
    fila = db.execute(
        select(Proveedor).where(Proveedor.tenant_id == tenant_id, Proveedor.clave == clave)
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado(
            f"No hay ningún proveedor «{clave}» configurado",
            error_code="integration.proveedor_no_encontrado",
        )
    return fila


def _encargo(db: Session, tenant_id: UUID, encargo_id: UUID) -> Encargo:
    fila = db.execute(
        select(Encargo).where(Encargo.id == encargo_id, Encargo.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("El encargo no existe", error_code="integration.encargo_no_encontrado")
    return fila


# ── Mapa de estados (CRM-00.04.05.02) ─────────────────────────────────────


def traducir_estado(proveedor: Proveedor, crudo: str) -> tuple[str | None, str]:
    """Traduce el estado del proveedor al canónico.

    Devuelve `None` cuando no lo conoce, **y eso no se convierte en un estado por
    defecto**: adivinar que un estado desconocido es «en curso» hace que un
    encargo devuelto o cancelado siga contando como en camino, y nadie lo mira
    hasta que el cliente pregunta. Se deja sin traducir y se avisa, que es lo
    único que hace que alguien añada el estado al mapa.
    """
    mapa = {str(k).strip().upper(): str(v) for k, v in (proveedor.mapa_estados or {}).items()}
    destino = mapa.get(str(crudo).strip().upper())
    if destino is None:
        return None, (
            f"«{crudo}» no está en el mapa de estados de «{proveedor.clave}». "
            "Añádelo para que el seguimiento lo entienda."
        )
    if destino not in ESTADOS:
        return None, (
            f"El mapa de «{proveedor.clave}» traduce «{crudo}» a «{destino}», que "
            f"no es un estado del sistema. Los válidos: {', '.join(ESTADOS)}."
        )
    return destino, ""


# ── Elegir proveedor (CRM-00.04.05.07) ────────────────────────────────────


def elegir_proveedor(
    db: Session, tenant_id: UUID, datos: dict[str, Any]
) -> tuple[str, list[str], str]:
    """Qué proveedor le toca a este encargo y cuáles son sus alternativas.

    Gana **la primera regla que encaja**, como en el reparto de leads y de casos:
    una sola gramática en todo el producto, y un resultado que se puede explicar.

    Se devuelven también los **alternativos**: sin ellos, una caída del
    transportista habitual para la operación entera, y la única salida es que
    alguien los cambie a mano uno a uno.
    """
    from crmcore.authz.abac import Condicion

    reglas = (
        db.execute(
            select(ReglaProveedor)
            .where(ReglaProveedor.tenant_id == tenant_id, ReglaProveedor.activa.is_(True))
            .order_by(ReglaProveedor.prioridad, ReglaProveedor.nombre)
        )
        .scalars()
        .all()
    )
    ambito = {"encargo": datos}
    for regla in reglas:
        condiciones = [
            Condicion(
                atributo=str(c.get("atributo", "")),
                operador=str(c.get("operador", "=")),
                valor=c.get("valor"),
            )
            for c in (regla.condiciones or [])
            if isinstance(c, dict)
        ]
        if all(c.evaluar(ambito) for c in condiciones):
            return regla.proveedor, [str(a) for a in (regla.alternativos or [])], regla.nombre

    activos = (
        db.execute(
            select(Proveedor)
            .where(Proveedor.tenant_id == tenant_id, Proveedor.activo.is_(True))
            .order_by(Proveedor.clave)
        )
        .scalars()
        .all()
    )
    if not activos:
        raise ErrorValidacion(
            "No hay ningún proveedor configurado ni regla que elija uno.",
            error_code="integration.sin_proveedor",
        )
    # Sin regla que encaje se usa el primero activo **y se dice**: elegir en
    # silencio haría que un encargo saliera por un transportista que nadie
    # decidió, y eso solo se descubre en la factura.
    return activos[0].clave, [], "(sin regla: primer proveedor activo)"


# ── Alta y seguimiento (CRM-00.04.05.01) ──────────────────────────────────


def _siguiente_referencia(db: Session, tenant_id: UUID) -> str:
    anio = date.today().year
    cuantos = int(
        db.execute(
            select(func.count()).select_from(Encargo).where(Encargo.tenant_id == tenant_id)
        ).scalar_one()
        or 0
    )
    return f"ENC-{anio}-{cuantos + 1:06d}"


def crear(
    uow: UnidadDeTrabajo,
    *,
    proveedor: str = "",
    datos: dict[str, Any] | None = None,
    **campos: Any,
) -> Encargo:
    """Da de alta un encargo y le pone su plazo."""
    tenant_id = uow.tenant_id
    datos = datos or {}
    alternativos: list[str] = []
    regla = ""
    if not proveedor:
        proveedor, alternativos, regla = elegir_proveedor(uow.db, tenant_id, datos)

    ficha = _proveedor(uow.db, tenant_id, proveedor)
    if not ficha.activo:
        raise Conflicto(
            f"El proveedor «{proveedor}» está desactivado.",
            error_code="integration.proveedor_inactivo",
        )

    fila = Encargo(
        tenant_id=tenant_id,
        proveedor=proveedor,
        referencia_propia=_siguiente_referencia(uow.db, tenant_id),
        datos=datos,
        coste_previsto=ficha.coste_base,
        ultima_novedad_at=_ahora(),
        **campos,
    )
    if ficha.plazo_horas and fila.prometido_para is None:
        fila.prometido_para = _ahora() + timedelta(hours=ficha.plazo_horas)
    fila.interno = {
        **(fila.interno or {}),
        "alternativos": alternativos,
        "regla_de_eleccion": regla,
    }
    uow.db.add(fila)
    uow.db.flush()

    uow.db.add(
        HitoEncargo(
            tenant_id=tenant_id,
            encargo_id=fila.id,
            estado="creado",
            descripcion=f"Encargo creado y asignado a «{proveedor}»",
            ocurrio_at=_ahora(),
        )
    )
    # Se escribe ya: sin este `flush` el primer hito solo existe en memoria y
    # cualquier consulta hecha en la misma transacción —la propia pantalla que
    # se abre justo después— enseñaría un encargo sin historia.
    uow.db.flush()
    uow.emitir(
        "order.tracked.created",
        subject=("encargo", fila.id),
        data={
            "encargo_id": str(fila.id),
            "referencia": fila.referencia_propia,
            "proveedor": proveedor,
            "objeto_origen": fila.objeto_origen or "",
            "objeto_origen_id": str(fila.objeto_origen_id) if fila.objeto_origen_id else "",
        },
    )
    return fila


# ── Ingesta de eventos (CRM-00.04.05.03) ──────────────────────────────────

# Orden de los estados para detectar los que llegan desordenados. Un webhook
# puede llegar después del siguiente, y aplicar «en reparto» después de
# «entregado» haría que el cliente viera su paquete retroceder.
ORDEN_ESTADO = {e: i for i, e in enumerate(ESTADOS)}


def ingerir(
    uow: UnidadDeTrabajo,
    *,
    proveedor: str,
    referencia_externa: str = "",
    referencia_propia: str = "",
    estado_proveedor: str = "",
    ocurrio_at: datetime | None = None,
    id_externo: str = "",
    descripcion: str = "",
    lugar: str = "",
    crudo: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aplica un evento del proveedor, venga de webhook o de sondeo.

    **Idempotente por el identificador del evento**: las pasarelas reintentan, y
    sin esto un reintento duplicaría el hito y el cliente vería dos veces «salió
    de almacén».

    **Ordenado por encargo**: un hito más antiguo que el estado actual se guarda
    pero **no se aplica**. Guardarlo importa —es la prueba de lo que dijo el
    proveedor y cuándo— y no aplicarlo también, porque un paquete que retrocede
    en la pantalla es una llamada al servicio de atención.
    """
    tenant_id = uow.tenant_id
    ficha = _proveedor(uow.db, tenant_id, proveedor)

    consulta = select(Encargo).where(Encargo.tenant_id == tenant_id, Encargo.proveedor == proveedor)
    if referencia_propia:
        consulta = consulta.where(Encargo.referencia_propia == referencia_propia)
    elif referencia_externa:
        consulta = consulta.where(Encargo.referencia_externa == referencia_externa)
    else:
        raise ErrorValidacion(
            "Hace falta una referencia para saber de qué encargo se habla.",
            error_code="integration.evento_sin_referencia",
        )
    encargo = uow.db.execute(consulta).scalar_one_or_none()
    if encargo is None:
        # No se crea uno sobre la marcha: un evento de un encargo que no consta
        # suele ser una referencia mal escrita o de otro tenant, y crearlo
        # llenaría la base de encargos fantasma que nadie reclama.
        raise NoEncontrado(
            "No hay ningún encargo con esa referencia para ese proveedor",
            error_code="integration.encargo_no_encontrado",
        )

    if id_externo:
        ya = uow.db.execute(
            select(HitoEncargo).where(
                HitoEncargo.tenant_id == tenant_id,
                HitoEncargo.encargo_id == encargo.id,
                HitoEncargo.id_externo == id_externo,
            )
        ).scalar_one_or_none()
        if ya is not None:
            return {
                "aplicado": False,
                "duplicado": True,
                "encargo_id": str(encargo.id),
                "estado": encargo.estado,
            }

    destino, aviso = traducir_estado(ficha, estado_proveedor)
    momento = _con_tz(ocurrio_at) or _ahora()

    desordenado = (
        destino is not None
        and ORDEN_ESTADO.get(destino, 0) < ORDEN_ESTADO.get(encargo.estado, 0)
        and encargo.estado not in ("incidencia",)
    )
    aplicado = destino is not None and not desordenado

    hito = HitoEncargo(
        tenant_id=tenant_id,
        encargo_id=encargo.id,
        id_externo=id_externo or None,
        estado=destino or encargo.estado,
        estado_proveedor=estado_proveedor or None,
        descripcion=descripcion or None,
        lugar=lugar or None,
        ocurrio_at=momento,
        aplicado=aplicado,
        motivo_descarte=(
            aviso
            if destino is None
            else ("llegó después de un estado posterior" if desordenado else None)
        ),
        crudo=crudo or {},
    )
    uow.db.add(hito)

    # La novedad se anota **aunque el estado no se aplique**: el proveedor ha
    # hablado, y eso ya significa que el encargo no está mudo. Contar solo los
    # aplicados haría que un encargo con eventos que no entendemos pareciera
    # abandonado.
    encargo.ultima_novedad_at = _ahora()
    encargo.mudo = False

    if aplicado:
        encargo.estado = destino
        encargo.estado_proveedor = estado_proveedor or encargo.estado_proveedor
        if destino == "completado" and encargo.completado_at is None:
            encargo.completado_at = momento
        if destino == "incidencia":
            uow.emitir(
                "order.tracked.incident",
                subject=("encargo", encargo.id),
                data={
                    "encargo_id": str(encargo.id),
                    "referencia": encargo.referencia_propia,
                    "proveedor": proveedor,
                    "estado_proveedor": estado_proveedor,
                    "descripcion": descripcion,
                },
            )
        uow.emitir(
            "order.tracked.updated",
            subject=("encargo", encargo.id),
            data={
                "encargo_id": str(encargo.id),
                "referencia": encargo.referencia_propia,
                "estado": destino,
                "cuenta_id": str(encargo.cuenta_id) if encargo.cuenta_id else "",
            },
            dedup_key=f"encargo:{encargo.id}:{id_externo}" if id_externo else None,
        )
    elif destino is None:
        logger.warning(
            "integration.estado_sin_mapear",
            proveedor=proveedor,
            estado=estado_proveedor,
            encargo=str(encargo.id),
        )

    uow.db.flush()
    return {
        "aplicado": aplicado,
        "duplicado": False,
        "encargo_id": str(encargo.id),
        "estado": encargo.estado,
        "aviso": hito.motivo_descarte or "",
    }


def estados_sin_mapear(db: Session, tenant_id: UUID, *, dias: int = 30) -> list[dict[str, Any]]:
    """Estados que han llegado y no sabemos traducir.

    Es la lista que hay que mirar al integrar un proveedor nuevo: cada entrada es
    un evento que se guardó y no hizo nada, y el seguimiento del cliente se quedó
    parado sin que nadie fallara.
    """
    desde = _ahora() - timedelta(days=dias)
    filas = db.execute(
        select(Encargo.proveedor, HitoEncargo.estado_proveedor, func.count())
        .join(Encargo, Encargo.id == HitoEncargo.encargo_id)
        .where(
            HitoEncargo.tenant_id == tenant_id,
            HitoEncargo.aplicado.is_(False),
            HitoEncargo.estado_proveedor.isnot(None),
            HitoEncargo.recibido_at >= desde,
        )
        .group_by(Encargo.proveedor, HitoEncargo.estado_proveedor)
        .order_by(func.count().desc())
    ).all()
    return [{"proveedor": p, "estado_proveedor": e, "veces": int(c)} for p, e, c in filas]


# ── Incidencias (CRM-00.04.05.04) ─────────────────────────────────────────


def abrir_incidencia(
    uow: UnidadDeTrabajo,
    encargo_id: UUID,
    *,
    tipo: str,
    descripcion: str = "",
    responsable: str = "sin_determinar",
    caso_id: UUID | None = None,
) -> IncidenciaEncargo:
    """Abre una incidencia sobre el encargo.

    El **responsable** se declara porque decide dos cosas distintas: si se le
    reclama al proveedor y si cuenta en su cumplimiento. «Sin determinar» es un
    valor legítimo y el de partida: forzar a elegir en caliente hace que se
    marque lo primero, y ese dato después se usa para negociar contratos.

    La incidencia **se enlaza al caso, no lo duplica**: el cliente escribe al
    soporte, no a la integración, y tener dos hilos sobre el mismo problema es
    cómo se le acaba contestando dos cosas distintas.
    """
    if responsable not in RESPONSABLES:
        raise ErrorValidacion(
            f"Responsable «{responsable}» no válido.",
            error_code="integration.responsable_no_valido",
            detalle={"validos": list(RESPONSABLES)},
        )
    encargo = _encargo(uow.db, uow.tenant_id, encargo_id)
    fila = IncidenciaEncargo(
        tenant_id=encargo.tenant_id,
        encargo_id=encargo.id,
        tipo=tipo,
        descripcion=descripcion or None,
        responsable=responsable,
        caso_id=caso_id,
    )
    uow.db.add(fila)
    if encargo.estado not in TERMINALES:
        encargo.estado = "incidencia"
    uow.db.flush()

    registrar(
        uow.db,
        accion="integration.incidencia_abierta",
        objeto="encargo",
        objeto_id=encargo.id,
        datos={"tipo": tipo, "responsable": responsable, "proveedor": encargo.proveedor},
        tenant_id=encargo.tenant_id,
    )
    uow.emitir(
        "order.tracked.incident",
        subject=("encargo", encargo.id),
        data={
            "encargo_id": str(encargo.id),
            "referencia": encargo.referencia_propia,
            "proveedor": encargo.proveedor,
            "tipo": tipo,
            "responsable": responsable,
            "cuenta_id": str(encargo.cuenta_id) if encargo.cuenta_id else "",
        },
    )
    return fila


def resolver_incidencia(
    uow: UnidadDeTrabajo,
    incidencia_id: UUID,
    *,
    responsable: str = "",
    coste_asumido: Decimal | None = None,
) -> IncidenciaEncargo:
    """Cierra una incidencia, fijando de quién fue si no se sabía."""
    fila = uow.db.get(IncidenciaEncargo, incidencia_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado(
            "Incidencia no encontrada", error_code="integration.incidencia_no_encontrada"
        )
    if not fila.abierta:
        raise Conflicto(
            "Esa incidencia ya está cerrada", error_code="integration.incidencia_cerrada"
        )
    if responsable:
        if responsable not in RESPONSABLES:
            raise ErrorValidacion(
                f"Responsable «{responsable}» no válido.",
                error_code="integration.responsable_no_valido",
            )
        fila.responsable = responsable
    fila.coste_asumido = coste_asumido
    fila.abierta = False
    fila.resuelta_at = _ahora()
    return fila


# ── El encargo mudo (CRM-00.04.05.10) ─────────────────────────────────────


def revisar_silencios(uow: UnidadDeTrabajo, tenant_id: UUID) -> dict[str, Any]:
    """Marca los encargos de los que el proveedor no dice nada.

    **El fallo más caro de una integración de seguimiento no es el error: es el
    silencio.** Un envío del que el transportista no dice nada durante cuatro
    días parece que va bien —en la pantalla pone «en tránsito»— y no va bien.
    Nadie lo mira hasta que el cliente llama, y para entonces se ha perdido la
    semana de margen que había para arreglarlo.

    El plazo es **por proveedor**: uno que reporta cada hora y otro que reporta
    una vez al día no pueden medirse con la misma vara, y usar una sola llenaría
    la lista de falsos avisos hasta que nadie la mire.
    """
    ahora = _ahora()
    proveedores = {
        p.clave: p
        for p in uow.db.execute(select(Proveedor).where(Proveedor.tenant_id == tenant_id)).scalars()
    }
    abiertos = (
        uow.db.execute(
            select(Encargo).where(Encargo.tenant_id == tenant_id, Encargo.estado.not_in(TERMINALES))
        )
        .scalars()
        .all()
    )

    nuevos: list[dict[str, Any]] = []
    for encargo in abiertos:
        ficha = proveedores.get(encargo.proveedor)
        horas = (ficha.silencio_horas if ficha else 48) or 48
        ultima = _con_tz(encargo.ultima_novedad_at) or _con_tz(encargo.created_at) or ahora
        callado = (ahora - ultima) > timedelta(hours=horas)
        if callado and not encargo.mudo:
            encargo.mudo = True
            nuevos.append(
                {
                    "encargo_id": str(encargo.id),
                    "referencia": encargo.referencia_propia,
                    "proveedor": encargo.proveedor,
                    "estado": encargo.estado,
                    "horas_sin_novedad": int((ahora - ultima).total_seconds() // 3600),
                }
            )
            uow.emitir(
                "order.tracked.silent",
                subject=("encargo", encargo.id),
                data={
                    "encargo_id": str(encargo.id),
                    "referencia": encargo.referencia_propia,
                    "proveedor": encargo.proveedor,
                    "horas_sin_novedad": int((ahora - ultima).total_seconds() // 3600),
                },
                dedup_key=f"mudo:{encargo.id}",
            )
        elif not callado and encargo.mudo:
            encargo.mudo = False

    # El repaso escribe: marcar en memoria y devolver la lista dejaría un informe
    # que dice que hay tres encargos mudos y una base en la que no lo está
    # ninguno.
    uow.db.flush()
    return {
        "revisados": len(abiertos),
        "nuevos_mudos": nuevos,
        "mudos_totales": len([e for e in abiertos if e.mudo]),
        # Sin encargos abiertos no se dice «todo bien»: es que no hay nada que
        # vigilar, y un verde vacío se lee igual que uno ganado.
        "medible": bool(abiertos),
    }


# ── Lo que ve el cliente (CRM-00.04.05.06) ────────────────────────────────


def seguimiento_para_cliente(
    db: Session, tenant_id: UUID, encargo_id: UUID, *, cuenta_id: UUID | None = None
) -> dict[str, Any]:
    """El seguimiento tal como se le enseña al cliente.

    **El coste, el proveedor alternativo, la regla de elección y las notas
    internas no salen**, y eso se decide aquí y no en quien pinta la pantalla: si
    dependiera del front, bastaría una pantalla nueva que se olvidara de filtrar
    para enseñarle al cliente lo que nos cuesta su envío.

    Tampoco salen los hitos **no aplicados**: son eventos que no entendimos o que
    llegaron desordenados, y enseñarlos haría que el cliente viera su paquete
    retroceder o leyera un estado en el idioma del transportista.
    """
    encargo = _encargo(db, tenant_id, encargo_id)
    if cuenta_id is not None and encargo.cuenta_id != cuenta_id:
        # 404 y no 403: un 403 confirma que ese encargo existe, y con eso se
        # puede recorrer la base preguntando por referencias.
        raise NoEncontrado("El encargo no existe", error_code="integration.encargo_no_encontrado")

    hitos = (
        db.execute(
            select(HitoEncargo)
            .where(
                HitoEncargo.tenant_id == tenant_id,
                HitoEncargo.encargo_id == encargo.id,
                HitoEncargo.aplicado.is_(True),
            )
            .order_by(HitoEncargo.ocurrio_at)
        )
        .scalars()
        .all()
    )
    incidencias = (
        db.execute(
            select(IncidenciaEncargo).where(
                IncidenciaEncargo.tenant_id == tenant_id,
                IncidenciaEncargo.encargo_id == encargo.id,
            )
        )
        .scalars()
        .all()
    )

    return {
        "referencia": encargo.referencia_propia,
        "referencia_transportista": encargo.referencia_externa,
        "proveedor": encargo.proveedor,
        "estado": encargo.estado,
        "prometido_para": (encargo.prometido_para.isoformat() if encargo.prometido_para else None),
        "completado_at": encargo.completado_at.isoformat() if encargo.completado_at else None,
        "hitos": [
            {
                "estado": h.estado,
                "descripcion": h.descripcion,
                "lugar": h.lugar,
                "at": h.ocurrio_at.isoformat(),
            }
            for h in hitos
        ],
        # Se le dice que hay una incidencia y de qué tipo, pero **no de quién es
        # la culpa**: esa conversación se tiene hablando, no leyendo en una
        # pantalla que la culpa fue suya.
        "incidencias": [
            {"tipo": i.tipo, "abierta": i.abierta, "descripcion": i.descripcion}
            for i in incidencias
        ],
        # Y se dice si vamos tarde, porque el cliente lo va a notar igual y
        # enterarse por nosotros es distinto de enterarse esperando.
        "va_tarde": bool(
            encargo.prometido_para
            and encargo.estado not in TERMINALES
            and _con_tz(encargo.prometido_para) < _ahora()
        ),
        "sin_novedad": encargo.mudo,
    }


# ── Conciliación y cumplimiento (CRM-00.04.05.08, .09) ────────────────────


def conciliar(
    uow: UnidadDeTrabajo,
    *,
    proveedor: str,
    lineas: list[dict[str, Any]],
    tolerancia: Decimal = Decimal("0.01"),
) -> dict[str, Any]:
    """Compara lo que el proveedor factura con lo que consta entregado.

    Las tres diferencias se sacan **por separado** porque llevan a tres acciones
    distintas: lo facturado de más se reclama, lo facturado sin entregar se
    investiga, y lo entregado sin facturar se provisiona — nadie quiere la
    sorpresa de una factura de hace cuatro meses.
    """
    tenant_id = uow.tenant_id
    _proveedor(uow.db, tenant_id, proveedor)

    por_referencia = {
        str(linea.get("referencia") or ""): linea for linea in lineas if linea.get("referencia")
    }
    encargos = {
        e.referencia_externa or e.referencia_propia: e
        for e in uow.db.execute(
            select(Encargo).where(Encargo.tenant_id == tenant_id, Encargo.proveedor == proveedor)
        ).scalars()
    }

    diferencias: list[dict[str, Any]] = []
    sin_encargo: list[str] = []
    conciliadas = 0
    for referencia, linea in por_referencia.items():
        encargo = encargos.get(referencia)
        if encargo is None:
            sin_encargo.append(referencia)
            continue
        facturado = Decimal(str(linea.get("importe") or 0))
        encargo.coste_facturado = facturado
        previsto = encargo.coste_previsto or Decimal(0)
        if abs(facturado - previsto) > tolerancia:
            diferencias.append(
                {
                    "referencia": referencia,
                    "previsto": str(previsto),
                    "facturado": str(facturado),
                    "diferencia": str(facturado - previsto),
                    "estado": encargo.estado,
                    "entregado": encargo.estado == "completado",
                }
            )
        else:
            conciliadas += 1

    sin_facturar = [
        {"referencia": r, "previsto": str(e.coste_previsto or 0)}
        for r, e in encargos.items()
        if e.estado == "completado" and e.coste_facturado is None
    ]
    facturado_sin_entregar = [d for d in diferencias if not d["entregado"]]

    uow.db.flush()
    return {
        "proveedor": proveedor,
        "lineas": len(por_referencia),
        "conciliadas": conciliadas,
        "con_diferencia": diferencias,
        "facturado_sin_entregar": facturado_sin_entregar,
        "entregado_sin_facturar": sin_facturar,
        # Referencias que el proveedor factura y aquí no constan. No es un
        # error de cálculo: o falta un encargo o la referencia está mal, y las
        # dos exigen que alguien mire.
        "referencias_desconocidas": sin_encargo,
        "en_verde": not diferencias and not sin_encargo and not sin_facturar,
    }


def cumplimiento_proveedor(
    db: Session, tenant_id: UUID, *, desde: date, hasta: date
) -> list[dict[str, Any]]:
    """Plazo prometido contra real, incidencias y coste medio por proveedor.

    Es la tabla con la que se renegocia un contrato, y por eso se cuenta **solo lo
    que es suyo**: una incidencia cuya culpa fue del cliente o nuestra no cuenta
    contra el proveedor. Meterlas todas en el mismo saco hace que el número no se
    pueda defender en una reunión, y entonces no se usa.

    Sin encargos completados **no se dice que cumple el 100 %**: se dice que no es
    medible. Un proveedor recién contratado no ha demostrado nada.
    """
    inicio = datetime.combine(desde, datetime.min.time(), tzinfo=timezone.utc)
    fin = datetime.combine(hasta, datetime.max.time(), tzinfo=timezone.utc)
    encargos = (
        db.execute(
            select(Encargo).where(
                Encargo.tenant_id == tenant_id,
                Encargo.created_at >= inicio,
                Encargo.created_at <= fin,
            )
        )
        .scalars()
        .all()
    )
    incidencias = (
        db.execute(select(IncidenciaEncargo).where(IncidenciaEncargo.tenant_id == tenant_id))
        .scalars()
        .all()
    )
    por_encargo: dict[UUID, list[IncidenciaEncargo]] = {}
    for i in incidencias:
        por_encargo.setdefault(i.encargo_id, []).append(i)

    por_proveedor: dict[str, list[Encargo]] = {}
    for e in encargos:
        por_proveedor.setdefault(e.proveedor, []).append(e)

    salida: list[dict[str, Any]] = []
    for proveedor, suyos in sorted(por_proveedor.items()):
        completados = [e for e in suyos if e.estado == "completado" and e.completado_at]
        con_plazo = [e for e in completados if e.prometido_para]
        a_tiempo = [e for e in con_plazo if _con_tz(e.completado_at) <= _con_tz(e.prometido_para)]
        culpa_suya = [
            i for e in suyos for i in por_encargo.get(e.id, []) if i.responsable == "proveedor"
        ]
        costes = [e.coste_facturado for e in suyos if e.coste_facturado is not None]

        salida.append(
            {
                "proveedor": proveedor,
                "encargos": len(suyos),
                "completados": len(completados),
                "con_plazo_prometido": len(con_plazo),
                "a_tiempo": len(a_tiempo),
                "cumplimiento_pct": (
                    round(100 * len(a_tiempo) / len(con_plazo), 1) if con_plazo else None
                ),
                "incidencias_suyas": len(culpa_suya),
                "incidencias_por_mil": (
                    round(1000 * len(culpa_suya) / len(suyos), 1) if suyos else None
                ),
                "mudos": len([e for e in suyos if e.mudo]),
                "coste_medio": (
                    str((sum(costes) / len(costes)).quantize(Decimal("0.01"))) if costes else None
                ),
                "medible": bool(con_plazo),
                "aviso": (
                    ""
                    if con_plazo
                    else "Sin encargos completados con plazo prometido: todavía no "
                    "ha demostrado nada."
                ),
            }
        )
    return salida


# ── Prueba de entrega y documentos del proveedor (CRM-00.04.05.05) ────────


def archivar_documento(
    uow: UnidadDeTrabajo,
    encargo_id: UUID,
    *,
    documento_id: str,
    rol: str = "prueba_entrega",
    titulo: str = "",
    tipo: str = "",
    sistema: str = "contecmind",
    por: UUID | None = None,
) -> dict[str, Any]:
    """Enlaza al encargo un documento del proveedor: albarán, POD, foto de
    entrega (CRM-00.04.05.05).

    **Se enlaza, no se copia** (RT-5). El documento vive en el corpus documental,
    con su retención, su antivirus y sus permisos; guardar aquí el binario daría
    dos copias que divergen y una de ellas —la del CRM— sin política de borrado.

    Y la prueba de entrega importa por una razón concreta: cuando el cliente dice
    que no le llegó, lo que se enseña es eso. Sin ella, la discusión se resuelve
    dándole la razón al cliente.
    """
    from crmcore.documental.enlaces import enlazar

    encargo = _encargo(uow.db, uow.tenant_id, encargo_id)
    enlace = enlazar(
        uow.db,
        tenant_id=uow.tenant_id,
        objeto_tipo="encargo",
        objeto_id=encargo.id,
        documento_id=documento_id,
        titulo=titulo,
        tipo=tipo,
        rol=rol,
        sistema=sistema,
        por=por,
    )
    registrar(
        uow.db,
        accion="encargo.documento_archivado",
        objeto="encargo",
        objeto_id=encargo.id,
        datos={"documento_id": documento_id, "rol": rol, "sistema": sistema},
        tenant_id=uow.tenant_id,
    )
    return {
        "encargo_id": str(encargo.id),
        "enlace_id": str(enlace.id),
        "documento_id": documento_id,
        "rol": rol,
    }


def entregados_sin_prueba(
    db: Session, tenant_id: UUID, *, dias: int = 30, en_fecha: datetime | None = None
) -> dict[str, Any]:
    """Qué se dio por entregado sin dejar prueba archivada.

    Es la lista que hay que mirar **antes** de que el cliente llame diciendo que
    no le llegó: entonces ya no se puede pedir la prueba al transportista, porque
    casi todos la conservan unas semanas y luego la borran.
    """
    from crmcore.documental.enlaces import DocumentoEnlazado

    momento = en_fecha or _ahora()
    desde = momento - timedelta(days=dias)
    entregados = (
        db.execute(
            select(Encargo).where(
                Encargo.tenant_id == tenant_id,
                # «completado», que es el estado que existe: la máquina de
                # estados no tiene ninguno llamado «entregado». Filtrar por uno
                # inexistente devolvía SIEMPRE la lista vacía, y una lista vacía
                # aquí se lee como «todo tiene su prueba archivada» — la mentira
                # más cómoda de todas, porque nadie pregunta por qué no sale nada.
                Encargo.estado == "completado",
                Encargo.completado_at >= desde,
            )
        )
        .scalars()
        .all()
    )
    con_prueba = {
        fila.objeto_id
        for fila in db.execute(
            select(DocumentoEnlazado).where(
                DocumentoEnlazado.tenant_id == tenant_id,
                DocumentoEnlazado.objeto_tipo == "encargo",
                DocumentoEnlazado.rol == "prueba_entrega",
            )
        ).scalars()
    }
    faltan = [e for e in entregados if e.id not in con_prueba]
    return {
        "desde": desde.isoformat(),
        "entregados": len(entregados),
        "sin_prueba": [
            {
                "encargo_id": str(e.id),
                "proveedor": e.proveedor,
                "referencia_externa": e.referencia_externa,
                "entregado_at": (e.completado_at.isoformat() if e.completado_at else None),
            }
            for e in faltan
        ],
        "cuantos": len(faltan),
        # Sin entregas en la ventana no se dice que todo esté probado: se dice
        # que no había nada que probar.
        "medible": bool(entregados),
    }
