"""Importar con validación previa, y revertir una importación entera
(CRM-07.01.01.08, con los campos propios de CRM-00.04.03.08).

Lo que se defiende:

* **Simular no escribe nada** y dice qué haría con cada fila, también cuando
  una fila falla por un campo propio mal puesto.
* **Los campos propios llegan a la ficha**: el plan los separaba de la fila y
  nadie los escribía.
* **Una importación hecha se revierte entera**: lo creado a la papelera y lo
  completado a como estaba. Y lo que se ha tocado después no se pisa sin
  pedirlo — ni se revierte a medias.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from crmcore.errors import Conflicto

from services.party import administracion as admin
from services.party.modelos import Contacto, Cuenta


def _esquema(db: Any, tenant_id: UUID, objeto: str) -> None:
    from crmcore.metamodelo import EsquemaTenant

    db.add(
        EsquemaTenant(
            tenant_id=tenant_id,
            objeto=objeto,
            campos=[
                {"nombre": "zona", "etiqueta": "Zona comercial", "tipo": "texto", "activo": True}
            ],
        )
    )
    db.flush()


def _importar(
    db: Any, tenant_id: UUID, objeto: str, filas: list[dict[str, Any]], **kw: Any
) -> dict[str, Any]:
    return admin.importar_objeto(
        db,
        tenant_id=tenant_id,
        objeto=objeto,
        filas=filas,
        simular=kw.pop("simular", False),
        actualizar=kw.pop("actualizar", False),
        fichero="clientes.csv",
        **kw,
    )


@pytest.mark.db
def test_simular_no_escribe_y_dice_que_haria_con_cada_fila(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    informe = _importar(
        db,
        tenant_id,
        "cuenta",
        [{"nombre": "Alfa S.L."}, {"email": "sin-nombre@x.test", "nombre": ""}],
        simular=True,
    )
    assert db.query(Cuenta).count() == 0
    assert informe["previsualizacion"] == [{"fila": 1, "accion": "crear"}]
    assert informe["errores"][0]["fila"] == 2
    assert "importacion" not in informe


@pytest.mark.db
def test_los_campos_propios_llegan_a_la_ficha(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    _esquema(db, tenant_id, "cuenta")
    campos = admin.campos_importables(db, tenant_id, "cuenta")["campos"]
    assert {
        "nombre": "zona",
        "titulo": "Zona comercial",
        "tipo": "texto",
        "obligatorio": False,
        "propio": True,
    } in campos

    _importar(db, tenant_id, "cuenta", [{"nombre": "Beta S.L.", "zona": "Norte"}])
    cuenta = db.query(Cuenta).one()
    assert cuenta.campos["zona"] == "Norte"


@pytest.mark.db
def test_un_campo_propio_que_no_existe_falla_ya_al_simular(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Si sólo fallara al escribir, el informe previo diría «crear» de una fila
    que la carga de verdad rechazaría."""
    from crmcore.metamodelo import EsquemaTenant

    db.add(
        EsquemaTenant(
            tenant_id=tenant_id,
            objeto="cuenta",
            campos=[{"nombre": "empleados", "tipo": "numero", "activo": True}],
        )
    )
    db.flush()
    informe = _importar(
        db, tenant_id, "cuenta", [{"nombre": "Gamma", "empleados": "muchos"}], simular=True
    )
    assert informe["fallidos"] == 1
    assert not informe.get("previsualizacion")


@pytest.mark.db
def test_revertir_borra_lo_creado_y_devuelve_lo_completado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    existente = Cuenta(tenant_id=tenant_id, nombre="Delta S.L.", clave_canonica="delta")
    db.add(existente)
    db.flush()

    hecha = _importar(
        db,
        tenant_id,
        "cuenta",
        [{"nombre": "Delta S.L.", "email": "info@delta.test"}, {"nombre": "Épsilon S.A."}],
        actualizar=True,
    )
    importacion_id = UUID(hecha["importacion"]["id"])
    assert hecha["importacion"]["creados"] == 1 and hecha["importacion"]["actualizados"] == 1
    db.refresh(existente)
    assert existente.email == "info@delta.test"

    plan = admin.revertir_importacion(
        db, importacion_id, simular=True, forzar=False, por=None, motivo=""
    )
    assert (plan["borrados"], plan["restaurados"], plan["conflictos"]) == (1, 1, [])
    assert db.query(Cuenta).filter(Cuenta.deleted_at.is_(None)).count() == 2

    admin.revertir_importacion(
        db, importacion_id, simular=False, forzar=False, por=None, motivo="fichero malo"
    )
    db.refresh(existente)
    assert existente.email is None
    vivas = db.query(Cuenta).filter(Cuenta.deleted_at.is_(None)).all()
    assert [c.nombre for c in vivas] == ["Delta S.L."]
    # Y no se revierte dos veces.
    with pytest.raises(Conflicto):
        admin.revertir_importacion(
            db, importacion_id, simular=False, forzar=False, por=None, motivo="otra vez"
        )


@pytest.mark.db
def test_lo_tocado_despues_no_se_pisa_sin_pedirlo_ni_se_revierte_a_medias(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    hecha = _importar(db, tenant_id, "cuenta", [{"nombre": "Zeta"}, {"nombre": "Eta"}])
    importacion_id = UUID(hecha["importacion"]["id"])
    zeta = db.query(Cuenta).filter(Cuenta.nombre == "Zeta").one()
    zeta.telefono = "+34911000000"  # alguien la ha trabajado después
    db.flush()

    with pytest.raises(Conflicto) as exc:
        admin.revertir_importacion(
            db, importacion_id, simular=False, forzar=False, por=None, motivo="x"
        )
    assert exc.value.detalle["conflictos"][0]["campos"] == ["telefono"]
    # No ha revertido la otra: o entera, o nada.
    assert db.query(Cuenta).filter(Cuenta.deleted_at.is_(None)).count() == 2

    admin.revertir_importacion(
        db, importacion_id, simular=False, forzar=True, por=None, motivo="a sabiendas"
    )
    assert db.query(Cuenta).filter(Cuenta.deleted_at.is_(None)).count() == 0


@pytest.mark.db
def test_los_contactos_se_importan_y_se_completan_por_correo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    _esquema(db, tenant_id, "contacto")
    _importar(
        db,
        tenant_id,
        "contacto",
        [{"nombre": "Ana", "apellidos": "Pérez", "email": "Ana@X.test", "zona": "Sur"}],
    )
    contacto = db.query(Contacto).one()
    assert (contacto.email, contacto.nombre_completo, contacto.campos["zona"]) == (
        "ana@x.test",
        "Ana Pérez",
        "Sur",
    )

    _importar(
        db,
        tenant_id,
        "contacto",
        [{"nombre": "Ana", "email": "ana@x.test", "cargo": "Compras"}],
        actualizar=True,
    )
    assert db.query(Contacto).count() == 1
    db.refresh(contacto)
    assert contacto.cargo == "Compras"


@pytest.mark.db
def test_el_historial_lista_lo_importado(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    from crmcore.datos import importaciones

    _importar(db, tenant_id, "cuenta", [{"nombre": "Theta"}])
    historial = importaciones.listar(db, tenant_id)
    assert [(h["objeto"], h["fichero"], h["creados"]) for h in historial] == [
        ("cuenta", "clientes.csv", 1)
    ]
