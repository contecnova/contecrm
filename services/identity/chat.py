"""Chat interno: canales, grupos, directos y mensajes (CRM-06.02.02).

Existe porque media conversación de un CRM ocurre fuera de él. Se habla de una
oportunidad en otra herramienta, se decide algo, y lo que queda en el CRM es
una etapa cambiada sin el porqué. Seis meses después nadie sabe por qué se bajó
aquel precio.

**Lo que lo diferencia de un chat cualquiera** —y es la razón de tenerlo aquí y
no de poner un enlace a Teams— es que una conversación puede **colgar de un
registro**. No es «un canal donde además pegamos enlaces»: es la conversación
de *esta* oportunidad, que se abre desde su ficha y se lee con el importe y la
etapa al lado. Un chat genérico obliga a copiar el enlace y a que quien lo
recibe cambie de aplicación, y eso es exactamente donde se pierde el contexto.

Se apoya en lo que ya hay en vez de duplicarlo:

  * las **menciones** avisan por el mismo camino que todo lo demás
    —`crmcore.datos.seguimiento`—, así que respetan las preferencias por canal
    y aparecen en la misma bandeja. Un chat con su propio sistema de avisos
    obliga a configurar dos veces y a mirar en dos sitios.
  * el **borrado** va a la papelera del servicio, como cualquier otro registro.
  * el **aislamiento** por tenant lo pone el guard del ORM, no un `where` aquí.

Lo que NO hay, dicho claro: llamadas, vídeo ni grabaciones. Eso es una
herramienta de comunicaciones, no un CRM, y hacerlo a medias sería peor que no
hacerlo — la mitad de una videollamada es una videollamada que no funciona.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado, Prohibido
from crmcore.ids import nuevo_id
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

# Los tres tipos de conversación. Cerrado a propósito: cada uno tiene reglas
# distintas de quién entra y quién ve, y un cuarto tipo «otro» sería un tipo sin
# reglas, es decir, sin permisos.
#
#   canal    abierto al equipo; se entra y se sale
#   grupo    lista fija de personas, con nombre
#   directo  dos personas, sin nombre y sin invitados
TIPOS = ("canal", "grupo", "directo")  # CRM-06.02.02.01

# Estados de presencia. Se declaran porque el front pinta un color por cada uno
# y un estado inventado se pintaría como «desconocido», que no dice nada.
PRESENCIAS = ("disponible", "ocupado", "ausente", "no_molestar", "desconectado")  # CRM-06.02.02.06

# Reacciones admitidas. Una lista cerrada y corta, no un emoji libre: con emoji
# libre, la misma reacción se escribe de cinco maneras y contar «cuántos lo han
# aprobado» deja de ser posible.
REACCIONES = ("👍", "👎", "✅", "❓", "🎉", "👀")  # CRM-06.02.02.03


class ConversacionChat(Base, TimestampMixin, SoftDeleteMixin):
    """Un canal, un grupo o un directo."""

    __tablename__ = "chat_conversaciones"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    tipo: Mapped[str] = mapped_column(
        String(10), nullable=False, default="canal", info={"opciones": TIPOS}
    )
    # La clave solo la tienen los canales: es lo que permite escribir `#ventas`
    # y que sea siempre el mismo sitio.
    clave: Mapped[str | None] = mapped_column(String(80), nullable=True)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    proposito: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    privada: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # El anclaje al registro. Es lo que distingue este chat de uno cualquiera:
    # la conversación de una oportunidad se abre desde su ficha y no hay que
    # pegar ningún enlace.
    # CRM-06.02.02.02
    objeto_tipo: Mapped[str | None] = mapped_column(String(60), nullable=True)
    objeto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    creada_por: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    ultimo_mensaje_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_chat_conversacion_clave"),
        # Una sola conversación por registro: dos serían dos sitios donde mirar
        # lo que se dijo de la misma oportunidad, que es peor que ninguno.
        UniqueConstraint(
            "tenant_id", "objeto_tipo", "objeto_id", name="uq_chat_conversacion_objeto"
        ),
        Index("ix_chat_conversacion_reciente", "tenant_id", "ultimo_mensaje_at"),
    )


class MiembroConversacion(Base, TimestampMixin):
    """Quién está en una conversación y hasta dónde ha leído."""

    __tablename__ = "chat_miembros"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    conversacion_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("chat_conversaciones.id", ondelete="CASCADE"),
        nullable=False,
    )
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    rol: Mapped[str] = mapped_column(String(10), nullable=False, default="miembro")
    silenciada: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Hasta cuándo ha leído. Se guarda la FECHA y no el último mensaje leído: con
    # el identificador, un mensaje que llega desordenado —o uno borrado— deja el
    # contador de no leídos en un número que no se corresponde con nada.
    leido_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("conversacion_id", "usuario_id", name="uq_chat_miembro"),
        Index("ix_chat_miembro_usuario", "tenant_id", "usuario_id"),
    )


class MensajeChat(Base, TimestampMixin, SoftDeleteMixin):
    """Lo que alguien ha dicho. La papelera es CRM-06.02.02.09."""

    __tablename__ = "chat_mensajes"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    conversacion_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("chat_conversaciones.id", ondelete="CASCADE"),
        nullable=False,
    )
    autor_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    cuerpo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # El hilo: un mensaje que responde a otro. Sin hilos, una conversación con
    # dos temas a la vez es ilegible, y con hilos de verdad —no «citas»— cada
    # tema se sigue por separado.
    responde_a_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("chat_mensajes.id", ondelete="SET NULL"), nullable=True
    )
    # Historial de ediciones. Se guarda lo anterior y no solo la marca de
    # «editado»: en una conversación donde se decide algo, saber qué decía antes
    # es justo lo que hace falta cuando alguien lo discute.
    versiones: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    editado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    menciones: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    adjuntos: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (
        Index("ix_chat_mensaje_conversacion", "tenant_id", "conversacion_id", "created_at"),
        Index("ix_chat_mensaje_hilo", "responde_a_id"),
    )


class ReaccionMensaje(Base, TimestampMixin):
    """Una reacción de alguien a un mensaje."""

    __tablename__ = "chat_reacciones"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    mensaje_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("chat_mensajes.id", ondelete="CASCADE"), nullable=False
    )
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    emoji: Mapped[str] = mapped_column(String(8), nullable=False, info={"opciones": REACCIONES})

    __table_args__ = (
        UniqueConstraint("mensaje_id", "usuario_id", "emoji", name="uq_chat_reaccion"),
    )


class Presencia(Base, TimestampMixin):
    """Si alguien está y desde cuándo no se le ve."""

    __tablename__ = "chat_presencia"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, default="disponible", info={"opciones": PRESENCIAS}
    )
    # El estado escrito: «en un cliente hasta las 5». Vale más que el color,
    # porque responde a la pregunta de verdad —¿espero o llamo?—.
    mensaje: Mapped[str] = mapped_column(String(140), nullable=False, default="")
    visto_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "usuario_id", name="uq_chat_presencia"),)


# ── Reglas ────────────────────────────────────────────────────────────────


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def conversacion(db: Session, conversacion_id: UUID) -> ConversacionChat:
    fila = db.get(ConversacionChat, conversacion_id)
    if fila is None:
        raise NoEncontrado("Esa conversación no existe", error_code="chat.no_existe")
    return fila


def es_miembro(db: Session, conversacion_id: UUID, usuario_id: UUID) -> MiembroConversacion | None:
    return db.execute(
        select(MiembroConversacion).where(
            MiembroConversacion.conversacion_id == conversacion_id,
            MiembroConversacion.usuario_id == usuario_id,
        )
    ).scalar_one_or_none()


def exigir_miembro(db: Session, conversacion_id: UUID, usuario_id: UUID) -> MiembroConversacion:
    """Quien no está en la conversación no la lee.

    Y se contesta **404 y no 403**: decir «existe pero no puedes» sobre un
    canal privado confirma que ese canal existe, y el nombre de un canal
    —«despido-javier», «due-diligence»— ya es información.
    """
    miembro = es_miembro(db, conversacion_id, usuario_id)
    if miembro is None:
        raise NoEncontrado("Esa conversación no existe", error_code="chat.no_existe")
    return miembro


def crear_conversacion(
    db: Session,
    *,
    tenant_id: UUID,
    creada_por: UUID,
    tipo: str = "canal",
    clave: str = "",
    nombre: str = "",
    proposito: str = "",
    privada: bool = False,
    objeto_tipo: str | None = None,
    objeto_id: UUID | None = None,
    miembros: list[UUID] | None = None,
) -> ConversacionChat:
    """Abre una conversación y mete a quien va dentro.

    El directo es un caso aparte: **no se crea dos veces**. Quien escribe a
    alguien con quien ya habló espera seguir la misma conversación, no abrir una
    nueva vacía al lado de la que tiene el histórico.
    """
    if tipo not in TIPOS:
        raise ErrorValidacion(
            f"Tipo de conversación desconocido: «{tipo}»",
            error_code="chat.tipo_desconocido",
            detalle={"admitidos": list(TIPOS)},
        )

    personas = sorted({*(miembros or []), creada_por})

    if tipo == "directo":
        if len(personas) != 2:
            raise ErrorValidacion(
                "Un directo es entre dos personas. Para más, es un grupo.",
                error_code="chat.directo_no_es_de_dos",
            )
        existente = _directo_entre(db, tenant_id, personas[0], personas[1])
        if existente is not None:
            return existente

    if tipo == "canal" and not clave:
        raise ErrorValidacion(
            "Un canal necesita clave: es lo que permite nombrarlo siempre igual.",
            error_code="chat.canal_sin_clave",
        )
    if tipo != "canal" and clave:
        raise ErrorValidacion(
            "Solo los canales tienen clave.", error_code="chat.clave_fuera_de_canal"
        )

    if objeto_tipo and objeto_id:
        ya = db.execute(
            select(ConversacionChat).where(
                ConversacionChat.objeto_tipo == objeto_tipo, ConversacionChat.objeto_id == objeto_id
            )
        ).scalar_one_or_none()
        if ya is not None:
            return ya

    fila = ConversacionChat(
        tenant_id=tenant_id,
        tipo=tipo,
        clave=clave or None,
        nombre=nombre,
        proposito=proposito,
        privada=privada or tipo != "canal",
        objeto_tipo=objeto_tipo,
        objeto_id=objeto_id,
        creada_por=creada_por,
    )
    db.add(fila)
    db.flush()
    for usuario_id in personas:
        db.add(
            MiembroConversacion(
                tenant_id=tenant_id,
                conversacion_id=fila.id,
                usuario_id=usuario_id,
                rol="dueno" if usuario_id == creada_por else "miembro",
            )
        )
    db.flush()
    return fila


def _directo_entre(db: Session, tenant_id: UUID, uno: UUID, otro: UUID) -> ConversacionChat | None:
    candidatas = (
        db.execute(
            select(ConversacionChat.id).where(
                ConversacionChat.tenant_id == tenant_id, ConversacionChat.tipo == "directo"
            )
        )
        .scalars()
        .all()
    )
    for cid in candidatas:
        miembros = set(
            db.execute(
                select(MiembroConversacion.usuario_id).where(
                    MiembroConversacion.conversacion_id == cid
                )
            )
            .scalars()
            .all()
        )
        if miembros == {uno, otro}:
            return db.get(ConversacionChat, cid)
    return None


def añadir_miembro(
    db: Session, *, conversacion_id: UUID, usuario_id: UUID, tenant_id: UUID
) -> MiembroConversacion:
    fila = conversacion(db, conversacion_id)
    if fila.tipo == "directo":
        raise Conflicto(
            "A un directo no se añade gente: lo que se quiere es un grupo, y un "
            "grupo nuevo no arrastra lo que ya se dijo en privado.",
            error_code="chat.directo_no_admite_miembros",
        )
    ya = es_miembro(db, conversacion_id, usuario_id)
    if ya is not None:
        return ya
    miembro = MiembroConversacion(
        tenant_id=tenant_id, conversacion_id=conversacion_id, usuario_id=usuario_id
    )
    db.add(miembro)
    db.flush()
    return miembro


def enviar(
    db: Session,
    *,
    tenant_id: UUID,
    conversacion_id: UUID,
    autor_id: UUID,
    cuerpo: str,
    responde_a_id: UUID | None = None,
    menciones: list[UUID] | None = None,
    adjuntos: list[dict[str, Any]] | None = None,
) -> MensajeChat:
    """Escribe un mensaje y avisa a quien se menciona.

    El aviso va por `crmcore.datos.seguimiento`, el mismo camino que todo lo
    demás: así respeta las preferencias por canal de cada quien y aparece en la
    misma bandeja. Un chat con su propio sistema de avisos obliga a configurar
    dos veces y a mirar en dos sitios, y lo que pasa es que se mira en ninguno.
    """
    exigir_miembro(db, conversacion_id, autor_id)
    if not cuerpo.strip() and not adjuntos:
        raise ErrorValidacion("Un mensaje vacío no dice nada.", error_code="chat.mensaje_vacio")
    if responde_a_id is not None:
        padre = db.get(MensajeChat, responde_a_id)
        if padre is None or padre.conversacion_id != conversacion_id:
            raise ErrorValidacion(
                "Se responde a un mensaje de esta misma conversación.",
                error_code="chat.hilo_de_otra_conversacion",
            )

    fila = MensajeChat(
        tenant_id=tenant_id,
        conversacion_id=conversacion_id,
        autor_id=autor_id,
        cuerpo=cuerpo,
        responde_a_id=responde_a_id,
        menciones=[str(m) for m in (menciones or [])],
        adjuntos=adjuntos or [],
    )
    db.add(fila)
    conversacion(db, conversacion_id).ultimo_mensaje_at = _ahora()
    db.flush()

    if menciones:
        _avisar_menciones(db, tenant_id=tenant_id, mensaje=fila, menciones=menciones)
    return fila


def _avisar_menciones(
    db: Session, *, tenant_id: UUID, mensaje: MensajeChat, menciones: list[UUID]
) -> None:
    # CRM-06.02.02.04: el aviso va por el mismo camino que todo lo demás.
    from crmcore.datos.seguimiento import notificar

    charla = conversacion(db, mensaje.conversacion_id)
    # Solo se avisa a quien está dentro: mencionar a alguien que no puede leer
    # la conversación le manda a una pantalla que le dirá que no existe.
    dentro = [u for u in menciones if es_miembro(db, mensaje.conversacion_id, u) is not None]
    if not dentro:
        return
    notificar(
        db,
        tenant_id=tenant_id,
        tipo="chat.mencion",
        titulo=f"Te han mencionado en {charla.nombre or charla.clave or 'una conversación'}",
        cuerpo=mensaje.cuerpo[:200],
        objeto_tipo="conversacion_chat",
        objeto_id=charla.id,
        usuarios=dentro,
        excluir=[mensaje.autor_id],
        datos={"conversacion_id": str(charla.id), "mensaje_id": str(mensaje.id)},
    )


def editar(db: Session, *, mensaje_id: UUID, autor_id: UUID, cuerpo: str) -> MensajeChat:
    """Corrige un mensaje, guardando lo que decía antes.

    Solo lo edita quien lo escribió. Que un administrador pueda reescribir lo
    que dijo otro convierte el histórico en algo que no se puede citar, y la
    única razón para tener el histórico es poder citarlo.
    """
    fila = db.get(MensajeChat, mensaje_id)
    if fila is None:
        raise NoEncontrado("Ese mensaje no existe", error_code="chat.mensaje_no_existe")
    if fila.autor_id != autor_id:
        raise Prohibido("Solo edita un mensaje quien lo escribió.", error_code="chat.edicion_ajena")
    fila.versiones = [
        *(fila.versiones or []),
        {"cuerpo": fila.cuerpo, "hasta": _ahora().isoformat()},
    ]
    fila.cuerpo = cuerpo
    fila.editado_at = _ahora()
    db.flush()
    return fila


def reaccionar(
    db: Session, *, tenant_id: UUID, mensaje_id: UUID, usuario_id: UUID, emoji: str
) -> bool:
    """Pone o quita una reacción. Devuelve si quedó puesta.

    Es un interruptor y no dos operaciones: pulsar dos veces el mismo emoji es
    quitarlo, que es lo que espera cualquiera que haya usado un chat.
    """
    if emoji not in REACCIONES:
        raise ErrorValidacion(
            f"Reacción no admitida: «{emoji}»",
            error_code="chat.reaccion_no_admitida",
            detalle={"admitidas": list(REACCIONES)},
        )
    mensaje = db.get(MensajeChat, mensaje_id)
    if mensaje is None:
        raise NoEncontrado("Ese mensaje no existe", error_code="chat.mensaje_no_existe")
    exigir_miembro(db, mensaje.conversacion_id, usuario_id)

    ya = db.execute(
        select(ReaccionMensaje).where(
            ReaccionMensaje.mensaje_id == mensaje_id,
            ReaccionMensaje.usuario_id == usuario_id,
            ReaccionMensaje.emoji == emoji,
        )
    ).scalar_one_or_none()
    if ya is not None:
        db.delete(ya)
        db.flush()
        return False
    db.add(
        ReaccionMensaje(
            tenant_id=tenant_id, mensaje_id=mensaje_id, usuario_id=usuario_id, emoji=emoji
        )
    )
    db.flush()
    return True


def marcar_leido(db: Session, *, conversacion_id: UUID, usuario_id: UUID) -> datetime:
    """Hasta dónde ha leído esta persona (CRM-06.02.02.05)."""
    miembro = exigir_miembro(db, conversacion_id, usuario_id)
    miembro.leido_hasta = _ahora()
    db.flush()
    return miembro.leido_hasta


def sin_leer(db: Session, *, tenant_id: UUID, usuario_id: UUID) -> dict[str, int]:
    """Cuántos mensajes sin leer hay en cada conversación de esta persona.

    Se cuenta con una consulta por conversación y no con una sola agregada
    porque cada una tiene su propio corte de lectura; hacerlo de otra forma
    exigiría un `join` con condición por fila que no simplifica nada.
    """
    from sqlalchemy import func

    salida: dict[str, int] = {}
    miembros = (
        db.execute(
            select(MiembroConversacion).where(
                MiembroConversacion.tenant_id == tenant_id,
                MiembroConversacion.usuario_id == usuario_id,
            )
        )
        .scalars()
        .all()
    )
    for miembro in miembros:
        consulta = (
            select(func.count())
            .select_from(MensajeChat)
            .where(
                MensajeChat.conversacion_id == miembro.conversacion_id,
                MensajeChat.autor_id != usuario_id,
            )
        )
        if miembro.leido_hasta is not None:
            consulta = consulta.where(MensajeChat.created_at > miembro.leido_hasta)
        salida[str(miembro.conversacion_id)] = int(db.execute(consulta).scalar_one_or_none() or 0)
    return salida


def fijar_presencia(
    db: Session, *, tenant_id: UUID, usuario_id: UUID, estado: str, mensaje: str = ""
) -> Presencia:
    if estado not in PRESENCIAS:
        raise ErrorValidacion(
            f"Estado de presencia desconocido: «{estado}»",
            error_code="chat.presencia_desconocida",
            detalle={"admitidos": list(PRESENCIAS)},
        )
    fila = db.execute(
        select(Presencia).where(
            Presencia.tenant_id == tenant_id, Presencia.usuario_id == usuario_id
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = Presencia(tenant_id=tenant_id, usuario_id=usuario_id)
        db.add(fila)
    fila.estado = estado
    fila.mensaje = mensaje
    fila.visto_at = _ahora()
    db.flush()
    return fila
