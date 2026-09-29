"""Un campo personalizado llega hasta donde contecintelligence lo ve (`CRM-00.04.03.07`).

Las dos mitades estaban escritas, probadas y **no se encontraban nunca**:

- `POST /objetos/{objeto}/semantica` validaba el cuerpo, devolvía el resultado y
  no escribía nada. No había ni columna donde guardarlo. Quien declaraba la
  semántica se iba creyendo que estaba hecho y el catálogo seguía vacío.
- `GET /objetos/{objeto}/semantica` componía el contexto desde la **réplica del
  bus**, que a propósito lleva sólo lo justo para validar, filtrar e indexar.
  Con cero campos devolvía un contexto vacío de aspecto correcto; con uno solo
  reventaba con `KeyError: 'clave'`.

Las pruebas de `test_ia_aplicada.py` pasaban porque le daban a
`contexto_semantico` la salida de `describir_campo` — las dos puntas, juntas a
mano, en un sitio donde en producción no se juntan. Por eso esto va contra el
camino de verdad: se crea el campo, se declara qué significa, y se comprueba que
sale descrito por donde lo lee el de fuera.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.errors import ErrorValidacion, NoEncontrado

pytestmark = pytest.mark.db

DESCRIPCION = "En qué punto está la revisión de crédito del cliente, la rellena finanzas"


def _objeto_con_campo(
    db: Any, tenant_id: UUID, *, sensibilidad: str = "interno", tipo: str = "lista"
) -> tuple[str, str]:
    """Un objeto del tenant con un campo personalizado, por la vía normal."""
    from services.metadata.modelos import CampoDefinido, ObjetoDefinido

    objeto = f"obj_{uuid4().hex[:8]}"
    fila = ObjetoDefinido(tenant_id=tenant_id, nombre=objeto, etiqueta="Cuenta")
    db.add(fila)
    db.flush()
    campo = CampoDefinido(
        tenant_id=tenant_id,
        objeto_id=fila.id,
        nombre="cmp_2",
        etiqueta="Estado de crédito",
        tipo=tipo,
        sensibilidad=sensibilidad,
    )
    db.add(campo)
    db.flush()
    return objeto, campo.nombre


# ── Lo que se declara, se guarda ──────────────────────────────────────────


def test_lo_declarado_sigue_ahi_despues_de_contestar(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Esta es la avería: antes se validaba, se devolvía y se perdía.

    Se lee con otra llamada, no con el valor que devolvió la primera: si sólo se
    mirara lo devuelto, la prueba pasaría exactamente igual con el código roto.
    """
    from services.metadata import semantica

    objeto, nombre = _objeto_con_campo(db, tenant_id)

    semantica.declarar(
        db,
        tenant_id,
        objeto,
        nombre=nombre,
        descripcion=DESCRIPCION,
        rol="estado",
        valores=[{"valor": "C", "significa": "cliente en revisión de crédito"}],
    )

    campos = semantica.campos_descritos(db, tenant_id, objeto)
    assert [c["nombre"] for c in campos] == ["cmp_2"]
    assert (
        campos[0]["descripcion"] == DESCRIPCION
    ), f"lo declarado no sobrevivió a la llamada: {campos[0]}"
    assert campos[0]["rol"] == "estado"
    assert campos[0]["valores"] == [{"valor": "C", "significa": "cliente en revisión de crédito"}]


def test_describir_un_campo_que_no_existe_no_deja_semantica_huerfana(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Una descripción de un campo que no está no la vuelve a mirar nadie, y hace
    que la cobertura mienta hacia arriba."""
    from services.metadata import semantica

    objeto, _ = _objeto_con_campo(db, tenant_id)

    with pytest.raises(NoEncontrado) as fallo:
        semantica.declarar(
            db, tenant_id, objeto, nombre="cmp_inventado", descripcion=DESCRIPCION, rol="estado"
        )
    assert fallo.value.error_code == "metadata.campo_no_encontrado"


def test_una_descripcion_pobre_no_llega_a_guardarse(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La validación no puede quedarse en la ruta: si escribiera y luego validara,
    el catálogo acabaría con la etiqueta repetida como descripción."""
    from services.metadata import semantica

    objeto, nombre = _objeto_con_campo(db, tenant_id)

    with pytest.raises(ErrorValidacion):
        semantica.declarar(
            db, tenant_id, objeto, nombre=nombre, descripcion="Estado de crédito", rol="estado"
        )

    campos = semantica.campos_descritos(db, tenant_id, objeto)
    assert (
        campos[0]["descripcion"] == ""
    ), f"se guardó una descripción que la validación rechazó: {campos[0]}"


# ── Y sale descrito por donde lo lee el de fuera ──────────────────────────


def test_el_contexto_trae_el_campo_descrito(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El camino entero: se crea, se describe, y quien razona lo encuentra."""
    from services.metadata import semantica

    objeto, nombre = _objeto_con_campo(db, tenant_id)
    semantica.declarar(
        db,
        tenant_id,
        objeto,
        nombre=nombre,
        descripcion=DESCRIPCION,
        rol="estado",
        valores=[{"valor": "C", "significa": "cliente en revisión de crédito"}],
    )

    campos = semantica.campos_descritos(db, tenant_id, objeto)
    contexto = semantica.contexto_semantico(objeto=objeto, campos=campos)

    assert [c["nombre"] for c in contexto["campos"]] == ["cmp_2"], contexto
    assert contexto["campos"][0]["significa"] == DESCRIPCION
    assert contexto["campos"][0]["valores"] == [
        {"valor": "C", "significa": "cliente en revisión de crédito"}
    ]
    assert contexto["completo"] is True


def test_un_campo_con_tan_solo_publicarlo_no_entra_en_el_contexto(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La otra mitad, y la que reventaba.

    Un campo sin describir **no entra**, pero el contexto tiene que decirlo en
    vez de romperse o de callar: quien pregunte por él concluirá que el dato no
    existe, cuando lo que pasa es que nadie lo ha explicado.
    """
    from services.metadata import semantica

    objeto, _ = _objeto_con_campo(db, tenant_id)

    campos = semantica.campos_descritos(db, tenant_id, objeto)
    contexto = semantica.contexto_semantico(objeto=objeto, campos=campos)

    assert contexto["campos"] == []
    assert contexto["sin_describir"] == ["cmp_2"]
    assert contexto["completo"] is False
    assert "no están descritos" in contexto["aviso"]


def test_la_cobertura_se_mide_sobre_los_campos_de_verdad(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es el número que hay que enseñar antes de prometer que «la IA entiende tus
    datos». Medido sobre una lista vacía siempre saldría perfecto."""
    from services.metadata import semantica

    objeto, nombre = _objeto_con_campo(db, tenant_id)
    campos = semantica.campos_descritos(db, tenant_id, objeto)
    assert semantica.cobertura(campos=campos)["pct"] == 0.0

    semantica.declarar(db, tenant_id, objeto, nombre=nombre, descripcion=DESCRIPCION, rol="estado")
    campos = semantica.campos_descritos(db, tenant_id, objeto)
    assert semantica.cobertura(campos=campos)["pct"] == 100.0


# ── Lo sensible no sale, lo marque quien lo marque ────────────────────────


def test_un_campo_personal_no_entra_aunque_se_declare_explotable(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Esta es la puerta por la que se escapa un dato de salud.

    La sensibilidad la pone la clasificación del campo (CRM-07.03.01.05), no
    quien escribe la descripción. Si `explotable=True` bastara, cualquiera
    metería el diagnóstico de un paciente en un contexto que se manda fuera.
    """
    from services.metadata import semantica

    objeto, nombre = _objeto_con_campo(db, tenant_id, sensibilidad="especial", tipo="texto")
    semantica.declarar(
        db,
        tenant_id,
        objeto,
        nombre=nombre,
        descripcion="Diagnóstico clínico del paciente, lo rellena el personal sanitario",
        rol="texto_libre",
        explotable=True,
    )

    campos = semantica.campos_descritos(db, tenant_id, objeto)
    contexto = semantica.contexto_semantico(objeto=objeto, campos=campos)

    assert (
        contexto["campos"] == []
    ), f"un campo de categoría especial ha entrado en el contexto: {contexto}"
    assert contexto["fuera_por_sensibles"] == ["cmp_2"]


@pytest.mark.parametrize(
    ("sensibilidad", "sale"),
    [
        ("publico", True),
        ("interno", True),
        ("confidencial", False),
        ("personal", False),
        ("especial", False),
    ],
)
def test_cada_sensibilidad_decide_si_el_campo_sale(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, sensibilidad: str, sale: bool
) -> None:
    """Las cinco, no una. La clasificación es la del producto y se recorre entera:
    una sola sensibilidad probada deja las otras cuatro sin saber qué hacen."""
    from services.metadata import semantica

    objeto, nombre = _objeto_con_campo(db, tenant_id, sensibilidad=sensibilidad, tipo="texto")
    semantica.declarar(db, tenant_id, objeto, nombre=nombre, descripcion=DESCRIPCION, rol="estado")

    contexto = semantica.contexto_semantico(
        objeto=objeto, campos=semantica.campos_descritos(db, tenant_id, objeto)
    )
    assert (
        bool(contexto["campos"]) is sale
    ), f"con sensibilidad «{sensibilidad}» el campo {'no ' if sale else ''}sale: {contexto}"


def test_el_esquema_de_otro_tenant_no_se_ve(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un objeto con el mismo nombre en otro tenant no puede contestar aquí."""
    from services.metadata import semantica

    objeto, _ = _objeto_con_campo(db, tenant_id)

    with pytest.raises(NoEncontrado):
        semantica.campos_descritos(db, uuid4(), objeto)
