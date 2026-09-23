"""Lo que está en la papelera no sale en los listados, sin acordarse de nada.

El borrado lógico solo funciona si nadie se olvida de filtrarlo, y hay más de
cuarenta sitios que consultan modelos con papelera. Cuarenta oportunidades de
olvidarlo, y cuando se olvida **no falla nada**: sale una fila de más. Una
plantilla borrada que se sigue ofreciendo, un canal retirado que sigue
enviando, un contacto en la papelera que reaparece en un segmento.

Así que se filtra en un solo sitio, con el mismo mecanismo que el aislamiento
por tenant. Estas pruebas comprueban las dos mitades: que esconde lo borrado en
una consulta que no lo pide, y que lo enseña donde hace falta —restaurar,
purgar y archivar miran la papelera por definición— sin que ese permiso se
escape de su bloque.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import pytest
from crmcore.datos.guard_borrados import con_borrados
from sqlalchemy import select

from services.party.modelos import Cuenta


def _cuenta(db: Any, tenant_id: UUID, nombre: str) -> Cuenta:
    fila = Cuenta(tenant_id=tenant_id, nombre=nombre, clave_canonica=nombre.lower())
    db.add(fila)
    db.flush()
    return fila


@pytest.mark.db
def test_lo_borrado_no_sale_en_una_consulta_normal(db: Any, tenant_id: UUID) -> None:
    viva = _cuenta(db, tenant_id, "Viva")
    borrada = _cuenta(db, tenant_id, "Borrada")
    borrada.deleted_at = datetime.now(timezone.utc)
    db.flush()

    # Sin un solo `where` sobre `deleted_at`: ese es justo el punto.
    nombres = {
        c.nombre for c in db.execute(select(Cuenta).where(Cuenta.tenant_id == tenant_id)).scalars()
    }
    assert "Viva" in nombres
    assert "Borrada" not in nombres

    # Y tampoco por identificador, que es por donde se cuela una ficha que
    # enseña un registro que su listado ya no lista. Se vacía antes el mapa de
    # identidad: `get` devuelve sin consultar lo que la sesión ya tiene cargado,
    # y una petición de verdad empieza con la sesión vacía.
    ids = (viva.id, borrada.id)
    db.expunge_all()
    assert db.get(Cuenta, ids[1]) is None
    assert db.get(Cuenta, ids[0]) is not None


@pytest.mark.db
def test_con_borrados_lo_enseña_y_solo_dentro_del_bloque(db: Any, tenant_id: UUID) -> None:
    borrada = _cuenta(db, tenant_id, "Para restaurar")
    borrada.deleted_at = datetime.now(timezone.utc)
    db.flush()

    borrada_id = borrada.id
    db.expunge_all()
    with con_borrados(db):
        assert db.get(Cuenta, borrada_id) is not None

    # Fuera del bloque vuelve a estar escondida: si el permiso se quedara
    # pegado a la sesión, la siguiente petición atendida por esa misma sesión
    # vería la papelera entera sin haberlo pedido.
    db.expunge_all()
    assert db.get(Cuenta, borrada_id) is None


@pytest.mark.db
def test_restaurar_desde_la_papelera_funciona_con_el_guard_puesto(db: Any, tenant_id: UUID) -> None:
    """La comprobación que importa: el guard no puede romper la restauración.

    Restaurar necesita **encontrar** un registro borrado, y el guard esconde
    justo eso. Sin la salida explícita, «Restaurar» contestaba que el registro
    ya no existía en la base.
    """
    from crmcore.datos import papelera

    cuenta = _cuenta(db, tenant_id, "Ida y vuelta")
    cuenta_id = cuenta.id
    entrada = papelera.borrar(db, cuenta, objeto="cuenta", etiqueta=cuenta.nombre)
    db.flush()
    entrada_id = entrada.id
    db.expunge_all()
    assert db.get(Cuenta, cuenta_id) is None

    papelera.restaurar(db, entrada_id, modelos={"cuenta": Cuenta})
    db.flush()
    db.expunge_all()
    recuperada = db.get(Cuenta, cuenta_id)
    assert recuperada is not None
    assert recuperada.deleted_at is None
