"""Portal de cliente headless, comunidad e identidad de contacto
(CRM-04.03.02.01, .04, .05, CRM-00.05.01.10).

Un portal de cliente es la parte del CRM que **ve alguien que no trabaja aquí**, y
eso cambia todas las reglas:

**La identidad del cliente no es la del empleado (CIAM).** Un contacto no es un
usuario del CRM: no tiene roles, no cuenta para licencias y su alta la hace el
propio cliente o el comercial, no el departamento de sistemas. Mezclarlos —que es
lo que pasa cuando se reutiliza la tabla de usuarios— acaba en un contacto con
permisos de empleado el día que alguien le asigna un rol por comodidad.

**Lo que ve cada contacto lo decide su relación con la cuenta.** El jefe de
compras ve las facturas; el técnico, solo sus casos. Sin niveles, o se le enseña
todo a todos —y el portal deja de poder usarse para cosas sensibles— o se le
enseña lo mínimo a todos, y entonces no sirve.

**Todo lo que se sirve aquí se filtra en el servidor.** Filtrar en el cliente
funciona hasta que alguien mira la respuesta de la API, y entonces el portal deja
de ser un portal para ser una copia del CRM con un filtro de pantalla.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.audit import registrar
from crmcore.db.base import Base, SoftDeleteMixin, TimestampMixin
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoAutenticado, NoEncontrado, Prohibido
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

# Niveles de acceso de un contacto sobre su cuenta, de menos a más.
#
#   propio      solo lo que él ha abierto
#   cuenta      todo lo de su empresa
#   admin       además, gestiona a los demás contactos de su empresa
#
# Tres y no dos porque el caso real es exactamente ese: el técnico que solo ve lo
# suyo, el responsable que ve lo de su empresa y el que además da de alta a sus
# compañeros sin llamarnos.
NIVELES = ("propio", "cuenta", "admin")
ORDEN_NIVEL = {n: i for i, n in enumerate(NIVELES)}


class AccesoPortal(Base, TimestampMixin, SoftDeleteMixin):
    """La identidad de un contacto en el portal (CRM-04.03.02.05,
    CRM-00.05.01.10).

    Tabla aparte de `Usuario` a propósito. Un contacto **no cuenta para
    licencias**, no tiene roles del CRM y su ciclo de vida lo manda la relación
    comercial, no el directorio corporativo. Reutilizar la tabla de usuarios
    parece que ahorra trabajo y lo que hace es dejar abierta la puerta a que un
    contacto acabe con permisos de empleado porque alguien le asignó un rol por
    comodidad.
    """

    __tablename__ = "accesos_portal"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    contacto_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    cuenta_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    email: Mapped[str] = mapped_column(
        String(320), nullable=False, info={"sensibilidad": "personal"}
    )

    nivel: Mapped[str] = mapped_column(String(20), nullable=False, default="propio")
    # Qué secciones ve. Vacío = las de su nivel; con valores, se acota más.
    secciones: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    # Contraseña opcional: lo normal es entrar por enlace de un solo uso, que
    # evita gestionar contraseñas de gente que entra tres veces al año y las
    # olvida siempre.
    hash_contrasena: Mapped[str | None] = mapped_column(String(255), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ultimo_acceso_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Desactivado por nosotros o por el administrador del cliente. Se distingue
    # de `activo` para poder decirle a quien intenta entrar si tiene que hablar
    # con su empresa o con nosotros.
    desactivado_por: Mapped[str | None] = mapped_column(String(20), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "contacto_id", name="uq_acceso_portal"),
        Index("ix_accesos_portal_email", "tenant_id", "email"),
    )


class EnlaceAcceso(Base):
    """Enlace de un solo uso para entrar al portal.

    El token se guarda **hasheado** y con caducidad corta. Un enlace de acceso
    viaja por correo, y el correo se reenvía: sin caducidad, el que alguien
    reenvió hace seis meses sigue abriendo la cuenta de su empresa.
    """

    __tablename__ = "enlaces_acceso_portal"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    acceso_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("accesos_portal.id", ondelete="CASCADE"), nullable=False
    )
    hash_token: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    caduca_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_uso: Mapped[str | None] = mapped_column(
        String(64), nullable=True, info={"sensibilidad": "personal"}
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class HiloComunidad(Base, TimestampMixin, SoftDeleteMixin):
    """Pregunta de la comunidad (CRM-04.03.02.04)."""

    __tablename__ = "hilos_comunidad"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    titulo: Mapped[str] = mapped_column(String(300), nullable=False)
    cuerpo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    autor_contacto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    categoria: Mapped[str] = mapped_column(String(80), nullable=False, default="general")
    # abierto | respondido | cerrado | moderacion
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="moderacion")
    # Respuesta marcada como la buena. Es lo que separa un foro útil de un
    # archivo de conversaciones: sin ella, quien llega el mes que viene tiene que
    # leerse los treinta mensajes para saber cuál funcionó.
    respuesta_aceptada_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # Artículo al que dio lugar, si alguien lo convirtió en conocimiento.
    articulo_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    vistas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (Index("ix_hilos_comunidad", "tenant_id", "estado", "categoria"),)


class RespuestaComunidad(Base):
    """Respuesta a un hilo."""

    __tablename__ = "respuestas_comunidad"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    hilo_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("hilos_comunidad.id", ondelete="CASCADE"), nullable=False
    )
    cuerpo: Mapped[str] = mapped_column(Text, nullable=False)
    autor_contacto_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    autor_usuario_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # Respuesta del fabricante. Se marca porque en un foro de soporte la
    # diferencia entre «lo dice el fabricante» y «lo dice otro cliente» es toda.
    oficial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    votos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    oculta: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()"), nullable=False
    )

    __table_args__ = (Index("ix_respuestas_comunidad", "tenant_id", "hilo_id", "created_at"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _hash(valor: str) -> str:
    return hashlib.sha256(valor.encode()).hexdigest()


# ── Identidad del contacto (CRM-04.03.02.05, CRM-00.05.01.10) ─────────────


def dar_acceso(
    uow: UnidadDeTrabajo,
    *,
    contacto_id: UUID,
    email: str,
    cuenta_id: UUID | None = None,
    nivel: str = "propio",
    secciones: list[str] | None = None,
) -> AccesoPortal:
    """Da acceso al portal a un contacto.

    Nace en el nivel **más bajo**: ver solo lo suyo. Subirlo es una decisión, y
    que lo sea es lo que impide que el técnico que abrió una incidencia acabe
    viendo las facturas de su empresa porque alguien creó el acceso deprisa.
    """
    if nivel not in NIVELES:
        raise ErrorValidacion(
            f"Nivel «{nivel}» no válido.",
            error_code="service.nivel_portal_no_valido",
            detalle={"validos": list(NIVELES)},
        )
    # Un acceso de nivel «cuenta» o «admin» sin cuenta no ve **nada**: el filtro
    # es por cuenta y sin ella no hay por dónde filtrar. Se rechaza aquí en vez
    # de dejarlo pasar, porque el síntoma sería un portal que entra bien y sale
    # vacío — y eso se lee como «no tengo casos», no como «el acceso está mal
    # dado». La cuenta la pone quien crea el acceso porque el contacto vive en
    # otro servicio y este no puede consultarla.
    if nivel in ("cuenta", "admin") and cuenta_id is None:
        raise ErrorValidacion(
            f"Un acceso de nivel «{nivel}» necesita la cuenta del contacto: sin "
            "ella el portal entra y no enseña nada.",
            error_code="service.acceso_portal_sin_cuenta",
        )

    tenant_id = uow.tenant_id
    existente = uow.db.execute(
        select(AccesoPortal).where(
            AccesoPortal.tenant_id == tenant_id, AccesoPortal.contacto_id == contacto_id
        )
    ).scalar_one_or_none()
    if existente is not None:
        raise Conflicto(
            "Ese contacto ya tiene acceso al portal",
            error_code="service.acceso_portal_duplicado",
            detalle={"acceso_id": str(existente.id)},
        )

    fila = AccesoPortal(
        tenant_id=tenant_id,
        contacto_id=contacto_id,
        cuenta_id=cuenta_id,
        email=email.strip().lower(),
        nivel=nivel,
        secciones=secciones or [],
    )
    uow.db.add(fila)
    uow.db.flush()
    registrar(
        uow.db,
        accion="portal.acceso_concedido",
        objeto="contacto",
        objeto_id=contacto_id,
        datos={
            "email": fila.email,
            "nivel": nivel,
            "cuenta_id": str(cuenta_id) if cuenta_id else None,
        },
        tenant_id=tenant_id,
    )
    return fila


def revocar_acceso(
    uow: UnidadDeTrabajo, acceso_id: UUID, *, por: str = "proveedor", motivo: str = ""
) -> AccesoPortal:
    """Quita el acceso y corta los enlaces vivos.

    Los enlaces pendientes se invalidan **en el acto**: si no, alguien a quien
    acaban de retirar el acceso sigue entrando con el correo que recibió esta
    mañana, y en la lista figura como revocado.
    """
    fila = uow.db.get(AccesoPortal, acceso_id)
    if fila is None or fila.tenant_id != uow.tenant_id:
        raise NoEncontrado("Acceso no encontrado", error_code="service.acceso_no_encontrado")
    fila.activo = False
    fila.desactivado_por = por
    for enlace in uow.db.execute(
        select(EnlaceAcceso).where(
            EnlaceAcceso.acceso_id == fila.id, EnlaceAcceso.usado_at.is_(None)
        )
    ).scalars():
        enlace.usado_at = _ahora()
    registrar(
        uow.db,
        accion="portal.acceso_revocado",
        objeto="contacto",
        objeto_id=fila.contacto_id,
        datos={"por": por, "motivo": motivo},
        tenant_id=fila.tenant_id,
    )
    return fila


def emitir_enlace(
    uow: UnidadDeTrabajo, *, email: str, validez_minutos: int = 30
) -> tuple[EnlaceAcceso | None, str]:
    """Genera un enlace de un solo uso para entrar.

    **Devuelve enlace nulo sin decirlo** cuando el correo no tiene acceso: la
    respuesta de la API es la misma exista o no. Distinguirlas convertiría el
    portal en un comprobador de qué correos son clientes nuestros, que es
    exactamente la lista que quiere un competidor.
    """
    fila = uow.db.execute(
        select(AccesoPortal).where(
            AccesoPortal.tenant_id == uow.tenant_id,
            AccesoPortal.email == email.strip().lower(),
            AccesoPortal.activo.is_(True),
        )
    ).scalar_one_or_none()
    if fila is None:
        logger.info("portal.enlace_a_desconocido", tenant=str(uow.tenant_id))
        return None, ""

    token = secrets.token_urlsafe(32)
    enlace = EnlaceAcceso(
        tenant_id=fila.tenant_id,
        acceso_id=fila.id,
        hash_token=_hash(token),
        caduca_at=_ahora() + timedelta(minutes=validez_minutos),
    )
    uow.db.add(enlace)
    uow.db.flush()
    return enlace, token


def canjear_enlace(uow: UnidadDeTrabajo, token: str, *, ip: str = "") -> AccesoPortal:
    """Canjea el enlace y devuelve el acceso. De un solo uso.

    Cuando lo canjea un empleado, el tenant lo pone su sesión. Cuando lo canjea
    **el cliente** —que es el caso normal— no hay sesión ninguna: el enlace *es*
    la credencial, y pedirle además que diga de qué empresa es convierte el
    portal en un formulario con dos campos, uno de los cuales el cliente no
    tiene por qué saber.

    Por eso, sin tenant en contexto, se busca por el hash **entre todos**: el
    token son treinta y dos bytes aleatorios y su hash solo puede encontrar la
    fila de quien lo recibió. Es el mismo patrón que el refresco de sesión del
    CRM, y por lo mismo: lo que acota no es el tenant, es el secreto.
    """
    consulta = select(EnlaceAcceso).where(EnlaceAcceso.hash_token == _hash(token or ""))
    if uow.tenant_id is not None:
        consulta = consulta.where(EnlaceAcceso.tenant_id == uow.tenant_id)
    enlace = uow.db.execute(consulta).scalar_one_or_none()
    # Mismo error para todo: token inexistente, usado o caducado. Distinguirlos
    # le diría a quien prueba si ese enlace existió alguna vez.
    if enlace is None or enlace.usado_at is not None:
        raise NoAutenticado("Enlace no válido", error_code="portal.enlace_no_valido")
    caduca = (
        enlace.caduca_at
        if enlace.caduca_at.tzinfo
        else enlace.caduca_at.replace(tzinfo=timezone.utc)
    )
    if caduca < _ahora():
        raise NoAutenticado("Enlace no válido", error_code="portal.enlace_no_valido")

    acceso = uow.db.get(AccesoPortal, enlace.acceso_id)
    if acceso is None or not acceso.activo:
        raise NoAutenticado("Enlace no válido", error_code="portal.enlace_no_valido")

    enlace.usado_at = _ahora()
    enlace.ip_uso = ip or None
    acceso.ultimo_acceso_at = _ahora()
    registrar(
        uow.db,
        accion="portal.entrada",
        objeto="contacto",
        objeto_id=acceso.contacto_id,
        datos={"email": acceso.email, "ip": ip},
        tenant_id=acceso.tenant_id,
    )
    return acceso


def exigir_nivel(acceso: AccesoPortal, minimo: str) -> None:
    if ORDEN_NIVEL.get(acceso.nivel, 0) < ORDEN_NIVEL[minimo]:
        raise Prohibido(
            "Tu acceso no llega a esta sección. Habla con el responsable de tu "
            "empresa si necesitas más permisos.",
            error_code="portal.nivel_insuficiente",
            detalle={"tu_nivel": acceso.nivel, "necesario": minimo},
        )


# ── Lo que ve el cliente (CRM-04.03.02.01) ────────────────────────────────


def mis_casos(db: Session, acceso: AccesoPortal, *, limite: int = 50) -> list[dict[str, Any]]:
    """Los casos que este contacto puede ver.

    El filtro va **en el servidor y por el nivel del acceso**, no por un parámetro
    de quien llama. Filtrar en el cliente funciona hasta que alguien mira la
    respuesta de la API, y entonces el portal deja de ser un portal para ser una
    copia del CRM con un filtro de pantalla.
    """
    from services.service.modelos import Caso

    consulta = select(Caso).where(Caso.tenant_id == acceso.tenant_id, Caso.deleted_at.is_(None))
    if acceso.nivel == "propio":
        consulta = consulta.where(Caso.contacto_id == acceso.contacto_id)
    elif acceso.cuenta_id is not None:
        consulta = consulta.where(Caso.cuenta_id == acceso.cuenta_id)
    else:
        # Nivel de cuenta pero sin cuenta asignada: no se enseña nada. Enseñar
        # todo «porque tiene nivel de cuenta» sería el peor fallo posible aquí.
        consulta = consulta.where(text("false"))

    filas = db.execute(consulta.order_by(Caso.created_at.desc()).limit(limite)).scalars().all()
    return [
        {
            "caso_id": str(c.id),
            "codigo": c.codigo,
            "asunto": c.asunto,
            "estado": c.estado,
            "prioridad": c.prioridad,
            "abierto_at": c.created_at.isoformat() if c.created_at else None,
            # El compromiso se enseña, pero NO si se incumplió: decirle al
            # cliente «te hemos incumplido» antes de que lo pregunte se hace en
            # una conversación, no en una pantalla. El dato está y sale en el
            # informe de cumplimiento que se le entrega.
            "vence_resolucion_at": (
                c.vence_resolucion_at.isoformat() if c.vence_resolucion_at else None
            ),
        }
        for c in filas
    ]


def resumen(db: Session, acceso: AccesoPortal) -> dict[str, Any]:
    """La portada del portal, en una llamada.

    Igual que la consola de agente: una portada que abre seis peticiones tarda lo
    que tarde la más lenta. Y devuelve **datos, no pantallas**, que es lo que
    permite que el cliente monte su propio portal con su marca sin que nosotros
    hagamos uno por cliente.
    """
    casos = mis_casos(db, acceso, limite=10)
    abiertos = [c for c in casos if c["estado"] not in ("resuelto", "cerrado")]
    return {
        "contacto_id": str(acceso.contacto_id),
        "cuenta_id": str(acceso.cuenta_id) if acceso.cuenta_id else None,
        "nivel": acceso.nivel,
        "casos_abiertos": len(abiertos),
        "ultimos_casos": casos,
        # Se dice qué secciones puede abrir, para que el portal no pinte botones
        # que después dan 403: un botón que falla al pulsarlo es peor que uno que
        # no está.
        "secciones": secciones_de(acceso),
    }


SECCIONES_POR_NIVEL = {
    "propio": ("casos", "conocimiento", "comunidad"),
    "cuenta": ("casos", "conocimiento", "comunidad", "contratos", "activos", "pedidos"),
    "admin": (
        "casos",
        "conocimiento",
        "comunidad",
        "contratos",
        "activos",
        "pedidos",
        "facturas",
        "contactos",
    ),
}


def conversacion_del_portal(
    db: Session, acceso: AccesoPortal, *, limite: int = 200
) -> list[dict[str, Any]]:
    """Lo que este contacto ha hablado con nosotros, **sin las notas internas**.

    Reusa el historial omnicanal, que es el mismo hilo que ve el agente: el
    correo del lunes y el chat del miércoles son una sola conversación. Un chat
    aparte para el portal habría creado un segundo sitio donde mirar, y el
    agente tendría que acordarse de mirar los dos.

    `incluir_internos=False` va explícito porque la propia función avisa de que
    no se deduzca del permiso: deducirlo pondría una nota interna delante del
    cliente el día que alguien la reutilizara desde un sitio nuevo.
    """
    from services.service import omnicanal as omni

    return omni.historial(
        db,
        acceso.tenant_id,
        contacto_id=acceso.contacto_id,
        limite=limite,
        incluir_internos=False,
    )


def escribir_desde_portal(
    uow: UnidadDeTrabajo,
    acceso: AccesoPortal,
    *,
    texto: str,
    asunto: str = "",
) -> dict[str, Any]:
    """El cliente escribe desde el portal, y le llega al agente donde ya mira.

    No abre un canal de chat propio: entra por la misma conversación omnicanal
    que el correo o el formulario, así que aparece en la consola de agente sin
    que nadie tenga que vigilar una bandeja nueva. Un chat de portal que solo se
    ve en el portal es un chat que nadie contesta.
    """
    from services.service import omnicanal as omni

    texto = (texto or "").strip()
    if not texto:
        raise ErrorValidacion(
            "No se puede mandar un mensaje vacío", error_code="portal.mensaje_vacio"
        )

    conversacion, nueva = omni._conversacion_para(
        uow.db,
        acceso.tenant_id,
        identidad=acceso.email,
        contacto_id=acceso.contacto_id,
        cuenta_id=acceso.cuenta_id,
        canal="portal",
        asunto=asunto or texto[:120],
        ventana_horas=72,
    )
    mensaje = omni.Mensaje(
        tenant_id=acceso.tenant_id,
        conversacion_id=conversacion.id,
        canal="portal",
        direccion=omni.ENTRANTE,
        remitente=acceso.email,
        asunto=asunto[:300] or None,
        cuerpo=texto,
        interno=False,
    )
    uow.db.add(mensaje)
    conversacion.ultimo_mensaje_at = _ahora()

    # Un mensaje suelto no es nada que nadie tenga asignado: sin caso no hay
    # cola, ni compromiso de respuesta, ni a quién reclamarle. Es lo mismo que
    # hace el canal de correo, y por lo mismo — **una** por conversación, no una
    # por mensaje: si no, una conversación de seis mensajes son seis casos y el
    # cliente recibe seis respuestas de seis personas.
    if conversacion.caso_id is None:
        from services.service import servicio as svc

        caso = svc.abrir_caso(
            uow,
            asunto=asunto or texto[:120],
            descripcion=texto,
            origen="portal",
            contacto_id=acceso.contacto_id,
            cuenta_id=acceso.cuenta_id,
        )
        conversacion.caso_id = caso.id
    # Vuelve a la cola: si el agente la había dado por resuelta y el cliente
    # escribe otra vez, dejarla cerrada esconde la respuesta hasta que alguien
    # repase los cerrados — que no lo hace nadie.
    if conversacion.estado == "cerrada":
        conversacion.estado = "abierta"
    uow.db.flush()

    # El mismo evento que un mensaje por cualquier otro canal, no uno propio del
    # portal: quien se haya suscrito para avisar al agente ya está escuchando
    # este, y con un tipo nuevo habría que acordarse de suscribirse otra vez —y
    # hasta entonces los mensajes del portal no avisarían a nadie.
    uow.emitir(
        "case.message.received",
        subject=("conversacion", conversacion.id),
        data={
            "conversacion_id": str(conversacion.id),
            "caso_id": str(conversacion.caso_id) if conversacion.caso_id else None,
            "canal": "portal",
            "nueva": nueva,
        },
    )
    return {
        "conversacion_id": str(conversacion.id),
        "mensaje_id": str(mensaje.id),
        "caso_id": str(conversacion.caso_id) if conversacion.caso_id else None,
        "nueva": nueva,
    }


def secciones_de(acceso: AccesoPortal) -> list[str]:
    """Qué puede abrir este contacto.

    Si el acceso declara secciones concretas, se **intersecan** con las de su
    nivel en vez de sustituirlas: declarar una sección no puede ser una forma de
    saltarse el nivel, que es lo que pasaría si las declaradas mandaran.
    """
    del_nivel = set(SECCIONES_POR_NIVEL.get(acceso.nivel, ()))
    declaradas = {str(s) for s in (acceso.secciones or [])}
    return sorted(del_nivel & declaradas) if declaradas else sorted(del_nivel)


def abrir_caso_desde_portal(
    uow: UnidadDeTrabajo, acceso: AccesoPortal, *, asunto: str, descripcion: str = "", **datos: Any
) -> Any:
    """El cliente abre un caso desde el portal.

    El contacto y la cuenta los pone **el acceso**, no la petición: aceptarlos de
    quien llama permitiría abrir casos en nombre de otra empresa, que es la fuga
    más fácil de un portal.
    """
    from services.service import servicio as svc

    if not acceso.activo:
        raise Prohibido("Tu acceso está desactivado.", error_code="portal.acceso_inactivo")
    datos.pop("contacto_id", None)
    datos.pop("cuenta_id", None)
    return svc.abrir_caso(
        uow,
        asunto=asunto,
        descripcion=descripcion,
        origen="portal",
        contacto_id=acceso.contacto_id,
        cuenta_id=acceso.cuenta_id,
        **datos,
    )


# ── Comunidad (CRM-04.03.02.04) ───────────────────────────────────────────


def abrir_hilo(
    uow: UnidadDeTrabajo,
    acceso: AccesoPortal,
    *,
    titulo: str,
    cuerpo: str,
    categoria: str = "general",
    moderar: bool = True,
) -> HiloComunidad:
    """Un cliente publica una pregunta en la comunidad.

    Nace **en moderación** por defecto. Un foro de soporte sin moderación previa
    acaba con un cliente publicando su clave de licencia, la configuración de su
    red o el nombre de su proveedor — y eso, una vez público, ya no se puede
    retirar del todo.
    """
    hilo = HiloComunidad(
        tenant_id=acceso.tenant_id,
        titulo=titulo[:300],
        cuerpo=cuerpo,
        autor_contacto_id=acceso.contacto_id,
        categoria=categoria,
        estado="moderacion" if moderar else "abierto",
    )
    uow.db.add(hilo)
    uow.db.flush()
    return hilo


def responder_hilo(
    uow: UnidadDeTrabajo,
    hilo_id: UUID,
    *,
    cuerpo: str,
    contacto_id: UUID | None = None,
    usuario_id: UUID | None = None,
) -> RespuestaComunidad:
    """Responde a un hilo. Se marca si la respuesta es del fabricante.

    La marca no es decorativa: en un foro de soporte, la diferencia entre «lo
    dice el fabricante» y «lo dice otro cliente» es toda, y sin marcarla el
    cliente aplica el consejo de cualquiera creyendo que es oficial.
    """
    hilo = uow.db.get(HiloComunidad, hilo_id)
    if hilo is None or hilo.tenant_id != uow.tenant_id:
        raise NoEncontrado("Hilo no encontrado", error_code="service.hilo_no_encontrado")
    if hilo.estado == "cerrado":
        raise Conflicto("Ese hilo está cerrado", error_code="service.hilo_cerrado")

    fila = RespuestaComunidad(
        tenant_id=hilo.tenant_id,
        hilo_id=hilo.id,
        cuerpo=cuerpo,
        autor_contacto_id=contacto_id,
        autor_usuario_id=usuario_id,
        oficial=usuario_id is not None,
    )
    uow.db.add(fila)
    if hilo.estado == "abierto" and usuario_id is not None:
        hilo.estado = "respondido"
    uow.db.flush()
    return fila


def aceptar_respuesta(uow: UnidadDeTrabajo, hilo_id: UUID, respuesta_id: UUID) -> HiloComunidad:
    """Marca cuál fue la respuesta que funcionó.

    Es lo que separa un foro útil de un archivo de conversaciones: sin ella,
    quien llega el mes que viene tiene que leerse los treinta mensajes para saber
    cuál sirvió — y la mitad de las veces se rinde y abre un caso.
    """
    hilo = uow.db.get(HiloComunidad, hilo_id)
    if hilo is None or hilo.tenant_id != uow.tenant_id:
        raise NoEncontrado("Hilo no encontrado", error_code="service.hilo_no_encontrado")
    respuesta = uow.db.get(RespuestaComunidad, respuesta_id)
    if respuesta is None or respuesta.hilo_id != hilo.id:
        raise NoEncontrado("Respuesta no encontrada", error_code="service.respuesta_no_encontrada")
    hilo.respuesta_aceptada_id = respuesta.id
    hilo.estado = "respondido"
    return hilo


def moderar_hilo(
    uow: UnidadDeTrabajo, hilo_id: UUID, *, aprobar: bool, motivo: str = ""
) -> HiloComunidad:
    """Aprueba o rechaza un hilo pendiente."""
    hilo = uow.db.get(HiloComunidad, hilo_id)
    if hilo is None or hilo.tenant_id != uow.tenant_id:
        raise NoEncontrado("Hilo no encontrado", error_code="service.hilo_no_encontrado")
    if not aprobar and not (motivo or "").strip():
        raise ErrorValidacion(
            "Rechazar un hilo exige un motivo: el cliente que lo escribió tiene "
            "derecho a saber por qué no se publica.",
            error_code="service.rechazo_sin_motivo",
        )
    hilo.estado = "abierto" if aprobar else "cerrado"
    registrar(
        uow.db,
        accion="comunidad.moderado",
        objeto="hilo",
        objeto_id=hilo.id,
        datos={"aprobado": aprobar, "motivo": motivo},
        tenant_id=hilo.tenant_id,
    )
    return hilo


def hilos(
    db: Session,
    tenant_id: UUID,
    *,
    categoria: str = "",
    solo_publicados: bool = True,
    limite: int = 50,
) -> list[dict[str, Any]]:
    """Hilos de la comunidad.

    `solo_publicados` viene en cierto: lo que está en moderación **no se sirve**
    aunque quien pregunte sea un empleado, salvo que lo pida. Un hilo en
    moderación filtrado a la vista pública por un parámetro olvidado es
    exactamente lo que la moderación viene a impedir.
    """
    consulta = select(HiloComunidad).where(HiloComunidad.tenant_id == tenant_id)
    if solo_publicados:
        consulta = consulta.where(HiloComunidad.estado.in_(("abierto", "respondido")))
    if categoria:
        consulta = consulta.where(HiloComunidad.categoria == categoria)
    filas = (
        db.execute(consulta.order_by(HiloComunidad.updated_at.desc()).limit(limite)).scalars().all()
    )
    return [
        {
            "hilo_id": str(h.id),
            "titulo": h.titulo,
            "categoria": h.categoria,
            "estado": h.estado,
            "vistas": h.vistas,
            "resuelto": h.respuesta_aceptada_id is not None,
            "articulo_id": str(h.articulo_id) if h.articulo_id else None,
        }
        for h in filas
    ]


def convertir_en_articulo(
    uow: UnidadDeTrabajo, hilo_id: UUID, *, clave: str, audiencia: str = "cliente"
) -> Any:
    """Convierte un hilo resuelto en artículo de conocimiento.

    Solo si tiene respuesta aceptada: convertir un hilo sin resolver crea un
    artículo que describe un problema y no su solución, que es la peor cosa que
    puede haber en una base de conocimiento — parece una respuesta y no lo es.
    """
    from services.service import conocimiento as kb

    hilo = uow.db.get(HiloComunidad, hilo_id)
    if hilo is None or hilo.tenant_id != uow.tenant_id:
        raise NoEncontrado("Hilo no encontrado", error_code="service.hilo_no_encontrado")
    if hilo.respuesta_aceptada_id is None:
        raise Conflicto(
            "Ese hilo no tiene respuesta aceptada: el artículo describiría el "
            "problema y no su solución.",
            error_code="service.hilo_sin_respuesta_aceptada",
        )
    respuesta = uow.db.get(RespuestaComunidad, hilo.respuesta_aceptada_id)

    articulo, _ = kb.crear_articulo(
        uow,
        clave=clave,
        titulo=hilo.titulo,
        resumen=hilo.cuerpo[:500],
        cuerpo=(respuesta.cuerpo if respuesta else ""),
        audiencia="interno",
    )
    hilo.articulo_id = articulo.id
    del audiencia  # se publica aparte, con su aprobación
    return articulo
