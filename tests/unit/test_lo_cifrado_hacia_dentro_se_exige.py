"""Cuatro ajustes de cifrado y secretos que no leía nadie.

Medidos el 06-10-2026 con el barrido de ajustes sin lector.

`BUS_TLS` y `CACHE_TLS` prometían que esos dos tramos van cifrados, y quien los
ponía a `true` creía haber cerrado el camino hacia el bus: los eventos seguían
viajando por donde dijera la URL, en claro si era `redis://`.

**No se reescribe la URL.** Una URL reescrita a espaldas de quien la puso lleva
a un fallo de conexión que nadie relaciona con un ajuste de otra sección. Lo que
se hace es exigir: declarado el cifrado y la URL sin cifrar, el arranque se
niega. Mismo criterio que `TRUST_PROXY_HEADERS` con `TRUSTED_PROXIES`.

`SECRETOS_BACKEND` es el peor de los cuatro. Poner `vault` guardaba los secretos
en la base igual, y quien lo pusiera creería que las credenciales de sus
integraciones están en su gestor externo cuando están aquí. No es un ajuste
decorativo: es una creencia falsa sobre **dónde están los secretos del cliente**.
Y `SECRETOS_VAULT_URL` se quita, porque sólo tenía sentido con ese backend.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from crmcore.errors import ErrorValidacion
from crmcore.red import tls_exigido

# ── TLS exigido hacia el bus y la caché ───────────────────────────────────


@pytest.mark.parametrize("url", ["rediss://x:6379", "tls://x:4222", "amqps://x"])
def test_una_url_cifrada_pasa(url: str) -> None:
    tls_exigido.exigir(url, tramo="el bus", ajuste="BUS_TLS", exigido=True)


@pytest.mark.parametrize("url", ["redis://x:6379", "nats://x:4222", "amqp://x"])
def test_una_url_en_claro_con_el_cifrado_exigido_corta(url: str) -> None:
    with pytest.raises(ErrorValidacion) as fallo:
        tls_exigido.exigir(url, tramo="el bus", ajuste="BUS_TLS", exigido=True)
    assert fallo.value.error_code == "red.tls_exigido_sin_cifrar"
    # Y dice las dos salidas: cambiar la URL o apagar el ajuste. Decir sólo que
    # está mal deja a quien administra adivinando cuál de las dos quería.
    assert "BUS_TLS=false" in str(fallo.value)


def test_un_esquema_desconocido_no_se_da_por_cifrado() -> None:
    """Dar por bueno lo que no se reconoce es cómo una comprobación de seguridad
    deja de comprobar."""
    with pytest.raises(ErrorValidacion):
        tls_exigido.exigir("loquesea://x", tramo="el bus", ajuste="BUS_TLS", exigido=True)


def test_sin_exigirlo_no_se_comprueba_nada() -> None:
    """Declarar que un tramo va en claro es una decisión legítima —el bus en la
    misma red privada— y convertirla en un aviso en cada arranque enseña a
    ignorar los avisos."""
    tls_exigido.exigir("redis://x:6379", tramo="el bus", ajuste="BUS_TLS", exigido=False)


def test_la_url_no_se_reescribe() -> None:
    """Reescribirla a espaldas de quien la puso lleva a un fallo de conexión que
    nadie relaciona con un ajuste de otra sección."""
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    fuente = (raiz / "packages/crmcore/crmcore/red/tls_exigido.py").read_text(encoding="utf-8")
    # Nada que sustituya: sólo se mira y se compara. El mensaje de error sí
    # nombra el esquema que ha encontrado, que es lo que hace falta para
    # arreglarlo.
    assert ".replace(" not in fuente
    # Y lo comprobable de verdad: la URL vuelve igual de donde se mire.
    for url in ("redis://x", "rediss://x", "nats://x"):
        assert tls_exigido.esquema_de(url) == url.split("://")[0]


@pytest.mark.parametrize(
    ("fichero", "ajuste"),
    [
        ("packages/crmcore/crmcore/bus/base.py", "BUS_TLS"),
        ("packages/crmcore/crmcore/cache/base.py", "CACHE_TLS"),
    ],
)
def test_los_dos_tramos_lo_exigen_donde_se_conectan(fichero: str, ajuste: str) -> None:
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    fuente = (raiz / fichero).read_text(encoding="utf-8")
    assert f'ajuste="{ajuste}"' in fuente, f"{fichero} no exige {ajuste}"


def test_el_bus_lo_exige_en_sus_dos_transportes() -> None:
    """Redis y NATS son dos caminos, y cerrar sólo uno deja el otro abierto con
    el ajuste puesto: parecería hecho."""
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    fuente = (raiz / "packages/crmcore/crmcore/bus/base.py").read_text(encoding="utf-8")
    assert fuente.count("tls_exigido.exigir(") == 2


def test_la_cache_lo_exige_antes_de_caer_a_memoria() -> None:
    """La caché cae a memoria si Redis no responde, a propósito. Una URL en
    claro cuando se ha exigido cifrado no es una caché caída: es una
    configuración que miente, y caer la dejaría pasar en silencio."""
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    fuente = (raiz / "packages/crmcore/crmcore/cache/base.py").read_text(encoding="utf-8")
    trozo = fuente.split('if s.cache_backend == "redis" and s.cache_url:')[1][:900]
    assert trozo.index("tls_exigido.exigir") < trozo.index("try:")


# ── Dónde están los secretos ──────────────────────────────────────────────


@pytest.fixture
def backend(request: Any) -> Any:
    from crmcore.config import limpiar_cache_settings

    previo = os.environ.get("SECRETOS_BACKEND")
    os.environ["SECRETOS_BACKEND"] = request.param
    limpiar_cache_settings()
    try:
        yield
    finally:
        if previo is None:
            os.environ.pop("SECRETOS_BACKEND", None)
        else:
            os.environ["SECRETOS_BACKEND"] = previo
        limpiar_cache_settings()


@pytest.mark.parametrize("backend", ["vault"], indirect=True)
def test_un_almacen_que_no_existe_no_guarda_en_la_base_en_silencio(backend: Any) -> None:
    """Es la creencia falsa: «lo he puesto en vault y funciona, luego está en
    vault»."""
    from crmcore.security.cifrado import cifrar_dict

    with pytest.raises(ErrorValidacion) as fallo:
        cifrar_dict({"client_secret": "x"})
    assert fallo.value.error_code == "secretos.backend_desconocido"
    assert "db" in str(fallo.value.detalle["disponibles"])


@pytest.mark.parametrize("backend", ["vault"], indirect=True)
def test_tambien_al_leer(backend: Any) -> None:
    """Seguir sirviéndolos de la base confirmaría la creencia falsa."""
    from crmcore.security.cifrado import descifrar_dict

    with pytest.raises(ErrorValidacion):
        descifrar_dict({"client_secret": "x"})


@pytest.mark.parametrize("backend", ["db"], indirect=True)
def test_el_almacen_que_existe_funciona(backend: Any) -> None:
    from crmcore.security.cifrado import cifrar_dict, descifrar_dict

    cifrado = cifrar_dict({"client_secret": "secreto"})
    assert cifrado["client_secret"] != "secreto"
    assert descifrar_dict(cifrado)["client_secret"] == "secreto"


def test_la_url_de_vault_ya_no_existe() -> None:
    """Un ajuste que apunta a un gestor externo al que el producto no habla hace
    creer que los secretos están allí."""
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    fuente = (raiz / "packages/crmcore/crmcore/config_parts/_security.py").read_text(
        encoding="utf-8"
    )
    assert "secretos_vault_url: str" not in fuente
