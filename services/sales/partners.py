"""Canal indirecto: partners, portal, registro de oportunidades y precios de canal
(CRM-03.04.01.01, .02, .03, .05, .06).

Vender por canal no es vender con más gente: es vender con gente **que no
trabaja aquí y que a veces compite entre sí**. Todo lo que sigue sale de ahí.

**El nivel del partner no es una etiqueta, es un contrato.** «Oro» significa un
descuento mayor, una protección más larga y unos requisitos que hay que seguir
cumpliendo. Por eso los niveles son filas configurables y no una lista en el
código: cada fabricante tiene los suyos, y con tres niveles fijos el primer
cliente ya pide el cuarto.

**El registro de oportunidad es lo único que sostiene el canal.** Un partner
invierte semanas en un cliente; si el fabricante —o el partner de al lado— puede
entrar detrás y cerrarlo, deja de traer negocio y pasa a esperar el suyo. La
protección tiene que ser **comprobable y con fecha**, no una promesa comercial.

**Un conflicto de registro se resuelve sin decir quién es el otro.** Al segundo
que registra se le dice que ese cliente ya está protegido y hasta cuándo. No se
le dice por quién: para un competidor que también es partner, el nombre es la
información que estaba buscando.

**Lo que ve un partner está acotado en el servidor.** El compartimento va en el
token (`crmcore.authz.estanco`), no en un parámetro de la petición: si saliera de
la URL, entrar en la cartera del vecino sería cambiar un número.

**Los precios de canal no son un motor nuevo.** El motor de precios ya sabe de
canal, listas y vigencias; aquí solo se dice qué canal y qué lista le tocan a este
partner y **cuánto puede descontar por su cuenta**. Duplicar el motor habría dado
dos precios distintos para el mismo producto, que es peor que no tener precios de
canal.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoAutenticado, NoEncontrado
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

logger = get_logger(__name__)

CENTIMO = Decimal("0.01")

# Estados del ciclo de vida de un partner. Lista cerrada porque cada uno cambia
# lo que el partner **puede hacer**, y eso no puede depender de un texto que
# alguien escriba en una pantalla de administración.
#
#   alta        se está tramitando; no entra al portal
#   activo      opera con normalidad
#   suspendido  entra y ve lo suyo, pero no registra nada nuevo
#   baja        no entra
ESTADOS = ("alta", "activo", "suspendido", "baja")

# Estados de un registro de oportunidad.
#
#   pendiente   esperando decisión del fabricante
#   aprobado    protegido hasta una fecha
#   rechazado   con motivo, siempre
#   caducado    la protección venció sin cerrarse
#   convertido  acabó en oportunidad
ESTADOS_REGISTRO = ("pendiente", "aprobado", "rechazado", "caducado", "convertido")

# Cómo se decide que dos registros hablan del mismo cliente final. Cerrada a
# propósito: es lo que sostiene la protección, y una comparación que el tenant
# pudiera redefinir haría que la protección significara cosas distintas según
# quién configurase el sistema.
CLAVES_CONFLICTO = ("nif", "dominio", "cuenta_id")


class NivelPartner(Base, TimestampMixin):
    """Un escalón del programa de canal (CRM-03.04.01.01).

    Fila y no constante: los niveles de un fabricante de maquinaria no se parecen
    a los de una editorial de software, y con una lista fija en el código el
    primer cliente pide el nivel que falta.

    Los requisitos se guardan **medidos**, no descritos: «facturación mínima» y
    «certificaciones exigidas» son números que se pueden comprobar. Un requisito
    en prosa no se comprueba nunca y el nivel acaba asignándose a dedo.
    """

    __tablename__ = "niveles_partner"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(60), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    # De menor a mayor. Sin un orden declarado no se puede decir si un partner
    # sube o baja, y «oro» y «plata» no se ordenan solos.
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    facturacion_minima: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    certificaciones_exigidas: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Lo que da el nivel. El descuento adicional se suma al de su acuerdo; los
    # días de protección mandan sobre el valor por defecto del programa.
    descuento_extra_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    dias_proteccion: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_nivel_partner"),
        Index("ix_niveles_partner_orden", "tenant_id", "orden"),
    )


class Partner(Base, TimestampMixin, SoftDeleteMixin):
    """Una empresa que vende lo nuestro (CRM-03.04.01.01).

    `cuenta_id` apunta a la cuenta de `party` y **no se resuelve desde aquí**: un
    partner es también un cliente y tiene su ficha allí. Copiar sus datos
    comerciales a este esquema daría dos direcciones del mismo sitio y la que se
    actualizaría sería siempre la otra.
    """

    __tablename__ = "partners"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    # Revendedor, integrador, prescriptor, distribuidor… Lo nombra el tenant: el
    # vocabulario del canal cambia de sector a sector.
    tipo: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    # El canal con el que este partner entra en el motor de precios. Es la unión
    # entre el programa y los precios, y por eso es un campo y no un cálculo.
    canal: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    pais: Mapped[str | None] = mapped_column(String(2), nullable=True)
    nivel_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("niveles_partner.id", ondelete="SET NULL"), nullable=True
    )
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="alta")
    responsable_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # Pasos de alta pendientes y hechos. Se guardan como datos y no como
    # columnas porque el alta de un distribuidor y la de un prescriptor no tienen
    # los mismos trámites.
    onboarding: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    activado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motivo_estado: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_partner_clave"),
        Index("ix_partners_estado", "tenant_id", "estado", "canal"),
    )


class CertificacionPartner(Base, TimestampMixin):
    """Una certificación con fecha de caducidad (CRM-03.04.01.01).

    Caduca **de verdad**: una certificación sin vencimiento es una casilla que se
    marcó una vez y que sigue marcada tres años después, cuando la persona que se
    certificó ya no trabaja allí. Es lo que convierte un programa de canal en una
    lista de logotipos.
    """

    __tablename__ = "certificaciones_partner"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    partner_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("partners.id", ondelete="CASCADE"), nullable=False
    )
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Quién la tiene. Una certificación es de una persona, no de una empresa: si
    # esa persona se va, el partner deja de cumplir aunque el logotipo siga.
    persona: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    obtenida_el: Mapped[date] = mapped_column(Date, nullable=False)
    caduca_el: Mapped[date | None] = mapped_column(Date, nullable=True)
    evidencia_url: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        Index("ix_certificaciones_partner", "tenant_id", "partner_id", "clave"),
        Index("ix_certificaciones_caducidad", "tenant_id", "caduca_el"),
    )


class AccesoPartner(Base, TimestampMixin):
    """La identidad de una persona del partner en el portal (CRM-03.04.01.02).

    Tabla propia por el mismo motivo que la del portal de cliente: quien entra
    aquí **no es un empleado**, no cuenta para licencias y su ciclo de vida lo
    manda el acuerdo de canal. Y lleva el compartimento: es lo que hace que lo
    que vea esté acotado a su partner pase lo que pase.
    """

    __tablename__ = "accesos_partner"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    partner_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("partners.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(
        String(320), nullable=False, info={"sensibilidad": "personal"}
    )
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # admin: además da de alta a sus compañeros. Dos niveles y no tres: en el
    # canal no existe el equivalente al «técnico que solo ve lo suyo», porque el
    # registro de oportunidad es de la empresa, no de quien lo escribió.
    nivel: Mapped[str] = mapped_column(String(20), nullable=False, default="comercial")
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ultimo_acceso_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_acceso_partner_email"),
        Index("ix_accesos_partner", "tenant_id", "partner_id", "activo"),
    )


class EnlaceAccesoPartner(Base):
    """Enlace de un solo uso para entrar al portal de partner."""

    __tablename__ = "enlaces_acceso_partner"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    acceso_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("accesos_partner.id", ondelete="CASCADE"), nullable=False
    )
    # Se guarda el hash: con el token en claro, quien lea la tabla entra como
    # cualquiera de ellos.
    hash_token: Mapped[str] = mapped_column(String(64), nullable=False, info={"secreto": True})
    caduca_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_uso: Mapped[str | None] = mapped_column(
        String(64), nullable=True, info={"sensibilidad": "personal"}
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_enlaces_partner_token", "tenant_id", "hash_token"),)


class RegistroOportunidad(Base, TimestampMixin, SoftDeleteMixin):
    """Un partner declara que está trabajando un cliente (CRM-03.04.01.02).

    El cliente final se identifica por **nif, dominio o cuenta**, y no por el
    nombre: «Talleres García SL», «Talleres Garcia» y «T. García» son la misma
    empresa y tres registros distintos, y con tres registros la protección no
    protege de nada.
    """

    __tablename__ = "registros_oportunidad"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    partner_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("partners.id", ondelete="CASCADE"), nullable=False
    )
    cliente_nombre: Mapped[str] = mapped_column(
        String(200), nullable=False, info={"sensibilidad": "personal"}
    )
    nif: Mapped[str | None] = mapped_column(
        String(40), nullable=True, info={"sensibilidad": "personal"}
    )
    dominio: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    contacto: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    importe_estimado: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    cierre_estimado: Mapped[date | None] = mapped_column(Date, nullable=True)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")

    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    protegido_hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    decidido_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    decidido_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Siempre relleno al rechazar. Un rechazo sin motivo es el final del canal:
    # el partner deja de registrar porque no sabe qué hizo mal.
    motivo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Con qué registro chocó, si chocó. Se guarda para poder auditar la decisión;
    # al partner que llega segundo no se le dice de quién es.
    conflicto_con: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    oportunidad_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (
        Index("ix_registros_partner", "tenant_id", "partner_id", "estado"),
        Index("ix_registros_nif", "tenant_id", "nif"),
        Index("ix_registros_dominio", "tenant_id", "dominio"),
        Index("ix_registros_proteccion", "tenant_id", "estado", "protegido_hasta"),
    )


class AcuerdoCanal(Base, TimestampMixin):
    """Qué precios y qué margen de maniobra tiene un partner (CRM-03.04.01.05).

    No guarda precios: guarda **qué lista** se le aplica y **cuánto puede
    descontar sin preguntar**. El precio lo sigue calculando el motor de siempre,
    que ya sabe de canal, vigencias y prioridades.
    """

    __tablename__ = "acuerdos_canal"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # A un partner concreto o a todo un nivel. Uno de los dos: un acuerdo que no
    # se sabe a quién aplica se aplicaría a todos.
    partner_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("partners.id", ondelete="CASCADE"), nullable=True
    )
    nivel_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("niveles_partner.id", ondelete="CASCADE"), nullable=True
    )
    lista_precio_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    descuento_maximo_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    margen_minimo_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    desde: Mapped[date | None] = mapped_column(Date, nullable=True)
    hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (Index("ix_acuerdos_canal", "tenant_id", "partner_id", "activo"),)


class PlanConjunto(Base, TimestampMixin):
    """Plan de negocio conjunto con un partner (CRM-03.04.01.06).

    Los objetivos se guardan con su **métrica y su número**. Un plan conjunto
    escrito en prosa —«crecer en el sector sanitario»— no se puede revisar en el
    trimestre siguiente, y no revisarlo es exactamente lo que le pasa a casi
    todos.
    """

    __tablename__ = "planes_conjuntos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    partner_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("partners.id", ondelete="CASCADE"), nullable=False
    )
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    desde: Mapped[date] = mapped_column(Date, nullable=False)
    hasta: Mapped[date] = mapped_column(Date, nullable=False)
    objetivos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    acciones: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    revisiones: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="borrador")

    __table_args__ = (Index("ix_planes_conjuntos", "tenant_id", "partner_id", "desde"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _hoy(db: Any = None) -> date:
    """El día de hoy **donde está el cliente**, no en el servidor.

    Calculaba en UTC. Entre medianoche y las dos de la mañana en Madrid —y
    durante trece horas en Auckland— «hoy» era ayer para el servidor y hoy para
    el cliente, así que los días que quedaban salían con uno de más y un plazo
    que vencía hoy se seguía admitiendo. El huso sale del ajuste por tenant que
    ya existía, el mismo que usa el formateo.
    """
    from crmcore.fechas import hoy

    return hoy(db)
    return hoy(db)


def _hash(valor: str) -> str:
    return hashlib.sha256(valor.encode()).hexdigest()


def _redondear(valor: Decimal) -> Decimal:
    return Decimal(valor).quantize(CENTIMO, rounding=ROUND_HALF_UP)


def _partner(db: Session, tenant_id: UUID, partner_id: UUID) -> Partner:
    fila = db.get(Partner, partner_id)
    if fila is None or fila.tenant_id != tenant_id:
        raise NoEncontrado("El partner no existe", error_code="partners.no_encontrado")
    return fila


# ── Alta, niveles y certificaciones (CRM-03.04.01.01) ─────────────────────


def crear_nivel(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    nombre: str,
    orden: int = 0,
    facturacion_minima: Decimal = Decimal(0),
    certificaciones_exigidas: list[str] | None = None,
    descuento_extra_pct: Decimal = Decimal(0),
    dias_proteccion: int | None = None,
) -> NivelPartner:
    """Define un escalón del programa."""
    fila = NivelPartner(
        tenant_id=uow.tenant_id,
        clave=clave.strip(),
        nombre=nombre.strip(),
        orden=orden,
        facturacion_minima=facturacion_minima,
        certificaciones_exigidas=list(certificaciones_exigidas or []),
        descuento_extra_pct=descuento_extra_pct,
        dias_proteccion=dias_proteccion,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def crear_partner(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    nombre: str,
    tipo: str = "",
    canal: str = "",
    pais: str | None = None,
    cuenta_id: UUID | None = None,
    nivel_id: UUID | None = None,
    responsable_id: UUID | None = None,
    pasos_onboarding: list[str] | None = None,
) -> Partner:
    """Da de alta un partner. **Nace en `alta`, no activo** (CRM-03.04.01.01).

    Un partner que entra activo entra al portal y registra oportunidades antes de
    haber firmado nada. Y el día que se revise el programa, nadie sabrá cuáles
    llegaron a completar el alta y cuáles se quedaron a medias: estarán todos
    igual.
    """
    existente = uow.db.execute(
        select(Partner).where(Partner.tenant_id == uow.tenant_id, Partner.clave == clave.strip())
    ).scalar_one_or_none()
    if existente is not None:
        raise Conflicto(
            "Ya hay un partner con esa clave",
            error_code="partners.clave_duplicada",
            detalle={"partner_id": str(existente.id)},
        )
    fila = Partner(
        tenant_id=uow.tenant_id,
        clave=clave.strip(),
        nombre=nombre.strip(),
        tipo=tipo.strip(),
        canal=(canal or clave).strip(),
        pais=pais,
        cuenta_id=cuenta_id,
        nivel_id=nivel_id,
        responsable_id=responsable_id,
        onboarding=[
            {"paso": p, "hecho": False, "hecho_at": None} for p in (pasos_onboarding or [])
        ],
    )
    uow.db.add(fila)
    uow.db.flush()
    registrar(
        uow.db,
        accion="partner.alta",
        objeto="partner",
        objeto_id=fila.id,
        datos={"clave": fila.clave, "nivel_id": str(nivel_id) if nivel_id else None},
        tenant_id=uow.tenant_id,
    )
    return fila


def completar_paso(uow: UnidadDeTrabajo, partner_id: UUID, paso: str) -> Partner:
    """Marca un paso del alta como hecho."""
    fila = _partner(uow.db, uow.tenant_id, partner_id)
    pasos = list(fila.onboarding or [])
    encontrado = False
    for p in pasos:
        if p.get("paso") == paso:
            p["hecho"] = True
            p["hecho_at"] = _ahora().isoformat()
            encontrado = True
    if not encontrado:
        raise ErrorValidacion(
            f"El alta de este partner no tiene el paso «{paso}».",
            error_code="partners.paso_desconocido",
            detalle={"pasos": [p.get("paso") for p in pasos]},
        )
    fila.onboarding = pasos
    return fila


def certificar(
    uow: UnidadDeTrabajo,
    partner_id: UUID,
    *,
    clave: str,
    nombre: str = "",
    persona: str = "",
    obtenida_el: date | None = None,
    caduca_el: date | None = None,
    evidencia_url: str = "",
) -> CertificacionPartner:
    """Registra una certificación."""
    _partner(uow.db, uow.tenant_id, partner_id)
    fila = CertificacionPartner(
        tenant_id=uow.tenant_id,
        partner_id=partner_id,
        clave=clave.strip(),
        nombre=nombre.strip() or clave.strip(),
        persona=persona.strip(),
        obtenida_el=obtenida_el or _hoy(uow.db),
        caduca_el=caduca_el,
        evidencia_url=evidencia_url,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def certificaciones_vigentes(
    db: Session, tenant_id: UUID, partner_id: UUID, *, en_fecha: date | None = None
) -> set[str]:
    """Las claves de certificación que el partner tiene **hoy**."""
    hoy = en_fecha or _hoy(db)
    filas = (
        db.execute(
            select(CertificacionPartner).where(
                CertificacionPartner.tenant_id == tenant_id,
                CertificacionPartner.partner_id == partner_id,
            )
        )
        .scalars()
        .all()
    )
    return {f.clave for f in filas if f.caduca_el is None or f.caduca_el >= hoy}


def cumple_nivel(
    db: Session,
    tenant_id: UUID,
    partner_id: UUID,
    *,
    nivel_id: UUID | None = None,
    facturacion: Decimal = Decimal(0),
    en_fecha: date | None = None,
) -> dict[str, Any]:
    """Si un partner cumple los requisitos de un nivel, y qué le falta.

    La facturación **la trae quien llama**: vive en los pedidos y en el ERP, y
    recalcularla aquí daría un segundo número de lo mismo. Cuando no se pasa se
    dice (`facturacion_medida: false`) en vez de tomar cero por bueno: cero y «no
    lo sé» llevan a decisiones opuestas.
    """
    partner = _partner(db, tenant_id, partner_id)
    nivel = (
        db.get(NivelPartner, nivel_id or partner.nivel_id)
        if (nivel_id or partner.nivel_id)
        else None
    )
    if nivel is None or nivel.tenant_id != tenant_id:
        return {
            "cumple": False,
            "concluyente": False,
            "motivo": "El partner no tiene nivel asignado",
        }

    tiene = certificaciones_vigentes(db, tenant_id, partner_id, en_fecha=en_fecha)
    faltan = [c for c in (nivel.certificaciones_exigidas or []) if c not in tiene]
    falta_facturacion = Decimal(facturacion) < Decimal(nivel.facturacion_minima)
    return {
        "nivel": nivel.clave,
        "cumple": not faltan and not falta_facturacion,
        "certificaciones_faltantes": faltan,
        "facturacion_minima": str(nivel.facturacion_minima),
        "facturacion": str(Decimal(facturacion)),
        "facturacion_medida": Decimal(facturacion) > 0,
        # Con la facturación sin medir, esto no concluye: puede cumplir y no
        # saberse. Decir que no cumple bajaría de nivel a quien factura.
        "concluyente": Decimal(facturacion) > 0 or Decimal(nivel.facturacion_minima) == 0,
    }


def activar(
    uow: UnidadDeTrabajo,
    partner_id: UUID,
    *,
    facturacion: Decimal = Decimal(0),
    forzar: bool = False,
    motivo: str = "",
) -> Partner:
    """Pone al partner en activo si ha terminado el alta y cumple su nivel.

    Se puede **forzar con motivo**: hay altas que se cierran con un trámite
    pendiente por una decisión comercial, y sin esta puerta lo que se hace es
    marcar el trámite como hecho sin hacerlo — y entonces la lista de pendientes
    deja de decir la verdad.
    """
    partner = _partner(uow.db, uow.tenant_id, partner_id)
    pendientes = [p.get("paso") for p in (partner.onboarding or []) if not p.get("hecho")]
    estado_nivel = cumple_nivel(uow.db, uow.tenant_id, partner_id, facturacion=facturacion)
    problemas: list[str] = []
    if pendientes:
        problemas.append(f"Pasos de alta pendientes: {', '.join(str(p) for p in pendientes)}")
    if partner.nivel_id and not estado_nivel.get("cumple") and estado_nivel.get("concluyente"):
        problemas.append(
            "No cumple su nivel: faltan "
            + ", ".join(estado_nivel.get("certificaciones_faltantes") or ["requisitos"])
        )
    if problemas and not forzar:
        raise Conflicto(
            "El partner no puede activarse todavía",
            error_code="partners.alta_incompleta",
            detalle={"problemas": problemas},
        )
    if problemas and forzar and not motivo.strip():
        raise ErrorValidacion(
            "Forzar la activación exige un motivo.",
            error_code="partners.motivo_obligatorio",
        )

    partner.estado = "activo"
    partner.activado_at = _ahora()
    partner.motivo_estado = motivo.strip()
    uow.db.flush()
    registrar(
        uow.db,
        accion="partner.activado",
        objeto="partner",
        objeto_id=partner.id,
        datos={"forzado": bool(problemas and forzar), "problemas": problemas, "motivo": motivo},
        tenant_id=uow.tenant_id,
    )
    uow.emitir(
        "partner.activated",
        subject=("partner", partner.id),
        data={"partner_id": str(partner.id), "canal": partner.canal, "clave": partner.clave},
    )
    return partner


def cambiar_estado(
    uow: UnidadDeTrabajo, partner_id: UUID, *, estado: str, motivo: str = ""
) -> Partner:
    """Suspende, reactiva o da de baja. Con motivo siempre que no sea activar."""
    if estado not in ESTADOS:
        raise ErrorValidacion(
            f"Estado «{estado}» no válido.",
            error_code="partners.estado_no_valido",
            detalle={"validos": list(ESTADOS)},
        )
    if estado in ("suspendido", "baja") and not motivo.strip():
        raise ErrorValidacion(
            "Suspender o dar de baja a un partner exige motivo.",
            error_code="partners.motivo_obligatorio",
        )
    partner = _partner(uow.db, uow.tenant_id, partner_id)
    anterior = partner.estado
    partner.estado = estado
    partner.motivo_estado = motivo.strip()
    registrar(
        uow.db,
        accion="partner.estado",
        objeto="partner",
        objeto_id=partner.id,
        datos={"desde": anterior, "hasta": estado, "motivo": motivo},
        tenant_id=uow.tenant_id,
    )
    return partner


def certificaciones_por_caducar(
    db: Session, tenant_id: UUID, *, dias: int | None = None, en_fecha: date | None = None
) -> dict[str, Any]:
    """Qué se cae pronto, y a quién le cambia el nivel cuando se caiga.

    Avisar el día que caduca no sirve: certificar a alguien lleva semanas. El
    preaviso es un ajuste porque depende de lo que tarde el examen de cada
    fabricante.
    """
    hoy = en_fecha or _hoy(db)
    preaviso = int(
        dias if dias is not None else (rt.efectivo("partner_preaviso_certificacion_dias", db) or 60)
    )
    limite = hoy + timedelta(days=preaviso)
    filas = (
        db.execute(
            select(CertificacionPartner).where(
                CertificacionPartner.tenant_id == tenant_id,
                CertificacionPartner.caduca_el.is_not(None),
                CertificacionPartner.caduca_el <= limite,
            )
        )
        .scalars()
        .all()
    )
    salida = []
    for fila in filas:
        assert fila.caduca_el is not None
        salida.append(
            {
                "certificacion_id": str(fila.id),
                "partner_id": str(fila.partner_id),
                "clave": fila.clave,
                "persona": fila.persona,
                "caduca_el": str(fila.caduca_el),
                "caducada": fila.caduca_el < hoy,
                "dias": (fila.caduca_el - hoy).days,
            }
        )
    salida.sort(key=lambda f: f["caduca_el"])
    return {"preaviso_dias": preaviso, "en_fecha": str(hoy), "certificaciones": salida}


# ── Portal de partner (CRM-03.04.01.02, CRM-03.04.01.03) ──────────────────


def dar_acceso(
    uow: UnidadDeTrabajo,
    partner_id: UUID,
    *,
    email: str,
    nombre: str = "",
    nivel: str = "comercial",
) -> AccesoPartner:
    """Da acceso al portal a una persona del partner."""
    if nivel not in ("comercial", "admin"):
        raise ErrorValidacion(
            f"Nivel «{nivel}» no válido.",
            error_code="partners.nivel_acceso_no_valido",
            detalle={"validos": ["comercial", "admin"]},
        )
    partner = _partner(uow.db, uow.tenant_id, partner_id)
    if partner.estado in ("alta", "baja"):
        raise Conflicto(
            "Ese partner todavía no opera, o ya no opera",
            error_code="partners.no_operativo",
            detalle={"estado": partner.estado},
        )
    correo = email.strip().lower()
    existente = uow.db.execute(
        select(AccesoPartner).where(
            AccesoPartner.tenant_id == uow.tenant_id, AccesoPartner.email == correo
        )
    ).scalar_one_or_none()
    if existente is not None:
        raise Conflicto(
            "Ese correo ya tiene acceso al portal de partner",
            error_code="partners.acceso_duplicado",
            detalle={"acceso_id": str(existente.id)},
        )
    fila = AccesoPartner(
        tenant_id=uow.tenant_id,
        partner_id=partner_id,
        email=correo,
        nombre=nombre.strip(),
        nivel=nivel,
    )
    uow.db.add(fila)
    uow.db.flush()
    registrar(
        uow.db,
        accion="partner.acceso_concedido",
        objeto="partner",
        objeto_id=partner_id,
        datos={"email": correo, "nivel": nivel},
        tenant_id=uow.tenant_id,
    )
    return fila


def revocar_acceso(uow: UnidadDeTrabajo, acceso_id: UUID, *, motivo: str = "") -> AccesoPartner:
    """Quita el acceso y corta los enlaces vivos en el acto."""
    fila = uow.db.get(AccesoPartner, acceso_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("Acceso no encontrado", error_code="partners.acceso_no_encontrado")
    fila.activo = False
    for enlace in uow.db.execute(
        select(EnlaceAccesoPartner).where(
            EnlaceAccesoPartner.acceso_id == fila.id, EnlaceAccesoPartner.usado_at.is_(None)
        )
    ).scalars():
        enlace.usado_at = _ahora()
    registrar(
        uow.db,
        accion="partner.acceso_revocado",
        objeto="partner",
        objeto_id=fila.partner_id,
        datos={"email": fila.email, "motivo": motivo},
        tenant_id=uow.tenant_id,
    )
    return fila


def emitir_enlace(
    uow: UnidadDeTrabajo, *, email: str, validez_minutos: int | None = None
) -> tuple[EnlaceAccesoPartner | None, str]:
    """Enlace de un solo uso para entrar.

    **Devuelve enlace nulo sin decirlo** cuando el correo no vale: la respuesta es
    la misma exista o no. Distinguirlas convertiría el portal en un comprobador de
    qué empresas son partners nuestros, que es media lista de la competencia.
    """
    minutos = int(
        validez_minutos
        if validez_minutos is not None
        else (rt.efectivo("partner_enlace_validez_minutos", uow.db) or 30)
    )
    acceso = uow.db.execute(
        select(AccesoPartner).where(
            AccesoPartner.tenant_id == uow.tenant_id,
            AccesoPartner.email == email.strip().lower(),
            AccesoPartner.activo.is_(True),
        )
    ).scalar_one_or_none()
    if acceso is None:
        logger.info("partners.enlace_a_desconocido", tenant=str(uow.tenant_id))
        return None, ""
    partner = uow.db.get(Partner, acceso.partner_id)
    if partner is None or partner.estado not in ("activo", "suspendido"):
        # Un partner de baja no entra, y tampoco se le dice por qué.
        logger.info("partners.enlace_a_no_operativo", partner=str(acceso.partner_id))
        return None, ""

    token = secrets.token_urlsafe(32)
    enlace = EnlaceAccesoPartner(
        tenant_id=uow.tenant_id,
        acceso_id=acceso.id,
        hash_token=_hash(token),
        caduca_at=_ahora() + timedelta(minutes=minutos),
    )
    uow.db.add(enlace)
    uow.db.flush()
    return enlace, token


def canjear_enlace(uow: UnidadDeTrabajo, token: str, *, ip: str = "") -> AccesoPartner:
    """Canjea el enlace. De un solo uso, y con el mismo error para todo."""
    enlace = uow.db.execute(
        select(EnlaceAccesoPartner).where(
            EnlaceAccesoPartner.tenant_id == uow.tenant_id,
            EnlaceAccesoPartner.hash_token == _hash(token or ""),
        )
    ).scalar_one_or_none()
    if enlace is None or enlace.usado_at is not None:
        raise NoAutenticado("Enlace no válido", error_code="partners.enlace_no_valido")
    caduca = (
        enlace.caduca_at
        if enlace.caduca_at.tzinfo
        else enlace.caduca_at.replace(tzinfo=timezone.utc)
    )
    if caduca < _ahora():
        raise NoAutenticado("Enlace no válido", error_code="partners.enlace_no_valido")
    acceso = uow.db.get(AccesoPartner, enlace.acceso_id)
    if acceso is None or not acceso.activo:
        raise NoAutenticado("Enlace no válido", error_code="partners.enlace_no_valido")

    enlace.usado_at = _ahora()
    enlace.ip_uso = ip or None
    acceso.ultimo_acceso_at = _ahora()
    registrar(
        uow.db,
        accion="partner.entrada",
        objeto="partner",
        objeto_id=acceso.partner_id,
        datos={"email": acceso.email, "ip": ip},
        tenant_id=uow.tenant_id,
    )
    return acceso


def atributos_principal(acceso: AccesoPartner) -> dict[str, Any]:
    """Los atributos con los que se emite el principal de quien entra al portal.

    Aquí es donde el aislamiento deja de ser una intención (CRM-03.04.01.03): a
    partir de este momento el compartimento viaja en la identidad y ningún
    parámetro de ninguna petición puede cambiarlo.
    """
    from crmcore.authz.estanco import atributos_de

    return {**atributos_de("partner", acceso.partner_id), "nivel_partner": acceso.nivel}


# ── Registro de oportunidad y protección (CRM-03.04.01.02) ────────────────


def _clave_cliente(
    *, nif: str | None, dominio: str | None, cuenta_id: UUID | None
) -> tuple[str, str] | None:
    if cuenta_id:
        return ("cuenta_id", str(cuenta_id))
    if nif:
        return ("nif", nif.strip().upper().replace("-", "").replace(" ", ""))
    if dominio:
        return ("dominio", dominio.strip().lower().removeprefix("www."))
    return None


def conflicto_de(
    db: Session,
    tenant_id: UUID,
    *,
    nif: str | None = None,
    dominio: str | None = None,
    cuenta_id: UUID | None = None,
    excepto_id: UUID | None = None,
    en_fecha: date | None = None,
) -> RegistroOportunidad | None:
    """El registro vivo que protege a ese cliente final, si lo hay."""
    hoy = en_fecha or _hoy(db)
    clave = _clave_cliente(nif=nif, dominio=dominio, cuenta_id=cuenta_id)
    if clave is None:
        return None
    columna = {
        "nif": RegistroOportunidad.nif,
        "dominio": RegistroOportunidad.dominio,
        "cuenta_id": RegistroOportunidad.cuenta_id,
    }[clave[0]]
    valor: Any = UUID(clave[1]) if clave[0] == "cuenta_id" else clave[1]
    consulta = select(RegistroOportunidad).where(
        RegistroOportunidad.tenant_id == tenant_id,
        columna == valor,
        RegistroOportunidad.estado.in_(("pendiente", "aprobado")),
    )
    if excepto_id:
        consulta = consulta.where(RegistroOportunidad.id != excepto_id)
    for fila in db.execute(consulta.order_by(RegistroOportunidad.created_at)).scalars():
        if fila.estado == "pendiente":
            return fila
        if fila.protegido_hasta is None or fila.protegido_hasta >= hoy:
            return fila
    return None


def registrar_oportunidad(
    uow: UnidadDeTrabajo,
    *,
    partner_id: UUID,
    cliente_nombre: str,
    nif: str | None = None,
    dominio: str | None = None,
    cuenta_id: UUID | None = None,
    contacto: dict[str, Any] | None = None,
    importe_estimado: Decimal = Decimal(0),
    moneda: str = "EUR",
    cierre_estimado: date | None = None,
    descripcion: str = "",
) -> tuple[RegistroOportunidad, dict[str, Any]]:
    """Un partner declara que está trabajando un cliente (CRM-03.04.01.02).

    Se exige **nif, dominio o cuenta**. Sin ninguno de los tres el registro no
    protege de nada: dos partners escribirían el mismo nombre de dos maneras y el
    sistema diría que son clientes distintos.

    Si ya hay uno vivo, el nuevo **se guarda igual** y se marca el conflicto. No
    se rechaza en el acto: el primero puede caducar, o ser del propio partner que
    vuelve a registrar, y tirar la información deja al fabricante sin saber que
    dos partners van al mismo sitio — que es justo lo que tiene que saber.

    Lo que **no** se devuelve es de quién es el registro que estorba.
    """
    partner = _partner(uow.db, uow.tenant_id, partner_id)
    if partner.estado != "activo":
        raise Conflicto(
            "Un partner que no está activo no puede registrar oportunidades",
            error_code="partners.no_activo",
            detalle={"estado": partner.estado},
        )
    if _clave_cliente(nif=nif, dominio=dominio, cuenta_id=cuenta_id) is None:
        raise ErrorValidacion(
            "Hace falta NIF, dominio o cuenta para identificar al cliente final: "
            "el nombre no sirve, porque la misma empresa se escribe de cinco maneras.",
            error_code="partners.cliente_sin_identificar",
            detalle={"claves": list(CLAVES_CONFLICTO)},
        )

    choque = conflicto_de(uow.db, uow.tenant_id, nif=nif, dominio=dominio, cuenta_id=cuenta_id)
    fila = RegistroOportunidad(
        tenant_id=uow.tenant_id,
        partner_id=partner_id,
        cliente_nombre=cliente_nombre.strip(),
        nif=(nif or "").strip().upper().replace("-", "").replace(" ", "") or None,
        dominio=(dominio or "").strip().lower().removeprefix("www.") or None,
        cuenta_id=cuenta_id,
        contacto=contacto or {},
        importe_estimado=importe_estimado,
        moneda=moneda,
        cierre_estimado=cierre_estimado,
        descripcion=descripcion,
        conflicto_con=choque.id if choque is not None else None,
    )
    uow.db.add(fila)
    uow.db.flush()

    aviso = {"hay_conflicto": choque is not None}
    if choque is not None:
        propio = choque.partner_id == partner_id
        aviso.update(
            {
                # Al propio partner sí se le dice que ya lo tenía él: es su dato,
                # y no decírselo le haría registrar lo mismo cada semana.
                "es_propio": propio,
                "protegido_hasta": str(choque.protegido_hasta) if choque.protegido_hasta else None,
                "mensaje": (
                    "Ya tienes un registro vivo para ese cliente."
                    if propio
                    else "Ese cliente ya tiene un registro en curso. Tu solicitud queda "
                    "pendiente de revisión."
                ),
            }
        )
    registrar(
        uow.db,
        accion="partner.registro_oportunidad",
        objeto="registro_oportunidad",
        objeto_id=fila.id,
        datos={
            "partner_id": str(partner_id),
            "conflicto_con": str(choque.id) if choque is not None else None,
        },
        tenant_id=uow.tenant_id,
    )
    uow.emitir(
        "partner.deal.registered",
        subject=("registro_oportunidad", fila.id),
        data={
            "registro_id": str(fila.id),
            "partner_id": str(partner_id),
            "importe": str(importe_estimado),
            "hay_conflicto": choque is not None,
        },
    )
    return fila, aviso


def decidir_registro(
    uow: UnidadDeTrabajo,
    registro_id: UUID,
    *,
    aprobar: bool,
    motivo: str = "",
    dias_proteccion: int | None = None,
    decidido_por: UUID | None = None,
) -> RegistroOportunidad:
    """Aprueba o rechaza un registro (CRM-03.04.01.02).

    **Aprobar es fijar una fecha.** Una protección «mientras trabaje el cliente»
    no se puede comprobar y acaba discutiéndose por correo. Los días salen del
    nivel del partner y, si no lo tiene, del ajuste del programa: un partner de
    nivel alto protege más tiempo, y eso *es* el programa.

    **Rechazar exige motivo.** Sin él, el partner no sabe si fue por conflicto,
    por territorio o porque el cliente ya era nuestro, y lo que aprende es a no
    registrar.
    """
    fila = uow.db.get(RegistroOportunidad, registro_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("El registro no existe", error_code="partners.registro_no_encontrado")
    if fila.estado != "pendiente":
        raise Conflicto(
            "Ese registro ya está decidido",
            error_code="partners.registro_decidido",
            detalle={"estado": fila.estado},
        )
    if not aprobar and not motivo.strip():
        raise ErrorValidacion(
            "Rechazar un registro exige motivo.",
            error_code="partners.motivo_obligatorio",
        )

    fila.decidido_por = decidido_por
    fila.decidido_at = _ahora()
    fila.motivo = motivo.strip()
    if aprobar:
        dias = dias_proteccion
        if dias is None:
            partner = uow.db.get(Partner, fila.partner_id)
            nivel = (
                uow.db.get(NivelPartner, partner.nivel_id)
                if partner is not None and partner.nivel_id
                else None
            )
            dias = (
                nivel.dias_proteccion
                if nivel is not None and nivel.dias_proteccion is not None
                else int(rt.efectivo("partner_proteccion_dias", uow.db) or 90)
            )
        fila.estado = "aprobado"
        fila.protegido_hasta = _hoy(uow.db) + timedelta(days=int(dias))
    else:
        fila.estado = "rechazado"
        fila.protegido_hasta = None

    registrar(
        uow.db,
        accion="partner.registro_decidido",
        objeto="registro_oportunidad",
        objeto_id=fila.id,
        datos={
            "estado": fila.estado,
            "motivo": fila.motivo,
            "protegido_hasta": str(fila.protegido_hasta) if fila.protegido_hasta else None,
        },
        tenant_id=uow.tenant_id,
    )
    uow.emitir(
        "partner.deal.decided",
        subject=("registro_oportunidad", fila.id),
        data={
            "registro_id": str(fila.id),
            "partner_id": str(fila.partner_id),
            "estado": fila.estado,
            "protegido_hasta": str(fila.protegido_hasta) if fila.protegido_hasta else None,
        },
    )
    return fila


def caducar_protecciones(uow: UnidadDeTrabajo, *, en_fecha: date | None = None) -> dict[str, Any]:
    """Cierra las protecciones vencidas.

    Se hace **explícitamente y se audita**, en vez de calcularlo al vuelo cada
    vez que alguien mira: el partner tiene derecho a ver cuándo se le cayó la
    protección y por qué, y una caducidad implícita no deja rastro de nada.
    """
    hoy = en_fecha or _hoy(uow.db)
    filas = (
        uow.db.execute(
            select(RegistroOportunidad).where(
                RegistroOportunidad.tenant_id == uow.tenant_id,
                RegistroOportunidad.estado == "aprobado",
                RegistroOportunidad.protegido_hasta.is_not(None),
                RegistroOportunidad.protegido_hasta < hoy,
            )
        )
        .scalars()
        .all()
    )
    for fila in filas:
        fila.estado = "caducado"
        uow.emitir(
            "partner.deal.expired",
            subject=("registro_oportunidad", fila.id),
            data={"registro_id": str(fila.id), "partner_id": str(fila.partner_id)},
        )
    uow.db.flush()
    return {"en_fecha": str(hoy), "caducados": [str(f.id) for f in filas]}


def vincular_oportunidad(
    uow: UnidadDeTrabajo, registro_id: UUID, *, oportunidad_id: UUID
) -> RegistroOportunidad:
    """Enlaza el registro con la oportunidad que salió de él.

    Es lo que permite medir el canal de verdad después: sin el enlace, el negocio
    aparece en la oportunidad y el esfuerzo en el registro, y nadie puede decir
    cuánto de lo cerrado vino de partners.
    """
    fila = uow.db.get(RegistroOportunidad, registro_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("El registro no existe", error_code="partners.registro_no_encontrado")
    if fila.estado not in ("aprobado", "convertido"):
        raise Conflicto(
            "Solo se vincula un registro aprobado",
            error_code="partners.registro_no_aprobado",
            detalle={"estado": fila.estado},
        )
    fila.oportunidad_id = oportunidad_id
    fila.estado = "convertido"
    return fila


# ── Precios y descuentos de canal (CRM-03.04.01.05) ───────────────────────


def acuerdo_de(
    db: Session, tenant_id: UUID, partner_id: UUID, *, en_fecha: date | None = None
) -> AcuerdoCanal | None:
    """El acuerdo vigente: primero el del partner, si no el de su nivel."""
    hoy = en_fecha or _hoy(db)
    partner = _partner(db, tenant_id, partner_id)

    def _vigente(fila: AcuerdoCanal) -> bool:
        if not fila.activo:
            return False
        if fila.desde and hoy < fila.desde:
            return False
        return not (fila.hasta and hoy > fila.hasta)

    propios = (
        db.execute(
            select(AcuerdoCanal).where(
                AcuerdoCanal.tenant_id == tenant_id, AcuerdoCanal.partner_id == partner_id
            )
        )
        .scalars()
        .all()
    )
    for fila in propios:
        if _vigente(fila):
            return fila
    if partner.nivel_id:
        de_nivel = (
            db.execute(
                select(AcuerdoCanal).where(
                    AcuerdoCanal.tenant_id == tenant_id,
                    AcuerdoCanal.nivel_id == partner.nivel_id,
                    AcuerdoCanal.partner_id.is_(None),
                )
            )
            .scalars()
            .all()
        )
        for fila in de_nivel:
            if _vigente(fila):
                return fila
    return None


def precio_para_partner(
    db: Session,
    tenant_id: UUID,
    *,
    partner_id: UUID,
    producto_id: UUID,
    cantidad: Decimal = Decimal(1),
    cuenta_id: UUID | None = None,
    moneda: str = "",
    en_fecha: date | None = None,
) -> dict[str, Any]:
    """El precio de un producto para un partner, con su explicación
    (CRM-03.04.01.05).

    **Delega en el motor de precios**: el canal del partner entra como canal, y de
    ahí salen las listas, las vigencias y las prioridades de siempre. Lo único que
    se añade aquí es el descuento extra del nivel y el **tope** que ese partner
    puede dar por su cuenta.

    Se devuelve `precio_suelo`: por debajo de eso hace falta aprobación. Sin ese
    número, el tope existe en el acuerdo y no existe en la pantalla, y entonces se
    descubre al firmar.
    """
    from services.sales import catalogo

    partner = _partner(db, tenant_id, partner_id)
    calculo = catalogo.calcular_precio(
        db,
        tenant_id,
        producto_id=producto_id,
        cantidad=cantidad,
        cuenta_id=cuenta_id,
        canal=partner.canal,
        moneda=moneda,
        en_fecha=en_fecha,
    )
    precio = Decimal(str(calculo["precio"]))
    pasos = list(calculo.get("pasos") or [])

    nivel = db.get(NivelPartner, partner.nivel_id) if partner.nivel_id else None
    if nivel is not None and Decimal(nivel.descuento_extra_pct) > 0:
        antes = precio
        precio = _redondear(precio * (Decimal(1) - Decimal(nivel.descuento_extra_pct) / 100))
        pasos.append(
            {
                "regla": f"nivel {nivel.clave}",
                "accion": "descuento_pct",
                "valor": str(nivel.descuento_extra_pct),
                "desde": str(antes),
                "hasta": str(precio),
            }
        )

    acuerdo = acuerdo_de(db, tenant_id, partner_id, en_fecha=en_fecha)
    tope = Decimal(acuerdo.descuento_maximo_pct) if acuerdo is not None else Decimal(0)
    return {
        **calculo,
        "canal": partner.canal,
        "precio": str(precio),
        "pasos": pasos,
        "descuento_maximo_pct": str(tope),
        "precio_suelo": str(_redondear(precio * (Decimal(1) - tope / 100))),
        # Sin acuerdo no se dice que el tope es cero: se dice que no hay acuerdo.
        # Cero y «sin acuerdo» llevan a conversaciones distintas con el partner.
        "hay_acuerdo": acuerdo is not None,
    }


def comprobar_descuento(
    db: Session,
    tenant_id: UUID,
    *,
    partner_id: UUID,
    precio_lista: Decimal,
    precio_ofertado: Decimal,
    coste: Decimal | None = None,
    en_fecha: date | None = None,
) -> dict[str, Any]:
    """Si ese precio lo puede dar el partner solo o necesita aprobación."""
    acuerdo = acuerdo_de(db, tenant_id, partner_id, en_fecha=en_fecha)
    lista = Decimal(precio_lista)
    ofertado = Decimal(precio_ofertado)
    descuento = _redondear((lista - ofertado) / lista * 100) if lista > 0 else Decimal(0)
    tope = Decimal(acuerdo.descuento_maximo_pct) if acuerdo is not None else Decimal(0)
    motivos: list[str] = []
    if descuento > tope:
        motivos.append(f"El descuento del {descuento} % supera el tope de canal del {tope} %")
    margen: Decimal | None = None
    if coste is not None and ofertado > 0:
        margen = _redondear((ofertado - Decimal(coste)) / ofertado * 100)
        minimo = acuerdo.margen_minimo_pct if acuerdo is not None else None
        if minimo is not None and margen < Decimal(minimo):
            motivos.append(f"El margen del {margen} % queda por debajo del {minimo} % pactado")
    return {
        "descuento_pct": str(descuento),
        "tope_pct": str(tope),
        "margen_pct": str(margen) if margen is not None else None,
        # Sin coste no se afirma que el margen está bien: no se ha medido.
        "margen_medido": margen is not None,
        "necesita_aprobacion": bool(motivos),
        "motivos": motivos,
        "hay_acuerdo": acuerdo is not None,
    }


# ── Rendimiento y planes conjuntos (CRM-03.04.01.06) ──────────────────────


def crear_plan(
    uow: UnidadDeTrabajo,
    partner_id: UUID,
    *,
    nombre: str,
    desde: date,
    hasta: date,
    objetivos: list[dict[str, Any]] | None = None,
    acciones: list[dict[str, Any]] | None = None,
) -> tuple[PlanConjunto, list[str]]:
    """Plan de negocio conjunto. Devuelve los avisos de lo que no se podrá medir."""
    _partner(uow.db, uow.tenant_id, partner_id)
    if hasta < desde:
        raise ErrorValidacion(
            "El plan termina antes de empezar.", error_code="partners.periodo_invalido"
        )
    avisos: list[str] = []
    for i, objetivo in enumerate(objetivos or [], 1):
        if not objetivo.get("metrica") or objetivo.get("objetivo") is None:
            avisos.append(
                f"Objetivo {i} sin métrica o sin número: no se podrá revisar en el cierre."
            )
    fila = PlanConjunto(
        tenant_id=uow.tenant_id,
        partner_id=partner_id,
        nombre=nombre.strip(),
        desde=desde,
        hasta=hasta,
        objetivos=list(objetivos or []),
        acciones=list(acciones or []),
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila, avisos


def revisar_plan(
    uow: UnidadDeTrabajo,
    plan_id: UUID,
    *,
    fecha: date | None = None,
    logrado: dict[str, Any] | None = None,
    notas: str = "",
) -> dict[str, Any]:
    """Anota una revisión y dice cómo va cada objetivo.

    La revisión se **guarda**, no se recalcula: el plan conjunto vale por lo que
    se habló en cada trimestre, y un porcentaje recalculado hoy no dice qué se
    decidió entonces.
    """
    plan = uow.db.get(PlanConjunto, plan_id)
    if plan is None or plan.tenant_id != uow.tenant_id:
        raise NoEncontrado("El plan no existe", error_code="partners.plan_no_encontrado")
    medido = logrado or {}
    detalle = []
    for objetivo in plan.objetivos or []:
        metrica = str(objetivo.get("metrica") or "")
        meta = objetivo.get("objetivo")
        valor = medido.get(metrica)
        detalle.append(
            {
                "metrica": metrica,
                "objetivo": str(meta) if meta is not None else None,
                "logrado": str(valor) if valor is not None else None,
                "pct": (
                    float(round(Decimal(str(valor)) / Decimal(str(meta)) * 100, 1))
                    if valor is not None and meta not in (None, 0, "0")
                    else None
                ),
                # Un objetivo sin dato no es un objetivo incumplido.
                "medible": valor is not None and meta not in (None, 0, "0"),
            }
        )
    revision = {
        "fecha": str(fecha or _hoy(uow.db)),
        "notas": notas,
        "detalle": detalle,
    }
    plan.revisiones = [*(plan.revisiones or []), revision]
    return revision


def rendimiento(
    db: Session,
    tenant_id: UUID,
    *,
    desde: date,
    hasta: date,
    cerrado_por_partner: dict[str, Decimal] | None = None,
) -> dict[str, Any]:
    """Cómo va cada partner: registros, conversión y cuota de canal
    (CRM-03.04.01.06).

    Lo cerrado **lo trae quien llama**, como en las cuotas de venta directa: el
    importe vive en las oportunidades y calcularlo aquí daría un segundo número
    del mismo negocio.

    La **conversión** es el número que importa de un canal: un partner que
    registra treinta clientes y cierra uno no está trabajando, está bloqueando
    treinta clientes a los demás. Eso no se ve en el importe.
    """
    from services.sales.territorios import Cuota, prorratear

    cerrado = cerrado_por_partner or {}
    partners = (
        db.execute(select(Partner).where(Partner.tenant_id == tenant_id, Partner.estado != "baja"))
        .scalars()
        .all()
    )
    registros = (
        db.execute(
            select(RegistroOportunidad).where(
                RegistroOportunidad.tenant_id == tenant_id,
                func.date(RegistroOportunidad.created_at) >= desde,
                func.date(RegistroOportunidad.created_at) <= hasta,
            )
        )
        .scalars()
        .all()
    )
    cuotas = (
        db.execute(
            select(Cuota).where(
                Cuota.tenant_id == tenant_id,
                Cuota.partner_id.is_not(None),
                Cuota.desde >= desde,
                Cuota.hasta <= hasta,
            )
        )
        .scalars()
        .all()
    )
    cuota_por_partner = {str(c.partner_id): c for c in cuotas}

    filas = []
    for partner in partners:
        mios = [r for r in registros if r.partner_id == partner.id]
        convertidos = [r for r in mios if r.estado == "convertido"]
        logrado = Decimal(cerrado.get(str(partner.id), 0))
        cuota = cuota_por_partner.get(str(partner.id))
        objetivo = Decimal(prorratear(cuota)["objetivo_efectivo"]) if cuota is not None else None
        filas.append(
            {
                "partner_id": str(partner.id),
                "clave": partner.clave,
                "nombre": partner.nombre,
                "estado": partner.estado,
                "registros": len(mios),
                "aprobados": len([r for r in mios if r.estado in ("aprobado", "convertido")]),
                "rechazados": len([r for r in mios if r.estado == "rechazado"]),
                "caducados": len([r for r in mios if r.estado == "caducado"]),
                "convertidos": len(convertidos),
                "conversion_pct": (
                    float(round(100 * len(convertidos) / len(mios), 1)) if mios else None
                ),
                "cerrado": str(logrado),
                "objetivo": str(objetivo) if objetivo is not None else None,
                "pct_cuota": (
                    float(round(100 * logrado / objetivo, 1))
                    if objetivo is not None and objetivo > 0
                    else None
                ),
                # Sin cuota de canal no se dice que va bien ni mal: no hay contra
                # qué medir, que es distinto de ir justo.
                "con_cuota": cuota is not None,
            }
        )
    filas.sort(key=lambda f: (f["pct_cuota"] is None, -(f["pct_cuota"] or 0)))
    return {
        "desde": str(desde),
        "hasta": str(hasta),
        "partners": filas,
        "medible": bool(cerrado),
        "aviso": (
            ""
            if cerrado
            else "No se ha pasado lo cerrado por partner: los importes salen a cero y "
            "no significan que no se haya vendido."
        ),
    }
