"""Lo que acompaña a una operación no puede tumbarla. Ni siquiera fallando.

**Un `try/except` alrededor no basta, y esa es la trampa.** Cuando lo de dentro
escribe en la MISMA sesión, un fallo de la base la deja envenenada: SQLAlchemy la
marca como necesitada de `rollback`, así que la siguiente instrucción —la de la
operación de verdad— muere con `PendingRollbackError`. El `except` atrapa el
primer error, escribe su aviso tranquilizador, y la petición se cae igual unas
líneas más abajo con un mensaje que no menciona la causa.

Ya había mordido antes: el comentario de `metamodelo.anotar_uso` dice «el alta se
caía por culpa de una estadística, que es exactamente lo que el `try` pretendía
impedir — y no lo impedía». Se arregló el orden del `flush` y el agujero siguió.

Estas pruebas van contra Postgres a propósito. Con SQLite el fallo no se
reproduce igual, y una prueba que pasa por no llegar al caso es peor que no
tenerla.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from crmcore.db.al_margen import al_margen
from sqlalchemy import text


@pytest.mark.db
def test_lo_principal_sobrevive_a_un_fallo_al_margen(db: Any, tenant_id: UUID) -> None:
    """El caso entero: algo al margen revienta y la operación sigue.

    Sin el SAVEPOINT, el `INSERT` de después muere con `PendingRollbackError` y
    lo que se ve es que falló la operación, no la estadística.
    """
    db.execute(text("CREATE TEMP TABLE prueba_principal (id int primary key)"))
    db.execute(text("INSERT INTO prueba_principal (id) VALUES (1)"))

    with al_margen(db, "prueba.al_margen_fallido"):
        # Choca contra la clave primaria: un fallo de la base, no de Python.
        db.execute(text("INSERT INTO prueba_principal (id) VALUES (1)"))

    # Y la sesión sigue viva: esto es lo que antes moría.
    db.execute(text("INSERT INTO prueba_principal (id) VALUES (2)"))
    total = db.execute(text("SELECT count(*) FROM prueba_principal")).scalar_one()
    assert total == 2, "la operación de después no llegó a ejecutarse"


@pytest.mark.db
def test_lo_que_no_falla_se_guarda(db: Any) -> None:
    """El SAVEPOINT no es un `rollback` disfrazado: lo que sale bien, se queda."""
    db.execute(text("CREATE TEMP TABLE prueba_ok (id int primary key)"))
    with al_margen(db, "prueba.no_deberia_fallar"):
        db.execute(text("INSERT INTO prueba_ok (id) VALUES (7)"))
    assert db.execute(text("SELECT count(*) FROM prueba_ok")).scalar_one() == 1


@pytest.mark.db
def test_un_fallo_de_python_tampoco_se_propaga(db: Any) -> None:
    """No solo los de la base: cualquier excepción se queda dentro."""
    db.execute(text("CREATE TEMP TABLE prueba_py (id int primary key)"))
    with al_margen(db, "prueba.error_de_python"):
        raise ValueError("algo se rompió al calcular la estadística")
    db.execute(text("INSERT INTO prueba_py (id) VALUES (1)"))
    assert db.execute(text("SELECT count(*) FROM prueba_py")).scalar_one() == 1
