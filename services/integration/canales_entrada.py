"""Canales sin interfaz y registro automático de interacciones
(CRM-00.02.03.09, CRM-01.02.01.04).

Un CRM headless tiene que poder usarse **sin abrir el CRM**: se contesta un correo,
se cuelga una llamada, se cierra una reunión del calendario, y eso tiene que
quedar registrado sin que nadie teclee nada. Si registrarlo cuesta un minuto por
interacción, no se registra — y un CRM sin interacciones es una agenda cara.

Cuatro decisiones:

**Todos los canales entran por el mismo sitio.** Correo, SMS, voz, chat, CLI o un
agente: cambia el sobre, no el camino. Un camino por canal acaba con cuatro sitios
donde se crea una actividad y solo uno aplicando las reglas.

**Idempotencia por identificador del canal.** El proveedor de correo reintenta, la
centralita reenvía el CDR y el calendario manda el mismo evento cada vez que
alguien lo toca. Sin idempotencia, una reunión aparece cuatro veces en la ficha.

**Lo que no se puede atribuir se queda visible, no se tira.** Un correo de una
dirección que no está en el CRM es un contacto que falta, no basura: se guarda sin
atribuir y se cuenta. Descartarlo hace que la ficha del cliente parezca tranquila
cuando lo que pasa es que su correo nuevo no está dado de alta.

**Registrar no es leer.** Se guarda **que hubo** una llamada o un correo, con
quién y cuándo; el contenido solo si quien lo manda lo incluye y el tenant lo
permite. Volcar el buzón entero dentro del CRM multiplica el dato personal y la
superficie que hay que proteger, para algo que casi nadie vuelve a leer.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.bus.comandos import Comando
from crmcore.bus.comandos import emitir as emitir_comando
from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from crmcore.runtime import settings as rt
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

logger = get_logger(__name__)

# Canales de entrada. Lista cerrada: cada uno tiene su forma de identificar al
# interlocutor —correo, teléfono, usuario— y un canal nuevo necesita decidir la
# suya, no heredar una por descarte.
CANALES = ("correo", "sms", "voz", "chat", "cli", "agente", "calendario")

# Cómo se identifica al interlocutor en cada canal. Es lo que permite atribuir la
# interacción sin inventarse nada.
IDENTIFICADOR = {
    "correo": "email",
    "sms": "telefono",
    "voz": "telefono",
    "chat": "identificador",
    "cli": "usuario",
    "agente": "usuario",
    "calendario": "email",
}


class CanalEntrada(Base, TimestampMixin, SoftDeleteMixin):
    """Una vía por la que entra actividad sin interfaz (CRM-00.02.03.09)."""

    __tablename__ = "canales_entrada"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    canal: Mapped[str] = mapped_column(String(20), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # La dirección o número por el que entra: el buzón, el número corto, la
    # extensión. Sirve para saber por dónde llegó cuando hay varios.
    destino: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Qué se hace con lo que llega: actividad | caso | lead. Declarado, porque un
    # correo a soporte y uno a ventas no son la misma cosa aunque lleguen igual.
    produce: Mapped[str] = mapped_column(String(20), nullable=False, default="actividad")
    # Guardar el cuerpo del mensaje, o solo que existió. Apagado por defecto:
    # volcar el buzón dentro del CRM multiplica el dato personal para algo que
    # casi nadie vuelve a leer.
    guardar_contenido: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_canal_entrada"),
        Index("ix_canales_entrada", "tenant_id", "canal", "activo"),
    )


class Interaccion(Base):
    """Algo que pasó por un canal, registrado (CRM-01.02.01.04)."""

    __tablename__ = "interacciones_entrantes"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # El canal por el que entró la interacción.
    canal_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, info={"referencia": "canal_entrada"}
    )
    canal: Mapped[str] = mapped_column(String(20), nullable=False)
    # Identificador del mensaje **en el canal**: Message-ID, id de la llamada,
    # id del evento de calendario. Es lo que hace idempotente la ingesta.
    id_externo: Mapped[str] = mapped_column(String(300), nullable=False)
    direccion: Mapped[str] = mapped_column(String(10), nullable=False, default="entrante")
    interlocutor: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    asunto: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    contenido: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Huella del contenido aunque no se guarde el contenido: permite detectar el
    # duplicado que llega con otro identificador —reenvíos, copias— sin conservar
    # el texto.
    huella: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ocurrido_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recibido_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    duracion_s: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # A quién se atribuyó. Nulo = no se pudo, y se dice.
    contacto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    usuario_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    atribuida: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    motivo_sin_atribuir: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    # Qué se pidió crear con ella, si se pidió algo.
    produjo: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    datos: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "canal", "id_externo", name="uq_interaccion_externa"),
        Index("ix_interacciones_atribucion", "tenant_id", "atribuida", "ocurrido_at"),
        Index("ix_interacciones_contacto", "tenant_id", "contacto_id", "ocurrido_at"),
    )


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _con_tz(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


def _huella(texto: str) -> str:
    return hashlib.sha256(texto.encode()).hexdigest()


def declarar_canal(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    canal: str,
    destino: str = "",
    nombre: str = "",
    produce: str = "actividad",
    guardar_contenido: bool = False,
) -> CanalEntrada:
    """Declara una vía de entrada."""
    if canal not in CANALES:
        raise ErrorValidacion(
            f"Canal «{canal}» no soportado.",
            error_code="canales.no_valido",
            detalle={"validos": list(CANALES)},
        )
    if produce not in ("actividad", "caso", "lead"):
        raise ErrorValidacion(
            "Un canal produce actividad, caso o lead: un correo a soporte y uno a "
            "ventas no son la misma cosa aunque lleguen igual.",
            error_code="canales.produce_no_valido",
        )
    fila = CanalEntrada(
        tenant_id=uow.tenant_id,
        clave=clave.strip(),
        canal=canal,
        destino=destino.strip(),
        nombre=nombre.strip() or clave.strip(),
        produce=produce,
        guardar_contenido=guardar_contenido,
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def registrar(
    uow: UnidadDeTrabajo,
    *,
    canal: str,
    id_externo: str,
    interlocutor: str = "",
    asunto: str = "",
    contenido: str = "",
    ocurrido_at: datetime | None = None,
    duracion_s: int | None = None,
    direccion: str = "entrante",
    clave_canal: str = "",
    contacto_id: UUID | None = None,
    cuenta_id: UUID | None = None,
    usuario_id: UUID | None = None,
    datos: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Registra una interacción llegada por un canal (CRM-01.02.01.04).

    **Idempotente por el identificador del canal**: el proveedor de correo
    reintenta, la centralita reenvía el CDR y el calendario manda el mismo evento
    cada vez que alguien lo toca. Sin esto, una reunión sale cuatro veces en la
    ficha.

    Si no se puede atribuir a un contacto, **se guarda igual y se cuenta**: un
    correo de una dirección desconocida es un contacto que falta, no basura. Y la
    atribución la trae quien llama, que es quien puede buscar en `party`: hacerlo
    desde aquí exigiría leer el esquema de otro servicio.
    """
    if canal not in CANALES:
        raise ErrorValidacion(
            f"Canal «{canal}» no soportado.",
            error_code="canales.no_valido",
            detalle={"validos": list(CANALES)},
        )
    if not id_externo.strip():
        raise ErrorValidacion(
            "Falta el identificador del mensaje en su canal: sin él no se puede "
            "garantizar que un reenvío no lo duplique.",
            error_code="canales.sin_id_externo",
        )

    ya = uow.db.execute(
        select(Interaccion).where(
            Interaccion.tenant_id == uow.tenant_id,
            Interaccion.canal == canal,
            Interaccion.id_externo == id_externo.strip(),
        )
    ).scalar_one_or_none()
    if ya is not None:
        return {
            "registrada": False,
            "duplicada": True,
            "interaccion_id": str(ya.id),
            "porque": "Ya se había registrado esa interacción con el mismo identificador.",
        }

    ficha = None
    if clave_canal:
        ficha = uow.db.execute(
            select(CanalEntrada).where(
                CanalEntrada.tenant_id == uow.tenant_id, CanalEntrada.clave == clave_canal
            )
        ).scalar_one_or_none()
        if ficha is None:
            raise NoEncontrado("Ese canal no está declarado", error_code="canales.no_encontrado")

    guardar = (
        bool(ficha.guardar_contenido)
        if ficha is not None
        else bool(rt.efectivo("canal_guardar_contenido", uow.db, default=False))
    )
    atribuida = bool(contacto_id or cuenta_id)
    motivo = ""
    if not atribuida:
        clave_id = IDENTIFICADOR.get(canal, "identificador")
        motivo = (
            f"No se ha podido atribuir: no hay ningún contacto con ese {clave_id} "
            f"(«{interlocutor}»)."
            if interlocutor
            else "Llegó sin identificar al interlocutor."
        )

    fila = Interaccion(
        tenant_id=uow.tenant_id,
        canal_id=ficha.id if ficha is not None else None,
        canal=canal,
        id_externo=id_externo.strip(),
        direccion=direccion,
        interlocutor=interlocutor.strip(),
        asunto=asunto.strip()[:300],
        contenido=contenido if guardar else None,
        huella=_huella(contenido) if contenido else None,
        ocurrido_at=_con_tz(ocurrido_at) or _ahora(),
        duracion_s=duracion_s,
        contacto_id=contacto_id,
        cuenta_id=cuenta_id,
        usuario_id=usuario_id,
        atribuida=atribuida,
        motivo_sin_atribuir=motivo,
        datos=dict(datos or {}),
    )
    uow.db.add(fila)
    uow.db.flush()

    pedido = ""
    if atribuida and ficha is not None:
        # Lo que se crea lo crea el servicio dueño, por comando: `integration` no
        # escribe actividades ni casos. Y solo si se pudo atribuir: una actividad
        # colgando de nadie no la ve nadie.
        objeto = {"actividad": "actividad", "caso": "caso", "lead": "lead"}[ficha.produce]
        emitir_comando(
            uow,
            Comando(
                accion="crear",
                objeto=objeto,
                tenant_id=uow.tenant_id,
                datos={
                    "asunto": fila.asunto or f"{canal} con {fila.interlocutor}",
                    "descripcion": fila.contenido or "",
                    "tipo": canal,
                    "contacto_id": str(contacto_id) if contacto_id else None,
                    "cuenta_id": str(cuenta_id) if cuenta_id else None,
                    "origen": f"canal:{canal}",
                    "ocurrido_at": fila.ocurrido_at.isoformat(),
                },
                origen="canal_entrada",
                origen_id=str(fila.id),
            ),
        )
        pedido = ficha.produce
        fila.produjo = pedido

    uow.emitir(
        "interaction.recorded",
        subject=("interaccion", fila.id),
        data={"interaccion_id": str(fila.id), "canal": canal, "atribuida": atribuida},
    )
    return {
        "registrada": True,
        "duplicada": False,
        "interaccion_id": str(fila.id),
        "atribuida": atribuida,
        "motivo_sin_atribuir": motivo,
        # Se dice qué se **pidió** crear, no que exista: lo crea el servicio dueño.
        "pedido": pedido,
        "contenido_guardado": bool(fila.contenido),
    }


def sin_atribuir(db: Session, tenant_id: UUID, *, limite: int = 100) -> dict[str, Any]:
    """Interacciones que no se pudieron colgar de nadie.

    Es una lista de trabajo, no un cajón de errores: cada línea es un contacto que
    falta o un dato de contacto que cambió. Tirarlas haría que la ficha del cliente
    pareciera tranquila cuando lo que pasa es que escribe desde otro correo.
    """
    filas = (
        db.execute(
            select(Interaccion)
            .where(Interaccion.tenant_id == tenant_id, Interaccion.atribuida.is_(False))
            .order_by(Interaccion.ocurrido_at.desc())
            .limit(limite)
        )
        .scalars()
        .all()
    )
    por_interlocutor: dict[str, int] = {}
    for fila in filas:
        if fila.interlocutor:
            por_interlocutor[fila.interlocutor] = por_interlocutor.get(fila.interlocutor, 0) + 1
    return {
        "interacciones": [
            {
                "id": str(f.id),
                "canal": f.canal,
                "interlocutor": f.interlocutor,
                "asunto": f.asunto,
                "ocurrido_at": f.ocurrido_at.isoformat(),
                "porque": f.motivo_sin_atribuir,
            }
            for f in filas
        ],
        # Quién escribe más sin estar dado de alta: es la lista por la que
        # empezar, no por la primera interacción de la cola.
        "interlocutores_frecuentes": sorted(
            ({"interlocutor": k, "veces": v} for k, v in por_interlocutor.items()),
            key=lambda d: -d["veces"],
        )[:10],
        "cuantas": len(filas),
    }


def atribuir(
    uow: UnidadDeTrabajo,
    interaccion_id: UUID,
    *,
    contacto_id: UUID | None = None,
    cuenta_id: UUID | None = None,
) -> Interaccion:
    """Cuelga a posteriori una interacción que no se pudo atribuir."""
    fila = uow.db.get(Interaccion, interaccion_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("Esa interacción no existe", error_code="canales.no_encontrada")
    if not contacto_id and not cuenta_id:
        raise ErrorValidacion(
            "Atribuir exige un contacto o una cuenta.", error_code="canales.sin_destino"
        )
    fila.contacto_id = contacto_id
    fila.cuenta_id = cuenta_id
    fila.atribuida = True
    fila.motivo_sin_atribuir = ""
    uow.db.flush()
    return fila


def actividad_de(
    db: Session, tenant_id: UUID, *, contacto_id: UUID, limite: int = 50
) -> dict[str, Any]:
    """Las interacciones registradas de un contacto, de todos los canales.

    Juntas y no por canal: la pregunta que se hace antes de llamar a un cliente es
    «¿qué hemos hablado?», no «¿qué correos hemos cruzado?».
    """
    filas = (
        db.execute(
            select(Interaccion)
            .where(Interaccion.tenant_id == tenant_id, Interaccion.contacto_id == contacto_id)
            .order_by(Interaccion.ocurrido_at.desc())
            .limit(limite)
        )
        .scalars()
        .all()
    )
    return {
        "contacto_id": str(contacto_id),
        "interacciones": [
            {
                "id": str(f.id),
                "canal": f.canal,
                "direccion": f.direccion,
                "asunto": f.asunto,
                "ocurrido_at": f.ocurrido_at.isoformat(),
                "duracion_s": f.duracion_s,
                # Se dice si el contenido está guardado o solo consta que existió:
                # quien lo lea no puede confundir «no dijo nada» con «no se guardó».
                "con_contenido": f.contenido is not None,
            }
            for f in filas
        ],
        "por_canal": {
            canal: len([f for f in filas if f.canal == canal])
            for canal in sorted({f.canal for f in filas})
        },
        "cuantas": len(filas),
    }
