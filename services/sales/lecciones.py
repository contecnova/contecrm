"""Lecciones aprendidas de las oportunidades cerradas.

Pedido el 05-11-2026: «cuando se pierde una oportunidad, pantallas que den toda
la información de por qué se ha perdido, con todo lujo de detalles, y la IA
indicando en propuestas parecidas qué hacer y qué no». Lo decidido:

- **El expediente** (`expediente`): todo lo que pasó, calculado de lo que el
  CRM guarda —el recorrido por etapas con los días en cada una, cuántas veces
  se movió la fecha prevista o el importe, los presupuestos con su descuento y
  su margen, la competencia, quién decidía y con qué postura, la actividad— y
  **comparado con las ganadas del mismo embudo**, que es lo que convierte un
  dato en una señal: «tardó 41 días en Negociación; las ganadas, 12».
- **La lección** (`LeccionOportunidad`): se crea al cerrar y el expediente se
  congela **al firmarla**. En las perdidas es **obligatoria**: un post-mortem
  guiado —qué pasó, qué señal temprana no vimos, qué haríamos distinto— que la
  IA propone con el expediente delante y el comercial corrige y **firma**. En
  las ganadas, el «haz esto», opcional.

Implementa CRM-03.01.01.15. Lo que leerán las oportunidades abiertas —los
consejos, los avisos en los momentos clave y el resumen semanal— son
CRM-03.01.01.16 a .18, y están pendientes: las lecciones firmadas todavía no
llegan a ninguna otra oportunidad.
"""

from __future__ import annotations

import statistics
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from crmcore.audit.chain import registrar
from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado
from crmcore.fechas import hoy
from crmcore.ids import nuevo_id
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

# Registra las claves que lee `umbrales()`. Sin esto, quien importe este módulo
# sin pasar por el arranque del servicio —una prueba, un script— leía `None`.
from services.sales import ajustes as _ajustes  # noqa: E402,F401

ESTADOS = ("pendiente", "firmada")
# Lo que puede pesar en una pérdida o en una victoria. Lista cerrada a propósito:
# es lo que permite agrupar y contar patrones; un texto libre no se agrupa.
FACTORES = (
    "precio",
    "descuento_tardio",
    "competidor",
    "sin_decisor",
    "decisor_en_contra",
    "sin_presupuesto_cliente",
    "plazo",
    "producto_no_encaja",
    "seguimiento_flojo",
    "demasiado_tiempo_en_etapa",
    "fecha_movida",
    "relacion",
    "propuesta_de_valor",
    "otro",
)

# Cómo se escribe cada factor en un texto que lee una persona —un aviso, un
# resumen, la notificación que sale por correo—. La pantalla tiene los suyos;
# éstos son para lo que redacta el servidor.
ROTULO_FACTOR = {
    "precio": "el precio",
    "descuento_tardio": "un descuento tardío",
    "competidor": "un competidor",
    "sin_decisor": "no saber quién decidía",
    "decisor_en_contra": "un decisor en contra",
    "sin_presupuesto_cliente": "que el cliente no tenía presupuesto",
    "plazo": "el plazo",
    "producto_no_encaja": "que el producto no encajaba",
    "seguimiento_flojo": "un seguimiento flojo",
    "demasiado_tiempo_en_etapa": "demasiado tiempo en una etapa",
    "fecha_movida": "una fecha que se movió",
    "relacion": "la relación",
    "propuesta_de_valor": "la propuesta de valor",
    "otro": "otros motivos",
}


class LeccionOportunidad(Base, TimestampMixin):
    """Lo que enseñó una oportunidad cerrada."""

    __tablename__ = "lecciones_oportunidad"
    __table_args__ = (UniqueConstraint("tenant_id", "oportunidad_id"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # Parte de su oportunidad (ver `consejos.AvisoLeccion`): sin la cascada,
    # ninguna oportunidad cerrada se podía borrar, porque toda tiene lección.
    oportunidad_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("oportunidades.id", ondelete="CASCADE"), nullable=False
    )
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    titulo: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    resultado: Mapped[str] = mapped_column(String(20), nullable=False)
    motivo: Mapped[str | None] = mapped_column(String(80), nullable=True)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    # El post-mortem: lo que firma el comercial.
    que_paso: Mapped[str | None] = mapped_column(
        Text, nullable=True, info={"anonimizar_en_copias": True}
    )
    senal_temprana: Mapped[str | None] = mapped_column(
        Text, nullable=True, info={"anonimizar_en_copias": True}
    )
    que_hariamos_distinto: Mapped[str | None] = mapped_column(
        Text, nullable=True, info={"anonimizar_en_copias": True}
    )
    factores: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # El expediente congelado al cerrar: lo que había, no lo que haya después.
    hechos: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Si el texto lo propuso la IA y cuánto se corrigió.
    propuesta_ia: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    responsable_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    firmada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    firmada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    obligatoria: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Cuándo se cerró y por cuánto, copiados de la oportunidad: la lista se
    # ordena y se lee por aquí, y la fecha de alta de la lección no lo dice —
    # las históricas nacen todas el mismo día—.
    cerrada_el: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    importe: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)


# ── El expediente ─────────────────────────────────────────────────────────


def _mediana(valores: list[float]) -> float | None:
    return float(statistics.median(valores)) if valores else None


def _num(valor: Any) -> float | None:
    return float(valor) if valor is not None else None


def _recorrido(db: Session, oportunidad_id: UUID) -> list[dict[str, Any]]:
    from services.sales.modelos import CambioEtapa, Etapa

    filas = db.execute(
        select(CambioEtapa)
        .where(CambioEtapa.oportunidad_id == oportunidad_id)
        .order_by(CambioEtapa.created_at)
    ).scalars()
    nombres = {e.id: e.nombre for e in db.execute(select(Etapa)).scalars()}
    salida = []
    for c in filas:
        salida.append(
            {
                "cuando": c.created_at.isoformat() if c.created_at else None,
                "desde": nombres.get(c.etapa_desde_id) if c.etapa_desde_id else None,
                "hasta": nombres.get(c.etapa_hasta_id),
                "dias_en_la_anterior": c.dias_en_etapa,
                "importe": _num(c.importe_en_cambio),
                "fecha_prevista": c.fecha_cierre_en_cambio.isoformat()
                if c.fecha_cierre_en_cambio
                else None,
                "motivo": c.motivo,
            }
        )
    return salida


def _cambios_de_rumbo(recorrido: list[dict[str, Any]]) -> dict[str, Any]:
    """Cuántas veces se movió la fecha prevista y el importe por el camino."""
    fechas = [r["fecha_prevista"] for r in recorrido if r["fecha_prevista"]]
    importes = [r["importe"] for r in recorrido if r["importe"] is not None]
    movida = sum(1 for a, b in zip(fechas, fechas[1:], strict=False) if a != b)
    retrasada = sum(1 for a, b in zip(fechas, fechas[1:], strict=False) if b > a)
    cambios_importe = sum(1 for a, b in zip(importes, importes[1:], strict=False) if a != b)
    return {
        "veces_que_se_movio_la_fecha": movida,
        "veces_que_se_retraso": retrasada,
        "veces_que_cambio_el_importe": cambios_importe,
        "importe_inicial": importes[0] if importes else None,
        "importe_final": importes[-1] if importes else None,
    }


def _presupuestos(db: Session, oportunidad_id: UUID) -> list[dict[str, Any]]:
    from services.sales.presupuestos import Presupuesto

    filas = db.execute(
        select(Presupuesto)
        .where(Presupuesto.oportunidad_id == oportunidad_id, Presupuesto.deleted_at.is_(None))
        .order_by(Presupuesto.created_at)
    ).scalars()
    salida = []
    for p in filas:
        subtotal = _num(p.subtotal) or 0
        descuento = _num(p.descuento_total) or 0
        salida.append(
            {
                "numero": p.numero,
                "estado": p.estado,
                "enviado_el": p.enviado_at.isoformat() if p.enviado_at else None,
                "total": _num(p.total),
                "descuento": descuento,
                "descuento_pct": round(100 * descuento / subtotal, 1) if subtotal else None,
                "margen_pct": _num(p.margen_pct),
                "es_revision": p.anterior_id is not None,
            }
        )
    return salida


def _competencia(db: Session, oportunidad_id: UUID) -> list[dict[str, Any]]:
    from services.sales.modelos import CompetidorEnOportunidad as CompetidorOportunidad

    return [
        {
            "nombre": c.nombre,
            "fortalezas": c.fortalezas,
            "debilidades": c.debilidades,
            "gano": bool(c.ganador),
        }
        for c in db.execute(
            select(CompetidorOportunidad).where(
                CompetidorOportunidad.oportunidad_id == oportunidad_id
            )
        ).scalars()
    ]


def _decisores(db: Session, oportunidad_id: UUID, principal: Any) -> list[dict[str, Any]]:
    """Quién decidía, con su nombre y su cargo.

    El nombre se pide a party como quien mira, y queda congelado al firmar:
    «el decisor estaba en contra» no le sirve a nadie dentro de un año si no
    dice quién era. Si party no lo da —no se ve, o ya no existe—, se queda el
    rol y se dice que falta, sin inventarlo.
    """
    from crmcore import ia_ficha
    from crmcore.errors import CrmError

    from services.sales.ingresos import RolCompra

    filas = list(
        db.execute(select(RolCompra).where(RolCompra.oportunidad_id == oportunidad_id)).scalars()
    )
    personas: dict[UUID, dict[str, Any]] = {}
    for contacto_id in {r.contacto_id for r in filas}:
        try:
            datos = ia_ficha.leer(f"/api/v1/contacts/{contacto_id}", principal)
        except CrmError:
            continue
        if isinstance(datos, dict):
            personas[contacto_id] = datos
    return [
        {
            "contacto_id": str(r.contacto_id),
            "nombre": (personas.get(r.contacto_id) or {}).get("nombre_completo"),
            "cargo": (personas.get(r.contacto_id) or {}).get("cargo"),
            "rol": r.rol,
            # Numeric en la tabla: como entero, o no se puede congelar en JSON.
            "postura": int(r.postura or 0),
            "motivo": r.motivo,
        }
        for r in filas
    ]


def _cuando_paso(actividad: dict[str, Any]) -> str | None:
    """El día en que pasó una actividad de party.

    Party no guarda «realizada»: una reunión pasó cuando empezó, y lo que no
    tiene hora, cuando se completó. El vencimiento y el alta van detrás porque
    dicen cuándo se pensó, no cuándo se hizo. Hasta el 05-11-2026 se leía un
    `realizada_at` que no existe y todo caía en el alta: los días sin contacto
    al cerrar se contaban desde el día en que alguien apuntó la actividad.
    """
    for campo in ("inicio_at", "fin_at", "completada_at", "vence_at", "created_at"):
        if actividad.get(campo):
            return str(actividad[campo])[:10]
    return None


def umbrales(db: Session | None) -> dict[str, Any]:
    """Dónde empieza cada señal, leído UNA vez por expediente.

    Son ajustes en caliente —cada empresa decide qué es «tardar demasiado»— y
    leerlos va a la base, así que no se leen dentro de los bucles: se leen
    aquí, se pasan y quedan guardados en el expediente. Así la pantalla pinta
    con las mismas reglas con las que se calculó, y un expediente congelado
    dice con qué reglas se congeló.
    """
    from crmcore.runtime.settings import efectivo

    return {
        "minimo_comparables": int(efectivo("lecciones_minimo_comparables", db)),
        "actividades_max": int(efectivo("lecciones_actividades_max", db)),
        "factor_lento": float(efectivo("lecciones_factor_lento", db)),
        "descuento_margen_pp": float(efectivo("lecciones_descuento_margen_pp", db)),
        "dias_sin_contacto": int(efectivo("lecciones_dias_sin_contacto", db)),
    }


def _actividad(oportunidad: Any, principal: Any, u: dict[str, Any]) -> dict[str, Any]:
    """La actividad de la oportunidad, de party, leída como quien la pide."""
    from crmcore import ia_ficha
    from crmcore.errors import CrmError

    try:
        datos = ia_ficha.leer(
            "/api/v1/activities",
            principal,
            {
                "objeto": "oportunidad",
                "objeto_id": str(oportunidad.id),
                # 200 es el tope de página de la API de party, no un umbral.
                "limite": min(200, u["actividades_max"]),
            },
        )
    except CrmError as exc:
        return {"leida": False, "porque": str(exc)[:200]}
    items = (datos or {}).get("items", []) if isinstance(datos, dict) else []
    por_tipo: dict[str, int] = {}
    fechas: list[str] = []
    ultimas: list[dict[str, Any]] = []
    for a in items:
        por_tipo[str(a.get("tipo") or "otra")] = por_tipo.get(str(a.get("tipo") or "otra"), 0) + 1
        cuando = _cuando_paso(a)
        if cuando:
            fechas.append(cuando)
        ultimas.append({"tipo": a.get("tipo"), "asunto": a.get("asunto"), "cuando": cuando})
    fechas.sort()
    ultima = fechas[-1] if fechas else None
    cierre = oportunidad.fecha_cierre_real
    dias_sin_contacto = (cierre - date.fromisoformat(ultima)).days if ultima and cierre else None
    return {
        "leida": True,
        "total": len(items),
        "por_tipo": por_tipo,
        "primera": fechas[0] if fechas else None,
        "ultima": ultima,
        "dias_sin_contacto_al_cerrar": dias_sin_contacto,
        "ultimas": sorted(ultimas, key=lambda a: a["cuando"] or "", reverse=True)[:10],
    }


def _referencia_ganadas(db: Session, oportunidad: Any, u: dict[str, Any]) -> dict[str, Any]:
    """Cómo fueron las ganadas del mismo embudo: la vara de medir."""
    from services.sales.modelos import CambioEtapa, Etapa, Oportunidad
    from services.sales.presupuestos import Presupuesto

    ganadas = db.execute(
        select(
            Oportunidad.id,
            Oportunidad.created_at,
            Oportunidad.fecha_cierre_real,
            Oportunidad.importe,
        ).where(
            Oportunidad.pipeline_id == oportunidad.pipeline_id,
            Oportunidad.estado == "ganada",
            Oportunidad.deleted_at.is_(None),
        )
    ).all()
    minimo = u["minimo_comparables"]
    if len(ganadas) < minimo:
        return {
            "comparable": False,
            "ganadas": len(ganadas),
            "porque": f"Hay {len(ganadas)} ganadas en este embudo y hacen falta {minimo} "
            "para que la comparación diga algo.",
        }
    ids = [g.id for g in ganadas]
    duraciones = [
        (g.fecha_cierre_real - g.created_at.date()).days
        for g in ganadas
        if g.fecha_cierre_real and g.created_at
    ]
    nombres = {e.id: e.nombre for e in db.execute(select(Etapa)).scalars()}
    por_etapa: dict[str, list[float]] = {}
    for c in db.execute(
        select(CambioEtapa.etapa_desde_id, CambioEtapa.dias_en_etapa).where(
            CambioEtapa.oportunidad_id.in_(ids), CambioEtapa.dias_en_etapa.is_not(None)
        )
    ).all():
        if c.etapa_desde_id:
            por_etapa.setdefault(nombres.get(c.etapa_desde_id, "?"), []).append(
                float(c.dias_en_etapa)
            )
    descuentos = [
        100 * float(p.descuento_total) / float(p.subtotal)
        for p in db.execute(
            select(Presupuesto.descuento_total, Presupuesto.subtotal).where(
                Presupuesto.oportunidad_id.in_(ids), Presupuesto.subtotal > 0
            )
        ).all()
        if p.descuento_total is not None
    ]
    return {
        "comparable": True,
        "ganadas": len(ganadas),
        "mediana_dias_hasta_cerrar": _mediana([float(d) for d in duraciones]),
        "mediana_dias_por_etapa": {k: _mediana(v) for k, v in sorted(por_etapa.items())},
        "mediana_descuento_pct": round(_mediana(descuentos), 1) if descuentos else None,
        "mediana_importe": _mediana([float(g.importe) for g in ganadas if g.importe is not None]),
    }


def _senales(hechos: dict[str, Any]) -> list[dict[str, Any]]:
    """Lo que se aparta de las ganadas, dicho con su número. Sólo hechos."""
    senales: list[dict[str, Any]] = []
    ref = hechos.get("comparado_con_las_ganadas") or {}
    u = hechos.get("umbrales") or {}
    lento = float(u.get("factor_lento") or 0)
    if ref.get("comparable") and lento:
        por_etapa = ref.get("mediana_dias_por_etapa") or {}
        for paso in hechos.get("recorrido") or []:
            etapa, dias = paso.get("desde"), paso.get("dias_en_la_anterior")
            normal = por_etapa.get(etapa) if etapa else None
            if dias is not None and normal and dias >= lento * normal:
                senales.append(
                    {
                        "factor": "demasiado_tiempo_en_etapa",
                        "texto": f"{dias} días en «{etapa}»; las ganadas, {normal:g}.",
                    }
                )
        duracion = (hechos.get("oportunidad") or {}).get("dias_abierta")
        normal = ref.get("mediana_dias_hasta_cerrar")
        if duracion and normal and duracion >= lento * normal:
            senales.append(
                {
                    "factor": "demasiado_tiempo_en_etapa",
                    "texto": f"Abierta {duracion} días; las ganadas se cierran en {normal:g}.",
                }
            )
        descuentos = [
            p["descuento_pct"] for p in hechos.get("presupuestos") or [] if p.get("descuento_pct")
        ]
        normal = ref.get("mediana_descuento_pct")
        margen = float(u.get("descuento_margen_pp") or 0)
        if descuentos and normal is not None and max(descuentos) > normal + margen:
            senales.append(
                {
                    "factor": "precio",
                    "texto": f"Descuento de hasta el {max(descuentos):g} %; en las ganadas, "
                    f"{normal:g} %.",
                }
            )
    rumbo = hechos.get("cambios_de_rumbo") or {}
    if rumbo.get("veces_que_se_retraso"):
        senales.append(
            {
                "factor": "fecha_movida",
                "texto": f"La fecha prevista se retrasó {rumbo['veces_que_se_retraso']} veces.",
            }
        )
    if not hechos.get("decisores"):
        senales.append({"factor": "sin_decisor", "texto": "No consta quién decidía."})
    else:
        # La postura es un número: negativa, en contra; positiva, a favor.
        en_contra = [d for d in hechos["decisores"] if int(d.get("postura") or 0) < 0]
        if en_contra:
            # Con quién y por qué, que es lo que se puede usar la próxima vez.
            quienes = "; ".join(
                f"{d.get('nombre') or 'alguien'} ({d.get('rol')})"
                + (f": {d['motivo']}" if d.get("motivo") else "")
                for d in en_contra
            )
            senales.append({"factor": "decisor_en_contra", "texto": f"En contra: {quienes}."})
    actividad = hechos.get("actividad") or {}
    sin = actividad.get("dias_sin_contacto_al_cerrar")
    tope_sin = u.get("dias_sin_contacto")
    if actividad.get("leida") and sin is not None and tope_sin and sin >= int(tope_sin):
        senales.append(
            {"factor": "seguimiento_flojo", "texto": f"{sin} días sin contacto antes de cerrarse."}
        )
    ganador = (hechos.get("oportunidad") or {}).get("competidor_ganador")
    if ganador:
        senales.append({"factor": "competidor", "texto": f"La ganó {ganador}."})
    return senales


def expediente(db: Session, oportunidad_id: UUID, principal: Any) -> dict[str, Any]:
    """Todo lo que pasó en la oportunidad, y en qué se aparta de las ganadas."""
    from services.sales.servicio import _oportunidad

    # Por el cargador compartido: evalúa las políticas de acceso al registro.
    # El expediente enseña la oportunidad entera; quien no puede leerla no lo ve.
    op = _oportunidad(db, oportunidad_id)
    u = umbrales(db)
    recorrido = _recorrido(db, op.id)
    abierta = (
        ((op.fecha_cierre_real or datetime.now(timezone.utc).date()) - op.created_at.date()).days
        if op.created_at
        else None
    )
    hechos: dict[str, Any] = {
        "oportunidad": {
            "id": str(op.id),
            "nombre": op.nombre,
            "estado": op.estado,
            "importe": _num(op.importe),
            "moneda": op.moneda,
            "motivo_perdida": op.motivo_perdida,
            "nota_perdida": op.nota_perdida,
            "competidor_ganador": op.competidor_ganador,
            "creada": op.created_at.date().isoformat() if op.created_at else None,
            "cerrada": op.fecha_cierre_real.isoformat() if op.fecha_cierre_real else None,
            "dias_abierta": abierta,
        },
        "recorrido": recorrido,
        "cambios_de_rumbo": _cambios_de_rumbo(recorrido),
        "presupuestos": _presupuestos(db, op.id),
        "competencia": _competencia(db, op.id),
        "decisores": _decisores(db, op.id, principal),
        "actividad": _actividad(op, principal, u),
        "comparado_con_las_ganadas": _referencia_ganadas(db, op, u),
        "umbrales": u,
    }
    hechos["senales"] = _senales(hechos)
    return hechos


# ── La lección ────────────────────────────────────────────────────────────


def al_cerrar(uow: UnidadDeTrabajo, oportunidad: Any, *, ganada: bool) -> LeccionOportunidad:
    """Crea la lección pendiente. Obligatoria en las perdidas.

    El expediente se congela en el post-mortem al firmar, no aquí: aquí la
    sesión es la del cierre, y la actividad hay que pedírsela a party con la
    identidad de alguien. Se guarda lo que sale de esta base, que ya es mucho.
    """
    fila = uow.db.execute(
        select(LeccionOportunidad).where(
            LeccionOportunidad.tenant_id == uow.tenant_id,
            LeccionOportunidad.oportunidad_id == oportunidad.id,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = LeccionOportunidad(
            tenant_id=uow.tenant_id,
            oportunidad_id=oportunidad.id,
            cuenta_id=oportunidad.cuenta_id,
            responsable_id=oportunidad.owner_id,
        )
        uow.db.add(fila)
    fila.titulo = str(oportunidad.nombre or "")[:300]
    fila.resultado = "ganada" if ganada else "perdida"
    fila.motivo = None if ganada else oportunidad.motivo_perdida
    fila.obligatoria = not ganada
    fila.estado = "pendiente"
    fila.cerrada_el = oportunidad.fecha_cierre_real or hoy(uow.db)
    fila.importe = oportunidad.importe
    uow.db.flush()
    return fila


def crear_de_las_cerradas(uow: UnidadDeTrabajo) -> dict[str, int]:
    """La lección de cada oportunidad que se cerró antes de que existieran.

    **No obligatorias**: son históricas, y hacerlas obligatorias llenaría de
    golpe la lista de pendientes con cierres de hace meses que nadie recuerda.
    Quedan para quien quiera escribirlas, y su expediente se puede ver igual.
    """
    from services.sales.modelos import Oportunidad

    ya = set(
        uow.db.execute(
            select(LeccionOportunidad.oportunidad_id).where(
                LeccionOportunidad.tenant_id == uow.tenant_id
            )
        ).scalars()
    )
    creadas = 0
    for op in uow.db.execute(
        select(Oportunidad).where(
            Oportunidad.estado.in_(("perdida", "ganada")), Oportunidad.deleted_at.is_(None)
        )
    ).scalars():
        if op.id in ya:
            continue
        fila = al_cerrar(uow, op, ganada=op.estado == "ganada")
        fila.obligatoria = False
        creadas += 1
    uow.db.flush()
    return {"creadas": creadas, "ya_tenian": len(ya)}


def leccion(db: Session, leccion_id: UUID) -> LeccionOportunidad:
    """La lección, sólo si quien la pide puede ver su oportunidad.

    Pasa por el cargador de la oportunidad, que es el punto único de decisión:
    una lección firmada enseña el expediente congelado —importes, descuentos,
    quién decidía— sin volver a calcularlo, así que sin esto se leía entero
    aunque la oportunidad estuviera fuera del alcance de quien miraba.
    """
    from services.sales.servicio import _oportunidad

    fila = db.get(LeccionOportunidad, leccion_id)
    if fila is None:
        raise NoEncontrado("Esa lección no existe", error_code="leccion.no_encontrada")
    _oportunidad(db, fila.oportunidad_id)
    return fila


def proponer_con_ia(db: Session, fila: LeccionOportunidad, principal: Any) -> dict[str, Any]:
    """El borrador del post-mortem, pedido a la IA con el expediente delante."""
    import json

    from crmcore import ia_ficha

    hechos = expediente(db, fila.oportunidad_id, principal)
    salida = ia_ficha.pedir(
        "/api/v1/ia/generar",
        {
            "plantilla": "leccion_oportunidad",
            "datos": {
                "nombre": fila.titulo or "la oportunidad",
                "resultado": fila.resultado,
            },
            "contexto": [
                {
                    "texto": json.dumps(hechos, ensure_ascii=False, default=str),
                    "fuente": "expediente",
                    "id": str(fila.oportunidad_id),
                    "permiso": "opportunity:read",
                    "sensibilidad": "interno",
                }
            ],
            "objeto": "oportunidad",
            "objeto_id": str(fila.oportunidad_id),
        },
        principal,
    )
    propuesta = _leer_borrador(str((salida or {}).get("texto") or ""))
    fila.propuesta_ia = {
        **propuesta,
        "propuesta_id": (salida or {}).get("propuesta_id"),
        "generado": bool((salida or {}).get("generado", True)) and bool(propuesta),
    }
    fila.hechos = hechos
    db.flush()
    return {"leccion_id": str(fila.id), "propuesta": fila.propuesta_ia, "hechos": hechos}


def _leer_borrador(texto: str) -> dict[str, Any]:
    """El borrador viene en JSON; si no, se deja el texto entero en «qué pasó»."""
    import json
    import re

    bloque = re.search(r"\{.*\}", texto, re.S)
    if bloque:
        try:
            datos = json.loads(bloque.group(0))
            return {
                "que_paso": str(datos.get("que_paso") or ""),
                "senal_temprana": str(datos.get("senal_temprana") or ""),
                "que_hariamos_distinto": str(datos.get("que_hariamos_distinto") or ""),
                "factores": [f for f in datos.get("factores") or [] if f in FACTORES],
            }
        except ValueError:
            pass
    return {
        "que_paso": texto.strip(),
        "senal_temprana": "",
        "que_hariamos_distinto": "",
        "factores": [],
    }


def firmar(
    uow: UnidadDeTrabajo,
    leccion_id: UUID,
    *,
    que_paso: str,
    senal_temprana: str,
    que_hariamos_distinto: str,
    factores: list[str],
    principal: Any,
) -> LeccionOportunidad:
    fila = leccion(uow.db, leccion_id)
    if fila.estado == "firmada":
        raise Conflicto("Esa lección ya está firmada", error_code="leccion.ya_firmada")
    if fila.resultado == "perdida" and not (que_paso.strip() and que_hariamos_distinto.strip()):
        raise ErrorValidacion(
            "Una pérdida se firma diciendo qué pasó y qué haríamos distinto: es lo que "
            "la siguiente oportunidad parecida va a leer.",
            error_code="leccion.incompleta",
        )
    desconocidos = sorted(set(factores) - set(FACTORES))
    if desconocidos:
        raise ErrorValidacion(
            f"Factores desconocidos: {', '.join(desconocidos)}",
            error_code="leccion.factor_desconocido",
            detalle={"validos": list(FACTORES)},
        )
    if not fila.hechos:
        fila.hechos = expediente(uow.db, fila.oportunidad_id, principal)
    fila.que_paso = que_paso.strip()
    fila.senal_temprana = senal_temprana.strip() or None
    fila.que_hariamos_distinto = que_hariamos_distinto.strip()
    fila.factores = sorted(set(factores))
    fila.estado = "firmada"
    fila.firmada_por = principal.id
    fila.firmada_at = datetime.now(timezone.utc)
    uow.db.flush()
    registrar(
        uow.db,
        accion="leccion.firmada",
        objeto="oportunidad",
        objeto_id=fila.oportunidad_id,
        datos={"resultado": fila.resultado, "factores": fila.factores},
        tenant_id=fila.tenant_id,
    )
    uow.emitir(
        "opportunity.lesson.signed",
        subject=("oportunidad", fila.oportunidad_id),
        data={
            "leccion_id": str(fila.id),
            "oportunidad_id": str(fila.oportunidad_id),
            "resultado": fila.resultado,
        },
    )
    return fila


def patrones(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Lo que se repite en las firmadas: factores, motivos y dónde se pierde."""
    filas = (
        db.execute(
            select(LeccionOportunidad).where(
                LeccionOportunidad.tenant_id == tenant_id,
                LeccionOportunidad.estado == "firmada",
            )
        )
        .scalars()
        .all()
    )
    por_factor: dict[str, dict[str, int]] = {}
    for f in filas:
        for factor in f.factores or []:
            cuenta = por_factor.setdefault(factor, {"perdida": 0, "ganada": 0})
            cuenta[f.resultado] = cuenta.get(f.resultado, 0) + 1
    donde: dict[str, int] = {}
    for f in filas:
        if f.resultado != "perdida":
            continue
        recorrido = (f.hechos or {}).get("recorrido") or []
        ultima = next((p.get("desde") for p in reversed(recorrido) if p.get("desde")), None)
        if ultima:
            donde[ultima] = donde.get(ultima, 0) + 1
    pendientes = db.execute(
        select(func.count())
        .select_from(LeccionOportunidad)
        .where(
            LeccionOportunidad.tenant_id == tenant_id,
            LeccionOportunidad.estado == "pendiente",
            LeccionOportunidad.obligatoria.is_(True),
        )
    ).scalar()
    # Cuántas hay de cada, contadas aquí: la lista va por páginas y contar en
    # la pantalla lo cargado diría 200 donde hay 456.
    por_resultado = dict(
        db.execute(
            select(LeccionOportunidad.resultado, func.count())
            .where(LeccionOportunidad.tenant_id == tenant_id)
            .group_by(LeccionOportunidad.resultado)
        ).all()
    )

    def _orden(cuentas: dict[str, int]) -> dict[str, int]:
        # Lo que no pesa no sale: una barra a cero es ruido.
        return dict(sorted(((k, v) for k, v in cuentas.items() if v), key=lambda x: -x[1]))

    # Planas, una pregunta cada una: la pantalla las dibuja como barras sin
    # saber qué son, igual que cualquier otra medida de un módulo.
    return {
        "firmadas": len(filas),
        "pendientes_obligatorias": int(pendientes or 0),
        "perdidas": int(por_resultado.get("perdida", 0)),
        "ganadas": int(por_resultado.get("ganada", 0)),
        "factores_en_las_perdidas": _orden({f: n.get("perdida", 0) for f, n in por_factor.items()}),
        "factores_en_las_ganadas": _orden({f: n.get("ganada", 0) for f, n in por_factor.items()}),
        "etapa_donde_se_pierde": _orden(donde),
        "que_significa": (
            f"Sale de {len(filas)} post-mortem firmados. Una perdida sin firmar no "
            "cuenta: su lección no la ha escrito nadie todavía."
        ),
    }
