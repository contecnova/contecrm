"""Identidad: tokens, sesiones, MFA y credenciales de máquina."""

from __future__ import annotations

from typing import Literal

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

    # ── Segundo factor por SMS y correo (CRM-00.05.01.17) ─────────────────
    # Van apagados por defecto, y a propósito: el SMS es el factor más débil de
    # los que hay —se intercepta con un cambio de SIM que no depende de nadie de
    # aquí—, y encenderlo tiene que ser una decisión consciente de quien acepta
    # ese riesgo, no el estado de fábrica.
    otp_sms_enabled: bool = False
    otp_email_enabled: bool = False
    otp_digitos: int = Field(6, ge=4, le=10)
    # Vida del código. Corta a propósito: lo que hace seguro un OTP no es el
    # código, es que caduque pronto y solo valga una vez.
    otp_validez_segundos: int = Field(300, ge=30, le=1800)
    # Intentos antes de invalidar el desafío. Seis dígitos son un millón de
    # combinaciones: sin tope se agotan a fuerza bruta en minutos.
    otp_max_intentos: int = Field(5, ge=1, le=20)
    # Espera mínima entre reenvíos, para que «reenviar código» no sea un
    # amplificador de SMS a costa del cliente.
    otp_reenvio_segundos: int = Field(60, ge=10, le=900)

    # ── Reautenticación reforzada, step-up (CRM-00.05.01.18) ──────────────
    # Cuánto vale un segundo factor superado antes de volver a pedirlo para una
    # operación sensible. Con la sesión entera valdría ocho horas, y quien pasó
    # el factor por la mañana podría exportar la base a las seis de la tarde.
    stepup_validez_minutos: int = Field(15, ge=1, le=480)

    # ── Dispositivos de confianza (CRM-00.05.01.20) ───────────────────────
    # 0 = desactivado, que es el valor de fábrica: recordar un equipo es
    # renunciar al segundo factor en ese equipo, y eso lo decide el cliente.
    dispositivo_confianza_dias: int = Field(0, ge=0, le=365)

    # ── Federación (CRM-00.05.01.01..05) ──────────────────────────────────
    oidc_enabled: bool = False
    saml_enabled: bool = False
    scim_enabled: bool = False
    # Crear el usuario la primera vez que entra por el proveedor de identidad.
    # Cómodo y estándar, pero significa que quien controle el IdP crea usuarios
    # aquí: por eso es configurable y no un hecho.
    jit_provisioning: bool = True
    # Forzar la entrada por el IdP (CRM-00.05.01.13). Se configura por tenant;
    # esto es el interruptor global de la instalación.
    sso_forzado: bool = False
    # Aceptar el segundo factor que ya ha exigido el IdP (CRM-00.05.01.24), si
    # el proveedor declara cuáles valen. Apagado, se pide aquí igualmente.
    delegar_mfa_al_idp: bool = True
    # Aviso previo a que caduque un certificado de firma del IdP
    # (CRM-00.05.01.15). Treinta días es el plazo en el que todavía se puede
    # pedir el certificado nuevo al departamento que lo custodia sin prisa.
    idp_aviso_caducidad_dias: int = Field(30, ge=1, le=365)

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
    # `SUPLANTACION_EXIGE_MOTIVO` estuvo aquí y SE QUITA (06-10-2026). El motivo
    # se exige **siempre** en `servicio.suplantar`, por la razón escrita arriba:
    # sin motivo no hay forma de revisar después si el acceso estaba
    # justificado. Es decir, el único valor honesto del interruptor era `true`.
    #
    # Y no lo leía nadie, así que ponerlo a `false` no quitaba nada: quien lo
    # pusiera creería haber relajado una comprobación que seguía ahí. Un ajuste
    # que miente en los dos sentidos —no enciende y no apaga— no se arregla
    # enchufándolo: enchufarlo habría sido ofrecer apagar una garantía de
    # auditoría. Se quita, que es lo que dice la verdad.
    #
    # El interruptor de verdad es `suplantacion_enabled`, por tenant, que sí se
    # lee: apaga la suplantación entera en vez de vaciarla por dentro.

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

    # ── Sesión de navegador (CRM-07.04.02.03) ─────────────────────────────
    # El token de acceso viaja en cookie cuando quien llama es un navegador. Es
    # la única forma de que un XSS no se lleve la sesión: lo que está en
    # `localStorage` lo lee cualquier script inyectado, y una cookie `HttpOnly`
    # no.
    #
    # Nombre configurable porque dos despliegues de la casa en el mismo dominio
    # se pisarían la cookie, y el síntoma —entrar en uno te saca del otro— es de
    # los que tardan en atribuirse.
    sesion_cookie_nombre: str = "contecrm_sesion"
    # `secure` en producción SIEMPRE: una cookie sin él viaja en claro si
    # alguien fuerza http, y con ella va la sesión entera.
    #
    # Sin decidir (`None`) lo resuelve el entorno: apagado en desarrollo,
    # encendido en el resto. Estaba fijo a `True`, y en local sobre http eso
    # hace que **Safari descarte la cookie y no se pueda entrar**: el acceso
    # contesta 200, la sesión no se guarda y la aplicación devuelve a la
    # pantalla de acceso sin decir por qué. Chrome la acepta en `localhost` y
    # Safari no, así que el fallo dependía del navegador, que es la peor forma
    # de tenerlo.
    sesion_cookie_secure_bruto: bool | None = Field(
        None, alias="sesion_cookie_secure", description="Sin poner: apagado solo en desarrollo"
    )
    # `lax` y no `strict`: con `strict` la vuelta del proveedor de identidad
    # —que es una navegación desde otro dominio— llega sin cookie y el SSO no
    # completa nunca. `lax` sigue bloqueando el envío en peticiones cruzadas de
    # escritura, que es de lo que protege.
    sesion_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    # ── Cuenta de arranque (la de quien opera la plataforma) ──────────────
    # Sin esto, una instalación recién levantada no tiene a nadie que pueda
    # abrir la consola de plataforma —dar de alta empresas, ver su consumo,
    # suspender una—: `es_plataforma` existía en el modelo, lo exigían ciento
    # sesenta y una operaciones, y no había ninguna forma de ponerlo. El
    # producto arrancaba sin dueño.
    #
    # Manda el fichero y se aplica **en cada arranque**, contraseña incluida:
    # una cuenta de esta potencia no puede depender de que alguien recuerde
    # haberla creado, y si se cambia en el `.env` es porque se quiere cambiar.
    superadmin_email: str = ""
    superadmin_password: SecretStr = SecretStr("")
    # El tenant al que pertenece. Entrar exige uno —no hay sesión sin empresa—,
    # así que el operador tiene el suyo propio y no se cuela en el de un
    # cliente, donde vería sus datos sin querer.
    superadmin_tenant: str = "plataforma"
    superadmin_nombre: str = "Operación de la plataforma"

    # ── Passkeys (WebAuthn, CRM-00.05.01.23) ─────────────────────────────
    #
    # Una passkey se ata a un **dominio** y el navegador no la entrega a otro:
    # eso es lo que la hace resistente al phishing, y también lo que obliga a
    # declararlo bien. Los dos van vacíos a propósito: se derivan de
    # `public_base_url` y de `cors_origins`, que ya describen dónde vive esto.
    # Declararlos otra vez sería una tercera verdad que se separa de las dos.
    #
    # Se rellenan solo cuando el CRM se sirve desde un dominio distinto del de
    # su API —una instalación con el front en `crm.cliente.com` y la API en
    # `api.cliente.com`— porque ahí la regla del navegador es el dominio padre
    # y hay que decirlo.
    passkey_rp_id: str = ""
    passkey_rp_nombre: str = ""
    # Orígenes exactos desde los que se acepta una passkey, separados por comas.
    # Vacío = los de CORS, que es de donde llega el navegador.
    passkey_origenes: str = ""
