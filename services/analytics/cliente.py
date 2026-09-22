"""Cliente de contecintelligence: canje de token y estado (CRM-05.01.04.01, .11).

**El canje ocurre en el servidor, siempre.** La credencial de aplicación puede
representar a *todos* los tenants: si bajara al navegador sería la llave de
todos. Lo que baja es un token que nombra una organización, una persona y unos
alcances, y que dura minutos.

Los dos pasos —credencial → token corto— son de contecintelligence, no una
invención de aquí, y están así justamente por eso.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from crmcore.errors import ErrorDependencia, ErrorValidacion, NoDisponible
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Último estado conocido de la integración. En memoria del proceso a propósito:
# es información de *este* proceso sobre *su* conectividad, y compartirla entre
# réplicas diría que la integración va bien en una réplica que no puede llegar.
_estado: dict[str, Any] = {
    "alcanzable": None,
    "comprobado_at": None,
    "latencia_ms": None,
    "error": None,
    "version": None,
}


@dataclass(frozen=True, slots=True)
class TokenUsuario:
    token: str
    expira_en_s: int
    organizacion: str
    alcances: tuple[str, ...]

    def a_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "expira_en_s": self.expira_en_s,
            "organizacion": self.organizacion,
            "alcances": list(self.alcances),
        }


def _config() -> Any:
    from crmcore.config import get_settings

    s = get_settings()
    if not s.ci_enabled:
        raise NoDisponible(
            "La explotación del dato está desactivada en este despliegue " "(CI_ENABLED=false)",
            error_code="analytics.desactivada",
        )
    if not s.ci_base_url:
        raise NoDisponible(
            "No hay contecintelligence configurado: la explotación la resuelve él "
            "(RT-4), así que hay que levantarlo con la pila o dar la dirección de "
            "uno ya en marcha en CI_BASE_URL",
            error_code="analytics.sin_configurar",
        )
    return s


def estado() -> dict[str, Any]:
    """Lo último que se sabe de la integración: versión, latencia y último error
    (CRM-05.01.04.12).

    No comprueba en el momento: lo llama el `/health/ready`, y una comprobación
    de salud que hace una llamada de red a otro sistema convierte la lentitud de
    ese sistema en la lentitud de la nuestra — y, si el orquestador la usa para
    reiniciar, en un reinicio en cascada.
    """
    from crmcore.config import get_settings

    s = get_settings()
    return {
        **_estado,
        "activa": s.ci_enabled,
        "url": s.ci_base_url or None,
        "obligatoria_para_arrancar": s.ci_obligatorio_para_arrancar,
    }


def comprobar() -> dict[str, Any]:
    """Pregunta a contecintelligence si está vivo y guarda el resultado.

    Se ejecuta al arrancar y desde el endpoint de estado. Lo que se consulta es
    su contrato publicado, que no exige autenticación: así una credencial mal
    puesta se distingue de un sistema caído, que son dos problemas con dos
    soluciones distintas.
    """
    from crmcore.red import cliente_seguro

    s = _config()
    url = s.ci_base_url.rstrip("/") + "/openapi.json"
    inicio = time.monotonic()
    try:
        with cliente_seguro(timeout=s.ci_timeout_s) as cli:
            respuesta = cli.get(url)
            respuesta.raise_for_status()
            contrato = respuesta.json()
    except Exception as exc:  # noqa: BLE001 — cualquier fallo aquí es "no alcanzable"
        _estado.update(
            alcanzable=False,
            comprobado_at=time.time(),
            latencia_ms=int((time.monotonic() - inicio) * 1000),
            error=str(exc)[:300],
            version=None,
        )
        logger.error(
            "analytics.contecintelligence_no_alcanzable",
            url=s.ci_base_url,
            error=str(exc)[:200],
        )
        return dict(_estado)

    _estado.update(
        alcanzable=True,
        comprobado_at=time.time(),
        latencia_ms=int((time.monotonic() - inicio) * 1000),
        error=None,
        version=str((contrato.get("info") or {}).get("version") or ""),
    )
    logger.info(
        "analytics.contecintelligence_listo",
        url=s.ci_base_url,
        version=_estado["version"],
        latencia_ms=_estado["latencia_ms"],
    )
    return dict(_estado)


def comprobar_al_arrancar() -> None:
    """Comprobación de arranque (CRM-05.01.04.11). El fallo se dice aquí, no al abrir un informe.

    **No impide arrancar por defecto** (CRM-05.01.04.08): el CRM operativo no
    puede depender de la herramienta de consulta, y dejar el alta de un cliente
    atada a que el motor analítico esté vivo sería convertir una herramienta en
    una dependencia crítica. Se avisa bien alto y la explotación queda degradada.

    Quien prefiera lo contrario —una instalación donde el CRM sin informes no
    sirve— lo enciende con `CI_OBLIGATORIO_PARA_ARRANCAR`.
    """
    from crmcore.config import get_settings

    s = get_settings()
    if not s.ci_enabled or not s.ci_comprobar_al_arrancar:
        return
    if not s.ci_base_url:
        mensaje = (
            "CI_ENABLED está activo y no hay CI_BASE_URL: no habrá explotación "
            "del dato. Levanta contecintelligence con la pila o dale la dirección "
            "de uno en marcha."
        )
        if s.ci_obligatorio_para_arrancar:
            raise RuntimeError(mensaje)
        logger.error("analytics.sin_configurar", aviso=mensaje)
        return

    resultado = comprobar()
    if not resultado["alcanzable"]:
        mensaje = (
            f"contecintelligence no responde en {s.ci_base_url}: la explotación "
            "del dato no va a funcionar"
        )
        if s.ci_obligatorio_para_arrancar:
            raise RuntimeError(mensaje)
        logger.error("analytics.degradada", aviso=mensaje, error=resultado["error"])


def canjear_token(
    *, organizacion: str, sujeto: str, rol: str, alcances: list[str] | None = None
) -> TokenUsuario:
    """Cambia la credencial de aplicación por un token de usuario final.

    `organizacion` sale de la correspondencia guardada, nunca de lo que mande el
    cliente: contecintelligence solo acepta nombrar organizaciones mapeadas, y
    ese control se pierde si el nombre viaja desde el navegador.

    El `rol` decide permisos y enmascarado al otro lado, así que se manda el que
    corresponde a lo que la persona puede ver **aquí**: una explotación que ve
    más que la aplicación es una fuga con otro nombre.
    """
    from crmcore.red import cliente_seguro

    s = _config()
    if not s.ci_client_id or not s.ci_client_secret:
        raise NoDisponible(
            "Falta la credencial de aplicación de contecintelligence "
            "(CI_CLIENT_ID / CI_CLIENT_SECRET)",
            error_code="analytics.sin_credencial",
        )
    if not organizacion:
        raise ErrorValidacion(
            "Este tenant no tiene organización asignada en contecintelligence",
            error_code="analytics.sin_organizacion",
        )

    cuerpo = {
        "tenant": organizacion,
        "subject": sujeto,
        "role": rol,
        "scopes": alcances or list(s.ci_scopes),
        "ttl": int(s.ci_token_ttl_s),
    }
    url = s.ci_base_url.rstrip("/") + "/api/v1/tokens/exchange"
    try:
        with cliente_seguro(timeout=s.ci_timeout_s) as cli:
            respuesta = cli.post(
                url,
                json=cuerpo,
                auth=(s.ci_client_id, s.ci_client_secret.get_secret_value()),
            )
    except Exception as exc:  # noqa: BLE001
        raise ErrorDependencia(
            "No se ha podido contactar con contecintelligence",
            error_code="analytics.inalcanzable",
            detalle={"error": str(exc)[:200]},
        ) from exc

    if respuesta.status_code >= 400:
        # Sin el cuerpo: puede traer detalles de nuestra credencial.
        logger.warning(
            "analytics.canje_rechazado",
            codigo_http=respuesta.status_code,
            organizacion=organizacion,
        )
        raise ErrorDependencia(
            "contecintelligence ha rechazado el canje del token",
            error_code="analytics.canje_rechazado",
            detalle={"codigo_http": respuesta.status_code},
        )

    datos = respuesta.json()
    token = datos.get("token") or datos.get("access_token")
    if not token:
        raise ErrorDependencia(
            "contecintelligence no ha devuelto token",
            error_code="analytics.canje_sin_token",
        )
    return TokenUsuario(
        token=str(token),
        expira_en_s=int(datos.get("expires_in") or s.ci_token_ttl_s),
        organizacion=organizacion,
        alcances=tuple(cuerpo["scopes"]),
    )


def rol_para(permisos: frozenset[str], es_admin: bool) -> str:
    """Traduce los permisos del CRM al rol que entiende contecintelligence.

    La correspondencia es **a la baja**: ante la duda se manda el rol que menos
    ve. Equivocarse hacia arriba en una herramienta que responde con tablas
    enteras es enseñar de una vez lo que en el CRM se ve ficha a ficha.
    """
    if es_admin or "*:*" in permisos:
        return "admin"
    if any(p.startswith("report:") or p == "analytics:write" for p in permisos):
        return "analyst"
    return "viewer"
