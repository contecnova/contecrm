"""Passkeys: entrar sin contraseña y sin poder caer en un engaño (CRM-00.05.01.23).

Una passkey es una pareja de claves que guarda el dispositivo —el llavero del
teléfono, el del portátil, una llave física— y que **el navegador solo entrega
al dominio que la creó**. Eso cambia la naturaleza del problema: una contraseña
robada sirve desde cualquier sitio, y una passkey no se puede teclear en una
página falsa porque el navegador no la ofrece ahí. Es la única credencial de
este sistema que no se pierde por phishing.

Lo que hay que entender de cómo está montado:

**El secreto nunca sale del dispositivo.** Aquí se guarda la clave pública y un
contador; con eso se comprueba una firma, y con eso no se puede suplantar a
nadie. Una base de datos filtrada no da acceso a ninguna cuenta.

**El reto se guarda en el servidor y se usa una vez.** Si el reto lo eligiera el
cliente, o valiera dos veces, una firma capturada se podría reproducir — que es
justo el ataque del que protege esto.

**El contador se comprueba y solo sube.** Un autenticador clonado lo delata:
dos copias de la misma llave acaban firmando con un contador que retrocede. No
todos los dispositivos lo llevan —los que no, lo dejan en cero—, así que se
comprueba solo cuando hay algo que comprobar.

**Y el dominio y los orígenes no se escriben aquí**: salen de la configuración,
que ya dice dónde vive esto.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from crmcore.db.base import Base
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoAutenticado, NoEncontrado
from crmcore.ids import nuevo_id
from crmcore.logging import get_logger
from sqlalchemy import DateTime, Index, Integer, LargeBinary, String, select
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, Session, mapped_column

logger = get_logger(__name__)

# Cuánto vale un reto. Muy corto: el usuario está delante del navegador y el
# diálogo se contesta en segundos. Alargarlo solo alarga la ventana de reproducir
# una firma capturada.
MINUTOS_RETO = 5

PROPOSITOS = ("registro", "entrada")


class Passkey(Base):
    """Una llave registrada por alguien, con su rastro de uso."""

    __tablename__ = "passkeys"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    usuario_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    # El identificador que devuelve el autenticador, en base64url. Único en toda
    # la instalación: la misma llave no puede estar registrada dos veces.
    credencial_id: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    # La pública. La privada no sale nunca del dispositivo.
    clave_publica: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # Lo que ha firmado esta llave. Solo puede subir.
    contador: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Cómo la llama su dueño: «el iPhone», «la llave del cajón». Sin un nombre,
    # revocar una de tres es elegir a ciegas.
    nombre: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    # Qué modelo de autenticador es, tal como se identifica.
    aaguid: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    ultimo_uso_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_passkeys_usuario", "tenant_id", "usuario_id"),)


class RetoPasskey(Base):
    """Un reto emitido, para que una firma no se pueda reproducir."""

    __tablename__ = "retos_passkey"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=nuevo_id)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    usuario_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    reto: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    proposito: Mapped[str] = mapped_column(String(20), nullable=False)
    caduca_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _config() -> tuple[str, str, tuple[str, ...]]:
    from crmcore.config import get_settings

    s = get_settings()
    return s.passkey_dominio, s.passkey_nombre, s.passkey_origenes_validos


def _guardar_reto(
    db: Session, *, tenant_id: UUID, usuario_id: UUID | None, reto: bytes, proposito: str
) -> None:
    from webauthn.helpers import bytes_to_base64url

    db.add(
        RetoPasskey(
            tenant_id=tenant_id,
            usuario_id=usuario_id,
            reto=bytes_to_base64url(reto),
            proposito=proposito,
            caduca_at=_ahora() + timedelta(minutes=MINUTOS_RETO),
        )
    )
    db.flush()


def _consumir_reto(db: Session, *, reto_b64: str, proposito: str) -> RetoPasskey:
    """Gasta el reto. De un solo uso, y por eso no se puede reproducir una firma."""
    fila = db.execute(
        select(RetoPasskey).where(RetoPasskey.reto == reto_b64, RetoPasskey.proposito == proposito)
    ).scalar_one_or_none()
    if fila is None or fila.usado_at is not None:
        raise NoAutenticado("Ese intento ya no vale", error_code="passkey.reto_no_valido")
    caduca = (
        fila.caduca_at if fila.caduca_at.tzinfo else fila.caduca_at.replace(tzinfo=timezone.utc)
    )
    if caduca < _ahora():
        raise NoAutenticado("Ese intento ya no vale", error_code="passkey.reto_no_valido")
    fila.usado_at = _ahora()
    db.flush()
    return fila


# ── Registrar una llave ───────────────────────────────────────────────────


def opciones_registro(db: Session, *, tenant_id: UUID, usuario: Any) -> dict[str, Any]:
    """Lo que el navegador necesita para crear una llave nueva.

    Se le pasan las que ya tiene para que **no registre dos veces el mismo
    dispositivo**: sin eso, quien pulsa el botón dos veces acaba con dos llaves
    idénticas y una lista que no dice nada.
    """
    import json

    from webauthn import generate_registration_options, options_to_json
    from webauthn.helpers import base64url_to_bytes
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria,
        PublicKeyCredentialDescriptor,
        ResidentKeyRequirement,
        UserVerificationRequirement,
    )

    dominio, nombre_rp, _ = _config()
    ya = [
        PublicKeyCredentialDescriptor(id=base64url_to_bytes(p.credencial_id))
        for p in db.execute(select(Passkey).where(Passkey.usuario_id == usuario.id)).scalars().all()
    ]
    opciones = generate_registration_options(
        rp_id=dominio,
        rp_name=nombre_rp,
        user_id=str(usuario.id).encode(),
        user_name=usuario.email,
        user_display_name=usuario.nombre or usuario.email,
        exclude_credentials=ya,
        authenticator_selection=AuthenticatorSelectionCriteria(
            # Residente: la llave se guarda en el dispositivo con su nombre, así
            # que se puede entrar **sin escribir el correo**. Es la diferencia
            # entre una passkey y un segundo factor.
            resident_key=ResidentKeyRequirement.PREFERRED,
            # Y con verificación del usuario: huella, cara o PIN. Sin ella, una
            # llave robada del bolsillo entra sola.
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    _guardar_reto(
        db,
        tenant_id=tenant_id,
        usuario_id=usuario.id,
        reto=opciones.challenge,
        proposito="registro",
    )
    return dict(json.loads(options_to_json(opciones)))


def guardar_registro(
    uow: UnidadDeTrabajo, *, usuario_id: UUID, respuesta: dict[str, Any], nombre: str = ""
) -> Passkey:
    """Comprueba lo que devuelve el navegador y guarda la llave."""
    import json

    from webauthn import verify_registration_response
    from webauthn.helpers import base64url_to_bytes
    from webauthn.helpers.exceptions import InvalidRegistrationResponse

    dominio, _, origenes = _config()
    try:
        reto_b64 = json.loads(base64url_to_bytes(respuesta["response"]["clientDataJSON"]).decode())[
            "challenge"
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise ErrorValidacion(
            "La respuesta del navegador no tiene la forma esperada",
            error_code="passkey.respuesta_invalida",
        ) from exc

    fila_reto = _consumir_reto(uow.db, reto_b64=reto_b64, proposito="registro")
    if fila_reto.usuario_id != usuario_id:
        raise NoAutenticado("Ese intento no es tuyo", error_code="passkey.reto_ajeno")

    # Se prueban los orígenes declarados: una instalación puede servirse desde
    # varios —el dominio y su `www`— y fallar por eso sería fallar por nada.
    ultimo: Exception | None = None
    for origen in origenes:
        try:
            verificado = verify_registration_response(
                credential=respuesta,
                expected_challenge=base64url_to_bytes(reto_b64),
                expected_rp_id=dominio,
                expected_origin=origen,
            )
            break
        except InvalidRegistrationResponse as exc:
            ultimo = exc
    else:
        raise NoAutenticado(
            "Esa llave no se ha podido comprobar", error_code="passkey.registro_no_valido"
        ) from ultimo

    from webauthn.helpers import bytes_to_base64url

    credencial = bytes_to_base64url(verificado.credential_id)
    if uow.db.execute(
        select(Passkey).where(Passkey.credencial_id == credencial)
    ).scalar_one_or_none():
        raise Conflicto("Esa llave ya estaba registrada", error_code="passkey.ya_registrada")

    fila = Passkey(
        tenant_id=uow.tenant_id,
        usuario_id=usuario_id,
        credencial_id=credencial,
        clave_publica=verificado.credential_public_key,
        contador=verificado.sign_count,
        nombre=(nombre or "").strip()[:120] or "Llave sin nombre",
        aaguid=str(verificado.aaguid or ""),
    )
    uow.db.add(fila)
    uow.db.flush()
    uow.emitir(
        "user.passkey.registered",
        subject=("usuario", usuario_id),
        data={"usuario_id": str(usuario_id), "passkey_id": str(fila.id), "nombre": fila.nombre},
    )
    return fila


# ── Entrar con una llave ──────────────────────────────────────────────────


def opciones_entrada(db: Session, *, tenant_id: UUID, usuario: Any | None) -> dict[str, Any]:
    """El reto para entrar. Sin usuario, vale cualquier llave del dispositivo.

    Sin usuario a propósito: con llaves residentes no hace falta escribir el
    correo, y **no decir si ese correo existe** es lo que impide que esta
    pantalla sirva para averiguar quién tiene cuenta aquí.
    """
    import json

    from webauthn import generate_authentication_options, options_to_json
    from webauthn.helpers import base64url_to_bytes
    from webauthn.helpers.structs import (
        PublicKeyCredentialDescriptor,
        UserVerificationRequirement,
    )

    dominio, _, _ = _config()
    permitidas = []
    if usuario is not None:
        permitidas = [
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(p.credencial_id))
            for p in db.execute(select(Passkey).where(Passkey.usuario_id == usuario.id))
            .scalars()
            .all()
        ]
    opciones = generate_authentication_options(
        rp_id=dominio,
        allow_credentials=permitidas,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    _guardar_reto(
        db,
        tenant_id=tenant_id,
        usuario_id=usuario.id if usuario is not None else None,
        reto=opciones.challenge,
        proposito="entrada",
    )
    return dict(json.loads(options_to_json(opciones)))


def verificar_entrada(db: Session, *, respuesta: dict[str, Any], ip: str = "") -> Passkey:
    """Comprueba la firma y devuelve la llave. Quien llama emite los tokens."""
    import json

    from webauthn import verify_authentication_response
    from webauthn.helpers import base64url_to_bytes
    from webauthn.helpers.exceptions import InvalidAuthenticationResponse

    dominio, _, origenes = _config()
    try:
        reto_b64 = json.loads(base64url_to_bytes(respuesta["response"]["clientDataJSON"]).decode())[
            "challenge"
        ]
        credencial = respuesta["id"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ErrorValidacion(
            "La respuesta del navegador no tiene la forma esperada",
            error_code="passkey.respuesta_invalida",
        ) from exc

    _consumir_reto(db, reto_b64=reto_b64, proposito="entrada")
    llave = db.execute(
        select(Passkey).where(Passkey.credencial_id == credencial)
    ).scalar_one_or_none()
    if llave is None:
        raise NoAutenticado("Esa llave no vale aquí", error_code="passkey.desconocida")

    ultimo: Exception | None = None
    for origen in origenes:
        try:
            verificado = verify_authentication_response(
                credential=respuesta,
                expected_challenge=base64url_to_bytes(reto_b64),
                expected_rp_id=dominio,
                expected_origin=origen,
                credential_public_key=llave.clave_publica,
                credential_current_sign_count=llave.contador,
            )
            break
        except InvalidAuthenticationResponse as exc:
            ultimo = exc
    else:
        raise NoAutenticado(
            "Esa llave no se ha podido comprobar", error_code="passkey.firma_no_valida"
        ) from ultimo

    # El contador solo sube. Si baja, hay dos copias de la misma llave: se
    # rechaza y se deja dicho, porque es la única señal que da un clonado.
    if verificado.new_sign_count and verificado.new_sign_count <= llave.contador:
        logger.error(
            "passkey.contador_retrocede",
            passkey_id=str(llave.id),
            guardado=llave.contador,
            recibido=verificado.new_sign_count,
        )
        raise NoAutenticado(
            "Esa llave no se ha podido comprobar", error_code="passkey.contador_invalido"
        )
    llave.contador = verificado.new_sign_count or llave.contador
    llave.ultimo_uso_at = _ahora()
    db.flush()
    logger.info("passkey.entrada", usuario_id=str(llave.usuario_id), ip=ip)
    return llave


# ── Gestión ───────────────────────────────────────────────────────────────


def listar(db: Session, usuario_id: UUID) -> list[dict[str, Any]]:
    filas = (
        db.execute(
            select(Passkey).where(Passkey.usuario_id == usuario_id).order_by(Passkey.created_at)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(f.id),
            "nombre": f.nombre,
            "creada_at": f.created_at.isoformat(),
            "ultimo_uso_at": f.ultimo_uso_at.isoformat() if f.ultimo_uso_at else None,
            "aaguid": f.aaguid,
        }
        for f in filas
    ]


def revocar(uow: UnidadDeTrabajo, *, usuario_id: UUID, passkey_id: UUID) -> None:
    """Quita una llave. Solo su dueño, y se borra de verdad.

    De verdad y no a la papelera: una credencial revocada que sigue en una tabla
    con su clave pública invita a «restaurarla», y restaurar una credencial es
    justo lo que no puede pasar.
    """
    fila = uow.db.get(Passkey, passkey_id)
    if fila is None or fila.usuario_id != usuario_id:
        raise NoEncontrado("Esa llave no existe", error_code="passkey.no_encontrada")
    uow.db.delete(fila)
    uow.db.flush()
    uow.emitir(
        "user.passkey.revoked",
        subject=("usuario", usuario_id),
        data={"usuario_id": str(usuario_id), "passkey_id": str(passkey_id)},
    )
