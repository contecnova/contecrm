"""Probar una tabla de decisión SIN guardarla (CRM-00.03.02.10).

El editor de tablas necesita ver qué saldría con unos datos antes de publicar
el cambio, y la API sólo evaluaba la tabla guardada: para probar había que
publicar, y publicar es lo que no se quiere hacer con una tabla que aún no se
sabe si está bien —la leen los procesos en marcha—.
"""

from __future__ import annotations

from typing import Any

import pytest
from crmcore.errors import ErrorValidacion

from services.orchestrator.api_tablas_decision import ProbarTabla, probar_tabla

TABLA: dict[str, Any] = {
    "nombre": "Quién aprueba",
    "politica": "primera",
    "entradas": [{"clave": "importe", "expresion": "@oportunidad.importe", "tipo": "numero"}],
    "salidas": [{"clave": "aprobador", "tipo": "texto"}],
    "reglas": [
        {
            "nombre": "grande",
            "condiciones": [{"entrada": "importe", "op": ">=", "valor": 50000}],
            "salidas": {"aprobador": "director"},
        },
        {"nombre": "resto", "condiciones": [], "salidas": {"aprobador": "jefe"}},
    ],
}


def test_explica_qué_regla_acertó_y_por_qué_falló_la_otra() -> None:
    salida = probar_tabla(
        ProbarTabla(tabla=TABLA, variables={"oportunidad": {"importe": 1200}})  # type: ignore[arg-type]
    )
    assert salida["salidas"] == {"aprobador": "jefe"}
    grande, resto = salida["reglas"]
    assert grande["caso"] is False
    assert grande["fallo_en"] == {
        "entrada": "importe",
        "operador": ">=",
        "esperado": 50000,
        "encontrado": 1200,
    }
    assert resto["caso"] is True


def test_una_tabla_mal_formada_dice_qué_le_falta_en_vez_de_evaluarse() -> None:
    rota = {**TABLA, "reglas": [{"nombre": "x", "condiciones": [{"entrada": "nada"}]}]}
    with pytest.raises(ErrorValidacion) as e:
        probar_tabla(ProbarTabla(tabla=rota, variables={}))  # type: ignore[arg-type]
    problemas = e.value.detalle["problemas"]  # type: ignore[index]
    assert any("nada" in p for p in problemas)


def test_la_ruta_esta_montada_en_el_servicio() -> None:
    """Que exige permiso lo vigila `test_toda_ruta_de_escritura_exige_permiso`
    sobre el árbol del código; aquí, que la puerta existe."""
    import os

    os.environ.setdefault("SERVICE_NAME", "orchestrator")
    from services.orchestrator.main import app

    assert "post" in app.openapi()["paths"]["/api/v1/tablas-decision/probar"]
