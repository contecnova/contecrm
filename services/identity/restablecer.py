"""Volver a entrar cuando se ha olvidado la contraseña (CRM-00.05.01.26).

Sin esto, olvidar la contraseña era un billete de ida: no había forma de
recuperarla desde la pantalla, así que la única salida era que alguien de dentro
la cambiara a mano. Eso produce dos cosas, las dos malas: contraseñas dictadas
por teléfono, y administradores que acaban poniendo una igual para todos porque
la piden diez veces al día.

Las reglas son las de un enlace de un solo uso, y ninguna es decorativa:

**La respuesta es la misma exista o no ese correo.** Distinguirlas convierte
esta pantalla en un comprobador de qué correos tienen cuenta aquí, que es
exactamente la lista que quiere quien va a intentar entrar.

**El token se guarda hasheado.** Quien lea la base de datos no puede usar los
enlaces pendientes. Es la misma razón por la que no se guarda la contraseña.

**Caduca pronto y vale una vez.** Un enlace de recuperación viaja por correo, y
el correo se reenvía, se archiva y se queda en el histórico del cliente de
correo del portátil que alguien vende dos años después.

**Y al usarlo se cierran todas las sesiones.** Si alguien pide restablecer es
porque no puede entrar, o porque sospecha: dejar abiertas las sesiones que ya
había es dejar dentro justo a quien motivó el cambio.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, NoAutenticado, Prohibido
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import Boolean, DateTime, Index, String, select
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Cuánto vale el enlace. Corto: el que lo pide está delante de la pantalla, y lo
# que alarga la vida del enlace alarga la ventana de quien lo intercepte.
MINUTOS = 30

# Longitud mínima de la contraseña nueva. Aquí y no solo en el formulario: una
# comprobación que solo vive en el navegador no comprueba nada.
MINIMO = 12


class EnlaceRestablecer(Base):
    """Un enlace de recuperación emitido, con su rastro."""

    __tablename__ = "enlaces_restablecer"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # Hasheado, nunca el token. Quien lea la base no puede usar lo pendiente.
    hash_token: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True, info={"secreto": True}
    )
    caduca_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Las dos son dato personal: una IP identifica a una persona lo bastante
    # como para que el RGPD la trate así, y estas además dicen desde dónde se
    # intentó recuperar una cuenta.
    ip_solicitud: Mapped[str | None] = mapped_column(
        String(64), nullable=True, info={"sensibilidad": "personal"}
    )
    ip_uso: Mapped[str | None] = mapped_column(
        String(64), nullable=True, info={"sensibilidad": "personal"}
    )
    # Se anota si el correo no existía: el que pide no lo sabe, pero quien vigila
    # la instalación sí necesita ver que alguien está probando correos.
    encontrado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (Index("ix_enlaces_restablecer", "tenant_id", "usuario_id", "usado_at"),)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _hash(valor: str) -> str:
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


def solicitar(uow: UnidadDeTrabajo, *, email: str, ip: str = "") -> str:
    """Emite un enlace de recuperación. Devuelve el token, o cadena vacía.

    Cadena vacía cuando ese correo no tiene cuenta. **Quien llama tiene que
    contestar lo mismo en los dos casos**: la diferencia es la que convierte
    esto en un comprobador de correos.
    """
    from services.identity.modelos import Usuario

    limpio = (email or "").strip().lower()
    usuario = uow.db.execute(
        select(Usuario).where(Usuario.email == limpio, Usuario.activo.is_(True))
    ).scalar_one_or_none()
    if usuario is None:
        logger.info("restablecer.correo_desconocido", ip=ip)
        return ""

    token = secrets.token_urlsafe(32)
    uow.db.add(
        EnlaceRestablecer(
            tenant_id=uow.tenant_id,
            usuario_id=usuario.id,
            hash_token=_hash(token),
            caduca_at=_ahora() + timedelta(minutes=MINUTOS),
            ip_solicitud=ip or None,
        )
    )
    uow.db.flush()
    uow.emitir(
        "user.password.reset_requested",
        subject=("usuario", usuario.id),
        data={"usuario_id": str(usuario.id), "email": usuario.email},
    )
    return token


def confirmar(db: Session, token: str, *, contrasena: str, ip: str = "") -> UUID:
    """Cambia la contraseña con el enlace. Devuelve el usuario. De un solo uso.

    La sesión es **de sistema** y la acotación la hace el propio token: quien
    llega aquí todavía no ha entrado, así que no hay tenant en el contexto. Es
    lo mismo que el refresco de sesión y que el enlace del portal — lo que acota
    no es el tenant, es el secreto.
    """
    from services.identity import servicio as svc
    from services.identity.modelos import Usuario

    if len(contrasena or "") < MINIMO:
        raise ErrorValidacion(
            f"La contraseña necesita al menos {MINIMO} caracteres",
            error_code="restablecer.contrasena_corta",
            detalle={"minimo": MINIMO},
        )

    enlace = db.execute(
        select(EnlaceRestablecer).where(EnlaceRestablecer.hash_token == _hash(token or ""))
    ).scalar_one_or_none()
    # Mismo error para todo: inexistente, usado o caducado. Distinguirlos le
    # diría a quien prueba si ese enlace llegó a existir.
    if enlace is None or enlace.usado_at is not None:
        raise NoAutenticado("El enlace no vale", error_code="restablecer.enlace_no_valido")
    caduca = (
        enlace.caduca_at
        if enlace.caduca_at.tzinfo
        else enlace.caduca_at.replace(tzinfo=timezone.utc)
    )
    if caduca < _ahora():
        raise NoAutenticado("El enlace no vale", error_code="restablecer.enlace_no_valido")

    usuario = db.get(Usuario, enlace.usuario_id)
    if usuario is None or not usuario.activo:
        raise NoAutenticado("El enlace no vale", error_code="restablecer.enlace_no_valido")

    # SI EL TENANT FUERZA EL SSO, aquí no se pone contraseña (CRM-00.05.01.13).
    #
    # No lo miraba nadie: se podía pedir el enlace, elegir una contraseña nueva
    # y que el sistema la guardara tan contento — para después rechazarla en
    # cada intento de entrar, porque el login sí lo comprueba. El usuario acaba
    # convencido de que escribe mal la contraseña que acaba de poner.
    #
    # Y lo de fondo: «sin contraseña local» tiene que valer también para la
    # puerta que las crea, no solo para la que las acepta.
    from services.identity.sso_gobierno import puede_tener_contrasena_local

    if not puede_tener_contrasena_local(db, enlace.tenant_id, usuario.email):
        raise Prohibido(
            "Esta organización entra por su proveedor de identidad: aquí no se "
            "pone contraseña. Entra por el enlace de tu organización.",
            error_code="restablecer.sso_obligatorio",
        )

    usuario.hash_contrasena = svc.hashear_contrasena(contrasena)
    enlace.usado_at = _ahora()
    enlace.ip_uso = ip or None
    # Todas las sesiones fuera: quien pide restablecer no puede entrar, o
    # sospecha. Dejar abiertas las que había es dejar dentro a quien lo motivó.
    svc._revocar_todas(db, usuario.id, motivo="restablecer_contrasena")
    db.flush()
    logger.info("restablecer.hecho", usuario_id=str(usuario.id))
    return usuario.id


def pendientes(db: Session, usuario_id: UUID) -> list[dict[str, Any]]:
    """Los enlaces vivos de un usuario, para poder mirarlos desde dentro."""
    filas = (
        db.execute(
            select(EnlaceRestablecer).where(
                EnlaceRestablecer.usuario_id == usuario_id,
                EnlaceRestablecer.usado_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    ahora = _ahora()
    return [
        {
            "id": str(f.id),
            "pedido_at": f.created_at.isoformat(),
            "caduca_at": f.caduca_at.isoformat(),
            "caducado": (
                f.caduca_at if f.caduca_at.tzinfo else f.caduca_at.replace(tzinfo=timezone.utc)
            )
            < ahora,
            "ip_solicitud": f.ip_solicitud,
        }
        for f in filas
    ]
