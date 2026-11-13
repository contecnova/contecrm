"""La IP de quien llama no la decide quien llama (SEC-8, auditoría 13-11-2026).

Con `TRUST_PROXY_HEADERS` activo se cogía el PRIMER valor de `X-Forwarded-For`,
que es justo el que escribe el cliente: nginx añade la IP real a la derecha. Así
se saltaban el límite por IP, la lista de redes de una clave de API y el acceso
contextual. Y `TRUSTED_PROXIES` no lo leía nadie.

Había tres copias de esa lógica; las tres usan ahora `ip_del_cliente`, y la
última prueba lo fija.
"""

from __future__ import annotations

import inspect

import pytest
from crmcore.config import get_settings
from crmcore.http.ip_cliente import ip_del_cliente

NGINX = "10.0.0.5"


@pytest.fixture
def detras_de_nginx(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "trust_proxy_headers", True)
    monkeypatch.setattr(s, "trusted_proxies", "10.0.0.0/24, 172.18.0.2")


def test_lo_que_el_cliente_pone_a_la_izquierda_no_vale(detras_de_nginx: None) -> None:
    """El ataque: el cliente manda una IP permitida y nginx le añade la suya."""
    assert ip_del_cliente(NGINX, "192.168.1.10, 203.0.113.7") == "203.0.113.7"


def test_sin_proxy_de_confianza_delante_la_cabecera_no_se_mira(detras_de_nginx: None) -> None:
    assert ip_del_cliente("198.51.100.9", "192.168.1.10") == "198.51.100.9"


def test_una_cadena_de_proxies_propios_se_atraviesa(detras_de_nginx: None) -> None:
    """Cliente → nginx (10.0.0.5) → gateway (172.18.0.2) → servicio."""
    assert ip_del_cliente("172.18.0.2", "203.0.113.7, 10.0.0.5") == "203.0.113.7"


def test_sin_redes_declaradas_no_se_confia_en_nadie(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "trust_proxy_headers", True)
    monkeypatch.setattr(s, "trusted_proxies", "")
    assert ip_del_cliente(NGINX, "192.168.1.10") == NGINX


def test_apagado_es_el_par_tcp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "trust_proxy_headers", False)
    assert ip_del_cliente(NGINX, "192.168.1.10") == NGINX


def test_las_tres_puertas_usan_la_misma_regla() -> None:
    """La dependencia HTTP, el limitador y el gateway: ninguna parte la cabecera."""
    from crmcore.http import deps, rate_limit

    from services.gateway import main

    for funcion in (deps._ip, rate_limit._ip_cliente, main.ip_de):
        fuente = inspect.getsource(funcion)
        assert "ip_del_cliente" in fuente, funcion.__qualname__
        assert 'split(",")[0]' not in fuente, funcion.__qualname__
