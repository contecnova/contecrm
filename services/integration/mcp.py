"""Exposición a agentes de IA por MCP o equivalente (CRM-00.03.04.11).

Un agente que puede leer y escribir en el CRM es útil y es peligroso por lo
mismo: hace en un segundo lo que una persona tardaría una tarde. Las tres
decisiones de este módulo salen de ahí.

**El agente tiene su propio principal, no el del usuario.** Actuar «en nombre de»
heredando permisos convierte cualquier fallo del agente en un fallo con los
permisos del jefe. Aquí una exposición declara **qué herramientas** publica y con
qué permisos, y el catálogo de herramientas que ve cada agente es el resultado de
cruzar lo declarado con lo que su principal puede.

**Lo que escribe pasa por el mismo sitio que lo que escribe una persona.** Las
herramientas de escritura emiten **comandos** al servicio dueño del objeto; no hay
una puerta trasera que se salte las reglas de negocio. Sin eso, un agente podría
cerrar una oportunidad sin motivo de pérdida y el CRM tendría dos verdades sobre
qué se puede hacer.

**Todo lo que hace un agente queda contado.** Cuántas llamadas, a qué, con qué
resultado y con qué coste declarado. Un agente sin cuota es una factura sorpresa,
y un agente sin traza es una auditoría imposible el día que alguien pregunte por
qué cambió un dato.

El protocolo se llama MCP porque es el que hay. Lo que se guarda aquí —una
herramienta con su esquema, sus permisos y su traza— no depende de él: si mañana
el estándar es otro, cambia el envoltorio y no el modelo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado, Prohibido
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
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

# Qué hace una herramienta. La distinción no es decorativa: lo que solo lee se
# puede conceder con menos miedo, y lo que escribe pasa por comando.
TIPOS = ("lectura", "escritura")


class Exposicion(Base, TimestampMixin, SoftDeleteMixin):
    """Un conjunto de herramientas publicado a agentes (CRM-00.03.04.11)."""

    __tablename__ = "exposiciones_mcp"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Tope de llamadas por hora. Un agente sin cuota es una factura sorpresa y,
    # con una API de pago detrás, la de otro.
    cuota_hora: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    # Interruptor de emergencia (CRM-05.02.03.04): apagarlo corta todo lo de este
    # conjunto sin tocar permisos ni borrar nada.
    detenida: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    motivo_detencion: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (UniqueConstraint("tenant_id", "clave", name="uq_exposicion_mcp"),)


class Herramienta(Base, TimestampMixin):
    """Una operación que un agente puede invocar."""

    __tablename__ = "herramientas_mcp"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    exposicion_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("exposiciones_mcp.id", ondelete="CASCADE"), nullable=False
    )
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    # Lo que el agente lee para decidir si la usa. Una descripción mala hace que
    # el agente llame a la herramienta equivocada, y eso se parece mucho a un
    # fallo del modelo cuando en realidad es un fallo de documentación.
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tipo: Mapped[str] = mapped_column(
        String(20), nullable=False, default="lectura", info={"opciones": TIPOS}
    )
    # Qué permiso hace falta. Se comprueba contra el principal del agente, no
    # contra el de quien lo invocó.
    permiso: Mapped[str] = mapped_column(String(80), nullable=False)
    # Esquema de parámetros, en JSON Schema. Validarlo aquí evita que un agente
    # mande cualquier cosa al servicio dueño.
    parametros: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # A qué se traduce: ruta de lectura, o comando de escritura {objeto, accion}.
    destino: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Escritura que requiere que una persona confirme antes de ejecutarse. Es lo
    # que permite dar herramientas de escritura sin jugársela: el agente prepara
    # y alguien firma.
    exige_confirmacion: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "exposicion_id", "nombre", name="uq_herramienta_mcp"),
        Index("ix_herramientas_mcp", "tenant_id", "exposicion_id", "activa"),
    )


class LlamadaAgente(Base):
    """Cada invocación, con su resultado y su coste."""

    __tablename__ = "llamadas_agente"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    exposicion_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    herramienta: Mapped[str] = mapped_column(String(80), nullable=False)
    agente_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # ejecutada | rechazada | pendiente_confirmacion | error
    resultado: Mapped[str] = mapped_column(String(30), nullable=False, default="ejecutada")
    porque: Mapped[str] = mapped_column(Text, nullable=False, default="")
    argumentos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    duracion_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_llamadas_agente", "tenant_id", "exposicion_id", "created_at"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def crear_exposicion(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    nombre: str = "",
    descripcion: str = "",
    cuota_hora: int = 1000,
) -> Exposicion:
    """Crea un conjunto de herramientas."""
    fila = Exposicion(
        tenant_id=uow.tenant_id,
        clave=clave.strip(),
        nombre=nombre.strip() or clave.strip(),
        descripcion=descripcion,
        cuota_hora=max(1, int(cuota_hora)),
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def publicar_herramienta(
    uow: UnidadDeTrabajo,
    exposicion_id: UUID,
    *,
    nombre: str,
    permiso: str,
    descripcion: str = "",
    tipo: str = "lectura",
    parametros: dict[str, Any] | None = None,
    destino: dict[str, Any] | None = None,
    exige_confirmacion: bool = False,
) -> tuple[Herramienta, list[str]]:
    """Publica una herramienta.

    Una de **escritura** tiene que declarar a qué comando se traduce: sin eso, la
    única forma de ejecutarla sería escribir directamente, y entonces el agente se
    saltaría las reglas que aplica el servicio dueño a todo el mundo.
    """
    if tipo not in TIPOS:
        raise ErrorValidacion(
            f"Tipo «{tipo}» no válido.",
            error_code="mcp.tipo_no_valido",
            detalle={"validos": list(TIPOS)},
        )
    if not permiso.strip():
        raise ErrorValidacion(
            "Una herramienta sin permiso declarado sería accesible para cualquier " "agente.",
            error_code="mcp.sin_permiso",
        )
    destino = dict(destino or {})
    if tipo == "escritura" and not (destino.get("objeto") and destino.get("accion")):
        raise ErrorValidacion(
            "Una herramienta de escritura se traduce a un comando: hace falta "
            "`objeto` y `accion`. Escribir directamente saltaría las reglas del "
            "servicio dueño.",
            error_code="mcp.destino_incompleto",
        )

    avisos: list[str] = []
    if not descripcion.strip():
        avisos.append(
            "Sin descripción: el agente decide por ella, y una mala hace que llame "
            "a la herramienta equivocada. Parecerá un fallo del modelo."
        )
    if tipo == "escritura" and not exige_confirmacion:
        avisos.append(
            "Herramienta de escritura sin confirmación humana: el agente podrá "
            "ejecutarla sola. Es legítimo, pero conviene que sea una decisión."
        )

    fila = Herramienta(
        tenant_id=uow.tenant_id,
        exposicion_id=exposicion_id,
        nombre=nombre.strip(),
        descripcion=descripcion.strip(),
        tipo=tipo,
        permiso=permiso.strip(),
        parametros=dict(parametros or {}),
        destino=destino,
        exige_confirmacion=exige_confirmacion,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila, avisos


def catalogo_para(
    db: Session, tenant_id: UUID, *, exposicion: str, principal: Any
) -> dict[str, Any]:
    """Las herramientas que **ese** agente puede ver.

    Se filtra por sus permisos antes de enseñarlas. Publicar el catálogo entero y
    fallar al invocar le haría gastar llamadas —y dinero— en cosas que no puede
    hacer, y peor: intentar rodearlas.
    """
    ficha = db.execute(
        select(Exposicion).where(Exposicion.tenant_id == tenant_id, Exposicion.clave == exposicion)
    ).scalar_one_or_none()
    if ficha is None:
        raise NoEncontrado("Esa exposición no existe", error_code="mcp.exposicion_no_encontrada")
    if ficha.detenida or not ficha.activa:
        return {
            "exposicion": exposicion,
            "herramientas": [],
            "detenida": ficha.detenida,
            "porque": ficha.motivo_detencion or "La exposición está desactivada.",
        }

    filas = (
        db.execute(
            select(Herramienta).where(
                Herramienta.tenant_id == tenant_id,
                Herramienta.exposicion_id == ficha.id,
                Herramienta.activa.is_(True),
            )
        )
        .scalars()
        .all()
    )
    visibles = [h for h in filas if _puede(principal, h.permiso)]
    return {
        "exposicion": exposicion,
        "herramientas": [
            {
                "nombre": h.nombre,
                "descripcion": h.descripcion,
                "tipo": h.tipo,
                "parametros": h.parametros,
                "exige_confirmacion": h.exige_confirmacion,
            }
            for h in visibles
        ],
        # Cuántas se le ocultan por permisos: es lo que explica por qué dos
        # agentes ven catálogos distintos, en vez de parecer un error.
        "ocultas_por_permisos": len(filas) - len(visibles),
        "detenida": False,
    }


def _puede(principal: Any, permiso: str) -> bool:
    tiene = getattr(principal, "tiene", None)
    return bool(tiene(permiso)) if callable(tiene) else False


def invocar(
    uow: UnidadDeTrabajo,
    *,
    exposicion: str,
    herramienta: str,
    argumentos: dict[str, Any] | None = None,
    principal: Any = None,
    agente_id: UUID | None = None,
) -> dict[str, Any]:
    """Ejecuta una herramienta en nombre de un agente.

    El orden de las comprobaciones importa y es este: **interruptor, permiso,
    cuota, parámetros**. El interruptor primero porque tiene que cortar aunque
    todo lo demás esté bien; y la cuota antes de validar los parámetros porque un
    agente en bucle manda miles de llamadas y validar cada una cuesta más que
    rechazarla.

    Una herramienta de escritura **no escribe aquí**: emite el comando al servicio
    dueño, que aplica sus reglas. Y si exige confirmación, ni eso: se deja
    preparada y alguien la firma.
    """
    inicio = _ahora()
    ficha = uow.db.execute(
        select(Exposicion).where(
            Exposicion.tenant_id == uow.tenant_id, Exposicion.clave == exposicion
        )
    ).scalar_one_or_none()
    if ficha is None:
        raise NoEncontrado("Esa exposición no existe", error_code="mcp.exposicion_no_encontrada")

    def _anotar(resultado: str, porque: str = "") -> None:
        uow.db.add(
            LlamadaAgente(
                tenant_id=uow.tenant_id,
                exposicion_id=ficha.id,
                herramienta=herramienta,
                agente_id=agente_id,
                resultado=resultado,
                porque=porque,
                argumentos=dict(argumentos or {}),
                duracion_ms=int((_ahora() - inicio).total_seconds() * 1000),
            )
        )
        uow.db.flush()

    if ficha.detenida or not ficha.activa:
        _anotar("rechazada", ficha.motivo_detencion or "exposición desactivada")
        raise Prohibido(
            "Esta exposición está detenida: " + (ficha.motivo_detencion or "desactivada"),
            error_code="mcp.detenida",
        )

    fila = uow.db.execute(
        select(Herramienta).where(
            Herramienta.tenant_id == uow.tenant_id,
            Herramienta.exposicion_id == ficha.id,
            Herramienta.nombre == herramienta,
            Herramienta.activa.is_(True),
        )
    ).scalar_one_or_none()
    if fila is None:
        _anotar("rechazada", "herramienta desconocida")
        raise NoEncontrado("Esa herramienta no existe", error_code="mcp.herramienta_no_encontrada")

    if not _puede(principal, fila.permiso):
        _anotar("rechazada", f"le falta el permiso {fila.permiso}")
        raise Prohibido(
            "El agente no tiene permiso para esa herramienta",
            error_code="mcp.permiso_ausente",
            detalle={"permiso_requerido": fila.permiso},
        )

    desde = _ahora() - timedelta(hours=1)
    usadas = (
        uow.db.execute(
            select(func.count())
            .select_from(LlamadaAgente)
            .where(
                LlamadaAgente.tenant_id == uow.tenant_id,
                LlamadaAgente.exposicion_id == ficha.id,
                LlamadaAgente.created_at >= desde,
                LlamadaAgente.resultado == "ejecutada",
            )
        )
    ).scalar_one()
    if int(usadas) >= ficha.cuota_hora:
        _anotar("rechazada", f"cuota agotada ({ficha.cuota_hora}/h)")
        raise Conflicto(
            "Cuota de llamadas agotada para esta hora",
            error_code="mcp.cuota_agotada",
            detalle={"cuota_hora": ficha.cuota_hora, "usadas": int(usadas)},
        )

    faltan = [
        campo
        for campo in (fila.parametros or {}).get("required", [])
        if campo not in (argumentos or {})
    ]
    if faltan:
        _anotar("rechazada", f"faltan parámetros: {', '.join(faltan)}")
        raise ErrorValidacion(
            f"Faltan parámetros obligatorios: {', '.join(faltan)}.",
            error_code="mcp.parametros_incompletos",
            detalle={"faltan": faltan},
        )

    if fila.tipo == "escritura":
        if fila.exige_confirmacion:
            _anotar("pendiente_confirmacion", "espera confirmación de una persona")
            return {
                "estado": "pendiente_confirmacion",
                "herramienta": herramienta,
                "porque": (
                    "Esta herramienta escribe y exige que una persona lo confirme. "
                    "Queda preparada, no ejecutada."
                ),
            }
        from crmcore.bus.comandos import Comando
        from crmcore.bus.comandos import emitir as emitir_comando

        emitir_comando(
            uow,
            Comando(
                accion=str(fila.destino.get("accion")),
                objeto=str(fila.destino.get("objeto")),
                tenant_id=uow.tenant_id,
                registro_id=(
                    UUID(str(argumentos["registro_id"]))
                    if (argumentos or {}).get("registro_id")
                    else None
                ),
                datos=dict(argumentos or {}),
                origen="agente",
                origen_id=str(agente_id) if agente_id else None,
            ),
        )
        _anotar("ejecutada", "comando emitido al servicio dueño")
        return {
            "estado": "pedido",
            "herramienta": herramienta,
            # Se dice «pedido» y no «hecho»: lo ejecuta el servicio dueño, que
            # puede rechazarlo por sus propias reglas.
            "porque": "Se ha pedido al servicio dueño; sus reglas deciden si se aplica.",
        }

    _anotar("ejecutada", "lectura")
    return {
        "estado": "ejecutada",
        "herramienta": herramienta,
        "destino": fila.destino,
        "porque": "",
    }


def detener(uow: UnidadDeTrabajo, *, exposicion: str, motivo: str) -> Exposicion:
    """Corta en seco todo lo de esta exposición (kill switch).

    Sin borrar nada y sin tocar permisos: lo que se quiere el día que un agente se
    porta mal es **parar ahora** y decidir después, no ponerse a revocar roles
    mientras sigue llamando.
    """
    if not motivo.strip():
        raise ErrorValidacion(
            "Detener una exposición exige motivo: alguien preguntará por qué dejó " "de funcionar.",
            error_code="mcp.motivo_obligatorio",
        )
    fila = uow.db.execute(
        select(Exposicion).where(
            Exposicion.tenant_id == uow.tenant_id, Exposicion.clave == exposicion
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("Esa exposición no existe", error_code="mcp.exposicion_no_encontrada")
    fila.detenida = True
    fila.motivo_detencion = motivo.strip()
    uow.db.flush()
    return fila


def uso(db: Session, tenant_id: UUID, *, horas: int = 24) -> dict[str, Any]:
    """Qué han hecho los agentes, y qué se les ha rechazado.

    Los rechazos importan tanto como las ejecuciones: muchos por permisos
    significa que el catálogo publicado y lo que el agente puede hacer no
    coinciden, y eso se arregla configurando, no reintentando.
    """
    desde = _ahora() - timedelta(hours=horas)
    filas = (
        db.execute(
            select(LlamadaAgente).where(
                LlamadaAgente.tenant_id == tenant_id, LlamadaAgente.created_at >= desde
            )
        )
        .scalars()
        .all()
    )
    por_herramienta: dict[str, dict[str, int]] = {}
    for fila in filas:
        cuenta = por_herramienta.setdefault(fila.herramienta, {})
        cuenta[fila.resultado] = cuenta.get(fila.resultado, 0) + 1
    return {
        "ventana_horas": horas,
        "llamadas": len(filas),
        "ejecutadas": len([f for f in filas if f.resultado == "ejecutada"]),
        "rechazadas": len([f for f in filas if f.resultado == "rechazada"]),
        "pendientes_confirmacion": len(
            [f for f in filas if f.resultado == "pendiente_confirmacion"]
        ),
        "por_herramienta": por_herramienta,
        "medible": bool(filas),
    }
