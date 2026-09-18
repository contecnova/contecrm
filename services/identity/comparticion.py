"""Reglas de compartición: quién ve qué registro (CRM-00.05.02.04).

El permiso dice si alguien puede leer cuentas; la compartición dice **cuáles**.
Son cosas distintas y mezclarlas lleva al error más caro de un CRM: o todo el
mundo lo ve todo, o cada excepción se resuelve dando permisos de más.

Cinco vías, y se **suman** —nunca se restan—:

  * **Propietario**: el registro es tuyo.
  * **Jerarquía**: eres el responsable de quien lo posee, directo o no.
  * **Equipo**: estás en el equipo de esa cuenta.
  * **Criterio**: una regla que comparte todo lo que cumpla una condición
    («todas las cuentas del País Vasco con el equipo de Bilbao»).
  * **Manual y temporal**: alguien te lo compartió, con o sin fecha de fin.

Que solo sumen es lo que hace posible responder a «¿por qué ve esto?» con una
lista de motivos. Con reglas que además quitan, la respuesta exige ejecutar el
motor entero y no se puede explicar.

**Lo que esto NO hace todavía, dicho claramente**: no reescribe las consultas de
los demás servicios. Devuelve el conjunto de identificadores visibles y la
explicación; aplicarlo en cada listado es trabajo del servicio dueño del objeto,
y está pendiente en `party` y `sales` (ver el manual, «Lo que está a medias»).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Index,
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


class ReglaComparticion(Base, TimestampMixin):
    """Una regla que comparte registros por criterio."""

    __tablename__ = "reglas_comparticion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    objeto: Mapped[str] = mapped_column(String(80), nullable=False)
    # Condiciones sobre el registro, en la misma forma que las de ABAC y las
    # automatizaciones: una sola gramática para todo el producto, en vez de tres
    # que se parecen y se comportan distinto.
    condiciones: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    combinacion: Mapped[str] = mapped_column(String(10), nullable=False, default="todas")

    # A quién se comparte: usuario, rol o unidad de negocio.
    destino_tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    destino_id: Mapped[str] = mapped_column(String(80), nullable=False)
    acceso: Mapped[str] = mapped_column(String(20), nullable=False, default="lectura")
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "nombre", name="uq_regla_comparticion"),
        Index("ix_reglas_comparticion", "tenant_id", "objeto", "activa"),
    )


class ComparticionManual(Base, TimestampMixin):
    """Un registro compartido a mano con alguien, con caducidad opcional.

    La caducidad es lo que hace que esto no se convierta en un acceso permanente
    concedido para una tarde: «compártemelo para revisar la propuesta» son tres
    días, no para siempre.
    """

    __tablename__ = "comparticiones_manuales"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    objeto: Mapped[str] = mapped_column(String(80), nullable=False)
    registro_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    acceso: Mapped[str] = mapped_column(String(20), nullable=False, default="lectura")
    motivo: Mapped[str | None] = mapped_column(Text, nullable=True)
    compartido_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    hasta: Mapped[date | None] = mapped_column(Date, nullable=True)
    revocada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_comparticiones_usuario", "tenant_id", "usuario_id", "objeto"),
        Index("ix_comparticiones_registro", "tenant_id", "objeto", "registro_id"),
    )


@dataclass
class Visibilidad:
    """Por qué alguien ve (o no) un registro.

    Los motivos van en lista porque suelen ser varios a la vez —es tuyo **y**
    además te lo compartieron—, y quien pregunta necesita verlos todos: quitar
    una compartición no cambia nada si además era el propietario.
    """

    puede_leer: bool = False
    puede_escribir: bool = False
    motivos: list[str] = field(default_factory=list)

    def a_dict(self) -> dict[str, Any]:
        return {
            "puede_leer": self.puede_leer,
            "puede_escribir": self.puede_escribir,
            "motivos": self.motivos,
        }


def visibilidad_de(
    db: Session,
    *,
    tenant_id: UUID,
    usuario_id: UUID,
    objeto: str,
    registro: dict[str, Any],
    subordinados: set[UUID] | None = None,
    equipos: set[UUID] | None = None,
) -> Visibilidad:
    """Calcula si un usuario ve un registro concreto, y por qué.

    `subordinados` y `equipos` se pasan ya resueltos: calcularlos aquí obligaría
    a este módulo a conocer la jerarquía de mando y los equipos de cuenta, que
    viven en otros sitios.
    """
    resultado = Visibilidad()

    owner = registro.get("owner_id")
    if owner and str(owner) == str(usuario_id):
        resultado.puede_leer = resultado.puede_escribir = True
        resultado.motivos.append("es su propietario")

    if owner and subordinados and UUID(str(owner)) in subordinados:
        resultado.puede_leer = resultado.puede_escribir = True
        resultado.motivos.append("es responsable de quien lo posee")

    registro_id = registro.get("id")
    if equipos and registro_id and UUID(str(registro_id)) in equipos:
        resultado.puede_leer = True
        resultado.motivos.append("está en el equipo de la cuenta")

    for regla in _reglas_aplicables(db, tenant_id, objeto):
        if not _destino_incluye(regla, usuario_id, registro):
            continue
        if not _cumple(regla, registro):
            continue
        resultado.puede_leer = True
        resultado.puede_escribir = resultado.puede_escribir or regla.acceso == "escritura"
        resultado.motivos.append(f"regla de compartición «{regla.nombre}»")

    manual = _comparticion_manual(db, tenant_id, usuario_id, objeto, registro_id)
    if manual is not None:
        resultado.puede_leer = True
        resultado.puede_escribir = resultado.puede_escribir or manual.acceso == "escritura"
        caduca = f" hasta {manual.hasta.isoformat()}" if manual.hasta else ""
        resultado.motivos.append(f"compartido a mano{caduca}")

    if not resultado.motivos:
        resultado.motivos.append("ninguna regla lo alcanza")
    return resultado


def _reglas_aplicables(db: Session, tenant_id: UUID, objeto: str) -> list[ReglaComparticion]:
    return list(
        db.execute(
            select(ReglaComparticion).where(
                ReglaComparticion.tenant_id == tenant_id,
                ReglaComparticion.objeto == objeto,
                ReglaComparticion.activa.is_(True),
            )
        )
        .scalars()
        .all()
    )


def _destino_incluye(regla: ReglaComparticion, usuario_id: UUID, registro: dict[str, Any]) -> bool:
    """Si la regla apunta a este usuario.

    Con `rol` y `unidad_negocio` hace falta saber los del usuario, y esos los
    aporta quien llama a través del registro (`_usuario`). Se resuelve así para
    no consultar la membresía en cada evaluación de cada regla de cada registro.
    """
    if regla.destino_tipo == "usuario":
        return regla.destino_id == str(usuario_id)
    usuario = registro.get("_usuario") or {}
    if regla.destino_tipo == "rol":
        return regla.destino_id in (usuario.get("roles") or [])
    if regla.destino_tipo == "unidad_negocio":
        return regla.destino_id == str(usuario.get("business_unit_id") or "")
    return False


def _cumple(regla: ReglaComparticion, registro: dict[str, Any]) -> bool:
    """Evalúa las condiciones con la gramática de ABAC.

    **La misma que usan las políticas de permisos y el enrutamiento de leads**,
    y eso es el punto: `{"atributo", "operador", "valor"}` con las rutas
    `registro.x` y `usuario.y`. Antes esto usaba el evaluador del orquestador,
    con la clave `op` en vez de `operador` y otro resolutor de rutas — así que
    el producto tenía dos gramáticas que se parecían lo justo para que una
    condición copiada de un sitio a otro no fallara: simplemente no encajaba
    nunca, y la regla dejaba de compartir sin decir nada.
    """
    from crmcore.authz.abac import Condicion

    ambito = {"registro": registro, "usuario": registro.get("_usuario") or {}}
    resultados: list[bool] = []
    for bruta in regla.condiciones or []:
        try:
            condicion = Condicion(
                atributo=bruta["atributo"],
                operador=bruta["operador"],
                valor=bruta.get("valor"),
            )
        except (KeyError, TypeError):
            # Una condición mal formada NO se ignora como si no existiera: eso
            # convertiría una regla específica en un comodín que comparte de
            # más. Se cuenta como no cumplida.
            logger.warning(
                "comparticion.condicion_mal_formada", regla=regla.nombre, condicion=str(bruta)[:200]
            )
            resultados.append(False)
            continue
        resultados.append(condicion.evaluar(ambito))
    if not resultados:
        # Una regla sin condiciones comparte TODO el objeto. Es legítimo
        # («todas las cuentas con el equipo de dirección») y por eso se permite,
        # pero se anota: es la forma más fácil de abrir de más sin darse cuenta.
        logger.info("comparticion.regla_sin_condiciones", regla=regla.nombre)
        return True
    return all(resultados) if regla.combinacion == "todas" else any(resultados)


def _comparticion_manual(
    db: Session, tenant_id: UUID, usuario_id: UUID, objeto: str, registro_id: Any
) -> ComparticionManual | None:
    if not registro_id:
        return None
    from sqlalchemy import or_

    return db.execute(
        select(ComparticionManual).where(
            ComparticionManual.tenant_id == tenant_id,
            ComparticionManual.usuario_id == usuario_id,
            ComparticionManual.objeto == objeto,
            ComparticionManual.registro_id == UUID(str(registro_id)),
            ComparticionManual.revocada_at.is_(None),
            or_(ComparticionManual.hasta.is_(None), ComparticionManual.hasta >= date.today()),
        )
    ).scalar_one_or_none()


def compartir(
    db: Session,
    *,
    tenant_id: UUID,
    objeto: str,
    registro_id: UUID,
    usuario_id: UUID,
    acceso: str = "lectura",
    hasta: date | None = None,
    motivo: str = "",
    por: UUID | None = None,
) -> ComparticionManual:
    """Comparte un registro con alguien, opcionalmente con caducidad."""
    from crmcore.audit.chain import registrar

    existente = db.execute(
        select(ComparticionManual).where(
            ComparticionManual.tenant_id == tenant_id,
            ComparticionManual.objeto == objeto,
            ComparticionManual.registro_id == registro_id,
            ComparticionManual.usuario_id == usuario_id,
            ComparticionManual.revocada_at.is_(None),
        )
    ).scalar_one_or_none()
    if existente is not None:
        existente.acceso = acceso
        existente.hasta = hasta
        existente.motivo = motivo or existente.motivo
        return existente

    comparticion = ComparticionManual(
        tenant_id=tenant_id,
        objeto=objeto,
        registro_id=registro_id,
        usuario_id=usuario_id,
        acceso=acceso,
        hasta=hasta,
        motivo=motivo or None,
        compartido_por=por,
    )
    db.add(comparticion)
    registrar(
        db,
        accion="registro.compartido",
        objeto=objeto,
        objeto_id=registro_id,
        datos={
            "con": str(usuario_id),
            "acceso": acceso,
            "hasta": hasta.isoformat() if hasta else None,
        },
        tenant_id=tenant_id,
    )
    return comparticion


def revocar(db: Session, comparticion_id: UUID, *, por: UUID | None = None) -> None:
    from crmcore.audit.chain import registrar
    from crmcore.errors import NoEncontrado

    comparticion = db.get(ComparticionManual, comparticion_id)
    if comparticion is None:
        raise NoEncontrado("Esa compartición no existe", error_code="comparticion.no_encontrada")
    comparticion.revocada_at = func.now()
    registrar(
        db,
        accion="registro.comparticion_revocada",
        objeto=comparticion.objeto,
        objeto_id=comparticion.registro_id,
        datos={"con": str(comparticion.usuario_id)},
        tenant_id=comparticion.tenant_id,
    )
