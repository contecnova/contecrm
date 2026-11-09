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
    DateTime,
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
    secreto: Mapped[str] = mapped_column(Text, nullable=False, default="", info={"secreto": True})
    cabecera_firma: Mapped[str] = mapped_column(String(80), nullable=False, default="x-signature")
    # La cabecera con el instante de la firma, si el proveedor la manda. Vacía
    # significa **canal reproducible**: su firma no caduca, así que un mensaje
    # capturado vale para siempre. Se guarda vacía en vez de inventarse un valor
    # por defecto porque cada plataforma la llama de una forma, y adivinar haría
    # que la comprobación fallara siempre o no se hiciera nunca.
    cabecera_momento: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    # Qué órdenes admite ESTE canal. El canal de dirección no tiene por qué poder
    # cambiar estados, y el de un equipo no tiene por qué poder consultar todo.
    ordenes: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Si a este canal le llegan los avisos de notificaciones y automatizaciones
    # (09-11-2026). Apagado por defecto: un canal que se declara para consultar
    # no tiene por qué llenarse de avisos.
    recibe_avisos: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Cómo fue el último aviso que se mandó: cuándo, si llegó y qué contestó el
    # canal. Sin esto, «el canal no recibe nada» se investiga en la plataforma
    # de chat, donde todo está bien.
    ultimo_aviso_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ultimo_aviso_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ultimo_aviso_detalle: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )

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
    cabecera_momento: str = "",
    ordenes: list[str] | None = None,
    recibe_avisos: bool = False,
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
    fila.cabecera_momento = cabecera_momento
    # Vacío significa **solo consultar**: es lo menos que puede hacer un canal, y
    # lo que menos daño hace si alguien se equivoca al declararlo.
    fila.ordenes = list(ordenes or ["consultar"])
    fila.recibe_avisos = bool(recibe_avisos)
    fila.activo = True
    uow.db.flush()
    return fila


def canal_por_clave(db: Any, tenant_id: UUID, clave: str) -> CanalChat:
    """El canal, o se dice que no existe.

    Se saca aparte porque la ruta lo necesita **antes** de leer las cabeceras:
    cuáles son las cabeceras lo decide el canal, no el producto. Fijarlas en la
    ruta ataría la instalación a una plataforma concreta.
    """
    fila = (
        db.execute(
            select(CanalChat).where(CanalChat.tenant_id == tenant_id, CanalChat.clave == clave)
        )
        .scalars()
        .first()
    )
    if fila is None or not fila.activo:
        raise NoEncontrado(
            "Ese canal de chat no existe o está desactivado", error_code="chat.no_encontrado"
        )
    return fila


def comprobar_firma(
    canal: CanalChat, *, cuerpo: bytes, firma: str, momento: str | int | None = None
) -> None:
    """Verifica que el mensaje viene de quien dice, **y que no es uno viejo**.

    Se compara en tiempo constante: una comparación normal filtra el secreto byte
    a byte a quien sepa medir, y eso convierte la firma en decoración.

    **Y con ventana anti-reenvío cuando el canal manda el instante.** Esto era
    una tercera implementación del mismo HMAC —el núcleo ya tenía la suya, usada
    para firmar lo que sale— y la que menos se mira es la que se quedó corta:
    ésta no miraba el instante, así que un mensaje capturado una vez valía para
    siempre. Quien pueda repetir una orden de chat puede repetirla mil veces, y
    lo que hay al otro lado son cambios en el CRM.

    El instante **no se exige**: lo manda el proveedor de chat con su nombre de
    cabecera, y hay plataformas que no lo mandan. Cuando no viene, se comprueba
    la firma sin ventana y el canal queda marcado como reproducible en su ficha
    —eso es un dato que quien lo configura debe ver, no un silencio—.
    """
    if not firma:
        raise NoAutenticado("El mensaje llega sin firma", error_code="chat.sin_firma")

    limpia = firma.strip().lower()
    if momento in (None, ""):
        esperada = hmac.new(canal.secreto.encode(), cuerpo, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(esperada, limpia):
            raise NoAutenticado("La firma del mensaje no cuadra", error_code="chat.firma_invalida")
        return

    # Con instante: se usa la verificación del núcleo, que es la que ya está
    # escrita, probada y publicada en el manual del integrador. Tres copias de un
    # HMAC divergen, y la que diverge es la que deja pasar algo.
    from crmcore.security.firma import verificar_firma

    try:
        instante = int(momento)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise NoAutenticado(
            "El instante de la firma no es un número de segundos",
            error_code="chat.momento_invalido",
        ) from None

    if not verificar_firma(cuerpo, canal.secreto, limpia, instante):
        raise NoAutenticado(
            "La firma no cuadra o el mensaje es demasiado viejo: un mensaje "
            "capturado no se puede reenviar pasada la ventana.",
            error_code="chat.firma_invalida",
        )


def atender(
    uow: UnidadDeTrabajo,
    *,
    clave: str,
    cuerpo: bytes,
    firma: str,
    momento: str | int | None = None,
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

    comprobar_firma(canal, cuerpo=cuerpo, firma=firma, momento=momento)

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


# ══════════════════════════════════════════════════════════════════════════
# Lo que sale de verdad (09-11-2026)
#
# `aviso()` componía el mensaje y decía «lo manda el transporte declarado». No
# lo mandaba nadie: no había quien lo llamara. Y la orden «consultar» contestaba
# «pregúntale al servicio dueño». Lo de abajo manda el aviso al webhook entrante
# del canal y contesta la consulta con el dato, con los permisos de quien
# pregunta.
# ══════════════════════════════════════════════════════════════════════════


def _ajuste(clave: str, db: Any) -> Any:
    from services.integration.ajustes import valor

    return valor(clave, db)


def enlace_al_registro(db: Any, objeto: str, objeto_id: UUID | None) -> str:
    """El enlace al registro en el CRM, con la dirección pública configurada.

    `/abrir/{objeto}/{id}` lo resuelve el front a la ficha de su módulo: el
    servidor no tiene por qué saber en qué módulo se enseña cada objeto. Sin
    dirección configurada no se inventa: se devuelve vacío y el aviso sobre un
    registro se rechaza diciéndolo.
    """
    base = str(_ajuste("chat_url_crm", db) or "").rstrip("/")
    if not base or not objeto or objeto_id is None:
        return ""
    return f"{base}/abrir/{objeto}/{objeto_id}"


def _postear(url: str, cuerpo: dict[str, Any], *, timeout_s: float) -> tuple[bool, str]:
    """POST al webhook entrante, por el cliente con guard de SSRF."""
    import httpx
    from crmcore.red import cliente_seguro

    try:
        with cliente_seguro(timeout=timeout_s) as cli:
            r = cli.post(url, json=cuerpo)
    except (httpx.HTTPError, ValueError) as exc:
        return False, f"No se ha podido llamar al canal: {exc}"[:500]
    except Exception as exc:  # noqa: BLE001 — el guard rechaza con su propio error
        return False, f"El canal no se puede llamar desde el servidor: {exc}"[:500]
    if r.status_code >= 400:
        return False, f"El canal contestó HTTP {r.status_code}: {r.text[:300]}"
    return True, f"HTTP {r.status_code}"


Poster = Any


def mandar_aviso(
    db: Session,
    tenant_id: UUID,
    *,
    clave: str,
    texto: str,
    objeto: str = "",
    objeto_id: UUID | None = None,
    enlace: str = "",
    postear: Poster = None,
) -> dict[str, Any]:
    """Compone el aviso y lo MANDA al webhook entrante del canal.

    El resultado se guarda en el canal —cuándo, si llegó y qué contestó—, que
    es lo que se mira cuando alguien dice que el canal no recibe nada.
    """
    from services.integration import conector

    if not texto.strip():
        raise ErrorValidacion("Un aviso sin texto no dice nada", error_code="chat.aviso_vacio")
    enlace = enlace or enlace_al_registro(db, objeto, objeto_id)
    try:
        compuesto = aviso(
            db,
            tenant_id,
            clave=clave,
            texto=texto,
            objeto=objeto,
            objeto_id=objeto_id,
            enlace=enlace,
        )
    except ErrorValidacion as exc:
        if exc.error_code == "chat.aviso_sin_enlace":
            raise ErrorValidacion(
                exc.mensaje + " Configura la dirección pública del CRM (ajuste "
                "«chat_url_crm») para que el enlace se ponga solo.",
                error_code=exc.error_code,
            ) from exc
        raise
    canal = canal_por_clave(db, tenant_id, clave)
    if not canal.url_entrante:
        raise ErrorValidacion(
            "Este canal no tiene dirección de webhook entrante: no hay dónde mandar el aviso.",
            error_code="chat.sin_url_entrante",
        )
    plantilla = _ajuste("chat_plantilla_aviso", db) or {"text": "{{texto}} {{enlace}}"}
    cuerpo = conector._renderizar(
        plantilla,
        {
            "texto": texto.strip(),
            "enlace": enlace,
            "objeto": objeto,
            "objeto_id": str(objeto_id) if objeto_id else "",
        },
    )
    ok, detalle = (postear or _postear)(
        canal.url_entrante, cuerpo, timeout_s=float(_ajuste("chat_espera_s", db))
    )
    canal.ultimo_aviso_at = datetime.now(timezone.utc)
    canal.ultimo_aviso_ok = ok
    canal.ultimo_aviso_detalle = detalle[:1000]
    db.flush()
    logger.info("chat.aviso", canal=clave, ok=ok)
    return {**compuesto, "enviado": ok, "detalle": detalle, "cuerpo": cuerpo}


def avisar_a_los_canales(
    db: Session,
    tenant_id: UUID,
    *,
    texto: str,
    objeto: str = "",
    objeto_id: UUID | None = None,
    postear: Poster = None,
) -> dict[str, Any]:
    """Manda un aviso a todos los canales que tienen `recibe_avisos`.

    Un canal que falla no tapa a los demás, y se cuenta.
    """
    canales = (
        db.execute(
            select(CanalChat).where(
                CanalChat.tenant_id == tenant_id,
                CanalChat.activo.is_(True),
                CanalChat.recibe_avisos.is_(True),
                CanalChat.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    enviados, fallidos = 0, []
    for c in canales:
        try:
            r = mandar_aviso(
                db,
                tenant_id,
                clave=c.clave,
                texto=texto,
                objeto=objeto,
                objeto_id=objeto_id,
                postear=postear,
            )
            if r["enviado"]:
                enviados += 1
            else:
                fallidos.append({"canal": c.clave, "detalle": r["detalle"]})
        except ErrorValidacion as exc:
            fallidos.append({"canal": c.clave, "detalle": exc.mensaje})
    return {"canales": len(canales), "enviados": enviados, "fallidos": fallidos}


async def consumir_aviso(mensaje: Any) -> None:
    """El evento `automatizacion.aviso` (la acción «notificar»), al chat.

    Llega por el bus; en una instalación sin bus no llega nunca, y entonces el
    aviso al chat sale sólo por `POST /canales-chat/{clave}/aviso`.
    """
    from crmcore.db.uow import unidad_de_trabajo

    datos = dict(getattr(mensaje, "data", None) or (mensaje or {}).get("data") or {})
    tenant = str(getattr(mensaje, "tenant_id", "") or (mensaje or {}).get("tenant_id") or "")
    if not tenant or not datos.get("titulo"):
        return
    texto = str(datos.get("titulo"))
    if datos.get("cuerpo"):
        texto += f" — {datos['cuerpo']}"
    objeto_id: UUID | None
    try:
        objeto_id = UUID(str(datos.get("objeto_id"))) if datos.get("objeto_id") else None
    except ValueError:
        objeto_id = None
    with unidad_de_trabajo(UUID(tenant), sistema=True) as uow:
        salida = avisar_a_los_canales(
            uow.db,
            uow.tenant_id,
            texto=texto,
            objeto=str(datos.get("objeto_tipo") or ""),
            objeto_id=objeto_id,
        )
    logger.info("chat.avisos_de_automatizacion", **salida)


# ── La consulta desde el chat, con los permisos de quien pregunta ────────

_COLECCIONES: dict[str, str] = {}


def _pedir_alcance(tenant_id: UUID, correo: str) -> dict[str, Any] | None:
    from crmcore.http.interno import pedir

    return pedir("identity", f"/api/v1/interno/usuarios/{tenant_id}/por-correo/{correo}/alcance")


def _invocar(**kw: Any) -> dict[str, Any]:
    from crmcore.http.interno import invocar

    return invocar(**kw)


def coleccion_de(objeto: str, *, identidad: dict[str, Any], invocar: Any) -> str | None:
    """La colección HTTP de este objeto, preguntando a los servicios.

    Cada servicio publica en `/{servicio}/filtros` qué colecciones tiene: una
    segunda tabla «objeto → ruta» escrita aquí se quedaría atrás.
    """
    if objeto in _COLECCIONES:
        return _COLECCIONES[objeto]
    from crmcore.config import get_settings
    from crmcore.rutas_de_api import cargar_destinos

    for servicio in sorted(cargar_destinos(get_settings().rutas_servicios)):
        try:
            r = invocar(metodo="GET", ruta=f"/api/v1/{servicio}/filtros", **identidad)
        except Exception:  # noqa: BLE001 — un servicio caído no tapa a los demás
            continue
        if not r.get("ok"):
            continue
        ruta = ((r.get("datos") or {}).get("colecciones") or {}).get(objeto)
        if ruta:
            _COLECCIONES[objeto] = str(ruta)
            return _COLECCIONES[objeto]
    return None


# Lo que se contesta de un registro en el chat: lo que cabe en una línea. El
# registro entero en un canal donde lee todo el equipo es lo que no se quiere.
CAMPOS_RESPUESTA = (
    "nombre",
    "nombre_completo",
    "asunto",
    "titulo",
    "estado",
    "etapa_nombre",
    "importe",
    "moneda",
    "fecha_cierre",
    "prioridad",
)


def contestar_consulta(
    tenant_id: UUID,
    *,
    objeto: str,
    objeto_id: UUID | None,
    usuario_externo: str,
    pedir_alcance: Any = None,
    invocar: Any = None,
) -> dict[str, Any]:
    """Contesta «¿en qué está esto?» con el dato, **con los permisos de quien pregunta**.

    Quien escribe en el chat se resuelve por su correo a una persona del CRM
    (identity); el registro se pide a su servicio dueño con SU identidad —sus
    roles y sus permisos—. Si no se sabe quién es, no se contesta con datos: un
    canal lo lee todo el equipo, y contestar con los permisos del canal sería
    enseñar a cualquiera lo que sólo ve dirección.
    """
    invocar = invocar or _invocar
    if not objeto or objeto_id is None:
        raise ErrorValidacion(
            "Di qué registro quieres consultar: objeto y su identificador.",
            error_code="chat.sin_objeto",
        )
    correo = (usuario_externo or "").strip().lower()
    if "@" not in correo:
        return {
            "hecho": False,
            "porque": (
                "No se sabe quién pregunta: el chat no ha mandado el correo de la "
                "persona. Sin eso no se contesta con datos."
            ),
        }
    alcance = (pedir_alcance or _pedir_alcance)(tenant_id, correo)
    if not alcance:
        return {
            "hecho": False,
            "porque": f"{correo} no es una persona con acceso a este CRM: no se contesta con datos.",
        }
    identidad = {
        "tenant_id": tenant_id,
        "principal_id": alcance.get("usuario_id"),
        "permisos": list(alcance.get("permisos") or []),
        "roles": list(alcance.get("roles") or []),
        "tipo": "usuario",
    }
    ruta = coleccion_de(objeto, identidad=identidad, invocar=invocar)
    if not ruta:
        return {"hecho": False, "porque": f"«{objeto}» no es un objeto que se pueda consultar."}
    r = invocar(metodo="GET", ruta=f"{ruta}/{objeto_id}", **identidad)
    if r.get("estado") in (403, 404):
        return {
            "hecho": False,
            "porque": "Ese registro no existe o no lo puedes ver.",
        }
    if not r.get("ok"):
        return {"hecho": False, "porque": f"El servicio dueño contestó HTTP {r.get('estado')}."}
    datos = dict(r.get("datos") or {})
    resumen = {c: datos[c] for c in CAMPOS_RESPUESTA if datos.get(c) not in (None, "")}
    return {
        "hecho": True,
        "accion": "consultar",
        "objeto": objeto,
        "objeto_id": str(objeto_id),
        "quien": correo,
        "datos": resumen,
        "tapados": r.get("campos_tapados") or [],
        "texto": ", ".join(f"{k}: {v}" for k, v in resumen.items()) or "Sin datos que enseñar.",
    }
