"""Derechos de servicio, consumo, satisfacción y créditos
(CRM-04.01.02.01, .06, .07, .08, CRM-04.01.01.12).

Un contrato de soporte dice tres cosas: **a qué tienes derecho** (entitlement),
**cuánto llevas gastado** (consumo) y **qué pasa si no cumplimos** (créditos). Las
tres se llevan casi siempre en hojas de cálculo distintas, y por eso la discusión
de renovación empieza siempre con dos números que no coinciden.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.fechas import hoy
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

# `Caso` se importa DENTRO de las funciones y no arriba. El motivo es el orden de
# carga: `modelos.py` importa este módulo al final para que el generador de
# migraciones vea sus tablas, así que importarlo aquí arriba cerraría el círculo
# y el servicio no arrancaría. Anotar con `TYPE_CHECKING` da el tipado sin pagar
# el import en ejecución.
if TYPE_CHECKING:  # pragma: no cover
    from services.service.modelos import Caso


class Entitlement(Base, TimestampMixin, SoftDeleteMixin):
    """A qué tiene derecho un cliente (CRM-04.01.02.01).

    Cuelga de un contrato, de un producto, de una cuenta o de un plan, y gana el
    más específico — igual que el SLA. Lo que **no** hace es deducirse del plan
    comercial: un cliente puede tener plan básico y un contrato de soporte
    premium negociado aparte, y deducirlo del plan le daría el trato que no ha
    contratado.
    """

    __tablename__ = "entitlements"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(60), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)

    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    contrato_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    producto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    plan: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # El SLA que concede. Es el enlace entre lo contratado y lo que corre el
    # reloj: sin él, el entitlement sería un papel y el SLA se elegiría aparte.
    sla_clave: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # Bolsas (CRM-04.01.02.06). Nulo = sin límite, que no es lo mismo que cero:
    # cero significa «no tienes derecho a ninguno» y nulo «no se cuentan».
    casos_incluidos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    horas_incluidas: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    # Qué pasa al agotar: bloquear, avisar o facturar el exceso. Se declara
    # porque las tres son legítimas según el contrato, y elegir por nosotros
    # significaría cortarle el soporte a alguien que pagaba por el exceso.
    al_agotar: Mapped[str] = mapped_column(String(20), nullable=False, default="avisar")

    vigente_desde: Mapped[date] = mapped_column(Date, nullable=False)
    vigente_hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_entitlement_clave"),
        Index("ix_entitlements_cuenta", "tenant_id", "cuenta_id", "activo"),
    )


class ConsumoEntitlement(Base):
    """Lo que un caso ha gastado del derecho (CRM-04.01.02.06).

    Una fila por apunte y no un contador en el entitlement: con un contador, un
    cliente que discute la factura no puede ver **qué** consumió, y la única
    respuesta posible es «el sistema dice que 40 horas». Con apuntes, se enseña
    el detalle y la conversación se acaba.
    """

    __tablename__ = "consumos_entitlement"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    entitlement_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("entitlements.id", ondelete="CASCADE"), nullable=False
    )
    caso_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    concepto: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    horas: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    # Un caso consume «una incidencia» aunque no se imputen horas: hay contratos
    # que cuentan casos y no tiempo, y contarlos como cero horas los haría
    # invisibles en la bolsa de incidencias.
    cuenta_como_caso: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    facturable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()"), nullable=False
    )

    __table_args__ = (
        Index("ix_consumos_entitlement", "tenant_id", "entitlement_id", "created_at"),
    )


class Encuesta(Base, TimestampMixin, SoftDeleteMixin):
    """Encuesta enviada tras cerrar un caso (CRM-04.01.01.12).

    Se guarda la **invitación** y no solo la respuesta. Guardar solo las
    respuestas hace que el CSAT lo calculen los que contestan, que son los muy
    contentos y los muy enfadados: sin saber a cuántos se preguntó, el número no
    significa nada y siempre sale bien o siempre sale mal.
    """

    __tablename__ = "encuestas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    caso_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # csat | ces | nps
    tipo: Mapped[str] = mapped_column(String(10), nullable=False, default="csat")
    contacto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    enviada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    respondida_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    puntuacion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comentario: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Token de un solo uso con el que se responde sin iniciar sesión. Hasheado:
    # quien lea la tabla no puede contestar por el cliente.
    hash_token: Mapped[str] = mapped_column(String(64), nullable=False, info={"secreto": True})
    caduca_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "caso_id", "tipo", name="uq_encuesta_caso"),
        Index("ix_encuestas_periodo", "tenant_id", "tipo", "respondida_at"),
    )


class CreditoServicio(Base, TimestampMixin, SoftDeleteMixin):
    """Penalización calculada por incumplimiento (CRM-04.01.02.08).

    Se **calcula y se propone**, no se aplica sola. Descontar dinero de una
    factura automáticamente por un incumplimiento que puede tener una explicación
    —una parada acordada, un dato que faltaba del cliente— convertiría cada
    incidencia en una reclamación. Lo que sí hace el sistema es no dejar que se
    olvide: queda propuesto y alguien tiene que decidir.
    """

    __tablename__ = "creditos_servicio"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    cuenta_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    periodo: Mapped[str] = mapped_column(String(20), nullable=False)
    casos_incumplidos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    casos_con_compromiso: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cumplimiento_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    credito_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    importe: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    # propuesto | aprobado | rechazado | aplicado
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="propuesto")
    motivo_decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    decidido_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    detalle: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "cuenta_id", "periodo", name="uq_credito_periodo"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


# ── Entitlement aplicable (CRM-04.01.02.01) ───────────────────────────────


def entitlement_aplicable(
    db: Session,
    tenant_id: UUID,
    *,
    cuenta_id: UUID | None = None,
    contrato_id: UUID | None = None,
    producto_id: UUID | None = None,
    plan: str = "",
    en_fecha: date | None = None,
) -> Entitlement | None:
    """El derecho que aplica, el más específico.

    Contrato manda sobre producto, producto sobre cuenta y cuenta sobre plan. Al
    revés, un cliente con un contrato de soporte negociado aparte recibiría lo
    que le da su plan comercial — que es justo lo que pagó por mejorar.
    """
    en_fecha = en_fecha or hoy(db)
    filas = (
        db.execute(
            select(Entitlement).where(
                Entitlement.tenant_id == tenant_id,
                Entitlement.activo.is_(True),
                Entitlement.vigente_desde <= en_fecha,
            )
        )
        .scalars()
        .all()
    )
    candidatos = [
        f
        for f in filas
        if (f.vigente_hasta is None or f.vigente_hasta >= en_fecha)
        and (f.contrato_id is None or f.contrato_id == contrato_id)
        and (f.producto_id is None or f.producto_id == producto_id)
        and (f.cuenta_id is None or f.cuenta_id == cuenta_id)
        and (f.plan is None or f.plan == plan)
    ]
    if not candidatos:
        return None

    def _peso(f: Entitlement) -> int:
        return (
            (1000 if f.contrato_id is not None else 0)
            + (100 if f.producto_id is not None else 0)
            + (10 if f.cuenta_id is not None else 0)
            + (1 if f.plan is not None else 0)
        )

    return max(candidatos, key=_peso)


# ── Consumo (CRM-04.01.02.06) ─────────────────────────────────────────────


def imputar(
    uow: UnidadDeTrabajo,
    *,
    entitlement_id: UUID,
    caso_id: UUID | None,
    horas: float = 0,
    concepto: str = "",
    cuenta_como_caso: bool = True,
    por: UUID | None = None,
) -> ConsumoEntitlement:
    """Anota consumo contra un derecho.

    **No bloquea aquí.** Comprobar el saldo y negarse a imputar haría que el
    trabajo ya hecho no se registrara, que es la peor combinación: se ha gastado
    y no consta. Se anota siempre y el saldo se consulta aparte; qué hacer al
    agotar lo decide el entitlement.
    """
    entitlement = uow.db.get(Entitlement, entitlement_id)
    if entitlement is None or entitlement.tenant_id != uow.tenant_id:
        raise NoEncontrado("El derecho no existe", error_code="service.entitlement_no_encontrado")
    if horas < 0:
        raise ErrorValidacion(
            "Las horas imputadas no pueden ser negativas. Para corregir, anota un "
            "apunte de ajuste con su concepto.",
            error_code="service.horas_negativas",
        )

    fila = ConsumoEntitlement(
        tenant_id=uow.tenant_id,
        entitlement_id=entitlement_id,
        caso_id=caso_id,
        concepto=concepto[:200],
        horas=Decimal(str(horas)),
        cuenta_como_caso=cuenta_como_caso,
        por=por,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def saldo(db: Session, tenant_id: UUID, entitlement_id: UUID) -> dict[str, Any]:
    """Cuánto queda del derecho, con lo consumido al lado.

    Se devuelven las dos bolsas —casos y horas— aunque solo una esté limitada:
    enseñar solo la limitada hace que quien mira no sepa si la otra no se cuenta
    o es que nadie ha gastado.
    """
    entitlement = db.get(Entitlement, entitlement_id)
    if entitlement is None or entitlement.tenant_id != tenant_id:
        raise NoEncontrado("El derecho no existe", error_code="service.entitlement_no_encontrado")

    horas = Decimal(
        db.execute(
            select(func.coalesce(func.sum(ConsumoEntitlement.horas), 0)).where(
                ConsumoEntitlement.entitlement_id == entitlement_id
            )
        ).scalar_one()
        or 0
    )
    casos = int(
        db.execute(
            select(func.count())
            .select_from(ConsumoEntitlement)
            .where(
                ConsumoEntitlement.entitlement_id == entitlement_id,
                ConsumoEntitlement.cuenta_como_caso.is_(True),
            )
        ).scalar_one()
        or 0
    )

    horas_incluidas = (
        Decimal(str(entitlement.horas_incluidas))
        if entitlement.horas_incluidas is not None
        else None
    )
    return {
        "entitlement": entitlement.clave,
        "al_agotar": entitlement.al_agotar,
        "horas": {
            "incluidas": str(horas_incluidas) if horas_incluidas is not None else None,
            "consumidas": str(horas),
            "restantes": str(horas_incluidas - horas) if horas_incluidas is not None else None,
            # Nulo = sin límite, que NO es lo mismo que cero: cero significa «no
            # tienes derecho a ninguna» y nulo «no se cuentan».
            "sin_limite": horas_incluidas is None,
            "agotado": horas_incluidas is not None and horas >= horas_incluidas,
        },
        "casos": {
            "incluidos": entitlement.casos_incluidos,
            "consumidos": casos,
            "restantes": (
                entitlement.casos_incluidos - casos
                if entitlement.casos_incluidos is not None
                else None
            ),
            "sin_limite": entitlement.casos_incluidos is None,
            "agotado": (
                entitlement.casos_incluidos is not None and casos >= entitlement.casos_incluidos
            ),
        },
        "vigente_hasta": (
            entitlement.vigente_hasta.isoformat() if entitlement.vigente_hasta else None
        ),
        # Se avisa de la caducidad además del saldo: un derecho con 200 horas
        # libres que vence el viernes es tan inservible como uno agotado, y en
        # las hojas de cálculo esto se descubre siempre tarde.
        "caduca_en_dias": (
            (entitlement.vigente_hasta - hoy(db)).days if entitlement.vigente_hasta else None
        ),
    }


def comprobar_antes_de_abrir(db: Session, tenant_id: UUID, entitlement_id: UUID) -> dict[str, Any]:
    """Si se puede abrir un caso contra este derecho, y qué decir si no.

    Devuelve la decisión en vez de lanzar: quien abre el caso decide qué hacer
    según el contrato —bloquear, avisar o facturar el exceso—, y las tres son
    legítimas. Elegir por él significaría cortarle el soporte a alguien que
    pagaba por el exceso.
    """
    estado = saldo(db, tenant_id, entitlement_id)
    agotado = estado["horas"]["agotado"] or estado["casos"]["agotado"]
    if not agotado:
        return {"permitido": True, "aviso": "", "estado": estado}
    entitlement = db.get(Entitlement, entitlement_id)
    accion = entitlement.al_agotar if entitlement else "avisar"
    return {
        "permitido": accion != "bloquear",
        "aviso": (
            f"El derecho «{estado['entitlement']}» está agotado. Acción "
            f"contratada al agotar: {accion}."
        ),
        "al_agotar": accion,
        "estado": estado,
    }


# ── Encuestas (CRM-04.01.01.12) ───────────────────────────────────────────

RANGOS = {"csat": (1, 5), "ces": (1, 7), "nps": (0, 10)}


def programar_encuesta(
    uow: UnidadDeTrabajo,
    caso: Caso,
    *,
    tipo: str = "csat",
    validez_dias: int = 14,
) -> tuple[Encuesta, str]:
    """Crea la invitación y devuelve el token, una sola vez.

    El token se devuelve aquí y **no se guarda en claro**: quien lea la tabla no
    puede contestar por el cliente. Y se guarda la invitación aunque nadie
    conteste, porque sin saber a cuántos se preguntó el CSAT lo calculan los que
    contestan —los muy contentos y los muy enfadados— y el número no significa
    nada.
    """
    import hashlib
    import secrets

    if tipo not in RANGOS:
        raise ErrorValidacion(
            f"Tipo de encuesta «{tipo}» no válido.",
            error_code="service.encuesta_tipo_no_valido",
            detalle={"validos": sorted(RANGOS)},
        )
    existente = uow.db.execute(
        select(Encuesta).where(
            Encuesta.tenant_id == caso.tenant_id,
            Encuesta.caso_id == caso.id,
            Encuesta.tipo == tipo,
        )
    ).scalar_one_or_none()
    if existente is not None:
        # No se manda dos veces: recibir la misma encuesta cada vez que alguien
        # toca el caso es la forma más rápida de que el cliente la marque como
        # correo no deseado, y entonces se pierden todas las siguientes.
        raise Conflicto(
            "Ya se ha enviado esa encuesta para este caso",
            error_code="service.encuesta_duplicada",
        )

    token = secrets.token_urlsafe(32)
    fila = Encuesta(
        tenant_id=caso.tenant_id,
        caso_id=caso.id,
        tipo=tipo,
        contacto_id=caso.contacto_id,
        enviada_at=_ahora(),
        hash_token=hashlib.sha256(token.encode()).hexdigest(),
        caduca_at=_ahora() + timedelta(days=validez_dias),
    )
    uow.db.add(fila)
    uow.db.flush()
    uow.emitir(
        "case.survey.sent",
        subject=("caso", caso.id),
        data={"caso_id": str(caso.id), "tipo": tipo, "encuesta_id": str(fila.id)},
    )
    return fila, token


def responder_encuesta(
    uow: UnidadDeTrabajo,
    *,
    encuesta_id: UUID,
    token: str,
    puntuacion: int,
    comentario: str = "",
) -> Encuesta:
    """Registra la respuesta del cliente."""
    import hashlib
    import hmac

    fila = uow.db.get(Encuesta, encuesta_id)
    if fila is None:
        raise NoEncontrado("Encuesta no encontrada", error_code="service.encuesta_no_encontrada")
    if not hmac.compare_digest(fila.hash_token, hashlib.sha256((token or "").encode()).hexdigest()):
        raise NoEncontrado("Encuesta no encontrada", error_code="service.encuesta_no_encontrada")
    if fila.respondida_at is not None:
        raise Conflicto("Esa encuesta ya está respondida", error_code="service.encuesta_respondida")
    caduca = (
        fila.caduca_at if fila.caduca_at.tzinfo else fila.caduca_at.replace(tzinfo=timezone.utc)
    )
    if caduca < _ahora():
        raise Conflicto(
            "El enlace de la encuesta ha caducado", error_code="service.encuesta_caducada"
        )

    minimo, maximo = RANGOS[fila.tipo]
    if not minimo <= puntuacion <= maximo:
        raise ErrorValidacion(
            f"La puntuación de {fila.tipo.upper()} va de {minimo} a {maximo}.",
            error_code="service.puntuacion_fuera_de_rango",
        )

    fila.puntuacion = puntuacion
    fila.comentario = comentario or None
    fila.respondida_at = _ahora()
    uow.emitir(
        "case.survey.answered",
        subject=("caso", fila.caso_id),
        data={
            "caso_id": str(fila.caso_id),
            "tipo": fila.tipo,
            "puntuacion": puntuacion,
            # Se marca el detractor para que pueda dispararse una alerta: un NPS
            # de 2 avisado tres semanas después, en el informe mensual, ya no
            # sirve para recuperar a ese cliente.
            "detractor": _es_detractor(fila.tipo, puntuacion),
        },
    )
    return fila


def _es_detractor(tipo: str, puntuacion: int) -> bool:
    if tipo == "nps":
        return puntuacion <= 6
    if tipo == "csat":
        return puntuacion <= 2
    return puntuacion <= 3


def satisfaccion(db: Session, tenant_id: UUID, *, desde: date, hasta: date) -> dict[str, Any]:
    """CSAT, CES y NPS del periodo, con la tasa de respuesta al lado.

    La tasa de respuesta va **junto al número y no aparte**: un CSAT de 4,8 sobre
    el 3 % de los clientes no es un CSAT de 4,8, y enseñarlos separados hace que
    el primero se cite y el segundo no.
    """
    inicio = datetime.combine(desde, datetime.min.time(), tzinfo=timezone.utc)
    fin = datetime.combine(hasta, datetime.max.time(), tzinfo=timezone.utc)
    filas = (
        db.execute(
            select(Encuesta).where(
                Encuesta.tenant_id == tenant_id,
                Encuesta.enviada_at >= inicio,
                Encuesta.enviada_at <= fin,
            )
        )
        .scalars()
        .all()
    )

    salida: dict[str, Any] = {"desde": desde.isoformat(), "hasta": hasta.isoformat()}
    for tipo in RANGOS:
        suyas = [f for f in filas if f.tipo == tipo]
        respondidas = [f for f in suyas if f.puntuacion is not None]
        bloque: dict[str, Any] = {
            "enviadas": len(suyas),
            "respondidas": len(respondidas),
            "tasa_respuesta_pct": (
                round(100 * len(respondidas) / len(suyas), 1) if suyas else None
            ),
            "medible": bool(respondidas),
        }
        if respondidas:
            puntos = [f.puntuacion or 0 for f in respondidas]
            bloque["media"] = round(sum(puntos) / len(puntos), 2)
            if tipo == "nps":
                promotores = len([p for p in puntos if p >= 9])
                detractores = len([p for p in puntos if p <= 6])
                bloque["nps"] = round(100 * (promotores - detractores) / len(puntos), 1)
            bloque["detractores"] = len(
                [f for f in respondidas if _es_detractor(tipo, f.puntuacion or 0)]
            )
        salida[tipo] = bloque
    return salida


# ── Cumplimiento por cliente y equipo (CRM-04.01.02.07) ───────────────────


def cumplimiento_desglosado(
    db: Session, tenant_id: UUID, *, desde: date, hasta: date, por: str = "cuenta"
) -> dict[str, Any]:
    """Cumplimiento de SLA por cliente o por equipo.

    El total global esconde lo único accionable: un 94 % de cumplimiento puede
    ser «todo va bien» o «va bien con todos menos con el cliente grande». Solo el
    desglose distingue esas dos situaciones, y son opuestas.
    """
    if por not in ("cuenta", "equipo"):
        raise ErrorValidacion(
            f"No se puede desglosar por «{por}».",
            error_code="service.desglose_no_soportado",
            detalle={"validos": ["cuenta", "equipo"]},
        )
    from services.service.modelos import Caso

    inicio = datetime.combine(desde, datetime.min.time(), tzinfo=timezone.utc)
    fin = datetime.combine(hasta, datetime.max.time(), tzinfo=timezone.utc)
    casos = (
        db.execute(
            select(Caso).where(
                Caso.tenant_id == tenant_id,
                Caso.created_at >= inicio,
                Caso.created_at <= fin,
                Caso.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
    )

    grupos: dict[str, dict[str, Any]] = {}
    for caso in casos:
        clave = str(
            getattr(caso, "cuenta_id" if por == "cuenta" else "equipo", None) or "(sin asignar)"
        )
        g = grupos.setdefault(
            clave,
            {"casos": 0, "con_compromiso": 0, "incumplidos_pr": 0, "incumplidos_res": 0},
        )
        g["casos"] += 1
        if caso.vence_resolucion_at is not None:
            g["con_compromiso"] += 1
            if caso.incumplio_resolucion:
                g["incumplidos_res"] += 1
        if caso.incumplio_primera_respuesta:
            g["incumplidos_pr"] += 1

    salida = []
    for clave, g in sorted(grupos.items()):
        pct = (
            round(100 * (g["con_compromiso"] - g["incumplidos_res"]) / g["con_compromiso"], 1)
            if g["con_compromiso"]
            else None
        )
        salida.append({"clave": clave, **g, "cumplimiento_pct": pct})

    # Ordenado por el peor primero: la lista existe para actuar, y ordenarla
    # alfabéticamente obliga a buscar el problema en vez de enseñarlo.
    salida.sort(key=lambda g: (g["cumplimiento_pct"] is None, g["cumplimiento_pct"] or 0))
    return {"desde": desde.isoformat(), "hasta": hasta.isoformat(), "por": por, "grupos": salida}


# ── Créditos de servicio (CRM-04.01.02.08) ────────────────────────────────


def calcular_creditos(
    uow: UnidadDeTrabajo,
    *,
    periodo: str,
    desde: date,
    hasta: date,
    escala: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Propone los créditos de servicio del periodo por cliente.

    La escala es **dato**: `[{"hasta_pct": 95, "credito_pct": 5}, …]`. Cada
    contrato tiene la suya y escribirla en el código haría que un cliente con una
    escala distinta fuera una versión del producto.

    Se propone, **no se aplica**. Descontar dinero de una factura automáticamente
    por un incumplimiento que puede tener explicación —una parada acordada, un
    dato que faltaba del cliente— convertiría cada incidencia en una reclamación.
    Lo que sí hace el sistema es no dejar que se olvide.
    """
    tenant_id = uow.tenant_id
    escala = sorted(escala or [], key=lambda e: float(e.get("hasta_pct", 100)))
    desglose = cumplimiento_desglosado(uow.db, tenant_id, desde=desde, hasta=hasta, por="cuenta")

    propuestos: list[dict[str, Any]] = []
    for grupo in desglose["grupos"]:
        if grupo["cumplimiento_pct"] is None or grupo["clave"] == "(sin asignar)":
            continue
        pct = float(grupo["cumplimiento_pct"])
        credito = 0.0
        for tramo in escala:
            if pct <= float(tramo.get("hasta_pct", 100)):
                credito = float(tramo.get("credito_pct", 0))
                break
        if credito <= 0:
            continue

        cuenta_id = UUID(grupo["clave"])
        fila = uow.db.execute(
            select(CreditoServicio).where(
                CreditoServicio.tenant_id == tenant_id,
                CreditoServicio.cuenta_id == cuenta_id,
                CreditoServicio.periodo == periodo,
            )
        ).scalar_one_or_none()
        if fila is not None and fila.estado != "propuesto":
            # Una vez decidido no se recalcula: recalcular un crédito ya aprobado
            # cambiaría un importe que el cliente ya ha visto en su factura.
            continue
        if fila is None:
            fila = CreditoServicio(tenant_id=tenant_id, cuenta_id=cuenta_id, periodo=periodo)
            uow.db.add(fila)

        fila.casos_incumplidos = grupo["incumplidos_res"]
        fila.casos_con_compromiso = grupo["con_compromiso"]
        fila.cumplimiento_pct = pct
        fila.credito_pct = credito
        fila.detalle = {"escala": escala, "desde": desde.isoformat(), "hasta": hasta.isoformat()}
        propuestos.append(
            {
                "cuenta_id": str(cuenta_id),
                "cumplimiento_pct": pct,
                "credito_pct": credito,
                "casos_incumplidos": grupo["incumplidos_res"],
            }
        )

    uow.db.flush()
    registrar(
        uow.db,
        accion="servicio.creditos_propuestos",
        objeto="periodo",
        objeto_id=None,
        datos={"periodo": periodo, "cuantos": len(propuestos)},
        tenant_id=tenant_id,
    )
    return propuestos


def decidir_credito(
    uow: UnidadDeTrabajo,
    credito_id: UUID,
    *,
    aprobar: bool,
    motivo: str,
    importe: Decimal | None = None,
    por: UUID | None = None,
) -> CreditoServicio:
    """Aprueba o rechaza un crédito propuesto.

    El motivo es obligatorio en los dos sentidos. Rechazar sin explicación deja
    al comercial que atiende a ese cliente sin nada que decirle, y aprobar sin
    explicación hace imposible saber después si fue una decisión o un descuido.
    """
    if not (motivo or "").strip():
        raise ErrorValidacion(
            "Decidir un crédito de servicio exige un motivo escrito.",
            error_code="service.credito_sin_motivo",
        )
    fila = uow.db.get(CreditoServicio, credito_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("Crédito no encontrado", error_code="service.credito_no_encontrado")
    if fila.estado != "propuesto":
        raise Conflicto(
            f"Ese crédito ya está «{fila.estado}»", error_code="service.credito_ya_decidido"
        )

    fila.estado = "aprobado" if aprobar else "rechazado"
    fila.motivo_decision = motivo
    fila.decidido_por = por
    if aprobar and importe is not None:
        fila.importe = importe
    registrar(
        uow.db,
        accion="servicio.credito_decidido",
        objeto="credito_servicio",
        objeto_id=fila.id,
        datos={
            "estado": fila.estado,
            "periodo": fila.periodo,
            "credito_pct": float(fila.credito_pct),
            "motivo": motivo,
        },
        tenant_id=fila.tenant_id,
    )
    return fila
