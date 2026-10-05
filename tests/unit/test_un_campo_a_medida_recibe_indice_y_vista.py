"""Un campo a medida sin índice ni vista (`CRM-00.04.03.04`).

Auditado el 05-10-2026. El metamodelo sabía crear el índice parcial de un tenant
y su vista tipada —`sincronizar_indices` y `sincronizar_vista`, las dos escritas
y probadas— y **no las llamaba nadie**. Un campo declarado por un cliente se
guardaba y se validaba, y:

  * filtrar u ordenar por él recorría la tabla entera. Eso no da un error: da
    una pantalla que tarda un poco más cada mes, hasta que alguien dice que «el
    CRM va lento» y nadie sabe por dónde empezar;
  * y la **vista tipada del tenant no existía**, mientras el motor de informes
    la nombra como entidad de respaldo cuando no hay fuente externa registrada.
    Ese camino moría con «Table with name v_oportunidad_… does not exist», que
    es el mismo fallo que ya se cazó una vez por el otro lado.

El esquema llega por el bus a los catorce servicios y sólo el dueño de la tabla
puede crear su índice. Por eso hay un registro objeto → tabla **por proceso**,
que apuntan solos los montadores de listado y de ficha.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from crmcore import metamodelo as mm
from sqlalchemy import text


def _tabla(db: Any) -> str:
    """Una tabla con `campos` JSONB, que es como guardan los campos a medida
    todas las entidades del producto (`EntidadBase.campos`).

    Se crea aquí en vez de usar una del esquema: la prueba mide el DDL que se
    genera, no la tabla concreta, y atarla a una real haría que un cambio en
    esa tabla rompiera una prueba que no habla de ella.
    """
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS tabla_con_campos ("
            "  id uuid PRIMARY KEY, tenant_id uuid NOT NULL,"
            "  created_at timestamptz, updated_at timestamptz,"
            "  campos jsonb NOT NULL DEFAULT '{}')"
        )
    )
    return "tabla_con_campos"


CAMPOS = [
    {"nombre": "codigo_erp", "tipo": "texto", "indexado": True},
    {"nombre": "importe_bonus", "tipo": "numero"},
]


def test_un_objeto_que_no_es_de_este_servicio_no_se_toca(db: Any) -> None:
    """El esquema llega a los catorce y sólo el dueño crea nada. Intentarlo
    desde los otros trece sería trece intentos de tocar una tabla que no está."""
    salida = mm.aplicar_esquema_fisico(
        db, tenant_id=uuid4(), objeto="objeto_que_no_existe_aqui", campos=CAMPOS
    )
    assert salida["aplicado"] is False
    assert "no guarda" in salida["porque"]


def test_el_dueno_crea_la_vista_y_el_indice(db: Any, tenant_id: UUID) -> None:
    """**Esta es la del agujero.**"""
    mm.declarar_tabla("cosa_de_prueba", _tabla(db))
    salida = mm.aplicar_esquema_fisico(
        db, tenant_id=tenant_id, objeto="cosa_de_prueba", campos=CAMPOS
    )
    assert salida["aplicado"] is True, salida.get("porque")
    assert salida["creados"] >= 1, "no se ha creado ningún índice para el campo indexado"

    vista = mm.nombre_de_vista("cosa_de_prueba", tenant_id)
    existe = db.execute(
        text("SELECT 1 FROM pg_views WHERE viewname = :v"), {"v": vista}
    ).scalar_one_or_none()
    assert existe, f"la vista «{vista}» no existe, y el motor de informes la nombra"


def test_quitar_un_campo_retira_su_indice(db: Any, tenant_id: UUID) -> None:
    """Un índice que sobrevive al campo ocupa disco y frena cada escritura sin
    acelerar ninguna lectura: nadie consulta ya por ese campo."""
    mm.declarar_tabla("cosa_que_encoge", _tabla(db))
    mm.aplicar_esquema_fisico(db, tenant_id=tenant_id, objeto="cosa_que_encoge", campos=CAMPOS)
    # Se replica el esquema para que la vuelta siguiente sepa qué había antes.
    mm.aplicar_esquema(db, tenant_id=tenant_id, objeto="cosa_que_encoge", campos=CAMPOS, version=1)
    db.flush()
    salida = mm.aplicar_esquema_fisico(
        db, tenant_id=tenant_id, objeto="cosa_que_encoge", campos=[CAMPOS[1]]
    )
    assert salida["retirados"] >= 1, "el índice del campo quitado sigue ahí"


def test_la_vista_se_rehace_cuando_cambian_las_columnas(db: Any, tenant_id: UUID) -> None:
    """Postgres rechaza reemplazar una vista si la lista de columnas cambia, y
    quitar un campo la cambia. Fallar ahí dejaría la vista congelada en el
    esquema de antes sin que nadie se enterase."""
    mm.declarar_tabla("cosa_que_cambia", _tabla(db))
    mm.aplicar_esquema_fisico(db, tenant_id=tenant_id, objeto="cosa_que_cambia", campos=CAMPOS)
    salida = mm.aplicar_esquema_fisico(
        db, tenant_id=tenant_id, objeto="cosa_que_cambia", campos=[CAMPOS[0]]
    )
    assert salida["aplicado"] is True, salida.get("porque")


def test_un_fallo_fisico_no_tumba_la_replica_del_esquema(db: Any, tenant_id: UUID) -> None:
    """La validación con los campos nuevos es lo urgente: el consultor tiene al
    cliente delante. Un índice que no se pudo crear se reintenta en la
    publicación siguiente — lo que no se hace es callarlo."""
    mm.declarar_tabla("cosa_sin_tabla", "tabla_que_no_existe_en_ninguna_parte")
    salida = mm.aplicar_esquema_fisico(
        db, tenant_id=tenant_id, objeto="cosa_sin_tabla", campos=CAMPOS
    )
    assert salida["aplicado"] is False
    assert salida["porque"], "ha fallado en silencio"


def test_cada_servicio_declara_las_tablas_de_sus_objetos() -> None:
    """Sin el registro, el esquema físico no se aplica en ninguna parte: el
    evento llega a los catorce y ninguno sabe qué tabla es la suya."""
    import importlib
    import os

    from crmcore.config import limpiar_cache_settings

    previo = os.environ.get("SERVICE_NAME")
    os.environ["SERVICE_NAME"] = "party"
    limpiar_cache_settings()
    try:
        importlib.import_module("services.party.main")
        declaradas = mm.tablas_declaradas()
    finally:
        if previo is None:
            os.environ.pop("SERVICE_NAME", None)
        else:
            os.environ["SERVICE_NAME"] = previo
        limpiar_cache_settings()

    # Las dos que más campos a medida reciben de un cliente.
    assert declaradas.get("cuenta") == "cuentas"
    assert declaradas.get("contacto") == "contactos"
