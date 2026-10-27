"""Los vocabularios de negocio los decide el cliente (CRM-07.01.01.03).

Un motivo de pérdida no es un estado de protocolo: es la forma que tiene una
empresa de contar por qué pierde. Escritos como una constante, los nueve que
trae el producto eran los nueve que iba a tener siempre ese cliente — y la
pantalla los enseñaba sin dejar tocar ninguno.

Lo que estas pruebas defienden:

  * Sin tocar nada valen los de fábrica, para que una instalación nueva pueda
    cerrar una oportunidad desde el primer día.
  * Tocar uno **no pierde el resto**, que es el fallo clásico de este patrón.
  * Lo retirado deja de admitirse, pero la fila no se borra.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore import vocabulario as voc

DEFECTOS = frozenset({"precio", "plazo", "competencia"})


@pytest.fixture(autouse=True)
def _declarado() -> Any:
    voc.registrar("pruebas_motivos", DEFECTOS, etiqueta="Motivos de prueba")
    yield
    voc._REGISTRO.pop("pruebas_motivos", None)


def test_sin_tocar_nada_valen_los_de_fabrica(db: Any) -> None:
    assert voc.valores(db, "pruebas_motivos") == DEFECTOS


def test_los_de_fabrica_se_marcan_como_tales(db: Any) -> None:
    """La pantalla necesita distinguirlos: esa diferencia es justo la que decide
    si tiene sentido tocarlos."""
    lista = voc.como_lista(db, "pruebas_motivos")

    assert len(lista) == 3
    assert all(f["de_fabrica"] for f in lista)
    # Y cada uno se identifica por su código, que es lo que llevan escrito los
    # registros que lo usan y lo único que existe antes de materializar.
    assert {f["id"] for f in lista} == DEFECTOS


def test_añadir_uno_conserva_los_de_fabrica(db: Any, tenant_id: UUID) -> None:
    """El fallo clásico: tener algo guardado es lo que apaga los defectos, así
    que sin materializar antes, añadir un valor dejaba la lista con **uno**."""
    voc.materializar(db, "pruebas_motivos", tenant_id)
    db.add(
        voc.ValorVocabulario(
            tenant_id=tenant_id,
            vocabulario="pruebas_motivos",
            valor="condiciones_de_pago",
            etiqueta="Condiciones de pago",
        )
    )
    db.flush()

    assert voc.valores(db, "pruebas_motivos") == DEFECTOS | {"condiciones_de_pago"}


def test_materializar_dos_veces_no_duplica(db: Any, tenant_id: UUID) -> None:
    voc.materializar(db, "pruebas_motivos", tenant_id)
    voc.materializar(db, "pruebas_motivos", tenant_id)

    assert len(voc.filas(db, "pruebas_motivos", incluir_inactivos=True)) == 3


def test_lo_retirado_no_se_admite_pero_no_se_borra(db: Any, tenant_id: UUID) -> None:
    """Se desactiva y no se borra: los registros que ya lo usan tienen que
    seguir enseñando su etiqueta, o el histórico queda en códigos sueltos."""
    voc.materializar(db, "pruebas_motivos", tenant_id)
    fila = next(f for f in voc.filas(db, "pruebas_motivos") if f.valor == "plazo")
    fila.activo = False
    db.flush()

    assert voc.valores(db, "pruebas_motivos") == {"precio", "competencia"}
    assert len(voc.filas(db, "pruebas_motivos", incluir_inactivos=True)) == 3


def test_un_vocabulario_que_nadie_declara_no_admite_nada(db: Any) -> None:
    """Y no revienta: un servicio puede preguntar por uno que no es suyo."""
    assert voc.valores(db, f"inventado_{uuid4().hex}") == frozenset()


# ── Un servicio no hereda los vocabularios del vecino ─────────────────────


def test_un_servicio_no_ve_los_vocabularios_de_otro(monkeypatch: Any) -> None:
    """El registro es global al proceso, y eso decidía rutas por orden de import.

    En producción da igual: cada servicio importa sus módulos y nada más. Donde
    no da igual es donde se construyen varios en el mismo proceso —el sellado
    del contrato, los gates que leen los catorce OpenAPI—. El router de
    vocabularios sólo se monta si el servicio declara alguno, y al construir en
    orden alfabético, cuando llegaba el turno de `service` y `tenancy` ya
    estaban importados los módulos de `sales`: montaban el router.

    Lo que se veía, medido el 27-10-2026: el contrato publicado anunciaba
    **doce operaciones** —`/api/v1/service/vocabularios` y
    `/api/v1/tenancy/vocabularios` con sus valores— que pedidas al servicio de
    verdad daban 404. Un contrato que anuncia lo que no existe es peor que uno
    incompleto: quien integra escribe contra ello.
    """
    from dataclasses import dataclass

    @dataclass
    class _Ajustes:
        service_name: str

    registro = dict(voc._REGISTRO)
    try:
        voc._REGISTRO.clear()
        voc._REGISTRO["motivos_perdida"] = voc.Vocabulario(
            nombre="motivos_perdida",
            etiqueta="Motivos de pérdida",
            defectos=("precio",),
            servicio="sales",
        )
        voc._REGISTRO["canales_caso"] = voc.Vocabulario(
            nombre="canales_caso",
            etiqueta="Canales",
            defectos=("correo",),
            servicio="service",
        )

        import crmcore.config as cfg

        monkeypatch.setattr(cfg, "get_settings", lambda: _Ajustes("sales"))
        assert set(voc.registrados()) == {
            "motivos_perdida"
        }, "«sales» no puede ver el vocabulario que declaró «service»"

        monkeypatch.setattr(cfg, "get_settings", lambda: _Ajustes("tenancy"))
        assert voc.registrados() == {}, (
            "«tenancy» no declara ninguno: si ve alguno, monta un router que en "
            "producción no monta, y el contrato anuncia rutas que dan 404"
        )
    finally:
        voc._REGISTRO.clear()
        voc._REGISTRO.update(registro)


def test_cada_vocabulario_sabe_quien_lo_declara() -> None:
    """De lo contrario el filtro de arriba no filtra nada y pasa siempre.

    El servicio sale del nombre del módulo que llama a `registrar`, no de un
    argumento: pedirlo obligaría a escribirlo en cada llamada, y el día que
    alguien copie una declaración de un servicio a otro se la deja puesta.
    """
    import importlib

    importlib.import_module("services.sales.servicio")
    declarados = {n: v.servicio for n, v in voc._REGISTRO.items() if n.startswith("motivos_")}
    assert declarados, "no se ve ningún vocabulario de ventas: el recorrido no mira"
    assert set(declarados.values()) == {"sales"}, declarados
