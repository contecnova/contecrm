"""Cuentas personales, plan de cuenta, estado financiero, mapa de influencia y
cambio de empresa (CRM-01.01.01.09, .11, .12 · CRM-01.01.02.03, .07).

Cinco cosas que parecen de la ficha y en realidad son de cómo se vende.

**Cuentas personales (B2C).** La tentación es crear un modelo aparte para el
particular. Con dos modelos, cada informe se escribe dos veces, la deduplicación
va por un lado y los permisos por otro, y a los seis meses uno de los dos está
peor mantenido. Es la misma cuenta con una marca — y con una consecuencia seria:
si la cuenta es una persona física, **la ficha entera es dato personal**, no solo
el contacto.

**Plan de cuenta.** Objetivos, hueco por cubrir, mapa de poder y riesgos. Lo que
lo hace útil o inútil es una sola cosa: si el hueco se **calcula** con lo que ya
se le vende, o si lo teclea el comercial. Tecleado es una lista de deseos.

**Estado financiero.** Riesgo, crédito disponible, deuda vencida y bloqueo. No es
del CRM: es del ERP. Aquí vive una **proyección con su fecha**, y el día que se
usa para bloquear una oferta hay que saber de cuándo es — bloquear con un dato de
hace tres semanas es casi peor que no bloquear.

**Mapa de influencia.** Quién reporta a quién, quién es aliado y quién detractor.
Vale para preparar una reunión y **no es un dato inocente**: «detractor» es una
opinión sobre una persona identificada, va con su motivo y no se enseña fuera.

**Cambio de empresa.** Cuando alguien se va, lo que no se puede hacer es mover el
contacto a la cuenta nueva. Su historia —los correos, las reuniones, lo que se
habló— es de la cuenta antigua, y moverlo la reescribe: esa cuenta pasaría a no
haber hablado nunca con nadie. Se crea la ficha nueva y se enlazan.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Qué relación puede haber entre dos personas de la misma cuenta. Cerrada porque
# de estas cuatro se saca el mapa de poder, y con texto libre no se puede dibujar
# nada ni avisar de nada.
RELACIONES = ("reporta_a", "aliado", "detractor", "influye_en", "sustituye_a")

# Opiniones sobre una persona identificada. No son un dato más: van con motivo,
# con autor y sin salir del CRM.
RELACIONES_QUE_SON_OPINION = ("aliado", "detractor")

# Estados del estado financiero replicado.
ESTADOS_FINANCIEROS = ("al_corriente", "vigilancia", "deuda_vencida", "bloqueado")

# Cuántos días puede tener la proyección financiera antes de que no valga para
# bloquear. Bloquear una oferta con un dato de hace tres semanas es casi peor que
# no bloquear: el comercial deja de creerse el bloqueo.
DIAS_FIABLE_FINANCIERO = 2


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


class PlanCuenta(Base, TimestampMixin, SoftDeleteMixin):
    """El plan de una cuenta: a dónde se quiere llegar y qué falta."""

    __tablename__ = "planes_cuenta"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    cuenta_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    periodo: Mapped[str] = mapped_column(String(20), nullable=False)
    objetivo_importe: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    objetivos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    riesgos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Qué del catálogo NO se le vende todavía. Se calcula, no se teclea.
    hueco: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    calculado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revisado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    responsable_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "cuenta_id", "periodo", name="uq_plan_cuenta"),)


class EstadoFinanciero(Base, TimestampMixin):
    """Lo que dice el ERP del crédito de esta cuenta, replicado con su fecha.

    Proyección local, no verdad propia: el dueño es el ERP y este servicio no lee
    su base. Por eso lleva `vigente_at` — sin esa fecha, un bloqueo se aplica con
    un dato de antigüedad desconocida.
    """

    __tablename__ = "estados_financieros"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    cuenta_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="al_corriente")
    limite_credito: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True, info={"sensibilidad": "confidencial"}
    )
    credito_dispuesto: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True, info={"sensibilidad": "confidencial"}
    )
    deuda_vencida: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True, info={"sensibilidad": "confidencial"}
    )
    dias_vencido_maximo: Mapped[int | None] = mapped_column(Numeric(6, 0), nullable=True)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    bloqueado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    motivo_bloqueo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # De cuándo es el dato en el sistema de origen, no cuándo llegó aquí.
    vigente_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    origen: Mapped[str] = mapped_column(String(80), nullable=False, default="")

    __table_args__ = (UniqueConstraint("tenant_id", "cuenta_id", name="uq_financiero_cuenta"),)


class RelacionPersona(Base, TimestampMixin, SoftDeleteMixin):
    """Quién es quién dentro de una cuenta: jerarquía, aliados y detractores."""

    __tablename__ = "relaciones_persona"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    origen_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    destino_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    # Una valoración sobre una persona sin el porqué es un rumor guardado en una
    # base de datos. Con el porqué, es información que otro puede contrastar.
    motivo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    anotada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "origen_id", "destino_id", "tipo", name="uq_relacion_persona"
        ),
        Index("ix_relaciones_persona", "tenant_id", "origen_id"),
    )


class CambioDeEmpresa(Base, TimestampMixin):
    """Alguien se ha ido de una cuenta a otra, detectado y por confirmar."""

    __tablename__ = "cambios_de_empresa"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    contacto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    cuenta_anterior_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    indicio: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    detalle: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # detectado | confirmado | descartado
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="detectado")
    contacto_nuevo_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    cuenta_nueva_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (Index("ix_cambios_empresa", "tenant_id", "estado"),)


# ── Cuentas personales (CRM-01.01.01.09) ──────────────────────────────────


def validar_cuenta_personal(*, datos: dict[str, Any]) -> dict[str, Any]:
    """Comprueba una cuenta que es una persona física.

    **No hay un modelo aparte.** Con dos, cada informe se escribe dos veces, la
    deduplicación va por un lado y los permisos por otro, y a los seis meses uno
    de los dos está peor mantenido.

    Lo que sí cambia son tres cosas, y ninguna es cosmética:

    * **La ficha entera pasa a ser dato personal.** No solo el contacto: el
      nombre de la cuenta es el nombre de alguien, y su dirección es su domicilio.
    * **Los campos de empresa dejan de tener sentido** y no se pueden exigir.
      Pedirle el CNAE a un particular es lo que hace que el comercial escriba
      cualquier cosa para poder guardar.
    * **El identificador fiscal es el suyo**, y eso es dato personal también.
    """
    problemas: list[str] = []
    if not str(datos.get("nombre") or "").strip():
        problemas.append("Una cuenta personal necesita el nombre de la persona")

    de_empresa = [
        c for c in ("sector_codigo", "empleados", "facturacion_anual") if datos.get(c) is not None
    ]
    return {
        "valido": not problemas,
        "problemas": problemas,
        "es_dato_personal_toda_la_ficha": True,
        "campos_de_empresa_presentes": de_empresa,
        "aviso": (
            ""
            if not de_empresa
            else f"Esta cuenta personal trae campos de empresa ({', '.join(de_empresa)}). "
            "No es un error, pero no significan nada aquí, y exigirlos es lo que hace "
            "que alguien escriba cualquier cosa para poder guardar."
        ),
        "que_implica": (
            "Toda la ficha es dato personal: el nombre de la cuenta es el nombre de "
            "una persona y su dirección es su domicilio. Los derechos de acceso, "
            "supresión y portabilidad aplican a la cuenta entera, no solo al contacto."
        ),
    }


# ── Plan de cuenta (CRM-01.01.01.11) ──────────────────────────────────────


def calcular_hueco(*, catalogo: list[dict[str, Any]], ya_le_vendemos: list[str]) -> dict[str, Any]:
    """Qué del catálogo no se le vende todavía — **calculado, no tecleado**.

    Es lo único que separa un plan de cuenta de una lista de deseos. Si el hueco
    lo escribe el comercial, escribe lo que tiene en la cabeza; calculado contra
    lo que ya se factura, aparece lo que nadie había mirado.
    """
    vendidos = {str(x) for x in ya_le_vendemos}
    hueco = [
        {
            "familia": p.get("familia"),
            "producto": p.get("clave"),
            "potencial": p.get("potencial"),
        }
        for p in catalogo
        if str(p.get("clave")) not in vendidos
    ]
    return {
        "hueco": sorted(hueco, key=lambda h: -(h.get("potencial") or 0)),
        "cubierto": sorted(vendidos),
        "pct_cubierto": (round(len(vendidos) / len(catalogo) * 100, 1) if catalogo else 0.0),
        "porque": (
            "Calculado contra lo que ya se le factura. Tecleado a mano, un plan de "
            "cuenta es una lista de deseos: sale lo que el comercial tiene en la "
            "cabeza, no lo que nadie ha mirado."
        ),
        "medible": bool(catalogo),
    }


def guardar_plan(
    uow: UnidadDeTrabajo,
    *,
    cuenta_id: UUID,
    periodo: str,
    objetivos: list[dict[str, Any]],
    riesgos: list[dict[str, Any]],
    hueco: list[dict[str, Any]],
    objetivo_importe: Decimal | None = None,
    responsable_id: UUID | None = None,
) -> PlanCuenta:
    """Guarda el plan, exigiendo que los objetivos tengan fecha y dueño.

    Un objetivo sin fecha y sin responsable no es un objetivo: es una frase. Y un
    plan lleno de frases se revisa una vez, en la reunión en la que se escribió.
    """
    sin_fecha = [o.get("titulo") for o in objetivos if not o.get("fecha_objetivo")]
    sin_dueno = [o.get("titulo") for o in objetivos if not o.get("responsable_id")]
    if sin_fecha or sin_dueno:
        raise ErrorValidacion(
            "Hay objetivos sin fecha o sin responsable. Un objetivo sin las dos cosas "
            "es una frase, y un plan de frases se revisa una vez: en la reunión en la "
            "que se escribió.",
            error_code="plan.objetivo_incompleto",
            detalle={"sin_fecha": sin_fecha, "sin_responsable": sin_dueno},
        )

    fila = uow.db.execute(
        select(PlanCuenta).where(
            PlanCuenta.tenant_id == uow.tenant_id,
            PlanCuenta.cuenta_id == cuenta_id,
            PlanCuenta.periodo == periodo,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = PlanCuenta(tenant_id=uow.tenant_id, cuenta_id=cuenta_id, periodo=periodo)
        uow.db.add(fila)

    fila.objetivos = objetivos
    fila.riesgos = riesgos
    fila.hueco = hueco
    fila.objetivo_importe = objetivo_importe
    fila.responsable_id = responsable_id
    fila.calculado_at = _ahora()
    uow.db.flush()
    return fila


def plan_caducado(
    *, revisado_at: datetime | None, dias: int = 90, ahora: datetime | None = None
) -> dict[str, Any]:
    """Si este plan lleva demasiado sin revisarse.

    Un plan anual que nadie toca desde enero no es un plan: es un documento. Se
    avisa en vez de dejarlo envejecer en silencio, porque en la reunión de
    seguimiento se enseña igual y nadie mira la fecha.
    """
    momento = ahora or _ahora()
    if revisado_at is None:
        return {
            "caducado": True,
            "nunca_revisado": True,
            "porque": "El plan no se ha revisado nunca desde que se escribió.",
        }
    revisado = revisado_at if revisado_at.tzinfo else revisado_at.replace(tzinfo=timezone.utc)
    dias_pasados = (momento - revisado).days
    return {
        "caducado": dias_pasados >= dias,
        "nunca_revisado": False,
        "dias_sin_revisar": dias_pasados,
        "porque": (
            f"Lleva {dias_pasados} días sin revisarse y el plazo son {dias}. Un plan "
            "que nadie toca no es un plan, es un documento — y en la reunión de "
            "seguimiento se enseña igual sin que nadie mire la fecha."
            if dias_pasados >= dias
            else f"Revisado hace {dias_pasados} días."
        ),
    }


# ── Estado financiero (CRM-01.01.01.12) ───────────────────────────────────


def replicar_financiero(
    uow: UnidadDeTrabajo,
    *,
    cuenta_id: UUID,
    estado: str,
    origen: str,
    vigente_at: datetime,
    limite_credito: Decimal | None = None,
    credito_dispuesto: Decimal | None = None,
    deuda_vencida: Decimal | None = None,
    dias_vencido_maximo: int | None = None,
    bloqueado: bool = False,
    motivo_bloqueo: str = "",
) -> EstadoFinanciero:
    """Guarda lo que dice el ERP, **con la fecha del origen**.

    `vigente_at` es de cuándo es el dato allí, no cuándo llegó aquí. La diferencia
    importa el día que se bloquea una oferta: si el dato es de hace tres semanas,
    el bloqueo es una suposición y hay que decirlo.

    Y un bloqueo **sin motivo no se guarda**: el comercial que se encuentra la
    oferta parada tiene que poder decirle algo al cliente que no sea «el sistema
    no me deja».
    """
    if estado not in ESTADOS_FINANCIEROS:
        raise ErrorValidacion(
            f"Estado financiero «{estado}» desconocido",
            error_code="financiero.estado_invalido",
            detalle={"admitidos": list(ESTADOS_FINANCIEROS)},
        )
    if bloqueado and not motivo_bloqueo.strip():
        raise ErrorValidacion(
            "Un bloqueo sin motivo deja al comercial con «el sistema no me deja» "
            "delante del cliente.",
            error_code="financiero.bloqueo_sin_motivo",
        )

    fila = uow.db.execute(
        select(EstadoFinanciero).where(
            EstadoFinanciero.tenant_id == uow.tenant_id,
            EstadoFinanciero.cuenta_id == cuenta_id,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = EstadoFinanciero(tenant_id=uow.tenant_id, cuenta_id=cuenta_id)
        uow.db.add(fila)

    fila.estado = estado
    fila.limite_credito = limite_credito
    fila.credito_dispuesto = credito_dispuesto
    fila.deuda_vencida = deuda_vencida
    fila.dias_vencido_maximo = dias_vencido_maximo
    fila.bloqueado = bloqueado
    fila.motivo_bloqueo = motivo_bloqueo.strip()
    fila.vigente_at = vigente_at
    fila.origen = origen
    uow.db.flush()
    return fila


def puede_comprometer(
    db: Session,
    tenant_id: UUID,
    *,
    cuenta_id: UUID,
    importe: Decimal,
    ahora: datetime | None = None,
) -> dict[str, Any]:
    """Si se le puede vender más a esta cuenta, y con qué confianza.

    Las tres respuestas son distintas y se distinguen:

    * **Sí**, con crédito disponible suficiente.
    * **No**, porque está bloqueada o no cabe.
    * **No se sabe**, porque no hay dato financiero o el que hay es viejo. Y
      «no se sabe» no se redondea a «sí»: dejar pasar la oferta y descubrir el
      impago después es exactamente lo que este dato existe para evitar.
    """
    momento = ahora or _ahora()
    fila = db.execute(
        select(EstadoFinanciero).where(
            EstadoFinanciero.tenant_id == tenant_id, EstadoFinanciero.cuenta_id == cuenta_id
        )
    ).scalar_one_or_none()

    if fila is None:
        return {
            "puede": None,
            "fiable": False,
            "porque": (
                "No hay estado financiero replicado de esta cuenta. No es que esté al "
                "corriente: es que no se sabe, y no es lo mismo."
            ),
            "que_hacer": "Comprobarlo en el ERP antes de comprometer nada grande.",
        }

    vigente = fila.vigente_at
    antiguedad = (
        (momento - (vigente if vigente.tzinfo else vigente.replace(tzinfo=timezone.utc))).days
        if vigente
        else None
    )
    fiable = antiguedad is not None and antiguedad <= DIAS_FIABLE_FINANCIERO

    if fila.bloqueado:
        return {
            "puede": False,
            "fiable": fiable,
            "porque": f"La cuenta está bloqueada: {fila.motivo_bloqueo}",
            "dato_de_hace_dias": antiguedad,
            "que_decirle_al_cliente": fila.motivo_bloqueo,
        }

    limite = fila.limite_credito
    dispuesto = fila.credito_dispuesto or Decimal(0)
    if limite is None:
        return {
            "puede": None,
            "fiable": False,
            "porque": (
                "No consta límite de crédito. Tratarlo como ilimitado es una decisión "
                "que nadie ha tomado."
            ),
            "dato_de_hace_dias": antiguedad,
        }

    disponible = limite - dispuesto
    cabe = importe <= disponible
    return {
        "puede": cabe,
        "fiable": fiable,
        "disponible": str(disponible),
        "dato_de_hace_dias": antiguedad,
        "porque": (
            f"Quedan {disponible} de límite y se piden {importe}."
            if cabe
            else f"Se piden {importe} y solo quedan {disponible} de crédito."
        ),
        "aviso": (
            ""
            if fiable
            else f"El dato financiero es de hace {antiguedad} días. Bloquear o dejar "
            "pasar con esto es una suposición: el comercial deja de creerse un bloqueo "
            "que se basa en algo de hace tres semanas."
        ),
    }


# ── Mapa de influencia (CRM-01.01.02.03) ──────────────────────────────────


def anotar_relacion(
    uow: UnidadDeTrabajo,
    *,
    origen_id: UUID,
    destino_id: UUID,
    tipo: str,
    motivo: str,
    por: UUID | None = None,
) -> RelacionPersona:
    """Anota que dos personas se relacionan de una forma concreta.

    **Una valoración exige motivo.** «Detractor» sin el porqué es un rumor
    guardado en una base de datos, y además es una opinión sobre una persona
    identificada: si algún día esa persona ejerce su derecho de acceso, lo que
    sale es eso.
    """
    if tipo not in RELACIONES:
        raise ErrorValidacion(
            f"Relación «{tipo}» desconocida",
            error_code="relacion.tipo_invalido",
            detalle={"admitidas": list(RELACIONES)},
        )
    if origen_id == destino_id:
        raise ErrorValidacion(
            "Una persona no se relaciona consigo misma", error_code="relacion.circular"
        )
    if tipo in RELACIONES_QUE_SON_OPINION and not motivo.strip():
        raise ErrorValidacion(
            f"«{tipo}» es una valoración sobre una persona: sin el porqué es un rumor "
            "guardado en una base de datos. Y si esa persona ejerce su derecho de "
            "acceso, lo que sale es esto.",
            error_code="relacion.opinion_sin_motivo",
        )

    fila = uow.db.execute(
        select(RelacionPersona).where(
            RelacionPersona.tenant_id == uow.tenant_id,
            RelacionPersona.origen_id == origen_id,
            RelacionPersona.destino_id == destino_id,
            RelacionPersona.tipo == tipo,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = RelacionPersona(
            tenant_id=uow.tenant_id, origen_id=origen_id, destino_id=destino_id, tipo=tipo
        )
        uow.db.add(fila)
    fila.motivo = motivo.strip()
    fila.anotada_por = por
    uow.db.flush()
    return fila


def mapa_de_poder(
    db: Session, tenant_id: UUID, *, contactos: list[dict[str, Any]]
) -> dict[str, Any]:
    """El mapa de la cuenta: quién manda, quién ayuda y quién estorba.

    Y lo que de verdad hace falta antes de una reunión: **con quién no se ha
    hablado nunca**. Un mapa que solo enseña a los conocidos confirma lo que el
    comercial ya sabía; el valor está en el decisor con el que nadie ha hablado.
    """
    ids = [UUID(str(c["id"])) for c in contactos if c.get("id")]
    relaciones = (
        list(
            db.execute(
                select(RelacionPersona).where(
                    RelacionPersona.tenant_id == tenant_id,
                    RelacionPersona.origen_id.in_(ids),
                )
            )
            .scalars()
            .all()
        )
        if ids
        else []
    )

    por_tipo: dict[str, list[dict[str, Any]]] = {}
    for rel in relaciones:
        por_tipo.setdefault(rel.tipo, []).append(
            {"de": str(rel.origen_id), "a": str(rel.destino_id), "motivo": rel.motivo}
        )

    sin_contacto = [
        {"contacto": str(c.get("id")), "nombre": c.get("nombre"), "rol": c.get("rol_compra")}
        for c in contactos
        if not c.get("ultima_interaccion")
    ]
    decisores_sin_contacto = [s for s in sin_contacto if s.get("rol") in ("decisor", "economico")]

    return {
        "relaciones": por_tipo,
        "personas": len(contactos),
        "sin_hablar_nunca": sin_contacto,
        "decisores_sin_hablar": decisores_sin_contacto,
        "que_mirar": (
            "Todo el mapa está cubierto."
            if not decisores_sin_contacto
            else f"Hay {len(decisores_sin_contacto)} personas con capacidad de decidir "
            "con las que no se ha hablado nunca. Es lo único que este mapa aporta que "
            "el comercial no supiera ya."
        ),
        "medible": bool(contactos),
    }


# ── Cambio de empresa (CRM-01.01.02.07) ───────────────────────────────────

# Señales de que alguien ya no está donde estaba. Ninguna es concluyente por sí
# sola, y por eso esto ABRE una sospecha en vez de cambiar la ficha.
INDICIOS = (
    "correo_rebotado",
    "respuesta_automatica_de_baja",
    "aparece_en_otra_cuenta",
    "lo_dijo_un_compañero",
    "cambio_en_fuente_externa",
)


def detectar_cambio(
    uow: UnidadDeTrabajo,
    *,
    contacto_id: UUID,
    cuenta_anterior_id: UUID | None,
    indicio: str,
    detalle: str,
) -> CambioDeEmpresa:
    """Abre la sospecha de que alguien ha cambiado de empresa.

    **Sospecha, no cambio.** Un correo que rebota puede ser un buzón lleno, y una
    respuesta automática puede ser una baja de tres meses. Cambiar la ficha con
    eso deja a un cliente activo marcado como que se fue, y a nadie llamándole.
    """
    if indicio not in INDICIOS:
        raise ErrorValidacion(
            f"Indicio «{indicio}» desconocido",
            error_code="cambio.indicio_invalido",
            detalle={"admitidos": list(INDICIOS)},
        )
    fila = uow.db.execute(
        select(CambioDeEmpresa).where(
            CambioDeEmpresa.tenant_id == uow.tenant_id,
            CambioDeEmpresa.contacto_id == contacto_id,
            CambioDeEmpresa.estado == "detectado",
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = CambioDeEmpresa(
            tenant_id=uow.tenant_id,
            contacto_id=contacto_id,
            cuenta_anterior_id=cuenta_anterior_id,
        )
        uow.db.add(fila)
    fila.indicio = indicio
    fila.detalle = detalle
    uow.db.flush()
    return fila


def confirmar_cambio(
    uow: UnidadDeTrabajo,
    *,
    cambio_id: UUID,
    cuenta_nueva_id: UUID,
    contacto_nuevo_id: UUID,
) -> dict[str, Any]:
    """Confirma el cambio **creando una ficha nueva, sin mover la antigua**.

    Mover el contacto a la cuenta nueva es lo cómodo y reescribe la historia: los
    correos, las reuniones y lo que se habló son de la cuenta antigua, y al
    moverlos esa cuenta pasa a no haber hablado nunca con nadie — justo cuando
    alguien intenta entender por qué se perdió.

    Se crean dos fichas enlazadas: la antigua se marca como que ya no está allí y
    la nueva hereda la relación personal, que es lo que de verdad se quiere
    conservar — y una razón para llamar.
    """
    fila = uow.db.get(CambioDeEmpresa, cambio_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("Ese cambio no existe", error_code="cambio.no_encontrado")
    if contacto_nuevo_id == fila.contacto_id:
        raise ErrorValidacion(
            "El contacto nuevo no puede ser el mismo registro: mover la ficha "
            "reescribiría la historia de la cuenta antigua, que pasaría a no haber "
            "hablado nunca con nadie.",
            error_code="cambio.no_se_mueve",
        )

    fila.estado = "confirmado"
    fila.cuenta_nueva_id = cuenta_nueva_id
    fila.contacto_nuevo_id = contacto_nuevo_id
    uow.db.flush()

    return {
        "contacto_anterior": str(fila.contacto_id),
        "contacto_nuevo": str(contacto_nuevo_id),
        "la_historia_se_queda_donde_estaba": True,
        "porque": (
            "Los correos y las reuniones son de la cuenta antigua. Moverlos la dejaría "
            "sin historia justo cuando alguien intenta entender por qué se perdió."
        ),
        "que_hacer_ahora": (
            "Llamarle. Alguien que acaba de llegar a otra empresa y ya conocía el "
            "producto es la oportunidad más barata que hay, y dura pocas semanas."
        ),
    }


def descartar_cambio(uow: UnidadDeTrabajo, *, cambio_id: UUID, motivo: str) -> dict[str, Any]:
    """El indicio no era nada. Se descarta **con motivo**.

    Sin el motivo, el mismo rebote vuelve a abrir la sospecha la semana que viene
    y alguien la vuelve a mirar. Dos veces es tolerable; a la quinta se deja de
    mirar la cola entera.
    """
    fila = uow.db.get(CambioDeEmpresa, cambio_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("Ese cambio no existe", error_code="cambio.no_encontrado")
    if not motivo.strip():
        raise ErrorValidacion(
            "Descartar sin motivo hace que el mismo indicio vuelva a abrir la sospecha "
            "la semana que viene, y a la quinta vez se deja de mirar la cola.",
            error_code="cambio.descarte_sin_motivo",
        )
    fila.estado = "descartado"
    fila.detalle = f"{fila.detalle} · Descartado: {motivo.strip()}"
    uow.db.flush()
    return {"cambio_id": str(fila.id), "estado": "descartado", "motivo": motivo.strip()}
