"""Un duplicado se dice, no se disfraza de avería.

Una violación de `UNIQUE` salía como 500 «Error interno. Si el problema
persiste, facilita el identificador de la petición al soporte». Quien lo lee
entiende que el sistema está roto y que no puede hacer nada, cuando lo que pasa
es que ya existe algo con ese nombre y basta con cambiarlo. En el sembrado de
una instalación ya sembrada, treinta altas repetidas se veían como treinta
caídas del servidor.

Las demás violaciones de integridad —clave ajena, `NOT NULL`— sí son fallos de
programación y siguen siendo 500: ahí quien llama no puede arreglar nada, y
darle un 409 le haría buscar el problema en sus datos.
"""

from __future__ import annotations

import pytest
from crmcore.http.problems import registrar_manejadores
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import errors as pg
from sqlalchemy.exc import IntegrityError


class _Diag:
    constraint_name = "uq_rol_nombre"


# `diag` es de solo lectura en los errores de psycopg —los rellena el driver—,
# así que para la prueba se hereda en vez de asignarlo.
class _Duplicado(pg.UniqueViolation):
    @property
    def diag(self):  # type: ignore[override]
        return _Diag()


class _ClaveAjena(pg.ForeignKeyViolation):
    @property
    def diag(self):  # type: ignore[override]
        return _Diag()


def _violacion(clase: type[Exception]) -> IntegrityError:
    return IntegrityError("INSERT …", {}, clase("duplicate key value violates unique constraint"))


@pytest.fixture
def cliente() -> TestClient:
    app = FastAPI()
    registrar_manejadores(app)

    @app.get("/repetido")
    def repetido() -> None:
        raise _violacion(_Duplicado)

    @app.get("/roto")
    def roto() -> None:
        raise _violacion(_ClaveAjena)

    return TestClient(app, raise_server_exceptions=False)


def test_un_duplicado_contesta_409_y_lo_explica(cliente: TestClient) -> None:
    respuesta = cliente.get("/repetido")
    assert respuesta.status_code == 409
    cuerpo = respuesta.json()
    assert cuerpo["code"] == "conflicto"
    assert "ya existe" in cuerpo["detail"].lower()
    # El nombre de la restricción sí, los valores no: pueden ser datos
    # personales, y el detalle de Postgres los lleva dentro.
    assert cuerpo["detalle"]["restriccion"] == "uq_rol_nombre"
    assert "duplicate key value" not in respuesta.text


def test_lo_que_no_puede_arreglar_quien_llama_sigue_siendo_500(cliente: TestClient) -> None:
    respuesta = cliente.get("/roto")
    assert respuesta.status_code == 500
