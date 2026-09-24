"""Explotación delegada: fuente, preguntas, permisos y degradación
(CRM-05.01.04).

La sección estaba construida y **sin una sola prueba**. Estas son las que
faltaban, y van detrás de lo que de verdad decide si la delegación es segura:

  * que el token lo canjee el servidor y con el rol correcto (CRM-05.01.04.01,
    CRM-05.01.04.05),
  * que el registro lleve el esquema y ni una fila (CRM-05.01.04.04),
  * que no se reenvíe lo que no ha cambiado,
  * que cuando no responde se diga qué SÍ funciona (CRM-05.01.04.08),
  * y que una pregunta a medio afinar no aparezca en la lista de todos
    (CRM-05.01.04.06).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, NoEncontrado

from services.analytics import cliente as cli
from services.analytics import fuente as fte
from services.analytics.modelos import OrganizacionExterna


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.fixture
def organizacion(db: Any, tenant_id: UUID) -> OrganizacionExterna:
    fila = OrganizacionExterna(tenant_id=tenant_id, organizacion="acme", estado="confirmada")
    db.add(fila)
    db.flush()
    return fila


# ── El rol viaja a la baja (CRM-05.01.04.05) ──────────────────────────────


def test_el_rol_se_traduce_a_la_baja() -> None:
    """Equivocarse hacia arriba en una herramienta que responde con tablas
    enteras es enseñar de una vez lo que en el CRM se ve ficha a ficha."""
    solo_lectura = cli.rol_para(frozenset({"account:read"}), False)
    administrador = cli.rol_para(frozenset({"*:*"}), True)
    assert solo_lectura != administrador


def test_sin_permisos_no_se_manda_un_rol_amplio() -> None:
    """Quien no puede leer nada en el CRM no puede preguntar por todo fuera."""
    assert cli.rol_para(frozenset(), False) == cli.rol_para(frozenset({"nada:nada"}), False)


# ── El registro de la fuente (CRM-05.01.04.04) ────────────────────────────


def test_la_descripcion_no_lleva_ni_una_fila(db: Any, tenant_id: UUID) -> None:
    """Mandar datos convertiría una descripción del esquema en una copia del CRM
    fuera de su sitio."""
    descripcion = fte.describir(db, tenant_id)
    assert descripcion["modelo"]["sin_datos"] is True
    assert "filas" not in descripcion["modelo"]
    assert "datos" not in descripcion["modelo"]


def test_la_descripcion_incluye_los_campos_del_cliente(db: Any, tenant_id: UUID) -> None:
    """Es la razón de existir del registro: un campo que el cliente añadió en su
    implantación no está en ningún esquema que contecintelligence pueda leer."""
    from crmcore import metamodelo

    metamodelo.aplicar_esquema(
        db,
        tenant_id=tenant_id,
        objeto="oportunidad",
        version=1,
        campos=[{"nombre": "canal_origen", "tipo": "texto", "etiqueta": "Canal de origen"}],
    )
    descripcion = fte.describir(db, tenant_id)
    plano = str(descripcion["modelo"])
    assert "canal_origen" in plano


def test_no_se_reenvia_lo_que_no_ha_cambiado(
    uow: UnidadDeTrabajo, organizacion: Any, monkeypatch: Any
) -> None:
    """Un registro que se reenvía por reloj gasta en cada tenant sin que nadie
    haya tocado un campo."""
    enviados: list[dict[str, Any]] = []
    monkeypatch.setattr(fte, "_publicar", lambda modelo, org, **_: enviados.append({"org": org}))
    primera = fte.registrar_fuente(uow, uow.tenant_id, organizacion="acme")
    segunda = fte.registrar_fuente(uow, uow.tenant_id, organizacion="acme")
    assert primera["registrada"] is True
    assert segunda["sin_cambios"] is True
    assert len(enviados) == 1


def test_un_campo_nuevo_obliga_a_registrar_otra_vez(
    uow: UnidadDeTrabajo, organizacion: Any, monkeypatch: Any, db: Any
) -> None:
    """Lo que importa —que el campo nuevo esté— no depende del reloj sino del
    cambio."""
    from crmcore import metamodelo

    enviados: list[Any] = []
    monkeypatch.setattr(fte, "_publicar", lambda modelo, org, **_: enviados.append(org))
    fte.registrar_fuente(uow, uow.tenant_id, organizacion="acme")
    metamodelo.aplicar_esquema(
        db,
        tenant_id=uow.tenant_id,
        objeto="cuenta",
        version=1,
        campos=[{"nombre": "segmento", "tipo": "texto", "etiqueta": "Segmento"}],
    )
    segunda = fte.registrar_fuente(uow, uow.tenant_id, organizacion="acme")
    assert segunda["registrada"] is True
    assert len(enviados) == 2


def test_un_fallo_al_registrar_queda_escrito(
    uow: UnidadDeTrabajo, organizacion: Any, monkeypatch: Any, db: Any
) -> None:
    """Sin el motivo escrito, «no se puede preguntar» no dice qué arreglar."""
    from sqlalchemy import select

    def revienta(modelo: Any, org: str, **_: Any) -> None:
        raise RuntimeError("credencial rechazada")

    monkeypatch.setattr(fte, "_publicar", revienta)
    salida = fte.registrar_fuente(uow, uow.tenant_id, organizacion="acme")
    assert salida["registrada"] is False
    fila = db.execute(select(fte.FuenteRegistrada)).scalars().one()
    assert fila.estado == "error"
    assert "credencial rechazada" in fila.error


# ── Degradación explicada (CRM-05.01.04.08) ───────────────────────────────


def test_sin_organizacion_se_dice_que_falta_la_organizacion(db: Any, tenant_id: UUID) -> None:
    salida = fte.diagnostico(db, tenant_id)
    assert salida["puede_preguntar"] is False
    assert any("organización" in p for p in salida["problemas"])


def test_el_diagnostico_dice_que_el_crm_sigue_funcionando(db: Any, tenant_id: UUID) -> None:
    """«Servicio no disponible» deja a quien lo lee creyendo que su CRM se ha
    caído. No se ha caído: lo que no funciona es preguntar."""
    salida = fte.diagnostico(db, tenant_id)
    assert salida["sigue_funcionando"]
    assert any("CRM entero" in s for s in salida["sigue_funcionando"])
    assert any("Preguntar" in s for s in salida["no_funciona"])


def test_sin_fuente_registrada_se_dice(db: Any, tenant_id: UUID, organizacion: Any) -> None:
    salida = fte.diagnostico(db, tenant_id)
    assert any("fuente consultable" in p for p in salida["problemas"])


# ── Preguntas guardadas (CRM-05.01.04.06) ─────────────────────────────────


def test_una_pregunta_nace_sin_publicar(uow: UnidadDeTrabajo) -> None:
    """Una pregunta a medio afinar que aparece en la lista de todos se usa como
    si estuviera bien, y su autor ni se entera."""
    fila = fte.guardar_pregunta(
        uow, clave="ventas-mes", titulo="Ventas del mes", pregunta="¿cuánto vendimos?"
    )
    assert fila.publicada is False


def test_la_pregunta_sin_publicar_solo_la_ve_su_autor(uow: UnidadDeTrabajo) -> None:
    yo, otro = uuid4(), uuid4()
    fte.guardar_pregunta(uow, clave="borrador", titulo="Borrador", pregunta="?", autor_id=yo)
    assert len(fte.preguntas_de(uow.db, uow.tenant_id, usuario_id=yo)) == 1
    assert fte.preguntas_de(uow.db, uow.tenant_id, usuario_id=otro) == []


def test_la_publicada_la_ve_todo_el_mundo(uow: UnidadDeTrabajo) -> None:
    fte.guardar_pregunta(
        uow, clave="buena", titulo="Buena", pregunta="?", autor_id=uuid4(), publicada=True
    )
    assert len(fte.preguntas_de(uow.db, uow.tenant_id, usuario_id=uuid4())) == 1


def test_una_publicada_acotada_a_un_rol_respeta_el_rol(uow: UnidadDeTrabajo) -> None:
    fte.guardar_pregunta(
        uow,
        clave="direccion",
        titulo="Solo dirección",
        pregunta="?",
        autor_id=uuid4(),
        publicada=True,
        roles=["direccion"],
    )
    assert fte.preguntas_de(uow.db, uow.tenant_id, roles=frozenset({"comercial"})) == []
    assert len(fte.preguntas_de(uow.db, uow.tenant_id, roles=frozenset({"direccion"}))) == 1


def test_publicar_como_informe_cierra_el_circulo(uow: UnidadDeTrabajo) -> None:
    """Sin este paso, lo que funciona vive en la cabeza de quien supo preguntar, y
    cuando se va se va con él."""
    pregunta = fte.guardar_pregunta(
        uow, clave="pipeline", titulo="Pipeline por mes", pregunta="¿cómo va el mes?"
    )
    salida = fte.publicar_como_informe(
        uow,
        pregunta.id,
        definicion={
            "objeto": "oportunidad",
            "tipo": "agrupado",
            "agrupaciones": [{"campo": "cerrada_el", "periodo": "mes"}],
            "metricas": [{"campo": "importe", "agregado": "suma", "como": "total"}],
        },
    )
    assert salida["clave"] == "pipeline"
    assert pregunta.informe_id is not None
    assert pregunta.publicada is True


def test_una_pregunta_no_se_publica_dos_veces(uow: UnidadDeTrabajo) -> None:
    pregunta = fte.guardar_pregunta(uow, clave="p", titulo="P", pregunta="?")
    definicion = {
        "objeto": "oportunidad",
        "columnas": ["nombre"],
    }
    fte.publicar_como_informe(uow, pregunta.id, definicion=definicion)
    with pytest.raises(Conflicto) as e:
        fte.publicar_como_informe(uow, pregunta.id, definicion=definicion)
    assert e.value.error_code == "analytics.pregunta_ya_publicada"


def test_publicar_una_pregunta_que_no_existe_da_404(uow: UnidadDeTrabajo) -> None:
    with pytest.raises(NoEncontrado):
        fte.publicar_como_informe(uow, uuid4(), definicion={"objeto": "cuenta"})


def test_el_uso_se_cuenta(uow: UnidadDeTrabajo) -> None:
    """Una lista de preguntas guardadas que nadie poda acaba con doscientas y
    nadie encuentra la suya."""
    pregunta = fte.guardar_pregunta(uow, clave="p", titulo="P", pregunta="?")
    fte.anotar_uso(uow.db, uow.tenant_id, pregunta.id)
    fte.anotar_uso(uow.db, uow.tenant_id, pregunta.id)
    assert pregunta.veces_usada == 2


# ── El ejecutor (CRM-05.01.04.05) ─────────────────────────────────────────


def test_un_plan_sin_token_no_sale(uow: UnidadDeTrabajo) -> None:
    """Sin token de usuario, la consulta se haría con la credencial de
    aplicación, que puede verlo todo: eso es una fuga con otro nombre."""
    from crmcore.errors import NoDisponible

    with pytest.raises(NoDisponible) as e:
        fte.ejecutar_plan(plan={"vista": "v_x", "columnas": []}, tenant_id=uow.tenant_id)
    assert e.value.error_code == "analytics.plan_sin_token"
