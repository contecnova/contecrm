"""Seguimiento de registros y notificaciones (CRM-06.02.01.02).

«Avísame cuando cambie esto.» Es la funcionalidad que hace que un CRM se use de
verdad: sin ella la gente entra a mirar si ha pasado algo, y como casi nunca ha
pasado, deja de entrar.

Dos piezas que conviene no confundir:

* **Seguir** un registro es una suscripción explícita de una persona a un
  objeto. Se sigue lo propio automáticamente, y lo demás a mano.
* **Notificar** es entregar un hecho a quien lo sigue, por los canales que esa
  persona tenga configurados.

**Las notificaciones se agrupan.** Una oportunidad que cambia cinco veces en
diez minutos genera **una** notificación, no cinco. Sin agrupar, la bandeja se
convierte en ruido y la gente la silencia entera — que es la forma de perder el
canal para siempre, incluido lo que sí importaba.

**Preferencias por persona y por tipo.** Quien no quiere correo por cada nota
pero sí por cada caso escalado tiene que poder decirlo, y por eso la matriz es
(tipo de evento × canal) y no un interruptor global.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
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

from crmcore.db.base import Base
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Canales de entrega. La lista es cerrada porque cada uno tiene su entregador;
# añadir uno es añadir código, no configuración.
CANALES = ("app", "correo", "push", "sms", "webhook")

# Motivos por los que alguien sigue un registro. Se guarda el motivo y no solo
# el hecho porque de él depende si se puede dejar de seguir: al propietario de
# un caso no se le deja desuscribirse de su propio caso.
MOTIVOS = {
    "propietario": "Es suyo",
    "manual": "Lo pidió",
    "mencion": "Lo mencionaron",
    "equipo": "Es de su equipo",
    "participante": "Participa en él",
}


class Seguimiento(Base):
    """Una persona sigue un registro."""

    __tablename__ = "seguimientos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    objeto_tipo: Mapped[str] = mapped_column(String(60), nullable=False)
    objeto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    motivo: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    # Silenciado: sigue el registro pero no quiere avisos ahora. Distinto de no
    # seguirlo — al dejar de silenciar vuelve sin tener que buscarlo de nuevo.
    silenciado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "usuario_id", "objeto_tipo", "objeto_id", name="uq_seguimiento"
        ),
        Index("ix_seguimientos_objeto", "tenant_id", "objeto_tipo", "objeto_id"),
        Index("ix_seguimientos_usuario", "tenant_id", "usuario_id", "created_at"),
    )


class PreferenciaNotificacion(Base):
    """Qué canales quiere una persona para un tipo de evento.

    Sin fila = valores por defecto. No se siembran filas al crear el usuario a
    propósito: así, cambiar el defecto del producto afecta a todo el que no lo
    haya tocado, en vez de solo a los usuarios nuevos.
    """

    __tablename__ = "preferencias_notificacion"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    # `*` vale para «cualquier tipo»: es la fila que usa quien quiere apagar el
    # correo entero sin enumerar treinta tipos de evento.
    tipo: Mapped[str] = mapped_column(String(80), nullable=False, default="*")
    canales: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Minutos de agrupación: los hechos del mismo tipo dentro de la ventana se
    # entregan en una sola notificación. 0 = entrega inmediata.
    agrupar_minutos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Horas de silencio: [22, 8] no molesta entre las diez de la noche y las
    # ocho de la mañana. Lo urgente pasa igual (ver `notificar`).
    silencio_desde: Mapped[int | None] = mapped_column(Integer, nullable=True)
    silencio_hasta: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "usuario_id", "tipo", name="uq_preferencia_notificacion"),
        Index("ix_preferencias_usuario", "tenant_id", "usuario_id"),
    )


class Notificacion(Base):
    """Un aviso entregado a una persona."""

    __tablename__ = "notificaciones"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    tipo: Mapped[str] = mapped_column(String(80), nullable=False)
    titulo: Mapped[str] = mapped_column(String(300), nullable=False)
    cuerpo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    objeto_tipo: Mapped[str | None] = mapped_column(String(60), nullable=True)
    objeto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # baja | normal | alta | urgente. `urgente` atraviesa el horario de silencio.
    prioridad: Mapped[str] = mapped_column(String(10), nullable=False, default="normal")

    canales: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    datos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    leida_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Cuántos hechos se agruparon en esta notificación. 1 = solo uno.
    agrupadas: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Instante a partir del cual se puede entregar. Con agrupación, se adelanta
    # la entrega al final de la ventana y hasta entonces se siguen sumando
    # hechos a la misma fila.
    entregar_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    entregada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_notificaciones_bandeja", "tenant_id", "usuario_id", "leida_at", "created_at"),
        Index("ix_notificaciones_pendientes", "tenant_id", "entregada_at", "entregar_at"),
    )


# ── Seguir / dejar de seguir ──────────────────────────────────────────────


def seguir(
    db: Session,
    *,
    tenant_id: UUID,
    usuario_id: UUID,
    objeto_tipo: str,
    objeto_id: UUID,
    motivo: str = "manual",
) -> Seguimiento:
    """Suscribe a alguien a un registro. Idempotente.

    Si ya lo sigue, se **mejora el motivo** cuando el nuevo es más fuerte:
    quien seguía una cuenta a mano y luego pasa a ser su propietario ya no puede
    dejar de seguirla, y eso tiene que reflejarse.
    """
    ya = db.execute(
        select(Seguimiento).where(
            Seguimiento.tenant_id == tenant_id,
            Seguimiento.usuario_id == usuario_id,
            Seguimiento.objeto_tipo == objeto_tipo,
            Seguimiento.objeto_id == objeto_id,
        )
    ).scalar_one_or_none()
    if ya is not None:
        if motivo == "propietario" and ya.motivo != "propietario":
            ya.motivo = motivo
        return ya

    fila = Seguimiento(
        tenant_id=tenant_id,
        usuario_id=usuario_id,
        objeto_tipo=objeto_tipo,
        objeto_id=objeto_id,
        motivo=motivo if motivo in MOTIVOS else "manual",
    )
    db.add(fila)
    db.flush()
    return fila


def dejar_de_seguir(
    db: Session, *, tenant_id: UUID, usuario_id: UUID, objeto_tipo: str, objeto_id: UUID
) -> bool:
    """Quita la suscripción. Devuelve si había algo que quitar.

    Al propietario se le **silencia** en vez de desuscribirle: no puede dejar de
    ser responsable de su registro, pero sí puede querer dejar de recibir avisos
    de él. Borrar la fila haría que al siguiente cambio volviera a suscribirse
    solo, y el usuario viviría un bucle de «ya he dicho que no».
    """
    fila = db.execute(
        select(Seguimiento).where(
            Seguimiento.tenant_id == tenant_id,
            Seguimiento.usuario_id == usuario_id,
            Seguimiento.objeto_tipo == objeto_tipo,
            Seguimiento.objeto_id == objeto_id,
        )
    ).scalar_one_or_none()
    if fila is None:
        return False
    if fila.motivo == "propietario":
        fila.silenciado = True
        return True
    db.delete(fila)
    return True


def seguidores(
    db: Session,
    *,
    tenant_id: UUID,
    objeto_tipo: str,
    objeto_id: UUID,
    incluir_silenciados: bool = False,
) -> list[UUID]:
    """Quién sigue este registro."""
    consulta = select(Seguimiento.usuario_id).where(
        Seguimiento.tenant_id == tenant_id,
        Seguimiento.objeto_tipo == objeto_tipo,
        Seguimiento.objeto_id == objeto_id,
    )
    if not incluir_silenciados:
        consulta = consulta.where(Seguimiento.silenciado.is_(False))
    return list(db.execute(consulta).scalars().all())


# ── Preferencias y entrega ────────────────────────────────────────────────


def preferencia(
    db: Session, *, tenant_id: UUID, usuario_id: UUID, tipo: str
) -> PreferenciaNotificacion | None:
    """La preferencia que aplica: la del tipo exacto, o la genérica `*`.

    La específica gana sobre la genérica, siempre. «Nada de correo salvo los
    casos escalados» es la petición normal, y con la genérica ganando sería
    imposible de expresar.
    """
    filas = (
        db.execute(
            select(PreferenciaNotificacion).where(
                PreferenciaNotificacion.tenant_id == tenant_id,
                PreferenciaNotificacion.usuario_id == usuario_id,
                PreferenciaNotificacion.tipo.in_((tipo, "*")),
            )
        )
        .scalars()
        .all()
    )
    exacta = next((f for f in filas if f.tipo == tipo), None)
    return exacta or next((f for f in filas if f.tipo == "*"), None)


def _en_silencio(pref: PreferenciaNotificacion | None, momento: datetime) -> bool:
    """Si el instante cae en la franja de silencio de esa persona.

    Contempla la franja que **cruza la medianoche** (22 → 8), que es la normal.
    Tratarla como un intervalo simple haría que 22 > 8 no encajara nunca y la
    franja no funcionara justo en el caso para el que se configura.
    """
    if pref is None or pref.silencio_desde is None or pref.silencio_hasta is None:
        return False
    hora = momento.hour
    desde, hasta = pref.silencio_desde, pref.silencio_hasta
    if desde > hasta:  # cruza la medianoche: 22 → 8
        return hora >= desde or hora < hasta
    return desde <= hora < hasta


def notificar(
    db: Session,
    *,
    tenant_id: UUID,
    tipo: str,
    titulo: str,
    cuerpo: str = "",
    objeto_tipo: str | None = None,
    objeto_id: UUID | None = None,
    prioridad: str = "normal",
    datos: dict[str, Any] | None = None,
    usuarios: list[UUID] | None = None,
    excluir: list[UUID] | None = None,
    canales_por_defecto: tuple[str, ...] = ("app",),
    canales_forzados: tuple[str, ...] = (),
) -> list[Notificacion]:
    """Crea las notificaciones para quien siga el registro.

    `excluir` sirve para no avisar a quien provocó el cambio: recibir un correo
    de «has cambiado la etapa» justo después de cambiarla es la clase de aviso
    que enseña a ignorarlos todos.

    Devuelve las notificaciones creadas o actualizadas. **No las entrega**: la
    entrega por cada canal la hace el repartidor, leyendo `entregar_at`. Separar
    las dos cosas es lo que permite que crear una notificación no dependa de que
    el servidor de correo conteste.
    """
    destinatarios = usuarios
    if destinatarios is None:
        if objeto_tipo is None or objeto_id is None:
            raise ValueError("Sin destinatarios explícitos hace falta el objeto que se sigue")
        destinatarios = seguidores(
            db, tenant_id=tenant_id, objeto_tipo=objeto_tipo, objeto_id=objeto_id
        )

    fuera = set(excluir or [])
    ahora = datetime.now(timezone.utc)
    creadas: list[Notificacion] = []

    for usuario_id in dict.fromkeys(d for d in destinatarios if d not in fuera):
        pref = preferencia(db, tenant_id=tenant_id, usuario_id=usuario_id, tipo=tipo)
        # Con preferencia, manda SIEMPRE lo que diga —incluso una lista vacía,
        # que significa «no me avises de esto». Tratar la lista vacía como
        # «sin preferencia» y caer al valor por defecto haría que apagar todos
        # los canales no apagara nada, que es exactamente lo contrario de lo
        # que el usuario acaba de pedir.
        canales = list(pref.canales) if pref is not None else list(canales_por_defecto)
        # `canales_forzados` se salta la preferencia, y hay que usarlo con
        # cuidado: es para el aviso que **tiene** que salir por un canal —una
        # confirmación de pedido, un enlace de aprobación— y no para el aviso de
        # movimiento, que es justo lo que la preferencia existe para acotar.
        # Abusar de esto es cómo un sistema de avisos se gana que lo filtren.
        if canales_forzados:
            canales = list(dict.fromkeys([*canales, *canales_forzados]))
        if not canales:
            continue

        # Lo urgente atraviesa el silencio; lo demás se retiene hasta que acabe.
        # No se descarta: lo que pasó de noche sigue habiendo pasado.
        entregar_at = ahora
        if _en_silencio(pref, ahora) and prioridad != "urgente":
            entregar_at = _fin_del_silencio(pref, ahora)

        ventana = pref.agrupar_minutos if pref else 0
        if ventana > 0:
            abierta = db.execute(
                select(Notificacion)
                .where(
                    Notificacion.tenant_id == tenant_id,
                    Notificacion.usuario_id == usuario_id,
                    Notificacion.tipo == tipo,
                    Notificacion.objeto_id == objeto_id,
                    Notificacion.entregada_at.is_(None),
                    Notificacion.created_at >= ahora - timedelta(minutes=ventana),
                )
                .order_by(Notificacion.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if abierta is not None:
                abierta.agrupadas += 1
                abierta.titulo = titulo
                abierta.cuerpo = cuerpo
                creadas.append(abierta)
                continue
            entregar_at = max(entregar_at, ahora + timedelta(minutes=ventana))

        fila = Notificacion(
            tenant_id=tenant_id,
            usuario_id=usuario_id,
            tipo=tipo,
            titulo=titulo,
            cuerpo=cuerpo,
            objeto_tipo=objeto_tipo,
            objeto_id=objeto_id,
            prioridad=prioridad,
            canales=canales,
            datos=datos or {},
            entregar_at=entregar_at,
        )
        db.add(fila)
        creadas.append(fila)

    if creadas:
        db.flush()
        logger.info("notificacion.creadas", tipo=tipo, destinatarios=len(creadas))
    return creadas


def _fin_del_silencio(pref: PreferenciaNotificacion | None, momento: datetime) -> datetime:
    """Primer instante fuera de la franja de silencio."""
    if pref is None or pref.silencio_hasta is None:
        return momento
    fin = momento.replace(hour=pref.silencio_hasta, minute=0, second=0, microsecond=0)
    return fin if fin > momento else fin + timedelta(days=1)


def marcar_leidas(
    db: Session, *, tenant_id: UUID, usuario_id: UUID, ids: list[UUID] | None = None
) -> int:
    """Marca como leídas. Sin `ids`, todas las del usuario.

    Devuelve cuántas se marcaron, y no cuántas se pidieron: pedir marcar una que
    ya estaba leída no es un error, pero decir que se marcó sería mentir.
    """
    consulta = select(Notificacion).where(
        Notificacion.tenant_id == tenant_id,
        Notificacion.usuario_id == usuario_id,
        Notificacion.leida_at.is_(None),
    )
    if ids:
        consulta = consulta.where(Notificacion.id.in_(ids))
    ahora = datetime.now(timezone.utc)
    marcadas = 0
    for fila in db.execute(consulta).scalars().all():
        fila.leida_at = ahora
        marcadas += 1
    # Se vuelca antes de salir: si no, una segunda llamada dentro de la misma
    # transacción vuelve a leer las filas sin marcar y las cuenta otra vez.
    db.flush()
    return marcadas


def bandeja(
    db: Session,
    *,
    tenant_id: UUID,
    usuario_id: UUID,
    solo_no_leidas: bool = False,
    limite: int = 50,
) -> list[Notificacion]:
    """Las notificaciones de una persona, de la más reciente atrás.

    Solo las ya entregables: una notificación retenida por la franja de silencio
    todavía no es suya, y enseñarla en la bandeja mientras se le retiene el
    correo sería incoherente.
    """
    consulta = select(Notificacion).where(
        Notificacion.tenant_id == tenant_id,
        Notificacion.usuario_id == usuario_id,
        Notificacion.entregar_at <= datetime.now(timezone.utc),
    )
    if solo_no_leidas:
        consulta = consulta.where(Notificacion.leida_at.is_(None))
    return list(
        db.execute(consulta.order_by(Notificacion.created_at.desc()).limit(limite)).scalars().all()
    )


def pendientes_de_entregar(db: Session, *, limite: int = 200) -> list[Notificacion]:
    """Lo que el repartidor tiene que sacar ahora, por cualquier canal que no sea `app`.

    `app` no necesita entrega: la bandeja se lee de la tabla. Incluirlas haría
    que el repartidor procesara el 90 % de las filas para no hacer nada.

    `FOR UPDATE SKIP LOCKED` para que varias réplicas repartan a la vez sin
    entregar la misma dos veces ni bloquearse entre ellas.
    """
    ahora = datetime.now(timezone.utc)
    return list(
        db.execute(
            select(Notificacion)
            .where(
                Notificacion.entregada_at.is_(None),
                Notificacion.entregar_at <= ahora,
                # Lo que NO se agota con la bandeja: `contained_by(["app"])`
                # es cierto para las que solo van por `app`, así que negarlo
                # deja exactamente las que necesitan un entregador. Comparar el
                # JSON serializado en texto también «funcionaría», hasta el día
                # que el orden de los canales cambie.
                ~Notificacion.canales.contained_by(["app"]),
            )
            .order_by(Notificacion.entregar_at)
            .limit(limite)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
