"""Lo que escribe el sistema no sale en el formulario de edición.

El PATCH genérico de `montar_ficha` saca sus campos del modelo. Hasta el
08-11-2026 ofrecía, entre otros, el hash y el sello de tiempo de un sobre de
firma —tocarlos falsea la prueba de lo que se firmó— y el nombre completo de un
contacto, que sale de su nombre y apellidos. Se mira en el contrato que se
publica, que es de donde el front saca el formulario.
"""

from __future__ import annotations

import importlib
import os
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _devolver_el_servicio() -> Any:
    from crmcore.config import limpiar_cache_settings

    previo = os.environ.get("SERVICE_NAME")
    try:
        yield
    finally:
        if previo is None:
            os.environ.pop("SERVICE_NAME", None)
        else:
            os.environ["SERVICE_NAME"] = previo
        limpiar_cache_settings()


def _campos_editables(servicio: str, esquema: str) -> set[str]:
    from crmcore.config import limpiar_cache_settings

    os.environ["SERVICE_NAME"] = servicio
    os.environ.setdefault("BUS_BACKEND", "memoria")
    limpiar_cache_settings()
    app = importlib.import_module(f"services.{servicio}.main").app
    return set(app.openapi()["components"]["schemas"][esquema]["properties"])


@pytest.mark.parametrize(
    ("servicio", "esquema", "del_sistema", "de_una_persona"),
    [
        (
            "integration",
            "EditarSobreFirma",
            {"hash_enviado", "hash_firmado", "sello_tiempo"},
            set(),
        ),
        ("party", "EditarContacto", {"nombre_completo", "clave_canonica"}, {"nombre"}),
    ],
)
def test_el_formulario_no_ofrece_lo_que_escribe_el_sistema(
    servicio: str, esquema: str, del_sistema: set[str], de_una_persona: set[str]
) -> None:
    editables = _campos_editables(servicio, esquema)
    assert not editables & del_sistema, editables & del_sistema
    # Y no se lleva por delante lo que sí corrige una persona.
    assert de_una_persona <= editables
