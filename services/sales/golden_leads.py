"""La ficha buena del lead y su umbral de duplicado por objeto
(CRM-01.01.04.06, CRM-01.01.04.02).

Hasta el 09-11-2026 la ficha buena —qué valor sobrevive cuando varias fuentes
dicen cosas distintas, y de dónde sale cada uno— y el umbral por objeto
cubrían cuentas y contactos, que viven en `party`. El lead vive aquí, y es
justo donde más versiones de la misma persona hay: el formulario que se rellena
dos veces, la captura que se fusiona en el lead que ya estaba y el alta manual
que queda señalada como posible duplicado.

La **decisión** es la del núcleo (`crmcore.datos.supervivencia`), la misma que
usa `party`: ningún servicio importa a otro y dos copias de la regla acabarían
diciendo cosas distintas. Lo que es de aquí:

- **Las reglas se guardan** por campo del lead, con la confianza de cada
  fuente. El campo `*` es la regla por defecto del lead.
- **Los candidatos salen del CRM**: lo que tiene hoy el lead (`crm`), cada
  captura fusionada en él con su canal como fuente —quedan anotadas en
  `campos.capturas_fusionadas`— y cada lead señalado como posible duplicado de
  este (`duplicado`).
- **El resultado se guarda** con la procedencia de cada valor. Componer no
  escribe en el lead; aplicar sí, y deja el antes en la auditoría.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.audit.chain import registrar
from crmcore.authz.decision import exigir
from crmcore.datos import supervivencia
from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from sqlalchemy import Boolean, DateTime, Index, String, Text, UniqueConstraint, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

OBJETO = "lead"

# Los datos de la persona: lo que una captura puede traer distinto. El estado,
# el origen o el SLA son del lead, no de quien lo dejó, y no compiten.
CAMPOS = ("nombre", "apellidos", "empresa", "cargo", "email", "telefono", "web", "pais")

# Con qué se compara un lead al deduplicarlo, y qué umbrales tiene cada uno.
OBJETOS_DEDUPE = ("lead", "contacto")
TIPOS_UMBRAL = {
    "sugerencia": "lead_dedupe_umbral_sugerencia",
    "bloqueo": "lead_dedupe_umbral_bloqueo",
}


class ReglaSupervivenciaLead(Base, TimestampMixin):
    """Qué valor sobrevive en un campo del lead, y cuánto se fía de cada fuente."""

    __tablename__ = "reglas_supervivencia_lead"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # `*` es la regla por defecto del lead.
    campo: Mapped[str] = mapped_column(String(80), nullable=False)
    estrategia: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="mayor_confianza",
        info={"opciones": supervivencia.ESTRATEGIAS},
    )
    confianza_por_fuente: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    activa: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    nota: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    __table_args__ = (UniqueConstraint("tenant_id", "campo", name="uq_regla_supervivencia_lead"),)


class GoldenLead(Base, TimestampMixin):
    """La ficha buena compuesta de un lead, con de dónde sale cada valor."""

    __tablename__ = "golden_leads"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    lead_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    valores: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
        info={"anonimizar_en_copias": True},
    )
    # {campo: {fuente, estrategia, regla, porque, candidatos}}
    procedencia: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
        info={"anonimizar_en_copias": True},
    )
    a_revisar: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
        info={"anonimizar_en_copias": True},
    )
    fuentes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    aplicado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    aplicados: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
        info={"anonimizar_en_copias": True},
    )
    compuesto_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "lead_id", name="uq_golden_lead"),
        Index("ix_golden_leads_lead", "tenant_id", "lead_id"),
    )


# ── Reglas ────────────────────────────────────────────────────────────────


def _regla_a_dict(r: ReglaSupervivenciaLead) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "objeto": OBJETO,
        "campo": r.campo,
        "estrategia": r.estrategia,
        "confianza_por_fuente": dict(r.confianza_por_fuente or {}),
        "activa": r.activa,
        "nota": r.nota,
    }


def reglas(db: Session, tenant_id: UUID) -> dict[str, Any]:
    filas = db.execute(
        select(ReglaSupervivenciaLead)
        .where(ReglaSupervivenciaLead.tenant_id == tenant_id)
        .order_by(ReglaSupervivenciaLead.campo)
    ).scalars()
    return {
        "objeto": OBJETO,
        "reglas": [_regla_a_dict(r) for r in filas],
        "campos": list(CAMPOS),
        "estrategias": list(supervivencia.ESTRATEGIAS),
    }


def guardar_regla(
    uow: UnidadDeTrabajo,
    *,
    campo: str,
    estrategia: str,
    confianza_por_fuente: dict[str, int] | None = None,
    activa: bool = True,
    nota: str = "",
) -> dict[str, Any]:
    supervivencia.validar_estrategia(estrategia)
    if campo != "*" and campo not in CAMPOS:
        raise ErrorValidacion(
            f"«{campo}» no es un campo que se componga en el lead.",
            error_code="golden.campo_no_componible",
            detalle={"admitidos": ["*", *CAMPOS]},
        )
    confianzas = supervivencia.validar_confianzas(confianza_por_fuente)
    fila = uow.db.execute(
        select(ReglaSupervivenciaLead).where(
            ReglaSupervivenciaLead.tenant_id == uow.tenant_id,
            ReglaSupervivenciaLead.campo == campo,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = ReglaSupervivenciaLead(tenant_id=uow.tenant_id, campo=campo)
        uow.db.add(fila)
    fila.estrategia = estrategia
    fila.confianza_por_fuente = confianzas
    fila.activa = activa
    fila.nota = nota.strip()
    uow.db.flush()
    registrar(
        uow.db,
        accion="golden.regla_guardada",
        objeto=OBJETO,
        objeto_id=fila.id,
        datos=_regla_a_dict(fila),
        tenant_id=uow.tenant_id,
    )
    return _regla_a_dict(fila)


def borrar_regla(uow: UnidadDeTrabajo, campo: str) -> None:
    fila = uow.db.execute(
        select(ReglaSupervivenciaLead).where(
            ReglaSupervivenciaLead.tenant_id == uow.tenant_id,
            ReglaSupervivenciaLead.campo == campo,
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado(
            "Ese campo no tiene regla propia", error_code="golden.regla_no_encontrada"
        )
    uow.db.delete(fila)
    uow.db.flush()


# ── Candidatos ────────────────────────────────────────────────────────────


def _texto(valor: Any) -> str:
    return "" if valor is None else str(valor).strip()


def _aware(momento: Any) -> datetime | None:
    if isinstance(momento, str):
        try:
            momento = datetime.fromisoformat(momento)
        except ValueError:
            return None
    if isinstance(momento, datetime):
        return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)
    return None


def _lead(db: Session, tenant_id: UUID, lead_id: UUID, accion: str = "read") -> Any:
    from services.sales.modelos import Lead

    fila = db.get(Lead, lead_id)
    if fila is None or fila.tenant_id != tenant_id or fila.deleted_at is not None:
        raise NoEncontrado(
            "No hay ningún lead con ese identificador",
            error_code="golden.ficha_no_encontrada",
        )
    exigir(db, objeto=OBJETO, accion=accion, registro=fila)
    return fila


def candidatos(db: Session, tenant_id: UUID, lead_id: UUID) -> dict[str, Any]:
    """Lo que dice cada fuente de cada campo de este lead."""
    from services.sales.modelos import Lead

    fila = _lead(db, tenant_id, lead_id)
    por_campo: dict[str, list[dict[str, Any]]] = {c: [] for c in CAMPOS}

    def _anadir(campo: str, candidato: dict[str, Any]) -> None:
        if campo not in por_campo or not _texto(candidato.get("valor")):
            return
        for ya in por_campo[campo]:
            if ya["fuente"] == candidato["fuente"] and _texto(ya["valor"]) == _texto(
                candidato["valor"]
            ):
                return
        por_campo[campo].append(candidato)

    # 1. Lo que tiene hoy el lead.
    for campo in CAMPOS:
        _anadir(
            campo,
            {
                "fuente": "crm",
                "valor": getattr(fila, campo, None),
                "cambiado_at": _aware(fila.updated_at),
                "recibido_at": _aware(fila.updated_at),
                "origen": "ficha",
            },
        )

    # 2. Cada captura fusionada en este lead, con su canal como fuente: es
    # justo lo que un tenant quiere poder pesar («el formulario de la feria
    # trae el cargo bien; el chat, no»).
    capturas = list((fila.campos or {}).get("capturas_fusionadas") or [])
    for captura in capturas:
        if not isinstance(captura, dict):
            continue
        datos = captura.get("datos") or {}
        canal = _texto(captura.get("canal")) or "captura"
        for campo in CAMPOS:
            _anadir(
                campo,
                {
                    "fuente": canal,
                    "valor": datos.get(campo),
                    "cambiado_at": _aware(captura.get("at")),
                    "recibido_at": _aware(captura.get("at")),
                    "origen": "captura",
                },
            )

    # 3. Cada lead que quedó señalado como posible duplicado de este.
    duplicados = list(
        db.execute(
            select(Lead).where(
                Lead.tenant_id == tenant_id,
                Lead.duplicado_de_id == lead_id,
                Lead.deleted_at.is_(None),
            )
        ).scalars()
    )
    for otro in duplicados:
        for campo in CAMPOS:
            _anadir(
                campo,
                {
                    "fuente": "duplicado",
                    "valor": getattr(otro, campo, None),
                    "cambiado_at": _aware(otro.updated_at),
                    "recibido_at": _aware(otro.created_at),
                    "origen": f"lead:{otro.id}",
                },
            )

    return {
        "fila": fila,
        "campos": {c: v for c, v in por_campo.items() if v},
        "capturas": len(capturas),
        "duplicados": len(duplicados),
    }


def _reglas_efectivas(db: Session, tenant_id: UUID) -> dict[str, dict[str, Any]]:
    return {
        r.campo: {"estrategia": r.estrategia, "confianza_por_fuente": r.confianza_por_fuente}
        for r in db.execute(
            select(ReglaSupervivenciaLead).where(
                ReglaSupervivenciaLead.tenant_id == tenant_id,
                ReglaSupervivenciaLead.activa.is_(True),
            )
        ).scalars()
    }


def componer(
    uow: UnidadDeTrabajo,
    *,
    lead_id: UUID,
    aplicar: bool = False,
    por: UUID | None = None,
) -> dict[str, Any]:
    """Compone, guarda y —si se pide— aplica la ficha buena de este lead."""
    assert uow.tenant_id is not None
    datos = candidatos(uow.db, uow.tenant_id, lead_id)
    fila = datos["fila"]
    if aplicar:
        exigir(uow.db, objeto=OBJETO, accion="write", registro=fila)
    compuesto = supervivencia.componer_campos(
        datos["campos"], reglas=_reglas_efectivas(uow.db, uow.tenant_id)
    )
    valores = compuesto["valores"]
    procedencia = compuesto["procedencia"]

    golden = uow.db.execute(
        select(GoldenLead).where(
            GoldenLead.tenant_id == uow.tenant_id, GoldenLead.lead_id == lead_id
        )
    ).scalar_one_or_none()
    if golden is None:
        golden = GoldenLead(tenant_id=uow.tenant_id, lead_id=lead_id)
        uow.db.add(golden)
    golden.valores = valores
    golden.procedencia = procedencia
    golden.a_revisar = compuesto["a_revisar"]
    golden.fuentes = compuesto["fuentes"]
    golden.compuesto_por = por
    golden.aplicado_at = None
    golden.aplicados = []

    if aplicar:
        aplicados: list[dict[str, Any]] = []
        for campo, valor in valores.items():
            if valor is None or _texto(getattr(fila, campo, None)) == _texto(valor):
                continue
            aplicados.append(
                {
                    "campo": campo,
                    "antes": getattr(fila, campo, None),
                    "despues": valor,
                    "fuente": procedencia[campo]["fuente"],
                }
            )
            setattr(fila, campo, valor)
        golden.aplicado_at = datetime.now(timezone.utc)
        golden.aplicados = aplicados
        registrar(
            uow.db,
            accion="golden.aplicado",
            objeto=OBJETO,
            objeto_id=lead_id,
            datos={"cambios": aplicados},
            tenant_id=uow.tenant_id,
        )
    uow.db.flush()
    return {**a_dict(golden), "capturas": datos["capturas"], "duplicados": datos["duplicados"]}


def a_dict(g: GoldenLead) -> dict[str, Any]:
    return {
        "id": str(g.id),
        "objeto": OBJETO,
        "objeto_id": str(g.lead_id),
        "valores": dict(g.valores or {}),
        "procedencia": dict(g.procedencia or {}),
        "a_revisar": list(g.a_revisar or []),
        "fuentes": dict(g.fuentes or {}),
        "limpio": not g.a_revisar,
        "compuesto_at": (g.updated_at or g.created_at).isoformat() if g.created_at else None,
        "aplicado_at": g.aplicado_at.isoformat() if g.aplicado_at else None,
        "aplicados": list(g.aplicados or []),
    }


def guardado(db: Session, tenant_id: UUID, lead_id: UUID) -> dict[str, Any]:
    _lead(db, tenant_id, lead_id)
    g = db.execute(
        select(GoldenLead).where(GoldenLead.tenant_id == tenant_id, GoldenLead.lead_id == lead_id)
    ).scalar_one_or_none()
    if g is None:
        raise NoEncontrado(
            "Este lead todavía no tiene ficha buena compuesta.",
            error_code="golden.sin_componer",
        )
    return a_dict(g)


def con_varias_versiones(db: Session, tenant_id: UUID, *, limite: int) -> list[dict[str, Any]]:
    """Los leads donde hay más de una versión de la verdad: con capturas
    fusionadas o con otros leads señalados como su duplicado."""
    from sqlalchemy import func, or_

    from services.sales.modelos import Lead

    vivos = (Lead.tenant_id == tenant_id, Lead.deleted_at.is_(None))
    duplicados = dict(
        db.execute(
            select(Lead.duplicado_de_id, func.count())
            .where(*vivos, Lead.duplicado_de_id.is_not(None))
            .group_by(Lead.duplicado_de_id)
            .limit(limite)
        ).all()
    )
    con_versiones = Lead.campos.has_key("capturas_fusionadas")
    if duplicados:
        con_versiones = or_(con_versiones, Lead.id.in_(list(duplicados)))
    filas = list(
        db.execute(
            select(Lead).where(*vivos, con_versiones).order_by(Lead.updated_at.desc()).limit(limite)
        ).scalars()
    )
    compuestos = (
        {
            g.lead_id: g
            for g in db.execute(
                select(GoldenLead).where(
                    GoldenLead.tenant_id == tenant_id,
                    GoldenLead.lead_id.in_([f.id for f in filas]),
                )
            ).scalars()
        }
        if filas
        else {}
    )
    salida = []
    for f in filas:
        g = compuestos.get(f.id)
        persona = " ".join(p for p in (f.nombre or "", f.apellidos or "") if p).strip()
        salida.append(
            {
                "objeto": OBJETO,
                "objeto_id": str(f.id),
                "nombre": " · ".join(p for p in (persona, f.empresa or "") if p) or (f.email or ""),
                "capturas": len((f.campos or {}).get("capturas_fusionadas") or []),
                "duplicados": int(duplicados.get(f.id, 0)),
                "compuesto_at": g.updated_at.isoformat() if g and g.updated_at else None,
                "aplicado_at": g.aplicado_at.isoformat() if g and g.aplicado_at else None,
            }
        )
    return salida


# ── Umbral de duplicado por objeto (CRM-01.01.04.02) ──────────────────────


def _por_objeto(db: Session | None) -> dict[str, Any]:
    from crmcore.runtime import settings as rt

    from services.sales.ajustes import ajustes

    valor = rt.efectivo("lead_dedupe_umbral_por_objeto", db)
    if not isinstance(valor, dict):
        valor = ajustes().lead_dedupe_umbral_por_objeto
    return dict(valor or {})


def umbral_de(db: Session | None, objeto: str, tipo: str, *, por_objeto: Any = None) -> float:
    """El umbral con el que un lead se compara con ESTE objeto.

    Lo que el objeto no diga sale del general de siempre
    (`lead_dedupe_umbral_sugerencia` / `_bloqueo`).
    """
    from crmcore.runtime import settings as rt

    from services.sales.ajustes import ajustes

    propio = ((por_objeto if por_objeto is not None else _por_objeto(db)) or {}).get(objeto)
    if isinstance(propio, dict) and propio.get(tipo) is not None:
        try:
            valor = float(propio[tipo])
            if 0.0 <= valor <= 1.0:
                return valor
        except (TypeError, ValueError):
            pass
    clave = TIPOS_UMBRAL[tipo]
    general = rt.efectivo(clave, db)
    return float(getattr(ajustes(), clave) if general is None else general)


def umbrales_por_objeto(db: Session | None) -> dict[str, dict[str, Any]]:
    """Los umbrales que valen ahora para cada objeto, y si son propios o del general."""
    por_objeto = _por_objeto(db)
    salida: dict[str, dict[str, Any]] = {}
    for objeto in OBJETOS_DEDUPE:
        propio = por_objeto.get(objeto) or {}
        salida[objeto] = {
            tipo: {
                "valor": umbral_de(db, objeto, tipo, por_objeto=por_objeto),
                "propio": isinstance(propio, dict) and propio.get(tipo) is not None,
            }
            for tipo in TIPOS_UMBRAL
        }
    return salida


def validar_umbrales(por_objeto: dict[str, dict[str, Any]]) -> dict[str, dict[str, float]]:
    limpio: dict[str, dict[str, float]] = {}
    for objeto, umbrales in por_objeto.items():
        if objeto not in OBJETOS_DEDUPE:
            raise ErrorValidacion(
                f"Un lead no se compara con «{objeto}».",
                error_code="duplicados.objeto_no_valido",
                detalle={"admitidos": list(OBJETOS_DEDUPE)},
            )
        for tipo, valor in umbrales.items():
            try:
                numero = float(valor)
            except (TypeError, ValueError):
                numero = -1.0
            if tipo not in TIPOS_UMBRAL or not 0.0 <= numero <= 1.0:
                raise ErrorValidacion(
                    "Cada umbral es sugerencia o bloqueo, entre 0 y 1.",
                    error_code="duplicados.umbral_no_valido",
                    detalle={"objeto": objeto, "tipo": tipo},
                )
        if umbrales:
            limpio[objeto] = {k: float(v) for k, v in umbrales.items()}
    return limpio
