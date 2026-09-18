"""SAML 2.0 como proveedor de servicio (CRM-00.05.01.02).

**Dependencia opcional, y a propósito.**

Portado en su postura de `contecweb/app/services/saml.py`, y lo que se conserva
sobre todo es lo que ese módulo decide **no** hacer: **no se valida la firma XML
a mano**. Comprobar bien una firma XML —canonicalización, referencias,
transformaciones, envoltura— es un campo de minas conocido (*XML signature
wrapping*), y una implementación propia que funciona con las aserciones de
prueba es exactamente por donde se cuela una aserción falsificada. Si la
librería no está, aquí no hay SAML.

La librería es `python3-saml`, que necesita `libxmlsec1` compilada en el
sistema. Ponerla en `requirements.txt` obligaría a compilar xmlsec en **todas**
las instalaciones, incluidas las que usan OIDC o no usan SSO. Así que se instala
donde hace falta, y sin ella estos endpoints responden 503 diciendo exactamente
qué falta.

Lo que sigue después de validar la aserción —quién es, si existe, con qué
roles— es el tramo común de `sso.py`, el mismo que usa OIDC. Duplicarlo haría
que la política de provisión acabara siendo distinta según por dónde entre cada
uno.
"""

from __future__ import annotations

from typing import Any

from crmcore.errors import ErrorValidacion, NoAutenticado, NoDisponible
from crmcore.logging import get_logger

logger = get_logger(__name__)

PISTA_INSTALACION = (
    "SAML necesita la librería opcional `python3-saml`, que a su vez necesita "
    "`libxmlsec1` en el sistema. En Debian o Ubuntu: `apt-get install "
    "libxmlsec1-dev pkg-config` y después `pip install python3-saml`."
)


def disponible() -> bool:
    """Si la librería está instalada en este despliegue."""
    try:
        from onelogin.saml2.auth import OneLogin_Saml2_Auth  # noqa: F401
    except ImportError:
        return False
    return True


def exigir_disponible() -> None:
    if not disponible():
        raise NoDisponible(
            "Este despliegue no tiene SAML instalado",
            error_code="saml.no_instalado",
            detalle={"como_instalarlo": PISTA_INSTALACION},
        )


def problemas_de_configuracion(config: dict[str, Any]) -> list[str]:
    """Qué le falta a la configuración de un proveedor SAML.

    Se devuelven **todos** los problemas, no el primero: a quien está
    configurando un IdP le sirve mucho más ver las cuatro cosas que faltan de
    una vez que descubrirlas de una en una, con un intento de inicio de sesión
    entre cada dos.
    """
    problemas: list[str] = []
    for clave, explicacion in (
        ("idp_entity_id", "el identificador de entidad del IdP"),
        ("idp_sso_url", "la URL a la que se manda al usuario"),
        ("idp_x509_cert", "el certificado con el que el IdP firma"),
        ("sp_entity_id", "nuestro propio identificador de entidad"),
        ("sp_acs_url", "la URL a la que el IdP nos devuelve la aserción"),
    ):
        if not str(config.get(clave) or "").strip():
            problemas.append(f"Falta «{clave}»: {explicacion}")

    cert = str(config.get("idp_x509_cert") or "")
    if cert and "BEGIN CERTIFICATE" not in cert and len(cert) < 100:
        problemas.append(
            "«idp_x509_cert» no parece un certificado: pega el PEM completo, no la huella"
        )
    return problemas


def _ajustes(config: dict[str, Any]) -> dict[str, Any]:
    """Traduce la configuración del proveedor al formato de `python3-saml`."""
    return {
        "strict": True,
        "debug": False,
        "sp": {
            "entityId": config["sp_entity_id"],
            "assertionConsumerService": {
                "url": config["sp_acs_url"],
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "x509cert": config.get("sp_x509_cert", ""),
            "privateKey": config.get("sp_private_key", ""),
        },
        "idp": {
            "entityId": config["idp_entity_id"],
            "singleSignOnService": {
                "url": config["idp_sso_url"],
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "singleLogoutService": {
                "url": config.get("idp_slo_url", ""),
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": config["idp_x509_cert"],
        },
        "security": {
            # Se exige aserción firmada. Sin esto, `python3-saml` aceptaría una
            # respuesta sin firma si el IdP no la manda — que es el agujero de
            # libro.
            "wantAssertionsSigned": True,
            "wantMessagesSigned": bool(config.get("exigir_mensaje_firmado", False)),
            "requestedAuthnContext": False,
            "rejectUnsolicitedResponsesWithInResponseTo": True,
        },
    }


def _peticion(datos: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """La forma de petición que espera `python3-saml`.

    El host y el esquema salen de **nuestra** URL configurada (`sp_acs_url`) y
    no de las cabeceras de la petición: `Host` y `X-Forwarded-Host` las pone
    quien llama, y usarlas aquí dejaría que una cabecera falsificada cambiara la
    URL contra la que se valida el destinatario de la aserción.
    """
    from urllib.parse import urlparse

    acs = urlparse(str(config["sp_acs_url"]))
    return {
        "https": "on" if acs.scheme == "https" else "off",
        "http_host": acs.netloc,
        "server_port": str(acs.port or (443 if acs.scheme == "https" else 80)),
        "script_name": acs.path,
        "get_data": {},
        "post_data": datos,
    }


def url_de_inicio(config: dict[str, Any], *, volver_a: str | None = None) -> str:
    """URL a la que se manda al usuario para que se autentique en su IdP."""
    exigir_disponible()
    from onelogin.saml2.auth import OneLogin_Saml2_Auth

    problemas = problemas_de_configuracion(config)
    if problemas:
        raise ErrorValidacion(
            "La configuración SAML de este proveedor está incompleta",
            error_code="saml.configuracion_incompleta",
            detalle={"problemas": problemas},
        )
    auth = OneLogin_Saml2_Auth(_peticion({}, config), _ajustes(config))
    return str(auth.login(return_to=volver_a))


def metadatos(config: dict[str, Any]) -> str:
    """El XML de metadatos de nuestro lado, para dárselo al administrador del IdP."""
    exigir_disponible()
    from onelogin.saml2.settings import OneLogin_Saml2_Settings

    ajustes = OneLogin_Saml2_Settings(_ajustes(config), sp_validation_only=True)
    xml = ajustes.get_sp_metadata()
    errores = ajustes.validate_metadata(xml)
    if errores:
        raise ErrorValidacion(
            "Los metadatos generados no son válidos",
            error_code="saml.metadatos_invalidos",
            detalle={"errores": [str(e) for e in errores]},
        )
    return xml.decode("utf-8") if isinstance(xml, bytes) else str(xml)


def procesar_respuesta(
    config: dict[str, Any], datos_post: dict[str, Any]
) -> tuple[str, str, list[str]]:
    """Valida la aserción y devuelve (correo, nombre, grupos).

    La validación —firma, destinatario, vigencia, condiciones— la hace la
    librería. Aquí solo se traduce el resultado y se comprueba que trae lo
    mínimo para identificar a alguien.
    """
    exigir_disponible()
    from onelogin.saml2.auth import OneLogin_Saml2_Auth

    auth = OneLogin_Saml2_Auth(_peticion(datos_post, config), _ajustes(config))
    auth.process_response()

    errores = auth.get_errors()
    if errores:
        # El motivo detallado va al log, no a la respuesta: dice cosas sobre
        # nuestra configuración y sobre la del IdP que no tiene por qué ver
        # quien está intentando entrar.
        logger.warning(
            "saml.respuesta_invalida",
            errores=errores,
            motivo=str(auth.get_last_error_reason() or "")[:300],
        )
        raise NoAutenticado(
            "La respuesta del proveedor de identidad no es válida",
            error_code="saml.respuesta_invalida",
        )
    if not auth.is_authenticated():
        raise NoAutenticado(
            "El proveedor de identidad no ha autenticado al usuario",
            error_code="saml.no_autenticado",
        )

    atributos = auth.get_attributes() or {}
    correo = _primero(
        atributos,
        config.get("attr_email"),
        ("email", "mail", "emailAddress", "urn:oid:0.9.2342.19200300.100.1.3"),
    ) or (auth.get_nameid() or "")
    nombre = (
        _primero(
            atributos,
            config.get("attr_nombre"),
            ("displayName", "name", "cn", "urn:oid:2.16.840.1.113730.3.1.241"),
        )
        or ""
    )
    grupos = _lista(atributos, config.get("attr_grupos"), ("groups", "memberOf", "Role"))

    if not correo or "@" not in correo:
        raise ErrorValidacion(
            "La aserción no trae un correo con el que identificar a la persona. "
            "Configura qué atributo lo lleva en «attr_email».",
            error_code="saml.sin_email",
            detalle={"atributos_recibidos": sorted(atributos)[:30]},
        )
    return correo.strip().lower(), nombre.strip(), grupos


def _primero(atributos: dict[str, Any], configurado: Any, candidatos: tuple[str, ...]) -> str:
    """Primer valor del atributo configurado o de los nombres habituales.

    Se prueban varios nombres porque no hay uno solo: cada IdP manda el correo
    con el suyo, y varios usan los OID de LDAP en vez de un nombre legible.
    """
    nombres = [str(configurado)] if configurado else []
    nombres.extend(candidatos)
    for nombre in nombres:
        valores = atributos.get(nombre)
        if isinstance(valores, (list, tuple)) and valores:
            return str(valores[0])
        if isinstance(valores, str) and valores:
            return valores
    return ""


def _lista(atributos: dict[str, Any], configurado: Any, candidatos: tuple[str, ...]) -> list[str]:
    nombres = [str(configurado)] if configurado else []
    nombres.extend(candidatos)
    salida: list[str] = []
    for nombre in nombres:
        valores = atributos.get(nombre)
        if isinstance(valores, (list, tuple)):
            salida.extend(str(v) for v in valores if v)
        elif isinstance(valores, str) and valores:
            salida.append(valores)
    return list(dict.fromkeys(salida))
