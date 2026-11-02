"""Una vista de lista guardada es de quien la guarda (CRM-07.04.03.07).

Lo que defienden estas pruebas es **una frontera de privacidad**, y es de las
que se rompen en silencio: si `listar` dejara de filtrar por propietario,
nadie vería un error — vería más vistas en el desplegable, y pensaría que
alguien se las ha compartido.

Y lo que se filtraría no es poca cosa. El NOMBRE de una vista cuenta lo que
esa persona está mirando: «Cuentas en riesgo de fuga», «Oportunidades que no
me cuadran», «Clientes de los que me voy a quejar». Eso es suyo.

Dos reglas, y las dos se prueban:

1. Cada uno ve **las compartidas del tenant y las suyas**, nunca las de otro.
2. **Compartir** con todo el tenant es otra cosa que guardar un recorte propio,
   y tiene su propio permiso. Eso se comprueba en la ruta, no aquí.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from crmcore.errors import Conflicto, NoEncontrado

from services.metadata import vistas_de_lista as vl

RECURSO = "/api/v1/accounts"


@pytest.fixture
def tres(db, tenant_id: UUID):
    """Una vista compartida, una de Ana y una de Luis."""
    ana, luis = uuid4(), uuid4()
    compartida = vl.crear(
        db,
        tenant_id=tenant_id,
        usuario_id=ana,
        recurso=RECURSO,
        nombre="Todas las cuentas",
        filtros={},
        columnas=[],
        orden=None,
        compartida=True,
        es_defecto=False,
    )
    deAna = vl.crear(
        db,
        tenant_id=tenant_id,
        usuario_id=ana,
        recurso=RECURSO,
        nombre="Las que llevo yo",
        filtros={"owner_id": "@yo"},
        columnas=["nombre"],
        orden=None,
        compartida=False,
        es_defecto=False,
    )
    deLuis = vl.crear(
        db,
        tenant_id=tenant_id,
        usuario_id=luis,
        recurso=RECURSO,
        nombre="Cuentas en riesgo de fuga",
        filtros={},
        columnas=[],
        orden=None,
        compartida=False,
        es_defecto=False,
    )
    return ana, luis, compartida, deAna, deLuis


def test_cada_uno_ve_las_suyas_y_las_del_tenant(db, tenant_id: UUID, tres) -> None:
    ana, luis, compartida, deAna, deLuis = tres

    nombresDeAna = [v.nombre for v in vl.listar(db, tenant_id, ana, RECURSO)]
    assert "Todas las cuentas" in nombresDeAna
    assert "Las que llevo yo" in nombresDeAna
    # Lo que importa: el nombre de la vista de Luis ya cuenta lo que mira.
    assert "Cuentas en riesgo de fuga" not in nombresDeAna

    nombresDeLuis = [v.nombre for v in vl.listar(db, tenant_id, luis, RECURSO)]
    assert "Cuentas en riesgo de fuga" in nombresDeLuis
    assert "Las que llevo yo" not in nombresDeLuis


def test_las_compartidas_salen_primero_y_el_orden_no_baila(db, tenant_id: UUID, tres) -> None:
    # El desplegable tiene que salir siempre igual: si el orden dependiera de
    # cuándo se creó cada una, la de arriba cambiaría de sitio entre visitas y
    # se acabaría pulsando la equivocada.
    ana = tres[0]
    unas = [v.nombre for v in vl.listar(db, tenant_id, ana, RECURSO)]
    otras = [v.nombre for v in vl.listar(db, tenant_id, ana, RECURSO)]
    assert unas == otras
    assert unas[0] == "Todas las cuentas"


def test_la_vista_de_otro_no_se_puede_tocar(db, tenant_id: UUID, tres) -> None:
    ana, _luis, _c, _a, deLuis = tres
    # 404 y no 403: un 403 sobre un identificador confirma que esa vista
    # existe, y con el nombre ya se ha filtrado lo que se quería proteger.
    with pytest.raises(NoEncontrado):
        vl._suya_o_404(db, tenant_id, ana, deLuis.id)


def test_la_de_otro_TENANT_tampoco(db, tenant_id: UUID, otro_tenant_id: UUID, tres) -> None:
    ana, _luis, compartida, _a, _l = tres
    with pytest.raises(NoEncontrado):
        vl._suya_o_404(db, otro_tenant_id, ana, compartida.id)


def test_dos_personas_pueden_llamar_igual_a_dos_recortes(db, tenant_id: UUID) -> None:
    # El nombre distingue DENTRO de su dueño. «Las mías» es el nombre que le
    # pone todo el mundo, y que el segundo no pueda usarlo sería absurdo.
    uno, otro = uuid4(), uuid4()
    for quien in (uno, otro):
        vl.crear(
            db,
            tenant_id=tenant_id,
            usuario_id=quien,
            recurso=RECURSO,
            nombre="Las mías",
            filtros={},
            columnas=[],
            orden=None,
            compartida=False,
            es_defecto=False,
        )
    assert len(vl.listar(db, tenant_id, uno, RECURSO)) == 1


def test_la_misma_persona_no_puede_repetir_nombre(db, tenant_id: UUID) -> None:
    quien = uuid4()
    for _ in range(1):
        vl.crear(
            db,
            tenant_id=tenant_id,
            usuario_id=quien,
            recurso=RECURSO,
            nombre="Las mías",
            filtros={},
            columnas=[],
            orden=None,
            compartida=False,
            es_defecto=False,
        )
    with pytest.raises(Conflicto):
        vl.crear(
            db,
            tenant_id=tenant_id,
            usuario_id=quien,
            recurso=RECURSO,
            nombre="Las mías",
            filtros={},
            columnas=[],
            orden=None,
            compartida=False,
            es_defecto=False,
        )


def test_solo_una_por_defecto(db, tenant_id: UUID) -> None:
    # Dos por defecto no es un estado válido: el listado abriría con la que
    # saliera primero, y eso cambia entre consultas.
    quien = uuid4()
    primera = vl.crear(
        db,
        tenant_id=tenant_id,
        usuario_id=quien,
        recurso=RECURSO,
        nombre="Una",
        filtros={},
        columnas=[],
        orden=None,
        compartida=False,
        es_defecto=True,
    )
    vl.crear(
        db,
        tenant_id=tenant_id,
        usuario_id=quien,
        recurso=RECURSO,
        nombre="Otra",
        filtros={},
        columnas=[],
        orden=None,
        compartida=False,
        es_defecto=True,
    )
    db.refresh(primera)
    assert primera.es_defecto is False
    porDefecto = [v.nombre for v in vl.listar(db, tenant_id, quien, RECURSO) if v.es_defecto]
    assert porDefecto == ["Otra"]
