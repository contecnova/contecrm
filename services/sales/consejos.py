"""Lo que las lecciones aprendidas le dicen a las oportunidades abiertas.

Las lecciones firmadas (`lecciones.py`, CRM-03.01.01.15) no sirven de nada si
sólo se leen en su ficha. Esto las lleva a donde se decide:

- **Consejos** (CRM-03.01.01.16): en cada oportunidad abierta, las lecciones
  del **mismo cliente** y las **parecidas por significado** de cualquier otro,
  ganadas y perdidas. La IA puede resumirlas en «haz esto / no hagas esto»,
  y cada consejo tiene que decir de qué lección sale: el que no se puede
  atribuir se descarta, porque un consejo sin fuente es una opinión.
- **Avisos** (CRM-03.01.01.17): al crear la oportunidad, al cambiar de etapa y
  al mandar el presupuesto, si alguna lección tiene algo que decir en ese
  momento. Se guardan —se ven en la ficha aunque el aviso no llegue— y se
  emiten para que identity los notifique al responsable. Sin nada que decir
  no hay aviso: un aviso vacío enseña a ignorarlos todos.
- **Resumen** (CRM-03.01.01.18): cada `lecciones_resumen_dias`, lo firmado, lo
  cerrado y lo que queda por firmar, para quien dirige a quien tiene lecciones.

Los avisos se calculan **sin la IA y sin el índice**: corren dentro de la
transacción que crea o mueve la oportunidad, y atar eso a otro servicio
haría que no se pudiera mover una etapa con intelligence caído. Los
consejos sí los usan, porque se piden al abrir la ficha y pueden esperar.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import CrmError
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from services.sales.lecciones import FACTORES, ROTULO_FACTOR, LeccionOportunidad

logger = get_logger(__name__)

MOMENTOS = ("creacion", "etapa", "presupuesto")
TIPOS_DE_CONSEJO = ("haz", "no_hagas")


class AvisoLeccion(Base, TimestampMixin):
    """Lo que una lección tenía que decir en un momento de una oportunidad."""

    __tablename__ = "avisos_leccion"
    # Uno por momento y clave —la etapa, el presupuesto—: volver a la misma
    # etapa no repite el aviso, lo actualiza.
    __table_args__ = (UniqueConstraint("tenant_id", "oportunidad_id", "momento", "clave"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # Parte de la oportunidad, no una referencia a ella: la cascada es como el
    # modelo lo dice, y sin ella un aviso generado por el sistema impedía
    # borrar la oportunidad.
    oportunidad_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("oportunidades.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    momento: Mapped[str] = mapped_column(String(20), nullable=False, info={"opciones": MOMENTOS})
    clave: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    titulo: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    detalle: Mapped[str] = mapped_column(Text, nullable=False, default="")
    lecciones: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)


class ResumenLecciones(Base, TimestampMixin):
    """El resumen de un periodo, con a quién se mandó."""

    __tablename__ = "resumenes_lecciones"
    __table_args__ = (UniqueConstraint("tenant_id", "desde"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    desde: Mapped[date] = mapped_column(Date, nullable=False)
    hasta: Mapped[date] = mapped_column(Date, nullable=False)
    titulo: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    detalle: Mapped[str] = mapped_column(Text, nullable=False, default="")
    datos: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    destinatarios: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    enviado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── Qué lecciones vienen a cuento ─────────────────────────────────────────


def _firmadas(tenant_id: UUID) -> Any:
    return select(LeccionOportunidad).where(
        LeccionOportunidad.tenant_id == tenant_id,
        LeccionOportunidad.estado == "firmada",
    )


def _como_consejo(
    fila: LeccionOportunidad, por_que: str, parecido: float | None = None
) -> dict[str, Any]:
    return {
        "id": str(fila.id),
        "oportunidad_id": str(fila.oportunidad_id),
        "titulo": fila.titulo,
        "resultado": fila.resultado,
        "motivo": fila.motivo,
        "factores": fila.factores or [],
        "que_paso": (fila.que_paso or "")[:600],
        "que_hariamos_distinto": fila.que_hariamos_distinto or "",
        "cerrada_el": fila.cerrada_el.isoformat() if fila.cerrada_el else None,
        "por_que": por_que,
        "parecido": parecido,
    }


def del_mismo_cliente(db: Session, oportunidad: Any, tope: int) -> list[LeccionOportunidad]:
    """Las firmadas de la misma cuenta, las más recientes primero."""
    if not oportunidad.cuenta_id:
        return []
    return list(
        db.execute(
            _firmadas(oportunidad.tenant_id)
            .where(
                LeccionOportunidad.cuenta_id == oportunidad.cuenta_id,
                LeccionOportunidad.oportunidad_id != oportunidad.id,
            )
            .order_by(LeccionOportunidad.cerrada_el.desc())
            .limit(tope)
        ).scalars()
    )


def _texto_de_la_oportunidad(db: Session, oportunidad: Any) -> str:
    """Lo que se le pregunta al índice: de qué va esta venta."""
    from services.sales.modelos import Etapa, LineaOportunidad

    etapa = db.get(Etapa, oportunidad.etapa_id) if oportunidad.etapa_id else None
    lineas = db.execute(
        select(LineaOportunidad.descripcion).where(
            LineaOportunidad.oportunidad_id == oportunidad.id
        )
    ).scalars()
    partes = [
        oportunidad.nombre or "",
        oportunidad.descripcion or "",
        f"Etapa: {etapa.nombre}" if etapa else "",
        "Líneas: " + ", ".join(lineas),
    ]
    return "\n".join(p for p in partes if p and p != "Líneas: ")


def parecidas(
    db: Session,
    oportunidad: Any,
    principal: Any,
    *,
    tope: int,
    minimo: float,
    excluir: set[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Las firmadas de otros clientes que se parecen por significado.

    Se le preguntan a intelligence **con la identidad de quien mira**, y cada
    una se vuelve a cargar de esta base y por el cargador de la lección, que
    pasa por la política de su oportunidad: el índice dice qué se parece, no
    quién puede verlo. Lo que no se puede ver no sale ni se cuenta.
    """
    from crmcore import ia_ficha

    from services.sales import lecciones as lec

    try:
        datos = ia_ficha.pedir(
            "/api/v1/ia/indice/buscar",
            {
                "texto": _texto_de_la_oportunidad(db, oportunidad),
                "fuentes": ["leccion"],
                # Más candidatas que el tope: el umbral y la visibilidad se
                # aplican después y dejan fuera a una parte.
                "tope": min(200, tope * 4),
            },
            principal,
        )
    except CrmError as exc:
        return [], {"usada": False, "porque": str(exc)[:300]}
    candidatas = [i for i in (datos or {}).get("items", []) if isinstance(i, dict)]
    salida: list[dict[str, Any]] = []
    for item in candidatas:
        referencia = str(item.get("referencia") or "")
        parecido = float(item.get("parecido") or 0)
        if parecido < minimo or referencia in excluir:
            continue
        try:
            fila = lec.leccion(db, UUID(referencia))
        except (CrmError, ValueError):
            continue
        if fila.estado != "firmada" or fila.oportunidad_id == oportunidad.id:
            continue
        salida.append(_como_consejo(fila, "parecida", parecido))
        excluir.add(referencia)
        if len(salida) >= tope:
            break
    return salida, {"usada": True, "candidatas": len(candidatas), "minimo": minimo}


def consejos(db: Session, oportunidad_id: UUID, principal: Any) -> dict[str, Any]:
    """Las lecciones que vienen a cuento para esta oportunidad, y los avisos."""
    from crmcore.runtime.settings import efectivo

    from services.sales.servicio import _oportunidad

    op = _oportunidad(db, oportunidad_id)
    tope = int(efectivo("lecciones_consejos_max", db))
    minimo = float(efectivo("lecciones_parecido_minimo", db))
    mismas = [_como_consejo(f, "mismo_cliente") for f in del_mismo_cliente(db, op, tope)]
    vistas = {m["id"] for m in mismas}
    otras, semantica = parecidas(db, op, principal, tope=tope, minimo=minimo, excluir=vistas)
    return {
        "oportunidad_id": str(op.id),
        "mismo_cliente": mismas,
        "parecidas": otras,
        "busqueda_por_significado": semantica,
        "avisos": [_aviso_a_dict(a) for a in avisos_de(db, op.id)],
    }


def consejos_ia(db: Session, oportunidad_id: UUID, principal: Any) -> dict[str, Any]:
    """«Haz esto / no hagas esto», sacado de las lecciones y citándolas."""
    from crmcore import ia_ficha

    base = consejos(db, oportunidad_id, principal)
    lecciones = base["mismo_cliente"] + base["parecidas"]
    if not lecciones:
        # Sin lecciones no se llama al modelo: escribiría consejos de manual,
        # y parecerían salir de la experiencia de la empresa.
        return {
            "consejos": [],
            "descartados": 0,
            "porque": "Ninguna lección firmada viene a cuento para esta oportunidad.",
        }
    from services.sales.modelos import Oportunidad

    op = db.get(Oportunidad, oportunidad_id)
    salida = ia_ficha.pedir(
        "/api/v1/ia/generar",
        {
            "plantilla": "consejos_lecciones",
            "datos": {"nombre": (op.nombre if op else "") or "la oportunidad"},
            "contexto": [
                {
                    "texto": json.dumps(lc, ensure_ascii=False, default=str),
                    "fuente": "leccion",
                    "id": lc["id"],
                    "permiso": "opportunity:read",
                    "sensibilidad": "interno",
                }
                for lc in lecciones
            ],
            "objeto": "oportunidad",
            "objeto_id": str(oportunidad_id),
        },
        principal,
    )
    validos = {lc["id"]: lc for lc in lecciones}
    lista, descartados = leer_consejos(str((salida or {}).get("texto") or ""), set(validos))
    for c in lista:
        c["leccion"] = {k: validos[c["leccion_id"]][k] for k in ("titulo", "resultado", "por_que")}
    return {
        "consejos": lista,
        "descartados": descartados,
        "propuesta_id": (salida or {}).get("propuesta_id"),
    }


def leer_consejos(texto: str, validos: set[str]) -> tuple[list[dict[str, Any]], int]:
    """Los consejos del modelo que se pueden atribuir a una lección dada.

    Devuelve también cuántos se descartaron, para decirlo: «la IA propuso 6 y
    2 no salían de ninguna lección» es información, no un error.
    """
    bloque = re.search(r"\[.*\]", texto, re.S)
    if not bloque:
        return [], 0
    try:
        crudo = json.loads(bloque.group(0))
    except ValueError:
        return [], 0
    buenos: list[dict[str, Any]] = []
    descartados = 0
    for c in crudo if isinstance(crudo, list) else []:
        if (
            isinstance(c, dict)
            and c.get("tipo") in TIPOS_DE_CONSEJO
            and str(c.get("texto") or "").strip()
            and str(c.get("leccion_id") or "") in validos
        ):
            buenos.append(
                {
                    "tipo": c["tipo"],
                    "texto": str(c["texto"]).strip(),
                    "leccion_id": str(c["leccion_id"]),
                }
            )
        else:
            descartados += 1
    return buenos, descartados


# ── El índice ─────────────────────────────────────────────────────────────


def _texto_indexable(fila: LeccionOportunidad) -> str:
    senales = [s.get("texto", "") for s in (fila.hechos or {}).get("senales") or []]
    partes = [
        f"{'Ganada' if fila.resultado == 'ganada' else 'Perdida'}"
        + (f" por {fila.motivo}" if fila.motivo else ""),
        f"Qué pasó: {fila.que_paso or ''}",
        f"Señal temprana: {fila.senal_temprana or ''}",
        f"Qué haríamos distinto: {fila.que_hariamos_distinto or ''}",
        "Factores: " + ", ".join(f for f in fila.factores or [] if f in FACTORES),
        "Señales: " + " ".join(senales),
    ]
    return "\n".join(partes)


def indexar(fila: LeccionOportunidad, principal: Any) -> dict[str, Any]:
    """Manda una lección firmada al índice de intelligence, como quien firma.

    Se hace al firmar y no por evento: el texto de la lección es interno —lleva
    qué pasó con un cliente— y un evento lo dejaría en el bus y en los
    webhooks. Si intelligence no contesta, la firma sigue y se dice; reindexar
    lo recoge después.
    """
    from crmcore import ia_ficha

    try:
        ia_ficha.pedir(
            "/api/v1/ia/indice/indexar",
            {
                "fuente": "leccion",
                "referencia": str(fila.id),
                "titulo": fila.titulo or "",
                "texto": _texto_indexable(fila),
            },
            principal,
        )
    except CrmError as exc:
        logger.warning("leccion.no_indexada", leccion_id=str(fila.id), motivo=str(exc)[:200])
        return {"indexada": False, "porque": str(exc)[:300]}
    return {"indexada": True}


def indexar_firmadas(db: Session, tenant_id: UUID, principal: Any) -> dict[str, Any]:
    """Todas las firmadas al índice: las de antes y las que no llegaron."""
    hechas, fallos = 0, []
    for fila in db.execute(_firmadas(tenant_id)).scalars():
        r = indexar(fila, principal)
        if r["indexada"]:
            hechas += 1
        else:
            fallos.append({"leccion_id": str(fila.id), "porque": r["porque"]})
            if len(fallos) >= 3 and hechas == 0:
                # Tres seguidas sin una buena es que intelligence no está: seguir
                # sólo multiplicaría el mismo error por cada lección.
                break
    return {"indexadas": hechas, "fallidas": fallos}


# ── Los avisos ────────────────────────────────────────────────────────────


def avisos_de(db: Session, oportunidad_id: UUID) -> list[AvisoLeccion]:
    return list(
        db.execute(
            select(AvisoLeccion)
            .where(AvisoLeccion.oportunidad_id == oportunidad_id)
            .order_by(AvisoLeccion.updated_at.desc())
        ).scalars()
    )


def _aviso_a_dict(a: AvisoLeccion) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "momento": a.momento,
        "clave": a.clave,
        "titulo": a.titulo,
        "detalle": a.detalle,
        "lecciones": a.lecciones or [],
        "cuando": (a.updated_at or a.created_at).isoformat() if a.created_at else None,
    }


def _perdidas_en_etapa(db: Session, tenant_id: UUID, etapa: str) -> list[LeccionOportunidad]:
    """Las perdidas firmadas cuya última etapa antes de perderse fue ésta."""
    salida = []
    for fila in db.execute(
        _firmadas(tenant_id).where(LeccionOportunidad.resultado == "perdida")
    ).scalars():
        recorrido = (fila.hechos or {}).get("recorrido") or []
        ultima = next((p.get("desde") for p in reversed(recorrido) if p.get("desde")), None)
        if ultima == etapa:
            salida.append(fila)
    return salida


def _legibles(factores: list[str]) -> str:
    return ", ".join(ROTULO_FACTOR.get(f, f.replace("_", " ")) for f in factores)


def _n(cuantas: int, una: str, varias: str) -> str:
    return f"{cuantas} {una if cuantas == 1 else varias}"


def _factores_que_mas_pesan(filas: list[LeccionOportunidad], cuantos: int = 3) -> list[str]:
    cuenta: dict[str, int] = {}
    for f in filas:
        for factor in f.factores or []:
            cuenta[factor] = cuenta.get(factor, 0) + 1
    return [f for f, _ in sorted(cuenta.items(), key=lambda x: -x[1])[:cuantos]]


def avisar_en(
    uow: UnidadDeTrabajo,
    oportunidad: Any,
    momento: str,
    *,
    clave: str = "",
    etapa: str | None = None,
    descuento: float | None = None,
) -> AvisoLeccion | None:
    """El aviso de un momento clave, si alguna lección tiene algo que decir."""
    from crmcore.runtime.settings import efectivo

    from services.sales import lecciones as lec

    db = uow.db
    tope = int(efectivo("lecciones_consejos_max", db))
    lineas: list[str] = []
    citadas: dict[str, dict[str, Any]] = {}

    mismas = del_mismo_cliente(db, oportunidad, tope)
    if mismas:
        perdidas = [m for m in mismas if m.resultado == "perdida"]
        lineas.append(
            f"Con este cliente hay {_n(len(mismas), 'lección firmada', 'lecciones firmadas')}"
            + (
                (", de una venta perdida" if len(mismas) == 1 else ", una de una venta perdida")
                if len(perdidas) == 1
                else (f", {len(perdidas)} de ventas perdidas" if perdidas else "")
            )
            + ". Lo que se haría distinto: "
            + " · ".join(m.que_hariamos_distinto for m in mismas[:2] if m.que_hariamos_distinto)
        )
        for m in mismas:
            citadas[str(m.id)] = _como_consejo(m, "mismo_cliente")

    if momento == "etapa" and etapa:
        aqui = _perdidas_en_etapa(db, oportunidad.tenant_id, etapa)
        if aqui:
            factores = _factores_que_mas_pesan(aqui)
            perdidas_aqui = (
                "se ha perdido una oportunidad"
                if len(aqui) == 1
                else f"se han perdido {len(aqui)} oportunidades"
            )
            lineas.append(
                f"En «{etapa}» {perdidas_aqui} con lección firmada"
                + (f"; lo que más pesó: {_legibles(factores)}" if factores else "")
                + "."
            )
            for m in aqui[:tope]:
                citadas.setdefault(str(m.id), _como_consejo(m, "misma_etapa"))

    if momento == "presupuesto" and descuento is not None:
        u = lec.umbrales(db)
        ref = lec._referencia_ganadas(db, oportunidad, u)
        normal = ref.get("mediana_descuento_pct")
        if ref.get("comparable") and normal is not None:
            margen = float(u["descuento_margen_pp"])
            if descuento > float(normal) + margen:
                lineas.append(
                    f"Este presupuesto lleva un descuento del {descuento:g} %; las ganadas "
                    f"del mismo embudo se cerraron con un {float(normal):g} % de mediana."
                )

    if not lineas:
        return None
    titulos = {
        "creacion": "Las lecciones tienen algo que decir de esta oportunidad",
        "etapa": f"Al entrar en «{etapa}»: lo que dicen las lecciones",
        "presupuesto": "Antes de mandar el presupuesto: lo que dicen las lecciones",
    }
    aviso = db.execute(
        select(AvisoLeccion).where(
            AvisoLeccion.tenant_id == uow.tenant_id,
            AvisoLeccion.oportunidad_id == oportunidad.id,
            AvisoLeccion.momento == momento,
            AvisoLeccion.clave == clave,
        )
    ).scalar_one_or_none()
    if aviso is None:
        aviso = AvisoLeccion(
            tenant_id=uow.tenant_id, oportunidad_id=oportunidad.id, momento=momento, clave=clave
        )
        db.add(aviso)
    aviso.owner_id = oportunidad.owner_id
    aviso.titulo = titulos.get(momento, "Lo que dicen las lecciones")[:300]
    aviso.detalle = "\n".join(lineas)
    aviso.lecciones = list(citadas.values())
    aviso.updated_at = datetime.now(timezone.utc)
    db.flush()
    uow.emitir(
        "opportunity.lesson.advice",
        subject=("oportunidad", oportunidad.id),
        data={
            "oportunidad_id": str(oportunidad.id),
            "aviso_id": str(aviso.id),
            "momento": momento,
            "titulo": aviso.titulo,
            "detalle": aviso.detalle,
            "owner_id": str(oportunidad.owner_id) if oportunidad.owner_id else "",
        },
    )
    return aviso


# ── El resumen ────────────────────────────────────────────────────────────


def resumen(uow: UnidadDeTrabajo, *, hoy: date, forzar: bool = False) -> ResumenLecciones | None:
    """El resumen del periodo, si toca y si hay algo que contar.

    Toca cuando el último es de hace `lecciones_resumen_dias` o más; `forzar`
    lo genera ya (el botón «Generar ahora»), pero tampoco repite el mismo día.
    Sin nada en el periodo y sin nada pendiente no se genera: un resumen de
    ceros cada semana es el correo que se aprende a borrar sin abrir.
    """
    from crmcore.authz.jerarquia import MandoReplicado
    from crmcore.runtime.settings import efectivo

    db = uow.db
    tenant_id = uow.tenant_id
    dias = int(efectivo("lecciones_resumen_dias", db))
    ultimo = db.execute(
        select(func.max(ResumenLecciones.hasta)).where(ResumenLecciones.tenant_id == tenant_id)
    ).scalar()
    if ultimo is not None and (ultimo >= hoy or (not forzar and (hoy - ultimo).days < dias)):
        return None
    desde = max(ultimo, hoy - timedelta(days=dias)) if ultimo else hoy - timedelta(days=dias)

    todas = list(
        db.execute(
            select(LeccionOportunidad).where(LeccionOportunidad.tenant_id == tenant_id)
        ).scalars()
    )
    firmadas = [
        f
        for f in todas
        if f.estado == "firmada" and f.firmada_at and desde < f.firmada_at.date() <= hoy
    ]
    cerradas = [f for f in todas if f.cerrada_el and desde < f.cerrada_el <= hoy]
    pendientes = [f for f in todas if f.estado == "pendiente" and f.obligatoria]
    if not (firmadas or cerradas or pendientes):
        return None

    por_responsable: dict[str, int] = {}
    for f in pendientes:
        clave = str(f.responsable_id) if f.responsable_id else "sin_responsable"
        por_responsable[clave] = por_responsable.get(clave, 0) + 1
    datos = {
        "firmadas": len(firmadas),
        "perdidas_cerradas": sum(1 for f in cerradas if f.resultado == "perdida"),
        "ganadas_cerradas": sum(1 for f in cerradas if f.resultado == "ganada"),
        "pendientes_obligatorias": len(pendientes),
        "factores_de_lo_firmado": _factores_que_mas_pesan(firmadas, 5),
        "pendientes_por_responsable": por_responsable,
    }

    # A quién: a quien dirige a los que tienen lecciones en el periodo o por
    # firmar. Sin jerarquía replicada, a ellos mismos: que llegue a alguien.
    implicados = {f.responsable_id for f in cerradas + pendientes + firmadas if f.responsable_id}
    mandos = (
        set(
            db.execute(
                select(MandoReplicado.superior_id).where(
                    MandoReplicado.tenant_id == tenant_id,
                    MandoReplicado.usuario_id.in_(implicados),
                    MandoReplicado.superior_id.is_not(None),
                )
            ).scalars()
        )
        if implicados
        else set()
    )
    destinatarios = sorted(str(d) for d in (mandos or implicados))

    detalle = (
        f"Del {desde.isoformat()} al {hoy.isoformat()}: {datos['firmadas']} lecciones "
        f"firmadas, {datos['perdidas_cerradas']} perdidas y {datos['ganadas_cerradas']} "
        f"ganadas cerradas. Quedan {datos['pendientes_obligatorias']} post-mortem "
        "obligatorios por firmar."
        + (
            " Lo que más se repite en lo firmado: "
            + _legibles(datos["factores_de_lo_firmado"])
            + "."
            if datos["factores_de_lo_firmado"]
            else ""
        )
    )
    fila = ResumenLecciones(
        tenant_id=tenant_id,
        desde=desde,
        hasta=hoy,
        titulo=f"Lecciones aprendidas: del {desde.isoformat()} al {hoy.isoformat()}",
        detalle=detalle,
        datos=datos,
        destinatarios=destinatarios,
        enviado_at=datetime.now(timezone.utc) if destinatarios else None,
    )
    db.add(fila)
    db.flush()
    if destinatarios:
        uow.emitir(
            "opportunity.lessons.summary",
            subject=("resumen_lecciones", fila.id),
            data={
                "resumen_id": str(fila.id),
                "titulo": fila.titulo,
                "detalle": detalle,
                "destinatarios": destinatarios,
            },
        )
    return fila


def tenants_con_lecciones() -> list[Any]:
    """Los tenants con alguna lección, de la propia tabla de sales."""
    from crmcore.db.session import sesion

    with sesion(sistema=True) as db:
        return [t for (t,) in db.execute(select(LeccionOportunidad.tenant_id).distinct()).all()]
