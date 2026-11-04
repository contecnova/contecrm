"""Un 422 tiene que decir QUÉ campo, y decirlo en castellano.

**Medido el 03-11-2026** dando de alta un segmento desde la pantalla: falta
`definicion`, el servidor lo sabe y lo dice, y en pantalla salía «Los datos
enviados no son válidos» — sin la palabra «definición» por ninguna parte—.
Quien lo lee tiene que adivinar cuál de veintinueve campos es.

Y lo que sí viajaba por campo iba en inglés: `errors[].mensaje` era el texto
crudo de Pydantic, «Field required», dentro de un envoltorio en castellano.

Se traduce por el `type` del error —`missing`, `string_too_short`—, que es lo
estable; el texto cambia entre versiones de Pydantic y traducir por él se
rompería solo. Lo que no está traducido se devuelve tal cual: un mensaje en
inglés se entiende a medias, y ninguno no se entiende nada.
"""

from __future__ import annotations

import pytest
from crmcore.http.problems import _en_castellano


def test_lo_que_falta_se_dice_en_castellano() -> None:
    assert _en_castellano({"type": "missing", "msg": "Field required"}) == "Falta este campo"


def test_los_limites_dicen_el_limite() -> None:
    """«de 3 caracteres como poco» ayuda; «String should have at least 3
    characters» no, y además está en otro idioma."""
    dicho = _en_castellano(
        {
            "type": "string_too_short",
            "msg": "String should have at least 3 characters",
            "ctx": {"min_length": 3},
        }
    )
    assert dicho == "Tiene que tener 3 caracteres como poco"
    assert "3" in dicho, "un límite sin el número no dice nada"


@pytest.mark.parametrize(
    "tipo",
    [
        "missing",
        "int_parsing",
        "uuid_parsing",
        "datetime_parsing",
        "bool_parsing",
        "enum",
        "extra_forbidden",
        "json_invalid",
    ],
)
def test_los_motivos_corrientes_estan_traducidos(tipo: str) -> None:
    """Los que salen de verdad en un formulario. Si uno deja de estarlo, su
    inglés acaba en la pantalla de alguien."""
    dicho = _en_castellano({"type": tipo, "msg": "Something in English"})
    assert dicho != "Something in English", f"«{tipo}» sigue saliendo en inglés"
    # Y en castellano de verdad, no una cadena vacía que taparía el problema.
    assert len(dicho) > 8


def test_uno_desconocido_no_se_queda_mudo() -> None:
    """Antes que un hueco, el mensaje del validador: se entiende a medias, y
    un vacío no se entiende nada."""
    assert _en_castellano({"type": "lo_que_sea", "msg": "Unknown problem"}) == "Unknown problem"


def test_el_recorrido_mira_de_verdad() -> None:
    """Sin esto, un diccionario vacío dejaría todas las de arriba en verde
    salvo la última, y el gate parecería puesto."""
    from crmcore.http.problems import _EN_CASTELLANO

    assert len(_EN_CASTELLANO) >= 15, f"sólo hay {len(_EN_CASTELLANO)} motivos traducidos"


@pytest.mark.asyncio
async def test_la_respuesta_de_verdad_lo_usa() -> None:
    """**Por la respuesta entera, no por el traductor suelto.**

    Las de arriba llaman a `_en_castellano` directamente, así que seguían en
    verde con el envoltorio devolviendo el texto crudo otra vez: probado
    plantándolo. Lo que hay que afirmar es que **sale** en castellano, y para
    eso hay que mirar el cuerpo que se manda.
    """
    import json

    from crmcore.http.problems import manejar_validacion
    from fastapi.exceptions import RequestValidationError
    from starlette.requests import Request

    peticion = Request(
        {"type": "http", "method": "POST", "path": "/api/v1/segmentos", "headers": []}
    )
    exc = RequestValidationError(
        [{"type": "missing", "loc": ("body", "definicion"), "msg": "Field required", "input": {}}]
    )

    respuesta = await manejar_validacion(peticion, exc)
    cuerpo = json.loads(bytes(respuesta.body))

    assert cuerpo["status"] == 422
    errores = cuerpo["errors"]
    assert len(errores) == 1, errores
    # Qué campo: sin esto, quien lo lee adivina cuál de veintinueve es.
    assert errores[0]["campo"] == "definicion"
    # Y en castellano, que es lo que se escapaba.
    assert errores[0]["mensaje"] == "Falta este campo", errores[0]
