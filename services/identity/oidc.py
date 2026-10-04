"""Cliente OIDC con flujo de código y PKCE (CRM-00.05.01.01).

**Portado de `contecmind/app/core/oidc.py`**, que ya pasó por varias auditorías,
y adaptado a lo que aquí cambia todo: el proveedor es **del tenant**, no del
producto. Allí la configuración era global; aquí cada tenant tiene el suyo —o
varios— y eso mueve tres cosas de sitio:

  * Las cachés de descubrimiento y de claves son **por proveedor**, no por
    proceso. Con una sola caché global, el segundo tenant se autenticaría contra
    las claves del primero.
  * La URL del proveedor la escribe el cliente, así que pasa por el guard de
    SSRF (`crmcore.red`): sin él, configurar un IdP en `169.254.169.254` sería
    una forma cómoda de leer los metadatos de la nube.
  * No hay «el» `client_id`: la audiencia que se valida es la del proveedor que
    inició ese flujo concreto.

Lo que **no** cambia, porque cambiarlo sería reintroducir agujeros conocidos:

  * Una clave que no case con el `kid` del token **no se sustituye por la
    primera** de la lista. Hacerlo enmascara una rotación de claves o una
    configuración cruzada, y hace que un token firmado con otra clave pase.
  * El algoritmo se valida contra una **lista blanca asimétrica**, cruzada con
    lo que el propio proveedor anuncia. Sin esto caben `alg: none` y la
    confusión de algoritmos: firmar con HS256 usando la clave pública —que es
    pública— como secreto.
  * El emisor que se valida sale del **documento de descubrimiento**, no de la
    URL configurada.
  * Se exigen `exp`, `iat`, `iss`, `aud` y `sub`. `sub` es el identificador
    estable del usuario: un token sin él no identifica a nadie.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from threading import RLock
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import jwt
from crmcore.errors import ErrorDependencia, ErrorValidacion
from crmcore.logging import get_logger
from jwt.exceptions import InvalidTokenError

logger = get_logger(__name__)

# Solo asimétricos. Un algoritmo simétrico aquí permitiría firmar el token con
# la clave pública del proveedor —que es pública— haciéndola pasar por secreto
# compartido. Es la confusión de algoritmos, y es trivial de explotar.
ALGORITMOS = frozenset(
    {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256", "PS384", "PS512", "EdDSA"}
)

# Caché por proveedor: `{proveedor_id: (momento, documento)}`. Por proveedor y no
# global porque cada tenant tiene el suyo; con una caché global, el segundo
# tenant se validaría contra las claves del primero.
_descubrimiento: dict[str, tuple[float, dict[str, Any]]] = {}
_claves: dict[str, tuple[float, dict[str, Any]]] = {}
# RLock y no Lock: `_jwks()` toma el cerrojo y dentro llama a `_descubrir()`,
# que vuelve a tomarlo. Con un cerrojo normal, eso es un interbloqueo.
_cerrojo = RLock()


@dataclass(frozen=True, slots=True)
class Proveedor:
    """Configuración efectiva de un proveedor OIDC de un tenant."""

    id: str
    tenant_id: UUID
    nombre: str
    issuer_url: str
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: tuple[str, ...] = ("openid", "email", "profile")
    exigir_email_verificado: bool = True
    jit: bool = True
    mapeo_roles: dict[str, Any] | None = None


def desde_modelo(fila: Any) -> Proveedor:
    """Convierte una fila de `proveedores_identidad` en configuración usable.

    Los secretos se descifran aquí y no se guardan en la caché de
    descubrimiento: esa caché vive en memoria durante minutos y se vuelca en un
    volcado de proceso.
    """
    from crmcore.security.cifrado import descifrar

    config = dict(fila.config or {})
    # `descifrar` es idempotente: devuelve tal cual lo que no lleva la marca,
    # así que vale igual para un secreto ya cifrado y para uno recién puesto en
    # claro durante una migración.
    secreto = descifrar(str(config.get("client_secret") or ""), proposito="idp")

    faltan = [c for c in ("issuer_url", "client_id", "redirect_uri") if not config.get(c)]
    if faltan:
        raise ErrorValidacion(
            f"Al proveedor «{fila.nombre}» le falta configuración: {', '.join(faltan)}",
            error_code="oidc.configuracion_incompleta",
            detalle={"faltan": faltan},
        )

    return Proveedor(
        id=str(fila.id),
        tenant_id=fila.tenant_id,
        nombre=fila.nombre,
        issuer_url=str(config["issuer_url"]).rstrip("/"),
        client_id=str(config["client_id"]),
        client_secret=str(secreto or ""),
        redirect_uri=str(config["redirect_uri"]),
        scopes=tuple(config.get("scopes") or ("openid", "email", "profile")),
        exigir_email_verificado=bool(config.get("exigir_email_verificado", True)),
        jit=bool(fila.jit_provisioning),
        mapeo_roles=dict(fila.mapeo_roles or {}),
    )


# ── Descubrimiento y claves ───────────────────────────────────────────────


def _ttl() -> float:
    from crmcore.runtime import settings as rt

    return float(rt.efectivo("oidc_cache_ttl_s") or 300)


def _descubrir(proveedor: Proveedor) -> dict[str, Any]:
    """Documento `/.well-known/openid-configuration`, cacheado por proveedor.

    La comprobación del TTL, la petición y la escritura van dentro de la **misma**
    sección crítica. Soltar el cerrojo durante la petición haría que dos
    peticiones simultáneas en frío dispararan dos consultas al proveedor; pasa
    poco, pero pasa justo en el arranque, que es cuando llegan todas a la vez.
    """
    from crmcore.red import cliente_seguro, exigir

    with _cerrojo:
        guardado = _descubrimiento.get(proveedor.id)
        if guardado and (time.monotonic() - guardado[0]) < _ttl():
            return guardado[1]

        url = f"{proveedor.issuer_url}/.well-known/openid-configuration"
        exigir(url)
        try:
            with cliente_seguro(timeout=10.0) as cli:
                respuesta = cli.get(url)
                respuesta.raise_for_status()
                documento = respuesta.json()
        except Exception as exc:  # noqa: BLE001 — httpx lanza varias clases
            raise ErrorDependencia(
                f"No se ha podido leer la configuración del proveedor «{proveedor.nombre}»",
                error_code="oidc.descubrimiento_fallido",
                detalle={"url": url, "error": str(exc)[:200]},
            ) from exc

        if "issuer" not in documento:
            raise ErrorDependencia(
                "El proveedor no declara su emisor en el documento de descubrimiento",
                error_code="oidc.descubrimiento_sin_issuer",
                detalle={"url": url},
            )
        _descubrimiento[proveedor.id] = (time.monotonic(), documento)
        return documento


def _jwks(proveedor: Proveedor) -> dict[str, Any]:
    """Claves públicas del proveedor, cacheadas."""
    from crmcore.red import cliente_seguro, exigir

    with _cerrojo:
        guardado = _claves.get(proveedor.id)
        if guardado and (time.monotonic() - guardado[0]) < _ttl():
            return guardado[1]

        url = _descubrir(proveedor).get("jwks_uri")
        if not url:
            raise ErrorDependencia(
                "El proveedor no publica sus claves (falta `jwks_uri`)",
                error_code="oidc.sin_jwks",
            )
        exigir(str(url))
        try:
            with cliente_seguro(timeout=10.0) as cli:
                respuesta = cli.get(str(url))
                respuesta.raise_for_status()
                documento = respuesta.json()
        except Exception as exc:  # noqa: BLE001
            raise ErrorDependencia(
                "No se han podido leer las claves del proveedor",
                error_code="oidc.jwks_fallido",
                detalle={"error": str(exc)[:200]},
            ) from exc
        _claves[proveedor.id] = (time.monotonic(), documento)
        return documento


def invalidar_cache(proveedor_id: str | None = None) -> None:
    """Olvida lo cacheado de un proveedor, o de todos."""
    with _cerrojo:
        if proveedor_id:
            _descubrimiento.pop(proveedor_id, None)
            _claves.pop(proveedor_id, None)
        else:
            _descubrimiento.clear()
            _claves.clear()


# ── PKCE y URL de autorización ────────────────────────────────────────────


def _b64url(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).decode("ascii").rstrip("=")


@dataclass(frozen=True, slots=True)
class Autorizacion:
    url: str
    estado: str
    nonce: str
    verificador: str


def construir_autorizacion(proveedor: Proveedor, *, prompt: str | None = None) -> Autorizacion:
    """Prepara la URL a la que se manda al usuario, con PKCE.

    **PKCE siempre, incluso con secreto de cliente.** OAuth 2.1 lo exige para
    todos los clientes, no solo para los públicos: sin él, quien intercepte el
    código de autorización —en un log de proxy, en el historial del navegador,
    en un `Referer`— puede canjearlo. Con él, hace falta además el verificador,
    que nunca sale de este servidor.

    `estado` y `nonce` son cosas distintas y las dos hacen falta: el `estado`
    ata la respuesta a la petición que la inició (defensa de CSRF), y el `nonce`
    ata el token de identidad a ese mismo flujo (defensa de repetición).
    """
    documento = _descubrir(proveedor)
    endpoint = documento.get("authorization_endpoint")
    if not endpoint:
        raise ErrorDependencia(
            "El proveedor no declara su punto de autorización",
            error_code="oidc.sin_authorization_endpoint",
        )

    verificador = _b64url(secrets.token_bytes(32))
    reto = _b64url(hashlib.sha256(verificador.encode("ascii")).digest())
    estado = _b64url(secrets.token_bytes(24))
    nonce = _b64url(secrets.token_bytes(24))

    parametros = {
        "response_type": "code",
        "client_id": proveedor.client_id,
        "redirect_uri": proveedor.redirect_uri,
        "scope": " ".join(proveedor.scopes),
        "state": estado,
        "nonce": nonce,
        "code_challenge": reto,
        # `plain` no se ofrece: convierte PKCE en un adorno, porque el reto y el
        # verificador serían el mismo valor.
        "code_challenge_method": "S256",
    }
    if prompt:
        parametros["prompt"] = prompt

    return Autorizacion(
        url=f"{endpoint}?{urlencode(parametros)}",
        estado=estado,
        nonce=nonce,
        verificador=verificador,
    )


# ── Canje del código ──────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Tokens:
    access_token: str
    id_token: str
    refresh_token: str | None
    expira_en: int


def canjear(proveedor: Proveedor, *, codigo: str, verificador: str) -> Tokens:
    """Cambia el código de autorización por tokens."""
    from crmcore.red import cliente_seguro, exigir

    endpoint = _descubrir(proveedor).get("token_endpoint")
    if not endpoint:
        raise ErrorDependencia(
            "El proveedor no declara su punto de tokens", error_code="oidc.sin_token_endpoint"
        )
    exigir(str(endpoint))

    datos = {
        "grant_type": "authorization_code",
        "code": codigo,
        "redirect_uri": proveedor.redirect_uri,
        "client_id": proveedor.client_id,
        "code_verifier": verificador,
    }
    if proveedor.client_secret:
        datos["client_secret"] = proveedor.client_secret

    try:
        with cliente_seguro(timeout=15.0) as cli:
            respuesta = cli.post(str(endpoint), data=datos)
    except Exception as exc:  # noqa: BLE001
        raise ErrorDependencia(
            "No se ha podido contactar con el proveedor de identidad",
            error_code="oidc.token_inalcanzable",
            detalle={"error": str(exc)[:200]},
        ) from exc

    if respuesta.status_code >= 400:
        # Sin el cuerpo entero: puede traer el código y trazas del proveedor.
        logger.warning(
            "oidc.canje_rechazado",
            proveedor=proveedor.nombre,
            codigo_http=respuesta.status_code,
        )
        raise ErrorValidacion(
            "El proveedor de identidad ha rechazado el inicio de sesión",
            error_code="oidc.canje_rechazado",
        )

    cuerpo = respuesta.json()
    if not cuerpo.get("id_token"):
        raise ErrorValidacion(
            "El proveedor no ha devuelto token de identidad: revisa que el ámbito "
            "`openid` esté pedido",
            error_code="oidc.sin_id_token",
        )
    return Tokens(
        access_token=cuerpo.get("access_token", ""),
        id_token=cuerpo["id_token"],
        refresh_token=cuerpo.get("refresh_token"),
        expira_en=int(cuerpo.get("expires_in", 0) or 0),
    )


# ── Verificación del token de identidad ───────────────────────────────────


def _clave_que_encaja(claves: list[dict[str, Any]], kid: str | None) -> dict[str, Any] | None:
    """La clave del `kid`, o la única si el token no trae `kid`.

    **No se cae a la primera cuando el token SÍ trae `kid` y no encaja
    ninguna.** Hacerlo enmascara una rotación de claves o una configuración
    cruzada entre tenants, y deja pasar un token firmado con otra clave.
    """
    if kid:
        return next((c for c in claves if c.get("kid") == kid), None)
    return claves[0] if claves else None


def _resolver_clave(proveedor: Proveedor, kid: str | None) -> dict[str, Any]:
    """Busca la clave y, si no está, refresca el JWKS una sola vez."""
    claves = _jwks(proveedor).get("keys") or []
    clave = _clave_que_encaja(claves, kid)
    if clave is not None:
        return clave

    invalidar_cache(proveedor.id)
    claves = _jwks(proveedor).get("keys") or []
    if not claves:
        # Se distingue del caso siguiente a propósito: aquí el problema es el
        # proveedor —rotación simultánea, punto de claves caído devolviendo
        # 200— y no el token. Con un mensaje genérico, el operador busca donde
        # no es.
        raise ErrorDependencia(
            "El proveedor no devuelve ninguna clave: puede estar rotándolas ahora mismo",
            error_code="oidc.jwks_vacio",
        )
    clave = _clave_que_encaja(claves, kid)
    if clave is None:
        raise ErrorValidacion(
            "Ninguna clave del proveedor sirve para verificar este token",
            error_code="oidc.sin_clave",
        )
    return clave


def _algoritmo(proveedor: Proveedor, cabecera: dict[str, Any]) -> str:
    """Valida el algoritmo contra la lista blanca cruzada con lo que anuncia el IdP."""
    alg = cabecera.get("alg", "RS256")
    anunciados = set(_descubrir(proveedor).get("id_token_signing_alg_values_supported") or [])
    permitidos = (ALGORITMOS & anunciados) if anunciados else ALGORITMOS
    if alg not in permitidos:
        raise ErrorValidacion(
            f"El token viene firmado con «{alg}», que no está permitido",
            error_code="oidc.algoritmo_no_permitido",
            detalle={"permitidos": sorted(permitidos)},
        )
    return str(alg)


def verificar_id_token(
    proveedor: Proveedor, id_token: str, *, nonce: str | None = None
) -> dict[str, Any]:
    """Comprueba firma, emisor, audiencia, vigencia y nonce. Devuelve los claims."""
    from crmcore.config import get_settings

    try:
        cabecera = jwt.get_unverified_header(id_token)
    except InvalidTokenError as exc:
        raise ErrorValidacion(
            f"La cabecera del token no es válida: {exc}", error_code="oidc.cabecera_invalida"
        ) from exc

    clave = _resolver_clave(proveedor, cabecera.get("kid"))
    alg = _algoritmo(proveedor, cabecera)
    # El emisor sale del documento de descubrimiento y no de la URL configurada:
    # es el que el proveedor dice ser, que es contra el que hay que comparar.
    emisor = _descubrir(proveedor)["issuer"]

    try:
        algoritmo = jwt.get_algorithm_by_name(alg)
        material = algoritmo.from_jwk(clave)
    except Exception as exc:  # noqa: BLE001 — PyJWT lanza varias clases
        raise ErrorValidacion(
            f"La clave del proveedor no sirve para {alg}: {exc}",
            error_code="oidc.clave_invalida",
        ) from exc

    try:
        claims = jwt.decode(
            id_token,
            material,
            algorithms=[alg],
            audience=proveedor.client_id,
            issuer=emisor,
            # `sub` obligatorio: es el identificador estable del usuario en
            # OIDC, y un token sin él no identifica a nadie. Exigirlo aquí evita
            # que cualquier código de más abajo confíe en uno que no lo trae.
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            # MARGEN DE RELOJ. Sin él, un token recién emitido por un IdP cuyo
            # reloj va unos segundos adelantado parece del futuro y se rechaza:
            # el usuario ve «no válido», vuelve a intentarlo, y le vuelve a
            # pasar. `SSO_MARGEN_RELOJ_S` existía en los ajustes, documentado
            # exactamente para esto, y **no lo leía nadie**.
            leeway=int(get_settings().sso_margen_reloj_s),
        )
    except InvalidTokenError as exc:
        raise ErrorValidacion(
            f"El token de identidad no es válido: {exc}", error_code="oidc.token_invalido"
        ) from exc

    if nonce is not None and claims.get("nonce") != nonce:
        raise ErrorValidacion(
            "El token no corresponde a este inicio de sesión",
            error_code="oidc.nonce_no_coincide",
        )
    if proveedor.exigir_email_verificado and claims.get("email_verified") is not True:
        raise ErrorValidacion(
            "El proveedor no da el correo por verificado. Si es un IdP interno que "
            "no publica ese dato, desactívalo en la configuración del proveedor.",
            error_code="oidc.email_sin_verificar",
        )
    return dict(claims)


def grupos_de(claims: dict[str, Any], userinfo: dict[str, Any] | None = None) -> list[str]:
    """Grupos del usuario, mirando los nombres de claim que usan los IdP reales.

    Se miran varios nombres porque no hay uno estándar: `groups` es lo habitual,
    pero hay proveedores que usan `roles` y otros que lo mandan en `/userinfo` y
    no en el token, para no hacerlo crecer.
    """
    salida: list[str] = []
    for fuente in (claims, userinfo or {}):
        for nombre in ("groups", "roles", "memberOf"):
            valor = fuente.get(nombre)
            if isinstance(valor, str):
                salida.extend(v.strip() for v in valor.split(",") if v.strip())
            elif isinstance(valor, (list, tuple)):
                salida.extend(str(v) for v in valor if v)
    return list(dict.fromkeys(salida))
