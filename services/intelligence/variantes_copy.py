"""Variantes de copy generadas por el modelo, con revisión humana
(CRM-02.04.01.04).

**Lo que había, medido el 09-11-2026.** `POST /variantes` recibía los textos
ya escritos por quien llamaba y los devolvía marcados: no generaba nada, no
guardaba nada y la aprobación no quedaba en ningún sitio.

Ahora se generan con el modelo de la casa a partir de un texto base y un
objetivo, se **guardan como propuesta** colgadas de lo que se está escribiendo
(una plantilla de correo, un contenido), y una persona aprueba —puede
reescribir—, rechaza y elige la ganadora. Las reglas de siempre siguen en
`variantes`: las afirmaciones comprobables se marcan y no hay aprobación sin
leer.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, CrmError, ErrorDependencia, ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import Boolean, DateTime, Index, String, Text, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from services.intelligence import variantes as var

logger = get_logger(__name__)

_MARCADOR = re.compile(r"\{\{\s*[\w.]+\s*\}\}")

ESTADOS = ("propuesta", "aprobada", "rechazada")
CANALES = ("email", "asunto", "sms", "push", "anuncio", "web", "redes")


class VarianteCopy(Base, TimestampMixin):
    """Una variante propuesta por el modelo y lo que una persona hizo con ella."""

    __tablename__ = "variantes_copy"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # Las que salieron de la misma petición.
    lote_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # De qué se está escribiendo: `plantilla_correo` + su clave, por ejemplo.
    objeto: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    objeto_ref: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    canal: Mapped[str] = mapped_column(
        String(20), nullable=False, default="email", info={"opciones": CANALES}
    )
    base: Mapped[str] = mapped_column(Text, nullable=False, default="")
    objetivo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    texto_propuesto: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Lo que quedó tras revisarla. Con el par se sabe si el modelo ayuda.
    texto_final: Mapped[str | None] = mapped_column(Text, nullable=True)
    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, default="propuesta", info={"opciones": ESTADOS}
    )
    ganadora: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    afirmaciones: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    motivo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    modelo: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    creada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    decidida_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    decidida_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_variantes_copy_objeto", "tenant_id", "objeto", "objeto_ref"),
        Index("ix_variantes_copy_lote", "tenant_id", "lote_id"),
    )


_redactor: Callable[..., dict[str, Any]] | None = None


def registrar_redactor(fn: Callable[..., dict[str, Any]] | None) -> None:
    global _redactor
    _redactor = fn


def _maximas(db: Any) -> int:
    from crmcore.runtime import settings as rt

    from services.intelligence.ajustes import ajustes

    valor = rt.efectivo("ia_variantes_maximas", db)
    return int(ajustes().ia_variantes_maximas if valor is None else valor)


def _marcadores_perdidos(base: str, texto: str) -> list[dict[str, str]]:
    """Los `{{marcador}}` de la base que la variante ha perdido.

    Medido el 09-11-2026 con el modelo de verdad: de «Incidencia en tu pedido
    {{pedido.referencia}}» salieron tres variantes sin la referencia. Un asunto
    sin el dato que lo hace útil se aprueba leyendo deprisa; marcado, no.
    """
    perdidos = [m for m in dict.fromkeys(_MARCADOR.findall(base)) if m not in texto]
    return [{"texto": m, "es": "un marcador que falta"} for m in perdidos]


def generar(
    uow: UnidadDeTrabajo,
    *,
    principal: Any,
    base: str,
    objetivo: str,
    canal: str = "email",
    cuantas: int = 3,
    objeto: str = "",
    objeto_ref: str = "",
    idioma: str = "es",
) -> dict[str, Any]:
    """Pide N variantes al modelo y las guarda como propuestas."""
    from services.intelligence import enrutador, uso

    if not base.strip():
        raise ErrorValidacion("Falta el texto base.", error_code="variantes.sin_base")
    if canal not in CANALES:
        raise ErrorValidacion(
            f"Canal «{canal}» no reconocido.",
            error_code="variantes.canal",
            detalle={"admitidos": list(CANALES)},
        )
    tope = _maximas(uow.db)
    if cuantas < 1 or cuantas > tope:
        raise ErrorValidacion(
            f"Se pueden pedir entre 1 y {tope} variantes.",
            error_code="variantes.cuantas",
            detalle={"maximo": tope},
        )
    if _redactor is None:
        raise ErrorDependencia("No hay puerto de IA conectado.", error_code="variantes.sin_puerto")
    elegido = enrutador.exigir_disponible(uow.db, uow.tenant_id, uso="redaccion")
    inicio = datetime.now(timezone.utc)
    lote = nuevo_id()
    try:
        salida = _redactor(
            proveedor=elegido["elegido"],
            modelo=elegido.get("modelo", ""),
            base=base,
            objetivo=objetivo,
            canal=canal,
            cuantas=cuantas,
            idioma=idioma,
            opt_out=bool(elegido.get("opt_out")),
        )
    except CrmError as exc:
        uso.anotar(
            uow,
            tarea="variantes",
            proveedor=str(elegido.get("elegido") or ""),
            modelo=str(elegido.get("modelo") or ""),
            objeto="variantes",
            objeto_id=lote,
            resultado="error",
            error=str(exc)[:200],
            opt_out=bool(elegido.get("opt_out")),
        )
        raise
    uso.anotar(
        uow,
        tarea="variantes",
        proveedor=str(elegido.get("elegido") or ""),
        modelo=str(salida.get("modelo") or elegido.get("modelo") or ""),
        region=str(elegido.get("region") or ""),
        usuario_id=getattr(principal, "id", None),
        objeto="variantes",
        objeto_id=lote,
        prompt=base,
        tokens_entrada=int(salida.get("tokens_entrada") or 0),
        tokens_salida=int(salida.get("tokens_salida") or 0),
        coste=enrutador.coste_estimado(
            uow.db,
            proveedor=str(elegido.get("elegido") or ""),
            tokens_entrada=int(salida.get("tokens_entrada") or 0),
            tokens_salida=int(salida.get("tokens_salida") or 0),
        ),
        duracion_ms=int((datetime.now(timezone.utc) - inicio).total_seconds() * 1000),
        resultado="pendiente",
        opt_out=bool(elegido.get("opt_out")),
    )
    textos = [str(t).strip() for t in salida.get("variantes") or [] if str(t).strip()]
    # Ni repetidas ni la base copiada: presentar cinco opciones de las que dos
    # son la misma hace perder el tiempo de quien revisa.
    vistos = {base.strip().lower()}
    unicos: list[str] = []
    for t in textos:
        if t.lower() not in vistos:
            vistos.add(t.lower())
            unicos.append(t)
    unicos = unicos[:cuantas]
    if not unicos:
        raise ErrorDependencia(
            "El modelo no ha devuelto ninguna variante distinta de la base.",
            error_code="variantes.vacias",
        )
    filas = []
    for t in unicos:
        fila = VarianteCopy(
            tenant_id=uow.tenant_id,
            lote_id=lote,
            objeto=objeto[:60],
            objeto_ref=objeto_ref[:200],
            canal=canal,
            base=base,
            objetivo=objetivo,
            texto_propuesto=t,
            afirmaciones=var.marcar_afirmaciones(t)["afirmaciones"] + _marcadores_perdidos(base, t),
            modelo=str(salida.get("modelo") or elegido.get("modelo") or "")[:120],
            creada_por=getattr(principal, "id", None),
        )
        uow.db.add(fila)
        filas.append(fila)
    uow.db.flush()
    return {
        "lote_id": str(lote),
        "variantes": [a_dict(f) for f in filas],
        "pedidas": cuantas,
        "aviso": (
            ""
            if len(unicos) == cuantas
            else f"Se pidieron {cuantas} y el modelo ha dado {len(unicos)} distintas."
        ),
        "ninguna_sale_sin_aprobar": True,
    }


def a_dict(fila: VarianteCopy) -> dict[str, Any]:
    return {
        "id": str(fila.id),
        "lote_id": str(fila.lote_id),
        "objeto": fila.objeto,
        "objeto_ref": fila.objeto_ref,
        "canal": fila.canal,
        "base": fila.base,
        "objetivo": fila.objetivo,
        "texto_propuesto": fila.texto_propuesto,
        "texto_final": fila.texto_final,
        "estado": fila.estado,
        "ganadora": fila.ganadora,
        "afirmaciones": list(fila.afirmaciones or []),
        "hubo_reescritura": bool(fila.texto_final)
        and (fila.texto_final or "").strip() != fila.texto_propuesto.strip(),
        "motivo": fila.motivo,
        "modelo": fila.modelo,
        "decidida_por": str(fila.decidida_por) if fila.decidida_por else None,
        "decidida_at": fila.decidida_at.isoformat() if fila.decidida_at else None,
        "created_at": fila.created_at.isoformat() if fila.created_at else None,
    }


def listar(db: Any, tenant_id: UUID, *, objeto: str, objeto_ref: str) -> list[dict[str, Any]]:
    filas = (
        db.execute(
            select(VarianteCopy)
            .where(
                VarianteCopy.tenant_id == tenant_id,
                VarianteCopy.objeto == objeto,
                VarianteCopy.objeto_ref == objeto_ref,
            )
            .order_by(VarianteCopy.created_at.desc(), VarianteCopy.id)
            .limit(200)
        )
        .scalars()
        .all()
    )
    return [a_dict(f) for f in filas]


def _traer(uow: UnidadDeTrabajo, variante_id: UUID) -> VarianteCopy:
    fila = uow.db.execute(
        select(VarianteCopy).where(
            VarianteCopy.id == variante_id, VarianteCopy.tenant_id == uow.tenant_id
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("Esa variante no existe", error_code="variantes.no_encontrada")
    return fila


def decidir(
    uow: UnidadDeTrabajo,
    *,
    variante_id: UUID,
    principal: Any,
    aprobar: bool,
    texto_final: str = "",
    motivo: str = "",
) -> dict[str, Any]:
    """Aprueba (puede reescribirla) o rechaza. Se decide de una en una."""
    fila = _traer(uow, variante_id)
    if fila.estado != "propuesta":
        raise Conflicto(f"Esta variante ya está {fila.estado}.", error_code="variantes.ya_decidida")
    fila.decidida_por = getattr(principal, "id", None)
    fila.decidida_at = datetime.now(timezone.utc)
    fila.motivo = motivo[:2000]
    if aprobar:
        final = texto_final.strip() or fila.texto_propuesto
        # Las reglas de siempre: marca lo comprobable del texto final.
        aprobada = var.aprobar(
            texto_propuesto=fila.texto_propuesto,
            texto_final=final,
            aprobada_por=fila.decidida_por or uow.tenant_id,
        )
        fila.texto_final = final
        fila.afirmaciones = aprobada["afirmaciones"]
        fila.estado = "aprobada"
    else:
        fila.estado = "rechazada"
    uow.db.flush()
    registrar(
        uow.db,
        accion="variantes.decidida",
        objeto="variante_copy",
        objeto_id=fila.id,
        datos={"estado": fila.estado, "lote_id": str(fila.lote_id)},
        tenant_id=uow.tenant_id,
    )
    return a_dict(fila)


def elegir_ganadora(uow: UnidadDeTrabajo, *, variante_id: UUID, principal: Any) -> dict[str, Any]:
    """La que se usa de su lote. Sólo una aprobada puede ganar."""
    fila = _traer(uow, variante_id)
    if fila.estado != "aprobada":
        raise Conflicto(
            "Sólo gana una variante aprobada: lo que no ha leído nadie no sale.",
            error_code="variantes.ganadora_sin_aprobar",
        )
    hermanas = (
        uow.db.execute(
            select(VarianteCopy).where(
                VarianteCopy.tenant_id == uow.tenant_id, VarianteCopy.lote_id == fila.lote_id
            )
        )
        .scalars()
        .all()
    )
    for h in hermanas:
        h.ganadora = h.id == fila.id
    uow.db.flush()
    registrar(
        uow.db,
        accion="variantes.ganadora",
        objeto="variante_copy",
        objeto_id=fila.id,
        datos={"lote_id": str(fila.lote_id), "por": str(getattr(principal, "id", "") or "")},
        tenant_id=uow.tenant_id,
    )
    return a_dict(fila)
