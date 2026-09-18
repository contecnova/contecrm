"""Guard de SSRF en las salidas de red del servidor.

Todo sitio que busca una URL **que aporta el tenant** —webhooks, conector de
integraciones, descubrimiento del proveedor de identidad— pasa por aquí.

Sin esto no hace falta ningún fallo del producto: basta la funcionalidad tal
como está diseñada. Un tenant registra un webhook contra el punto de metadatos
de la nube y se lleva las credenciales de la máquina; o contra un puerto interno
y escanea la red desde dentro, con la salida en el cuerpo de la respuesta que el
propio CRM le guarda para depurar.
"""

from __future__ import annotations

from typing import Any

import pytest
from crmcore.errors import ErrorValidacion
from crmcore.red import evaluar, exigir

# ── Forma de la URL ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url,fragmento",
    [
        ("file:///etc/passwd", "esquema"),
        ("gopher://x/", "esquema"),
        ("", "vacía"),
        ("https://", "host"),
        ("https://usuario:clave@ejemplo.com/", "credenciales"),
    ],
)
def test_se_rechaza_por_la_forma_sin_tocar_el_dns(url: str, fragmento: str) -> None:
    veredicto = evaluar(url)
    assert not veredicto.ok
    assert fragmento in veredicto.motivo


def test_el_orden_de_los_rechazos_es_contrato() -> None:
    """Cuando una URL viola varias cosas, el motivo es el de la PRIMERA. Es lo
    que acaba en el log y delante del operador; cambiar el orden cambia el
    diagnóstico."""
    veredicto = evaluar("file://usuario:clave@/etc/passwd")
    assert "esquema" in veredicto.motivo


# ── Rangos bloqueados ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "ip",
    [
        "169.254.169.254",  # metadatos de AWS, GCP y Azure: el objetivo número uno
        "127.0.0.1",
        "10.0.0.5",
        "172.16.0.1",
        "192.168.1.1",
        "0.0.0.0",
        "[::1]",
        "[fd00::1]",
    ],
)
def test_las_ip_internas_se_bloquean(ip: str) -> None:
    veredicto = evaluar(f"http://{ip}/algo")
    assert not veredicto.ok
    assert "bloqueado" in veredicto.motivo


def test_una_ip_publica_pasa() -> None:
    veredicto = evaluar("https://8.8.8.8/x")
    assert veredicto.ok


def test_un_host_que_resuelve_a_interna_se_bloquea() -> None:
    """Apuntar un dominio propio a 127.0.0.1 es el truco más simple para
    saltarse un filtro que solo mire el texto de la URL."""
    veredicto = evaluar("http://localhost/algo")
    assert not veredicto.ok
    assert "bloqueado" in veredicto.motivo


def test_un_host_que_no_resuelve_falla_cerrado() -> None:
    """Dejarlo pasar convertiría un DNS lento en una vía para saltarse el guard."""
    veredicto = evaluar("https://este-dominio-no-existe-jamas-987654321.invalid/")
    assert not veredicto.ok


def test_exigir_lanza_con_codigo_estable() -> None:
    with pytest.raises(ErrorValidacion) as exc:
        exigir("http://169.254.169.254/latest/meta-data/")
    assert exc.value.error_code == "red.url_bloqueada"


# ── Escape configurado ────────────────────────────────────────────────────


def test_el_operador_puede_admitir_un_host_interno(monkeypatch: pytest.MonkeyPatch) -> None:
    """Existe porque hay instalaciones con el IdP o el ERP en la red interna, y
    negarlo obligaría a apagar el guard entero."""
    import crmcore.red.guard_url as g

    monkeypatch.setattr(g, "_permitidos", lambda: {"erp.interno"})
    assert evaluar("https://erp.interno/api").ok
    # Y no abre la mano para los demás.
    assert not evaluar("https://otro.interno/api").ok


# ── Fijado de IP y redirecciones ──────────────────────────────────────────


def test_el_cliente_seguro_revalida_y_fija_la_ip() -> None:
    """Cierra la ventana del DNS rebinding: entre que se aprueba el host y el
    socket conecta, el DNS puede cambiar a una dirección interna."""
    import httpx
    from crmcore.red.guard_url import _preparar

    peticion = httpx.Request("GET", "https://example.com/recurso")
    _preparar(peticion)

    # El destino pasa a ser la IP validada, pero el nombre se conserva para el
    # TLS y la cabecera Host: si no, el certificado no validaría.
    assert peticion.url.host != "example.com"
    assert peticion.headers["Host"] == "example.com"
    assert peticion.extensions.get("sni_hostname") == "example.com"


def test_una_redireccion_hacia_dentro_se_bloquea_en_el_salto() -> None:
    """Un servidor que responde 302 hacia los metadatos salta cualquier
    validación hecha solo sobre la URL inicial. El conector sigue
    redirecciones, así que esto no es hipotético."""
    import httpx
    from crmcore.red.guard_url import _preparar

    salto = httpx.Request("GET", "http://169.254.169.254/latest/meta-data/")
    with pytest.raises(ErrorValidacion) as exc:
        _preparar(salto)
    assert exc.value.error_code == "red.url_bloqueada"


def test_una_ip_literal_publica_no_se_reescribe() -> None:
    import httpx
    from crmcore.red.guard_url import _preparar

    peticion = httpx.Request("GET", "https://8.8.8.8/x")
    _preparar(peticion)
    assert peticion.url.host == "8.8.8.8"


# ── Integración con los sitios que lo usan ────────────────────────────────


def test_los_clientes_del_nucleo_traen_el_guard_puesto() -> None:
    """Un `httpx.AsyncClient` normal en cualquiera de estos caminos sería el
    agujero de vuelta; el gate de arquitectura lo vigila, esto lo comprueba."""
    from crmcore.red import cliente_seguro, cliente_seguro_async
    from crmcore.red.guard_url import _TransporteFijado, _TransporteFijadoAsync

    assert isinstance(cliente_seguro()._transport, _TransporteFijado)
    assert isinstance(cliente_seguro_async()._transport, _TransporteFijadoAsync)


def test_dar_de_alta_un_webhook_hacia_dentro_se_rechaza(db: Any) -> None:
    """Se comprueba al darlo de alta además de en cada entrega: así el error sale
    delante de quien lo configura y no en un log a las tres de la mañana."""
    with pytest.raises(ErrorValidacion) as exc:
        exigir("https://169.254.169.254/hook")
    assert exc.value.error_code == "red.url_bloqueada"
