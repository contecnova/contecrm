"""Chat corporativo: avisar, consultar y actuar desde la conversación
(CRM-06.01.01.03).

La integración con el chat se vende como notificaciones y se usa para otra cosa:
lo que de verdad ahorra tiempo es **no tener que abrir el CRM** para contestar
«¿en qué está esto?» o para mover una oportunidad. Si solo manda avisos, a las
dos semanas el canal está silenciado.

Las decisiones:

**Un canal declarado, no un módulo por casa.** Teams y Slack son un endpoint, un
formato de mensaje y una firma de webhook. Eso es configuración; escribir un
módulo por cada uno convierte cada implantación en una versión del producto.

**Lo que llega del chat entra por el canal de entrada de siempre.** Igual que el
correo y la centralita: cambia el sobre, no el camino.

**Un mensaje entrante se comprueba antes de creerlo.** Cualquiera que sepa la URL
puede mandar un POST. Sin firma verificada, «actuar desde el chat» es «actuar
desde internet».

**Lo que escribe pasa por comandos**, como todo lo demás que no es de este
servicio. No hay una puerta trasera que se salte las reglas de negocio porque la
petición venga de un chat.

**Y el aviso dice a qué registro pertenece.** Un mensaje que dice «oportunidad
ganada» sin enlace obliga a buscarla, y entonces se deja de mirar el canal.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, NoAutenticado, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import (
    Boolean,
    Index,
    String,
    Text,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Qué se puede pedir desde el chat. Lista cerrada: una orden libre desde un canal
# donde cualquiera escribe es una API sin contrato.
ORDENES = ("consultar", "registrar_nota", "cambiar_estado", "asignar")


class CanalChat(Base, TimestampMixin, SoftDeleteMixin):
    """Un espacio de chat conectado, con su firma y sus permisos."""

    __tablename__ = "canales_chat"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(80), nullable=False)
    # El perfil declarado —cómo se manda y cómo se firma—, no el nombre de la casa.
    perfil: Mapped[str] = mapped_column(String(60), nullable=False, default="generico")
    url_entrante: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # El secreto con el que el proveedor firma lo que manda. Sin él no se acepta
    # nada: «actuar desde el chat» sin firma es «actuar desde internet».
    secreto: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cabecera_firma: Mapped[str] = mapped_column(String(80), nullable=False, default="x-signature")
    # Qué órdenes admite ESTE canal. El canal de dirección no tiene por qué poder
    # cambiar estados, y el de un equipo no tiene por qué poder consultar todo.
    ordenes: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "clave", name="uq_canal_chat"),
        Index("ix_canales_chat", "tenant_id", "activo"),
    )


def declarar_canal(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    url_entrante: str,
    secreto: str,
    perfil: str = "generico",
    cabecera_firma: str = "x-signature",
    ordenes: list[str] | None = None,
) -> CanalChat:
    """Conecta un espacio de chat.

    El secreto es obligatorio. Un canal sin firma acepta cualquier POST de
    cualquiera que sepa la URL, y desde ahí se pueden pedir las mismas cosas que
    desde el CRM.
    """
    if not secreto.strip():
        raise ErrorValidacion(
            "Un canal de chat sin secreto de firma acepta órdenes de cualquiera "
            "que conozca la URL.",
            error_code="chat.sin_secreto",
        )
    desconocidas = sorted(set(ordenes or []) - set(ORDENES))
    if desconocidas:
        raise ErrorValidacion(
            f"Órdenes no reconocidas: {desconocidas}",
            error_code="chat.orden_desconocida",
            detalle={"admitidas": list(ORDENES)},
        )

    fila = (
        uow.db.execute(
            select(CanalChat).where(CanalChat.tenant_id == uow.tenant_id, CanalChat.clave == clave)
        )
        .scalars()
        .first()
    )
    if fila is None:
        fila = CanalChat(tenant_id=uow.tenant_id, clave=clave)
        uow.db.add(fila)
    fila.perfil = perfil
    fila.url_entrante = url_entrante
    fila.secreto = secreto
    fila.cabecera_firma = cabecera_firma
    # Vacío significa **solo consultar**: es lo menos que puede hacer un canal, y
    # lo que menos daño hace si alguien se equivoca al declararlo.
    fila.ordenes = list(ordenes or ["consultar"])
    fila.activo = True
    uow.db.flush()
    return fila


def comprobar_firma(canal: CanalChat, *, cuerpo: bytes, firma: str) -> None:
    """Verifica que el mensaje viene de quien dice.

    Se compara en tiempo constante: una comparación normal filtra el secreto byte
    a byte a quien sepa medir, y eso convierte la firma en decoración.
    """
    if not firma:
        raise NoAutenticado("El mensaje llega sin firma", error_code="chat.sin_firma")
    esperada = hmac.new(canal.secreto.encode(), cuerpo, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(esperada, firma.strip().lower()):
        raise NoAutenticado("La firma del mensaje no cuadra", error_code="chat.firma_invalida")


def atender(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    cuerpo: bytes,
    firma: str,
    orden: str,
    objeto: str = "",
    objeto_id: UUID | None = None,
    texto: str = "",
    usuario_externo: str = "",
) -> dict[str, Any]:
    """Atiende una orden que llega del chat.

    Lo que **escribe** sale como comando al servicio dueño del objeto, igual que
    cualquier otra automatización: que la petición venga de un chat no le da
    permisos distintos.
    """
    canal = (
        uow.db.execute(
            select(CanalChat).where(CanalChat.tenant_id == uow.tenant_id, CanalChat.clave == clave)
        )
        .scalars()
        .first()
    )
    if canal is None or not canal.activo:
        raise NoEncontrado(
            "Ese canal de chat no existe o está desactivado", error_code="chat.no_encontrado"
        )

    comprobar_firma(canal, cuerpo=cuerpo, firma=firma)

    if orden not in (canal.ordenes or []):
        # No es un error del que escribe: es que este canal no puede hacer eso, y
        # decirlo así evita que alguien conceda todas las órdenes «para que
        # funcione».
        return {
            "hecho": False,
            "porque": (
                f"El canal «{clave}» no admite la orden «{orden}». Las que admite "
                f"son {canal.ordenes}."
            ),
        }

    if orden == "consultar":
        # Consultar no escribe nada y se resuelve donde vive el dato: aquí solo
        # se dice a quién hay que preguntar, porque este servicio no lee el
        # esquema de los demás.
        return {
            "hecho": True,
            "accion": "consultar",
            "objeto": objeto,
            "objeto_id": str(objeto_id) if objeto_id else None,
            "quien_contesta": (
                "El servicio dueño del objeto por su API. Este servicio no lee su " "esquema."
            ),
        }

    if objeto_id is None or not objeto:
        raise ErrorValidacion(
            "Esa orden necesita saber sobre qué registro actúa",
            error_code="chat.sin_objeto",
        )

    from crmcore.bus.comandos import Comando
    from crmcore.bus.comandos import emitir as emitir_comando

    accion = {
        "registrar_nota": "anotar",
        "cambiar_estado": "actualizar",
        "asignar": "actualizar",
    }[orden]
    datos: dict[str, Any] = {"origen_chat": clave, "por": usuario_externo}
    if orden == "registrar_nota":
        datos["texto"] = texto
    else:
        datos["campos"] = {"nota_chat": texto} if texto else {}

    emitir_comando(
        uow,
        Comando(
            accion=accion,
            objeto=objeto,
            tenant_id=uow.tenant_id,
            registro_id=objeto_id,
            datos=datos,
            origen="chat",
            origen_id=f"{clave}:{usuario_externo}",
        ),
    )
    logger.info("chat.orden_atendida", canal=clave, orden=orden, objeto=objeto)
    return {
        "hecho": True,
        "accion": accion,
        # «Pedido» y no «hecho»: el servicio dueño puede rechazarlo por sus
        # propias reglas, y decir que está hecho aquí sería mentir sobre algo que
        # todavía puede fallar.
        "estado": "pedido",
        "porque": (
            "Se ha pedido al servicio dueño del objeto. Sus reglas de negocio "
            "deciden: venir de un chat no da permisos distintos."
        ),
    }


def aviso(
    db: Session,
    tenant_id: UUID,
    *,
    clave: str,
    texto: str,
    objeto: str = "",
    objeto_id: UUID | None = None,
    enlace: str = "",
) -> dict[str, Any]:
    """Compone un aviso para el chat, con su enlace al registro.

    **Siempre con enlace.** Un mensaje que dice «oportunidad ganada» sin decir
    cuál obliga a buscarla, y a la tercera vez se deja de mirar el canal.

    No lo manda: eso lo hace el transporte declarado, que es el mismo que manda
    los webhooks y las notificaciones. Tener un envío propio por canal es cómo se
    acaba con tres sitios donde reintentar.
    """
    canal = (
        db.execute(
            select(CanalChat).where(CanalChat.tenant_id == tenant_id, CanalChat.clave == clave)
        )
        .scalars()
        .first()
    )
    if canal is None:
        raise NoEncontrado("Ese canal de chat no existe", error_code="chat.no_encontrado")
    if objeto_id and not enlace:
        raise ErrorValidacion(
            "Un aviso sobre un registro necesita su enlace: sin él, quien lo lea "
            "tiene que buscarlo, y a la tercera vez deja de mirar el canal.",
            error_code="chat.aviso_sin_enlace",
        )
    return {
        "canal": clave,
        "url": canal.url_entrante,
        "mensaje": {
            "texto": texto,
            "objeto": objeto,
            "objeto_id": str(objeto_id) if objeto_id else None,
            "enlace": enlace,
        },
        "lo_manda": "El transporte declarado, con sus reintentos y su registro.",
        "compuesto_at": datetime.now(timezone.utc).isoformat(),
    }
