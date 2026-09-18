"""Identidad: tokens, sesiones, MFA y credenciales de máquina."""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings


class _AuthSettings(BaseSettings):
    # ── Firma de tokens ───────────────────────────────────────────────────
    # Firma TODOS los tokens de acceso y refresco. Si en producción sigue
    # valiendo el placeholder, cualquiera puede emitirse un token de
    # administrador: el arranque lo comprueba y se niega a levantar.
    secret_key: SecretStr = SecretStr("CHANGE_ME_SECRET_KEY")
    jwt_algorithm: str = "HS256"

    # Duración del token de acceso. Corta a propósito: la revocación de una
    # sesión no puede invalidar un JWT ya emitido, así que el tiempo de vida ES
    # la ventana de exposición. 15 minutos es el equilibrio habitual entre eso
    # y no renovar constantemente.
    access_token_minutos: int = Field(15, ge=1, le=1440)
    # El refresco sí es revocable (está en base de datos), por eso puede durar.
    refresh_token_dias: int = Field(14, ge=1, le=365)

    # ── Sesiones (CRM-00.05.01.08) ────────────────────────────────────────
    # Sesiones simultáneas por usuario. 0 = sin límite. Ponerlo a 1 es lo que
    # exigen algunos clientes regulados.
    sesiones_max_por_usuario: int = Field(0, ge=0, le=1000)
    # Caducidad por inactividad, además de la absoluta del refresco.
    sesion_inactividad_minutos: int = Field(480, ge=5, le=10_080)

    # ── Intentos y bloqueo ────────────────────────────────────────────────
    login_max_intentos: int = Field(5, ge=1, le=100)
    login_bloqueo_minutos: int = Field(15, ge=1, le=1440)

    # ── MFA (CRM-00.05.01.06) ─────────────────────────────────────────────
    mfa_enabled: bool = True
    # Exigir MFA a todo el mundo. Lo normal es exigirla por rol (se configura
    # por tenant); esto es el interruptor global para instalaciones que la
    # quieren obligatoria sin excepciones.
    mfa_obligatoria: bool = False
    # Ventana de códigos TOTP aceptados hacia atrás y adelante, para absorber
    # relojes desajustados. Cada paso son 30 s; 1 = ±30 s.
    totp_ventana_pasos: int = Field(1, ge=0, le=10)

    # ── Federación (CRM-00.05.01.01..05) ──────────────────────────────────
    oidc_enabled: bool = False
    saml_enabled: bool = False
    scim_enabled: bool = False
    # Crear el usuario la primera vez que entra por el proveedor de identidad.
    # Cómodo y estándar, pero significa que quien controle el IdP crea usuarios
    # aquí: por eso es configurable y no un hecho.
    jit_provisioning: bool = True

    # ── Credenciales de máquina (CRM-00.05.01.07) ─────────────────────────
    # Caducidad por defecto de una clave de API nueva. 0 = sin caducidad, que se
    # desaconseja y por eso no es el default.
    api_key_caducidad_dias: int = Field(365, ge=0, le=3650)
    # Longitud en bytes del secreto generado (se muestra en base64url una sola
    # vez). 32 bytes = 256 bits.
    api_key_bytes: int = Field(32, ge=16, le=128)

    # ── Suplantación (CRM-00.05.02.10) ────────────────────────────────────
    # El soporte puede entrar como un usuario del tenant, pero: con motivo
    # escrito, con caducidad corta y dejando rastro en la auditoría. Sin las
    # tres cosas, es un agujero con buena intención.
    suplantacion_enabled: bool = True
    suplantacion_max_minutos: int = Field(60, ge=5, le=1440)
    suplantacion_exige_motivo: bool = True

    # ── SSO por proveedor externo (CRM-00.05.01.01, .02) ──────────────────
    # Cuánto se cachean el documento de descubrimiento y las claves de un
    # proveedor. Cinco minutos: lo bastante para no consultar al IdP en cada
    # inicio de sesión, y lo bastante poco para que una rotación de claves se
    # recoja sola sin tocar nada.
    oidc_cache_ttl_s: int = Field(300, ge=10, le=86_400)
    # Margen de reloj admitido al validar la vigencia de un token. Los relojes
    # del IdP y del servidor no van sincronizados al milisegundo, y sin margen
    # un token recién emitido puede parecer futuro.
    sso_margen_reloj_s: int = Field(60, ge=0, le=600)
    # Cuánto vive un inicio de sesión a medias —el estado entre que se manda al
    # usuario al IdP y vuelve—. Cinco minutos basta para escribir una
    # contraseña y pasar el segundo factor; más deja la ventana abierta.
    sso_estado_ttl_s: int = Field(300, ge=60, le=3_600)
