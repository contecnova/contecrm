"""Por qué no se pudo registrar la fuente, dicho para leerse.

**Medido el 04-11-2026** abriendo «Explotación» en la pila local. En pantalla,
al usuario:

    El alta del CRM como fuente se intentó y falló: contecintelligence ha
    rechazado el registro de la fuente · {'codigo_http': 400, 'cuerpo':
    '{"detail":"La fuente no responde (health_check fallo)."}'}

Un diccionario de Python con un JSON dentro. El motivo de verdad —«la fuente
no responde»— estaba ahí metido, y lo único que permite arreglarlo —**con qué
dirección tiene que alcanzarnos contecintelligence**— no salía por ninguna
parte: ni en la pantalla, ni en el detalle técnico, ni en el registro.

No lo cazaba el barrido de pantallas porque busca `null`, `undefined` y
`[object Object]`, y la representación de un `dict` de Python no es ninguna de
las tres.
"""

from __future__ import annotations

from services.analytics.fuente import _porque_lo_rechazo


class _Respuesta:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


def test_dice_el_motivo_del_otro_lado_sin_el_envoltorio() -> None:
    dicho = _porque_lo_rechazo(
        _Respuesta(400, '{"detail":"La fuente no responde (health_check fallo)."}'),
        "http://host.docker.internal:18080/api/v1",
    )
    assert "La fuente no responde" in dicho
    # Y sin el diccionario ni las llaves de JSON delante de nadie.
    for basura in ("{'", "codigo_http", '{"detail"', "cuerpo'"):
        assert basura not in dicho, f"sigue saliendo «{basura}»"


def test_dice_con_que_direccion_tiene_que_alcanzarnos() -> None:
    """Es lo único accionable, y era lo único que no estaba.

    Sin ella, quien lee «la fuente no responde» no sabe si mirar el puerto, el
    cortafuegos o el nombre de red: son tres sitios distintos.
    """
    dicho = _porque_lo_rechazo(
        _Respuesta(400, '{"detail":"La fuente no responde."}'),
        "http://host.docker.internal:18080/api/v1",
    )
    assert "http://host.docker.internal:18080/api/v1" in dicho


def test_un_rechazo_mudo_no_deja_la_frase_a_medias() -> None:
    """Si el otro lado no dice nada, se dice eso: una frase que acaba en dos
    puntos y nada detrás parece que falta texto, no que falte el motivo."""
    dicho = _porque_lo_rechazo(_Respuesta(503, ""), "http://crm/api/v1")
    assert "no ha dicho por qué" in dicho
    assert "503" in dicho


def test_un_cuerpo_que_no_es_json_se_enseña_igual() -> None:
    """Un proxy delante puede contestar HTML. Antes que tragárselo, se enseña
    lo que llegó: recortado, pero algo."""
    dicho = _porque_lo_rechazo(_Respuesta(502, "<html>Bad Gateway</html>"), "http://crm/api/v1")
    assert "Bad Gateway" in dicho
    assert "502" in dicho


def test_el_registro_usa_esta_frase_y_no_otra() -> None:
    """**Por el sitio donde se lanza, no por el ayudante suelto.**

    Las de arriba llaman a `_porque_lo_rechazo` directamente, así que seguían
    en verde con el `raise` devolviendo el texto corto otra vez y el
    diccionario detrás: probado plantándolo. Lo que hay que afirmar es que la
    frase **sale**, y eso depende de quién la construye.
    """
    import inspect

    from services.analytics import fuente

    fuentes = inspect.getsource(fuente)
    i = fuentes.index('error_code="analytics.registro_rechazado"')
    # Los veinte renglones de antes: ahí está el mensaje del `raise`.
    antes = fuentes[:i].rsplit("raise ErrorDependencia(", 1)[-1]
    assert "_porque_lo_rechazo(" in antes, (
        "el rechazo vuelve a lanzarse con un texto suelto, así que el motivo "
        "de contecintelligence y la dirección no llegan a la pantalla"
    )


def test_lo_que_se_guarda_para_la_pantalla_no_lleva_el_diccionario() -> None:
    """El texto que acaba en «Explotación» sale de `fila.error`.

    Se le pegaba el `detalle` del error —un `dict` de Python— porque el
    mensaje era un titular que no decía el motivo. Ahora sí lo dice, así que
    pegarlo no añade nada y estropea la pantalla. El detalle sigue entero en
    el registro, que es de donde lo saca quien depura.
    """
    import inspect

    from services.analytics import fuente

    fuentes = inspect.getsource(fuente)
    assert 'f"{exc} · {detalle}"' not in fuentes, (
        "el detalle vuelve a pegarse al mensaje, así que la pantalla enseña "
        "un diccionario de Python al usuario"
    )
    # Y no se pierde: el registro lo sigue llevando.
    assert "detalle=detalle" in fuentes
