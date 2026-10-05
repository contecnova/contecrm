"""El modo solo lectura existía en la página de estado y no en el sistema
(`CRM-08.01.01.06`).

Medido el 05-10-2026. `resiliencia.exigir_escritura` estaba escrita, probada y
**sin que la llamara nadie**; `entrar_en_solo_lectura` tampoco tenía llamante.
O sea: se podía declarar el modo degradado, la página de estado lo enseñaba, y
las escrituras seguían pasando.

Lo que eso cuesta es justo lo que el modo existe para evitar: durante una avería
de la base primaria, en vez de «no se puede guardar ahora, tus datos están ahí»,
el usuario recibe errores de escritura a medias y vuelve a intentarlo cambiando
lo que escribió.

Se aplica en la **unidad de trabajo**, que es por donde pasan todas las
escrituras. Ruta a ruta sería «funciona donde alguien se acordó», y durante un
incidente la que falta es la que escribe.
"""

from __future__ import annotations

import ast
import inspect

import pytest
from crmcore import resiliencia
from crmcore.errors import ErrorValidacion, NoDisponible


@pytest.fixture(autouse=True)
def _limpio() -> None:
    resiliencia.salir_de_solo_lectura()
    yield
    resiliencia.salir_de_solo_lectura()


def test_en_modo_solo_lectura_la_escritura_se_corta() -> None:
    resiliencia.entrar_en_solo_lectura("base primaria caída")
    with pytest.raises(NoDisponible) as fallo:
        resiliencia.exigir_escritura()
    assert fallo.value.error_code == "resiliencia.solo_lectura"
    # El motivo viaja al usuario: sin él cree que su cambio tenía algo malo.
    assert "base primaria" in fallo.value.mensaje


def test_entrar_sin_motivo_no_se_admite() -> None:
    """El mensaje que vería el usuario sería «modo solo lectura: », que es peor
    que no decir nada."""
    with pytest.raises(ErrorValidacion) as fallo:
        resiliencia.entrar_en_solo_lectura("   ")
    assert fallo.value.error_code == "resiliencia.solo_lectura_sin_motivo"
    assert resiliencia.en_solo_lectura() is False


def test_salir_devuelve_la_escritura() -> None:
    resiliencia.entrar_en_solo_lectura("mantenimiento")
    resiliencia.salir_de_solo_lectura()
    resiliencia.exigir_escritura()  # no lanza


def test_la_unidad_de_trabajo_lo_aplica() -> None:
    """**Esta es la del agujero.**

    En la unidad de trabajo y no ruta a ruta: es por donde pasan todas las
    escrituras, y la ruta en la que alguien se olvide durante una incidencia es
    siempre la que escribe.
    """
    from crmcore.http import deps

    arbol = ast.parse(inspect.getsource(deps.get_uow))
    llama = any(
        isinstance(n, ast.Call) and getattr(n.func, "id", "") == "exigir_escritura"
        for n in ast.walk(arbol)
    )
    assert llama, "la unidad de trabajo ya no comprueba el modo solo lectura"


def test_la_lectura_sigue_funcionando() -> None:
    """Es lo que separa «no se puede guardar» de «el CRM no funciona»: con
    lectura, el comercial que está delante de un cliente sigue viendo su ficha."""
    from crmcore.http import deps

    arbol = ast.parse(inspect.getsource(deps.get_db))
    llama = any(
        isinstance(n, ast.Call) and getattr(n.func, "id", "") == "exigir_escritura"
        for n in ast.walk(arbol)
    )
    assert not llama, (
        "la sesión de LECTURA comprueba el modo solo lectura: eso convierte una "
        "degradación en una caída, que es lo contrario de para lo que existe"
    )
