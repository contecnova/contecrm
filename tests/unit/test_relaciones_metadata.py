"""Relaciones entre objetos del modelo (CRM-00.04.01.03).

Lo que estas pruebas defienden: **los tipos de relación no son etiquetas**. Cada
uno impone reglas, y validarlas al declarar la relación es lo que evita
descubrirlas cuando ya hay cien mil registros — momento en el que corregirlas
deja de ser un cambio de configuración y pasa a ser una migración.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.errors import Conflicto, ErrorValidacion

from services.metadata import relaciones as rel


def _datos(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "nombre": "cuenta_contactos",
        "etiqueta": "Contactos",
        "origen": "contacto",
        "destino": "cuenta",
        "tipo": "referencia",
        "cardinalidad": "1:N",
        "al_borrar": "restringir",
        "obligatoria": False,
    }
    base.update(extra)
    return base


# ── Validación por tipo ───────────────────────────────────────────────────


def test_una_referencia_normal_es_valida() -> None:
    assert rel.validar(_datos()) == []


def test_se_devuelven_todos_los_problemas_no_el_primero() -> None:
    """Quien modela un objeto agradece ver de una vez las tres cosas que no
    encajan, en vez de corregir una, reenviar y descubrir la siguiente."""
    problemas = rel.validar(
        _datos(tipo="inventado", cardinalidad="7:3", al_borrar="explotar", origen=None)
    )
    assert len(problemas) >= 4


def test_maestro_detalle_impone_sus_tres_reglas() -> None:
    """Si se pudieran elegir, el tipo sería una etiqueta sin efecto: la
    diferencia con una referencia es justo esto."""
    problemas = rel.validar(
        _datos(
            tipo="maestro_detalle",
            cardinalidad="N:M",
            al_borrar="restringir",
            obligatoria=False,
            via="algo",
        )
    )
    assert any("siempre 1:N" in p for p in problemas)
    assert any("cascada" in p for p in problemas)
    assert any("obligatoria" in p for p in problemas)


def test_una_maestro_detalle_bien_declarada_pasa() -> None:
    assert (
        rel.validar(
            _datos(
                nombre="pedido_lineas",
                origen="linea_pedido",
                destino="pedido",
                tipo="maestro_detalle",
                cardinalidad="1:N",
                al_borrar="cascada",
                obligatoria=True,
            )
        )
        == []
    )


def test_una_jerarquica_va_de_un_objeto_a_si_mismo() -> None:
    problemas = rel.validar(
        _datos(nombre="matriz", origen="cuenta", destino="contacto", tipo="jerarquica")
    )
    assert any("a sí mismo" in p for p in problemas)


def test_una_jerarquia_no_borra_en_cascada() -> None:
    """Borrar la matriz se llevaría por delante el grupo entero sin que nadie lo
    haya pedido."""
    problemas = rel.validar(
        _datos(
            nombre="matriz",
            origen="cuenta",
            destino="cuenta",
            tipo="jerarquica",
            al_borrar="cascada",
        )
    )
    assert any("no borra en cascada" in p for p in problemas)


def test_una_jerarquia_nm_no_es_un_arbol() -> None:
    """Cada nodo tendría varios padres y consolidar por ella daría totales
    repetidos."""
    problemas = rel.validar(
        _datos(
            nombre="matriz",
            origen="cuenta",
            destino="cuenta",
            tipo="jerarquica",
            cardinalidad="N:M",
            via="enlace",
        )
    )
    assert any("no es un árbol" in p for p in problemas)


def test_una_polimorfica_necesita_varios_destinos() -> None:
    """Con uno solo es una referencia normal."""
    problemas = rel.validar(
        _datos(nombre="sobre", destino=None, destinos=["cuenta"], tipo="polimorfica")
    )
    assert any("al menos dos destinos" in p for p in problemas)


def test_una_polimorfica_no_puede_tener_destino_unico() -> None:
    problemas = rel.validar(
        _datos(nombre="sobre", destino="cuenta", destinos=["cuenta", "caso"], tipo="polimorfica")
    )
    assert any("destino único" in p for p in problemas)


def test_una_polimorfica_no_borra_en_cascada() -> None:
    """Habría que cascadear sobre tipos distintos, cada uno con sus reglas."""
    problemas = rel.validar(
        _datos(
            nombre="sobre",
            destino=None,
            destinos=["cuenta", "caso"],
            tipo="polimorfica",
            al_borrar="cascada",
        )
    )
    assert any("no puede borrar en cascada" in p for p in problemas)


def test_una_polimorfica_nm_no_se_puede_resolver() -> None:
    problemas = rel.validar(
        _datos(
            nombre="sobre",
            destino=None,
            destinos=["cuenta", "caso"],
            tipo="polimorfica",
            cardinalidad="N:M",
            via="enlace",
        )
    )
    assert any("no se puede resolver" in p for p in problemas)


def test_una_nm_necesita_objeto_intermedio() -> None:
    """Es donde viven los datos de la propia relación, como el rol de un
    contacto en una cuenta."""
    problemas = rel.validar(_datos(cardinalidad="N:M"))
    assert any("objeto intermedio" in p for p in problemas)


def test_via_solo_tiene_sentido_en_una_nm() -> None:
    problemas = rel.validar(_datos(via="enlace"))
    assert any("solo tiene sentido" in p for p in problemas)


def test_una_11_obligatoria_que_restringe_deja_los_dos_atados() -> None:
    problemas = rel.validar(_datos(cardinalidad="1:1", obligatoria=True, al_borrar="restringir"))
    assert any("atados" in p for p in problemas)


# ── Declaración ───────────────────────────────────────────────────────────


def test_declarar_una_relacion_incoherente_se_rechaza(db: Any, tenant_id: UUID) -> None:
    with pytest.raises(ErrorValidacion) as exc:
        rel.crear(db, tenant_id=tenant_id, datos=_datos(tipo="maestro_detalle"))
    assert exc.value.error_code == "metadata.relacion_incoherente"


def test_no_se_repite_el_nombre(db: Any, tenant_id: UUID) -> None:
    rel.crear(db, tenant_id=tenant_id, datos=_datos())
    with pytest.raises(Conflicto) as exc:
        rel.crear(db, tenant_id=tenant_id, datos=_datos())
    assert exc.value.error_code == "metadata.relacion_duplicada"


def test_dos_tenants_pueden_usar_el_mismo_nombre(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID
) -> None:
    rel.crear(db, tenant_id=tenant_id, datos=_datos())
    assert rel.crear(db, tenant_id=otro_tenant_id, datos=_datos()) is not None


# ── Plan de borrado ───────────────────────────────────────────────────────


def _modelo_completo(db: Any, tenant_id: UUID) -> None:
    rel.crear(db, tenant_id=tenant_id, datos=_datos())  # contacto → cuenta, restringe
    rel.crear(
        db,
        tenant_id=tenant_id,
        datos=_datos(
            nombre="lineas",
            origen="linea_pedido",
            destino="pedido",
            tipo="maestro_detalle",
            al_borrar="cascada",
            obligatoria=True,
        ),
    )
    rel.crear(
        db,
        tenant_id=tenant_id,
        datos=_datos(
            nombre="actividades", origen="actividad", destino="cuenta", al_borrar="desvincular"
        ),
    )
    db.flush()


def test_el_plan_dice_que_arrastra_y_que_impide(db: Any, tenant_id: UUID) -> None:
    _modelo_completo(db, tenant_id)

    plan = rel.plan_de_borrado(db, tenant_id=tenant_id, objeto="cuenta")

    efectos = {p.objeto: p.efecto for p in plan}
    assert efectos == {"contacto": "impide", "actividad": "desvincular"}


def test_lo_que_impide_va_primero(db: Any, tenant_id: UUID) -> None:
    """Enterrarlo entre veinte cascadas hace que se lea el listado y se pase por
    alto justo lo que bloquea."""
    _modelo_completo(db, tenant_id)
    plan = rel.plan_de_borrado(db, tenant_id=tenant_id, objeto="cuenta")
    assert plan[0].efecto == "impide"


def test_una_maestro_detalle_sale_como_cascada(db: Any, tenant_id: UUID) -> None:
    _modelo_completo(db, tenant_id)
    plan = rel.plan_de_borrado(db, tenant_id=tenant_id, objeto="pedido")
    assert [p.efecto for p in plan] == ["cascada"]


def test_una_polimorfica_cuenta_para_todos_sus_destinos(db: Any, tenant_id: UUID) -> None:
    rel.crear(
        db,
        tenant_id=tenant_id,
        datos=_datos(
            nombre="adjunto_sobre",
            origen="adjunto",
            destino=None,
            destinos=["cuenta", "caso"],
            tipo="polimorfica",
            al_borrar="desvincular",
        ),
    )
    db.flush()

    for objeto in ("cuenta", "caso"):
        plan = rel.plan_de_borrado(db, tenant_id=tenant_id, objeto=objeto)
        assert [p.objeto for p in plan] == ["adjunto"]


# ── Destinos polimórficos ─────────────────────────────────────────────────


def test_un_destino_fuera_de_los_admitidos_se_rechaza(db: Any, tenant_id: UUID) -> None:
    """Sin esto, una actividad puede acabar apuntando a un tipo que nadie previó,
    y quien recorra esas referencias se encontrará un identificador que no
    resuelve a nada."""
    relacion = rel.crear(
        db,
        tenant_id=tenant_id,
        datos=_datos(
            nombre="sobre",
            origen="actividad",
            destino=None,
            destinos=["cuenta", "oportunidad"],
            tipo="polimorfica",
            al_borrar="desvincular",
        ),
    )
    rel.validar_destino(relacion, "cuenta")
    with pytest.raises(ErrorValidacion) as exc:
        rel.validar_destino(relacion, "factura")
    assert exc.value.error_code == "metadata.destino_no_admitido"


def test_una_referencia_normal_solo_admite_su_destino(db: Any, tenant_id: UUID) -> None:
    relacion = rel.crear(db, tenant_id=tenant_id, datos=_datos())
    rel.validar_destino(relacion, "cuenta")
    with pytest.raises(ErrorValidacion):
        rel.validar_destino(relacion, "oportunidad")


# ── Ciclos en jerarquías ──────────────────────────────────────────────────


def test_un_registro_no_puede_colgar_de_si_mismo() -> None:
    uno = uuid4()
    with pytest.raises(Conflicto) as exc:
        rel.comprobar_ciclo(lambda _x: None, hijo=uno, nuevo_padre=uno)
    assert exc.value.error_code == "jerarquia.ciclo"


def test_se_detecta_un_ciclo_indirecto() -> None:
    """A cuelga de B y B de C: colgar C de A cerraría el círculo.

    Al revés —colgar A de C— **no** es un ciclo sino un reparentado, y la
    primera versión de esta prueba lo daba por ciclo. El código tenía razón.
    """
    a, b, c = uuid4(), uuid4(), uuid4()
    padres = {a: b, b: c}

    with pytest.raises(Conflicto):
        rel.comprobar_ciclo(padres.get, hijo=c, nuevo_padre=a)

    # Reparentar sí se permite: A pasa a colgar directamente de C.
    rel.comprobar_ciclo(padres.get, hijo=a, nuevo_padre=c)


def test_un_enlace_legitimo_pasa() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    padres = {b: c}
    rel.comprobar_ciclo(padres.get, hijo=a, nuevo_padre=b)


def test_un_arbol_ya_ciclado_no_cuelga_la_comprobacion() -> None:
    """Si una carga de datos se saltó esta comprobación y dejó un ciclo, subir
    por los padres no terminaría nunca: el método colgaría en vez de informar."""
    a, b = uuid4(), uuid4()
    padres = {a: b, b: a}  # ciclo ya existente

    rel.comprobar_ciclo(padres.get, hijo=uuid4(), nuevo_padre=a)


# ── Grafo ─────────────────────────────────────────────────────────────────


def test_el_grafo_enumera_objetos_y_aristas(db: Any, tenant_id: UUID) -> None:
    """Sin el grafo, una pantalla no puede ofrecer «ver los contactos de esta
    cuenta» sin que alguien lo haya programado a mano."""
    _modelo_completo(db, tenant_id)

    g = rel.grafo(db, tenant_id)

    assert set(g["objetos"]) == {"contacto", "cuenta", "linea_pedido", "pedido", "actividad"}
    assert len(g["relaciones"]) == 3
    lineas = next(r for r in g["relaciones"] if r["nombre"] == "lineas")
    assert lineas["tipo"] == "maestro_detalle"
    assert lineas["destinos"] == ["pedido"]


def test_el_grafo_de_un_tenant_no_enseña_el_de_otro(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID
) -> None:
    _modelo_completo(db, tenant_id)
    assert rel.grafo(db, otro_tenant_id)["relaciones"] == []
