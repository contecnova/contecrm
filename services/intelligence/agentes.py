"""Agentes que ejecutan procesos, con control humano, límites y reversión
(CRM-05.02.03.01, .03, .04, .05, .06).

Un agente es una automatización que decide sola qué paso dar. Eso es lo que lo
hace útil y lo que lo hace peligroso, y las dos cosas salen de la misma
propiedad: **nadie escribió de antemano lo que va a hacer**. Así que todo lo de
aquí está construido alrededor de poder contestar, meses después, «¿por qué el
CRM hizo esto?» y, sobre todo, «¿cómo lo deshago?».

Las decisiones:

**Un agente tiene su propio principal.** Actuar «en nombre de» heredando permisos
convierte cualquier error suyo en un error con los permisos del jefe. Y el kill
switch tiene dónde aplicarse solo si el agente es alguien.

**El plan se guarda antes de ejecutarlo.** Sin plan previo, la auditoría es una
lista de cosas que pasaron y no hay forma de ver dónde se torció: si el primer
paso ya iba mal, los otros cuatro son consecuencia y no decisiones.

**Lo que puede salir caro se para y espera a una persona.** Por riesgo de la
herramienta o por importe, con el umbral configurable. Un control humano que
depende de que el modelo pida permiso no es un control.

**Hay tres límites y son distintos**: cuántas acciones por ejecución, cuántos
tokens por periodo y un interruptor de apagado. El primero acota un bucle, el
segundo una factura y el tercero un incidente, y tener solo uno de los tres deja
fuera dos de los tres problemas.

**Todo paso de escritura guarda cómo deshacerse.** Una auditoría que cuenta lo
que pasó sin poder revertirlo sirve para la reunión de después, no para la noche
en que está pasando.

**Y lo que no se puede deshacer se dice.** Un correo enviado no vuelve. Fingir
que la reversión es total sería peor que no tenerla, porque alguien confiaría.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable
from uuid import UUID

from crmcore.audit.chain import registrar
from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorDependencia, ErrorValidacion, NoEncontrado, Prohibido
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
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from services.intelligence import enrutador, uso

logger = get_logger(__name__)

# Qué agentes se pueden declarar. Lista cerrada porque cada uno tiene su
# plantilla, sus herramientas y su nivel de control: con texto libre, «soporte» y
# «atencion» serían dos agentes distintos y uno de los dos estaría sin revisar.
TIPOS = (
    "calificacion_leads",
    "respuesta_soporte",
    "actualizacion_datos",
    "asistente_conversacional",
)

ESTADOS_EJECUCION = (
    "planificando",
    "esperando_aprobacion",
    "ejecutando",
    "terminada",
    "fallida",
    "detenida",
    "revertida",
)

ESTADOS_PASO = ("planificado", "esperando_aprobacion", "hecho", "fallido", "saltado", "revertido")

# El puerto que de verdad llama a la herramienta. Se registra desde fuera, como
# el del modelo: así lo que se prueba es qué se le pide y qué se hace con lo que
# vuelve, que es donde están los fallos que importan.
_invocador: Callable[..., dict[str, Any]] | None = None
_planificador: Callable[..., dict[str, Any]] | None = None


def registrar_invocador(fn: Callable[..., dict[str, Any]]) -> None:
    global _invocador
    _invocador = fn


def registrar_planificador(fn: Callable[..., dict[str, Any]]) -> None:
    global _planificador
    _planificador = fn


def _definicion(agente: "Agente", nombre: str) -> dict[str, Any]:
    """La herramienta tal como la declaró el agente: método, ruta y parámetros.

    El paso guarda el NOMBRE, no la ruta, y a propósito: una herramienta es la
    misma aunque el contrato cambie de camino, y guardar la ruta en cada paso
    dejaría ejecuciones viejas llamando a rutas que ya no existen. Quien ejecuta
    la busca aquí, en la declaración viva del agente.

    Vacío si el agente ya no la tiene. Quien llama decide qué hacer con eso; lo
    que no puede es inventarse un método y una ruta, que es como un agente
    acabaría llamando a algo que nadie le dio.
    """
    for h in agente.herramientas or []:
        if str(h.get("nombre") or "") == nombre:
            return dict(h)
    return {}


class Agente(Base, TimestampMixin, SoftDeleteMixin):
    """Un agente declarado, con sus herramientas y sus límites."""

    __tablename__ = "agentes_ia"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    tipo: Mapped[str] = mapped_column(String(40), nullable=False, info={"opciones": TIPOS})
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Su propio principal. No hereda el de quien lo lanza: un agente que actúa
    # con los permisos del jefe convierte su error en el error del jefe.
    # Quién queda como responsable de lo que haga el agente.
    principal_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, info={"referencia": "usuario"}
    )
    permisos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    herramientas: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    # ── Los tres límites, que son tres problemas distintos ────────────────
    # Un bucle: el agente que se llama a sí mismo cien veces.
    max_acciones: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    # Una factura: el agente que funciona y cuesta lo que nadie previó.
    presupuesto_tokens_dia: Mapped[int] = mapped_column(Integer, nullable=False, default=200_000)
    # Un incidente: el agente que hay que parar ahora mismo.
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    motivo_apagado: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # ── Control humano (CRM-05.02.03.03) ──────────────────────────────────
    # Qué riesgos exigen que una persona apruebe. Vacío NO significa «ninguno»:
    # significa el valor por defecto, que incluye lo destructivo.
    aprobacion_por_riesgo: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Por encima de este importe, aprueba una persona aunque el riesgo sea bajo.
    # Nulo = el importe no dispara aprobación.
    aprobacion_desde_importe: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_agente_clave"),
        Index("ix_agentes_activos", "tenant_id", "activo"),
    )


class EjecucionAgente(Base):
    """Una puesta en marcha del agente, con su plan y su resultado."""

    __tablename__ = "ejecuciones_agente"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    agente_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    objetivo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    contexto: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    estado: Mapped[str] = mapped_column(String(30), nullable=False, default="planificando")
    lanzada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    motivo_fin: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    terminada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_ejecuciones_agente", "tenant_id", "agente_id", "estado"),)


class PasoAgente(Base):
    """Un paso del plan: qué se pensaba hacer, qué se hizo y cómo se deshace."""

    __tablename__ = "pasos_agente"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    ejecucion_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    herramienta: Mapped[str] = mapped_column(String(80), nullable=False)
    riesgo: Mapped[str] = mapped_column(String(20), nullable=False, default="lectura")
    # Por qué el agente cree que este paso hace falta. Es lo que se lee cuando
    # alguien pregunta por qué el CRM hizo algo, y lo que el aprobador mira.
    porque: Mapped[str] = mapped_column(Text, nullable=False, default="")
    argumentos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    importe: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    estado: Mapped[str] = mapped_column(String(30), nullable=False, default="planificado")
    resultado: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Cómo se deshace: la llamada inversa, guardada ANTES de ejecutar. Calcularla
    # después obligaría a saber qué había antes, y para entonces ya se cambió.
    compensacion: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Lo que no tiene vuelta atrás. Un correo enviado no se «des-envía», y decir
    # que sí sería la peor promesa de todo este módulo.
    reversible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    aprobado_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    aprobado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ejecutado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revertido_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_pasos_agente", "tenant_id", "ejecucion_id", "orden"),
        Index("ix_pasos_pendientes", "tenant_id", "estado"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


# ── Declaración (CRM-05.02.03.01, .06) ────────────────────────────────────


def declarar(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    tipo: str,
    descripcion: str = "",
    permisos: list[str] | None = None,
    herramientas: list[dict[str, Any]] | None = None,
    principal_id: UUID | None = None,
    max_acciones: int = 10,
    presupuesto_tokens_dia: int = 200_000,
    aprobacion_por_riesgo: list[str] | None = None,
    aprobacion_desde_importe: Decimal | None = None,
) -> Agente:
    """Declara un agente con sus herramientas y sus límites.

    Los agentes concretos —calificar leads, contestar soporte, actualizar datos—
    son **configuración y no código** (CRM-05.02.03.06): lo que cambia entre uno
    y otro es qué herramientas tiene y cuándo para. Escribir uno por cliente sería
    tener tantos agentes como implantaciones.
    """
    if tipo not in TIPOS:
        raise ErrorValidacion(
            f"Tipo de agente desconocido: «{tipo}»",
            error_code="agente.tipo_desconocido",
            detalle={"admitidos": list(TIPOS)},
        )
    if max_acciones < 1:
        raise ErrorValidacion(
            "Un agente sin tope de acciones es un bucle esperando a pasar",
            error_code="agente.sin_tope",
        )

    fila = (
        uow.db.execute(
            select(Agente).where(Agente.tenant_id == uow.tenant_id, Agente.clave == clave)
        )
        .scalars()
        .first()
    )
    if fila is None:
        fila = Agente(tenant_id=uow.tenant_id, clave=clave, tipo=tipo)
        uow.db.add(fila)
    fila.tipo = tipo
    fila.descripcion = descripcion or fila.descripcion
    fila.permisos = sorted(set(permisos or []))
    fila.herramientas = list(herramientas or [])
    fila.principal_id = principal_id or fila.principal_id
    fila.max_acciones = int(max_acciones)
    fila.presupuesto_tokens_dia = int(presupuesto_tokens_dia)
    # Vacío no es «ninguno»: es el valor por defecto, que incluye lo destructivo.
    # Leerlo como «ninguno» haría que declarar un agente sin pensar en esto
    # quitara justo el control que más falta hace.
    fila.aprobacion_por_riesgo = list(aprobacion_por_riesgo or ["destructivo"])
    fila.aprobacion_desde_importe = aprobacion_desde_importe
    fila.activo = True
    uow.db.flush()
    return fila


def apagar(uow: UnidadDeTrabajo, *, clave: str, motivo: str) -> Agente:
    """Kill switch del agente (CRM-05.02.03.04).

    Parar uno no para a los demás, y por eso existe además el apagado de toda la
    IA del tenant: cuando algo va mal de verdad no hay tiempo de decidir cuál de
    los seis agentes era.
    """
    if not motivo.strip():
        raise ErrorValidacion(
            "Apagar un agente exige decir por qué: el siguiente que lo encienda "
            "tiene que saber qué pasó.",
            error_code="agente.apagado_sin_motivo",
        )
    agente = _agente(uow.db, uow.tenant_id, clave)
    agente.activo = False
    agente.motivo_apagado = motivo
    uow.db.flush()

    # Y se detienen sus ejecuciones en vuelo: apagar un agente que sigue
    # terminando lo que empezó no es apagarlo.
    detenidas = 0
    for ejecucion in (
        uow.db.execute(
            select(EjecucionAgente).where(
                EjecucionAgente.tenant_id == uow.tenant_id,
                EjecucionAgente.agente_id == agente.id,
                EjecucionAgente.estado.in_(("planificando", "esperando_aprobacion", "ejecutando")),
            )
        )
        .scalars()
        .all()
    ):
        ejecucion.estado = "detenida"
        ejecucion.motivo_fin = f"Agente apagado: {motivo}"
        ejecucion.terminada_at = _ahora()
        detenidas += 1
    uow.db.flush()

    registrar(
        uow.db,
        accion="agente.apagado",
        objeto="agente_ia",
        objeto_id=agente.id,
        datos={"clave": clave, "ejecuciones_detenidas": detenidas},
        motivo=motivo,
        tenant_id=uow.tenant_id,
    )
    logger.warning("agente.apagado", clave=clave, detenidas=detenidas)
    return agente


def _agente(db: Session, tenant_id: UUID, clave: str) -> Agente:
    fila = (
        db.execute(select(Agente).where(Agente.tenant_id == tenant_id, Agente.clave == clave))
        .scalars()
        .first()
    )
    if fila is None:
        raise NoEncontrado("Ese agente no existe", error_code="agente.no_encontrado")
    return fila


# ── Ejecución (CRM-05.02.03.01, .03, .04) ─────────────────────────────────


def lanzar(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    objetivo: str,
    contexto: dict[str, Any] | None = None,
    por: UUID | None = None,
) -> dict[str, Any]:
    """Pone un agente a trabajar: **planifica primero y guarda el plan**.

    Sin plan previo, la auditoría es una lista de cosas que pasaron y no hay
    forma de ver dónde se torció: si el primer paso ya iba mal, los cuatro
    siguientes son consecuencia y no decisiones.

    Nada se ejecuta aquí. Los pasos que necesitan aprobación quedan esperando, y
    los demás se ejecutan uno a uno con `avanzar`, para que el tope de acciones y
    el apagado tengan dónde aplicarse entre paso y paso.
    """
    agente = _agente(uow.db, uow.tenant_id, clave)
    if not agente.activo:
        raise Prohibido(
            f"El agente «{clave}» está apagado: {agente.motivo_apagado}",
            error_code="agente.apagado",
        )
    # El apagado general de la IA del tenant manda sobre el del agente: cuando
    # algo va mal de verdad no hay tiempo de decidir cuál de los seis era.
    disponible = enrutador.exigir_disponible(uow.db, uow.tenant_id, uso="redaccion")
    if _planificador is None:
        raise ErrorDependencia(
            "No hay puerto de IA conectado: sin él no hay plan, y ejecutar sin "
            "plan sería exactamente lo que este módulo evita.",
            error_code="agente.sin_puerto",
        )

    gastado = _tokens_de_hoy(uow.db, uow.tenant_id, agente.id)
    if gastado >= agente.presupuesto_tokens_dia:
        raise Conflicto(
            f"El agente «{clave}» ha agotado su presupuesto de tokens de hoy "
            f"({gastado} de {agente.presupuesto_tokens_dia}).",
            error_code="agente.presupuesto_agotado",
            detalle={"gastado": gastado, "presupuesto": agente.presupuesto_tokens_dia},
        )

    ejecucion = EjecucionAgente(
        tenant_id=uow.tenant_id,
        agente_id=agente.id,
        objetivo=objetivo,
        contexto=dict(contexto or {}),
        lanzada_por=por,
        estado="planificando",
    )
    uow.db.add(ejecucion)
    uow.db.flush()

    salida = _planificador(
        proveedor=disponible["elegido"],
        modelo=disponible["modelo"],
        objetivo=objetivo,
        contexto=dict(contexto or {}),
        herramientas=agente.herramientas,
        opt_out=bool(disponible.get("opt_out")),
    )
    pasos_pedidos = list(salida.get("pasos") or [])
    ejecucion.tokens = int(salida.get("tokens_entrada") or 0) + int(
        salida.get("tokens_salida") or 0
    )

    uso.anotar(
        uow,
        tarea="redaccion",
        proveedor=disponible["elegido"],
        modelo=disponible["modelo"],
        objeto="ejecucion_agente",
        objeto_id=ejecucion.id,
        tokens_entrada=int(salida.get("tokens_entrada") or 0),
        tokens_salida=int(salida.get("tokens_salida") or 0),
        resultado="pendiente",
        opt_out=bool(disponible.get("opt_out")),
    )

    # El tope de acciones se aplica AL PLAN, no solo al ejecutar: un plan de
    # cuarenta pasos que se corta en el diez deja veinte a medias y nadie sabe
    # cuáles. Se recorta y se dice.
    recortado = len(pasos_pedidos) > agente.max_acciones
    pasos_pedidos = pasos_pedidos[: agente.max_acciones]

    conocidas = {str(h.get("nombre")): h for h in (agente.herramientas or [])}
    creados: list[PasoAgente] = []
    descartados: list[str] = []
    for orden, pedido in enumerate(pasos_pedidos, start=1):
        nombre = str(pedido.get("herramienta") or "")
        ficha = conocidas.get(nombre)
        if ficha is None:
            # Una herramienta que el agente no tiene no se intenta «por si
            # acaso»: se descarta y se dice. Intentarla daría un 403 del otro
            # lado y un paso fallido que parece un error del sistema.
            descartados.append(nombre)
            continue
        riesgo = str(ficha.get("riesgo") or "lectura")
        importe = pedido.get("importe")
        # La decisión de aprobación se toma ANTES de convertir el importe, porque
        # es ella la que sabe qué hacer con uno ilegible. Convertirlo primero
        # reventaba el plan entero por un campo que el modelo escribió mal —y un
        # plan que falla al construirse no deja ni rastro de qué se pretendía.
        necesita_aprobacion = _necesita_aprobacion(agente, riesgo, importe)
        paso = PasoAgente(
            tenant_id=uow.tenant_id,
            ejecucion_id=ejecucion.id,
            orden=orden,
            herramienta=nombre,
            riesgo=riesgo,
            porque=str(pedido.get("porque") or ""),
            argumentos=dict(pedido.get("argumentos") or {}),
            importe=_importe(importe),
            compensacion=dict(pedido.get("compensacion") or {}),
            reversible=bool(pedido.get("compensacion")),
            estado="esperando_aprobacion" if necesita_aprobacion else "planificado",
        )
        uow.db.add(paso)
        creados.append(paso)

    ejecucion.estado = (
        "esperando_aprobacion"
        if any(p.estado == "esperando_aprobacion" for p in creados)
        else "ejecutando"
    )
    uow.db.flush()

    registrar(
        uow.db,
        accion="agente.plan_creado",
        objeto="ejecucion_agente",
        objeto_id=ejecucion.id,
        datos={"agente": clave, "pasos": len(creados), "objetivo": objetivo[:200]},
        tenant_id=uow.tenant_id,
    )
    return {
        "ejecucion_id": str(ejecucion.id),
        "estado": ejecucion.estado,
        "pasos": [
            {
                "orden": p.orden,
                "herramienta": p.herramienta,
                "riesgo": p.riesgo,
                "porque": p.porque,
                "estado": p.estado,
                "reversible": p.reversible,
            }
            for p in creados
        ],
        "esperando_aprobacion": [p.orden for p in creados if p.estado == "esperando_aprobacion"],
        # Las dos cosas que el modelo pidió y no se le van a dar, dichas aparte:
        # sin esto, el agente «no hace lo que le pido» y nadie sabe por qué.
        "herramientas_descartadas": descartados,
        "plan_recortado": recortado,
        "aviso": (
            f"El plan traía más de {agente.max_acciones} pasos y se ha recortado."
            if recortado
            else ""
        ),
    }


def _importe(valor: Any) -> Decimal | None:
    """El importe del paso, o nada si no se entiende.

    Se guarda vacío en vez de romper: lo que decide si hace falta aprobación ya
    ha mirado el valor crudo y, si era ilegible, ha pedido aprobación. Guardar
    un número inventado aquí haría que el aprobador viera un importe que nadie
    escribió.
    """
    if valor is None:
        return None
    try:
        return Decimal(str(valor))
    except Exception:  # noqa: BLE001 — un importe ilegible no tumba el plan
        return None


def _necesita_aprobacion(agente: Agente, riesgo: str, importe: Any) -> bool:
    """Si este paso tiene que esperar a una persona (CRM-05.02.03.03).

    Se decide **aquí y no preguntándole al modelo**: un control humano que
    depende de que el propio agente pida permiso no es un control.
    """
    if riesgo in (agente.aprobacion_por_riesgo or []):
        return True
    if agente.aprobacion_desde_importe is not None and importe is not None:
        try:
            return Decimal(str(importe)) >= agente.aprobacion_desde_importe
        except Exception:  # noqa: BLE001
            # Un importe ilegible se trata como si superara el umbral. Al revés
            # —dejarlo pasar— haría que un dato mal formado se saltara el control.
            return True
    return False


def aprobar(
    uow: UnidadDeTrabajo, *, paso_id: UUID, aprobado: bool, por: UUID, motivo: str = ""
) -> dict[str, Any]:
    """Una persona autoriza —o no— un paso que estaba esperando."""
    paso = uow.db.get(PasoAgente, paso_id)
    if paso is None or paso.tenant_id != uow.tenant_id:
        raise NoEncontrado("Ese paso no existe", error_code="agente.paso_no_encontrado")
    if paso.estado != "esperando_aprobacion":
        raise Conflicto(
            f"Ese paso está en «{paso.estado}», no esperando aprobación",
            error_code="agente.paso_no_espera",
        )
    paso.aprobado_por = por
    paso.aprobado_at = _ahora()
    paso.estado = "planificado" if aprobado else "saltado"
    paso.error = "" if aprobado else (motivo or "Rechazado por una persona")
    uow.db.flush()
    registrar(
        uow.db,
        accion="agente.paso_aprobado" if aprobado else "agente.paso_rechazado",
        objeto="paso_agente",
        objeto_id=paso.id,
        datos={"herramienta": paso.herramienta, "riesgo": paso.riesgo},
        motivo=motivo or None,
        tenant_id=uow.tenant_id,
    )
    return {"paso_id": str(paso.id), "estado": paso.estado}


def avanzar(uow: UnidadDeTrabajo, *, ejecucion_id: UUID) -> dict[str, Any]:
    """Ejecuta el siguiente paso listo, uno solo.

    Uno y no todos: entre paso y paso es donde caben el apagado, el tope y la
    aprobación. Un bucle que los ejecuta todos de golpe convierte esos tres
    controles en decoración.
    """
    ejecucion = uow.db.get(EjecucionAgente, ejecucion_id)
    if ejecucion is None or ejecucion.tenant_id != uow.tenant_id:
        raise NoEncontrado("Esa ejecución no existe", error_code="agente.ejecucion_no_encontrada")
    agente = uow.db.get(Agente, ejecucion.agente_id)
    if agente is None:
        raise NoEncontrado("El agente ya no existe", error_code="agente.no_encontrado")
    if not agente.activo or ejecucion.estado == "detenida":
        raise Prohibido(
            f"El agente está apagado: {agente.motivo_apagado}", error_code="agente.apagado"
        )
    if _invocador is None:
        raise ErrorDependencia(
            "No hay invocador de herramientas conectado", error_code="agente.sin_invocador"
        )

    pasos = (
        uow.db.execute(
            select(PasoAgente)
            .where(
                PasoAgente.tenant_id == uow.tenant_id,
                PasoAgente.ejecucion_id == ejecucion_id,
            )
            .order_by(PasoAgente.orden)
        )
        .scalars()
        .all()
    )
    hechos = len([p for p in pasos if p.estado == "hecho"])
    if hechos >= agente.max_acciones:
        ejecucion.estado = "terminada"
        ejecucion.motivo_fin = "Tope de acciones alcanzado"
        ejecucion.terminada_at = _ahora()
        uow.db.flush()
        return {"avanzado": False, "porque": "Se ha alcanzado el tope de acciones del agente."}

    siguiente = next((p for p in pasos if p.estado == "planificado"), None)
    if siguiente is None:
        esperando = [p for p in pasos if p.estado == "esperando_aprobacion"]
        if esperando:
            ejecucion.estado = "esperando_aprobacion"
            uow.db.flush()
            return {
                "avanzado": False,
                "porque": f"{len(esperando)} paso(s) esperan a que una persona los apruebe.",
                "esperando": [p.orden for p in esperando],
            }
        ejecucion.estado = "terminada"
        ejecucion.terminada_at = _ahora()
        uow.db.flush()
        return {"avanzado": False, "porque": "No queda ningún paso por hacer.", "terminada": True}

    try:
        resultado = _invocador(
            herramienta=siguiente.herramienta,
            argumentos=siguiente.argumentos,
            definicion=_definicion(agente, siguiente.herramienta),
            tenant_id=uow.tenant_id,
            principal_id=agente.principal_id,
            permisos=list(agente.permisos or []),
        )
        siguiente.resultado = dict(resultado or {})
        siguiente.estado = "hecho"
    except Exception as exc:  # noqa: BLE001 — un paso fallido no tumba la ejecución
        siguiente.error = str(exc)[:400]
        siguiente.estado = "fallido"
        # Y la ejecución se para. Seguir con los siguientes pasos de un plan cuyo
        # tercer paso falló es ejecutar un plan que ya no tiene sentido.
        ejecucion.estado = "fallida"
        ejecucion.motivo_fin = f"El paso {siguiente.orden} ha fallado"
        ejecucion.terminada_at = _ahora()
    siguiente.ejecutado_at = _ahora()
    uow.db.flush()

    registrar(
        uow.db,
        accion="agente.paso_ejecutado",
        objeto="paso_agente",
        objeto_id=siguiente.id,
        datos={
            "herramienta": siguiente.herramienta,
            "estado": siguiente.estado,
            "riesgo": siguiente.riesgo,
        },
        tenant_id=uow.tenant_id,
    )
    return {
        "avanzado": True,
        "paso": siguiente.orden,
        "herramienta": siguiente.herramienta,
        "estado": siguiente.estado,
        "error": siguiente.error,
    }


def _tokens_de_hoy(db: Session, tenant_id: UUID, agente_id: UUID) -> int:
    desde = _ahora() - timedelta(days=1)
    total = db.execute(
        select(func.coalesce(func.sum(EjecucionAgente.tokens), 0)).where(
            EjecucionAgente.tenant_id == tenant_id,
            EjecucionAgente.agente_id == agente_id,
            EjecucionAgente.created_at >= desde,
        )
    ).scalar_one()
    return int(total or 0)


# ── Auditoría y reversión (CRM-05.02.03.05) ───────────────────────────────


def actuacion(db: Session, tenant_id: UUID, ejecucion_id: UUID) -> dict[str, Any]:
    """Qué hizo el agente, por qué y qué se puede deshacer.

    El plan y lo ejecutado se enseñan **juntos**: ver solo lo que pasó no dice
    dónde se torció, y ver solo el plan no dice qué llegó a hacerse.
    """
    ejecucion = db.get(EjecucionAgente, ejecucion_id)
    if ejecucion is None or ejecucion.tenant_id != tenant_id:
        raise NoEncontrado("Esa ejecución no existe", error_code="agente.ejecucion_no_encontrada")
    pasos = (
        db.execute(
            select(PasoAgente)
            .where(PasoAgente.ejecucion_id == ejecucion_id)
            .order_by(PasoAgente.orden)
        )
        .scalars()
        .all()
    )
    hechos = [p for p in pasos if p.estado == "hecho"]
    return {
        "ejecucion_id": str(ejecucion.id),
        "objetivo": ejecucion.objetivo,
        "estado": ejecucion.estado,
        "tokens": ejecucion.tokens,
        "pasos": [
            {
                "orden": p.orden,
                "herramienta": p.herramienta,
                "riesgo": p.riesgo,
                "porque": p.porque,
                "argumentos": p.argumentos,
                "estado": p.estado,
                "error": p.error,
                "aprobado_por": str(p.aprobado_por) if p.aprobado_por else None,
                "reversible": p.reversible,
                "ejecutado_at": p.ejecutado_at.isoformat() if p.ejecutado_at else None,
            }
            for p in pasos
        ],
        "reversible_del_todo": all(p.reversible for p in hechos),
        # Lo que no tiene vuelta atrás, dicho por su nombre. Fingir que la
        # reversión es total sería peor que no tenerla, porque alguien confiaría.
        "no_reversibles": [
            {"orden": p.orden, "herramienta": p.herramienta} for p in hechos if not p.reversible
        ],
    }


def revertir(
    uow: UnidadDeTrabajo, *, ejecucion_id: UUID, por: UUID | None = None
) -> dict[str, Any]:
    """Deshace lo que el agente hizo, en orden inverso.

    En orden inverso porque los pasos se apoyan unos en otros: deshacer el
    primero antes que el tercero deja el tercero apuntando a algo que ya no está.

    Lo irreversible **no se toca y se dice**. Un correo enviado no se
    «des-envía»; lo que se puede hacer con él es contarlo, no ocultarlo.
    """
    if _invocador is None:
        raise ErrorDependencia(
            "No hay invocador de herramientas conectado", error_code="agente.sin_invocador"
        )
    ejecucion = uow.db.get(EjecucionAgente, ejecucion_id)
    if ejecucion is None or ejecucion.tenant_id != uow.tenant_id:
        raise NoEncontrado("Esa ejecución no existe", error_code="agente.ejecucion_no_encontrada")
    # El agente, para deshacer con SU identidad y con sus herramientas. Se pide
    # aunque esté apagado: apagar un agente no puede impedir deshacer lo que
    # hizo —sería justo al revés de lo que hace falta ese día—.
    agente = uow.db.get(Agente, ejecucion.agente_id)
    if agente is None:
        raise NoEncontrado("El agente ya no existe", error_code="agente.no_encontrado")

    pasos = (
        uow.db.execute(
            select(PasoAgente)
            .where(
                PasoAgente.tenant_id == uow.tenant_id,
                PasoAgente.ejecucion_id == ejecucion_id,
                PasoAgente.estado == "hecho",
            )
            .order_by(PasoAgente.orden.desc())
        )
        .scalars()
        .all()
    )
    revertidos: list[int] = []
    imposibles: list[dict[str, Any]] = []
    fallidos: list[dict[str, Any]] = []

    for paso in pasos:
        if not paso.reversible or not paso.compensacion:
            imposibles.append(
                {
                    "orden": paso.orden,
                    "herramienta": paso.herramienta,
                    "porque": "El paso no declaró cómo deshacerse",
                }
            )
            continue
        try:
            # Con la identidad del agente, no sin ninguna. Iba con
            # `principal_id=None` y `permisos=[]`: la compensación salía sin
            # identidad y sin permisos, así que en cuanto el invocador fuera de
            # verdad la habría rechazado el servicio de destino — y deshacer
            # habría fallado justo cuando hace falta.
            nombre_compensa = str(paso.compensacion.get("herramienta") or "")
            _invocador(
                herramienta=nombre_compensa,
                argumentos=dict(paso.compensacion.get("argumentos") or {}),
                definicion=_definicion(agente, nombre_compensa),
                tenant_id=uow.tenant_id,
                principal_id=agente.principal_id,
                permisos=list(agente.permisos or []),
            )
            paso.estado = "revertido"
            paso.revertido_at = _ahora()
            revertidos.append(paso.orden)
        except Exception as exc:  # noqa: BLE001
            fallidos.append({"orden": paso.orden, "error": str(exc)[:200]})

    ejecucion.estado = "revertida" if not fallidos and not imposibles else ejecucion.estado
    uow.db.flush()
    registrar(
        uow.db,
        accion="agente.revertido",
        objeto="ejecucion_agente",
        objeto_id=ejecucion.id,
        datos={"revertidos": len(revertidos), "imposibles": len(imposibles)},
        tenant_id=uow.tenant_id,
    )
    return {
        "revertidos": revertidos,
        "no_reversibles": imposibles,
        "fallidos_al_revertir": fallidos,
        "completa": not imposibles and not fallidos,
        "que_significa": (
            "Todo lo que hizo el agente se ha deshecho."
            if not imposibles and not fallidos
            else "Queda trabajo del agente sin deshacer: mira `no_reversibles` y "
            "`fallidos_al_revertir`. Nada de esto se arregla solo."
        ),
    }
