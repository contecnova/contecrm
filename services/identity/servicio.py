"""Lógica de identidad: autenticación, sesiones, credenciales y suplantación."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from crmcore.audit.chain import registrar
from crmcore.authz.rbac import ROLES_BASE, Rol, resolver_permisos
from crmcore.config import get_settings
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoAutenticado, NoEncontrado, Prohibido
from crmcore.logging import get_logger
from services.identity.modelos import ClaveApi, Membresia, RolTenant, Sesion, Usuario

logger = get_logger(__name__)

# Argon2id con los parámetros recomendados por OWASP. Se dejan explícitos y no
# por defecto porque el coste es una decisión de seguridad con consecuencia
# medible en latencia de login, y tiene que poder revisarse a la vista.
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)

# Prefijo de las claves de API. Sirve para que un secreto filtrado en un
# repositorio público se pueda detectar automáticamente por su forma.
PREFIJO_CLAVE = "crm_"


# ── Contraseñas ───────────────────────────────────────────────────────────


def hashear_contrasena(contrasena: str) -> str:
    if len(contrasena) < 12:
        raise ErrorValidacion(
            "La contraseña debe tener al menos 12 caracteres",
            error_code="auth.contrasena_corta",
        )
    return _hasher.hash(contrasena)


def verificar_contrasena(hash_guardado: str | None, contrasena: str) -> bool:
    """Verifica en tiempo aproximadamente constante.

    Cuando no hay hash (usuario solo-SSO o inexistente) se hashea igualmente un
    valor de descarte. Si se devolviera `False` de inmediato, la diferencia de
    tiempo diría a quien lo intenta qué correos existen en el sistema.
    """
    if not hash_guardado:
        _hasher.hash("descartar-para-igualar-el-tiempo")
        return False
    try:
        return _hasher.verify(hash_guardado, contrasena)
    except (VerifyMismatchError, InvalidHashError):
        return False


# ── TOTP (CRM-00.05.01.06) ────────────────────────────────────────────────


def generar_secreto_totp() -> str:
    """Secreto TOTP en base32, que es lo que leen las aplicaciones de códigos."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def codigo_totp(secreto: str, momento: float | None = None) -> str:
    """Código TOTP de 6 dígitos (RFC 6238) para un instante."""
    clave = base64.b32decode(secreto + "=" * (-len(secreto) % 8))
    contador = int((momento or time.time()) // 30)
    digest = hmac.new(clave, struct.pack(">Q", contador), hashlib.sha1).digest()
    desplazamiento = digest[-1] & 0x0F
    valor = struct.unpack(">I", digest[desplazamiento : desplazamiento + 4])[0] & 0x7FFFFFFF
    return f"{valor % 1_000_000:06d}"


def verificar_totp(secreto: str, codigo: str, *, ventana: int | None = None) -> bool:
    """Verifica un código admitiendo desfase de reloj.

    La ventana existe porque el reloj del móvil y el del servidor no coinciden
    al segundo. Cada paso son 30 s; con ventana 1 se admite ±30 s, que absorbe
    el desfase normal sin ampliar de más el margen para probar códigos.
    """
    ventana = ventana if ventana is not None else get_settings().totp_ventana_pasos
    ahora = time.time()
    return any(
        # Comparación en tiempo constante también aquí: un código es un secreto.
        hmac.compare_digest(codigo_totp(secreto, ahora + paso * 30), codigo.strip())
        for paso in range(-ventana, ventana + 1)
    )


def generar_codigos_recuperacion(cuantos: int = 10) -> tuple[list[str], list[str]]:
    """Devuelve (códigos en claro, hashes). Los primeros se enseñan una vez."""
    codigos = [secrets.token_hex(5) for _ in range(cuantos)]
    return codigos, [hashlib.sha256(c.encode()).hexdigest() for c in codigos]


# ── Autenticación ─────────────────────────────────────────────────────────


def autenticar(
    db: Session,
    *,
    email: str,
    contrasena: str,
    tenant_id: UUID,
    codigo_mfa: str = "",
) -> Usuario:
    """Comprueba credenciales y devuelve el usuario. Lanza si no procede."""
    s = get_settings()
    usuario = db.execute(
        select(Usuario).where(Usuario.email == email.strip().lower())
    ).scalar_one_or_none()

    if usuario and usuario.bloqueado_hasta and usuario.bloqueado_hasta > datetime.now(timezone.utc):
        raise NoAutenticado(
            "La cuenta está bloqueada temporalmente por intentos fallidos",
            error_code="auth.cuenta_bloqueada",
        )

    if not usuario or not verificar_contrasena(usuario.hash_contrasena, contrasena):
        if usuario:
            _anotar_fallo(db, usuario, s.login_max_intentos, s.login_bloqueo_minutos)
        # El mismo mensaje tanto si el correo no existe como si la contraseña es
        # incorrecta: distinguirlos convierte el formulario de acceso en un
        # comprobador de qué correos están dados de alta.
        raise NoAutenticado(
            "Credenciales incorrectas", error_code="auth.credenciales_invalidas"
        )

    if not usuario.activo:
        raise Prohibido("La cuenta está desactivada", error_code="auth.cuenta_inactiva")

    membresia = _membresia(db, usuario.id, tenant_id)
    if membresia is None or not membresia.activa:
        # Otra vez el mismo mensaje: decir «existes pero no perteneces a este
        # tenant» confirmaría la existencia de la cuenta a quien no debe saberlo.
        raise NoAutenticado(
            "Credenciales incorrectas", error_code="auth.credenciales_invalidas"
        )

    from crmcore.runtime import settings as rt

    exige_mfa = usuario.mfa_activo or bool(rt.efectivo("mfa_obligatoria", db))
    if exige_mfa:
        if not usuario.mfa_activo:
            raise Prohibido(
                "Este tenant exige doble factor: configúralo para poder entrar",
                error_code="auth.mfa_no_configurada",
            )
        if not codigo_mfa:
            raise NoAutenticado(
                "Falta el código de doble factor", error_code="auth.mfa_requerida"
            )
        if not _verificar_segundo_factor(db, usuario, codigo_mfa):
            _anotar_fallo(db, usuario, s.login_max_intentos, s.login_bloqueo_minutos)
            raise NoAutenticado(
                "El código de doble factor no es válido", error_code="auth.mfa_invalida"
            )

    usuario.intentos_fallidos = 0
    usuario.bloqueado_hasta = None
    usuario.ultimo_acceso_at = datetime.now(timezone.utc)
    return usuario


def _verificar_segundo_factor(db: Session, usuario: Usuario, codigo: str) -> bool:
    """TOTP o, si no, un código de recuperación (que se consume)."""
    if usuario.mfa_secreto and verificar_totp(usuario.mfa_secreto, codigo):
        return True
    hash_codigo = hashlib.sha256(codigo.strip().encode()).hexdigest()
    if hash_codigo in (usuario.mfa_recuperacion or []):
        # Se consume: un código de recuperación vale una vez. Si valiera
        # siempre, sería una contraseña permanente escrita en un papel.
        usuario.mfa_recuperacion = [c for c in usuario.mfa_recuperacion if c != hash_codigo]
        registrar(
            db,
            accion="usuario.mfa_recuperacion_usada",
            objeto="usuario",
            objeto_id=usuario.id,
            datos={"restantes": len(usuario.mfa_recuperacion)},
        )
        return True
    return False


def _anotar_fallo(db: Session, usuario: Usuario, maximo: int, minutos: int) -> None:
    usuario.intentos_fallidos += 1
    if usuario.intentos_fallidos >= maximo:
        usuario.bloqueado_hasta = datetime.now(timezone.utc) + timedelta(minutes=minutos)
        logger.warning("auth.cuenta_bloqueada", usuario_id=str(usuario.id))


def _membresia(db: Session, usuario_id: UUID, tenant_id: UUID) -> Membresia | None:
    return db.execute(
        select(Membresia).where(
            Membresia.usuario_id == usuario_id, Membresia.tenant_id == tenant_id
        )
    ).scalar_one_or_none()


# ── Permisos efectivos ────────────────────────────────────────────────────


def permisos_efectivos(db: Session, usuario_id: UUID, tenant_id: UUID) -> frozenset[str]:
    """Permisos del usuario en ese tenant: roles base + roles del tenant."""
    membresia = _membresia(db, usuario_id, tenant_id)
    if membresia is None:
        return frozenset()

    propios = {
        r.nombre: Rol(
            nombre=r.nombre,
            permisos=frozenset(r.permisos or []),
            hereda_de=r.hereda_de,
            descripcion=r.descripcion,
        )
        for r in db.execute(select(RolTenant).where(RolTenant.tenant_id == tenant_id))
        .scalars()
        .all()
    }
    # Los del tenant tienen prioridad: un tenant puede redefinir «comercial» a
    # su manera. Lo que no puede es redefinir «admin» y quedarse sin nadie que
    # administre, y por eso los roles de sistema no se pueden borrar.
    catalogo = {**ROLES_BASE, **propios}

    permisos: set[str] = set()
    for rol in membresia.roles or []:
        permisos |= resolver_permisos(str(rol), roles=catalogo, conjuntos={})
    return frozenset(permisos)


# ── Sesiones y tokens ─────────────────────────────────────────────────────


def _hash(valor: str) -> str:
    return hashlib.sha256(valor.encode()).hexdigest()


def crear_sesion(
    db: Session,
    *,
    usuario: Usuario,
    tenant_id: UUID,
    ip: str = "",
    user_agent: str = "",
    actor_real_id: UUID | None = None,
    motivo_suplantacion: str | None = None,
) -> tuple[Sesion, str, str]:
    """Crea la sesión y devuelve (sesión, token de acceso, token de refresco)."""
    s = get_settings()
    ahora = datetime.now(timezone.utc)

    from crmcore.runtime import settings as rt

    maximo = int(rt.efectivo("sesiones_max_por_usuario", db) or 0)
    if maximo > 0:
        vivas = (
            db.execute(
                select(Sesion)
                .where(
                    Sesion.usuario_id == usuario.id,
                    Sesion.tenant_id == tenant_id,
                    Sesion.revocada_at.is_(None),
                    Sesion.expira_at > ahora,
                )
                .order_by(Sesion.ultima_actividad_at)
            )
            .scalars()
            .all()
        )
        # Se cierran las más ANTIGUAS por actividad, no la que se acaba de
        # pedir: negarle la entrada a quien está autenticándose correctamente
        # sería incomprensible para él y no aporta seguridad.
        for sobrante in vivas[: max(0, len(vivas) - maximo + 1)]:
            sobrante.revocada_at = ahora
            sobrante.motivo_revocacion = "limite_sesiones"

    refresco = secrets.token_urlsafe(48)
    sesion = Sesion(
        tenant_id=tenant_id,
        usuario_id=usuario.id,
        hash_refresco=_hash(refresco),
        ip=ip or None,
        user_agent=(user_agent or "")[:400] or None,
        expira_at=ahora + timedelta(days=s.refresh_token_dias),
        actor_real_id=actor_real_id,
        motivo_suplantacion=motivo_suplantacion,
    )
    db.add(sesion)
    db.flush()

    acceso = emitir_token_acceso(
        db,
        usuario=usuario,
        tenant_id=tenant_id,
        sesion_id=sesion.id,
        actor_real_id=actor_real_id,
    )
    return sesion, acceso, refresco


def emitir_token_acceso(
    db: Session,
    *,
    usuario: Usuario,
    tenant_id: UUID,
    sesion_id: UUID,
    actor_real_id: UUID | None = None,
) -> str:
    """JWT de acceso con los permisos ya resueltos.

    Los permisos van dentro del token para que los servicios no tengan que
    consultarlos en cada petición. El precio es que un cambio de permisos no se
    ve hasta que el token se renueva —minutos— y eso está asumido: para quitar
    el acceso **ya** se revoca la sesión, que sí es inmediata en el refresco.
    """
    s = get_settings()
    membresia = _membresia(db, usuario.id, tenant_id)
    ahora = datetime.now(timezone.utc)
    carga = {
        "sub": str(usuario.id),
        "tenant": str(tenant_id),
        "sid": str(sesion_id),
        "tipo": "usuario",
        "roles": list(membresia.roles or []) if membresia else [],
        "permisos": sorted(permisos_efectivos(db, usuario.id, tenant_id)),
        "plataforma": usuario.es_plataforma,
        "iat": int(ahora.timestamp()),
        "exp": int((ahora + timedelta(minutes=s.access_token_minutos)).timestamp()),
    }
    if membresia and membresia.business_unit_id:
        carga["bu"] = str(membresia.business_unit_id)
    if actor_real_id:
        carga["actor_real"] = str(actor_real_id)
    return jwt.encode(carga, s.secret_key.get_secret_value(), algorithm=s.jwt_algorithm)


def renovar(db: Session, refresco: str) -> tuple[str, str]:
    """Renueva con rotación del token de refresco.

    **Rotación**: cada uso invalida el refresco anterior y entrega otro. Eso es
    lo que permite detectar el robo: si alguien usa un refresco ya rotado, es
    que hay dos copias, y entonces se revoca la sesión entera. Sin rotación, un
    refresco robado vale hasta que caduca y nadie se entera nunca.
    """
    sesion = db.execute(
        select(Sesion).where(Sesion.hash_refresco == _hash(refresco))
    ).scalar_one_or_none()
    if sesion is None:
        raise NoAutenticado(
            "El token de refresco no es válido", error_code="auth.refresco_invalido"
        )
    if not sesion.esta_viva:
        # Reutilización de un refresco ya rotado o de una sesión revocada: se
        # revocan TODAS las sesiones del usuario. Es agresivo a propósito —
        # significa que alguien tiene una copia que no debería.
        _revocar_todas(db, sesion.usuario_id, motivo="reutilizacion_refresco")
        logger.warning("auth.refresco_reutilizado", usuario_id=str(sesion.usuario_id))
        raise NoAutenticado(
            "La sesión ha caducado. Vuelve a iniciar sesión.",
            error_code="auth.sesion_caducada",
        )

    usuario = db.get(Usuario, sesion.usuario_id)
    if usuario is None or not usuario.activo:
        raise Prohibido("La cuenta está desactivada", error_code="auth.cuenta_inactiva")

    nuevo_refresco = secrets.token_urlsafe(48)
    sesion.hash_refresco = _hash(nuevo_refresco)
    sesion.ultima_actividad_at = datetime.now(timezone.utc)
    acceso = emitir_token_acceso(
        db,
        usuario=usuario,
        tenant_id=sesion.tenant_id,
        sesion_id=sesion.id,
        actor_real_id=sesion.actor_real_id,
    )
    return acceso, nuevo_refresco


def revocar(db: Session, sesion_id: UUID, *, motivo: str = "cierre_sesion") -> None:
    sesion = db.get(Sesion, sesion_id)
    if sesion is None:
        raise NoEncontrado("La sesión no existe", error_code="auth.sesion_no_encontrada")
    sesion.revocada_at = datetime.now(timezone.utc)
    sesion.motivo_revocacion = motivo


def _revocar_todas(db: Session, usuario_id: UUID, *, motivo: str) -> int:
    ahora = datetime.now(timezone.utc)
    sesiones = (
        db.execute(
            select(Sesion).where(
                Sesion.usuario_id == usuario_id, Sesion.revocada_at.is_(None)
            )
        )
        .scalars()
        .all()
    )
    for s_ in sesiones:
        s_.revocada_at = ahora
        s_.motivo_revocacion = motivo
    return len(sesiones)


# ── Suplantación (CRM-00.05.02.10) ────────────────────────────────────────


def suplantar(
    db: Session, *, soporte: Usuario, usuario_id: UUID, tenant_id: UUID, motivo: str
) -> tuple[Sesion, str, str]:
    """Abre una sesión como otro usuario, con motivo, caducidad y rastro.

    Las tres condiciones son necesarias juntas. Sin motivo no hay forma de
    revisar si el acceso estaba justificado; sin caducidad corta, una sesión de
    soporte abierta un martes sigue viva en octubre; sin auditoría, el cliente
    no puede saber quién entró en sus datos. Quitar cualquiera de las tres
    convierte esto en una puerta trasera con buena intención.
    """
    from crmcore.runtime import settings as rt

    if not bool(rt.efectivo("suplantacion_enabled", db)):
        raise Prohibido(
            "La suplantación está desactivada en este tenant",
            error_code="auth.suplantacion_desactivada",
        )
    if not soporte.es_plataforma:
        raise Prohibido(
            "Solo el personal de plataforma puede suplantar",
            error_code="auth.suplantacion_no_permitida",
        )
    if not motivo.strip():
        raise ErrorValidacion(
            "La suplantación exige un motivo escrito",
            error_code="auth.suplantacion_sin_motivo",
        )

    objetivo = db.get(Usuario, usuario_id)
    if objetivo is None:
        raise NoEncontrado("El usuario no existe", error_code="usuario.no_encontrado")

    sesion, acceso, refresco = crear_sesion(
        db,
        usuario=objetivo,
        tenant_id=tenant_id,
        actor_real_id=soporte.id,
        motivo_suplantacion=motivo.strip(),
    )
    # La caducidad de la sesión de suplantación es la del ajuste, no la normal.
    minutos = int(rt.efectivo("suplantacion_max_minutos", db) or 60)
    sesion.expira_at = datetime.now(timezone.utc) + timedelta(minutes=minutos)

    registrar(
        db,
        accion="soporte.acceso_tenant",
        objeto="usuario",
        objeto_id=usuario_id,
        datos={"soporte_id": str(soporte.id), "minutos": minutos},
        motivo=motivo,
        tenant_id=tenant_id,
    )
    logger.warning(
        "auth.suplantacion_iniciada",
        soporte_id=str(soporte.id),
        objetivo_id=str(usuario_id),
        minutos=minutos,
    )
    return sesion, acceso, refresco


# ── Claves de API ─────────────────────────────────────────────────────────


def crear_clave_api(
    db: Session,
    *,
    tenant_id: UUID,
    nombre: str,
    scopes: list[str],
    rol: str = "integracion",
    dias: int | None = None,
    ips_permitidas: list[str] | None = None,
    creada_por: UUID | None = None,
) -> tuple[ClaveApi, str]:
    """Crea una clave y devuelve (fila, secreto en claro). El secreto no se
    vuelve a poder leer."""
    s = get_settings()
    secreto = PREFIJO_CLAVE + secrets.token_urlsafe(s.api_key_bytes)
    dias = s.api_key_caducidad_dias if dias is None else dias

    clave = ClaveApi(
        tenant_id=tenant_id,
        nombre=nombre.strip(),
        prefijo=secreto[:12],
        hash_secreto=_hash(secreto),
        scopes=scopes,
        rol=rol,
        ips_permitidas=ips_permitidas or [],
        expira_at=(datetime.now(timezone.utc) + timedelta(days=dias)) if dias > 0 else None,
        creada_por=creada_por,
    )
    db.add(clave)
    registrar(
        db,
        accion="clave_api.creada",
        objeto="clave_api",
        objeto_id=clave.id,
        datos={"nombre": nombre, "scopes": scopes, "rol": rol, "caduca_en_dias": dias},
        tenant_id=tenant_id,
    )
    return clave, secreto


def validar_clave_api(db: Session, secreto: str, *, ip: str = "") -> ClaveApi:
    """Valida una clave de API y devuelve su fila."""
    clave = db.execute(
        select(ClaveApi).where(ClaveApi.hash_secreto == _hash(secreto))
    ).scalar_one_or_none()
    if clave is None or clave.revocada_at is not None:
        raise NoAutenticado("Clave de API no válida", error_code="auth.clave_invalida")
    if clave.expira_at and clave.expira_at < datetime.now(timezone.utc):
        raise NoAutenticado("La clave de API ha caducado", error_code="auth.clave_caducada")
    if clave.ips_permitidas and ip and ip not in clave.ips_permitidas:
        logger.warning("auth.clave_ip_no_permitida", prefijo=clave.prefijo, ip=ip)
        raise Prohibido(
            "La clave no admite esta dirección de origen",
            error_code="auth.clave_ip_no_permitida",
        )
    clave.ultimo_uso_at = datetime.now(timezone.utc)
    return clave


# ── Alta de usuarios ──────────────────────────────────────────────────────


def crear_usuario(
    uow: UnidadDeTrabajo,
    *,
    email: str,
    nombre: str,
    tenant_id: UUID,
    roles: list[str],
    contrasena: str | None = None,
    via: str = "manual",
) -> Usuario:
    """Alta de usuario y su membresía en el tenant."""
    email = email.strip().lower()
    usuario = uow.db.execute(
        select(Usuario).where(Usuario.email == email)
    ).scalar_one_or_none()

    if usuario is None:
        usuario = Usuario(
            email=email,
            nombre=nombre.strip(),
            hash_contrasena=hashear_contrasena(contrasena) if contrasena else None,
        )
        uow.db.add(usuario)
        uow.db.flush()
    elif _membresia(uow.db, usuario.id, tenant_id) is not None:
        raise Conflicto(
            "Ese usuario ya pertenece a este tenant", error_code="usuario.ya_existe"
        )

    uow.db.add(Membresia(tenant_id=tenant_id, usuario_id=usuario.id, roles=roles))
    registrar(
        uow.db,
        accion="usuario.alta",
        objeto="usuario",
        objeto_id=usuario.id,
        datos={"email": email, "roles": roles, "via": via},
        tenant_id=tenant_id,
    )
    uow.emitir(
        "user.provisioned",
        subject=("usuario", usuario.id),
        data={"user_id": str(usuario.id), "email": email, "via": via},
    )
    return usuario


def desactivar_usuario(
    uow: UnidadDeTrabajo, usuario_id: UUID, tenant_id: UUID, *, via: str = "manual"
) -> None:
    """Baja del usuario en un tenant: desactiva su membresía y corta sus sesiones.

    No borra el usuario. Borrarlo dejaría huérfano todo lo que creó —cuentas,
    oportunidades, apuntes de auditoría— y el historial pasaría a referirse a un
    identificador que ya no existe.
    """
    membresia = _membresia(uow.db, usuario_id, tenant_id)
    if membresia is None:
        raise NoEncontrado(
            "El usuario no pertenece a este tenant", error_code="usuario.sin_membresia"
        )
    membresia.activa = False
    revocadas = _revocar_todas(uow.db, usuario_id, motivo="baja_usuario")

    registrar(
        uow.db,
        accion="usuario.baja",
        objeto="usuario",
        objeto_id=usuario_id,
        datos={"sesiones_revocadas": revocadas, "via": via},
        tenant_id=tenant_id,
    )
    uow.emitir(
        "user.deprovisioned",
        subject=("usuario", usuario_id),
        data={"user_id": str(usuario_id), "via": via},
    )


def _sin_usar(*_a: Any) -> None:  # pragma: no cover
    """Mantiene el import de `Any` para las anotaciones."""
