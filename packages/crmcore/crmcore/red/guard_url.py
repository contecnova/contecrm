"""Guard de SSRF. El porqué está en `crmcore/red/__init__.py`."""

from __future__ import annotations

import concurrent.futures
import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import ParseResult, urlparse

import httpx

from crmcore.errors import ErrorValidacion
from crmcore.logging import get_logger

logger = get_logger(__name__)

ESQUEMAS = {"http", "https"}


@dataclass(frozen=True, slots=True)
class Veredicto:
    ok: bool
    motivo: str
    ips: list[str] = field(default_factory=list)


def _ip_bloqueada(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Rangos que nunca se buscan desde el servidor.

    `is_private` cubre RFC1918 y ULA. Los demás cubren loopback, link-local
    —que incluye **169.254.169.254**, el punto de metadatos de AWS, GCP y
    Azure, y el objetivo número uno de cualquier SSRF—, multicast, reservados
    y la dirección sin especificar.
    """
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolver(host: str, timeout_s: float) -> list[str]:
    """Todas las IP del host. Lista vacía si no resuelve o si tarda demasiado.

    `getaddrinfo` no admite tiempo límite, y un DNS que no contesta colgaría el
    hilo que atiende la petición. Se ejecuta en un hilo aparte con plazo: es feo,
    y es la única forma de acotarlo sin cambiar de resolutor.
    """
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ejecutor:
            futuro = ejecutor.submit(socket.getaddrinfo, host, None, proto=socket.IPPROTO_TCP)
            try:
                infos = futuro.result(timeout=timeout_s)
            except concurrent.futures.TimeoutError:
                return []
    except socket.gaierror:
        return []
    ips = [str(i[4][0]) for i in infos if i[4] and i[4][0]]
    return list(dict.fromkeys(ips))


def _rechazo_por_forma(partes: ParseResult) -> Veredicto | None:
    """Lo que se puede rechazar sin tocar el DNS.

    El **orden** es contrato: cuando una URL viola varias cosas, el motivo que
    se devuelve —y que acaba en el log y delante del operador— es el de la
    primera. Cambiar el orden cambia el diagnóstico.
    """
    if partes.scheme.lower() not in ESQUEMAS:
        return Veredicto(False, f"esquema no admitido: {partes.scheme!r}")
    if partes.username or partes.password:
        # `http://usuario:clave@host` es el truco clásico para confundir a un
        # parser: muchos leen el host antes de la arroba.
        return Veredicto(False, "la URL no puede llevar credenciales dentro")
    if not (partes.hostname or "").strip():
        return Veredicto(False, "la URL no tiene host")
    return None


def _permitidos() -> set[str]:
    """Hosts que el operador ha decidido admitir pese a ser internos.

    Existe porque hay instalaciones con un IdP o un ERP en la red interna, y
    negarlo obligaría a apagar el guard entero. Va por configuración y en caliente.
    """
    from urllib.parse import urlparse

    from crmcore.config import get_settings
    from crmcore.runtime import settings as rt

    crudo = rt.efectivo("url_guard_hosts_permitidos") or ""
    permitidos = {h.strip().lower() for h in str(crudo).split(",") if h.strip()}

    # Y los servicios de ESTE despliegue, que salen de `RUTAS_SERVICIOS`. No son
    # una URL de usuario: son las direcciones que el operador ha declarado, y son
    # exactamente lo que este guardia NO tiene que vigilar —vigila lo que alguien
    # escribe en un formulario de webhook—.
    #
    # Antes había que ponerlos a mano en `URL_GUARD_HOSTS_PERMITIDOS`, y olvidarlo
    # no fallaba al arrancar: fallaba la primera vez que un servicio llamaba a
    # otro, con «Esa URL no se puede consultar desde el servidor», que no dice
    # nada de lo que pasa. Se descubrió al registrar el CRM como fuente, porque
    # `analytics` tiene que pedirle a `identity` la clave de lectura.
    s = get_settings()
    for trozo in (s.rutas_servicios or "").replace("\n", " ").split(","):
        _, _, url = trozo.strip().partition("=")
        host = urlparse(url.strip()).hostname if url.strip() else None
        if host:
            permitidos.add(host.lower())
    # Y las direcciones de los servicios de la casa con los que este despliegue
    # habla, por lo mismo: las pone el operador en el `.env`, no un usuario en un
    # formulario. Tenerlas que repetir en `URL_GUARD_HOSTS_PERMITIDOS` era pedir
    # que alguien se acordara de escribir dos veces lo mismo.
    for atributo in ("ci_base_url", "ci_url_del_crm", "dms_base_url"):
        valor = str(getattr(s, atributo, "") or "")
        host = urlparse(valor).hostname if valor else None
        if host:
            permitidos.add(host.lower())
    return permitidos


def evaluar(url: str) -> Veredicto:
    """Veredicto sobre una URL, sin lanzar. Para telemetría y comprobaciones.

    La cadena es: URL no vacía → forma → IP literal → resolución DNS. Cada
    eslabón es una defensa distinta.
    """
    from crmcore.config import get_settings

    if not url or not isinstance(url, str):
        return Veredicto(False, "URL vacía")
    partes = urlparse(url.strip())

    rechazo = _rechazo_por_forma(partes)
    if rechazo is not None:
        return rechazo

    host = (partes.hostname or "").strip()
    if host.lower() in _permitidos():
        return Veredicto(True, "host permitido por configuración", [host])

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if _ip_bloqueada(literal):
            return Veredicto(False, f"la IP {host} está en un rango bloqueado", [host])
        return Veredicto(True, "correcta (IP literal)", [host])

    ips = _resolver(host, float(get_settings().url_guard_dns_timeout_s))
    if not ips:
        # Falla cerrado: un host que no resuelve no se busca. Dejarlo pasar
        # convertiría un DNS lento en una vía para saltarse el guard.
        return Veredicto(False, f"no se puede resolver el host {host!r}")

    malas: list[str] = []
    for texto in ips:
        try:
            if _ip_bloqueada(ipaddress.ip_address(texto)):
                malas.append(texto)
        except ValueError:
            # Una dirección que no parsea cuenta como mala: un `getaddrinfo` que
            # devuelva algo inesperado no debe pasar por bueno.
            malas.append(texto)
    if malas:
        return Veredicto(False, f"el host {host!r} resuelve a {malas}, que está bloqueado", ips)
    return Veredicto(True, "correcta", ips)


def exigir(url: str) -> None:
    """Lanza si la URL no se puede buscar desde el servidor."""
    veredicto = evaluar(url)
    if not veredicto.ok:
        logger.warning("url_guard.bloqueada", url=str(url)[:200], motivo=veredicto.motivo)
        raise ErrorValidacion(
            "Esa URL no se puede consultar desde el servidor",
            error_code="red.url_bloqueada",
            detalle={"motivo": veredicto.motivo},
        )


def _preparar(peticion: httpx.Request) -> None:
    """Revalida y **fija la IP** de cada petición, incluida cada redirección.

    Esto es lo que cierra la ventana del *DNS rebinding*: entre que `evaluar()`
    aprueba un host y el socket conecta, el DNS puede haber cambiado a una
    dirección interna. Al reescribir el destino a la IP ya validada, esa ventana
    desaparece.

    El TLS sigue siendo correcto: el nombre original se conserva como SNI y en
    la cabecera `Host`, así que el certificado se valida contra el dominio de
    verdad y no contra la IP.

    Se fija **siempre la primera** IP validada. Es un compromiso consciente:
    ignora el balanceo por DNS y no reintenta con la segunda si la primera está
    caída. En un guard de seguridad, la simplicidad del pin vale más que el
    reintento.
    """
    # El contexto de traza se inyecta en TODA salida, incluida la permitida por
    # lista blanca y cada redirección: es la mitad que suele faltar, y sin ella
    # cada servicio traza su trozo y acabamos con cinco trazas de un salto en
    # vez de una de cinco. El identificador de traza no es un secreto —el
    # estándar W3C está pensado para atravesar organizaciones—, así que no hay
    # motivo para tratar distinto a un sistema externo.
    _propagar_traza(peticion)

    host = peticion.url.host
    if host and host.lower() in _permitidos():
        return

    veredicto = evaluar(str(peticion.url))
    if not veredicto.ok:
        logger.warning(
            "url_guard.bloqueada",
            url=str(peticion.url)[:200],
            motivo=veredicto.motivo,
            ips=veredicto.ips,
        )
        raise ErrorValidacion(
            "Esa URL no se puede consultar desde el servidor",
            error_code="red.url_bloqueada",
            detalle={"motivo": veredicto.motivo},
        )

    try:
        ipaddress.ip_address(host or "")
        es_literal = True
    except ValueError:
        es_literal = False

    if not es_literal and veredicto.ips:
        puerto = peticion.url.port
        cabecera = host if puerto is None else f"{host}:{puerto}"
        peticion.url = peticion.url.copy_with(host=veredicto.ips[0])
        peticion.headers["Host"] = cabecera
        peticion.extensions = {**peticion.extensions, "sni_hostname": host}


def _propagar_traza(peticion: httpx.Request) -> None:
    from crmcore.obs import trazas

    cabeceras: dict[str, str] = {}
    trazas.inyectar(cabeceras)
    for clave, valor in cabeceras.items():
        # `setdefault`: si quien construyó la petición ya puso un `traceparent`
        # a mano, manda el suyo. Pisarlo rompería el caso de reenviar una
        # petición conservando su traza original.
        peticion.headers.setdefault(clave, valor)


class _TransporteFijado(httpx.HTTPTransport):
    """Transporte síncrono que valida y fija cada petición."""

    def handle_request(self, peticion: httpx.Request) -> httpx.Response:
        _preparar(peticion)
        return super().handle_request(peticion)


class _TransporteFijadoAsync(httpx.AsyncHTTPTransport):
    """El mismo guard para el cliente asíncrono.

    Hace falta porque la entrega de webhooks y el conector de integraciones son
    asíncronos, y son justo los dos sitios donde la URL la escribe el cliente.
    """

    async def handle_async_request(self, peticion: httpx.Request) -> httpx.Response:
        _preparar(peticion)
        return await super().handle_async_request(peticion)


def cliente_seguro(**kwargs: object) -> httpx.Client:
    """`httpx.Client` con el guard en cada salto. Sustituto directo."""
    kwargs.setdefault("transport", _TransporteFijado())
    return httpx.Client(**kwargs)  # type: ignore[arg-type]


def cliente_seguro_async(**kwargs: object) -> httpx.AsyncClient:
    """`httpx.AsyncClient` con el guard en cada salto. Sustituto directo."""
    kwargs.setdefault("transport", _TransporteFijadoAsync())
    return httpx.AsyncClient(**kwargs)  # type: ignore[arg-type]
