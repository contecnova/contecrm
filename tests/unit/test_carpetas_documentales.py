"""Carpetas del expediente de un registro (CRM-06.01.01.05).

Una carpeta es dónde está un documento, y eso lleva consigo tres promesas que
si se rompen dejan el expediente peor que sin carpetas:

  * **La ruta nunca miente.** Es dato derivado del padre, así que cualquier
    movimiento que la deje vieja convierte la columna que se enseña en ruido.
  * **Borrar una carpeta ordena, no destruye.** Quien la borra está recogiendo;
    su contenido sube, y se le dice cuánto se movió.
  * **El árbol es del registro.** Ni una carpeta ni un adjunto pueden acabar en
    el expediente de otra ficha por pasar un identificador ajeno.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.datos.adjuntos import (
    Adjunto,
    CarpetaDocumental,
    _carpeta_profundidad_maxima,
    arbol_carpetas,
    borrar_carpeta,
    crear_carpeta,
    mover_adjunto,
    mover_carpeta,
    subir,
)
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado

OBJETO = "cuenta"


def _carpeta(db: Any, tenant_id: UUID, objeto_id: UUID, nombre: str, padre: Any = None) -> Any:
    return crear_carpeta(
        db,
        tenant_id=tenant_id,
        objeto_tipo=OBJETO,
        objeto_id=objeto_id,
        nombre=nombre,
        padre_id=padre.id if padre is not None else None,
    )


def _subir(db: Any, tenant_id: UUID, objeto_id: UUID, nombre: str, carpeta: Any = None) -> Adjunto:
    return subir(
        db,
        tenant_id=tenant_id,
        objeto_tipo=OBJETO,
        objeto_id=objeto_id,
        nombre=nombre,
        datos=nombre.encode() * 8,
        carpeta_id=carpeta.id if carpeta is not None else None,
    )


# ── La ruta ───────────────────────────────────────────────────────────────


def test_la_ruta_se_construye_desde_el_padre(db: Any, tenant_id: UUID) -> None:
    objeto = uuid4()
    contratos = _carpeta(db, tenant_id, objeto, "Contratos")
    firmados = _carpeta(db, tenant_id, objeto, "Firmados", contratos)
    y2026 = _carpeta(db, tenant_id, objeto, "2026", firmados)

    assert contratos.ruta == "Contratos"
    assert firmados.ruta == "Contratos/Firmados"
    assert y2026.ruta == "Contratos/Firmados/2026"


def test_mover_recalcula_la_rama_entera(db: Any, tenant_id: UUID) -> None:
    """Sin esto la nieta seguiría diciendo que está donde ya no está."""
    objeto = uuid4()
    contratos = _carpeta(db, tenant_id, objeto, "Contratos")
    archivo = _carpeta(db, tenant_id, objeto, "Archivo")
    firmados = _carpeta(db, tenant_id, objeto, "Firmados", contratos)
    y2026 = _carpeta(db, tenant_id, objeto, "2026", firmados)

    mover_carpeta(db, contratos.id, nuevo_padre_id=archivo.id)

    db.refresh(firmados)
    db.refresh(y2026)
    assert contratos.ruta == "Archivo/Contratos"
    assert firmados.ruta == "Archivo/Contratos/Firmados"
    assert y2026.ruta == "Archivo/Contratos/Firmados/2026"


def test_una_carpeta_no_puede_meterse_en_su_propia_rama(db: Any, tenant_id: UUID) -> None:
    """Se desconectaría del árbol y su contenido sería inalcanzable."""
    objeto = uuid4()
    padre = _carpeta(db, tenant_id, objeto, "Contratos")
    hija = _carpeta(db, tenant_id, objeto, "Firmados", padre)

    with pytest.raises(Conflicto) as e:
        mover_carpeta(db, padre.id, nuevo_padre_id=hija.id)
    assert e.value.error_code == "jerarquia.ciclo"


def test_el_nombre_no_admite_barra(db: Any, tenant_id: UUID) -> None:
    """«2026/Q1» parecería dos carpetas en cualquier sitio que pinte la ruta."""
    with pytest.raises(ErrorValidacion) as e:
        _carpeta(db, tenant_id, uuid4(), "2026/Q1")
    assert e.value.error_code == "carpeta.nombre_con_barra"


def test_dos_hermanas_no_pueden_llamarse_igual(db: Any, tenant_id: UUID) -> None:
    objeto = uuid4()
    padre = _carpeta(db, tenant_id, objeto, "Contratos")
    _carpeta(db, tenant_id, objeto, "2026", padre)
    with pytest.raises(ErrorValidacion) as e:
        _carpeta(db, tenant_id, objeto, "2026", padre)
    assert e.value.error_code == "carpeta.nombre_repetido"


def test_dos_raices_tampoco_aunque_el_padre_sea_nulo(db: Any, tenant_id: UUID) -> None:
    """En Postgres dos NULL no son iguales: la restricción de hermanas no basta."""
    objeto = uuid4()
    _carpeta(db, tenant_id, objeto, "Contratos")
    with pytest.raises(ErrorValidacion) as e:
        _carpeta(db, tenant_id, objeto, "Contratos")
    assert e.value.error_code == "carpeta.nombre_repetido"


def test_mover_a_un_sitio_donde_ya_hay_ese_nombre_se_rechaza(db: Any, tenant_id: UUID) -> None:
    objeto = uuid4()
    a = _carpeta(db, tenant_id, objeto, "A")
    b = _carpeta(db, tenant_id, objeto, "B")
    _carpeta(db, tenant_id, objeto, "2026", a)
    dentro_de_b = _carpeta(db, tenant_id, objeto, "2026", b)

    with pytest.raises(ErrorValidacion):
        mover_carpeta(db, dentro_de_b.id, nuevo_padre_id=a.id)


def test_hay_tope_de_profundidad(db: Any, tenant_id: UUID) -> None:
    """Sin tope, una rama larga genera una ruta que no cabe en la columna."""
    objeto = uuid4()
    actual = None
    for nivel in range(_carpeta_profundidad_maxima()):
        actual = _carpeta(db, tenant_id, objeto, f"n{nivel}", actual)
    with pytest.raises(ErrorValidacion) as e:
        _carpeta(db, tenant_id, objeto, "una_mas", actual)
    assert e.value.error_code == "carpeta.demasiado_profunda"


# ── Borrar ordena, no destruye ────────────────────────────────────────────


def test_borrar_una_carpeta_sube_su_contenido_y_dice_cuanto(db: Any, tenant_id: UUID) -> None:
    objeto = uuid4()
    contratos = _carpeta(db, tenant_id, objeto, "Contratos")
    uno = _subir(db, tenant_id, objeto, "marco.pdf", contratos)
    dos = _subir(db, tenant_id, objeto, "anexo.pdf", contratos)

    movidos = borrar_carpeta(db, contratos.id)

    assert movidos == 2
    db.refresh(uno)
    db.refresh(dos)
    assert uno.carpeta_id is None and dos.carpeta_id is None
    assert db.get(CarpetaDocumental, contratos.id) is None


def test_borrar_recoloca_las_hijas_con_su_ruta_al_dia(db: Any, tenant_id: UUID) -> None:
    """Cambiar el padre sin recalcular dejaba la rama apuntando a lo borrado."""
    objeto = uuid4()
    destino = _carpeta(db, tenant_id, objeto, "Archivo")
    contratos = _carpeta(db, tenant_id, objeto, "Contratos")
    firmados = _carpeta(db, tenant_id, objeto, "Firmados", contratos)
    y2026 = _carpeta(db, tenant_id, objeto, "2026", firmados)

    borrar_carpeta(db, contratos.id, mover_a=destino.id)

    db.refresh(firmados)
    db.refresh(y2026)
    assert firmados.ruta == "Archivo/Firmados"
    assert y2026.ruta == "Archivo/Firmados/2026"


def test_no_se_puede_mover_el_contenido_dentro_de_lo_que_se_borra(db: Any, tenant_id: UUID) -> None:
    objeto = uuid4()
    contratos = _carpeta(db, tenant_id, objeto, "Contratos")
    dentro = _carpeta(db, tenant_id, objeto, "Firmados", contratos)

    with pytest.raises(ErrorValidacion) as e:
        borrar_carpeta(db, contratos.id, mover_a=dentro.id)
    assert e.value.error_code == "carpeta.destino_dentro"


# ── El árbol es del registro ──────────────────────────────────────────────


def test_no_se_archiva_en_la_carpeta_de_otra_ficha(db: Any, tenant_id: UUID) -> None:
    """El documento desaparecería del sitio donde alguien lo va a buscar."""
    ajena = _carpeta(db, tenant_id, uuid4(), "Contratos")
    with pytest.raises(NoEncontrado) as e:
        _subir(db, tenant_id, uuid4(), "contrato.pdf", ajena)
    assert e.value.error_code == "carpeta.no_existe"


def test_una_carpeta_no_puede_colgar_de_otra_ficha(db: Any, tenant_id: UUID) -> None:
    ajena = _carpeta(db, tenant_id, uuid4(), "Contratos")
    with pytest.raises(NoEncontrado):
        _carpeta(db, tenant_id, uuid4(), "Firmados", ajena)


def test_mover_un_adjunto_arrastra_todas_sus_versiones(db: Any, tenant_id: UUID) -> None:
    """Dejar la v1 en un sitio y la v2 en otro parte el historial en dos."""
    objeto = uuid4()
    contratos = _carpeta(db, tenant_id, objeto, "Contratos")
    v1 = _subir(db, tenant_id, objeto, "contrato.pdf")
    v2 = subir(
        db,
        tenant_id=tenant_id,
        objeto_tipo=OBJETO,
        objeto_id=objeto,
        nombre="contrato.pdf",
        datos=b"segunda version",
        documento_id=v1.documento_id,
    )

    mover_adjunto(db, v2.id, carpeta_id=contratos.id)

    db.refresh(v1)
    db.refresh(v2)
    assert v1.carpeta_id == contratos.id
    assert v2.carpeta_id == contratos.id


def test_devolver_un_adjunto_a_la_raiz(db: Any, tenant_id: UUID) -> None:
    objeto = uuid4()
    contratos = _carpeta(db, tenant_id, objeto, "Contratos")
    doc = _subir(db, tenant_id, objeto, "contrato.pdf", contratos)

    mover_adjunto(db, doc.id, carpeta_id=None)

    db.refresh(doc)
    assert doc.carpeta_id is None


def test_el_arbol_llega_plano_ordenado_y_con_nivel(db: Any, tenant_id: UUID) -> None:
    """Anidarlo obligaría a recorrerlo entero para buscar una carpeta."""
    objeto = uuid4()
    contratos = _carpeta(db, tenant_id, objeto, "Contratos")
    _carpeta(db, tenant_id, objeto, "Firmados", contratos)
    _carpeta(db, tenant_id, objeto, "Albaranes")

    arbol = arbol_carpetas(db, objeto_tipo=OBJETO, objeto_id=objeto)

    assert [c["ruta"] for c in arbol] == ["Albaranes", "Contratos", "Contratos/Firmados"]
    assert [c["nivel"] for c in arbol] == [0, 0, 1]


def test_el_arbol_de_una_ficha_no_ensena_el_de_otra(db: Any, tenant_id: UUID) -> None:
    uno, otro = uuid4(), uuid4()
    _carpeta(db, tenant_id, uno, "Contratos")
    _carpeta(db, tenant_id, otro, "Nóminas")

    assert [c["nombre"] for c in arbol_carpetas(db, objeto_tipo=OBJETO, objeto_id=uno)] == [
        "Contratos"
    ]
