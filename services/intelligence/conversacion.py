"""Señales sobre la conversación: resumen, sentimiento e intención
(CRM-04.02.02.06 y CRM-04.02.02.07).

Estas dos cosas se usan en caliente, con el cliente al otro lado, y por eso son
las más fáciles de estropear. Un resumen que se inventa un compromiso hace que el
agente que recoge el caso prometa algo que nadie dijo. Un «cliente enfadado» que
salta cada vez que alguien escribe en mayúsculas enseña al supervisor a ignorar
el aviso justo antes del día que importa.

Las decisiones:

**El resumen se propone, no se escribe.** El caso vive en el servicio de
soporte, no aquí. Se devuelve el borrador y se **pide** al dueño que lo guarde;
mientras nadie lo acepta, el estado es «pedido», nunca «hecho».

**Un resumen lleva de dónde sale.** Se guarda sobre cuántos mensajes se hizo y
cuáles, porque un resumen de una conversación de cuarenta mensajes hecho con los
cinco últimos es un resumen del final, y quien lo lea creerá que es del todo.

**El sentimiento se mide con confianza y con umbral.** Por debajo del umbral se
devuelve «no concluyente», que es la respuesta honesta, en vez de un neutro que
se cuenta en las medias y las aplana.

**Nada se escala solo.** La señal avisa; escalar lo decide una regla del cliente
con su umbral configurable, y siempre queda quién lo decidió y por qué.

**Si no hay proveedor, se dice.** El hueco se nota: preferimos una conversación
sin señales a una conversación con señales inventadas.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

from crmcore.db.base import Base
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorDependencia, ErrorValidacion
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

from services.intelligence import enrutador, guardias, uso

logger = get_logger(__name__)

# Sentimientos cerrados. Una escala continua de -1 a 1 suena más fina y no lo es:
# nadie sabe qué hacer con un -0,23.
SENTIMIENTOS = ("muy_negativo", "negativo", "neutro", "positivo", "muy_positivo")

# Intenciones cerradas. Las que el cliente necesite se añaden con su definición;
# una lista abierta acaba con «queja», «reclamacion» y «quejarse» a la vez.
INTENCIONES = (
    "consulta",
    "incidencia",
    "reclamacion",
    "cancelacion",
    "compra",
    "presupuesto",
    "agradecimiento",
    "otro",
)

MOMENTOS = ("cierre", "transferencia", "peticion")

_clasificador: Callable[..., dict[str, Any]] | None = None
_resumidor: Callable[..., dict[str, Any]] | None = None


def registrar_clasificador(fn: Callable[..., dict[str, Any]]) -> None:
    global _clasificador
    _clasificador = fn


def registrar_resumidor(fn: Callable[..., dict[str, Any]]) -> None:
    global _resumidor
    _resumidor = fn


class ResumenConversacion(Base):
    """Un resumen propuesto, con la traza de sobre qué se hizo."""

    __tablename__ = "resumenes_conversacion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    conversacion_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    caso_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    momento: Mapped[str] = mapped_column(
        String(20), nullable=False, default="cierre", info={"opciones": MOMENTOS}
    )
    texto: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Lo que el modelo dice que quedó pendiente. Va aparte del resumen porque es
    # lo que el siguiente agente lee primero, y porque es lo que más se inventa:
    # así se puede revisar sin leer todo.
    pendientes: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # De dónde sale: cuántos mensajes había y cuántos se le dieron al modelo.
    mensajes_totales: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mensajes_usados: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # `parcial` es la diferencia entre un resumen y un resumen del final.
    parcial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # El caso lo escribe el servicio de soporte: aquí solo se pide.
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="propuesto")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_resumenes_conversacion", "tenant_id", "conversacion_id"),)


class SenalConversacion(Base):
    """Sentimiento e intención detectados en un momento de la conversación."""

    __tablename__ = "senales_conversacion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    conversacion_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    sentimiento: Mapped[str] = mapped_column(
        String(20), nullable=False, default="neutro", info={"opciones": SENTIMIENTOS}
    )
    intencion: Mapped[str] = mapped_column(
        String(20), nullable=False, default="otro", info={"opciones": INTENCIONES}
    )
    confianza: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=0)
    # Por debajo del umbral configurado, esto vale False y la señal no se usa
    # para nada automático: es la diferencia entre «neutro» y «no lo sé».
    concluyente: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Las palabras del cliente en las que se apoya. Sin ellas, el supervisor no
    # puede comprobar el aviso y acaba ignorándolo.
    indicios: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    sugiere_escalar: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    porque: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_senales_conversacion", "tenant_id", "conversacion_id", "created_at"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def resumir(
    uow: UnidadDeTrabajo,
    *,
    conversacion_id: UUID,
    mensajes: list[dict[str, Any]],
    momento: str = "cierre",
    caso_id: UUID | None = None,
    mensajes_totales: int | None = None,
    principal: Any = None,
) -> dict[str, Any]:
    """Resume una conversación al cerrarla o al transferirla (CRM-04.02.02.06).

    El resumen se **propone**: el caso vive en el servicio de soporte y este no
    escribe en su esquema. Se devuelve el borrador y el comando que lo guardaría;
    hasta que alguien lo acepta, el estado es «pedido».

    Y se guarda **sobre cuánto se hizo**: un resumen de cuarenta mensajes hecho
    con los cinco últimos es un resumen del final, y quien lo lea sin saberlo
    creerá que tiene toda la conversación.
    """
    if momento not in MOMENTOS:
        raise ErrorValidacion(
            f"Momento '{momento}' no reconocido. Los válidos son {list(MOMENTOS)}.",
            error_code="conversacion.momento_desconocido",
        )
    if not mensajes:
        raise ErrorValidacion(
            "No hay mensajes que resumir: un resumen de nada sería texto inventado.",
            error_code="conversacion.sin_mensajes",
        )

    disponible = enrutador.exigir_disponible(uow.db, uow.tenant_id, uso="resumen")
    if _resumidor is None:
        raise ErrorDependencia(
            "No hay puerto de IA conectado: preferimos una conversación sin resumen "
            "a un resumen inventado.",
            error_code="conversacion.sin_puerto",
        )

    # Lo que va al modelo pasa por los guardias como cualquier otro contexto: una
    # conversación de soporte lleva datos personales por definición.
    filtrado = guardias.filtrar_contexto(
        uow.db,
        uow.tenant_id,
        fragmentos=[
            {"texto": str(m.get("texto") or ""), "origen": str(m.get("autor") or "")}
            for m in mensajes
        ],
        principal=principal,
    )
    usados = filtrado.get("fragmentos") or []
    totales = int(mensajes_totales if mensajes_totales is not None else len(mensajes))

    inicio = _ahora()
    try:
        salida = _resumidor(
            proveedor=disponible["elegido"],
            modelo=disponible["modelo"],
            mensajes=usados,
            opt_out=bool(disponible.get("opt_out")),
        )
    except Exception as exc:  # el fallo también se contabiliza: si no, el gasto miente
        uso.anotar(
            uow,
            tarea="resumen",
            proveedor=disponible["elegido"],
            modelo=disponible["modelo"],
            objeto="conversacion",
            objeto_id=conversacion_id,
            resultado="error",
            error=str(exc)[:200],
            opt_out=bool(disponible.get("opt_out")),
        )
        raise

    fila = ResumenConversacion(
        tenant_id=uow.tenant_id,
        conversacion_id=conversacion_id,
        caso_id=caso_id,
        momento=momento,
        texto=str(salida.get("texto") or ""),
        pendientes=list(salida.get("pendientes") or []),
        mensajes_totales=totales,
        mensajes_usados=len(usados),
        parcial=len(usados) < totales,
    )
    uow.db.add(fila)
    uow.db.flush()

    uso.anotar(
        uow,
        tarea="resumen",
        proveedor=disponible["elegido"],
        modelo=disponible["modelo"],
        region=str(disponible.get("region") or ""),
        objeto="conversacion",
        objeto_id=conversacion_id,
        tokens_entrada=int(salida.get("tokens_entrada") or 0),
        tokens_salida=int(salida.get("tokens_salida") or 0),
        duracion_ms=int((_ahora() - inicio).total_seconds() * 1000),
        resultado="pendiente",
        opt_out=bool(disponible.get("opt_out")),
    )

    if caso_id is not None:
        # Cross-servicio: se **pide**. Que el comando se publique no significa que
        # el caso ya lo tenga, y decir «hecho» aquí sería mentir sobre algo que
        # todavía puede fallar en el otro lado.
        from crmcore.bus.comandos import Comando
        from crmcore.bus.comandos import emitir as emitir_comando

        emitir_comando(
            uow,
            Comando(
                accion="adjuntar_resumen",
                objeto="caso",
                tenant_id=uow.tenant_id,
                registro_id=caso_id,
                datos={
                    "resumen_id": str(fila.id),
                    "texto": fila.texto,
                    "pendientes": fila.pendientes,
                    "momento": momento,
                    "parcial": fila.parcial,
                },
                origen="ia_resumen",
                origen_id=str(fila.id),
            ),
        )

    return {
        "resumen_id": str(fila.id),
        "texto": fila.texto,
        "pendientes": fila.pendientes,
        "mensajes_totales": totales,
        "mensajes_usados": len(usados),
        "parcial": fila.parcial,
        "retirados_por_permisos": len(filtrado.get("quitados") or []),
        "estado": "pedido" if caso_id is not None else "propuesto",
        "aviso": (
            ""
            if not fila.parcial
            else f"Hecho con {len(usados)} de {totales} mensajes: es un resumen de "
            "una parte de la conversación, no de toda."
        ),
    }


def clasificar(
    uow: UnidadDeTrabajo,
    *,
    conversacion_id: UUID,
    texto: str,
    umbral_confianza: float = 0.6,
    umbral_escalado: float = 0.8,
) -> dict[str, Any]:
    """Sentimiento e intención de lo que acaba de decir el cliente
    (CRM-04.02.02.07).

    **Con confianza y con umbral**: por debajo del umbral la respuesta es «no
    concluyente», no «neutro». Un neutro falso entra en las medias del día y las
    aplana, y entonces el panel dice que todo va bien porque el clasificador no
    se atrevía a decir nada.

    **No escala solo.** Devuelve `sugiere_escalar` con su porqué; quién escala y
    cuándo lo decide una regla del cliente, y queda registrado.
    """
    if not texto.strip():
        raise ErrorValidacion("No hay texto que clasificar.", error_code="conversacion.sin_texto")
    disponible = enrutador.exigir_disponible(uow.db, uow.tenant_id, uso="clasificacion")
    if _clasificador is None:
        raise ErrorDependencia(
            "No hay puerto de IA conectado: sin él no hay señal, y una señal "
            "inventada en caliente es peor que ninguna.",
            error_code="conversacion.sin_puerto",
        )

    inicio = _ahora()
    salida = _clasificador(
        proveedor=disponible["elegido"],
        modelo=disponible["modelo"],
        texto=texto,
        sentimientos=list(SENTIMIENTOS),
        intenciones=list(INTENCIONES),
        opt_out=bool(disponible.get("opt_out")),
    )

    sentimiento = str(salida.get("sentimiento") or "neutro")
    intencion = str(salida.get("intencion") or "otro")
    # Si el modelo se inventa una etiqueta, no se guarda tal cual: la lista es
    # cerrada precisamente para que los paneles cuadren.
    if sentimiento not in SENTIMIENTOS:
        sentimiento = "neutro"
    if intencion not in INTENCIONES:
        intencion = "otro"
    confianza = max(0.0, min(1.0, float(salida.get("confianza") or 0)))
    concluyente = confianza >= float(umbral_confianza)

    escalar = bool(
        concluyente
        and sentimiento in ("muy_negativo", "negativo")
        and confianza >= float(umbral_escalado)
    )
    if not concluyente:
        porque = (
            f"Confianza {confianza:.2f}, por debajo del umbral {umbral_confianza:.2f}: "
            "no se afirma nada. No es neutro, es que no se sabe."
        )
    else:
        indicios = ", ".join(str(i) for i in (salida.get("indicios") or [])[:3])
        porque = f"Detectado «{sentimiento}» / «{intencion}»" + (
            f" por: {indicios}." if indicios else "."
        )
        if escalar:
            porque += " Sugiere escalar; la decisión sigue siendo de una persona."

    fila = SenalConversacion(
        tenant_id=uow.tenant_id,
        conversacion_id=conversacion_id,
        sentimiento=sentimiento,
        intencion=intencion,
        confianza=confianza,
        concluyente=concluyente,
        indicios=list(salida.get("indicios") or [])[:5],
        sugiere_escalar=escalar,
        porque=porque,
    )
    uow.db.add(fila)
    uow.db.flush()

    uso.anotar(
        uow,
        tarea="clasificacion",
        proveedor=disponible["elegido"],
        modelo=disponible["modelo"],
        region=str(disponible.get("region") or ""),
        objeto="conversacion",
        objeto_id=conversacion_id,
        tokens_entrada=int(salida.get("tokens_entrada") or 0),
        tokens_salida=int(salida.get("tokens_salida") or 0),
        duracion_ms=int((_ahora() - inicio).total_seconds() * 1000),
        # Ni «aceptada» ni «descartada»: nadie la ha juzgado. Una clasificación
        # que no llega al umbral es una llamada que no dio nada útil, y así es
        # como se cuenta.
        resultado="pendiente" if concluyente else "sin_respuesta",
        opt_out=bool(disponible.get("opt_out")),
    )

    return {
        "sentimiento": sentimiento if concluyente else None,
        "intencion": intencion if concluyente else None,
        "confianza": round(confianza, 3),
        "concluyente": concluyente,
        "indicios": fila.indicios,
        "sugiere_escalar": escalar,
        # Se dice explícitamente: nadie tiene que deducir del JSON que esto no
        # ha movido nada.
        "escalado_automatico": False,
        "porque": porque,
    }


def evolucion(
    db: Session, tenant_id: UUID, conversacion_id: UUID, *, limite: int = 50
) -> dict[str, Any]:
    """Cómo ha ido el ánimo a lo largo de la conversación.

    Las no concluyentes **no se cuentan** en la media, pero sí se dicen: si
    desaparecieran, una conversación que el clasificador no entiende parecería
    una conversación tranquila.
    """
    filas = (
        db.execute(
            select(SenalConversacion)
            .where(
                SenalConversacion.tenant_id == tenant_id,
                SenalConversacion.conversacion_id == conversacion_id,
            )
            .order_by(SenalConversacion.created_at.asc())
            .limit(max(1, limite))
        )
        .scalars()
        .all()
    )
    escala = {"muy_negativo": -2, "negativo": -1, "neutro": 0, "positivo": 1, "muy_positivo": 2}
    utiles = [f for f in filas if f.concluyente]
    valores = [escala[f.sentimiento] for f in utiles]
    tendencia = None
    if len(valores) >= 4:
        mitad = len(valores) // 2
        primera = sum(valores[:mitad]) / mitad
        segunda = sum(valores[mitad:]) / (len(valores) - mitad)
        delta = segunda - primera
        tendencia = "mejora" if delta > 0.3 else ("empeora" if delta < -0.3 else "estable")
    return {
        "señales": len(filas),
        "concluyentes": len(utiles),
        "no_concluyentes": len(filas) - len(utiles),
        "medio": round(sum(valores) / len(valores), 2) if valores else None,
        "tendencia": tendencia,
        "por_que_no_hay_tendencia": (
            None if tendencia else "Hacen falta al menos 4 señales concluyentes."
        ),
        "intenciones": sorted({f.intencion for f in utiles}),
        "linea": [
            {
                "sentimiento": f.sentimiento if f.concluyente else None,
                "concluyente": f.concluyente,
                "confianza": float(f.confianza),
                "momento": f.created_at.isoformat(),
            }
            for f in filas
        ],
    }


def resumenes_de(
    db: Session,
    tenant_id: UUID,
    *,
    conversacion_id: UUID | None = None,
    caso_id: UUID | None = None,
    limite: int = 100,
) -> dict[str, Any]:
    """Los resúmenes propuestos, con lo que quedó pendiente y de dónde salen.

    **Se escribían y no los leía nadie.** El resumen existe para que el agente
    que recoge una conversación no empiece de cero, y ninguna ruta lo
    devolvía: se generaba, se cobraba al proveedor de IA y se quedaba en una
    tabla que nadie podía abrir.

    Tres cosas viajan aparte del texto, y las tres deciden si uno se fía:

    - **los pendientes**, que es lo que el siguiente agente lee primero y lo
      que más se inventa un modelo. Revisables sin releer el resumen entero;
    - **de cuántos mensajes salió y cuántos se usaron**. Un resumen hecho con
      veinte de doscientos mensajes no es el mismo documento, y sin esos dos
      números los dos se leen igual;
    - **si es parcial**, que es la diferencia entre un resumen y el resumen del
      final de la conversación.
    """
    consulta = select(ResumenConversacion).where(ResumenConversacion.tenant_id == tenant_id)
    if conversacion_id is not None:
        consulta = consulta.where(ResumenConversacion.conversacion_id == conversacion_id)
    if caso_id is not None:
        consulta = consulta.where(ResumenConversacion.caso_id == caso_id)
    filas = (
        db.execute(consulta.order_by(ResumenConversacion.created_at.desc()).limit(limite))
        .scalars()
        .all()
    )
    return {
        "resumenes": [
            {
                "id": str(f.id),
                "conversacion_id": str(f.conversacion_id),
                "caso_id": str(f.caso_id) if f.caso_id else None,
                "momento": f.momento,
                "texto": f.texto,
                "pendientes": list(f.pendientes or []),
                "mensajes_totales": f.mensajes_totales,
                "mensajes_usados": f.mensajes_usados,
                "parcial": f.parcial,
                "estado": f.estado,
                "cuando": f.created_at.isoformat(),
            }
            for f in filas
        ],
        "cuantos": len(filas),
        # Los que traen compromisos, contados: es lo que hay que revisar antes
        # de dar el relevo, y lo que un modelo se inventa más a menudo.
        "con_pendientes": len([f for f in filas if f.pendientes]),
        "aviso": (
            ""
            if filas
            else "No consta ningún resumen de esta conversación. Eso no significa "
            "que no haga falta: significa que nadie lo ha pedido todavía."
        ),
    }
