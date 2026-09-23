"""Quien no ha entrado recibe un 401, no un 500.

La aplicación web pregunta «¿quién soy?» nada más cargar, antes de que haya
sesión. Esa llamada devolvía **500** con `db.sesion_sin_tenant`, porque la
dependencia de base de datos intentaba abrir una sesión atada a un tenant que no
existía todavía.

Un 500 no es un detalle de forma: dice «el servidor está roto», sale en rojo en
la consola de cualquiera que abra la aplicación, dispara las alertas de
operación y esconde los 500 de verdad entre el ruido. Y el peor detalle es que
la respuesta dependía del **orden de los parámetros** del endpoint: declarando
`principal` antes que `db` salía 401, y al revés salía 500.
"""

from __future__ import annotations

import pytest
from crmcore.errors import NoAutenticado
from crmcore.http.deps import ANONIMO, get_db


def test_una_peticion_sin_identidad_no_abre_sesion_de_base() -> None:
    with pytest.raises(NoAutenticado) as fallo:
        next(get_db(ANONIMO))
    assert fallo.value.error_code == "auth.requerida"


def test_el_orden_de_los_parametros_ya_no_decide_la_respuesta() -> None:
    """Las dos formas de escribir la firma dan lo mismo.

    Es lo que hacía que el fallo pasara desapercibido: casi todos los endpoints
    ponen `principal` primero y contestaban bien; los pocos que ponían `db`
    primero contestaban 500, y no había forma de saber cuáles sin probarlos.
    """
    from crmcore.http.deps import exige_autenticacion

    with pytest.raises(NoAutenticado):
        exige_autenticacion(ANONIMO)
    with pytest.raises(NoAutenticado):
        next(get_db(ANONIMO))
