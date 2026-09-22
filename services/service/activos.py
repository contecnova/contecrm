"""Activos instalados, jerarquía, garantías e historial
(CRM-04.04.02.01 a CRM-04.04.02.04).

Un activo instalado es la máquina que el cliente tiene puesta, no el producto que
se le vendió. La diferencia parece de matiz y es lo que decide si una llamada se
puede atender: el producto dice qué se compró, el activo dice **qué hay en esa
nave, con qué número de serie, desde cuándo y quién lo ha tocado**.

Cuatro decisiones, y todas salen de lo mismo:

**El número de serie identifica, y por eso no se repite.** Dos activos vivos con
la misma serie significan que alguien sustituyó una máquina y no lo registró. Si
el sistema lo admite en silencio, el historial de la nueva arrastra averías de la
vieja y la garantía se calcula sobre la fecha equivocada.

**La jerarquía es real: los componentes se mueven.** Un compresor sale de una
máquina y entra en otra. Si al moverlo se pierde de dónde venía, el análisis de
fiabilidad —«este modelo de compresor falla a los dos años»— deja de poder
hacerse, que es justo para lo que sirve tener activos.

**Sin garantía registrada no se dice que no hay cobertura.** Se dice que **no se
sabe**. Son cosas distintas: una manda factura al cliente y la otra manda mirar el
contrato. Un `false` por ausencia de datos factura al cliente que sí tenía
cobertura, y esa factura llega antes que la corrección.

**El historial es append-only y no se recalcula.** Si se reconstruyera consultando
las órdenes de trabajo, editar o borrar una orden reescribiría el pasado del
activo. Lo que pasó, pasó.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
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

# Estados de un activo instalado. Lista cerrada: cada uno cambia si se le puede
# planificar trabajo, si cuenta para el parque instalado y si su garantía sigue
# corriendo.
#
#   instalado      operativo en casa del cliente
#   en_reparacion  retirado temporalmente; sigue siendo suyo
#   sustituido     lo reemplazó otro activo, que queda enlazado
#   retirado       fuera de servicio; no se planifica nada sobre él
ESTADOS = ("instalado", "en_reparacion", "sustituido", "retirado")

# Qué cubre una garantía. Cerrada porque es lo que decide quién paga, y un
# concepto nuevo inventado en una pantalla dejaría fuera de cobertura algo que
# el contrato sí cubre.
#
#   piezas          el material
#   mano_obra       las horas del técnico
#   desplazamiento  el viaje hasta el cliente
CONCEPTOS = ("piezas", "mano_obra", "desplazamiento")

# Tipos de garantía, de menos a más específico. Cuando dos cubren lo mismo, gana
# la más específica; con empate, la que caduca más tarde.
TIPOS_GARANTIA = ("fabricante", "extension", "contrato")


class ActivoInstalado(Base, TimestampMixin):
    """Lo que el cliente tiene puesto (CRM-04.04.02.01).

    `producto_id` y `cuenta_id` son referencias a otros servicios y **no se
    resuelven desde aquí**: el catálogo es de ventas y la cuenta es de party.
    Copiar aquí el nombre del producto daría dos catálogos, y el que se
    actualizaría sería siempre el otro.
    """

    __tablename__ = "activos_instalados"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # Código legible: es lo que se pinta en la etiqueta de la máquina y lo que el
    # cliente lee por teléfono. Un UUID no se transcribe bien.
    codigo: Mapped[str | None] = mapped_column(String(40), nullable=True)
    numero_serie: Mapped[str | None] = mapped_column(String(120), nullable=True)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    modelo: Mapped[str | None] = mapped_column(String(120), nullable=True)
    fabricante: Mapped[str | None] = mapped_column(String(120), nullable=True)
    producto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)

    ubicacion: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    latitud: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitud: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)

    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="instalado")
    instalado_el: Mapped[date | None] = mapped_column(Date, nullable=True)
    retirado_el: Mapped[date | None] = mapped_column(Date, nullable=True)
    motivo_retirada: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Jerarquía: de qué activo es componente este (CRM-04.04.02.02).
    padre_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("activos_instalados.id", ondelete="SET NULL"),
        nullable=True,
    )
    # A qué activo sustituyó. Es lo que permite seguir la máquina más allá del
    # cambio de equipo: sin esto, cada sustitución empieza un historial de cero.
    sustituye_a_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # Contador de uso —horas, ciclos, kilómetros— para el mantenimiento por uso.
    # Con solo fechas, se revisa una máquina parada y se deja pasar una que va al
    # triple de carga (CRM-04.04.01.05).
    contador: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    unidad_contador: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contador_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    atributos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        # La serie identifica: dos vivos con la misma son una sustitución que
        # nadie registró. Se admite repetirla entre uno retirado y su sustituto,
        # que es el caso legítimo.
        Index(
            "uq_activo_serie_viva",
            "tenant_id",
            "numero_serie",
            unique=True,
            postgresql_where=text("numero_serie is not null and estado <> 'retirado'"),
        ),
        UniqueConstraint("tenant_id", "codigo", name="uq_activo_codigo"),
        Index("ix_activos_cuenta", "tenant_id", "cuenta_id", "estado"),
        Index("ix_activos_padre", "tenant_id", "padre_id"),
    )


class Garantia(Base, TimestampMixin):
    """Qué cubre, hasta cuándo y quién responde (CRM-04.04.02.03).

    La cobertura se guarda **por concepto** —piezas, mano de obra,
    desplazamiento— porque eso es lo que se discute en la puerta del cliente: casi
    ninguna garantía cubre el viaje, y la conversación siempre es esa.
    """

    __tablename__ = "garantias_activo"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    activo_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("activos_instalados.id", ondelete="CASCADE"),
        nullable=False,
    )
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="fabricante")
    referencia: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    proveedor: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    desde: Mapped[date] = mapped_column(Date, nullable=False)
    hasta: Mapped[date] = mapped_column(Date, nullable=False)
    cobertura: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Tope de uso: una garantía de 2 años **o** 4.000 horas, lo que antes pase.
    # Sin esto, una máquina a triple turno sale cubierta el doble de lo pactado.
    limite_contador: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    exclusiones: Mapped[str] = mapped_column(Text, nullable=False, default="")
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (Index("ix_garantias_activo", "tenant_id", "activo_id", "hasta"),)


class EventoActivo(Base):
    """Lo que le ha pasado a un activo (CRM-04.04.02.04).

    **Append-only y escrito en el momento.** Reconstruir el historial consultando
    las órdenes haría que editar una orden reescribiera el pasado del activo, y
    que borrarla lo borrara. Aquí lo que pasó, pasó — aunque después se corrija la
    orden que lo originó.
    """

    __tablename__ = "eventos_activo"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    activo_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("activos_instalados.id", ondelete="CASCADE"),
        nullable=False,
    )
    # instalacion | intervencion | traslado | sustitucion | estado | contador |
    # garantia | componente
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    origen: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    origen_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    usuario_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    datos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    ocurrido_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_eventos_activo", "tenant_id", "activo_id", "ocurrido_at"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _hoy() -> date:
    return datetime.now(timezone.utc).date()


def obtener(db: Session, tenant_id: UUID, activo_id: UUID) -> ActivoInstalado:
    fila = db.get(ActivoInstalado, activo_id)
    if fila is None or fila.tenant_id != tenant_id:
        raise NoEncontrado("El activo no existe", error_code="activos.no_encontrado")
    return fila


def anotar(
    db: Session,
    *,
    tenant_id: UUID,
    activo_id: UUID,
    tipo: str,
    descripcion: str = "",
    origen: str = "manual",
    origen_id: UUID | None = None,
    usuario_id: UUID | None = None,
    datos: dict[str, Any] | None = None,
    ocurrido_at: datetime | None = None,
) -> EventoActivo:
    """Escribe un hecho en el historial del activo."""
    fila = EventoActivo(
        tenant_id=tenant_id,
        activo_id=activo_id,
        tipo=tipo,
        descripcion=descripcion,
        origen=origen,
        origen_id=origen_id,
        usuario_id=usuario_id,
        datos=datos or {},
        ocurrido_at=ocurrido_at or _ahora(),
    )
    db.add(fila)
    db.flush()
    return fila


# ── Alta y ciclo de vida (CRM-04.04.02.01) ────────────────────────────────


def crear(
    uow: UnidadDeTrabajo,
    *,
    nombre: str,
    numero_serie: str | None = None,
    codigo: str | None = None,
    modelo: str | None = None,
    fabricante: str | None = None,
    producto_id: UUID | None = None,
    cuenta_id: UUID | None = None,
    ubicacion: str = "",
    latitud: Decimal | None = None,
    longitud: Decimal | None = None,
    instalado_el: date | None = None,
    padre_id: UUID | None = None,
    contador: Decimal | None = None,
    unidad_contador: str | None = None,
    atributos: dict[str, Any] | None = None,
) -> tuple[ActivoInstalado, list[str]]:
    """Da de alta un activo instalado.

    Devuelve avisos por lo que se podrá hacer peor sin ese dato, en vez de
    exigirlo: un técnico que da de alta una máquina desde el cliente no siempre
    tiene la serie a mano, y bloquearle el alta hace que no la dé.
    """
    avisos: list[str] = []
    serie = (numero_serie or "").strip() or None
    if serie:
        vivo = uow.db.execute(
            select(ActivoInstalado).where(
                ActivoInstalado.tenant_id == uow.tenant_id,
                ActivoInstalado.numero_serie == serie,
                ActivoInstalado.estado != "retirado",
            )
        ).scalar_one_or_none()
        if vivo is not None:
            raise Conflicto(
                "Ya hay un activo vivo con ese número de serie. Si es una "
                "sustitución, retira el anterior: dos vivos con la misma serie "
                "mezclan los dos historiales y calculan mal la garantía.",
                error_code="activos.serie_duplicada",
                detalle={"activo_id": str(vivo.id)},
            )
    else:
        avisos.append(
            "Sin número de serie: este activo no se podrá identificar en una "
            "sustitución ni cruzar con la garantía del fabricante."
        )
    if cuenta_id is None:
        avisos.append("Sin cuenta: no saldrá en el parque instalado del cliente.")

    if padre_id is not None:
        obtener(uow.db, uow.tenant_id, padre_id)

    fila = ActivoInstalado(
        tenant_id=uow.tenant_id,
        nombre=nombre.strip(),
        numero_serie=serie,
        codigo=(codigo or "").strip() or None,
        modelo=modelo,
        fabricante=fabricante,
        producto_id=producto_id,
        cuenta_id=cuenta_id,
        ubicacion=ubicacion.strip(),
        latitud=latitud,
        longitud=longitud,
        instalado_el=instalado_el or _hoy(),
        padre_id=padre_id,
        contador=contador,
        unidad_contador=unidad_contador,
        contador_at=_ahora() if contador is not None else None,
        atributos=atributos or {},
    )
    uow.db.add(fila)
    uow.db.flush()
    anotar(
        uow.db,
        tenant_id=uow.tenant_id,
        activo_id=fila.id,
        tipo="instalacion",
        descripcion=f"Alta del activo «{fila.nombre}»",
        datos={"serie": serie, "cuenta_id": str(cuenta_id) if cuenta_id else None},
    )
    uow.emitir(
        "asset.installed",
        subject=("activo", fila.id),
        data={
            "activo_id": str(fila.id),
            "cuenta_id": str(cuenta_id) if cuenta_id else None,
            "modelo": modelo or "",
        },
    )
    return fila, avisos


def cambiar_estado(
    uow: UnidadDeTrabajo, activo_id: UUID, *, estado: str, motivo: str = ""
) -> ActivoInstalado:
    """Cambia el estado. Retirar exige motivo."""
    if estado not in ESTADOS:
        raise ErrorValidacion(
            f"Estado «{estado}» no válido.",
            error_code="activos.estado_no_valido",
            detalle={"validos": list(ESTADOS)},
        )
    fila = obtener(uow.db, uow.tenant_id, activo_id)
    if estado == "retirado" and not motivo.strip():
        raise ErrorValidacion(
            "Retirar un activo exige motivo: sin él, el parque instalado mengua "
            "sin que nadie sepa si se cambió, se perdió o se dio de baja el cliente.",
            error_code="activos.motivo_obligatorio",
        )
    anterior = fila.estado
    fila.estado = estado
    if estado == "retirado":
        fila.retirado_el = _hoy()
        fila.motivo_retirada = motivo.strip()
    anotar(
        uow.db,
        tenant_id=uow.tenant_id,
        activo_id=fila.id,
        tipo="estado",
        descripcion=f"{anterior} → {estado}",
        datos={"motivo": motivo},
    )
    return fila


def sustituir(
    uow: UnidadDeTrabajo,
    activo_id: UUID,
    *,
    nuevo_nombre: str,
    numero_serie: str | None = None,
    motivo: str,
    modelo: str | None = None,
    heredar_garantias: bool = False,
) -> ActivoInstalado:
    """Retira el activo y da de alta el que lo sustituye, enlazados.

    Las garantías **no se heredan por defecto**: la del equipo nuevo empieza con
    el equipo nuevo. Heredarlas en silencio daría cobertura a una máquina que
    nadie aseguró, y quien pague la reparación lo descubrirá al reclamar al
    fabricante.
    """
    viejo = obtener(uow.db, uow.tenant_id, activo_id)
    if not motivo.strip():
        raise ErrorValidacion(
            "Una sustitución sin motivo no se puede analizar después.",
            error_code="activos.motivo_obligatorio",
        )
    cambiar_estado(uow, activo_id, estado="sustituido", motivo=motivo)
    viejo.retirado_el = _hoy()

    nuevo, _ = crear(
        uow,
        nombre=nuevo_nombre,
        numero_serie=numero_serie,
        modelo=modelo or viejo.modelo,
        fabricante=viejo.fabricante,
        producto_id=viejo.producto_id,
        cuenta_id=viejo.cuenta_id,
        ubicacion=viejo.ubicacion,
        latitud=viejo.latitud,
        longitud=viejo.longitud,
        padre_id=viejo.padre_id,
        unidad_contador=viejo.unidad_contador,
    )
    nuevo.sustituye_a_id = viejo.id

    if heredar_garantias:
        for garantia in uow.db.execute(
            select(Garantia).where(
                Garantia.tenant_id == uow.tenant_id,
                Garantia.activo_id == viejo.id,
                Garantia.activa.is_(True),
            )
        ).scalars():
            uow.db.add(
                Garantia(
                    tenant_id=uow.tenant_id,
                    activo_id=nuevo.id,
                    tipo=garantia.tipo,
                    referencia=garantia.referencia,
                    proveedor=garantia.proveedor,
                    desde=garantia.desde,
                    hasta=garantia.hasta,
                    cobertura=list(garantia.cobertura or []),
                    limite_contador=garantia.limite_contador,
                    exclusiones=garantia.exclusiones,
                )
            )
    uow.db.flush()
    anotar(
        uow.db,
        tenant_id=uow.tenant_id,
        activo_id=nuevo.id,
        tipo="sustitucion",
        descripcion=f"Sustituye al activo {viejo.codigo or viejo.id}",
        datos={
            "sustituye_a": str(viejo.id),
            "motivo": motivo,
            "garantias_heredadas": heredar_garantias,
        },
    )
    anotar(
        uow.db,
        tenant_id=uow.tenant_id,
        activo_id=viejo.id,
        tipo="sustitucion",
        descripcion=f"Sustituido por {nuevo.codigo or nuevo.id}",
        datos={"sustituido_por": str(nuevo.id), "motivo": motivo},
    )
    return nuevo


def leer_contador(
    uow: UnidadDeTrabajo, activo_id: UUID, *, valor: Decimal, unidad: str | None = None
) -> dict[str, Any]:
    """Anota una lectura del contador de uso.

    Un contador que **baja** se acepta y se marca: puede ser un cambio de placa o
    un error de lectura, y las dos cosas hay que verlas. Rechazarlo haría que el
    técnico no anotara nada, que es lo peor de los tres.
    """
    fila = obtener(uow.db, uow.tenant_id, activo_id)
    anterior = Decimal(fila.contador) if fila.contador is not None else None
    retrocede = anterior is not None and Decimal(valor) < anterior
    fila.contador = Decimal(valor)
    fila.unidad_contador = unidad or fila.unidad_contador
    fila.contador_at = _ahora()
    anotar(
        uow.db,
        tenant_id=uow.tenant_id,
        activo_id=fila.id,
        tipo="contador",
        descripcion=f"Lectura {valor} {fila.unidad_contador or ''}".strip(),
        datos={"anterior": str(anterior) if anterior is not None else None, "retrocede": retrocede},
    )
    return {
        "activo_id": str(fila.id),
        "contador": str(fila.contador),
        "unidad": fila.unidad_contador,
        "retrocede": retrocede,
        "aviso": (
            "La lectura es menor que la anterior: puede ser un cambio de equipo o "
            "un error de lectura, y conviene comprobarlo."
            if retrocede
            else ""
        ),
    }


# ── Jerarquía (CRM-04.04.02.02) ───────────────────────────────────────────


def mover_componente(
    uow: UnidadDeTrabajo, activo_id: UUID, *, nuevo_padre_id: UUID | None, motivo: str = ""
) -> ActivoInstalado:
    """Cambia un componente de equipo, dejando constancia de dónde venía.

    Sin esa constancia, el análisis de fiabilidad por modelo —«este compresor
    falla a los dos años»— deja de poder hacerse, que es una de las dos razones
    para tener activos.
    """
    fila = obtener(uow.db, uow.tenant_id, activo_id)
    if nuevo_padre_id is not None:
        if nuevo_padre_id == activo_id:
            raise ErrorValidacion(
                "Un activo no puede colgar de sí mismo.", error_code="activos.ciclo"
            )
        padre = obtener(uow.db, uow.tenant_id, nuevo_padre_id)
        # Un ciclo no da error al guardarlo: lo da al recorrer el árbol, y para
        # entonces el fallo aparece en un sitio que no tiene nada que ver.
        visto = {activo_id}
        actual: ActivoInstalado | None = padre
        while actual is not None:
            if actual.id in visto:
                raise ErrorValidacion(
                    "Ese movimiento crearía un ciclo en la jerarquía.",
                    error_code="activos.ciclo",
                )
            visto.add(actual.id)
            actual = uow.db.get(ActivoInstalado, actual.padre_id) if actual.padre_id else None

    anterior = fila.padre_id
    fila.padre_id = nuevo_padre_id
    anotar(
        uow.db,
        tenant_id=uow.tenant_id,
        activo_id=fila.id,
        tipo="componente",
        descripcion="Cambio de equipo padre",
        datos={
            "desde": str(anterior) if anterior else None,
            "hasta": str(nuevo_padre_id) if nuevo_padre_id else None,
            "motivo": motivo,
        },
    )
    if anterior:
        anotar(
            uow.db,
            tenant_id=uow.tenant_id,
            activo_id=anterior,
            tipo="componente",
            descripcion=f"Se le retiró el componente {fila.codigo or fila.id}",
            datos={"componente_id": str(fila.id), "motivo": motivo},
        )
    return fila


def arbol(db: Session, tenant_id: UUID, activo_id: UUID, *, profundidad: int = 6) -> dict[str, Any]:
    """El activo con sus componentes, hacia abajo.

    Con tope de profundidad: un ciclo que se colara por una carga de datos
    directa a la base colgaría esta función, y un límite es preferible a un
    proceso parado.
    """
    raiz = obtener(db, tenant_id, activo_id)

    def _rama(fila: ActivoInstalado, nivel: int, vistos: set[UUID]) -> dict[str, Any]:
        hijos: list[dict[str, Any]] = []
        truncado = False
        if nivel < profundidad:
            for hijo in db.execute(
                select(ActivoInstalado).where(
                    ActivoInstalado.tenant_id == tenant_id,
                    ActivoInstalado.padre_id == fila.id,
                )
            ).scalars():
                if hijo.id in vistos:
                    truncado = True
                    continue
                hijos.append(_rama(hijo, nivel + 1, vistos | {hijo.id}))
        else:
            truncado = True
        return {
            "id": str(fila.id),
            "codigo": fila.codigo,
            "nombre": fila.nombre,
            "numero_serie": fila.numero_serie,
            "estado": fila.estado,
            "componentes": hijos,
            "truncado": truncado,
        }

    return _rama(raiz, 0, {raiz.id})


def parque_de(db: Session, tenant_id: UUID, cuenta_id: UUID) -> list[dict[str, Any]]:
    """Lo que un cliente tiene instalado."""
    filas = (
        db.execute(
            select(ActivoInstalado)
            .where(
                ActivoInstalado.tenant_id == tenant_id,
                ActivoInstalado.cuenta_id == cuenta_id,
                ActivoInstalado.estado != "retirado",
            )
            .order_by(ActivoInstalado.nombre)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "codigo": f.codigo,
            "nombre": f.nombre,
            "modelo": f.modelo,
            "numero_serie": f.numero_serie,
            "estado": f.estado,
            "ubicacion": f.ubicacion,
            "instalado_el": str(f.instalado_el) if f.instalado_el else None,
            "es_componente": f.padre_id is not None,
        }
        for f in filas
    ]


# ── Garantías y cobertura (CRM-04.04.02.03) ───────────────────────────────


def registrar_garantia(
    uow: UnidadDeTrabajo,
    activo_id: UUID,
    *,
    desde: date,
    hasta: date,
    tipo: str = "fabricante",
    cobertura: list[str] | None = None,
    referencia: str = "",
    proveedor: str = "",
    limite_contador: Decimal | None = None,
    exclusiones: str = "",
) -> Garantia:
    """Registra una garantía con su cobertura por conceptos."""
    if tipo not in TIPOS_GARANTIA:
        raise ErrorValidacion(
            f"Tipo de garantía «{tipo}» no válido.",
            error_code="activos.tipo_garantia_no_valido",
            detalle={"validos": list(TIPOS_GARANTIA)},
        )
    conceptos = list(cobertura or [])
    malos = [c for c in conceptos if c not in CONCEPTOS]
    if malos:
        raise ErrorValidacion(
            f"Conceptos de cobertura no válidos: {malos}.",
            error_code="activos.concepto_no_valido",
            detalle={"validos": list(CONCEPTOS)},
        )
    if not conceptos:
        raise ErrorValidacion(
            "Una garantía que no cubre nada no es una garantía: hay que decir qué "
            "cubre, porque casi ninguna cubre el desplazamiento y esa es la "
            "conversación que se tiene en la puerta del cliente.",
            error_code="activos.cobertura_vacia",
            detalle={"validos": list(CONCEPTOS)},
        )
    if hasta < desde:
        raise ErrorValidacion(
            "La garantía termina antes de empezar.", error_code="activos.periodo_invalido"
        )
    obtener(uow.db, uow.tenant_id, activo_id)

    fila = Garantia(
        tenant_id=uow.tenant_id,
        activo_id=activo_id,
        tipo=tipo,
        referencia=referencia,
        proveedor=proveedor,
        desde=desde,
        hasta=hasta,
        cobertura=conceptos,
        limite_contador=limite_contador,
        exclusiones=exclusiones,
    )
    uow.db.add(fila)
    uow.db.flush()
    anotar(
        uow.db,
        tenant_id=uow.tenant_id,
        activo_id=activo_id,
        tipo="garantia",
        descripcion=f"Garantía {tipo} hasta {hasta}",
        datos={"cobertura": conceptos, "referencia": referencia},
    )
    return fila


def cobertura_de(
    db: Session,
    tenant_id: UUID,
    activo_id: UUID,
    *,
    concepto: str = "piezas",
    en_fecha: date | None = None,
) -> dict[str, Any]:
    """Si un concepto está cubierto, por qué garantía y hasta cuándo
    (CRM-04.04.02.03).

    **Sin garantías registradas no se dice que no hay cobertura**: se dice que no
    se sabe (`concluyente: false`). Un `false` por ausencia de datos factura al
    cliente que sí tenía cobertura, y esa factura llega antes que la corrección.
    """
    hoy = en_fecha or _hoy()
    activo = obtener(db, tenant_id, activo_id)
    filas = (
        db.execute(
            select(Garantia).where(
                Garantia.tenant_id == tenant_id,
                Garantia.activo_id == activo_id,
                Garantia.activa.is_(True),
            )
        )
        .scalars()
        .all()
    )
    if not filas:
        return {
            "cubierto": False,
            "concluyente": False,
            "motivo": "No hay ninguna garantía registrada para este activo: no se "
            "sabe si está cubierto. Antes de facturar, mirar el contrato.",
            "garantias": 0,
        }

    candidatas = []
    for fila in filas:
        if concepto not in (fila.cobertura or []):
            continue
        if hoy < fila.desde or hoy > fila.hasta:
            continue
        # El tope de uso corta antes que la fecha: 2 años **o** 4.000 horas.
        if (
            fila.limite_contador is not None
            and activo.contador is not None
            and Decimal(activo.contador) > Decimal(fila.limite_contador)
        ):
            continue
        candidatas.append(fila)

    if not candidatas:
        vencidas = [f for f in filas if hoy > f.hasta]
        return {
            "cubierto": False,
            "concluyente": True,
            "motivo": (
                f"Ninguna garantía viva cubre «{concepto}» a fecha {hoy}."
                + (f" La última venció el {max(f.hasta for f in vencidas)}." if vencidas else "")
            ),
            "garantias": len(filas),
        }

    # Cuando dos cubren lo mismo gana la más específica —contrato sobre
    # extensión sobre fabricante— y, con empate, la que dura más. Declarado, no
    # por orden de inserción: el orden cambiaría al restaurar una copia.
    orden = {t: i for i, t in enumerate(TIPOS_GARANTIA)}
    elegida = max(candidatas, key=lambda f: (orden.get(f.tipo, 0), f.hasta))
    return {
        "cubierto": True,
        "concluyente": True,
        "garantia_id": str(elegida.id),
        "tipo": elegida.tipo,
        "hasta": str(elegida.hasta),
        "proveedor": elegida.proveedor,
        "referencia": elegida.referencia,
        "exclusiones": elegida.exclusiones,
        "motivo": f"Cubierto por la garantía {elegida.tipo} hasta el {elegida.hasta}.",
        "garantias": len(filas),
    }


def garantias_por_vencer(
    db: Session, tenant_id: UUID, *, dias: int | None = None, en_fecha: date | None = None
) -> dict[str, Any]:
    """Qué se queda sin cobertura pronto.

    Es la lista con la que se vende la extensión, y sobre todo la que evita la
    llamada en la que se descubre que venció hace un mes.
    """
    from datetime import timedelta

    from crmcore.runtime import settings as rt

    hoy = en_fecha or _hoy()
    dias = int(dias if dias is not None else (rt.efectivo("garantia_preaviso_dias", db) or 90))
    limite = hoy + timedelta(days=dias)
    filas = (
        db.execute(
            select(Garantia)
            .where(
                Garantia.tenant_id == tenant_id,
                Garantia.activa.is_(True),
                Garantia.hasta <= limite,
                Garantia.hasta >= hoy,
            )
            .order_by(Garantia.hasta)
        )
        .scalars()
        .all()
    )
    return {
        "en_fecha": str(hoy),
        "dias": dias,
        "garantias": [
            {
                "garantia_id": str(f.id),
                "activo_id": str(f.activo_id),
                "tipo": f.tipo,
                "hasta": str(f.hasta),
                "dias_restantes": (f.hasta - hoy).days,
                "cobertura": f.cobertura,
            }
            for f in filas
        ],
    }


# ── Historial (CRM-04.04.02.04) ───────────────────────────────────────────


def historial(
    db: Session, tenant_id: UUID, activo_id: UUID, *, limite: int = 200
) -> dict[str, Any]:
    """Todo lo que le ha pasado al activo, y a lo que sustituyó.

    Se recorre la cadena de sustituciones hacia atrás: la pregunta real del
    técnico no es «¿qué le pasó a esta máquina?», es «¿esto ya había fallado
    antes?», y la respuesta suele estar en el equipo anterior.
    """
    activo = obtener(db, tenant_id, activo_id)
    cadena: list[UUID] = [activo.id]
    actual = activo
    while actual.sustituye_a_id and len(cadena) < 20:
        anterior = db.get(ActivoInstalado, actual.sustituye_a_id)
        if anterior is None or anterior.tenant_id != tenant_id:
            break
        cadena.append(anterior.id)
        actual = anterior

    filas = (
        db.execute(
            select(EventoActivo)
            .where(EventoActivo.tenant_id == tenant_id, EventoActivo.activo_id.in_(cadena))
            .order_by(EventoActivo.ocurrido_at.desc())
            .limit(limite)
        )
        .scalars()
        .all()
    )
    return {
        "activo_id": str(activo.id),
        "equipos_en_la_cadena": [str(i) for i in cadena],
        "eventos": [
            {
                "id": str(f.id),
                "activo_id": str(f.activo_id),
                "tipo": f.tipo,
                "descripcion": f.descripcion,
                "origen": f.origen,
                "origen_id": str(f.origen_id) if f.origen_id else None,
                "ocurrido_at": f.ocurrido_at.isoformat(),
                "datos": f.datos,
                # Lo del equipo anterior se marca: es historia útil, pero no es
                # de esta máquina, y confundirlo infla su tasa de avería.
                "de_equipo_anterior": f.activo_id != activo.id,
            }
            for f in filas
        ],
    }
