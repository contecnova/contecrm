"""Territorios, cuotas y capacidad (CRM-03.02.02.01 a CRM-03.02.02.07).

Un territorio decide **de quién es un cliente**, y por eso es la pieza que más
discusiones provoca de todo un CRM: cuando dos comerciales creen que una cuenta es
suya, el problema no es técnico.

Cinco decisiones que salen de ahí:

**La asignación se calcula, no se escribe a mano.** Con asignación manual, el
territorio existe en una hoja de cálculo y el CRM dice otra cosa; con reglas, el
CRM **es** la hoja de cálculo.

**Las excepciones son parte del modelo, no una corrupción de él.** Siempre hay una
cuenta nominal que lleva el director aunque esté en la zona de otro. Si no se puede
declarar, alguien la reasigna a mano y el siguiente recálculo se la quita.

**Un cambio de territorios se simula antes de publicarse.** Publicarlo y ver qué
pasa significa que doscientas cuentas cambian de dueño el lunes por la mañana, y
deshacerlo no devuelve las conversaciones que ya se tuvieron.

**La cuota se prorratea por días, no por meses.** Un comercial que entra el 20 de
febrero no tiene el mes entero, y darle la cuota completa hace que su primer
periodo sea imposible y el del equipo, injusto.

**La cobertura se mide contra la cuota que queda, no contra la del periodo.** A
mitad de trimestre, comparar el pipeline con la cuota entera dice que todo el mundo
va mal incluso cuando van bien.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, NoEncontrado
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

CENTIMO = Decimal("0.01")
# Por qué se puede recortar un territorio. Cerrado porque de aquí sale el informe
# de cobertura, y un criterio libre haría que dos territorios «por zona» no se
# pudieran comparar.
CRITERIOS = ("geografia", "sector", "tamano", "producto", "canal", "nominal")
# Qué se mide en una cuota. Cerrado por lo mismo.
METRICAS = ("importe", "unidades", "oportunidades", "nuevos_clientes", "margen")
PERIODOS = ("mensual", "trimestral", "anual")


class Territorio(Base, TimestampMixin, SoftDeleteMixin):
    """Un trozo de mercado con dueño (CRM-03.02.02.01, .02)."""

    __tablename__ = "territorios"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Jerarquía: un territorio cuelga de otro. Quien lleva el padre ve lo de los
    # hijos, igual que en la jerarquía de mando.
    padre_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    # Los criterios que lo definen, en la gramática de siempre.
    criterios: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Cuando dos territorios encajan, gana el de prioridad más baja. Declarado, no
    # implícito: con desempate por orden de inserción, el dueño de una cuenta
    # cambiaría al restaurar una copia de seguridad.
    prioridad: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    responsable_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, index=True
    )
    # borrador | publicado | archivado. Un territorio en borrador no asigna nada:
    # es lo que permite montar el mapa entero antes de que mueva una sola cuenta.
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="borrador")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_territorio_clave"),
        Index("ix_territorios_orden", "tenant_id", "estado", "prioridad"),
    )


class MiembroTerritorio(Base, TimestampMixin):
    """Quién trabaja un territorio, además del responsable."""

    __tablename__ = "miembros_territorio"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    territorio_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("territorios.id", ondelete="CASCADE"), nullable=False
    )
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # Solo lectura o también propiedad de las cuentas.
    solo_lectura: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("territorio_id", "usuario_id", name="uq_miembro_territorio"),
    )


class ExcepcionTerritorio(Base, TimestampMixin):
    """Una cuenta que va a otro territorio, por decisión (CRM-03.02.02.02).

    Siempre hay una cuenta nominal que lleva el director aunque esté en la zona de
    otro. Si no se puede declarar, alguien la reasigna a mano y el siguiente
    recálculo se la quita — y entonces nadie vuelve a fiarse del recálculo.
    """

    __tablename__ = "excepciones_territorio"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    cuenta_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    territorio_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # Por qué. Obligatorio: una excepción sin motivo es indistinguible de un error
    # y nadie se atreve a quitarla dos años después.
    motivo: Mapped[str] = mapped_column(String(300), nullable=False)
    hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    creada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "cuenta_id", name="uq_excepcion_cuenta"),)


class AsignacionTerritorio(Base):
    """A qué territorio pertenece cada cuenta, ya calculado."""

    __tablename__ = "asignaciones_territorio"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    cuenta_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    territorio_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # Por qué acabó aquí: la regla que ganó o la excepción. Sin esto, «¿por qué
    # esta cuenta es de Norte?» no tiene respuesta y la discusión no se cierra.
    por_que: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    por_excepcion: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    calculada_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "cuenta_id", name="uq_asignacion_cuenta"),
        Index("ix_asignaciones_territorio", "tenant_id", "territorio_id"),
    )


class Cuota(Base, TimestampMixin, SoftDeleteMixin):
    """Lo que alguien tiene que vender en un periodo (CRM-03.02.02.04)."""

    __tablename__ = "cuotas"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # A quién: una persona, un equipo o un territorio. Uno de los tres.
    usuario_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    equipo: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    territorio_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # …o un partner del canal indirecto (CRM-03.04.01.06). La cuota de canal es
    # la misma cuota: mismo prorrateo, mismo ranking y misma consecución. Con una
    # tabla aparte, el primer informe que mezclara canal y venta directa habría
    # tenido que sumar dos números calculados de dos maneras.
    partner_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)

    periodo: Mapped[str] = mapped_column(
        String(20), nullable=False, default="trimestral", info={"opciones": PERIODOS}
    )
    desde: Mapped[date] = mapped_column(Date, nullable=False)
    hasta: Mapped[date] = mapped_column(Date, nullable=False)
    metrica: Mapped[str] = mapped_column(
        String(30), nullable=False, default="importe", info={"opciones": METRICAS}
    )
    objetivo: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    # Acotada a una familia de producto, si hace falta.
    familia: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Prorrateo: desde y hasta cuándo cuenta de verdad esta persona
    # (CRM-03.02.02.05). Nulo = el periodo entero.
    activa_desde: Mapped[date | None] = mapped_column(Date, nullable=True)
    activa_hasta: Mapped[date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        Index("ix_cuotas_periodo", "tenant_id", "desde", "hasta"),
        Index("ix_cuotas_usuario", "tenant_id", "usuario_id", "desde"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _redondear(v: Decimal) -> Decimal:
    return Decimal(v).quantize(CENTIMO, rounding=ROUND_HALF_UP)


# ── Definición y asignación (CRM-03.02.02.01, .02) ────────────────────────


def validar_criterios(criterios: list[dict[str, Any]]) -> list[str]:
    """Comprueba los criterios de un territorio."""
    avisos: list[str] = []
    for criterio in criterios:
        tipo = str(criterio.get("tipo") or "")
        if tipo not in CRITERIOS:
            raise ErrorValidacion(
                f"Criterio «{tipo}» no válido.",
                error_code="territorio.criterio_no_valido",
                detalle={"validos": list(CRITERIOS)},
            )
        if not criterio.get("condiciones") and tipo != "nominal":
            raise ErrorValidacion(
                f"El criterio «{tipo}» no dice nada: sin condiciones no recorta nada.",
                error_code="territorio.criterio_vacio",
            )
    if not criterios:
        avisos.append(
            "El territorio no tiene criterios: le entrará todo lo que no encaje "
            "en otro más específico. Suele ser lo que se quiere del territorio "
            "«resto», y un error en cualquier otro."
        )
    return avisos


def crear(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    nombre: str,
    criterios: list[dict[str, Any]] | None = None,
    padre_id: UUID | None = None,
    prioridad: int = 100,
    responsable_id: UUID | None = None,
    descripcion: str = "",
) -> tuple[Territorio, list[str]]:
    """Crea un territorio **en borrador**.

    Nace en borrador a propósito: es lo que permite montar el mapa entero —con sus
    solapes y sus huecos— antes de que mueva una sola cuenta.
    """
    avisos = validar_criterios(list(criterios or []))
    if padre_id is not None:
        padre = uow.db.get(Territorio, padre_id)
        if padre is None or padre.tenant_id != uow.tenant_id:
            raise NoEncontrado(
                "El territorio padre no existe", error_code="territorio.padre_no_encontrado"
            )
    fila = Territorio(
        tenant_id=uow.tenant_id,
        clave=clave,
        nombre=nombre,
        descripcion=descripcion,
        criterios=list(criterios or []),
        padre_id=padre_id,
        prioridad=prioridad,
        responsable_id=responsable_id,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila, avisos


def _encaja(territorio: Territorio, cuenta: dict[str, Any]) -> tuple[bool, str]:
    """Si una cuenta cae en un territorio, y por qué regla."""
    from crmcore.authz.abac import Condicion

    if not territorio.criterios:
        return True, "sin criterios: le entra todo lo que no encaje en otro"
    ambito = {"cuenta": cuenta}
    for criterio in territorio.criterios:
        condiciones = [
            Condicion(
                atributo=str(c.get("atributo", "")),
                operador=str(c.get("operador", "=")),
                valor=c.get("valor"),
            )
            for c in (criterio.get("condiciones") or [])
            if isinstance(c, dict)
        ]
        if condiciones and all(c.evaluar(ambito) for c in condiciones):
            return True, f"criterio «{criterio.get('tipo')}»"
    return False, ""


def resolver(
    db: Session, tenant_id: UUID, cuenta: dict[str, Any], *, cuenta_id: UUID | None = None
) -> dict[str, Any]:
    """A qué territorio va esta cuenta, y **por qué**.

    El porqué se devuelve siempre. Sin él, «¿por qué esta cuenta es de Norte?» no
    tiene respuesta, y esa es justo la pregunta que abre la discusión entre dos
    comerciales — que no se cierra con un número, se cierra con una regla.
    """
    if cuenta_id is not None:
        excepcion = db.execute(
            select(ExcepcionTerritorio).where(
                ExcepcionTerritorio.tenant_id == tenant_id,
                ExcepcionTerritorio.cuenta_id == cuenta_id,
            )
        ).scalar_one_or_none()
        if excepcion is not None and (excepcion.hasta is None or excepcion.hasta >= date.today()):
            # La excepción manda sobre cualquier regla. Es el punto entero de que
            # exista: si una regla pudiera ganarle, no serviría para nada.
            territorio = db.get(Territorio, excepcion.territorio_id)
            return {
                "territorio_id": str(excepcion.territorio_id),
                "territorio": territorio.clave if territorio else "",
                "por_que": f"excepción declarada: {excepcion.motivo}",
                "por_excepcion": True,
            }

    publicados = (
        db.execute(
            select(Territorio)
            .where(
                Territorio.tenant_id == tenant_id,
                Territorio.estado == "publicado",
                Territorio.activo.is_(True),
            )
            .order_by(Territorio.prioridad, Territorio.clave)
        )
        .scalars()
        .all()
    )
    for territorio in publicados:
        encaja, motivo = _encaja(territorio, cuenta)
        if encaja:
            return {
                "territorio_id": str(territorio.id),
                "territorio": territorio.clave,
                "por_que": f"{territorio.nombre}: {motivo}",
                "por_excepcion": False,
            }
    # Sin territorio se dice, no se inventa uno. Una cuenta sin dueño es un
    # problema que hay que ver; asignarla al primero disponible lo esconde.
    return {
        "territorio_id": None,
        "territorio": None,
        "por_que": "No encaja en ningún territorio publicado.",
        "por_excepcion": False,
    }


def simular(db: Session, tenant_id: UUID, cuentas: list[dict[str, Any]]) -> dict[str, Any]:
    """Qué pasaría si se publicara el mapa tal como está (CRM-03.02.02.03).

    **Publicar y ver qué pasa** significa que doscientas cuentas cambian de dueño
    el lunes por la mañana, y deshacerlo no devuelve las conversaciones que ya se
    tuvieron.

    Se dice lo que cambia, lo que se queda **sin territorio** y lo que queda en
    **solape** —encaja en dos con la misma prioridad—, que es el error que produce
    una asignación que depende del orden alfabético.
    """
    actuales = {
        a.cuenta_id: a
        for a in db.execute(
            select(AsignacionTerritorio).where(AsignacionTerritorio.tenant_id == tenant_id)
        ).scalars()
    }
    publicados = (
        db.execute(
            select(Territorio)
            .where(Territorio.tenant_id == tenant_id, Territorio.activo.is_(True))
            .order_by(Territorio.prioridad, Territorio.clave)
        )
        .scalars()
        .all()
    )

    cambios: list[dict[str, Any]] = []
    sin_territorio: list[str] = []
    solapes: list[dict[str, Any]] = []
    sin_cambio = 0

    for cuenta in cuentas:
        cuenta_id = UUID(str(cuenta["id"])) if cuenta.get("id") else None
        encajan = [
            (t, motivo) for t in publicados for encaja, motivo in [_encaja(t, cuenta)] if encaja
        ]
        if len(encajan) > 1:
            primera, segunda = encajan[0][0], encajan[1][0]
            if primera.prioridad == segunda.prioridad:
                solapes.append(
                    {
                        "cuenta": str(cuenta_id) if cuenta_id else cuenta.get("nombre", ""),
                        "territorios": [primera.clave, segunda.clave],
                        "por_que": (
                            "los dos tienen prioridad "
                            f"{primera.prioridad}: quién gana depende del orden alfabético"
                        ),
                    }
                )
        nuevo = encajan[0][0] if encajan else None
        if nuevo is None:
            sin_territorio.append(str(cuenta_id) if cuenta_id else cuenta.get("nombre", ""))
            continue
        actual = actuales.get(cuenta_id) if cuenta_id else None
        if actual is None or actual.territorio_id != nuevo.id:
            anterior = None
            if actual is not None:
                fila = db.get(Territorio, actual.territorio_id)
                anterior = fila.clave if fila else None
            cambios.append(
                {
                    "cuenta": str(cuenta_id) if cuenta_id else cuenta.get("nombre", ""),
                    "de": anterior,
                    "a": nuevo.clave,
                    "responsable": str(nuevo.responsable_id) if nuevo.responsable_id else None,
                }
            )
        else:
            sin_cambio += 1

    return {
        "cuentas": len(cuentas),
        "cambian": cambios,
        "se_quedan": sin_cambio,
        # Lo que no encaja en ningún sitio se dice: una cuenta sin dueño es un
        # problema que hay que ver, no un hueco que se rellena solo.
        "sin_territorio": sin_territorio,
        # Y el solape, porque es el error que produce una asignación que depende
        # del orden alfabético — y nadie lo busca hasta que dos discuten.
        "solapes": solapes,
        "seguro_publicar": not solapes and not sin_territorio,
    }


def publicar(uow: UnidadDeTrabajo, territorio_id: UUID) -> dict[str, Any]:
    """Publica un territorio. A partir de aquí asigna."""
    fila = uow.db.get(Territorio, territorio_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("El territorio no existe", error_code="territorio.no_encontrado")
    validar_criterios(list(fila.criterios or []))
    if fila.estado == "publicado":
        fila.version += 1
    fila.estado = "publicado"
    uow.db.flush()
    uow.emitir(
        "territory.published",
        subject=("territorio", fila.id),
        data={"territorio": fila.clave, "version": fila.version},
    )
    return {"territorio": fila.clave, "version": fila.version}


def declarar_excepcion(
    uow: UnidadDeTrabajo,
    *,
    cuenta_id: UUID,
    territorio_id: UUID,
    motivo: str,
    hasta: date | None = None,
    por: UUID | None = None,
) -> ExcepcionTerritorio:
    """Saca una cuenta de su territorio por regla y la pone en otro.

    **El motivo es obligatorio.** Una excepción sin motivo es indistinguible de un
    error, y dos años después nadie se atreve a quitarla porque nadie sabe por qué
    está.
    """
    if not motivo.strip():
        raise ErrorValidacion(
            "Una excepción sin motivo es indistinguible de un error, y nadie se "
            "atreve a quitarla dos años después.",
            error_code="territorio.excepcion_sin_motivo",
        )
    territorio = uow.db.get(Territorio, territorio_id)
    if territorio is None or territorio.tenant_id != uow.tenant_id:
        raise NoEncontrado("El territorio no existe", error_code="territorio.no_encontrado")

    fila = uow.db.execute(
        select(ExcepcionTerritorio).where(
            ExcepcionTerritorio.tenant_id == uow.tenant_id,
            ExcepcionTerritorio.cuenta_id == cuenta_id,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = ExcepcionTerritorio(tenant_id=uow.tenant_id, cuenta_id=cuenta_id)
        uow.db.add(fila)
    fila.territorio_id = territorio_id
    fila.motivo = motivo.strip()
    fila.hasta = hasta
    fila.creada_por = por
    uow.db.flush()
    return fila


def aplicar(uow: UnidadDeTrabajo, tenant_id: UUID, cuentas: list[dict[str, Any]]) -> dict[str, Any]:
    """Escribe las asignaciones calculadas."""
    asignadas = 0
    sin_territorio: list[str] = []
    for cuenta in cuentas:
        if not cuenta.get("id"):
            continue
        cuenta_id = UUID(str(cuenta["id"]))
        resultado = resolver(uow.db, tenant_id, cuenta, cuenta_id=cuenta_id)
        if resultado["territorio_id"] is None:
            sin_territorio.append(str(cuenta_id))
            continue
        fila = uow.db.execute(
            select(AsignacionTerritorio).where(
                AsignacionTerritorio.tenant_id == tenant_id,
                AsignacionTerritorio.cuenta_id == cuenta_id,
            )
        ).scalar_one_or_none()
        if fila is None:
            fila = AsignacionTerritorio(tenant_id=tenant_id, cuenta_id=cuenta_id)
            uow.db.add(fila)
        fila.territorio_id = UUID(resultado["territorio_id"])
        fila.por_que = resultado["por_que"][:300]
        fila.por_excepcion = resultado["por_excepcion"]
        fila.calculada_at = _ahora()
        asignadas += 1
    uow.db.flush()
    return {
        "asignadas": asignadas,
        "sin_territorio": sin_territorio,
        "medible": bool(cuentas),
    }


# ── Cuotas y prorrateo (CRM-03.02.02.04, .05) ─────────────────────────────


def crear_cuota(
    uow: UnidadDeTrabajo,
    *,
    desde: date,
    hasta: date,
    objetivo: Decimal,
    usuario_id: UUID | None = None,
    equipo: str | None = None,
    territorio_id: UUID | None = None,
    partner_id: UUID | None = None,
    periodo: str = "trimestral",
    metrica: str = "importe",
    moneda: str = "EUR",
    familia: str | None = None,
    activa_desde: date | None = None,
    activa_hasta: date | None = None,
) -> Cuota:
    """Fija una cuota. Exige un sujeto y que el periodo tenga sentido."""
    if metrica not in METRICAS:
        raise ErrorValidacion(
            f"Métrica «{metrica}» no válida.",
            error_code="cuota.metrica_no_valida",
            detalle={"validas": list(METRICAS)},
        )
    if periodo not in PERIODOS:
        raise ErrorValidacion(
            f"Periodo «{periodo}» no válido.",
            error_code="cuota.periodo_no_valido",
            detalle={"validos": list(PERIODOS)},
        )
    if hasta <= desde:
        raise ErrorValidacion(
            "El periodo acaba antes de empezar.", error_code="cuota.periodo_invalido"
        )
    if not any((usuario_id, equipo, territorio_id, partner_id)):
        raise ErrorValidacion(
            "Una cuota sin sujeto no la cumple nadie: hace falta una persona, un "
            "equipo, un territorio o un partner.",
            error_code="cuota.sin_sujeto",
        )
    fila = Cuota(
        tenant_id=uow.tenant_id,
        usuario_id=usuario_id,
        equipo=equipo,
        territorio_id=territorio_id,
        partner_id=partner_id,
        periodo=periodo,
        desde=desde,
        hasta=hasta,
        metrica=metrica,
        objetivo=objetivo,
        moneda=moneda,
        familia=familia,
        activa_desde=activa_desde,
        activa_hasta=activa_hasta,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def prorratear(cuota: Cuota) -> dict[str, Any]:
    """Qué parte de la cuota le corresponde de verdad (CRM-03.02.02.05).

    **Por días, no por meses.** Un comercial que entra el 20 de febrero no tiene el
    mes entero, y darle la cuota completa hace que su primer periodo sea imposible
    y el del equipo, injusto: alguien tendrá que cubrir lo que él no podía hacer.

    Se devuelve también el objetivo **sin prorratear**, porque el número del plan
    anual sigue siendo ese y quien mire el informe tiene que ver los dos.
    """
    dias_periodo = (cuota.hasta - cuota.desde).days + 1
    inicio = max(cuota.activa_desde or cuota.desde, cuota.desde)
    fin = min(cuota.activa_hasta or cuota.hasta, cuota.hasta)
    dias_activos = max((fin - inicio).days + 1, 0)

    if dias_periodo <= 0:
        return {"objetivo": str(cuota.objetivo), "prorrateado": False}

    factor = Decimal(dias_activos) / Decimal(dias_periodo)
    prorrateado = _redondear(Decimal(cuota.objetivo) * factor)
    return {
        "objetivo_periodo": str(cuota.objetivo),
        "objetivo_efectivo": str(prorrateado),
        "dias_periodo": dias_periodo,
        "dias_activos": dias_activos,
        "prorrateado": dias_activos < dias_periodo,
        # Lo que NO cubre nadie si la cuota se prorratea y no se reparte. Es el
        # número que se olvida: el equipo sigue teniendo el objetivo entero.
        "hueco": str(_redondear(Decimal(cuota.objetivo) - prorrateado)),
    }


def consecucion(
    db: Session,
    tenant_id: UUID,
    *,
    desde: date,
    hasta: date,
    logrado_por_sujeto: dict[str, Decimal] | None = None,
) -> dict[str, Any]:
    """Cuánto lleva cada uno de su cuota, y el ranking (CRM-03.02.02.06).

    `logrado_por_sujeto` lo trae quien llama, con lo cerrado de verdad. **No se
    calcula aquí**: lo ganado vive en las oportunidades, y leerlo desde este
    módulo sería recalcular el forecast por segunda vez con otro criterio — y dos
    números distintos de lo mismo es peor que uno solo.

    El ranking sale **por porcentaje y no por importe**: por importe, quien lleva
    la cuenta grande gana siempre y el ranking deja de decir nada sobre quién
    trabaja bien.
    """
    logrado_por_sujeto = logrado_por_sujeto or {}
    cuotas = (
        db.execute(
            select(Cuota).where(
                Cuota.tenant_id == tenant_id, Cuota.desde >= desde, Cuota.hasta <= hasta
            )
        )
        .scalars()
        .all()
    )
    filas: list[dict[str, Any]] = []
    for cuota in cuotas:
        sujeto = (
            str(cuota.usuario_id)
            if cuota.usuario_id
            else (
                cuota.equipo
                or (str(cuota.partner_id) if cuota.partner_id else "")
                or str(cuota.territorio_id or "")
            )
        )
        detalle = prorratear(cuota)
        objetivo = Decimal(detalle["objetivo_efectivo"])
        logrado = Decimal(logrado_por_sujeto.get(sujeto, 0))
        filas.append(
            {
                "sujeto": sujeto,
                "tipo": "usuario"
                if cuota.usuario_id
                else (
                    "equipo" if cuota.equipo else ("partner" if cuota.partner_id else "territorio")
                ),
                "metrica": cuota.metrica,
                "objetivo": str(objetivo),
                "objetivo_sin_prorratear": detalle["objetivo_periodo"],
                "prorrateado": detalle["prorrateado"],
                "logrado": str(logrado),
                "pct": float(round(100 * logrado / objetivo, 1)) if objetivo > 0 else None,
                "falta": str(_redondear(max(objetivo - logrado, Decimal(0)))),
            }
        )

    con_pct = [f for f in filas if f["pct"] is not None]
    con_pct.sort(key=lambda f: -f["pct"])
    for i, fila in enumerate(con_pct, 1):
        fila["puesto"] = i

    return {
        "cuotas": filas,
        "ranking": con_pct,
        # Sin cuotas no se dice que se va bien: se dice que no hay contra qué
        # medir, que es distinto.
        "medible": bool(filas),
        "aviso": "" if filas else "No hay cuotas fijadas en ese periodo: no hay contra qué medir.",
    }


def cobertura(
    db: Session,
    tenant_id: UUID,
    *,
    desde: date,
    hasta: date,
    pipeline_por_sujeto: dict[str, Decimal] | None = None,
    logrado_por_sujeto: dict[str, Decimal] | None = None,
    en_fecha: date | None = None,
    minimo: Decimal = Decimal(3),
) -> dict[str, Any]:
    """Si hay pipeline suficiente para llegar (CRM-03.02.02.07).

    **Se mide contra la cuota que QUEDA, no contra la del periodo.** A mitad de
    trimestre, comparar el pipeline con la cuota entera dice que todo el mundo va
    mal incluso cuando van bien, y a fuerza de decirlo deja de mirarse.

    La cobertura mínima —tres veces lo que falta— es un ajuste y no una ley: un
    equipo que cierra el 50 % necesita dos y uno que cierra el 15 % necesita casi
    siete. Se devuelve el valor usado para que quien lo lea sepa contra qué se
    está comparando.
    """
    hoy = en_fecha or date.today()
    pipeline_por_sujeto = pipeline_por_sujeto or {}
    estado = consecucion(
        db, tenant_id, desde=desde, hasta=hasta, logrado_por_sujeto=logrado_por_sujeto
    )

    filas: list[dict[str, Any]] = []
    for cuota in estado["cuotas"]:
        falta = Decimal(cuota["falta"])
        pipeline = Decimal(pipeline_por_sujeto.get(cuota["sujeto"], 0))
        ratio = (pipeline / falta) if falta > 0 else None
        filas.append(
            {
                **cuota,
                "pipeline": str(pipeline),
                "cobertura": float(round(ratio, 2)) if ratio is not None else None,
                "suficiente": bool(ratio is not None and ratio >= minimo),
                # Ya cumplida es distinto de «cobertura infinita»: quien lo lea
                # tiene que ver que ese no necesita más pipeline, no que tiene
                # muchísimo.
                "ya_cumplida": falta <= 0,
            }
        )

    return {
        "en_fecha": str(hoy),
        "cobertura_minima": str(minimo),
        "sujetos": filas,
        "en_riesgo": [f for f in filas if not f["suficiente"] and not f["ya_cumplida"]],
        "medible": estado["medible"],
        "aviso": estado["aviso"],
    }
