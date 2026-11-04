"""Pasar el sembrador dos veces no deja dos copias de lo mismo.

Es su contrato —«pasar el sembrador dos veces es inofensivo»— y se cumplía sólo
donde la API rechaza el duplicado con un 409. En las colecciones que **no
exigen unicidad** no choca nada: cada pasada añade una copia.

**Medido el 04-11-2026** comparando lo que el sembrador declara con lo que hay
en una instalación sembrada varias veces: diez colecciones acumulaban, y
`claves-api` tenía **128 filas para tres declaradas**. No falla nada y no avisa;
lo que pasa es que esa pantalla queda ilegible y cada copia es una credencial de
verdad.

Dos mecanismos, y los dos se prueban aquí porque los dos fallaban:

  · `crear(..., unico_por="campo")` mira antes de dar de alta.
  · `asegurar(...)` miraba DESPUÉS —creaba y sólo buscaba al chocar—, que es
    justo lo que duplica donde no hay 409. Ahora mira antes.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

RAIZ = Path(__file__).resolve().parents[2]


def _modulo() -> Any:
    spec = importlib.util.spec_from_file_location(
        "sembrar_configuracion", RAIZ / "scripts" / "sembrar_configuracion.py"
    )
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["sembrar_configuracion"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def sembrador() -> Any:
    return _modulo()


class _ApiDeMentira:
    """Una colección que NO exige unicidad: cada POST crea una fila más.

    Es el caso que duplica. Con una que sí la exige —un 409— el sembrador ya
    funcionaba, y por eso el fallo no se veía.
    """

    def __init__(self, api_real: Any) -> None:
        self.filas: list[dict] = []
        self.posts = 0
        self._api = api_real

    def llamar(self, metodo: str, ruta: str, cuerpo: Any = None):
        if metodo == "GET":
            return 200, {"items": list(self.filas)}
        self.posts += 1
        fila = {"id": f"id-{len(self.filas)}", **(cuerpo or {})}
        self.filas.append(fila)
        return 201, fila


def _api(sembrador: Any) -> Any:
    api = sembrador.Api("http://ejemplo")
    falsa = _ApiDeMentira(api)
    api._llamar = falsa.llamar  # noqa: SLF001 — es el punto de sutura del cliente
    api._mentira = falsa
    return api


def test_crear_con_unico_por_no_repite(sembrador: Any) -> None:
    api = _api(sembrador)
    cuerpo = {"nombre": "Integración con el ERP", "dias": 365}

    api.crear("/api/v1/claves-api", cuerpo, unico_por="nombre")
    api.crear("/api/v1/claves-api", cuerpo, unico_por="nombre")
    api.crear("/api/v1/claves-api", cuerpo, unico_por="nombre")

    assert api._mentira.posts == 1, "ha vuelto a dar de alta lo que ya estaba"
    assert len(api._mentira.filas) == 1
    # Y las pasadas de más cuentan como «ya existía», no como creadas: el
    # informe final tiene que decir la verdad de lo que ha hecho.
    assert api.cuenta["creados"] == 1
    assert api.cuenta["saltados"] == 2


def test_sin_unico_por_sigue_creando(sembrador: Any) -> None:
    """La otra mitad: no se vuelve idempotente todo por si acaso.

    Hay colecciones donde dos filas iguales son dos hechos distintos —dos
    movimientos de almacén del mismo repuesto—, y mirar antes ahí perdería el
    segundo. Lo dice quien llama, caso a caso.
    """
    api = _api(sembrador)
    api.crear("/api/v1/movimientos", {"nombre": "entrada"})
    api.crear("/api/v1/movimientos", {"nombre": "entrada"})
    assert api._mentira.posts == 2


def test_asegurar_mira_antes_de_crear(sembrador: Any) -> None:
    api = _api(sembrador)
    cuerpo = {"clave": "foto-planta-2026", "nombre": "Fotografía de planta"}

    primero = api.asegurar("/api/v1/activos-marketing", cuerpo)
    segundo = api.asegurar("/api/v1/activos-marketing", cuerpo)

    assert api._mentira.posts == 1, "`asegurar` ha creado una copia en la segunda pasada"
    assert primero and segundo and primero["id"] == segundo["id"], (
        "la segunda pasada tiene que devolver LA MISMA fila: todo lo que cuelga "
        "de ella se encadena con ese identificador"
    )
