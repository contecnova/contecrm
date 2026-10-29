"""Campañas, miembros, coste y atribución
(CRM-02.02.01.01 a .07, CRM-02.02.02.06).

Marketing se mide de tres maneras y las tres tienen que cuadrar entre sí:
**cuánto costó** (presupuesto y gasto), **qué pasó** (miembros y su progresión) y
**cuánto trajo** (atribución sobre el pipeline). Cuando viven en tres sitios
distintos —y viven, casi siempre en tres hojas de cálculo— la conversación de
final de trimestre empieza con tres números que no coinciden y acaba sin decidir
nada.

Tres decisiones que gobiernan el módulo:

**La jerarquía es real, no una etiqueta.** Programa → campaña → táctica. El
presupuesto se declara arriba y el gasto se imputa abajo, y el consumo sube. Con
una lista plana, «cuánto llevamos gastado en el programa de otoño» se calcula a
mano cada vez y nunca coincide con lo que dice el de al lado.

**La atribución es un modelo, no una verdad.** First touch y last touch dan
respuestas opuestas sobre los mismos datos, y las dos son defendibles. Por eso se
calculan **varios modelos sobre los mismos toques** y se enseñan juntos: elegir
uno solo y presentarlo como «el ROI» es lo que hace que nadie se crea los informes
de marketing.

**La presión de contacto se cuenta aunque no se use.** Saber a cuánta gente le
hemos escrito cuatro veces esta semana es la diferencia entre una campaña y una
denuncia, y el dato solo existe si se cuenta desde el principio.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.datos import rollups as _rollups
from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
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

# Niveles de la jerarquía, de arriba abajo. Cerrados a propósito: con niveles
# libres, cada equipo inventa los suyos y comparar dos programas deja de ser
# posible — que es justo lo que un director de marketing quiere hacer.
NIVELES = ("programa", "campana", "tactica")
ORDEN_NIVEL = {n: i for i, n in enumerate(NIVELES)}

# Estados de progresión de un miembro. En orden: se avanza, no se retrocede, y
# el orden es lo que permite calcular el embudo sin que cada informe decida por
# su cuenta cuál va antes.
ESTADOS_MIEMBRO = (
    "objetivo",
    "enviado",
    "abierto",
    "clicado",
    "respondido",
    "convertido",
    "excluido",
)
ORDEN_MIEMBRO = {e: i for i, e in enumerate(ESTADOS_MIEMBRO)}

MODELOS_ATRIBUCION = ("primer_toque", "ultimo_toque", "lineal", "en_u", "en_w", "decaimiento")


class Campana(Base, TimestampMixin, SoftDeleteMixin):
    """Un programa, una campaña o una táctica (CRM-02.02.01.01)."""

    __tablename__ = "campanas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    padre_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("campanas.id", ondelete="RESTRICT"), nullable=True
    )
    nivel: Mapped[str] = mapped_column(
        String(20), nullable=False, default="campana", info={"opciones": NIVELES}
    )
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(300), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tipo: Mapped[str] = mapped_column(String(60), nullable=False, default="email")
    canal: Mapped[str] = mapped_column(String(40), nullable=False, default="email")

    desde: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    # borrador | planificada | en_curso | pausada | terminada | cancelada
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="borrador")

    # ── Dinero (CRM-02.02.01.01, .05) ─────────────────────────────────────
    # Presupuesto y gasto separados, y el gasto se imputa a la táctica. Un solo
    # campo «coste» obliga a elegir entre planificar y registrar, y lo que pasa
    # es que se planifica en una hoja aparte que nadie actualiza.
    presupuesto: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    gasto: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")

    # ── Objetivos (CRM-02.02.01.02) ───────────────────────────────────────
    # {"leads": 500, "oportunidades": 50, "ingresos": 250000}
    objetivos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    segmento_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    responsable_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # ── Eventos y ferias (CRM-02.02.01.07) ────────────────────────────────
    # Se guardan aquí y no en una tabla aparte porque un evento **es** una
    # campaña: tiene presupuesto, miembros y resultados. Separarlo obligaría a
    # duplicar la atribución y el ROI para él solo.
    lugar: Mapped[str | None] = mapped_column(String(300), nullable=True)
    aforo: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_campana_clave"),
        Index("ix_campanas_jerarquia", "tenant_id", "padre_id", "nivel"),
        Index("ix_campanas_calendario", "tenant_id", "desde", "hasta"),
    )


class MiembroCampana(Base):
    """Alguien dentro de una campaña, con su progresión (CRM-02.02.01.04).

    Se guarda **de dónde salió**: del segmento, de una importación, de una
    inscripción a un evento, a mano. Sin eso, «este lead vino de la campaña de
    otoño» es una afirmación que no se puede comprobar, y el día que los números
    no cuadran no hay forma de saber cuál de las cuatro vías falló.
    """

    __tablename__ = "miembros_campana"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    campana_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("campanas.id", ondelete="CASCADE"), nullable=False
    )
    objeto: Mapped[str] = mapped_column(String(20), nullable=False, default="contacto")
    objeto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)

    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="objetivo")
    # segmento | importacion | inscripcion | manual | api
    fuente_alta: Mapped[str] = mapped_column(String(20), nullable=False, default="segmento")
    # Asistencia real, para eventos: inscribirse y aparecer no es lo mismo, y la
    # diferencia entre las dos es el dato que decide si el evento salió bien.
    asistio: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    alta_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    estado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("campana_id", "objeto_id", name="uq_miembro_campana"),
        Index("ix_miembros_campana_estado", "tenant_id", "campana_id", "estado"),
    )


class ToqueCampana(Base):
    """Toque atribuible a una campaña, replicado desde `sales`.

    Igual que el perfil: `marketing` no puede leer el esquema de `sales`, y la
    atribución tiene que recorrer todos los toques de un lead para repartir el
    crédito. Hacerlo por HTTP, por cada oportunidad de un informe trimestral,
    serían decenas de miles de llamadas.
    """

    __tablename__ = "toques_campana"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    toque_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    lead_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    campana_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    campana: Mapped[str | None] = mapped_column(String(200), nullable=True)
    canal: Mapped[str] = mapped_column(String(40), nullable=False, default="web")
    fuente: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ocurrio_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "toque_id", name="uq_toque_campana"),
        Index("ix_toques_campana_lead", "tenant_id", "lead_id", "ocurrio_at"),
    )


class ContactoEnviado(Base):
    """Cada contacto saliente, para medir la presión (CRM-02.02.02.06).

    Existe aunque las reglas de fatiga estén apagadas. Saber a cuánta gente le
    hemos escrito cuatro veces esta semana es la diferencia entre una campaña y
    una denuncia, y ese dato solo existe si se cuenta desde el principio — cuando
    alguien pregunta, ya es tarde para empezar a contar.
    """

    __tablename__ = "contactos_enviados"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    objeto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    canal: Mapped[str] = mapped_column(String(20), nullable=False, default="email")
    campana_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # Comunicación que NO cuenta para la fatiga: un aviso de servicio, una
    # factura, la respuesta a un caso. Contarlas haría que un cliente con muchas
    # incidencias dejara de recibir la información que ha pedido.
    transaccional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enviado_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_contactos_presion", "tenant_id", "objeto_id", "canal", "enviado_at"),
    )


class ReglaFatiga(Base, TimestampMixin, SoftDeleteMixin):
    """Cuánto es demasiado (CRM-02.02.02.06)."""

    __tablename__ = "reglas_fatiga"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    canal: Mapped[str] = mapped_column(String(20), nullable=False, default="email")
    maximo: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    ventana_dias: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    # Horas mínimas entre dos contactos. Un tope semanal no impide mandar los
    # tres el mismo martes por la mañana, que es exactamente lo que el
    # destinatario percibe como acoso.
    horas_minimas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("tenant_id", "canal", name="uq_regla_fatiga"),)


class Rebote(Base, SoftDeleteMixin):
    """Un rebote o una queja del proveedor de correo (CRM-02.03.01.04).

    Se guardan **los blandos también**. Un blando aislado es normal —el buzón
    estaba lleno— pero cinco seguidos son una dirección muerta, y sin el
    histórico no se puede distinguir una cosa de la otra: o se suprime al primer
    fallo, perdiendo contactos buenos, o no se suprime nunca y la reputación de
    envío se hunde.
    """

    __tablename__ = "rebotes"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # Sin `index=True`: el índice compuesto de abajo ya lo cubre y con los dos
    # el nombre colisiona, que rompe la creación del esquema entera.
    direccion: Mapped[str] = mapped_column(
        String(320), nullable=False, info={"sensibilidad": "personal"}
    )
    # duro | blando | queja
    tipo: Mapped[str] = mapped_column(String(10), nullable=False)
    codigo: Mapped[str | None] = mapped_column(String(20), nullable=True)
    detalle: Mapped[str | None] = mapped_column(Text, nullable=True)
    campana_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    proveedor: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_rebotes_direccion", "tenant_id", "direccion", "created_at"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _con_tz(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


# ── Jerarquía (CRM-02.02.01.01) ───────────────────────────────────────────


def crear(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    nombre: str,
    nivel: str = "campana",
    padre_id: UUID | None = None,
    **datos: Any,
) -> Campana:
    """Crea un programa, una campaña o una táctica.

    La jerarquía se comprueba: una táctica cuelga de una campaña y una campaña de
    un programa, nunca al revés. Sin la comprobación, el árbol se desordena en
    dos semanas y el consumo de presupuesto deja de poder subir.
    """
    if nivel not in NIVELES:
        raise ErrorValidacion(
            f"Nivel «{nivel}» no válido.",
            error_code="marketing.nivel_no_valido",
            detalle={"validos": list(NIVELES)},
        )
    if padre_id is not None:
        padre = uow.db.get(Campana, padre_id)
        if padre is None or padre.tenant_id != uow.tenant_id:
            raise NoEncontrado(
                "La campaña padre no existe", error_code="marketing.campana_no_encontrada"
            )
        if ORDEN_NIVEL[nivel] <= ORDEN_NIVEL[padre.nivel]:
            raise ErrorValidacion(
                f"Un «{nivel}» no puede colgar de un «{padre.nivel}».",
                error_code="marketing.jerarquia_invalida",
                detalle={"orden": list(NIVELES)},
            )
    elif nivel != "programa":
        # Se admite una campaña suelta —no todo cuelga de un programa— pero se
        # avisa: una táctica huérfana no suma a ningún presupuesto y su gasto
        # desaparece del informe del programa sin que nadie lo note.
        logger.info("marketing.campana_sin_padre", clave=clave, nivel=nivel)

    if uow.db.execute(
        select(Campana.id).where(Campana.tenant_id == uow.tenant_id, Campana.clave == clave)
    ).first():
        raise Conflicto(
            "Ya existe una campaña con esa clave", error_code="marketing.campana_duplicada"
        )

    fila = Campana(
        tenant_id=uow.tenant_id, clave=clave, nombre=nombre, nivel=nivel, padre_id=padre_id, **datos
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def _campana(db: Session, tenant_id: UUID, campana_id: UUID) -> Campana:
    fila = db.execute(
        select(Campana).where(Campana.id == campana_id, Campana.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("La campaña no existe", error_code="marketing.campana_no_encontrada")
    return fila


def descendientes(db: Session, tenant_id: UUID, campana_id: UUID) -> list[Campana]:
    """Todo lo que cuelga de una campaña, a cualquier profundidad."""
    salida: list[Campana] = []
    pendientes = [campana_id]
    vistos: set[UUID] = set()
    while pendientes:
        actual = pendientes.pop()
        if actual in vistos:
            continue
        vistos.add(actual)
        hijos = (
            db.execute(
                select(Campana).where(Campana.tenant_id == tenant_id, Campana.padre_id == actual)
            )
            .scalars()
            .all()
        )
        salida.extend(hijos)
        pendientes.extend(h.id for h in hijos)
    return salida


def imputar_gasto(
    uow: UnidadDeTrabajo, campana_id: UUID, *, importe: Decimal, concepto: str = ""
) -> Campana:
    """Imputa gasto a una campaña.

    El gasto se imputa **donde ocurre** —la táctica— y sube por la jerarquía al
    consultarlo, no al escribirlo. Sumarlo hacia arriba al escribir obligaría a
    recalcularlo todo cada vez que alguien mueve una táctica de campaña, y el
    primer fallo dejaría dos totales distintos sin forma de saber cuál es bueno.
    """
    campana = _campana(uow.db, uow.tenant_id, campana_id)
    if importe < 0:
        raise ErrorValidacion(
            "El gasto no puede ser negativo. Para corregir, imputa un ajuste con " "su concepto.",
            error_code="marketing.gasto_negativo",
        )
    campana.gasto = (campana.gasto or Decimal(0)) + importe
    registrar(
        uow.db,
        accion="marketing.gasto_imputado",
        objeto="campana",
        objeto_id=campana.id,
        datos={"importe": str(importe), "concepto": concepto, "total": str(campana.gasto)},
        tenant_id=campana.tenant_id,
    )
    return campana


def consumo(db: Session, tenant_id: UUID, campana_id: UUID) -> dict[str, Any]:
    """Presupuesto contra gasto, con lo de abajo incluido.

    Se dice **si hay hijos sin presupuesto**: un programa cuyo presupuesto no
    cubre el de sus campañas no es un error del sistema, pero enseñar solo el
    total escondería que alguien planificó de más.
    """
    campana = _campana(db, tenant_id, campana_id)
    hijos = descendientes(db, tenant_id, campana_id)
    gasto = (campana.gasto or Decimal(0)) + sum((h.gasto or Decimal(0)) for h in hijos)
    presupuesto = campana.presupuesto
    presupuesto_hijos = sum((h.presupuesto or Decimal(0)) for h in hijos)

    return {
        "campana": campana.clave,
        "nivel": campana.nivel,
        "presupuesto": str(presupuesto) if presupuesto is not None else None,
        "gasto": str(gasto),
        "gasto_propio": str(campana.gasto or Decimal(0)),
        "gasto_descendientes": str(gasto - (campana.gasto or Decimal(0))),
        "restante": str(presupuesto - gasto) if presupuesto is not None else None,
        "consumido_pct": (
            round(100 * float(gasto) / float(presupuesto), 1) if presupuesto else None
        ),
        "sobrepasado": bool(presupuesto is not None and gasto > presupuesto),
        # Si lo repartido abajo supera lo asignado arriba, se dice: es un aviso de
        # planificación, no un fallo, pero enseñarlo evita la sorpresa de octubre.
        "hijos_presupuestados_de_mas": bool(
            presupuesto is not None and presupuesto_hijos > presupuesto
        ),
        "sin_presupuesto": presupuesto is None,
    }


# ── Calendario (CRM-02.02.01.03) ──────────────────────────────────────────


def calendario(db: Session, tenant_id: UUID, *, desde: date, hasta: date) -> dict[str, Any]:
    """Qué hay en marcha y qué se solapa.

    El solapamiento que importa no es el de fechas: es el de **audiencia y
    canal**. Dos campañas la misma semana a públicos distintos no molestan a
    nadie; dos al mismo público por el mismo canal sí, y esa es la que hay que
    ver antes de programar la tercera.
    """
    filas = (
        db.execute(
            select(Campana)
            .where(
                Campana.tenant_id == tenant_id,
                Campana.estado.not_in(("cancelada", "borrador")),
                Campana.desde <= hasta,
                Campana.hasta >= desde,
            )
            .order_by(Campana.desde)
        )
        .scalars()
        .all()
    )

    choques: list[dict[str, Any]] = []
    for i, una in enumerate(filas):
        for otra in filas[i + 1 :]:
            if una.canal != otra.canal:
                continue
            if una.segmento_id is None or una.segmento_id != otra.segmento_id:
                continue
            choques.append(
                {
                    "a": una.clave,
                    "b": otra.clave,
                    "canal": una.canal,
                    "segmento": str(una.segmento_id),
                    "motivo": "mismo segmento y mismo canal en fechas que se pisan",
                }
            )

    return {
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "campanas": [
            {
                "clave": c.clave,
                "nombre": c.nombre,
                "nivel": c.nivel,
                "canal": c.canal,
                "desde": c.desde.isoformat() if c.desde else None,
                "hasta": c.hasta.isoformat() if c.hasta else None,
                "estado": c.estado,
            }
            for c in filas
        ],
        "solapamientos": choques,
        # Se dice cuántas no tienen fechas: quedan fuera del calendario y quien
        # lo mira creería que no hay nada más en marcha.
        "sin_fechas": int(
            db.execute(
                select(func.count())
                .select_from(Campana)
                .where(
                    Campana.tenant_id == tenant_id,
                    Campana.estado == "en_curso",
                    Campana.desde.is_(None),
                )
            ).scalar_one()
            or 0
        ),
    }


# ── Miembros (CRM-02.02.01.04) ────────────────────────────────────────────


def anadir_miembros(
    uow: UnidadDeTrabajo,
    campana_id: UUID,
    *,
    objeto_ids: list[UUID],
    objeto: str = "contacto",
    fuente: str = "segmento",
) -> dict[str, Any]:
    """Mete gente en la campaña sin duplicar.

    Repetir una alta **no reinicia su estado**: quien ya está en «clicado» no
    puede volver a «objetivo» porque alguien recargó el segmento, que es lo que
    pasaría reemplazando. El embudo se quedaría a cero cada vez que se refresca
    la audiencia.
    """
    campana = _campana(uow.db, uow.tenant_id, campana_id)
    existentes = set(
        uow.db.execute(
            select(MiembroCampana.objeto_id).where(MiembroCampana.campana_id == campana.id)
        ).scalars()
    )
    nuevos = [i for i in objeto_ids if i not in existentes]
    for objeto_id in nuevos:
        uow.db.add(
            MiembroCampana(
                tenant_id=campana.tenant_id,
                campana_id=campana.id,
                objeto=objeto,
                objeto_id=objeto_id,
                fuente_alta=fuente,
            )
        )
    uow.db.flush()
    return {"anadidos": len(nuevos), "ya_estaban": len(objeto_ids) - len(nuevos)}


def avanzar(
    uow: UnidadDeTrabajo, campana_id: UUID, objeto_id: UUID, *, estado: str
) -> MiembroCampana:
    """Mueve a un miembro por el embudo.

    **No retrocede.** Que alguien abra un correo después de haber respondido no
    lo devuelve a «abierto»: el embudo mide hasta dónde llegó cada uno, y
    permitir el retroceso haría que las tasas de conversión bajaran solas con el
    tiempo sin que nadie hubiera hecho nada peor.
    """
    if estado not in ESTADOS_MIEMBRO:
        raise ErrorValidacion(
            f"Estado «{estado}» no válido.",
            error_code="marketing.estado_miembro_no_valido",
            detalle={"validos": list(ESTADOS_MIEMBRO)},
        )
    fila = uow.db.execute(
        select(MiembroCampana).where(
            MiembroCampana.campana_id == campana_id,
            MiembroCampana.objeto_id == objeto_id,
            MiembroCampana.tenant_id == uow.tenant_id,
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado(
            "Ese objeto no está en la campaña", error_code="marketing.miembro_no_encontrado"
        )

    if estado != "excluido" and ORDEN_MIEMBRO[estado] <= ORDEN_MIEMBRO[fila.estado]:
        return fila
    fila.estado = estado
    fila.estado_at = _ahora()
    return fila


def miembros_de(
    db: Session,
    tenant_id: UUID,
    campana_id: UUID,
    *,
    estado: str = "",
    limite: int = 200,
) -> list[dict[str, Any]]:
    """Quiénes están en la campaña, con su estado y de dónde salieron.

    **Faltaba.** Se podían añadir miembros y cambiarles el estado, y no había
    forma de listarlos: el embudo dice *cuántos* hay en cada estado y no
    *quiénes*. Para quien lleva la campaña, la diferencia entre «40 han hecho
    clic» y poder llamarlos es toda.

    Se filtra por estado porque es lo que se hace con esto: la lista entera de
    una campaña de veinte mil no la mira nadie; los que han abierto y no han
    respondido, sí.
    """
    consulta = select(MiembroCampana).where(
        MiembroCampana.tenant_id == tenant_id,
        MiembroCampana.campana_id == campana_id,
    )
    if estado:
        consulta = consulta.where(MiembroCampana.estado == estado)
    filas = (
        db.execute(consulta.order_by(MiembroCampana.estado_at.desc()).limit(limite)).scalars().all()
    )
    return [
        {
            "objeto": f.objeto,
            "objeto_id": str(f.objeto_id),
            "estado": f.estado,
            # De dónde salió: sin esto no se puede distinguir a quien se importó
            # de quien entró por un formulario, que es lo que decide si se le
            # puede escribir.
            "fuente_alta": f.fuente_alta,
            "asistio": f.asistio,
            "alta_at": f.alta_at.isoformat(),
            "estado_at": f.estado_at.isoformat(),
        }
        for f in filas
    ]


def embudo(db: Session, tenant_id: UUID, campana_id: UUID) -> dict[str, Any]:
    """El embudo de la campaña, acumulado.

    Acumulado y no por estado actual: quien respondió también abrió, y contar
    solo el estado actual daría «5 abiertos y 40 respondidos», que no se sostiene
    y hace que nadie se crea el resto del informe.
    """
    campana = _campana(db, tenant_id, campana_id)
    filas = dict(
        db.execute(
            select(MiembroCampana.estado, func.count())
            .where(MiembroCampana.campana_id == campana.id)
            .group_by(MiembroCampana.estado)
        ).all()
    )
    total = sum(filas.values())
    acumulado: dict[str, int] = {}
    for estado in ESTADOS_MIEMBRO:
        if estado == "excluido":
            continue
        acumulado[estado] = sum(
            v
            for e, v in filas.items()
            if e != "excluido" and ORDEN_MIEMBRO[e] >= ORDEN_MIEMBRO[estado]
        )
    return {
        "campana": campana.clave,
        "miembros": total,
        "excluidos": filas.get("excluido", 0),
        "embudo": acumulado,
        "conversion_pct": (
            round(100 * acumulado.get("convertido", 0) / acumulado.get("enviado", 1), 2)
            if acumulado.get("enviado")
            else None
        ),
    }


def inscribir(
    uow: UnidadDeTrabajo, campana_id: UUID, objeto_id: UUID, *, objeto: str = "contacto"
) -> MiembroCampana:
    """Inscripción a un evento, respetando el aforo (CRM-02.02.01.07)."""
    campana = _campana(uow.db, uow.tenant_id, campana_id)
    if campana.aforo is not None:
        inscritos = int(
            uow.db.execute(
                select(func.count())
                .select_from(MiembroCampana)
                .where(
                    MiembroCampana.campana_id == campana.id,
                    MiembroCampana.estado != "excluido",
                )
            ).scalar_one()
            or 0
        )
        if inscritos >= campana.aforo:
            raise Conflicto(
                f"El aforo de «{campana.nombre}» está completo ({campana.aforo}).",
                error_code="marketing.aforo_completo",
            )
    anadir_miembros(uow, campana_id, objeto_ids=[objeto_id], objeto=objeto, fuente="inscripcion")
    return uow.db.execute(
        select(MiembroCampana).where(
            MiembroCampana.campana_id == campana.id, MiembroCampana.objeto_id == objeto_id
        )
    ).scalar_one()


def marcar_asistencia(
    uow: UnidadDeTrabajo, campana_id: UUID, objeto_id: UUID, *, asistio: bool
) -> MiembroCampana:
    """Quién apareció de verdad.

    Inscribirse y aparecer no es lo mismo, y la diferencia entre las dos es el
    dato que decide si el evento salió bien. Sin él, un evento con trescientas
    inscripciones y ochenta asistentes se informa como un éxito.
    """
    fila = uow.db.execute(
        select(MiembroCampana).where(
            MiembroCampana.campana_id == campana_id,
            MiembroCampana.objeto_id == objeto_id,
            MiembroCampana.tenant_id == uow.tenant_id,
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado(
            "Ese objeto no está inscrito", error_code="marketing.miembro_no_encontrado"
        )
    fila.asistio = asistio
    return fila


def resultado_evento(db: Session, tenant_id: UUID, campana_id: UUID) -> dict[str, Any]:
    """Inscripciones contra asistencia real."""
    campana = _campana(db, tenant_id, campana_id)
    filas = (
        db.execute(select(MiembroCampana).where(MiembroCampana.campana_id == campana.id))
        .scalars()
        .all()
    )
    inscritos = [f for f in filas if f.fuente_alta == "inscripcion"]
    con_marca = [f for f in inscritos if f.asistio is not None]
    asistieron = [f for f in con_marca if f.asistio]
    return {
        "campana": campana.clave,
        "aforo": campana.aforo,
        "inscritos": len(inscritos),
        "asistieron": len(asistieron),
        "no_aparecieron": len(con_marca) - len(asistieron),
        # Se dice cuántos no se marcaron: sin eso, una asistencia baja podría ser
        # que no vino nadie o que nadie pasó lista, y son dos problemas opuestos.
        "sin_marcar": len(inscritos) - len(con_marca),
        "tasa_asistencia_pct": (
            round(100 * len(asistieron) / len(con_marca), 1) if con_marca else None
        ),
        "medible": bool(con_marca),
    }


# ── Atribución (CRM-02.02.01.06) ──────────────────────────────────────────


@dataclass(slots=True)
class Reparto:
    campana: str
    peso: float
    importe: Decimal


def repartir(
    toques: list[ToqueCampana], importe: Decimal, *, modelo: str, semivida_dias: int = 7
) -> list[Reparto]:
    """Reparte el crédito de una venta entre los toques que la precedieron.

    **Los modelos dan respuestas distintas sobre los mismos datos y las dos son
    defendibles.** El primer toque premia a quien trajo al desconocido; el último,
    a quien cerró. Por eso se calculan varios y se enseñan juntos: elegir uno y
    presentarlo como «el ROI» es lo que hace que nadie se crea los informes de
    marketing.

    Los toques sin campaña **no se descartan**: se agrupan como «(sin campaña)».
    Descartarlos repartiría todo el crédito entre las campañas y haría que el
    tráfico directo y el boca a boca parecieran no existir.
    """
    if modelo not in MODELOS_ATRIBUCION:
        raise ErrorValidacion(
            f"Modelo de atribución «{modelo}» no válido.",
            error_code="marketing.modelo_atribucion_no_valido",
            detalle={"validos": list(MODELOS_ATRIBUCION)},
        )
    if not toques:
        return []

    ordenados = sorted(toques, key=lambda t: _con_tz(t.ocurrio_at))
    n = len(ordenados)
    pesos: list[float] = []

    if modelo == "primer_toque":
        pesos = [1.0] + [0.0] * (n - 1)
    elif modelo == "ultimo_toque":
        pesos = [0.0] * (n - 1) + [1.0]
    elif modelo == "lineal":
        pesos = [1 / n] * n
    elif modelo in ("en_u", "en_w"):
        # En U: 40 % al primero, 40 % al último, 20 % repartido en medio. En W
        # entra además el toque de conversión, que aquí es el último — con un
        # solo toque los dos degeneran al 100 %, que es lo correcto.
        if n == 1:
            pesos = [1.0]
        elif n == 2:
            pesos = [0.5, 0.5]
        else:
            medio = 0.2 / (n - 2)
            pesos = [0.4] + [medio] * (n - 2) + [0.4]
    else:  # decaimiento
        # El toque más reciente pesa más, con semivida configurable. Sin
        # semivida no hay «decaimiento»: hay una constante disfrazada.
        ultimo = _con_tz(ordenados[-1].ocurrio_at)
        crudos = [
            0.5 ** ((ultimo - _con_tz(t.ocurrio_at)).days / max(1, semivida_dias))
            for t in ordenados
        ]
        total = sum(crudos) or 1.0
        pesos = [c / total for c in crudos]

    por_campana: dict[str, float] = {}
    for toque, peso in zip(ordenados, pesos, strict=True):
        clave = toque.campana or "(sin campaña)"
        por_campana[clave] = por_campana.get(clave, 0.0) + peso

    return [
        Reparto(
            campana=clave,
            peso=round(peso, 6),
            importe=(importe * Decimal(str(peso))).quantize(Decimal("0.01")),
        )
        for clave, peso in sorted(por_campana.items(), key=lambda p: -p[1])
    ]


def atribuir(
    db: Session,
    tenant_id: UUID,
    *,
    lead_id: UUID,
    importe: Decimal,
    modelos: list[str] | None = None,
    ventana_dias: int = 90,
) -> dict[str, Any]:
    """Atribuye una venta a las campañas que la precedieron, con varios modelos.

    La **ventana** existe porque un toque de hace tres años no trajo esta venta.
    Sin ella, la primera campaña que hizo la empresa se lleva el crédito de todo
    lo que pase después — que es el resultado favorito de quien la lanzó y el
    motivo por el que nadie se fía del informe.
    """
    modelos = modelos or list(MODELOS_ATRIBUCION)
    desde = _ahora() - timedelta(days=ventana_dias)
    toques = list(
        db.execute(
            select(ToqueCampana)
            .where(
                ToqueCampana.tenant_id == tenant_id,
                ToqueCampana.lead_id == lead_id,
                ToqueCampana.ocurrio_at >= desde,
            )
            .order_by(ToqueCampana.ocurrio_at)
        )
        .scalars()
        .all()
    )

    return {
        "lead_id": str(lead_id),
        "importe": str(importe),
        "ventana_dias": ventana_dias,
        "toques": len(toques),
        "modelos": {
            modelo: [
                {"campana": r.campana, "peso": r.peso, "importe": str(r.importe)}
                for r in repartir(toques, importe, modelo=modelo)
            ]
            for modelo in modelos
        },
        # Sin toques no se atribuye a nadie, y se dice. Repartirlo «a la campaña
        # más reciente» inventaría un origen que no consta, que es exactamente
        # cómo se fabrica un ROI que no se sostiene.
        "sin_toques": not toques,
        "aviso": (
            "No hay ningún toque en la ventana: esta venta no se atribuye a " "ninguna campaña."
            if not toques
            else "Los modelos dan respuestas distintas sobre los mismos datos; los "
            "dos son defendibles. Elige el que encaje con cómo vendéis y "
            "mantenlo."
        ),
    }


def rendimiento(
    db: Session,
    tenant_id: UUID,
    campana_id: UUID,
    *,
    ingresos_atribuidos: Decimal | None = None,
) -> dict[str, Any]:
    """Coste por lead, coste por oportunidad y ROI (CRM-02.02.01.05).

    Los ingresos atribuidos llegan **de fuera**: los calcula quien conoce las
    oportunidades, que es `sales`, y aquí no se leen. Se piden como parámetro en
    vez de inventarse un número, y si no llegan se dice que el ROI no es medible
    en vez de devolver cero — que se leería como «no trajo nada».
    """
    campana = _campana(db, tenant_id, campana_id)
    gasto = Decimal(consumo(db, tenant_id, campana_id)["gasto"])
    embudo_actual = embudo(db, tenant_id, campana_id)
    leads = embudo_actual["embudo"].get("clicado", 0)
    convertidos = embudo_actual["embudo"].get("convertido", 0)

    objetivos = campana.objetivos or {}
    plan_vs_real = {
        clave: {
            "objetivo": objetivo,
            "real": embudo_actual["embudo"].get(clave, 0)
            if clave in embudo_actual["embudo"]
            else None,
        }
        for clave, objetivo in objetivos.items()
    }

    return {
        "campana": campana.clave,
        "gasto": str(gasto),
        "leads": leads,
        "convertidos": convertidos,
        "coste_por_lead": str((gasto / leads).quantize(Decimal("0.01"))) if leads else None,
        "coste_por_conversion": (
            str((gasto / convertidos).quantize(Decimal("0.01"))) if convertidos else None
        ),
        "ingresos_atribuidos": str(ingresos_atribuidos)
        if ingresos_atribuidos is not None
        else None,
        "roi_pct": (
            round(100 * float(ingresos_atribuidos - gasto) / float(gasto), 1)
            if ingresos_atribuidos is not None and gasto
            else None
        ),
        "roi_medible": ingresos_atribuidos is not None and bool(gasto),
        "plan_vs_real": plan_vs_real,
        "aviso": (
            ""
            if ingresos_atribuidos is not None
            else "Sin ingresos atribuidos no se puede calcular el ROI. No es cero: "
            "es que no se ha medido."
        ),
    }


# ── Presión de contacto (CRM-02.02.02.06) ─────────────────────────────────


def anotar_envio(
    db: Session,
    tenant_id: UUID,
    *,
    objeto_id: UUID,
    canal: str = "email",
    campana_id: UUID | None = None,
    transaccional: bool = False,
) -> ContactoEnviado:
    """Cuenta un contacto saliente."""
    fila = ContactoEnviado(
        tenant_id=tenant_id,
        objeto_id=objeto_id,
        canal=canal,
        campana_id=campana_id,
        transaccional=transaccional,
    )
    db.add(fila)
    return fila


def comprobar_fatiga(
    db: Session, tenant_id: UUID, objeto_id: UUID, *, canal: str = "email"
) -> dict[str, Any]:
    """¿Se le puede escribir hoy a esta persona?

    Las comunicaciones **transaccionales no cuentan**: un aviso de servicio, una
    factura o la respuesta a un caso no son marketing, y contarlas haría que un
    cliente con muchas incidencias dejara de recibir la información que ha
    pedido.

    Devuelve la decisión en vez de lanzar: quien envía decide si respeta el tope
    o lo salta con motivo —hay envíos legítimos que lo justifican, como el aviso
    de fin de contrato— y esa decisión tiene que quedar en su sitio, no aquí.
    """
    regla = db.execute(
        select(ReglaFatiga).where(
            ReglaFatiga.tenant_id == tenant_id,
            ReglaFatiga.canal == canal,
            ReglaFatiga.activa.is_(True),
        )
    ).scalar_one_or_none()
    if regla is None:
        # Sin regla no se frena nada, pero se cuenta igual: el dato existe desde
        # el principio para cuando alguien pregunte «¿a cuánta gente le hemos
        # escrito cuatro veces?».
        return {"permitido": True, "hay_regla": False, "enviados": None}

    desde = _ahora() - timedelta(days=regla.ventana_dias)
    envios = list(
        db.execute(
            select(ContactoEnviado.enviado_at)
            .where(
                ContactoEnviado.tenant_id == tenant_id,
                ContactoEnviado.objeto_id == objeto_id,
                ContactoEnviado.canal == canal,
                ContactoEnviado.transaccional.is_(False),
                ContactoEnviado.enviado_at >= desde,
            )
            .order_by(ContactoEnviado.enviado_at.desc())
        ).scalars()
    )

    motivos: list[str] = []
    if len(envios) >= regla.maximo:
        motivos.append(
            f"ya se le han enviado {len(envios)} en {regla.ventana_dias} días "
            f"(máximo {regla.maximo})"
        )
    if regla.horas_minimas and envios:
        horas = (_ahora() - _con_tz(envios[0])).total_seconds() / 3600
        if horas < regla.horas_minimas:
            # Un tope semanal no impide mandar los tres el mismo martes por la
            # mañana, que es exactamente lo que el destinatario percibe como
            # acoso. Por eso hay dos límites y no uno.
            motivos.append(
                f"el último salió hace {int(horas)} h y el mínimo son " f"{regla.horas_minimas} h"
            )

    return {
        "permitido": not motivos,
        "hay_regla": True,
        "enviados": len(envios),
        "maximo": regla.maximo,
        "ventana_dias": regla.ventana_dias,
        "motivos": motivos,
    }


def presion(db: Session, tenant_id: UUID, *, dias: int = 7, canal: str = "email") -> dict[str, Any]:
    """A cuánta gente le hemos escrito y cuántas veces.

    Es la diferencia entre una campaña y una denuncia, y el dato solo existe si
    se cuenta desde el principio: cuando alguien pregunta, ya es tarde para
    empezar a contar.
    """
    desde = _ahora() - timedelta(days=dias)
    filas = db.execute(
        select(ContactoEnviado.objeto_id, func.count())
        .where(
            ContactoEnviado.tenant_id == tenant_id,
            ContactoEnviado.canal == canal,
            ContactoEnviado.transaccional.is_(False),
            ContactoEnviado.enviado_at >= desde,
        )
        .group_by(ContactoEnviado.objeto_id)
    ).all()

    reparto: dict[int, int] = {}
    for _objeto, cuantos in filas:
        reparto[int(cuantos)] = reparto.get(int(cuantos), 0) + 1
    return {
        "dias": dias,
        "canal": canal,
        "personas_contactadas": len(filas),
        "envios": sum(int(c) for _o, c in filas),
        "reparto_por_numero_de_envios": dict(sorted(reparto.items())),
        "mas_de_tres": sum(v for k, v in reparto.items() if k > 3),
    }


# ── Rebotes y quejas (CRM-02.03.01.04) ────────────────────────────────────


# Rebotes blandos seguidos a partir de los cuales se suprime. Un blando aislado
# es normal —el buzón estaba lleno—; cinco seguidos son una dirección muerta que
# está hundiendo la reputación de envío.
def _rebotes_blandos_para_suprimir() -> int:
    """Antes `_rebotes_blandos_para_suprimir() = 5`.

    Era una constante de módulo. Sale del `.env`, que es donde una instalación
    puede afinarla sin tocar código.
    """
    from crmcore.config import get_settings

    return get_settings().rebotes_blandos_para_suprimir


def anotar_rebote(
    uow: UnidadDeTrabajo,
    *,
    direccion: str,
    tipo: str,
    codigo: str = "",
    detalle: str = "",
    campana_id: UUID | None = None,
    proveedor: str = "",
) -> dict[str, Any]:
    """Registra un rebote o una queja y decide si hay que suprimir.

    **Un duro suprime al instante**: la dirección no existe, y seguir
    escribiéndole es lo que hunde la reputación de envío del dominio — y con ella
    la entrega de todos los correos, incluidos los que sí importan.

    **Una queja suprime y es permanente**: alguien ha pulsado «esto es spam», y
    volver a escribirle es exactamente lo que no se puede hacer.

    **Los blandos se acumulan.** Uno aislado es normal; varios seguidos son una
    dirección muerta. Sin el histórico hay que elegir entre suprimir al primer
    fallo —perdiendo contactos buenos— o no suprimir nunca.
    """
    if tipo not in ("duro", "blando", "queja"):
        raise ErrorValidacion(
            f"Tipo de rebote «{tipo}» no válido.",
            error_code="marketing.rebote_no_valido",
            detalle={"validos": ["duro", "blando", "queja"]},
        )
    direccion = direccion.strip().lower()
    uow.db.add(
        Rebote(
            tenant_id=uow.tenant_id,
            direccion=direccion,
            tipo=tipo,
            codigo=codigo or None,
            detalle=detalle or None,
            campana_id=campana_id,
            proveedor=proveedor or None,
        )
    )
    uow.db.flush()

    from services.marketing import segmentos as seg

    if tipo in ("duro", "queja"):
        seg.suprimir(
            uow,
            direccion=direccion,
            motivo="rebote_duro" if tipo == "duro" else "queja",
            detalle=detalle or codigo,
        )
        return {"suprimido": True, "motivo": tipo, "blandos_seguidos": 0}

    # Blandos seguidos: se cuentan desde el último rebote que no fue blando.
    recientes = list(
        uow.db.execute(
            select(Rebote.tipo)
            .where(Rebote.tenant_id == uow.tenant_id, Rebote.direccion == direccion)
            .order_by(Rebote.created_at.desc())
            .limit(_rebotes_blandos_para_suprimir())
        ).scalars()
    )
    seguidos = 0
    for t in recientes:
        if t != "blando":
            break
        seguidos += 1

    if seguidos >= _rebotes_blandos_para_suprimir():
        seg.suprimir(
            uow,
            direccion=direccion,
            motivo="rebote_duro",
            detalle=f"{seguidos} rebotes blandos seguidos",
        )
        return {"suprimido": True, "motivo": "blandos_acumulados", "blandos_seguidos": seguidos}
    return {"suprimido": False, "motivo": "", "blandos_seguidos": seguidos}


def salud_de_envio(db: Session, tenant_id: UUID, *, dias: int = 30) -> dict[str, Any]:
    """Tasas de rebote y de queja del periodo.

    Se enseñan **por separado y con el umbral del sector al lado**: una tasa de
    queja del 0,3 % suena a poco y es el triple de lo que los proveedores toleran
    antes de empezar a mandar a la carpeta de spam. Un número sin referencia no
    dice si hay que hacer algo.
    """
    desde = _ahora() - timedelta(days=dias)
    por_tipo = dict(
        db.execute(
            select(Rebote.tipo, func.count())
            .where(Rebote.tenant_id == tenant_id, Rebote.created_at >= desde)
            .group_by(Rebote.tipo)
        ).all()
    )
    enviados = int(
        db.execute(
            select(func.count())
            .select_from(ContactoEnviado)
            .where(
                ContactoEnviado.tenant_id == tenant_id,
                ContactoEnviado.canal == "email",
                ContactoEnviado.enviado_at >= desde,
            )
        ).scalar_one()
        or 0
    )

    def _tasa(cuantos: int) -> float | None:
        return round(100 * cuantos / enviados, 3) if enviados else None

    duros = int(por_tipo.get("duro", 0))
    quejas = int(por_tipo.get("queja", 0))
    return {
        "dias": dias,
        "enviados": enviados,
        "rebotes_duros": duros,
        "rebotes_blandos": int(por_tipo.get("blando", 0)),
        "quejas": quejas,
        "tasa_rebote_duro_pct": _tasa(duros),
        "tasa_queja_pct": _tasa(quejas),
        # Los umbrales son los que usan los proveedores grandes. Van aquí para
        # que el número signifique algo: sin referencia, «0,3 %» no dice si hay
        # que actuar hoy o no.
        "umbral_rebote_duro_pct": 2.0,
        "umbral_queja_pct": 0.1,
        "en_riesgo": bool(enviados and ((_tasa(duros) or 0) > 2.0 or (_tasa(quejas) or 0) > 0.1)),
        "medible": enviados > 0,
    }


# Los agregados sobre los hijos de una campaña (CRM-00.04.01.04). El listado
# devolvía las columnas de la campaña y ya: la pantalla de marketing pintaba
# «miembros», «enviados» y «respuestas» por fila y ninguno de los tres existe en
# la tabla, así que los tres salían vacíos en todas las campañas.
#
# «Miembros» sí es un agregado y por eso va aquí. «Enviados» y «respuestas» no:
# se cuentan sobre los envíos y salen del embudo de cada campaña, y pedirlos por
# fila sería una consulta por campaña — la lista los enseña como enlace a la
# ficha, no como número inventado.
_rollups.declarar(
    "campana",
    _rollups.Rollup(
        nombre="miembros",
        modelo_hijo=MiembroCampana,
        campo_padre="campana_id",
        funcion="cuenta",
    ),
)
