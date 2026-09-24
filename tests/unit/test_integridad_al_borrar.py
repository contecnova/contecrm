"""Borrar no puede dejar el sistema mintiendo (CRM-00.06.02.05).

Una lista de precios borrada con veinte ofertas colgando no desaparece de las
ofertas: sigue ahí como un identificador que ya no resuelve. Y no se nota al
borrar —el borrado va bien— sino tres semanas después, al abrir una oferta que
ya no sabe a cuánto vendía.

Lo que estas pruebas defienden:

  * Lo que otros registros usan **no se borra**, y el error dice qué y cuántos.
  * Lo que está en la papelera **no bloquea**: si bloqueara, un registro
    quedaría preso para siempre de algo que ya nadie ve.
  * Lo que no puede borrarse se puede **archivar**, que es lo que casi siempre
    se quería hacer.
  * Y las dependencias salen del modelo, no de una lista: una tabla nueva que
    apunte a esta queda protegida el día que se crea.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from crmcore.datos import integridad
from crmcore.errors import Conflicto


@pytest.fixture
def maestro_y_dependiente(db: Any, tenant_id: UUID) -> Any:
    """Dos tablas reales con una clave ajena entre ellas.

    Reales y no inventadas para la prueba: lo que se comprueba es que la regla
    sale del modelo de verdad, y con tablas de juguete se comprobaría que
    funciona sobre tablas de juguete.
    """
    from crmcore.datos.papelera import registrar_objeto

    from services.sales.modelos import AcuerdoCanal, ListaPrecio

    # Como lo declara su ficha al montarse: es de donde sale el nombre con el
    # que otras tablas la apuntan (`lista_precio_id`).
    registrar_objeto("lista_precio", ListaPrecio)
    lista = ListaPrecio(tenant_id=tenant_id, clave="t2026", nombre="Tarifa 2026", moneda="EUR")
    db.add(lista)
    db.flush()
    return lista, AcuerdoCanal


def test_lo_que_nadie_usa_se_puede_borrar(db: Any, maestro_y_dependiente: Any) -> None:
    lista, _ = maestro_y_dependiente
    assert integridad.quien_depende(db, lista) == []
    integridad.exigir_sin_dependencias(db, lista, objeto="lista_precio")


def test_lo_que_otros_usan_no_se_borra(
    db: Any, tenant_id: UUID, maestro_y_dependiente: Any
) -> None:
    lista, AcuerdoCanal = maestro_y_dependiente
    db.add(AcuerdoCanal(tenant_id=tenant_id, lista_precio_id=lista.id))
    db.flush()

    with pytest.raises(Conflicto) as fallo:
        integridad.exigir_sin_dependencias(db, lista, objeto="lista_precio")

    assert fallo.value.error_code == "integridad.referenciado"
    # El mensaje dice QUÉ y CUÁNTOS: «no se puede borrar» a secas obliga a
    # adivinar, y quien adivina va borrando dependencias hasta que le deja.
    usan = fallo.value.detalle["lo_usan"]
    assert any(u["tabla"] == "acuerdos_canal" and u["cuantos"] == 1 for u in usan), usan


def test_lo_que_esta_en_la_papelera_no_bloquea(db: Any, tenant_id: UUID) -> None:
    """Con una cuenta y sus oportunidades, que sí tienen borrado lógico.

    Si lo borrado bloqueara, un registro quedaría preso para siempre de algo
    que ya nadie ve y que nadie va a ir a purgar.
    """
    from datetime import datetime, timezone

    from crmcore.datos.papelera import registrar_objeto

    from services.party.modelos import Cuenta
    from services.sales.modelos import Etapa, Oportunidad, Pipeline

    registrar_objeto("cuenta", Cuenta)
    cuenta = Cuenta(tenant_id=tenant_id, nombre="ACME", clave_canonica="acme")
    embudo = Pipeline(tenant_id=tenant_id, clave="estandar", nombre="Estándar")
    db.add_all([cuenta, embudo])
    db.flush()
    etapa = Etapa(
        tenant_id=tenant_id, pipeline_id=embudo.id, clave="calif", nombre="Calificación", orden=1
    )
    db.add(etapa)
    db.flush()

    viva = Oportunidad(
        tenant_id=tenant_id,
        nombre="Renovación",
        cuenta_id=cuenta.id,
        pipeline_id=embudo.id,
        etapa_id=etapa.id,
    )
    db.add(viva)
    db.flush()
    assert [d.tabla for d in integridad.quien_depende(db, cuenta)] == ["oportunidades"]

    viva.deleted_at = datetime.now(timezone.utc)
    db.flush()
    assert integridad.quien_depende(db, cuenta) == []


def test_lo_que_no_se_puede_borrar_se_archiva(db: Any, maestro_y_dependiente: Any) -> None:
    lista, _ = maestro_y_dependiente
    assert integridad.se_puede_archivar(type(lista))

    integridad.archivar(lista)
    db.flush()

    assert lista.activa is False


def test_un_registro_sin_id_no_arrastra_media_base(db: Any) -> None:
    """Defensa de borde: sin identificador no hay a qué apuntar, y contar
    igualmente habría recorrido todas las tablas para nada."""

    class SinId:
        pass

    assert integridad.quien_depende(db, SinId()) == []


def test_las_dependencias_salen_del_modelo(db: Any) -> None:
    """Y no de una lista escrita a mano, que protege lo que alguien recordó."""
    from crmcore.datos.papelera import registrar_objeto

    from services.sales.modelos import ListaPrecio

    registrar_objeto("lista_precio", ListaPrecio)
    apuntan = {m.__table__.name for m, _ in integridad._tablas_que_apuntan(ListaPrecio)}
    assert "acuerdos_canal" in apuntan, apuntan
    # Las líneas SÍ cuelgan de la lista con `ON DELETE CASCADE`, y por eso no
    # cuentan: son parte de ella, no algo de fuera que la use.
    assert "reglas_precio" not in apuntan, apuntan
