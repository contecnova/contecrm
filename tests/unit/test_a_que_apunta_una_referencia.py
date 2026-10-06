"""A qué puede apuntar una referencia, comprobado donde se escribe
(CRM-00.04.01.03).

Una relación polimórfica dice que una actividad puede colgar de una cuenta, de
un contacto o de una oportunidad. Lo que **no** puede es colgar de cualquier
cosa: sin esta comprobación, una referencia acaba apuntando a un tipo que nadie
previó. Y eso no falla al escribir —el valor cabe— sino meses después, cuando
alguien recorre esas referencias y se encuentra un identificador que no resuelve
a nada.

La comprobación estaba escrita, y **la última de las noventa y dos funciones sin
llamante**. El motivo era estructural y por eso aguantó tanto: vivía en el
servicio que **declara** las relaciones, y quien **escribe** los valores son los
otros doce, que no leen ese esquema. Una regla que vive donde se declara y no
donde se aplica es una regla apagada.

Así que la regla se sube al núcleo y las relaciones viajan replicadas con el
esquema del objeto, por el mismo camino que sus campos propios.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

pytestmark = pytest.mark.db


POLIMORFICA = {
    "nombre": "actividad_de",
    "tipo": "polimorfica",
    "destino": "",
    "destinos": ["cuenta", "contacto", "oportunidad"],
}
NORMAL = {"nombre": "cuenta_que_paga", "tipo": "referencia", "destino": "cuenta", "destinos": []}
SIN_ACOTAR = {"nombre": "lo_que_sea", "tipo": "referencia", "destino": "", "destinos": []}


# ── La regla, en el núcleo ────────────────────────────────────────────────


def test_un_destino_admitido_pasa() -> None:
    from crmcore.relaciones import validar_destino

    validar_destino(POLIMORFICA, "cuenta")
    validar_destino(POLIMORFICA, "oportunidad")
    validar_destino(NORMAL, "cuenta")


def test_un_destino_que_nadie_previo_se_rechaza() -> None:
    """Es el caso que esto existe para cazar, y el que no se nota al escribir."""
    from crmcore.errors import ErrorValidacion
    from crmcore.relaciones import validar_destino

    with pytest.raises(ErrorValidacion) as fallo:
        validar_destino(POLIMORFICA, "factura")
    assert fallo.value.error_code == "metadata.destino_no_admitido"
    # Y se dice a qué SÍ podía apuntar: «destino no admitido» a secas obliga a
    # ir a buscar la definición para saber qué poner.
    assert fallo.value.detalle["admitidos"] == ["cuenta", "contacto", "oportunidad"]


def test_una_referencia_normal_solo_admite_el_suyo() -> None:
    from crmcore.errors import ErrorValidacion
    from crmcore.relaciones import validar_destino

    with pytest.raises(ErrorValidacion) as fallo:
        validar_destino(NORMAL, "contacto")
    assert "apunta a «cuenta»" in str(fallo.value)


def test_sin_destino_declarado_se_admite_cualquiera() -> None:
    """**Vacío es «sin acotar», no «no admite ninguno».** Obligar a enumerar los
    destinos antes de saberlos haría que nadie declarara una relación."""
    from crmcore.relaciones import validar_destino

    validar_destino(SIN_ACOTAR, "lo_que_venga")


def test_la_relacion_de_un_campo_no_se_adivina_por_parecido() -> None:
    """Dos relaciones hacia el mismo objeto son dos cosas distintas —«cuenta que
    lo paga» y «cuenta que lo usa»— y elegir por parecido acertaría casi
    siempre, que es la peor clase de casi."""
    from crmcore.relaciones import relacion_de_campo

    relaciones = [NORMAL, {**NORMAL, "nombre": "cuenta_que_lo_usa"}]
    assert relacion_de_campo(relaciones, {"restricciones": {}}) is None
    elegida = relacion_de_campo(relaciones, {"restricciones": {"relacion": "cuenta_que_lo_usa"}})
    assert elegida is not None and elegida["nombre"] == "cuenta_que_lo_usa"


# ── Replicadas con el esquema ─────────────────────────────────────────────


def test_las_relaciones_llegan_replicadas_con_el_objeto(db: Any, tenant_id: UUID) -> None:
    """Es lo que hace posible comprobarlas donde se escribe: el servicio que
    guarda el registro no lee el esquema de quien declara las relaciones."""
    from crmcore.metamodelo import aplicar_esquema, relaciones_de

    assert relaciones_de(db, tenant_id, "actividad") == []

    aplicar_esquema(
        db,
        tenant_id=tenant_id,
        objeto="actividad",
        campos=[{"nombre": "sobre", "tipo": "lookup"}],
        version=1,
        relaciones=[POLIMORFICA],
    )
    assert relaciones_de(db, tenant_id, "actividad") == [POLIMORFICA]


def test_un_esquema_nuevo_no_se_queda_con_las_relaciones_viejas(db: Any, tenant_id: UUID) -> None:
    """Quitar un destino admitido y que siga aceptándose sería peor que no
    comprobarlo: la pantalla diría una cosa y la escritura otra."""
    from crmcore.metamodelo import aplicar_esquema, relaciones_de

    aplicar_esquema(
        db, tenant_id=tenant_id, objeto="act2", campos=[], version=1, relaciones=[POLIMORFICA]
    )
    aplicar_esquema(
        db,
        tenant_id=tenant_id,
        objeto="act2",
        campos=[],
        version=2,
        relaciones=[{**POLIMORFICA, "destinos": ["cuenta"]}],
    )
    assert relaciones_de(db, tenant_id, "act2")[0]["destinos"] == ["cuenta"]


def test_el_productor_manda_las_relaciones_del_objeto() -> None:
    """Si `metadata` no las emite no hay nada que replicar, y la comprobación se
    queda otra vez sin poder hacerse en el sitio donde sirve."""
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    fuente = (raiz / "services" / "metadata" / "publicacion.py").read_text(encoding="utf-8")
    assert '"relaciones": _relaciones_del_objeto(' in fuente
    # Y manda lo justo: el nombre, el tipo y los destinos. La cardinalidad o qué
    # pasa al borrar sólo sabe aplicarlas quien las declara.
    assert '"destinos": list(f.destinos or [])' in fuente


# ── Aplicada donde se escribe ─────────────────────────────────────────────


def _con_relacion(db: Any, tenant_id: UUID, objeto: str) -> None:
    from crmcore.metamodelo import aplicar_esquema

    aplicar_esquema(
        db,
        tenant_id=tenant_id,
        objeto=objeto,
        campos=[
            {
                "nombre": "sobre",
                "tipo": "texto",
                "restricciones": {"relacion": "actividad_de", "objeto": "factura"},
            }
        ],
        version=1,
        relaciones=[POLIMORFICA],
    )


def test_escribir_hacia_un_tipo_no_previsto_se_rechaza(db: Any, tenant_id: UUID) -> None:
    """**Es el circuito cerrado.** La regla vivía en un servicio y la escritura
    en otro, así que no se cruzaban nunca."""
    from crmcore.errors import ErrorValidacion
    from crmcore.metamodelo import validar

    _con_relacion(db, tenant_id, "act3")

    with pytest.raises(ErrorValidacion) as fallo:
        validar(db, tenant_id, "act3", {"sobre": "id-de-una-factura"})

    motivos = [e.get("motivo") for e in (fallo.value.errores or [])]
    assert "destino_no_admitido" in motivos, fallo.value.errores


def test_escribir_hacia_un_tipo_admitido_pasa(db: Any, tenant_id: UUID) -> None:
    from crmcore.metamodelo import aplicar_esquema, validar

    aplicar_esquema(
        db,
        tenant_id=tenant_id,
        objeto="act4",
        campos=[
            {
                "nombre": "sobre",
                "tipo": "texto",
                "restricciones": {"relacion": "actividad_de", "objeto": "cuenta"},
            }
        ],
        version=1,
        relaciones=[POLIMORFICA],
    )
    salida = validar(db, tenant_id, "act4", {"sobre": "id-de-una-cuenta"})
    assert salida["sobre"] == "id-de-una-cuenta"


def test_un_objeto_sin_relaciones_escribe_como_siempre(db: Any, tenant_id: UUID) -> None:
    """La mayoría no tiene ninguna. Tratarlas como «no admite nada» cortaría
    escrituras legítimas en todo el producto."""
    from crmcore.metamodelo import aplicar_esquema, validar

    aplicar_esquema(
        db,
        tenant_id=tenant_id,
        objeto="act5",
        campos=[{"nombre": "nota", "tipo": "texto"}],
        version=1,
    )
    assert validar(db, tenant_id, "act5", {"nota": "lo que sea"})["nota"] == "lo que sea"


# ── Una sola regla, en un solo sitio ──────────────────────────────────────


def test_metadata_usa_la_del_nucleo_y_no_la_suya() -> None:
    """Dos implementaciones de la misma regla divergen, y la que menos se mira
    es la que se queda corta. Ya pasó con el HMAC de las firmas."""
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    fuente = (raiz / "services" / "metadata" / "relaciones.py").read_text(encoding="utf-8")
    assert "from crmcore.relaciones import validar_destino as comprobar" in fuente
    # Y no se ha quedado una copia de la lógica aquí.
    assert "polimorfica" not in fuente.split("def validar_destino(")[1].split("def ")[0]


def test_el_adaptador_de_metadata_sigue_comprobando(db: Any, tenant_id: UUID) -> None:
    """Que la regla viva en el núcleo no puede dejar sin comprobación al propio
    servicio que declara las relaciones."""
    from crmcore.errors import ErrorValidacion

    from services.metadata.relaciones import RelacionDefinida, validar_destino

    fila = RelacionDefinida(
        tenant_id=tenant_id,
        nombre="actividad_de",
        etiqueta="Actividad de",
        origen="actividad",
        tipo="polimorfica",
        destinos=["cuenta", "contacto"],
    )
    validar_destino(fila, "cuenta")
    with pytest.raises(ErrorValidacion) as fallo:
        validar_destino(fila, "factura")
    assert fallo.value.error_code == "metadata.destino_no_admitido"


def test_ya_no_queda_ninguna_funcion_sin_llamante() -> None:
    """La sonda llegó a marcar noventa y dos. Esta era la última."""
    import importlib.util
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    ruta = raiz / "tests" / "unit" / "test_nada_escrito_y_sin_enchufar.py"
    spec = importlib.util.spec_from_file_location("sonda_", ruta)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)

    sueltas = modulo._sin_llamante()
    assert sueltas == [], f"han vuelto a aparecer funciones sin llamante: {sueltas}"
