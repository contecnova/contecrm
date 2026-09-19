#!/usr/bin/env python3
"""Mide el cifrado de un despliegue. No lo declara: lo comprueba (CRM-00.05.03.01).

    python scripts/verificar_cifrado.py https://crm.ejemplo.com

Existe por la misma razón que `medir_volumetria.py`: **una garantía declarada y
no medida es una frase en un documento**. «Cifrado en tránsito con TLS 1.3» es
exactamente el tipo de afirmación que nadie comprueba hasta que un auditor la
pide, y para entonces llevas dos años con un balanceador aceptando TLS 1.0.

Qué comprueba, y qué NO:

  * **La versión de TLS que negocia de verdad** el extremo público, y que
    rechaza las versiones viejas. Eso se mide abriendo el socket.
  * **Las cabeceras de seguridad** que promete el middleware: HSTS y las tres
    que evitan que una respuesta se interprete como otra cosa.
  * **Que una petición en claro se rechaza**, si el despliegue lo declara.
  * **El modo SSL con Postgres**, preguntándole a la propia conexión.

Lo que **no** puede comprobar desde fuera: el cifrado del disco y de las copias
de seguridad. Eso lo da el proveedor de infraestructura o el sistema de
ficheros, y este script lo dice en vez de sugerir que lo ha verificado. La
comprobación de esa parte es una lista en el Manual de operación, firmada por
quien despliega.

Sale con código 1 si algo falla, para poder engancharlo a un `make` o a un
procedimiento de puesta en producción.
"""

from __future__ import annotations

import socket
import ssl
import sys
from urllib.parse import urlparse

VERSIONES_PROHIBIDAS = (
    ("TLSv1", ssl.TLSVersion.TLSv1),
    ("TLSv1.1", ssl.TLSVersion.TLSv1_1),
    ("TLSv1.2", ssl.TLSVersion.TLSv1_2),
)

CABECERAS_EXIGIDAS = {
    "strict-transport-security": "HSTS: sin él, la primera petición de cada navegador puede ir en claro",
    "x-content-type-options": "evita que una respuesta se interprete como otra cosa",
    "x-frame-options": "evita que la API se embeba en un marco ajeno",
    "referrer-policy": "evita filtrar la URL completa —con sus identificadores— al navegar fuera",
}


def _resultado(ok: bool, texto: str) -> tuple[bool, str]:
    print(f"  {'✓' if ok else '✗'} {texto}")
    return ok, texto


def comprobar_tls(host: str, puerto: int, minima: str) -> list[tuple[bool, str]]:
    """Negocia de verdad y mira qué sale."""
    salida: list[tuple[bool, str]] = []
    contexto = ssl.create_default_context()
    try:
        with socket.create_connection((host, puerto), timeout=10) as crudo:
            with contexto.wrap_socket(crudo, server_hostname=host) as seguro:
                negociada = seguro.version() or "?"
        esperada = f"TLSv{minima}"
        salida.append(
            _resultado(
                negociada >= esperada,
                f"negocia {negociada} (se exige al menos {esperada})",
            )
        )
    except Exception as exc:  # noqa: BLE001 — no poder conectar ES el resultado
        return [_resultado(False, f"no se pudo negociar TLS: {type(exc).__name__}: {exc}")]

    # Y que las viejas NO se aceptan. Que negocie 1.3 con un cliente moderno no
    # dice nada si además sigue aceptando 1.0 con uno antiguo: el atacante elige
    # el cliente.
    tope = {"1.2": ssl.TLSVersion.TLSv1_1, "1.3": ssl.TLSVersion.TLSv1_2}[minima]
    for nombre, version in VERSIONES_PROHIBIDAS:
        if version > tope:
            continue
        viejo = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        viejo.check_hostname = False
        viejo.verify_mode = ssl.CERT_NONE
        viejo.minimum_version = version
        viejo.maximum_version = version
        try:
            with socket.create_connection((host, puerto), timeout=10) as crudo:
                with viejo.wrap_socket(crudo, server_hostname=host):
                    salida.append(_resultado(False, f"ACEPTA {nombre}, que debería rechazar"))
        except Exception:  # noqa: BLE001 — que falle es lo correcto
            salida.append(_resultado(True, f"rechaza {nombre}"))
    return salida


def comprobar_cabeceras(url: str) -> list[tuple[bool, str]]:
    import httpx

    try:
        respuesta = httpx.get(f"{url}/health/live", timeout=10.0)
    except Exception as exc:  # noqa: BLE001
        return [_resultado(False, f"no responde: {exc}")]

    salida = []
    for cabecera, porque in CABECERAS_EXIGIDAS.items():
        presente = cabecera in respuesta.headers
        salida.append(_resultado(presente, f"{cabecera} — {porque}"))
    return salida


def comprobar_http_en_claro(host: str) -> list[tuple[bool, str]]:
    """Que una petición por HTTP no se atiende.

    Se espera un rechazo o una redirección, **no** un 200. Un 200 significa que
    la credencial ya ha viajado en claro.
    """
    import httpx

    try:
        respuesta = httpx.get(f"http://{host}/health/live", timeout=10.0, follow_redirects=False)
    except Exception:  # noqa: BLE001 — no escuchar en HTTP es el mejor resultado
        return [_resultado(True, "no atiende por HTTP en claro")]
    ok = respuesta.status_code >= 300
    return [_resultado(ok, f"HTTP en claro responde {respuesta.status_code} (debe ser 3xx o 4xx)")]


def comprobar_base_de_datos() -> list[tuple[bool, str]]:
    """Le pregunta a la propia conexión si está cifrada.

    `pg_stat_ssl` lo dice desde dentro, que es la única forma de saberlo sin
    fiarse de la configuración: un `sslmode=require` mal propagado se ve aquí y
    en ningún otro sitio.
    """
    try:
        from crmcore.db.session import get_engine
        from sqlalchemy import text

        with get_engine().connect() as conexion:
            fila = conexion.execute(
                text("SELECT ssl, version FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
            ).first()
    except Exception as exc:  # noqa: BLE001
        return [_resultado(False, f"no se pudo consultar el estado SSL de Postgres: {exc}")]

    if fila is None:
        return [_resultado(False, "Postgres no informa de `pg_stat_ssl`")]
    cifrada, version = bool(fila[0]), fila[1] or "?"
    return [
        _resultado(
            cifrada, f"conexión con Postgres {'cifrada' if cifrada else 'EN CLARO'} ({version})"
        )
    ]


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    url = sys.argv[1].rstrip("/")
    partes = urlparse(url)
    host = partes.hostname or ""
    puerto = partes.port or (443 if partes.scheme == "https" else 80)

    from crmcore.config import get_settings

    minima = get_settings().tls_version_minima

    resultados: list[tuple[bool, str]] = []
    print(f"\nCifrado en tránsito de {url}\n")
    print("TLS del extremo público")
    resultados += comprobar_tls(host, puerto, minima)
    print("\nCabeceras de seguridad")
    resultados += comprobar_cabeceras(url)
    print("\nHTTP en claro")
    resultados += comprobar_http_en_claro(host)
    print("\nConexión con la base de datos")
    resultados += comprobar_base_de_datos()

    print(
        "\nLo que este script NO comprueba, y hay que decirlo: el cifrado del\n"
        "disco y el de las copias de seguridad. Eso lo da la infraestructura, y\n"
        "su verificación es la lista del Manual de operación, firmada por quien\n"
        "despliega. Afirmar aquí que están cifrados sería inventárselo."
    )

    fallos = [texto for ok, texto in resultados if not ok]
    if fallos:
        print(f"\n{len(fallos)} comprobación(es) en rojo.")
        return 1
    print(f"\nTodo en verde ({len(resultados)} comprobaciones).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
