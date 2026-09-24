"""Conversación omnicanal: correo, formulario, chat, mensajería y API
(CRM-04.02.01.01 a .07, CRM-04.02.02.01, .02, .04, .08, CRM-04.03.02.03).

Reutiliza el patrón de captura de leads (`services/sales/captura.py`): un canal
declarado con su clave, su mapeo y su tope, en vez de un endpoint por
integración. El formulario de la web manda `nombre_completo`, el chat manda
`visitor_name` y WhatsApp manda `profile.name`; con un endpoint por cada uno,
cada cliente nuevo es código nuevo.

Las tres decisiones que gobiernan el módulo:

**La conversación es del cliente, no del canal.** Quien escribe por correo el
lunes, llama el martes y abre un chat el miércoles está teniendo **una**
conversación. Tres hilos separados hacen que el agente pregunte tres veces lo
mismo, que es lo que más enfada de un servicio de atención — y lo que el cliente
resume como «no os enteráis de nada».

**Todo mensaje entra por un solo sitio.** Un `Mensaje` con su canal, su
dirección y su identificador externo. Con una tabla por canal, «la conversación
de este cliente» sería una unión de cinco consultas que nadie mantiene al día, y
la mitad de las funciones acabarían soportando solo dos canales.

**No hay código de ningún proveedor.** WhatsApp, Messenger y Telegram entran por
el mismo canal declarativo que el formulario. Lo que cambia entre ellos —el
nombre de los campos, cómo viene el remitente— es configuración. Con un conector
por casa, cada cliente con una pasarela distinta sería una versión del producto.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, LimiteExcedido, NoAutenticado, NoEncontrado
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

if TYPE_CHECKING:  # pragma: no cover
    pass

# Canales admitidos, y a qué capacidad responde cada uno:
#
#   correo      CRM-04.02.01.01 — con hilo y anti-bucle
#   formulario  CRM-04.02.01.02 — formulario web y portal de cliente
#   portal      CRM-04.02.01.02 — la misma entrada, autenticada
#   chat        CRM-04.02.01.03 — chat en vivo
#   social      CRM-04.02.01.04 — WhatsApp, Messenger, Telegram
#   api         CRM-04.02.01.07 — soporte incrustado en el producto del cliente
#   telefono    para registrar la llamada dentro del mismo hilo
#
# Son un solo mecanismo y no siete: el transporte es el mismo y lo que cambia
# entre ellos —cómo se llama cada campo, cómo viene el remitente— es el mapeo
# declarado del canal. Con un módulo por canal, la mitad de las funciones de este
# fichero acabarían soportando solo dos.
CANALES = ("correo", "formulario", "chat", "social", "api", "telefono", "portal")
ENTRANTE, SALIENTE = "entrante", "saliente"


class CanalServicio(Base, TimestampMixin, SoftDeleteMixin):
    """Una entrada declarada de servicio: de dónde llega y cómo se traduce."""

    __tablename__ = "canales_servicio"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    tipo: Mapped[str] = mapped_column(
        String(20), nullable=False, default="formulario", info={"opciones": CANALES}
    )

    # Hasheado, igual que en la captura de leads: si la base se filtra, las
    # claves de los canales de todos los tenants no vienen en ella.
    secreto_hash: Mapped[str] = mapped_column(String(64), nullable=False, info={"secreto": True})

    # De qué campo de entrada sale cada campo del caso.
    mapeo: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Valores fijos del canal: la línea de servicio, la prioridad por defecto.
    # Van aquí y no en la petición porque vienen del canal, no de quien escribe —
    # que si no podría abrir todos sus casos como críticos.
    fijos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    obligatorios: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    campo_trampa: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    max_por_hora: Mapped[int] = mapped_column(Integer, nullable=False, default=300)

    # Dirección desde la que este canal responde. En correo es la cuenta del
    # buzón; se guarda para el anti-bucle: un mensaje que viene de nuestra propia
    # dirección es una respuesta automática nuestra rebotando.
    direccion_propia: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    recibidos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    descartados: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (UniqueConstraint("tenant_id", "clave", name="uq_canal_servicio"),)


class Conversacion(Base, TimestampMixin, SoftDeleteMixin):
    """El hilo con un cliente, por encima del canal (CRM-04.02.02.01).

    Cuelga del **contacto o de la cuenta**, no del canal. Quien escribe por
    correo el lunes y abre un chat el miércoles está teniendo una conversación:
    tres hilos separados hacen que el agente pregunte tres veces lo mismo.
    """

    __tablename__ = "conversaciones"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    caso_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    contacto_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, index=True
    )
    # Identidad de quien escribe cuando todavía no es un contacto conocido: el
    # correo, el teléfono o el identificador del visitante del chat.
    identidad_externa: Mapped[str] = mapped_column(String(320), nullable=False, default="")

    # Canal por el que está **ahora**. Cambia al transferir, y el historial de
    # canales vive en los mensajes: así una transferencia no borra por dónde
    # empezó la conversación, que es lo que el cliente recuerda.
    canal_actual: Mapped[str] = mapped_column(String(20), nullable=False, default="correo")
    asunto: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    # abierta | esperando | cerrada
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="abierta")
    # Quién está atendiendo la conversación.
    agente_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, info={"referencia": "usuario"}
    )
    # Si la lleva un bot. Se marca para poder medir la deflexión y, sobre todo,
    # para que el escalado a humano sepa que hay que traspasar contexto.
    atendida_por_bot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ultimo_mensaje_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_conversaciones_cliente", "tenant_id", "contacto_id", "ultimo_mensaje_at"),
        Index("ix_conversaciones_identidad", "tenant_id", "identidad_externa"),
    )


class Mensaje(Base):
    """Un mensaje de cualquier canal.

    Una sola tabla y no una por canal: con una por canal, «la conversación de
    este cliente» sería una unión de cinco consultas que nadie mantiene al día, y
    la mitad de las funciones acabarían soportando solo dos canales.
    """

    __tablename__ = "mensajes"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    conversacion_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("conversaciones.id", ondelete="CASCADE"), nullable=False
    )
    canal: Mapped[str] = mapped_column(String(20), nullable=False, info={"opciones": CANALES})
    direccion: Mapped[str] = mapped_column(String(10), nullable=False, default=ENTRANTE)
    remitente: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    asunto: Mapped[str | None] = mapped_column(String(300), nullable=True)
    cuerpo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Identificador del mensaje en el sistema de origen (`Message-ID` en correo,
    # el id del proveedor en mensajería). Es lo que impide procesar dos veces el
    # mismo mensaje cuando la pasarela reintenta.
    id_externo: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # A qué mensaje responde, para reconstruir el hilo.
    responde_a: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Solo para el agente: notas internas que el cliente no ve.
    interno: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    autor_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    adjuntos: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "id_externo", name="uq_mensaje_externo"),
        Index("ix_mensajes_conversacion", "tenant_id", "conversacion_id", "created_at"),
    )


class Macro(Base, TimestampMixin, SoftDeleteMixin):
    """Respuesta rápida o acción compuesta (CRM-04.02.02.04).

    Una macro puede escribir **y hacer**: contestar, cambiar el estado, poner una
    categoría y cerrar, todo de una vez. Que sea una sola acción es el punto:
    partida en cuatro clics, la mitad de las veces se queda a medias y el caso
    acaba contestado pero sin clasificar.
    """

    __tablename__ = "macros"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    # Plantilla del mensaje, con variables `{caso.codigo}`, `{contacto.nombre}`.
    cuerpo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Qué hace además de escribir: {"estado": "resuelto", "prioridad": "baja"}.
    acciones: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    canales: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    usos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (UniqueConstraint("tenant_id", "clave", name="uq_macro_clave"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _hash(valor: str) -> str:
    return hashlib.sha256(valor.encode()).hexdigest()


# ── Canales ───────────────────────────────────────────────────────────────


def crear_canal(
    db: Session, *, tenant_id: UUID, clave: str, nombre: str, tipo: str = "formulario", **datos: Any
) -> tuple[CanalServicio, str]:
    """Da de alta un canal y devuelve su secreto **una sola vez**."""
    if tipo not in CANALES:
        raise ErrorValidacion(
            f"Canal «{tipo}» no válido.",
            error_code="service.canal_no_valido",
            detalle={"validos": list(CANALES)},
        )
    if db.execute(
        select(CanalServicio.id).where(
            CanalServicio.tenant_id == tenant_id, CanalServicio.clave == clave
        )
    ).first():
        raise Conflicto("Ya existe un canal con esa clave", error_code="service.canal_duplicado")

    secreto = secrets.token_urlsafe(32)
    fila = CanalServicio(
        tenant_id=tenant_id,
        clave=clave,
        nombre=nombre,
        tipo=tipo,
        secreto_hash=_hash(secreto),
        **datos,
    )
    db.add(fila)
    db.flush()
    if not fila.campo_trampa and tipo in ("formulario", "portal"):
        # Se avisa en vez de imponerlo: hay formularios detrás de autenticación
        # donde la trampa sobra. Pero un formulario público sin trampa se llena
        # de basura en una tarde, y eso tiene que decirse al crearlo.
        logger.warning("service.canal_sin_trampa", canal=clave, tenant=str(tenant_id))
    return fila, secreto


def _canal(db: Session, tenant_id: UUID, clave: str, secreto: str) -> CanalServicio:
    fila = db.execute(
        select(CanalServicio).where(
            CanalServicio.tenant_id == tenant_id, CanalServicio.clave == clave
        )
    ).scalar_one_or_none()
    # Mismo error para «no existe» y «clave mala»: distinguirlos convertiría el
    # endpoint en un comprobador de qué canales tiene cada tenant.
    if fila is None or not hmac.compare_digest(fila.secreto_hash, _hash(secreto or "")):
        raise NoAutenticado("Canal o clave no válidos", error_code="service.canal_no_autorizado")
    if not fila.activo:
        raise NoAutenticado("Canal o clave no válidos", error_code="service.canal_no_autorizado")
    return fila


def _pasado_de_tope(db: Session, canal: CanalServicio) -> bool:
    desde = _ahora() - timedelta(hours=1)
    cuantos = int(
        db.execute(
            select(func.count())
            .select_from(Mensaje)
            .join(Conversacion, Conversacion.id == Mensaje.conversacion_id)
            .where(
                Mensaje.tenant_id == canal.tenant_id,
                Mensaje.canal == canal.tipo,
                Mensaje.direccion == ENTRANTE,
                Mensaje.created_at >= desde,
            )
        ).scalar_one()
        or 0
    )
    return cuantos >= canal.max_por_hora


# ── Anti-bucle del correo (CRM-04.02.01.01) ───────────────────────────────

# Cabeceras que marcan un mensaje automático. Están en el estándar y las ponen
# todos los servidores serios; mirarlas es lo que impide el bucle clásico:
# nuestra respuesta automática dispara el «estoy de vacaciones» del cliente, que
# abre un caso, que dispara nuestra respuesta automática, y así toda la noche.
CABECERAS_AUTOMATICAS = (
    "auto-submitted",
    "x-auto-response-suppress",
    "precedence",
    "x-autoreply",
    "list-id",
)
VALORES_AUTOMATICOS = ("auto-replied", "auto-generated", "bulk", "list", "junk", "yes")


def es_automatico(cabeceras: dict[str, str]) -> tuple[bool, str]:
    """Si el mensaje es una respuesta automática, y por qué lo parece.

    Se devuelve el motivo además del veredicto: «tu correo no abrió caso» es una
    incidencia frecuente, y sin el motivo la única respuesta posible es mirar el
    log del servidor de correo.
    """
    normalizadas = {k.lower(): str(v).lower() for k, v in (cabeceras or {}).items()}
    for cabecera in CABECERAS_AUTOMATICAS:
        valor = normalizadas.get(cabecera)
        if valor is None:
            continue
        if cabecera == "auto-submitted" and valor != "no":
            return True, f"{cabecera}: {valor}"
        if cabecera in ("list-id",):
            return True, "viene de una lista de distribución"
        if any(v in valor for v in VALORES_AUTOMATICOS):
            return True, f"{cabecera}: {valor}"
    return False, ""


_REF = re.compile(r"<[^>]+>")


def hilo_de(cabeceras: dict[str, str]) -> str | None:
    """El identificador del mensaje al que responde, según las cabeceras.

    Se mira `In-Reply-To` y, si no está, la **última** referencia de
    `References`: es la más cercana en el hilo. Coger la primera colgaría toda la
    conversación del mensaje original y perdería las ramas.
    """
    normalizadas = {k.lower(): str(v) for k, v in (cabeceras or {}).items()}
    en_respuesta = normalizadas.get("in-reply-to", "").strip()
    if en_respuesta:
        return en_respuesta
    referencias = _REF.findall(normalizadas.get("references", ""))
    return referencias[-1] if referencias else None


# ── Entrada de mensajes ───────────────────────────────────────────────────


def _traducir(canal: CanalServicio, entrada: dict[str, Any]) -> dict[str, Any]:
    salida = dict(canal.fijos or {})
    for destino, origen in (canal.mapeo or {}).items():
        if origen in entrada:
            salida[destino] = entrada[origen]
    return salida


def _conversacion_para(
    db: Session,
    tenant_id: UUID,
    *,
    identidad: str,
    contacto_id: UUID | None,
    cuenta_id: UUID | None,
    canal: str,
    asunto: str,
    ventana_horas: int,
) -> tuple[Conversacion, bool]:
    """La conversación viva de este cliente, o una nueva.

    Se busca por **contacto o identidad externa y no por canal**: es lo que hace
    que el correo del lunes y el chat del miércoles sean el mismo hilo.

    La ventana existe porque una conversación no dura para siempre: sin ella, un
    cliente que escribe cada tres meses tendría un único hilo de dos años que
    nadie puede leer, y el caso al que cuelga sería el de la primera vez.
    """
    desde = _ahora() - timedelta(hours=ventana_horas)
    consulta = select(Conversacion).where(
        Conversacion.tenant_id == tenant_id,
        Conversacion.estado != "cerrada",
        Conversacion.ultimo_mensaje_at >= desde,
    )
    if contacto_id is not None:
        consulta = consulta.where(Conversacion.contacto_id == contacto_id)
    elif identidad:
        consulta = consulta.where(Conversacion.identidad_externa == identidad)
    else:
        consulta = consulta.where(text("false"))

    fila = db.execute(
        consulta.order_by(Conversacion.ultimo_mensaje_at.desc()).limit(1)
    ).scalar_one_or_none()
    if fila is not None:
        return fila, False

    fila = Conversacion(
        tenant_id=tenant_id,
        contacto_id=contacto_id,
        cuenta_id=cuenta_id,
        identidad_externa=identidad,
        canal_actual=canal,
        asunto=asunto[:300],
    )
    db.add(fila)
    db.flush()
    return fila, True


def recibir(
    uow: UnidadDeTrabajo,
    *,
    canal_clave: str,
    secreto: str,
    entrada: dict[str, Any],
    cabeceras: dict[str, str] | None = None,
    ventana_horas: int = 72,
) -> dict[str, Any]:
    """Entra un mensaje por cualquier canal y se convierte en caso o en respuesta.

    Devuelve siempre un resultado y **nunca revela si se creó algo** cuando se
    descarta por trampa: contestar distinto le dice al robot qué cambiar para la
    próxima.
    """
    tenant_id = uow.tenant_id
    canal = _canal(uow.db, tenant_id, canal_clave, secreto)
    cabeceras = cabeceras or {}

    # 1. Trampa. Se descarta con éxito aparente, a propósito.
    if canal.campo_trampa and str(entrada.get(canal.campo_trampa, "")).strip():
        canal.descartados += 1
        return {"aceptado": True, "descartado": "trampa", "caso_id": None}

    # 2. Anti-bucle. Antes del tope, porque un bucle de respuestas automáticas
    # agota el tope en minutos y dejaría fuera a los clientes de verdad.
    automatico, motivo = es_automatico(cabeceras)
    if automatico:
        canal.descartados += 1
        return {"aceptado": True, "descartado": "automatico", "motivo": motivo, "caso_id": None}

    remitente = str(entrada.get("remitente") or entrada.get("from") or "").strip().lower()
    if canal.direccion_propia and remitente == canal.direccion_propia.strip().lower():
        # El mensaje viene de nuestra propia dirección: es nuestra respuesta
        # rebotando. Sin esto, el buzón se contesta a sí mismo indefinidamente.
        canal.descartados += 1
        return {"aceptado": True, "descartado": "propio", "caso_id": None}

    # 3. Tope.
    if _pasado_de_tope(uow.db, canal):
        canal.descartados += 1
        raise LimiteExcedido(
            "Este canal ha superado su tope por hora.",
            error_code="service.canal_tope_superado",
            reintentar_en_s=600,
        )

    # 4. Idempotencia por identificador externo: las pasarelas reintentan, y sin
    # esto un reintento abriría un caso duplicado por cada reintento.
    id_externo = str(entrada.get("id_externo") or cabeceras.get("Message-ID") or "").strip() or None
    if id_externo:
        ya = uow.db.execute(
            select(Mensaje).where(Mensaje.tenant_id == tenant_id, Mensaje.id_externo == id_externo)
        ).scalar_one_or_none()
        if ya is not None:
            return {
                "aceptado": True,
                "duplicado": True,
                "conversacion_id": str(ya.conversacion_id),
                "caso_id": None,
            }

    datos = _traducir(canal, entrada)
    faltan = [c for c in (canal.obligatorios or []) if not str(entrada.get(str(c), "")).strip()]
    if faltan:
        canal.descartados += 1
        return {
            "aceptado": False,
            "descartado": "incompleto",
            "faltan": faltan,
            "caso_id": None,
        }

    asunto = str(datos.get("asunto") or entrada.get("asunto") or "(sin asunto)")
    cuerpo = str(datos.get("cuerpo") or entrada.get("cuerpo") or "")
    contacto_id = datos.get("contacto_id")
    cuenta_id = datos.get("cuenta_id")

    # 5. Hilo: si responde a un mensaje nuestro, va a su conversación.
    responde_a = hilo_de(cabeceras)
    conversacion = None
    if responde_a:
        previo = uow.db.execute(
            select(Mensaje).where(Mensaje.tenant_id == tenant_id, Mensaje.id_externo == responde_a)
        ).scalar_one_or_none()
        if previo is not None:
            conversacion = uow.db.get(Conversacion, previo.conversacion_id)

    nueva = False
    if conversacion is None:
        conversacion, nueva = _conversacion_para(
            uow.db,
            tenant_id,
            identidad=remitente,
            contacto_id=UUID(str(contacto_id)) if contacto_id else None,
            cuenta_id=UUID(str(cuenta_id)) if cuenta_id else None,
            canal=canal.tipo,
            asunto=asunto,
            ventana_horas=ventana_horas,
        )

    mensaje = Mensaje(
        tenant_id=tenant_id,
        conversacion_id=conversacion.id,
        canal=canal.tipo,
        direccion=ENTRANTE,
        remitente=remitente,
        asunto=asunto[:300],
        cuerpo=cuerpo,
        id_externo=id_externo,
        responde_a=responde_a,
        adjuntos=list(entrada.get("adjuntos") or []),
    )
    uow.db.add(mensaje)
    conversacion.ultimo_mensaje_at = _ahora()
    conversacion.canal_actual = canal.tipo
    if conversacion.estado == "esperando":
        conversacion.estado = "abierta"
    canal.recibidos += 1

    # 6. Caso: uno por conversación, y solo si no lo tenía. Abrir uno por mensaje
    # convierte una conversación de seis correos en seis casos, y el cliente
    # recibe seis respuestas distintas de seis personas.
    caso_id = conversacion.caso_id
    if caso_id is None:
        from services.service import servicio as svc

        caso = svc.abrir_caso(
            uow,
            asunto=asunto,
            descripcion=cuerpo,
            origen=canal.tipo,
            contacto_id=conversacion.contacto_id,
            cuenta_id=conversacion.cuenta_id,
            **{
                k: v
                for k, v in (canal.fijos or {}).items()
                if k in ("tipo", "linea", "prioridad", "severidad", "equipo")
            },
        )
        conversacion.caso_id = caso.id
        caso_id = caso.id

    uow.db.flush()
    uow.emitir(
        "case.message.received",
        subject=("conversacion", conversacion.id),
        data={
            "conversacion_id": str(conversacion.id),
            "caso_id": str(caso_id),
            "canal": canal.tipo,
            "nueva": nueva,
        },
        dedup_key=f"msg:{tenant_id}:{id_externo}" if id_externo else None,
    )
    return {
        "aceptado": True,
        "conversacion_id": str(conversacion.id),
        "caso_id": str(caso_id),
        "mensaje_id": str(mensaje.id),
        "conversacion_nueva": nueva,
    }


def responder(
    uow: UnidadDeTrabajo,
    conversacion_id: UUID,
    *,
    cuerpo: str,
    canal: str = "",
    interno: bool = False,
    autor_id: UUID | None = None,
    id_externo: str | None = None,
) -> Mensaje:
    """Respuesta del agente.

    Una respuesta **no interna** marca la primera respuesta del caso: el
    indicador tiene que medir cuándo contestó una persona al cliente, y una nota
    interna no es contestar. Si contaran las notas, el tiempo de primera
    respuesta saldría siempre magnífico y no mediría nada.
    """
    conversacion = uow.db.get(Conversacion, conversacion_id)
    if conversacion is None or conversacion.tenant_id != uow.tenant_id:
        raise NoEncontrado(
            "Conversación no encontrada", error_code="service.conversacion_no_encontrada"
        )

    mensaje = Mensaje(
        tenant_id=conversacion.tenant_id,
        conversacion_id=conversacion.id,
        canal=canal or conversacion.canal_actual,
        direccion=SALIENTE,
        cuerpo=cuerpo,
        interno=interno,
        autor_id=autor_id,
        id_externo=id_externo,
    )
    uow.db.add(mensaje)
    conversacion.ultimo_mensaje_at = _ahora()
    if not interno:
        conversacion.estado = "esperando"
        if conversacion.caso_id is not None:
            from services.service import servicio as svc

            svc.registrar_primera_respuesta(uow, conversacion.caso_id, por=autor_id)
    uow.db.flush()
    return mensaje


# ── Conversación unificada (CRM-04.02.02.01) ──────────────────────────────


def historial(
    db: Session,
    tenant_id: UUID,
    *,
    contacto_id: UUID | None = None,
    identidad: str = "",
    limite: int = 200,
    incluir_internos: bool = True,
) -> list[dict[str, Any]]:
    """Todo lo que este cliente ha hablado con nosotros, por cualquier canal.

    Es la vista que evita preguntar tres veces lo mismo. Va ordenada por tiempo y
    **no agrupada por canal**: agrupar por canal reproduce exactamente el
    problema que esto viene a resolver.

    `incluir_internos` viene en **cierto** porque esta es la vista del agente, y
    las notas internas son justo lo que le ahorra releerse el caso. Quien pinte
    esto en un portal de cliente tiene que pasarlo en **falso**: el parámetro es
    explícito y no se deduce del permiso a propósito, porque deducirlo pondría
    una nota interna delante del cliente el día que alguien reutilizara la
    función desde un sitio nuevo. Cada mensaje lleva además su marca `interno`,
    para que no haya excusa.
    """
    consulta = select(Conversacion).where(Conversacion.tenant_id == tenant_id)
    if contacto_id is not None:
        consulta = consulta.where(Conversacion.contacto_id == contacto_id)
    elif identidad:
        consulta = consulta.where(Conversacion.identidad_externa == identidad)
    else:
        raise ErrorValidacion(
            "Hace falta un contacto o una identidad externa.",
            error_code="service.historial_sin_cliente",
        )

    conversaciones = list(db.execute(consulta).scalars().all())
    if not conversaciones:
        return []
    consulta_mensajes = select(Mensaje).where(
        Mensaje.conversacion_id.in_([c.id for c in conversaciones])
    )
    if not incluir_internos:
        consulta_mensajes = consulta_mensajes.where(Mensaje.interno.is_(False))
    mensajes = (
        db.execute(consulta_mensajes.order_by(Mensaje.created_at.desc()).limit(limite))
        .scalars()
        .all()
    )
    por_id = {c.id: c for c in conversaciones}
    return [
        {
            "at": m.created_at.isoformat(),
            "canal": m.canal,
            "direccion": m.direccion,
            "interno": m.interno,
            "asunto": m.asunto,
            "cuerpo": m.cuerpo[:2000],
            "conversacion_id": str(m.conversacion_id),
            "caso_id": (
                str(por_id[m.conversacion_id].caso_id)
                if por_id[m.conversacion_id].caso_id
                else None
            ),
        }
        for m in reversed(mensajes)
    ]


def transferir_canal(
    uow: UnidadDeTrabajo, conversacion_id: UUID, *, canal: str, motivo: str = ""
) -> Conversacion:
    """Cambia el canal conservando el hilo (CRM-04.02.02.02).

    Cambiar de canal **no abre una conversación nueva**. Si la abriera, pasar de
    chat a correo haría perder todo lo hablado, y el cliente tendría que
    explicarse otra vez — que es exactamente lo que se siente como «me habéis
    pasado con otro y no sabe nada».
    """
    if canal not in CANALES:
        raise ErrorValidacion(
            f"Canal «{canal}» no válido.",
            error_code="service.canal_no_valido",
            detalle={"validos": list(CANALES)},
        )
    conversacion = uow.db.get(Conversacion, conversacion_id)
    if conversacion is None or conversacion.tenant_id != uow.tenant_id:
        raise NoEncontrado(
            "Conversación no encontrada", error_code="service.conversacion_no_encontrada"
        )
    anterior = conversacion.canal_actual
    conversacion.canal_actual = canal
    uow.db.add(
        Mensaje(
            tenant_id=conversacion.tenant_id,
            conversacion_id=conversacion.id,
            canal=canal,
            direccion=SALIENTE,
            cuerpo=f"Conversación trasladada de {anterior} a {canal}. {motivo}".strip(),
            interno=True,
        )
    )
    return conversacion


def escalar_a_humano(
    uow: UnidadDeTrabajo, conversacion_id: UUID, *, motivo: str, resumen: str = ""
) -> dict[str, Any]:
    """Pasa una conversación del bot a una persona (CRM-04.03.02.03).

    Lo que se traspasa es **el contexto completo**, no un aviso. Escalar
    diciendo solo «el cliente quiere hablar con alguien» obliga a la persona a
    leerse la conversación entera mientras el cliente espera, y eso es lo que
    hace que el cliente repita todo lo que ya había contado al bot — que es la
    peor experiencia posible, porque acaba de invertir cinco minutos en contarlo.
    """
    conversacion = uow.db.get(Conversacion, conversacion_id)
    if conversacion is None or conversacion.tenant_id != uow.tenant_id:
        raise NoEncontrado(
            "Conversación no encontrada", error_code="service.conversacion_no_encontrada"
        )
    if not (motivo or "").strip():
        raise ErrorValidacion(
            "Escalar a una persona exige decir por qué.",
            error_code="service.escalado_sin_motivo",
        )

    mensajes = (
        uow.db.execute(
            select(Mensaje)
            .where(Mensaje.conversacion_id == conversacion.id)
            .order_by(Mensaje.created_at)
        )
        .scalars()
        .all()
    )
    conversacion.atendida_por_bot = False
    conversacion.estado = "abierta"
    uow.db.add(
        Mensaje(
            tenant_id=conversacion.tenant_id,
            conversacion_id=conversacion.id,
            canal=conversacion.canal_actual,
            direccion=SALIENTE,
            cuerpo=f"Escalado a persona. Motivo: {motivo}\n\n{resumen}".strip(),
            interno=True,
        )
    )
    uow.db.flush()
    uow.emitir(
        "case.escalated.human",
        subject=("conversacion", conversacion.id),
        data={
            "conversacion_id": str(conversacion.id),
            "caso_id": str(conversacion.caso_id) if conversacion.caso_id else "",
            "motivo": motivo,
            "mensajes": len(mensajes),
        },
    )
    return {
        "conversacion_id": str(conversacion.id),
        "caso_id": str(conversacion.caso_id) if conversacion.caso_id else None,
        "motivo": motivo,
        # El contexto va en la respuesta y no solo en un evento: quien recoge la
        # conversación la abre ahí mismo y tiene que verlo sin buscar.
        "contexto": [
            {
                "at": m.created_at.isoformat(),
                "direccion": m.direccion,
                "canal": m.canal,
                "cuerpo": m.cuerpo[:2000],
            }
            for m in mensajes
            if not m.interno
        ],
    }


# ── Macros (CRM-04.02.02.04) ──────────────────────────────────────────────

_VARIABLE = re.compile(r"\{([a-z_]+)\.([a-z_]+)\}")


def _interpolar(plantilla: str, contexto: dict[str, dict[str, Any]]) -> tuple[str, list[str]]:
    """Rellena la plantilla y **dice qué variables no ha podido resolver**.

    Mandarle al cliente un «Hola {contacto.nombre}» es el error más visible y más
    barato de evitar que hay en un servicio de atención.
    """
    sin_resolver: list[str] = []

    def _sustituir(casa: re.Match[str]) -> str:
        objeto, campo = casa.group(1), casa.group(2)
        valor = (contexto.get(objeto) or {}).get(campo)
        if valor in (None, ""):
            sin_resolver.append(f"{objeto}.{campo}")
            return casa.group(0)
        return str(valor)

    return _VARIABLE.sub(_sustituir, plantilla), sin_resolver


def aplicar_macro(
    uow: UnidadDeTrabajo,
    *,
    macro_clave: str,
    conversacion_id: UUID,
    contexto: dict[str, dict[str, Any]] | None = None,
    autor_id: UUID | None = None,
    forzar: bool = False,
) -> dict[str, Any]:
    """Escribe la respuesta y ejecuta las acciones, de una vez.

    Si quedan variables sin resolver **no se manda** salvo que se fuerce: es la
    diferencia entre una macro que ahorra tiempo y una que manda «Hola
    {contacto.nombre}» a un cliente.

    Es una sola acción a propósito: partida en cuatro clics, la mitad de las
    veces se queda a medias y el caso acaba contestado pero sin clasificar.
    """
    macro = uow.db.execute(
        select(Macro).where(Macro.tenant_id == uow.tenant_id, Macro.clave == macro_clave)
    ).scalar_one_or_none()
    if macro is None or not macro.activa:
        raise NoEncontrado("Macro no encontrada", error_code="service.macro_no_encontrada")

    conversacion = uow.db.get(Conversacion, conversacion_id)
    if conversacion is None or conversacion.tenant_id != uow.tenant_id:
        raise NoEncontrado(
            "Conversación no encontrada", error_code="service.conversacion_no_encontrada"
        )

    cuerpo, sin_resolver = _interpolar(macro.cuerpo, contexto or {})
    if sin_resolver and not forzar:
        raise ErrorValidacion(
            "La macro tiene variables sin resolver y no se ha enviado.",
            error_code="service.macro_variables_sin_resolver",
            detalle={"sin_resolver": sin_resolver},
        )

    mensaje = responder(uow, conversacion.id, cuerpo=cuerpo, autor_id=autor_id)
    aplicadas: dict[str, Any] = {}
    if conversacion.caso_id is not None and macro.acciones:
        from services.service import servicio as svc

        caso = svc.exigir_caso(uow.db, conversacion.caso_id)
        for campo, valor in (macro.acciones or {}).items():
            if campo == "estado":
                svc.cambiar_estado(uow, caso.id, estado=str(valor), motivo=f"macro «{macro.clave}»")
            elif campo == "cerrar":
                svc.cerrar_caso(uow, caso.id, motivo=str(valor))
            elif hasattr(caso, campo):
                setattr(caso, campo, valor)
            else:
                # Una acción que no se puede aplicar no se ignora en silencio: se
                # dice. Ignorarla haría que la macro pareciera funcionar y el
                # caso quedara a medias sin que nadie lo notara.
                aplicadas.setdefault("no_aplicadas", []).append(campo)
                continue
            aplicadas[campo] = valor

    macro.usos += 1
    registrar(
        uow.db,
        accion="servicio.macro_aplicada",
        objeto="conversacion",
        objeto_id=conversacion.id,
        datos={"macro": macro.clave, "acciones": aplicadas, "forzada": forzar},
        tenant_id=uow.tenant_id,
    )
    return {
        "mensaje_id": str(mensaje.id),
        "acciones": aplicadas,
        "variables_sin_resolver": sin_resolver,
    }


# ── Consola embebible (CRM-04.02.02.08) ───────────────────────────────────


def consola(db: Session, tenant_id: UUID, agente_id: UUID) -> dict[str, Any]:
    """Todo lo que necesita una consola de agente, en una llamada.

    Una sola llamada y no seis a propósito: una consola que abre seis peticiones
    para pintar una pantalla tarda lo que tarde la más lenta, y el agente lo ve
    como un producto lento aunque cinco vayan rápido.

    Devuelve **datos y no pantallas**: es lo que permite empotrarla en el front
    oficial, en el portal del cliente o en el producto del propio cliente sin
    reimplementar nada (CRM-04.02.02.08).
    """
    from services.service import operacion as ope
    from services.service.modelos import Caso

    mias = (
        db.execute(
            select(Conversacion)
            .where(
                Conversacion.tenant_id == tenant_id,
                Conversacion.agente_id == agente_id,
                Conversacion.estado != "cerrada",
            )
            .order_by(Conversacion.ultimo_mensaje_at.desc().nulls_last())
            .limit(50)
        )
        .scalars()
        .all()
    )
    casos = (
        db.execute(
            select(Caso)
            .where(
                Caso.tenant_id == tenant_id,
                Caso.owner_id == agente_id,
                Caso.estado.not_in(("resuelto", "cerrado")),
                Caso.deleted_at.is_(None),
            )
            .order_by(Caso.vence_resolucion_at.asc().nulls_last())
            .limit(50)
        )
        .scalars()
        .all()
    )
    agente = db.execute(
        select(ope.AgenteServicio).where(
            ope.AgenteServicio.tenant_id == tenant_id,
            ope.AgenteServicio.usuario_id == agente_id,
        )
    ).scalar_one_or_none()
    macros = (
        db.execute(
            select(Macro)
            .where(Macro.tenant_id == tenant_id, Macro.activa.is_(True))
            .order_by(Macro.usos.desc(), Macro.nombre)
            .limit(30)
        )
        .scalars()
        .all()
    )

    ahora = _ahora()
    return {
        "agente": {
            "usuario_id": str(agente_id),
            "presencia": agente.presencia if agente else "fuera",
            "capacidad": (agente.capacidad if agente else {}) or {},
            "competencias": (agente.competencias if agente else []) or [],
        },
        "mis_casos": [
            {
                "caso_id": str(c.id),
                "codigo": c.codigo,
                "asunto": c.asunto,
                "prioridad": c.prioridad,
                "estado": c.estado,
                "minutos_restantes": (
                    int(
                        (
                            (
                                c.vence_resolucion_at
                                if c.vence_resolucion_at.tzinfo
                                else c.vence_resolucion_at.replace(tzinfo=timezone.utc)
                            )
                            - ahora
                        ).total_seconds()
                        // 60
                    )
                    if c.vence_resolucion_at
                    else None
                ),
            }
            for c in casos
        ],
        "mis_conversaciones": [
            {
                "conversacion_id": str(c.id),
                "canal": c.canal_actual,
                "asunto": c.asunto,
                "estado": c.estado,
                "ultimo_mensaje_at": (
                    c.ultimo_mensaje_at.isoformat() if c.ultimo_mensaje_at else None
                ),
            }
            for c in mias
        ],
        "macros": [{"clave": m.clave, "nombre": m.nombre, "canales": m.canales} for m in macros],
        # Las macros van ordenadas por uso: la que se usa cuarenta veces al día
        # tiene que estar la primera, y ordenarlas alfabéticamente obliga a
        # buscarla cada vez.
        "orden_macros": "por uso",
    }
