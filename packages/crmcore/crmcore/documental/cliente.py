"""Hablar con el gestor documental, sin bajarle la credencial al navegador.

Mismo patrón que el cliente de contecintelligence (RT-4) y por las mismas
razones, así que quien entienda uno entiende el otro:

**La credencial de aplicación no baja nunca al navegador.** Con ella se canjea,
en el servidor, un token corto por usuario. La credencial puede representar a
todos los tenants; si llegara al navegador sería la llave de todos.

**El estado se cachea y no se comprueba en cada `/health/ready`.** Una
comprobación de salud que hace una llamada de red a otro sistema convierte la
lentitud de ese sistema en la nuestra — y, si el orquestador la usa para
reiniciar, en un reinicio en cascada.

**Un gestor caído no impide arrancar**, salvo que se pida. El CRM operativo no
puede depender del corpus documental: sin gestor hay CRM y hay adjuntos, lo que
no hay es corpus.
"""

from __future__ import annotations

import time
from typing import Any

from crmcore.errors import NoDisponible
from crmcore.logging import get_logger

logger = get_logger(__name__)

_estado: dict[str, Any] = {
    "alcanzable": None,
    "comprobado_at": None,
    "latencia_ms": None,
    "error": None,
    "version": None,
}


def _config() -> Any:
    from crmcore.config import get_settings

    s = get_settings()
    if not s.dms_enabled:
        raise NoDisponible(
            "El corpus documental está desactivado en este despliegue "
            "(DMS_ENABLED=false). Los adjuntos de los registros siguen "
            "funcionando: son otra cosa",
            error_code="documental.desactivado",
        )
    if not s.dms_base_url:
        raise NoDisponible(
            "No hay gestor documental configurado: el corpus lo resuelve "
            "contecmind (RT-5), así que hay que levantarlo con la pila o dar la "
            "dirección de uno ya en marcha en DMS_BASE_URL",
            error_code="documental.sin_configurar",
        )
    return s


def estado() -> dict[str, Any]:
    """Lo último que se sabe, sin volver a preguntar."""
    from crmcore.config import get_settings

    s = get_settings()
    return {
        **_estado,
        "activo": s.dms_enabled,
        "url": s.dms_base_url or None,
        "obligatorio_para_arrancar": s.dms_exigir_al_arrancar,
        # Se dice qué sigue funcionando sin él. Sin esta línea, un `/health` que
        # dice «documental: no alcanzable» hace pensar que no se puede adjuntar
        # nada, y sí se puede.
        "sin_el": "los adjuntos de los registros funcionan igual; no hay corpus documental",
    }


def comprobar() -> dict[str, Any]:
    """Pregunta si está vivo y guarda el resultado.

    Se consulta su contrato publicado, que no exige autenticación: así una
    credencial mal puesta se distingue de un sistema caído, que son dos
    problemas con dos soluciones distintas.
    """
    from crmcore.red import cliente_seguro

    s = _config()
    url = s.dms_base_url.rstrip("/") + "/openapi.json"
    inicio = time.monotonic()
    try:
        with cliente_seguro(timeout=s.dms_timeout_s) as cli:
            respuesta = cli.get(url)
            respuesta.raise_for_status()
            contrato = respuesta.json()
    except Exception as exc:  # noqa: BLE001 — cualquier fallo aquí es «no alcanzable»
        _estado.update(
            alcanzable=False,
            comprobado_at=time.time(),
            latencia_ms=int((time.monotonic() - inicio) * 1000),
            error=str(exc)[:300],
            version=None,
        )
        logger.error("documental.gestor_no_alcanzable", url=s.dms_base_url, error=str(exc)[:200])
        return dict(_estado)

    _estado.update(
        alcanzable=True,
        comprobado_at=time.time(),
        latencia_ms=int((time.monotonic() - inicio) * 1000),
        error=None,
        version=str((contrato.get("info") or {}).get("version") or ""),
    )
    logger.info("documental.gestor_listo", url=s.dms_base_url, version=_estado["version"])
    return dict(_estado)


def comprobar_al_arrancar() -> None:
    """El fallo se dice al desplegar, no al abrir el primer documento."""
    from crmcore.config import get_settings

    s = get_settings()
    if not s.dms_enabled or not s.dms_comprobar_al_arrancar:
        return
    if not s.dms_base_url:
        mensaje = (
            "DMS_ENABLED está activo y falta DMS_BASE_URL: el corpus documental "
            "lo resuelve contecmind (RT-5)"
        )
        if s.dms_exigir_al_arrancar:
            raise RuntimeError(mensaje)
        logger.error("documental.sin_configurar", aviso=mensaje)
        return

    resultado = comprobar()
    if not resultado["alcanzable"] and s.dms_exigir_al_arrancar:
        raise RuntimeError(
            f"El gestor documental no responde en {s.dms_base_url}: "
            f"{resultado['error']}. Con DMS_EXIGIR_AL_ARRANCAR=false el servicio "
            f"arranca igual y el corpus queda degradado"
        )


class TokenUsuario:
    """Token corto, por usuario y por organización. No es la credencial."""

    __slots__ = ("token", "expira_en_s", "organizacion", "alcances")

    def __init__(
        self, token: str, expira_en_s: int, organizacion: str, alcances: tuple[str, ...]
    ) -> None:
        self.token = token
        self.expira_en_s = expira_en_s
        self.organizacion = organizacion
        self.alcances = alcances


def canjear_token(
    *, organizacion: str, sujeto: str, rol: str, alcances: list[str] | None = None
) -> TokenUsuario:
    """Cambia la credencial de aplicación por un token de usuario final.

    `organizacion` sale **de la correspondencia guardada**, nunca de lo que
    mande el cliente: el gestor solo acepta nombrar organizaciones mapeadas, y
    ese control se pierde en cuanto el nombre viaja desde el navegador. Es lo
    que hace que esto sea multitenant de verdad y no una confianza en que el de
    enfrente filtre bien.

    El `rol` se traduce de lo que la persona puede ver **aquí**: un corpus
    documental que enseña más que el CRM es una fuga con otro nombre.
    """
    from crmcore.errors import ErrorDependencia, ErrorValidacion
    from crmcore.red import cliente_seguro

    s = _config()
    if not s.dms_client_id or not s.dms_client_secret:
        raise NoDisponible(
            "Falta la credencial de aplicación del gestor documental "
            "(DMS_CLIENT_ID / DMS_CLIENT_SECRET)",
            error_code="documental.sin_credencial",
        )
    if not organizacion:
        raise ErrorValidacion(
            "Este tenant no tiene organización asignada en el gestor documental",
            error_code="documental.sin_organizacion",
        )

    cuerpo = {
        "tenant": organizacion,
        "subject": sujeto,
        "role": rol,
        "scopes": alcances or list(s.dms_scopes),
        "ttl": int(s.dms_token_ttl_s),
    }
    try:
        with cliente_seguro(timeout=s.dms_timeout_s) as cli:
            respuesta = cli.post(
                s.dms_base_url.rstrip("/") + "/api/v1/tokens/exchange",
                json=cuerpo,
                auth=(s.dms_client_id, s.dms_client_secret.get_secret_value()),
            )
    except Exception as exc:  # noqa: BLE001
        raise ErrorDependencia(
            "No se ha podido contactar con el gestor documental",
            error_code="documental.inalcanzable",
            detalle={"error": str(exc)[:200]},
        ) from exc

    if respuesta.status_code >= 400:
        # Sin el cuerpo: puede traer detalles de nuestra credencial.
        logger.warning(
            "documental.canje_rechazado",
            codigo_http=respuesta.status_code,
            organizacion=organizacion,
        )
        raise ErrorDependencia(
            "El gestor documental ha rechazado el canje del token",
            error_code="documental.canje_rechazado",
            detalle={"codigo_http": respuesta.status_code},
        )

    datos = respuesta.json()
    token = datos.get("token") or datos.get("access_token")
    if not token:
        raise ErrorDependencia(
            "El gestor documental no ha devuelto token",
            error_code="documental.canje_sin_token",
        )
    return TokenUsuario(
        token=str(token),
        expira_en_s=int(datos.get("expires_in") or s.dms_token_ttl_s),
        organizacion=organizacion,
        alcances=tuple(cuerpo["scopes"]),
    )


def rol_para(permisos: frozenset[str], es_admin: bool) -> str:
    """Traduce los permisos del CRM al rol que entiende el gestor.

    Se manda el rol que corresponde a lo que la persona puede ver aquí. Mandar
    siempre el más alto —o el de la credencial— haría que cualquiera con acceso
    al CRM viera el corpus entero del tenant, incluidos los contratos que no le
    tocan.
    """
    if es_admin or "documento:admin" in permisos or "*:*" in permisos:
        return "admin"
    if "documento:escribir" in permisos or "adjunto:subir" in permisos:
        return "writer"
    return "reader"


def buscar(texto: str, *, token_usuario: str, limite: int = 20) -> list[dict[str, Any]]:
    """Busca en el corpus **con la identidad del usuario**, no con la nuestra.

    Es lo que hace que la integración sea frontless y no un agujero: el gestor
    aplica sus propios permisos sobre ese token, así que un usuario del CRM ve
    en el buscador exactamente lo que vería entrando al gestor. Buscar con la
    credencial de aplicación le enseñaría el corpus entero del tenant.
    """
    from crmcore.red import cliente_seguro

    s = _config()
    with cliente_seguro(timeout=s.dms_timeout_s) as cli:
        respuesta = cli.get(
            s.dms_base_url.rstrip("/") + "/api/v1/documents/search",
            params={"q": texto, "limit": limite},
            headers={"Authorization": f"Bearer {token_usuario}"},
        )
    if respuesta.status_code == 401:
        raise NoDisponible(
            "El gestor documental ha rechazado la identidad del usuario",
            error_code="documental.identidad_rechazada",
        )
    respuesta.raise_for_status()
    cuerpo = respuesta.json()
    return list(cuerpo.get("items") or cuerpo.get("results") or [])


def ficha(documento_id: str, *, token_usuario: str) -> dict[str, Any]:
    """El estado real del documento: versión publicada, si está obsoleto.

    Se pregunta **al abrirlo** y no se cachea en el enlace. Un «aprobado»
    caducado en una pantalla del CRM es peor que no enseñar el estado: alguien
    firmará algo creyendo que la versión vigente es otra.
    """
    from crmcore.red import cliente_seguro

    s = _config()
    with cliente_seguro(timeout=s.dms_timeout_s) as cli:
        respuesta = cli.get(
            s.dms_base_url.rstrip("/") + f"/api/v1/documents/{documento_id}",
            headers={"Authorization": f"Bearer {token_usuario}"},
        )
    if respuesta.status_code == 404:
        from crmcore.errors import NoEncontrado

        # El documento se borró en el gestor y el enlace del CRM se quedó
        # colgando. Se dice tal cual: inventarse un estado sería peor.
        raise NoEncontrado(
            "El documento ya no existe en el gestor documental",
            error_code="documental.documento_no_existe",
        )
    respuesta.raise_for_status()
    return dict(respuesta.json())
