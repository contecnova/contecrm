"""Un fichero a medio escribir no se procesa nunca (`CRM-06.01.01.*`).

`descargar_sftp` leía lo que hubiera y lo devolvía como si estuviera completo.
Un fichero de movimientos truncado a la mitad entraba como entero, y eso no se
descubre hasta que alguien cuadra las cuentas: **importar la mitad es peor que
no importar nada, porque parece que fue bien.**

La regla, decidida y escrita en el código con estas palabras: un fichero
incompleto **se rechaza y se reintenta**, nunca se procesa a medias. Dos casos:

1. Se nota antes de empezar → no se baja, no se archiva, se vuelve a intentar.
2. Se nota durante la lectura → se descarta lo leído y se empieza de cero.

Y **las dos mitades se comprueban**: que lo incompleto se rechace y que lo
completo se procese. Sin la segunda, un cambio que rechazara todo pasaría igual.

Aquí también se fijó un agujero aparte: `archivar_sftp` usaba `AutoAddPolicy()`
fijo, o sea que aceptaba la clave de host que viniera, mientras listar y
descargar exigían la huella. Las tres pasan ahora por el mismo conector.
"""

from __future__ import annotations

from typing import Any

import pytest


class _Atributos:
    """Lo que devuelve `stat`: tamaño y fecha."""

    def __init__(self, tamano: int, mtime: int = 1000) -> None:
        self.st_size = tamano
        self.st_mtime = mtime
        self.filename = ""


class _Fichero:
    def __init__(self, contenido: bytes) -> None:
        self._contenido = contenido

    def read(self) -> bytes:
        return self._contenido

    def __enter__(self) -> _Fichero:
        return self

    def __exit__(self, *_: Any) -> None:
        return None


class _Sftp:
    """Un SFTP de mentira que puede estar escribiéndose.

    `tamanos` es la secuencia que devuelve `stat` en cada llamada: así se
    reproduce exactamente «el fichero crece entre dos miradas», que es la
    situación real y no una metáfora de ella.
    """

    def __init__(self, tamanos: list[int], contenido: bytes) -> None:
        self._tamanos = list(tamanos)
        self._contenido = contenido
        self.movidos: list[tuple[str, str]] = []

    def stat(self, _ruta: str) -> _Atributos:
        tamano = self._tamanos.pop(0) if len(self._tamanos) > 1 else self._tamanos[0]
        return _Atributos(tamano, mtime=1000 + tamano)

    def open(self, _ruta: str, _modo: str) -> _Fichero:
        return _Fichero(self._contenido)

    def listdir_attr(self, _ruta: str) -> list[_Atributos]:
        return []

    def rename(self, origen: str, destino: str) -> None:
        self.movidos.append((origen, destino))


class _Cliente:
    def __init__(self, sftp: _Sftp) -> None:
        self._sftp = sftp
        self.cerrado = False

    def open_sftp(self) -> _Sftp:
        return self._sftp

    def close(self) -> None:
        self.cerrado = True


@pytest.fixture
def sin_esperas(monkeypatch: Any) -> Any:
    """La espera entre miradas, a cero: lo que se prueba es la regla, no el reloj."""
    from crmcore.config import get_settings

    monkeypatch.setenv("SFTP_ESPERA_ESTABILIDAD_S", "0.1")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _montar(monkeypatch: Any, sftp: _Sftp) -> _Cliente:
    from services.integration import transportes_legado as tr

    cliente = _Cliente(sftp)
    monkeypatch.setattr(tr, "_conectar", lambda _c: cliente)
    return cliente


CONFIG = {"host": "sftp.ejemplo.com", "huella_host": "", "aceptar_host_desconocido": True}


# ── Lo incompleto se rechaza ──────────────────────────────────────────────


def test_un_fichero_que_crece_entre_dos_miradas_no_se_baja(
    monkeypatch: Any, sin_esperas: Any
) -> None:
    """El caso 1: se nota antes de leer, así que ni se lee."""
    from services.integration import transportes_legado as tr

    sftp = _Sftp(tamanos=[100, 250], contenido=b"x" * 250)
    _montar(monkeypatch, sftp)

    with pytest.raises(tr.FicheroIncompleto) as fallo:
        tr.descargar_sftp(CONFIG, "/entrada/pedidos.csv")

    assert fallo.value.detalle["motivo"] == "tamano_cambia"
    assert "100" in str(fallo.value) and "250" in str(fallo.value), (
        "el error no dice cuánto creció: sin eso, quien lo lea no sabe si es "
        "un escritor lento o un fichero roto"
    )


def test_un_fichero_que_cambia_mientras_se_lee_se_descarta_entero(
    monkeypatch: Any, sin_esperas: Any
) -> None:
    """El caso 2, y el que más importa: **no se procesa lo leído**.

    Quedarse con el trozo es exactamente lo que esta regla viene a impedir.
    """
    from services.integration import transportes_legado as tr

    # Estable en las dos primeras miradas y distinto en la tercera: creció
    # justo mientras se leía.
    sftp = _Sftp(tamanos=[100, 100, 400], contenido=b"x" * 100)
    _montar(monkeypatch, sftp)

    with pytest.raises(tr.FicheroIncompleto) as fallo:
        tr.descargar_sftp(CONFIG, "/entrada/pedidos.csv")

    assert fallo.value.detalle["motivo"] == "cambia_al_leer"
    assert fallo.value.detalle["leidos"] == 100


def test_lo_leido_tiene_que_cuadrar_con_el_tamano(monkeypatch: Any, sin_esperas: Any) -> None:
    """Un `read` corto sin que cambie el tamaño también es media lectura.

    Pasa con una conexión que se corta: `read` devuelve lo que llegó y no
    levanta nada. Sin comparar con el tamaño, eso entra como fichero entero.
    """
    from services.integration import transportes_legado as tr

    sftp = _Sftp(tamanos=[500], contenido=b"x" * 120)
    _montar(monkeypatch, sftp)

    with pytest.raises(tr.FicheroIncompleto) as fallo:
        tr.descargar_sftp(CONFIG, "/entrada/pedidos.csv")

    assert fallo.value.detalle["leidos"] == 120
    assert fallo.value.detalle["tamano"] == 500


@pytest.mark.parametrize("nombre", ["pedidos.csv.part", "pedidos.tmp", ".pedidos.csv"])
def test_el_nombre_que_dice_que_se_esta_escribiendo_se_salta(
    monkeypatch: Any, sin_esperas: Any, nombre: str
) -> None:
    """La forma fiable, cuando el cliente la respeta: sube a `.part` y renombra.

    Ni se conecta: se rechaza antes.
    """
    from services.integration import transportes_legado as tr

    def _no_deberia(_c: Any) -> Any:
        raise AssertionError("se ha conectado para un fichero que no debía leer")

    monkeypatch.setattr(tr, "_conectar", _no_deberia)

    with pytest.raises(tr.FicheroIncompleto) as fallo:
        tr.descargar_sftp(CONFIG, f"/entrada/{nombre}")
    assert fallo.value.detalle["motivo"] == "nombre_en_curso"


# ── Y lo completo SÍ se procesa ───────────────────────────────────────────


def test_un_fichero_estable_se_baja_entero(monkeypatch: Any, sin_esperas: Any) -> None:
    """La otra mitad. Sin esto, un cambio que rechazara todo pasaría igual."""
    from services.integration import transportes_legado as tr

    sftp = _Sftp(tamanos=[42], contenido=b"a;b;c\n" + b"x" * 36)
    cliente = _montar(monkeypatch, sftp)

    salida = tr.descargar_sftp(CONFIG, "/entrada/pedidos.csv")

    assert salida.startswith("a;b;c")
    assert len(salida) == 42
    assert cliente.cerrado, "la conexión se ha quedado abierta"


# ── El reintento no es infinito en silencio ───────────────────────────────


def test_un_fichero_que_nunca_termina_acaba_avisando(
    monkeypatch: Any, sin_esperas: Any, capsys: Any
) -> None:
    """Sin contador, un fichero roto se reintenta cada pasada para siempre y
    nadie se entera. Se cuenta y se avisa a partir del umbral."""
    from crmcore.config import get_settings

    from services.integration import transportes_legado as tr

    monkeypatch.setenv("SFTP_INTENTOS_PARA_AVISAR", "3")
    get_settings.cache_clear()

    monkeypatch.setattr(
        tr, "listar_sftp", lambda _c: [{"ruta": "/entrada/roto.csv", "nombre": "roto.csv"}]
    )

    def _siempre_incompleto(_c: Any, ruta: str) -> str:
        raise tr.FicheroIncompleto(
            "sigue creciendo", error_code="transportes.sftp_incompleto", detalle={}
        )

    monkeypatch.setattr(tr, "descargar_sftp", _siempre_incompleto)

    cuenta: dict[str, int] = {}
    for _ in range(2):
        salida = tr.recoger_de_sftp(CONFIG, intentos=cuenta)
    assert (
        "fichero_nunca_termina" not in capsys.readouterr().out
    ), "ha avisado a los dos intentos con el umbral en tres"

    salida = tr.recoger_de_sftp(CONFIG, intentos=cuenta)

    assert salida["bajados"] == 0
    assert salida["esperando"][0]["intentos"] == 3
    assert "fichero_nunca_termina" in capsys.readouterr().out, (
        "tres intentos con el umbral en tres y no ha avisado: un fichero que "
        "nunca termina se reintentaría para siempre en silencio"
    )
    get_settings.cache_clear()


def test_el_contador_se_olvida_cuando_el_fichero_entra(monkeypatch: Any, sin_esperas: Any) -> None:
    """Un fichero que tardó tres pasadas y entró no puede seguir contando: la
    siguiente vez que tarde una, saltaría el aviso sin motivo."""
    from services.integration import transportes_legado as tr

    monkeypatch.setattr(
        tr, "listar_sftp", lambda _c: [{"ruta": "/entrada/ok.csv", "nombre": "ok.csv"}]
    )
    monkeypatch.setattr(tr, "descargar_sftp", lambda _c, _r: "contenido")

    cuenta = {"/entrada/ok.csv": 4}
    salida = tr.recoger_de_sftp(CONFIG, intentos=cuenta)

    assert salida["bajados"] == 1
    assert "/entrada/ok.csv" not in cuenta


# ── La huella del host, en las tres ───────────────────────────────────────


def test_archivar_comprueba_la_huella_como_las_otras_dos() -> None:
    """Usaba `AutoAddPolicy()` fijo: aceptaba la clave que viniera.

    Listar y descargar exigían la huella y mover el fichero ya procesado se la
    saltaba, así que quien se pusiera en medio podía hacerse pasar por el
    servidor justo en ese momento. Las tres pasan por el mismo conector.
    """
    import inspect

    from services.integration import transportes_legado as tr

    for funcion in (tr.listar_sftp, tr.descargar_sftp, tr.archivar_sftp):
        fuente = inspect.getsource(funcion)
        assert "_conectar(config)" in fuente, (
            f"«{funcion.__name__}» abre la conexión por su cuenta: tres copias "
            "de «conéctate al SFTP» divergen siempre, y la que se queda atrás "
            "es la puerta por la que se entra"
        )
        # SE MIRA LA LLAMADA, no la palabra: la primera versión de esto casaba
        # con el `AutoAddPolicy` del comentario que explica el arreglo, y daba
        # rojo sobre código correcto. Una sonda que no distingue el código del
        # texto que lo explica miente en las dos direcciones.
        assert "set_missing_host_key_policy" not in fuente, (
            f"«{funcion.__name__}» decide por su cuenta qué clave de host "
            "acepta, en vez de dejárselo al conector"
        )


def test_sin_huella_y_sin_declararlo_no_se_conecta() -> None:
    """El aviso solo lo lee alguien si le impide seguir."""
    from crmcore.errors import ErrorValidacion

    from services.integration import transportes_legado as tr

    with pytest.raises(ErrorValidacion) as fallo:
        tr._conectar({"host": "sftp.ejemplo.com"})
    assert fallo.value.error_code == "transportes.sftp_sin_huella"
