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


@pytest.mark.db
def test_sobrevive_cuando_el_fallo_salta_AL_VOLCAR_lo_que_el_ORM_tenia_pendiente(
    db: Any, tenant_id: UUID
) -> None:
    """El caso que faltaba, y es el que de verdad pasa en producción.

    Las pruebas de arriba fallan **dentro** del bloque, con un `execute` que
    choca al momento: ahí el savepoint sigue activo y deshacerlo es obvio.

    Lo que hace el producto es otra cosa. `al_margen` se usa con `db.add(...)`
    —anotar el uso de un campo, guardar la versión anterior de un ajuste— y una
    fila añadida no se escribe al añadirla: se escribe cuando el savepoint se
    cierra y SQLAlchemy vuelca lo pendiente. Si choca ahí, el motor **desactiva**
    el savepoint, así que `if punto.is_active: punto.rollback()` no deshacía
    nada y la sesión quedaba envenenada para todo lo que viniera después.

    Cómo se veía, que es por lo que costó encontrarlo: en la suite completa
    caían dos o tres pruebas **de otros módulos** —las pestañas de la consola,
    en un servicio distinto en cada tanda, y el ETag de ida y vuelta— con
    `PendingRollbackError`. Sueltas pasaban todas, porque el veneno viaja por la
    conexión que comparte el arnés. Lo que se veía siempre era la víctima.
    """
    from services.intelligence.agentes import Agente

    db.add(Agente(tenant_id=tenant_id, clave="repetida", tipo="calificacion_leads"))
    db.flush()

    with al_margen(db, "prueba.falla_al_volcar"):
        # No choca aquí: `add` no escribe. Choca cuando el savepoint se cierra
        # y el motor vuelca lo pendiente contra `uq_agente_clave`.
        db.add(Agente(tenant_id=tenant_id, clave="repetida", tipo="calificacion_leads"))

    # Y la sesión sigue viva. Esto es lo que moría, arrastrando a la siguiente
    # petición —que no tenía nada que ver— con un mensaje que no la menciona.
    db.add(Agente(tenant_id=tenant_id, clave="otra", tipo="calificacion_leads"))
    db.flush()
    total = db.execute(
        text("SELECT count(*) FROM agentes_ia WHERE tenant_id = :t"), {"t": tenant_id}
    ).scalar_one()
    assert total == 2, "la operación de después no llegó a ejecutarse"


@pytest.mark.db
def test_si_no_puede_deshacer_lo_dice_en_vez_de_tranquilizar(db: Any, tenant_id: UUID) -> None:
    """El aviso tranquilizador que escondía la causa.

    Cuando el `ROLLBACK TO SAVEPOINT` **también** falla, el punto ya no existe:
    la transacción se vino abajo entera o la conexión se cayó. La sesión queda
    inservible, y seguir como si nada no salva «lo principal» —ya está muerto—:
    sólo hace que muera unas líneas más abajo con un `PendingRollbackError` que
    no nombra ni este bloque ni la causa.

    Medido el 28-10-2026: así aparecía en la suite como «fallan las pestañas de
    la consola», en un servicio distinto cada vez. Lo que impedía verlo era que
    este bloque escribía su aviso y devolvía el control.
    """

    class PuntoQueNoSePuedeDeshacer:
        """Un savepoint que ya no existe, que es el caso real."""

        is_active = False

        def commit(self) -> None:
            raise RuntimeError("la operación de dentro ha fallado")

        def rollback(self) -> None:
            raise RuntimeError('savepoint "sa_savepoint_41" does not exist')

    class SesionRota:
        def begin_nested(self) -> Any:
            return PuntoQueNoSePuedeDeshacer()

    with pytest.raises(RuntimeError, match="does not exist"):
        with al_margen(SesionRota(), "prueba.no_se_puede_deshacer"):
            raise RuntimeError("la operación de dentro ha fallado")
