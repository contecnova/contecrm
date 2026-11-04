"""Los vecinos tienen dirección también cuando contecrm arranca EN LOCAL.

contecrm depende de dos servicios de la casa —contecintelligence para la
explotación del dato y contecmind para el corpus documental— y les habla por su
nombre dentro de la red de Docker: `http://contecintelligence:8000`,
`http://contecmind:4000`.

Ese nombre **no existe** para un proceso de la máquina. Y el arranque por
defecto, `./setup.sh arrancar` sin `--docker`, deja los catorce servicios como
procesos de la máquina. O sea que en la instalación que usa todo el mundo esas
direcciones no resuelven, y el área entera que cuelga de cada vecino se cae con
«nodename nor servname provided».

Le pasó primero a contecintelligence y se arregló: `arrancar_local` exporta su
dirección desde `CI_URL_PUBLICA`, que significa por definición «visto desde
fuera de su contenedor». **Y ahí se paró.** El vecino de al lado tenía el mismo
problema, idéntico, y nadie recorrió la familia: contecmind se quedó sin su
media línea. Medido el 04-11-2026 abriendo «Aprobaciones», que decía «El gestor
documental no responde en http://contecmind:4000». Era verdad, y no era culpa
suya: nadie podía llegar a él.

Esta prueba no vigila a contecmind: vigila a **todos los vecinos declarados**,
que es la forma de que el tercero no repita el caso del segundo.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]


def _vecinos_py():
    """El módulo `scripts/vecinos.py`, que no es un paquete importable."""
    spec = importlib.util.spec_from_file_location("vecinos_script", RAIZ / "scripts" / "vecinos.py")
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["vecinos_script"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def vecinos():
    return _vecinos_py()


def test_cada_vecino_declara_su_direccion_de_fuera(vecinos):
    """Los dos ajustes existen en Settings, no son nombres sueltos."""
    from crmcore.config import Settings

    campos = set(Settings.model_fields)
    assert vecinos.VECINOS, "no hay vecinos declarados: esta prueba no miraría nada"
    for vecino in vecinos.VECINOS:
        assert (
            vecino.ajuste_url.lower() in campos
        ), f"{vecino.nombre}: {vecino.ajuste_url} no es un ajuste de verdad"
        assert vecino.ajuste_url_local, (
            f"{vecino.nombre} no dice con qué dirección se le llama desde un "
            "proceso de la máquina. Sin eso, el arranque por defecto lo deja "
            "inalcanzable y la pantalla que dependa de él dirá que no responde"
        )
        assert (
            vecino.ajuste_url_local.lower() in campos
        ), f"{vecino.nombre}: {vecino.ajuste_url_local} no es un ajuste de verdad"


def test_el_arranque_local_exporta_la_direccion_de_cada_vecino(vecinos):
    """`setup.sh`, en local, saca la dirección de cada vecino de su ajuste.

    Es la línea que faltaba. Se mira el fichero porque es donde se decide, y se
    exige **la pareja**: exportar el ajuste de servidor a partir del de fuera.
    Exportarlo a partir de cualquier otra cosa sería escribir una dirección a
    mano, que es lo que no puede volver a pasar.
    """
    fuente = (RAIZ / "setup.sh").read_text()
    inicio = fuente.index("arrancar_local()")
    fin = (
        fuente.index("arrancar_docker()") if "arrancar_docker()" in fuente[inicio:] else len(fuente)
    )
    local = fuente[inicio:fin] if fin > inicio else fuente[inicio:]

    mirados = 0
    for vecino in vecinos.VECINOS:
        mirados += 1
        assert f"export {vecino.ajuste_url}=" in local, (
            f"{vecino.nombre}: el arranque local no exporta {vecino.ajuste_url}, "
            f"así que los servicios usarán el nombre de la red de Docker y no "
            f"llegarán. Es el fallo que dejó «Aprobaciones» muerta"
        )
        assert vecino.ajuste_url_local in local, (
            f"{vecino.nombre}: el arranque local no lee {vecino.ajuste_url_local}. "
            "La dirección tiene que salir de ahí, no escrita a mano"
        )
    assert mirados >= 2, "se han mirado menos vecinos de los que hay declarados"


def test_el_modo_local_no_se_lee_como_apagado(vecinos, monkeypatch):
    """Sin contenedor de gateway pero con el puerto ocupado, es LOCAL.

    Decía «contecrm no está levantado» con los catorce servicios en verde, y con
    esa frase **abortaba el arranque de los vecinos**: por eso el área documental
    llevaba muerta en el modo por defecto sin que nadie viera por qué.
    """

    class _Vacio:
        stdout = ""
        returncode = 0

    monkeypatch.setattr(vecinos, "_correr", lambda *a, **k: _Vacio())
    monkeypatch.setattr(vecinos, "_ocupado_en_el_equipo", lambda puerto, ip: True)
    assert vecinos.modo_de_contecrm() == (vecinos.MODO_LOCAL, None)

    # Y si además el puerto está libre, entonces sí: no está levantado.
    monkeypatch.setattr(vecinos, "_ocupado_en_el_equipo", lambda puerto, ip: False)
    assert vecinos.modo_de_contecrm() == (vecinos.MODO_APAGADO, None)


def test_cada_modo_mira_el_ajuste_que_manda(vecinos):
    """En local manda el ajuste de fuera; en Docker, el de la red."""
    for vecino in vecinos.VECINOS:
        assert vecinos.ajuste_de_este_modo(vecino, vecinos.MODO_LOCAL) == vecino.ajuste_url_local
        assert vecinos.ajuste_de_este_modo(vecino, vecinos.MODO_DOCKER) == vecino.ajuste_url


def test_la_puerta_publicada_puede_no_ser_la_del_api(vecinos):
    """Hay vecinos cuya API no publica puerto: se entra por otro contenedor.

    contecmind lo dice en su compose —«Sin `ports:` a propósito: la API se
    alcanza a través de `web`»—, así que preguntar al contenedor de la API por
    su puerto del equipo devolvía nada. Y «nada» no se leía como un fallo: se
    leía como una comprobación que no se podía hacer, que es peor.
    """
    mind = next(v for v in vecinos.VECINOS if v.nombre == "contecmind")
    assert mind.puerta_publicada() == ("contecmind-web", 8080)

    ci = next(v for v in vecinos.VECINOS if v.nombre == "contecintelligence")
    assert ci.puerta_publicada() == (ci.contenedor, ci.puerto_interno)
