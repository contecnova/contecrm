"""Trazabilidad de todo lo que hace la IA (CRM-05.02.02.08).

Cuando alguien pregunte «¿por qué el CRM escribió esto?» —y lo va a preguntar, a
veces con un abogado delante— la respuesta tiene que existir. Eso significa
guardar **qué se pidió, con qué modelo, con qué contexto, quién lo pidió y sobre
qué registro**.

Tres decisiones, y las tres cuestan algo:

**El prompt se guarda, pero el contexto solo por referencia.** Guardar el texto
completo que se mandó duplicaría dentro del registro de auditoría todos los datos
personales del CRM, y encima sin las reglas de retención de su tabla de origen. Se
guarda la **huella** del prompt y la lista de fuentes: con eso se puede reproducir
sin duplicar.

**El coste va por llamada, no por mes.** Una factura mensual no dice quién gastó;
por llamada se puede responder «esto costó 4 céntimos y lo pidió el equipo de
soporte para resumir casos», que es lo que pregunta quien firma la factura.

**Lo que salió mal también se guarda.** Un módulo que solo apunta los aciertos da
una tasa de éxito del 100 %. Los rechazos por guardarraíl, los tiempos de espera y
las respuestas que el usuario descartó son los tres números con los que se decide
si esto sirve.

Y una cosa que **no** se guarda: la respuesta completa del modelo cuando el
usuario no la acepta. Si se descartó, conservarla es guardar un texto sobre un
cliente que nadie ha validado, y esos textos acaban leyéndose como si fueran datos.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.db.base import Base
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# En qué acabó una llamada.
#
#   pendiente      se generó y **nadie la ha juzgado todavía**
#   aceptada       una persona la usó
#   descartada     una persona la vio y la tiró
#   error          el proveedor falló
#   bloqueada      la paró un guardarraíl
#   sin_respuesta  el modelo no devolvió nada útil
#
# `pendiente` existe porque marcar como aceptada una llamada que nadie ha mirado
# inflaría la tasa de descarte hasta dejarla sin significado — que es justo el
# número por el que se decide si esto sirve.
RESULTADOS = (
    "pendiente",
    "aceptada",
    "descartada",
    "error",
    "bloqueada",
    "sin_respuesta",
)


class LlamadaIA(Base):
    """Una petición a un modelo, con todo lo que hace falta para explicarla."""

    __tablename__ = "llamadas_ia"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    tarea: Mapped[str] = mapped_column(String(60), nullable=False)
    proveedor: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    modelo: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    region: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    usuario_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # Sobre qué registro del CRM se pidió. Es lo que permite contestar «¿por qué
    # el CRM escribió esto en mi ficha?».
    objeto: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    objeto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    # Huella del prompt y de la plantilla usada. Con la plantilla versionada y la
    # huella se puede reproducir sin guardar el texto, que llevaría dentro datos
    # personales sin la retención de su tabla de origen.
    plantilla: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    version_plantilla: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    huella_prompt: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # De dónde salió el contexto: [{fuente, id}]. Por referencia, no copiado.
    fuentes: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    tokens_entrada: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_salida: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coste: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    duracion_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resultado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Si el tenant exigía opt-out y si el proveedor lo garantizaba en ESA llamada.
    # Guardarlo por llamada y no por configuración es lo que permite demostrarlo
    # cuando la configuración haya cambiado tres veces.
    opt_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_llamadas_ia", "tenant_id", "created_at"),
        Index("ix_llamadas_ia_objeto", "tenant_id", "objeto", "objeto_id"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def huella(texto: str) -> str:
    return hashlib.sha256(texto.encode()).hexdigest()


def anotar(
    uow: UnidadDeTrabajo,
    *,
    tarea: str,
    proveedor: str = "",
    modelo: str = "",
    region: str = "",
    usuario_id: UUID | None = None,
    objeto: str = "",
    objeto_id: UUID | None = None,
    plantilla: str = "",
    version_plantilla: int = 0,
    prompt: str = "",
    fuentes: list[dict[str, Any]] | None = None,
    tokens_entrada: int = 0,
    tokens_salida: int = 0,
    coste: Decimal | None = None,
    duracion_ms: int = 0,
    resultado: str = "pendiente",
    error: str = "",
    opt_out: bool = False,
) -> LlamadaIA:
    """Registra una llamada. Se llama **siempre**, también cuando falla."""
    fila = LlamadaIA(
        tenant_id=uow.tenant_id,
        tarea=tarea,
        proveedor=proveedor,
        modelo=modelo,
        region=region,
        usuario_id=usuario_id,
        objeto=objeto,
        objeto_id=objeto_id,
        plantilla=plantilla,
        version_plantilla=version_plantilla,
        huella_prompt=huella(prompt) if prompt else "",
        fuentes=list(fuentes or []),
        tokens_entrada=max(0, int(tokens_entrada)),
        tokens_salida=max(0, int(tokens_salida)),
        coste=Decimal(coste or 0),
        duracion_ms=max(0, int(duracion_ms)),
        resultado=resultado if resultado in RESULTADOS else "error",
        error=error or None,
        opt_out=opt_out,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def marcar_resultado(uow: UnidadDeTrabajo, llamada_id: UUID, *, resultado: str) -> LlamadaIA | None:
    """Anota si la persona usó lo generado o lo tiró.

    Es el número que decide si esto sirve, y el que casi nadie mide: una
    funcionalidad de IA con el 70 % de respuestas descartadas está costando dinero
    y tiempo, aunque «funcione».
    """
    fila = uow.db.get(LlamadaIA, llamada_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        return None
    if resultado in RESULTADOS:
        fila.resultado = resultado
        uow.db.flush()
    return fila


def consumo(
    db: Session, tenant_id: UUID, *, dias: int = 30, ahora: datetime | None = None
) -> dict[str, Any]:
    """Qué se ha gastado, en qué y con qué provecho.

    Las tres cifras que importan van juntas: **coste, tasa de descarte y
    bloqueos**. Enseñar solo el coste hace que se discuta el precio de algo cuyo
    valor nadie ha medido.
    """
    momento = ahora or _ahora()
    desde = momento - timedelta(days=dias)
    filas = (
        db.execute(
            select(LlamadaIA).where(LlamadaIA.tenant_id == tenant_id, LlamadaIA.created_at >= desde)
        )
        .scalars()
        .all()
    )
    por_tarea: dict[str, dict[str, Any]] = {}
    for fila in filas:
        entrada = por_tarea.setdefault(
            fila.tarea, {"llamadas": 0, "coste": Decimal(0), "descartadas": 0}
        )
        entrada["llamadas"] += 1
        entrada["coste"] += Decimal(fila.coste)
        if fila.resultado == "descartada":
            entrada["descartadas"] += 1

    aceptadas = len([f for f in filas if f.resultado == "aceptada"])
    descartadas = len([f for f in filas if f.resultado == "descartada"])
    juzgadas = aceptadas + descartadas
    return {
        "dias": dias,
        "llamadas": len(filas),
        "coste": str(sum((Decimal(f.coste) for f in filas), Decimal(0))),
        "tokens_entrada": sum(f.tokens_entrada for f in filas),
        "tokens_salida": sum(f.tokens_salida for f in filas),
        "por_tarea": {k: {**v, "coste": str(v["coste"])} for k, v in sorted(por_tarea.items())},
        "errores": len([f for f in filas if f.resultado == "error"]),
        "bloqueadas": len([f for f in filas if f.resultado == "bloqueada"]),
        # La tasa de descarte solo sobre lo que alguien juzgó: contar como
        # aceptadas las que nadie miró inflaría el dato hasta no significar nada.
        "tasa_descarte": (round(100 * descartadas / juzgadas, 1) if juzgadas else None),
        "medible": bool(juzgadas),
        "aviso": (
            ""
            if juzgadas
            else "Nadie ha marcado si usó lo generado: se sabe lo que cuesta y no lo " "que vale."
        ),
        "sin_opt_out": len([f for f in filas if not f.opt_out]),
    }


def historial_de(db: Session, tenant_id: UUID, *, objeto: str, objeto_id: UUID) -> dict[str, Any]:
    """Qué ha hecho la IA sobre este registro.

    Es la respuesta a «¿por qué el CRM escribió esto en mi ficha?»: qué tarea, con
    qué modelo, cuándo, quién lo pidió y de qué fuentes salió.
    """
    filas = (
        db.execute(
            select(LlamadaIA)
            .where(
                LlamadaIA.tenant_id == tenant_id,
                LlamadaIA.objeto == objeto,
                LlamadaIA.objeto_id == objeto_id,
            )
            .order_by(LlamadaIA.created_at.desc())
            .limit(100)
        )
        .scalars()
        .all()
    )
    return {
        "objeto": objeto,
        "objeto_id": str(objeto_id),
        "llamadas": [
            {
                "id": str(f.id),
                "tarea": f.tarea,
                "modelo": f.modelo,
                "proveedor": f.proveedor,
                "region": f.region,
                "cuando": f.created_at.isoformat(),
                "usuario_id": str(f.usuario_id) if f.usuario_id else None,
                "fuentes": f.fuentes,
                "resultado": f.resultado,
                "plantilla": f"{f.plantilla} v{f.version_plantilla}" if f.plantilla else "",
                "coste": str(f.coste),
                "opt_out": f.opt_out,
            }
            for f in filas
        ],
        "cuantas": len(filas),
    }


def por_dia(db: Session, tenant_id: UUID, *, dias: int = 30) -> list[dict[str, Any]]:
    """Coste diario, para poder ver una subida antes de la factura."""
    desde = (_ahora() - timedelta(days=dias)).date()
    filas = db.execute(
        select(
            func.date(LlamadaIA.created_at).label("dia"),
            func.count().label("llamadas"),
            func.coalesce(func.sum(LlamadaIA.coste), 0).label("coste"),
        )
        .where(LlamadaIA.tenant_id == tenant_id, func.date(LlamadaIA.created_at) >= desde)
        .group_by(func.date(LlamadaIA.created_at))
        .order_by(func.date(LlamadaIA.created_at))
    ).all()
    return [
        {"dia": str(f.dia), "llamadas": int(f.llamadas), "coste": str(Decimal(f.coste))}
        for f in filas
    ]


def _fecha_hoy() -> date:
    return _ahora().date()
