"""El motor de transformación dice lo que aparta y no traga funciones inventadas
(CRM-00.03.04.04).

Medido el 09-11-2026 desde la pantalla, con una conexión a un JSON local de
cuatro registros: «Probar la conectividad» decía «2 registros» —dos no pasaban
la validación y no lo decía nadie—, invocar devolvía los dos buenos sin los
apartados, y una operación con `mayuscuals` se guardaba sin queja.
"""

from __future__ import annotations

import pytest
from crmcore.errors import ErrorValidacion

from services.integration import conector

OPERACION = {
    "mapeo": {"nombre": "nombre", "estado": "estado"},
    "transformar": {
        "nombre": ["recortar", "mayusculas"],
        "estado": [{"f": "mapa", "arg": {"A": "activo"}}],
    },
    "validar": {"obligatorios": ["nombre"], "admitidos": {"estado": ["activo"]}},
}

FILAS = [
    {"nombre": "  acme ", "estado": "A"},
    {"nombre": "", "estado": "A"},
    {"nombre": "Gamma", "estado": "Z"},
]


def test_probar_dice_cuantos_se_apartan_y_por_que() -> None:
    rechazos: list[dict] = []
    registros = conector.mapear(FILAS, OPERACION, rechazos=rechazos)
    assert registros == [{"nombre": "ACME", "estado": "activo"}]
    texto = conector.resumen_de_prueba({"registros": registros, "rechazados": rechazos})
    assert texto.startswith("1 registros; 2 apartados: ")
    assert "falta «nombre»" in texto
    assert "«estado» vale «Z»" in texto


def test_sin_apartados_no_se_inventa_ninguno() -> None:
    assert conector.resumen_de_prueba({"registros": [{}], "rechazados": []}) == "1 registros"


def test_una_funcion_mal_escrita_no_se_guarda() -> None:
    with pytest.raises(ErrorValidacion) as e:
        conector.exigir_funciones_conocidas({"transformar": {"nombre": ["mayuscuals"]}})
    assert e.value.error_code == "integracion.funciones_desconocidas"
    assert "mayuscuals" in str(e.value.mensaje)
    conector.exigir_funciones_conocidas(OPERACION)
