"""Enrutamiento y asignación de leads por reglas (CRM-01.01.03.04).

Un lead que entra y se queda sin dueño es un lead perdido: nadie lo mira porque
no sale en la lista de nadie. Esto decide **quién** lo atiende en el momento en
que entra, sin intervención humana, y deja escrito **por qué** lo decidió.

Las reglas son **datos**, no código. Las condiciones se evalúan con el mismo
motor que las políticas ABAC (`crmcore.authz.abac`), y esa reutilización no es
por ahorrar líneas: es para que el operador aprenda una sola sintaxis de
condición en todo el producto, y para que el día que se añada un operador lo
tengan las dos cosas.

**Toda asignación queda trazada.** `RegistroEnrutamiento` guarda la regla que
ganó, las que se evaluaron antes y por qué no ganaron. Sin eso, la pregunta
«¿por qué este lead le cayó a Marta y no a mí?» no tiene respuesta, y la
confianza en el reparto automático se pierde en la primera discusión.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.authz.abac import Condicion
from crmcore.db.base import Base, EntidadBase
from crmcore.errors import ErrorValidacion
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
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

# Estrategias de reparto dentro de un grupo de candidatos.
ESTRATEGIAS = {
    "round_robin": "Por turnos: el siguiente de la lista, en orden estable",
    "menos_carga": "Al que menos leads abiertos tenga ahora mismo",
    "primero_disponible": "Al primero de la lista que esté disponible",
    "fijo": "Siempre al mismo usuario",
}


class ReglaEnrutamiento(EntidadBase):
    """Una regla de reparto: si se cumplen las condiciones, asigna así.

    Se evalúan por `prioridad` ascendente y gana **la primera** que encaja, no
    la mejor: con varias que puntúan, explicar el resultado deja de ser posible
    y el operador pierde el control sobre su propio reparto.
    """

    __tablename__ = "reglas_enrutamiento"

    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    prioridad: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Condiciones en el formato de `crmcore.authz.abac.Condicion`:
    # [{"atributo": "lead.pais", "operador": "en", "valor": ["ES", "PT"]}]
    condiciones: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    combinacion: Mapped[str] = mapped_column(String(10), nullable=False, default="todas")

    estrategia: Mapped[str] = mapped_column(String(30), nullable=False, default="round_robin")
    # Candidatos entre los que reparte. Lista de IDs de usuario: se resuelve en
    # ventas y no se consulta a identidad en caliente, porque el enrutamiento
    # corre en el camino de entrada del lead y una llamada de red ahí convierte
    # una caída de identidad en leads sin asignar.
    candidatos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Cola a la que va si ningún candidato sirve. Un equipo, no una persona.
    cola: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Estado del round-robin: posición del último asignado. Va en la fila de la
    # regla y no en memoria porque el servicio tiene varias réplicas y un
    # contador en proceso repartiría todo al mismo cuando escala.
    cursor_turno: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("tenant_id", "nombre", name="uq_regla_enrutamiento_nombre"),
        Index("ix_reglas_enrutamiento_orden", "tenant_id", "activa", "prioridad"),
    )


class RegistroEnrutamiento(Base):
    """Por qué este lead acabó en manos de esta persona.

    Append-only y con el detalle de las reglas descartadas. Es lo que convierte
    el reparto automático en algo que se puede defender en una reunión.
    """

    __tablename__ = "registro_enrutamiento"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    lead_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    regla_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    regla_nombre: Mapped[str | None] = mapped_column(String(150), nullable=True)
    asignado_a: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    cola: Mapped[str | None] = mapped_column(String(80), nullable=True)
    estrategia: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # [{"regla": "...", "resultado": "no_encaja", "condicion_fallida": "..."}]
    evaluadas: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_registro_enrutamiento_lead", "tenant_id", "lead_id", "created_at"),)


def _condiciones_de(regla: ReglaEnrutamiento) -> list[Condicion]:
    """Convierte el JSON de la regla en condiciones evaluables.

    Las condiciones mal formadas se **descartan con aviso** en vez de reventar:
    una regla con una errata no puede dejar sin asignar todos los leads que
    entren desde ese momento. Descartada la condición, la regla se evalúa con
    las demás; si se queda sin ninguna, no encaja con nada (ver `_encaja`).
    """
    salida: list[Condicion] = []
    for bruto in regla.condiciones or []:
        try:
            salida.append(
                Condicion(
                    atributo=bruto["atributo"],
                    operador=bruto["operador"],
                    valor=bruto.get("valor"),
                )
            )
        except (KeyError, TypeError):
            logger.warning(
                "enrutamiento.condicion_mal_formada", regla=regla.nombre, condicion=str(bruto)[:200]
            )
    return salida


def _encaja(regla: ReglaEnrutamiento, ambito: dict[str, Any]) -> tuple[bool, str | None]:
    """Si la regla aplica, y si no, cuál fue la condición que lo impidió.

    Una regla **sin condiciones válidas no encaja con nada**. Lo contrario
    —tratarla como comodín— haría que una errata en la única condición
    convirtiera una regla específica en la que se lleva todos los leads.
    """
    condiciones = _condiciones_de(regla)
    if not condiciones:
        return False, "sin condiciones válidas"

    if regla.combinacion == "alguna":
        for cond in condiciones:
            if cond.evaluar(ambito):
                return True, None
        return False, "ninguna de las condiciones se cumple"

    for cond in condiciones:
        if not cond.evaluar(ambito):
            return False, f"{cond.atributo} {cond.operador} {cond.valor!r}"
    return True, None


def _carga_abierta(db: Session, tenant_id: UUID, usuarios: list[UUID]) -> dict[UUID, int]:
    """Leads abiertos por usuario. Una sola consulta agregada, no una por usuario."""
    from services.sales.modelos import Lead

    filas = db.execute(
        select(Lead.owner_id, func.count())
        .where(
            Lead.tenant_id == tenant_id,
            Lead.owner_id.in_(usuarios),
            Lead.estado.in_(("nuevo", "contactado", "cualificado")),
            Lead.deleted_at.is_(None),
        )
        .group_by(Lead.owner_id)
    ).all()
    conteo = {u: 0 for u in usuarios}
    conteo.update({fila[0]: fila[1] for fila in filas})
    return conteo


def _elegir(
    db: Session, regla: ReglaEnrutamiento, tenant_id: UUID, disponibles: set[UUID] | None
) -> UUID | None:
    """Aplica la estrategia de reparto sobre los candidatos de la regla."""
    candidatos = [UUID(str(c)) for c in (regla.candidatos or [])]
    if disponibles is not None:
        candidatos = [c for c in candidatos if c in disponibles]
    if not candidatos:
        return None

    if regla.estrategia == "fijo" or regla.estrategia == "primero_disponible":
        return candidatos[0]

    if regla.estrategia == "menos_carga":
        carga = _carga_abierta(db, tenant_id, candidatos)
        # El desempate es por el orden declarado, no arbitrario: con dos a cero
        # leads, repartir al azar hace que dos ejecuciones iguales den resultados
        # distintos y que el reparto no se pueda reproducir al investigarlo.
        return min(candidatos, key=lambda u: (carga.get(u, 0), candidatos.index(u)))

    # round_robin: avanza el cursor guardado en la propia fila.
    indice = regla.cursor_turno % len(candidatos)
    regla.cursor_turno = (regla.cursor_turno + 1) % max(len(candidatos), 1)
    return candidatos[indice]


def enrutar(
    db: Session,
    lead: Any,
    *,
    tenant_id: UUID,
    disponibles: set[UUID] | None = None,
) -> RegistroEnrutamiento:
    """Decide el dueño de un lead y deja la traza de por qué.

    `disponibles` acota los candidatos a quien esté de alta y activo. Se pasa
    desde fuera en vez de consultarlo aquí para no acoplar ventas a identidad en
    el camino caliente; si no se pasa, se reparte entre todos los candidatos
    declarados.

    **Siempre devuelve un registro**, incluso cuando no asigna: un lead que
    ninguna regla reclama tiene que salir en algún sitio, y ese sitio es la cola
    por defecto más esta traza. Silenciarlo es como se acumulan leads que nadie
    ve.
    """
    ambito = {
        "lead": {
            "pais": lead.pais,
            "origen": lead.origen,
            "estado": lead.estado,
            "empresa": lead.empresa,
            "email": lead.email,
            "cargo": lead.cargo,
            "campana_id": str(lead.campana_id) if lead.campana_id else None,
            "utm": lead.utm or {},
            "campos": getattr(lead, "campos", {}) or {},
        },
        "contexto": {"ahora": datetime.now(timezone.utc).isoformat()},
    }

    reglas = (
        db.execute(
            select(ReglaEnrutamiento)
            .where(ReglaEnrutamiento.tenant_id == tenant_id, ReglaEnrutamiento.activa.is_(True))
            .order_by(ReglaEnrutamiento.prioridad, ReglaEnrutamiento.nombre)
        )
        .scalars()
        .all()
    )

    evaluadas: list[dict[str, Any]] = []
    for regla in reglas:
        encaja, motivo = _encaja(regla, ambito)
        if not encaja:
            evaluadas.append({"regla": regla.nombre, "resultado": "no_encaja", "motivo": motivo})
            continue

        elegido = _elegir(db, regla, tenant_id, disponibles)
        if elegido is None and not regla.cola:
            # Encaja pero no tiene a quién asignar: se anota y se sigue, porque
            # una regla sin candidatos disponibles no debe bloquear a las
            # siguientes. Es lo que pasa en agosto con un equipo de vacaciones.
            evaluadas.append({"regla": regla.nombre, "resultado": "sin_candidatos_disponibles"})
            continue

        evaluadas.append({"regla": regla.nombre, "resultado": "gana"})
        registro = RegistroEnrutamiento(
            tenant_id=tenant_id,
            lead_id=lead.id,
            regla_id=regla.id,
            regla_nombre=regla.nombre,
            asignado_a=elegido,
            cola=regla.cola if elegido is None else None,
            estrategia=regla.estrategia,
            evaluadas=evaluadas,
        )
        db.add(registro)
        if elegido is not None:
            lead.owner_id = elegido
            lead.asignado_at = datetime.now(timezone.utc)
        logger.info(
            "lead.enrutado",
            lead_id=str(lead.id),
            regla=regla.nombre,
            asignado_a=str(elegido) if elegido else None,
            cola=registro.cola,
        )
        return registro

    # Ninguna regla encajó: cola por defecto, y queda anotado.
    registro = RegistroEnrutamiento(
        tenant_id=tenant_id,
        lead_id=lead.id,
        asignado_a=None,
        cola="sin_asignar",
        evaluadas=evaluadas,
    )
    db.add(registro)
    logger.info("lead.sin_regla", lead_id=str(lead.id), reglas_evaluadas=len(evaluadas))
    return registro


def explicar(db: Session, lead_id: UUID, tenant_id: UUID) -> list[dict[str, Any]]:
    """Historial de decisiones de reparto de un lead, de la más reciente atrás."""
    filas = (
        db.execute(
            select(RegistroEnrutamiento)
            .where(
                RegistroEnrutamiento.tenant_id == tenant_id,
                RegistroEnrutamiento.lead_id == lead_id,
            )
            .order_by(RegistroEnrutamiento.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "cuando": f.created_at.isoformat() if f.created_at else None,
            "regla": f.regla_nombre,
            "asignado_a": str(f.asignado_a) if f.asignado_a else None,
            "cola": f.cola,
            "estrategia": f.estrategia,
            "evaluadas": f.evaluadas,
        }
        for f in filas
    ]


def validar_regla(datos: dict[str, Any]) -> None:
    """Comprueba una regla ANTES de guardarla.

    Se valida al escribir y no al evaluar porque el momento de evaluar es el de
    la entrada de un lead: allí un error no se puede devolver a nadie, y lo
    único que cabe es descartar la regla y seguir. El sitio donde una errata
    todavía tiene a alguien delante para corregirla es este.
    """
    from crmcore.authz.abac import OPERADORES

    estrategia = datos.get("estrategia", "round_robin")
    if estrategia not in ESTRATEGIAS:
        raise ErrorValidacion(
            f"Estrategia desconocida: «{estrategia}»",
            error_code="sales.estrategia_desconocida",
            detalle={"admitidas": sorted(ESTRATEGIAS)},
        )
    if datos.get("combinacion", "todas") not in ("todas", "alguna"):
        raise ErrorValidacion(
            "La combinación solo puede ser «todas» o «alguna»",
            error_code="sales.combinacion_invalida",
        )
    condiciones = datos.get("condiciones") or []
    if not condiciones:
        raise ErrorValidacion(
            "Una regla sin condiciones no se aplicaría nunca; si quieres una "
            "regla de último recurso, ponle una condición siempre cierta.",
            error_code="sales.regla_sin_condiciones",
        )
    for i, cond in enumerate(condiciones):
        if not isinstance(cond, dict) or "atributo" not in cond or "operador" not in cond:
            raise ErrorValidacion(
                f"La condición {i + 1} necesita «atributo» y «operador»",
                error_code="sales.condicion_incompleta",
            )
        if cond["operador"] not in OPERADORES:
            raise ErrorValidacion(
                f"Operador desconocido en la condición {i + 1}: «{cond['operador']}»",
                error_code="sales.operador_desconocido",
                detalle={"admitidos": sorted(OPERADORES)},
            )
    if estrategia != "fijo" and not datos.get("candidatos") and not datos.get("cola"):
        raise ErrorValidacion(
            "La regla necesita candidatos o una cola: si no, encajaría sin "
            "poder asignar y el lead se quedaría sin dueño.",
            error_code="sales.regla_sin_destino",
        )
