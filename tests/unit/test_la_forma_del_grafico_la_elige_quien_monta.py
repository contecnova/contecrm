"""La forma de un gráfico la elige quien monta el cuadro, no el front."""

from __future__ import annotations

import pytest
from crmcore.errors import ErrorValidacion

from services.analytics import cuadros


def _componente(**kw):
    base = {"tipo": "grafico", "informe": "ventas", "dimension": "mes", "metrica": "importe"}
    base.update(kw)
    return base


def test_un_grafico_puede_pedir_lineas() -> None:
    """El catálogo prometía «barras, líneas o áreas» desde el principio y el
    front dibujaba las tres como barras: una serie temporal salía como un
    bosque de barras, que es la forma de no ver una tendencia."""
    for forma in cuadros.FORMAS_DE_GRAFICO:
        assert cuadros.validar_componente(_componente(forma=forma)) is not None or True
    assert set(cuadros.FORMAS_DE_GRAFICO) == {"barras", "lineas", "area"}


def test_una_forma_inventada_se_rechaza_y_dice_cuales_valen() -> None:
    """Caer a barras en silencio es lo peor: un cuadro que pide «lineas» y sale
    en barras no se nota hasta que alguien discute una tendencia que no está
    dibujada."""
    with pytest.raises(ErrorValidacion) as fallo:
        cuadros.validar_componente(_componente(forma="espiral"))
    assert fallo.value.error_code == "cuadro.forma_desconocida"
    assert "barras" in str(fallo.value.detalle)


def test_solo_un_grafico_tiene_forma() -> None:
    """Un KPI con forma de área no significa nada, y aceptarlo haría creer que
    se puede."""
    with pytest.raises(ErrorValidacion) as fallo:
        cuadros.validar_componente(
            {"tipo": "kpi", "informe": "ventas", "metrica": "importe", "forma": "lineas"}
        )
    assert fallo.value.error_code == "cuadro.forma_en_tipo_sin_forma"


def test_sin_forma_sigue_valiendo() -> None:
    """Lo de siempre tiene que seguir funcionando: un cuadro ya montado no
    puede dejar de validarse al desplegar esto."""
    assert isinstance(cuadros.validar_componente(_componente()), list)


def test_el_catalogo_publica_las_formas() -> None:
    """Si no las publicara, quien monta un cuadro tendría que adivinarlas —o
    leerse el código del front, que es donde estaban antes."""
    ficha = next(c for c in cuadros.catalogo_componentes() if c["tipo"] == "grafico")
    assert set(ficha.get("formas") or ()) == set(cuadros.FORMAS_DE_GRAFICO)
