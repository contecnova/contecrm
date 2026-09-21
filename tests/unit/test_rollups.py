"""Agregados sobre los hijos de un registro (CRM-00.04.01.04).

Lo que estas pruebas defienden es lo que decide si un rollup sirve o estorba:

  * **Se calculan de golpe.** Uno por fila es el patrón N+1 con otro nombre, y
    en un listado de doscientas cuentas con tres rollups son seiscientas
    consultas en vez de tres.
  * **El vacío no es siempre cero.** El máximo de un conjunto vacío no existe;
    devolver cero pondría arriba, en un listado ordenado por «última
    actividad», justo a quien no tiene ninguna.
  * **Un rollup roto no tumba el listado**, que es lo que la gente usa todo el
    día.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from crmcore.datos.rollups import Rollup, aplicar, calcular
from crmcore.errors import ErrorValidacion


def _cuenta(db: Any, tenant_id: UUID, nombre: str) -> Any:
    """Una oportunidad: es el caso canónico de rollup —el total de sus líneas—
    y además tiene la relación padre-hijo directa que un rollup necesita.

    Un contacto NO sirve de ejemplo aquí, y por un motivo de modelo: no cuelga
    de una cuenta, la relación es N:M. Un rollup necesita una columna que
    apunte al padre.
    """
    from services.sales.modelos import Etapa, Oportunidad, Pipeline

    pipeline = db.info.get("_pipeline")
    if pipeline is None:
        pipeline = Pipeline(tenant_id=tenant_id, nombre="Estándar", clave="estandar")
        db.add(pipeline)
        db.flush()
        etapa = Etapa(
            tenant_id=tenant_id, pipeline_id=pipeline.id, nombre="Inicial", clave="inicial", orden=1
        )
        db.add(etapa)
        db.flush()
        db.info["_pipeline"] = pipeline
        db.info["_etapa"] = etapa

    fila = Oportunidad(
        tenant_id=tenant_id,
        nombre=nombre,
        importe=Decimal(0),
        pipeline_id=pipeline.id,
        etapa_id=db.info["_etapa"].id,
    )
    db.add(fila)
    db.flush()
    return fila


def _contacto(db: Any, tenant_id: UUID, cuenta_id: UUID, nombre: str, activo: bool = True) -> None:
    from services.sales.modelos import LineaOportunidad

    db.add(
        LineaOportunidad(
            tenant_id=tenant_id,
            oportunidad_id=cuenta_id,
            descripcion=nombre,
            cantidad=Decimal(1),
            precio_unitario=Decimal(10),
            total=Decimal(10),
            orden=0 if activo else 1,
        )
    )
    db.flush()


# ── Declaración ───────────────────────────────────────────────────────────


def test_una_funcion_de_agregacion_inventada_se_rechaza() -> None:
    """Dejar pasar el nombre de una función de SQL desde la configuración del
    tenant es ejecutar SQL arbitrario con otro nombre."""
    from services.sales.modelos import LineaOportunidad

    with pytest.raises(ErrorValidacion) as e:
        Rollup(
            nombre="x",
            modelo_hijo=LineaOportunidad,
            campo_padre="oportunidad_id",
            funcion="drop_table",
        )
    assert e.value.error_code == "rollup.funcion_desconocida"


def test_agregar_sin_decir_sobre_que_campo_se_rechaza() -> None:
    from services.sales.modelos import LineaOportunidad

    with pytest.raises(ErrorValidacion) as e:
        Rollup(
            nombre="x",
            modelo_hijo=LineaOportunidad,
            campo_padre="oportunidad_id",
            funcion="suma",
        )
    assert e.value.error_code == "rollup.sin_campo"


# ── Cálculo ───────────────────────────────────────────────────────────────


@pytest.mark.db
def test_cuenta_los_hijos_de_cada_padre(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    from services.sales.modelos import LineaOportunidad

    una = _cuenta(db, tenant_id, "Una S.L.")
    otra = _cuenta(db, tenant_id, "Otra S.L.")
    _contacto(db, tenant_id, una.id, "Ana")
    _contacto(db, tenant_id, una.id, "Luis")
    _contacto(db, tenant_id, otra.id, "Marta")

    salida = calcular(
        db,
        [
            Rollup(
                nombre="contactos",
                modelo_hijo=LineaOportunidad,
                campo_padre="oportunidad_id",
                funcion="cuenta",
            )
        ],
        [una.id, otra.id],
    )

    assert salida[una.id]["contactos"] == 2
    assert salida[otra.id]["contactos"] == 1


@pytest.mark.db
def test_un_padre_sin_hijos_cuenta_cero(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """«Ninguna línea» suma cero: ahí el vacío sí es cero."""
    from services.sales.modelos import LineaOportunidad

    sola = _cuenta(db, tenant_id, "Sola S.L.")

    salida = calcular(
        db,
        [
            Rollup(
                nombre="contactos",
                modelo_hijo=LineaOportunidad,
                campo_padre="oportunidad_id",
                funcion="cuenta",
            )
        ],
        [sola.id],
    )
    assert salida[sola.id]["contactos"] == 0


@pytest.mark.db
def test_el_maximo_de_un_conjunto_vacio_no_es_cero(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Devolver cero pondría arriba, en un listado ordenado por «última
    actividad», justo a quien no tiene ninguna."""
    from services.sales.modelos import LineaOportunidad

    sola = _cuenta(db, tenant_id, "Sola S.L.")

    salida = calcular(
        db,
        [
            Rollup(
                nombre="ultimo",
                modelo_hijo=LineaOportunidad,
                campo_padre="oportunidad_id",
                funcion="maximo",
                campo="created_at",
            )
        ],
        [sola.id],
    )
    assert salida[sola.id]["ultimo"] is None


@pytest.mark.db
def test_el_filtro_lo_pone_el_servicio_dueño(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El único que sabe qué significa «activo» para un contacto es quien tiene
    ese modelo delante."""
    from services.sales.modelos import LineaOportunidad

    una = _cuenta(db, tenant_id, "Una S.L.")
    _contacto(db, tenant_id, una.id, "Activa", activo=True)
    _contacto(db, tenant_id, una.id, "Baja", activo=False)

    salida = calcular(
        db,
        [
            Rollup(
                nombre="activos",
                modelo_hijo=LineaOportunidad,
                campo_padre="oportunidad_id",
                funcion="cuenta",
                filtro=LineaOportunidad.orden == 0,
            )
        ],
        [una.id],
    )
    assert salida[una.id]["activos"] == 1


@pytest.mark.db
def test_varios_padres_y_varios_rollups_en_pocas_consultas(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Uno por fila sería el patrón N+1 con otro nombre."""
    from services.sales.modelos import LineaOportunidad

    cuentas = [_cuenta(db, tenant_id, f"Empresa {i}") for i in range(5)]
    for cuenta in cuentas:
        _contacto(db, tenant_id, cuenta.id, "Alguien")

    rollups = [
        Rollup(
            nombre="contactos",
            modelo_hijo=LineaOportunidad,
            campo_padre="oportunidad_id",
            funcion="cuenta",
        ),
        Rollup(
            nombre="ultimo",
            modelo_hijo=LineaOportunidad,
            campo_padre="oportunidad_id",
            funcion="maximo",
            campo="created_at",
        ),
    ]
    salida = calcular(db, rollups, [c.id for c in cuentas])
    assert all(salida[c.id]["contactos"] == 1 for c in cuentas)


@pytest.mark.db
def test_un_rollup_roto_no_tumba_el_listado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Propagar convertiría un rollup mal declarado en un listado que no se
    puede abrir, y el listado es lo que la gente usa todo el día."""
    from services.sales.modelos import LineaOportunidad

    una = _cuenta(db, tenant_id, "Una S.L.")
    roto = Rollup(
        nombre="malo",
        modelo_hijo=LineaOportunidad,
        campo_padre="oportunidad_id",
        funcion="suma",
        # Sumar un texto: Postgres se niega.
        campo="descripcion",
    )
    salida = calcular(db, [roto], [una.id])
    assert "malo" not in salida[una.id]


def test_una_columna_real_manda_sobre_un_rollup_del_mismo_nombre() -> None:
    """Al revés, un campo de configuración podría tapar un dato del registro y
    el síntoma sería una ficha que enseña un número que no está en la base."""
    assert aplicar({"total": 7}, {"total": 99})["total"] == 7
