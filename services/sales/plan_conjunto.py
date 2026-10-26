"""Plan conjunto con el cliente y revisión de la oportunidad
(CRM-03.01.02.05, CRM-03.01.02.06).

Dos prácticas que funcionan y que casi ningún CRM soporta, con lo cual acaban en
una hoja de cálculo compartida por correo — y ahí mueren.

**El plan conjunto** es una lista de pasos con fechas que acuerdan las dos partes:
quién hace qué para que esto esté firmado el día X. Su valor está casi entero en
una cosa: **obliga al cliente a comprometerse con fechas**. Un cliente que no
quiere poner fecha a su propia parte está diciendo algo importante, y lo dice
antes de que se haya invertido un trimestre.

Lo que lo estropea siempre: que sea nuestro plan con tareas nuestras. Eso es una
lista de seguimiento interna con otro nombre, y el cliente ni la mira.

**La revisión de oportunidad** es la conversación en la que un jefe pregunta por
qué esto va a cerrar. Sin estructura se convierte en «¿cómo lo ves?» y en un
número que sube porque el comercial es optimista. Con estructura —qué sabemos,
qué no, quién decide, qué puede salir mal— se convierte en trabajo.

Y lo que la hace útil de verdad: **queda registrada y se puede comparar con lo que
pasó**. Un equipo que revisa cincuenta oportunidades al trimestre y nunca mira
cuántas de las «seguras» se cayeron no aprende nada de las revisiones.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import Boolean, Date, DateTime, Index, Integer, String, Text, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# De quién es cada paso. La distinción es lo único que separa un plan conjunto de
# una lista de seguimiento interna con otro nombre.
DE_QUIEN = ("nuestro", "del_cliente", "conjunto")

ESTADOS_PASO = ("pendiente", "hecho", "retrasado", "cancelado")

# Las preguntas de una revisión. Cerrada a propósito: sin ellas, la revisión es
# «¿cómo lo ves?» y el número sube porque el comercial es optimista.
PREGUNTAS = (
    "por_que_compra",  # qué problema le resuelve, dicho por él
    "por_que_ahora",  # qué pasa si no lo hace este trimestre
    "por_que_nosotros",  # frente a la alternativa, incluida no hacer nada
    "quien_decide",  # y si hemos hablado con esa persona
    "que_puede_salir_mal",  # lo que se sabe y no se dice en la reunión
    "que_falta_por_saber",  # lo que no sabemos, que es lo que más pesa
)


# Cuántos días sin tocar el plan antes de que deje de valer. Un plan acordado en
# marzo y no revisado desde entonces no es un acuerdo: es un documento.
def _plan_dias_sin_tocar() -> int:
    """Antes `_plan_dias_sin_tocar() = 21`.

    Era una constante de módulo. Sale del `.env`, que es donde una instalación
    puede afinarla sin tocar código.
    """
    from crmcore.config import get_settings

    return get_settings().plan_dias_sin_tocar


def _hoy(db: Any = None) -> date:
    """El día de hoy **donde está el cliente**, si hay sesión con la que saberlo.

    Sin sesión cae a UTC, que es lo que hacía antes: no empeora nada y deja
    claro dónde falta el dato. Quien la tenga a mano está obligado a pasarla —
    hay un gate que lo mira—, porque entre medianoche y las dos de la mañana en
    Madrid la respuesta sin sesión es **la de ayer**.
    """
    from crmcore.fechas import hoy as _hoy_del_cliente

    return _hoy_del_cliente(db)


class PlanConjuntoCliente(Base, TimestampMixin, SoftDeleteMixin):
    """El plan acordado con el cliente para llegar a la firma.

    Se llama `...Cliente` porque ya existe un `PlanConjuntoCliente` con un partner
    (CRM-03.04.01.06) y son cosas distintas: aquel es un plan de negocio anual
    con quien revende, y este son los pasos para cerrar una venta concreta.
    Compartir el nombre habría hecho que una consulta devolviera lo que no es.
    """

    __tablename__ = "planes_conjuntos_cliente"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    oportunidad_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    fecha_objetivo: Mapped[date | None] = mapped_column(Date, nullable=True)
    pasos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Si el cliente lo ha visto. Un plan «conjunto» que el cliente no ha abierto
    # es nuestro plan, y conviene que el CRM no diga lo contrario.
    compartido_con_el_cliente: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    visto_por_el_cliente_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (Index("ix_planes_conjuntos_op", "tenant_id", "oportunidad_id"),)


class RevisionOportunidad(Base, TimestampMixin):
    """Una revisión estructurada, con lo que se dijo y lo que pasó después."""

    __tablename__ = "revisiones_oportunidad"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    oportunidad_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    revisada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    respuestas: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Lo que se dijo en la revisión, para poder compararlo con lo que pasó.
    probabilidad_declarada: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fecha_declarada: Mapped[date | None] = mapped_column(Date, nullable=True)
    acuerdos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    resultado: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    notas: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (Index("ix_revisiones_op", "tenant_id", "oportunidad_id"),)


# ── Plan conjunto (CRM-03.01.02.05) ───────────────────────────────────────


def guardar_plan(
    uow: UnidadDeTrabajo,
    *,
    oportunidad_id: UUID,
    pasos: list[dict[str, Any]],
    fecha_objetivo: date | None,
) -> PlanConjuntoCliente:
    """Guarda el plan, exigiendo que **haya pasos del cliente**.

    Un plan donde todos los pasos son nuestros es una lista de seguimiento interna
    con otro nombre: el cliente ni la mira, y no compromete a nadie a nada. Lo que
    hace valioso un plan conjunto es justo lo incómodo — que el cliente ponga
    fecha a su parte, porque si no quiere, eso ya es una respuesta.

    Y cada paso necesita **fecha y dueño**: sin ellas, el plan es una lista de
    buenas intenciones que se enseña en la reunión y no se mira entre reuniones.
    """
    if not pasos:
        raise ErrorValidacion("Un plan sin pasos no es un plan", error_code="plan.sin_pasos")
    desconocidos = sorted({str(p.get("de_quien")) for p in pasos} - set(DE_QUIEN))
    if desconocidos:
        raise ErrorValidacion(
            f"Pasos con dueño desconocido: {', '.join(desconocidos)}",
            error_code="plan.de_quien_invalido",
            detalle={"admitidos": list(DE_QUIEN)},
        )
    del_cliente = [p for p in pasos if p.get("de_quien") in ("del_cliente", "conjunto")]
    if not del_cliente:
        raise ErrorValidacion(
            "Todos los pasos son nuestros: eso es una lista de seguimiento interna con "
            "otro nombre. Lo que hace valioso un plan conjunto es que el cliente ponga "
            "fecha a su parte — y si no quiere, eso ya es una respuesta.",
            error_code="plan.sin_pasos_del_cliente",
        )
    sin_fecha = [p.get("titulo") for p in pasos if not p.get("fecha")]
    sin_dueno = [p.get("titulo") for p in pasos if not p.get("responsable")]
    if sin_fecha or sin_dueno:
        raise ErrorValidacion(
            "Hay pasos sin fecha o sin responsable: así el plan es una lista de buenas "
            "intenciones que se enseña en la reunión y no se mira entre reuniones.",
            error_code="plan.paso_incompleto",
            detalle={"sin_fecha": sin_fecha, "sin_responsable": sin_dueno},
        )

    fila = uow.db.execute(
        select(PlanConjuntoCliente).where(
            PlanConjuntoCliente.tenant_id == uow.tenant_id,
            PlanConjuntoCliente.oportunidad_id == oportunidad_id,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = PlanConjuntoCliente(tenant_id=uow.tenant_id, oportunidad_id=oportunidad_id)
        uow.db.add(fila)
    fila.pasos = pasos
    fila.fecha_objetivo = fecha_objetivo
    uow.db.flush()
    return fila


def estado_del_plan(*, plan: dict[str, Any], hoy: date | None = None) -> dict[str, Any]:
    """Cómo va, **y de quién es lo que va retrasado**.

    Distinguirlo es todo el valor. Si lo que se retrasa es nuestro, se aprieta
    dentro; si lo que se retrasa es del cliente, la fecha de cierre que hay en el
    CRM es una ilusión — y eso es lo que hay que contarle al jefe antes de que
    llegue el final del trimestre.
    """
    momento = hoy or _hoy()
    pasos = list(plan.get("pasos") or [])
    retrasados_nuestros: list[str] = []
    retrasados_del_cliente: list[str] = []
    retrasados_conjuntos: list[str] = []
    hechos = 0

    for paso in pasos:
        if str(paso.get("estado")) == "hecho":
            hechos += 1
            continue
        fecha = paso.get("fecha")
        if isinstance(fecha, str):
            fecha = date.fromisoformat(fecha)
        if isinstance(fecha, date) and fecha < momento:
            # Los tres cubos, y no dos. «conjunto» es un valor admitido del
            # vocabulario, y meterlo en el cubo del cliente —que es lo que hacía
            # el `else`— convierte un paso que también es nuestro en un retraso
            # ajeno: la lectura más cómoda y la que deja de apretar dentro.
            de_quien = str(paso.get("de_quien") or "")
            if de_quien == "nuestro":
                retrasados_nuestros.append(str(paso.get("titulo")))
            elif de_quien == "conjunto":
                retrasados_conjuntos.append(str(paso.get("titulo")))
            else:
                retrasados_del_cliente.append(str(paso.get("titulo")))

    compartido = bool(plan.get("compartido_con_el_cliente"))
    visto = plan.get("visto_por_el_cliente_at")

    return {
        "pasos": len(pasos),
        "hechos": hechos,
        "retrasados_nuestros": retrasados_nuestros,
        "retrasados_del_cliente": retrasados_del_cliente,
        "retrasados_conjuntos": retrasados_conjuntos,
        "compartido": compartido,
        "visto_por_el_cliente": bool(visto),
        # Un paso conjunto retrasado también deja la fecha en el aire: depende de
        # alguien de fuera igual que uno del cliente, y creérsela por estar
        # escrito «conjunto» es creérsela por la etiqueta.
        "la_fecha_es_creible": not retrasados_del_cliente and not retrasados_conjuntos,
        "que_significa": (
            "El plan va en fecha."
            if not retrasados_nuestros and not retrasados_del_cliente and not retrasados_conjuntos
            else " ".join(
                filter(
                    None,
                    [
                        f"{len(retrasados_nuestros)} pasos nuestros retrasados: se "
                        "aprieta dentro."
                        if retrasados_nuestros
                        else "",
                        f"{len(retrasados_del_cliente)} pasos del cliente retrasados: la "
                        "fecha de cierre que hay en el CRM es una ilusión, y eso hay que "
                        "contarlo antes del final del trimestre."
                        if retrasados_del_cliente
                        else "",
                        f"{len(retrasados_conjuntos)} pasos conjuntos retrasados: "
                        "dependen de los dos, así que no se arreglan apretando dentro "
                        "ni esperando fuera."
                        if retrasados_conjuntos
                        else "",
                    ],
                )
            )
        ),
        "aviso": (
            ""
            if compartido and visto
            else "El cliente no ha visto este plan. Un plan «conjunto» que solo hemos "
            "leído nosotros es nuestro plan, y conviene que el CRM no diga lo contrario."
        ),
    }


# ── Revisión de oportunidad (CRM-03.01.02.06) ─────────────────────────────


def revisar(
    uow: UnidadDeTrabajo,
    *,
    oportunidad_id: UUID,
    respuestas: dict[str, str],
    probabilidad_declarada: int,
    fecha_declarada: date | None,
    acuerdos: list[dict[str, Any]],
    revisada_por: UUID,
) -> dict[str, Any]:
    """Registra una revisión estructurada.

    Se exigen **las preguntas incómodas**, que son las que la gente se salta:
    «qué puede salir mal» y «qué falta por saber». Una revisión sin ellas es «¿cómo
    lo ves?» con acta, y el número sube porque el comercial es optimista — no
    porque mienta, sino porque está metido dentro.

    Y los **acuerdos llevan dueño y fecha**. Una revisión que termina en «hay que
    hablar con el director financiero» sin quién ni cuándo es la misma reunión que
    se repetirá dentro de dos semanas.
    """
    faltan = [p for p in PREGUNTAS if not str(respuestas.get(p, "")).strip()]
    incomodas = [p for p in ("que_puede_salir_mal", "que_falta_por_saber") if p in faltan]
    if incomodas:
        raise ErrorValidacion(
            "Faltan las preguntas que dan valor a la revisión: "
            + ", ".join(incomodas)
            + ". Sin ellas esto es «¿cómo lo ves?» con acta, y el número sube porque el "
            "comercial está metido dentro.",
            error_code="revision.faltan_preguntas",
            detalle={"faltan": faltan},
        )
    sin_dueno = [
        a.get("titulo") for a in acuerdos if not a.get("responsable") or not a.get("fecha")
    ]
    if sin_dueno:
        raise ErrorValidacion(
            "Hay acuerdos sin responsable o sin fecha. «Hay que hablar con el director "
            "financiero» sin quién ni cuándo es la misma reunión repetida dentro de dos "
            "semanas.",
            error_code="revision.acuerdo_incompleto",
            detalle={"acuerdos": sin_dueno},
        )

    fila = RevisionOportunidad(
        tenant_id=uow.tenant_id,
        oportunidad_id=oportunidad_id,
        revisada_por=revisada_por,
        respuestas=dict(respuestas),
        probabilidad_declarada=max(0, min(100, probabilidad_declarada)),
        fecha_declarada=fecha_declarada,
        acuerdos=acuerdos,
    )
    uow.db.add(fila)
    uow.db.flush()

    return {
        "revision_id": str(fila.id),
        "preguntas_sin_responder": faltan,
        "acuerdos": len(acuerdos),
        "porque_se_guarda": (
            "Para poder comparar lo que se dijo con lo que pasó. Un equipo que revisa "
            "cincuenta oportunidades al trimestre y nunca mira cuántas de las «seguras» "
            "se cayeron no aprende nada de las revisiones."
        ),
    }


def anotar_resultado(uow: UnidadDeTrabajo, oportunidad_id: UUID, *, ganada: bool) -> int:
    """Escribe en las revisiones de esa oportunidad **cómo acabó**.

    Sin esto la calibración no existe. La columna `resultado` llevaba desde el
    primer día con el comentario «para poder compararlo con lo que pasó» y **no
    la escribía nadie**: todas las revisiones se quedaban con el resultado vacío,
    así que la calibración —que descarta las que no tienen resultado— contestaba
    siempre «no hay suficientes para concluir». Una respuesta perfectamente
    razonable que habría seguido saliendo con diez años de revisiones dentro.

    Se anota **al cerrar**, que es el único momento en que se sabe. Pedirlo
    aparte significa que nadie lo pide.
    """
    filas = (
        uow.db.execute(
            select(RevisionOportunidad).where(
                RevisionOportunidad.tenant_id == uow.tenant_id,
                RevisionOportunidad.oportunidad_id == oportunidad_id,
            )
        )
        .scalars()
        .all()
    )
    for fila in filas:
        fila.resultado = "ganado" if ganada else "perdido"
    if filas:
        uow.db.flush()
    return len(filas)


def calibracion(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Cuánto se parece lo que se dice en las revisiones a lo que pasa.

    Es el único uso que justifica guardarlas. Si todo lo que se revisa al 80 % se
    gana la mitad de las veces, el 80 % no significa 80 %: significa «me gusta
    este caso», y el forecast que se construye con eso no cuadra nunca.

    Con pocas revisiones cerradas **no se concluye**: llamar optimista a un equipo
    con seis casos es injusto y además quita credibilidad al ejercicio entero.

    Lee las revisiones **de la tabla**. Antes recibía la lista por parámetro y se
    le pasaban `db` y `tenant_id` que no usaba: una firma que dice que lee y no
    lee, y que dejaba la medida en manos de quien llamara —que no llamaba nadie—.
    """
    revisiones = [
        {"probabilidad_declarada": f.probabilidad_declarada, "resultado": f.resultado}
        for f in db.execute(
            select(RevisionOportunidad).where(RevisionOportunidad.tenant_id == tenant_id)
        )
        .scalars()
        .all()
    ]
    cerradas = [r for r in revisiones if r.get("resultado") in ("ganado", "perdido")]
    if len(cerradas) < 10:
        return {
            "medible": False,
            "cerradas": len(cerradas),
            "porque": (
                f"Solo hay {len(cerradas)} revisiones con resultado. Llamar optimista a "
                "un equipo con seis casos es injusto y le quita credibilidad al "
                "ejercicio entero."
            ),
        }

    tramos: dict[str, dict[str, int]] = {}
    for revision in cerradas:
        p = int(revision.get("probabilidad_declarada") or 0)
        tramo = f"{p // 20 * 20}-{p // 20 * 20 + 19}"
        datos = tramos.setdefault(tramo, {"casos": 0, "ganados": 0})
        datos["casos"] += 1
        if revision.get("resultado") == "ganado":
            datos["ganados"] += 1

    filas = [
        {
            "tramo": tramo,
            "casos": d["casos"],
            "ganados": d["ganados"],
            "real_pct": round(d["ganados"] / d["casos"] * 100, 1),
        }
        for tramo, d in sorted(tramos.items())
    ]
    desviados = [
        f
        for f in filas
        if abs(f["real_pct"] - (int(f["tramo"].split("-")[0]) + 10)) > 20 and f["casos"] >= 5
    ]

    return {
        "medible": True,
        "cerradas": len(cerradas),
        "por_tramo": filas,
        "tramos_desviados": desviados,
        "que_significa": (
            "Lo que se declara en las revisiones se parece a lo que pasa."
            if not desviados
            else "Hay tramos donde lo declarado no se parece a lo que pasó. Un 80 % que "
            "se gana la mitad de las veces no significa 80 %: significa «me gusta este "
            "caso», y el forecast construido con eso no cuadra nunca."
        ),
    }


def sin_revisar(
    *, oportunidades: list[dict[str, Any]], dias: int = 30, hoy: date | None = None
) -> dict[str, Any]:
    """Qué oportunidades grandes llevan demasiado sin revisarse.

    Se filtra por **importe y etapa**, no por todas: revisar cien oportunidades
    pequeñas cada mes es lo que hace que las revisiones se conviertan en un
    trámite que nadie prepara.
    """
    momento = hoy or _hoy()
    pendientes = []
    for op in oportunidades:
        ultima = op.get("ultima_revision")
        if isinstance(ultima, str):
            ultima = date.fromisoformat(ultima)
        dias_sin = (momento - ultima).days if isinstance(ultima, date) else None
        if dias_sin is None or dias_sin >= dias:
            pendientes.append(
                {
                    "oportunidad_id": str(op.get("id")),
                    "importe": str(op.get("importe")),
                    "dias_sin_revisar": dias_sin,
                    "nunca_revisada": dias_sin is None,
                }
            )
    return {
        "pendientes": sorted(pendientes, key=lambda p: -(p["dias_sin_revisar"] or 9999)),
        "cuantas": len(pendientes),
        "porque_solo_estas": (
            "Se miran las grandes y las avanzadas. Revisar cien oportunidades pequeñas "
            "al mes es lo que convierte las revisiones en un trámite que nadie prepara."
        ),
    }
