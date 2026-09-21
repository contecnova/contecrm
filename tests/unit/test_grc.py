"""GRC: gobierno, riesgo y cumplimiento (CRM-07.03.02.*).

Lo que estas pruebas defienden no es el CRUD de riesgos y controles —eso lo
tiene cualquier GRC— sino las tres cosas que lo hacen distinto aquí:

  * **El control se ancla al catálogo de verdad.** Un control sobre una
    capacidad que no existe no se guarda, porque contaría en el informe de
    cobertura sin cubrir nada.
  * **El informe va en los dos sentidos.** El que nadie hace es el de vuelta:
    qué controles apuntan a capacidades que ya no existen.
  * **La evidencia la pone el sistema.** Adjuntarla a mano es como un GRC se
    queda desactualizado el segundo trimestre.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID

import pytest
from crmcore.errors import Conflicto, ErrorValidacion

from services.tenancy import grc

# Una capacidad que existe de verdad en el catálogo, y una que no.
REAL = "CRM-00.05.02.05"
INVENTADA = "CRM-99.99.99.99"


def _control(db: Any, tenant_id: UUID, **kwargs: Any) -> Any:
    base = {
        "codigo": "C-1",
        "nombre": "Revisión de accesos",
        "capacidades": [REAL],
    }
    return grc.guardar_control(db, tenant_id=tenant_id, **{**base, **kwargs})


# ── El anclaje al catálogo ────────────────────────────────────────────────


@pytest.mark.db
def test_un_control_sobre_una_capacidad_inventada_no_se_guarda(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Contaría en el informe de cobertura sin cubrir nada."""
    with pytest.raises(ErrorValidacion) as e:
        _control(db, tenant_id, capacidades=[REAL, INVENTADA])
    assert e.value.error_code == "grc.capacidad_desconocida"
    assert e.value.detalle["desconocidas"] == [INVENTADA]


@pytest.mark.db
def test_un_control_sobre_un_riesgo_que_no_existe_tampoco(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es un control huérfano presentado como tratamiento."""
    with pytest.raises(ErrorValidacion) as e:
        _control(db, tenant_id, riesgos=["R-INEXISTENTE"])
    assert e.value.error_code == "grc.riesgo_desconocido"


# ── Cobertura en los dos sentidos ─────────────────────────────────────────


@pytest.mark.db
def test_la_cobertura_dice_que_esta_cubierto_y_que_no(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    _control(db, tenant_id)
    db.flush()

    informe = grc.cobertura(db, tenant_id)

    assert informe["medible"] is True
    assert informe["con_control"] == 1
    assert REAL not in informe["capacidades_sin_control"]
    assert informe["sin_control"] == informe["capacidades"] - 1
    # Agrupado por sección: una lista de cientos de identificadores no la lee
    # nadie, y por sección se ve de un vistazo qué área está descubierta.
    assert any(d["con_control"] == 1 for d in informe["por_seccion"].values())


@pytest.mark.db
def test_la_cobertura_delata_los_controles_sobre_lo_que_ya_no_existe(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El informe al revés, que es el que nadie hace: así se detecta un control
    que lleva un año cubriendo algo que se quitó del producto."""
    from sqlalchemy import select

    _control(db, tenant_id)
    db.flush()
    # Se simula que la capacidad desaparece del catálogo escribiendo el anclaje
    # directamente: guardarlo por la vía normal lo habría impedido, que es
    # justo lo que la otra prueba comprueba.
    fila = db.execute(select(grc.Control).where(grc.Control.codigo == "C-1")).scalar_one()
    fila.capacidades = [REAL, INVENTADA]
    db.flush()

    informe = grc.cobertura(db, tenant_id)

    huerfanos = informe["controles_sobre_capacidades_inexistentes"]
    assert huerfanos == [{"control": "C-1", "capacidades": [INVENTADA]}]


@pytest.mark.db
def test_medir_solo_lo_entregado_da_un_numero_distinto(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sobre lo hecho es lo que un auditor puede comprobar hoy; sobre el
    catálogo entero es lo que queda por cubrir."""
    _control(db, tenant_id)
    db.flush()

    todo = grc.cobertura(db, tenant_id)
    hechas = grc.cobertura(db, tenant_id, solo_hechas=True)

    assert hechas["capacidades"] < todo["capacidades"]
    assert hechas["pct"] > todo["pct"]


# ── Riesgos ───────────────────────────────────────────────────────────────


@pytest.mark.db
def test_aceptar_un_riesgo_sin_residual_no_es_aceptar_es_archivar(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    with pytest.raises(ErrorValidacion) as e:
        grc.guardar_riesgo(
            db, tenant_id=tenant_id, codigo="R-1", titulo="Fuga de datos", tratamiento="aceptar"
        )
    assert e.value.error_code == "grc.aceptar_sin_residual"


@pytest.mark.db
def test_el_residual_es_lo_que_mide_si_el_control_sirvio(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    riesgo = grc.guardar_riesgo(
        db,
        tenant_id=tenant_id,
        codigo="R-1",
        titulo="Fuga de datos",
        probabilidad=4,
        impacto=5,
        residual_probabilidad=2,
        residual_impacto=5,
    )
    assert riesgo.inherente == 20
    assert riesgo.residual == 10


@pytest.mark.db
def test_un_riesgo_a_mitigar_sin_control_sale_en_lo_pendiente(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Una decisión sin ejecución: el caso que más veces sale en una auditoría."""
    grc.guardar_riesgo(db, tenant_id=tenant_id, codigo="R-1", titulo="Fuga de datos")
    db.flush()

    assert grc.vencidos(db, tenant_id)["riesgos_a_mitigar_sin_control"] == ["R-1"]

    _control(db, tenant_id, riesgos=["R-1"])
    db.flush()
    assert grc.vencidos(db, tenant_id)["riesgos_a_mitigar_sin_control"] == []


# ── Evaluaciones y evidencia ──────────────────────────────────────────────


@pytest.mark.db
def test_un_control_no_efectivo_exige_plan_de_accion(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sin esa obligación el registro se llena de controles «parciales» que
    nadie arregla, y el GRC pasa de herramienta a archivo."""
    _control(db, tenant_id)
    db.flush()
    with pytest.raises(Conflicto) as e:
        grc.evaluar_control(db, tenant_id=tenant_id, control_codigo="C-1", resultado="inefectivo")
    assert e.value.error_code == "grc.sin_plan_de_accion"


@pytest.mark.db
def test_la_proxima_evaluacion_se_calcula_de_la_frecuencia(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Una fecha escrita a mano es la primera que se queda sin poner, y así un
    control «trimestral» pasa dieciocho meses sin mirarse."""
    _control(db, tenant_id, frecuencia="mensual")
    db.flush()

    evaluacion = grc.evaluar_control(
        db, tenant_id=tenant_id, control_codigo="C-1", resultado="efectivo", fecha=date(2026, 1, 1)
    )
    assert evaluacion.proxima_at == date(2026, 1, 1) + timedelta(days=30)


@pytest.mark.db
def test_la_evidencia_la_pone_el_sistema(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Adjuntarla a mano es como un GRC se queda desactualizado el segundo
    trimestre: quien la sacaba cambia de puesto y nadie más sabe de dónde salía."""
    from crmcore.authz import politicas as pol

    pol.guardar(
        db,
        tenant_id=tenant_id,
        nombre="solo_propias",
        objeto="cuenta",
        acciones=["read"],
        condiciones=[],
        activa=True,
    )
    _control(db, tenant_id, fuente_evidencia="politicas_abac")
    db.flush()

    evaluacion = grc.evaluar_control(
        db, tenant_id=tenant_id, control_codigo="C-1", resultado="efectivo"
    )
    assert evaluacion.evidencia == {"fuente": "politicas_abac", "politicas_activas": 1}


@pytest.mark.db
def test_una_fuente_de_evidencia_que_no_se_sabe_leer_lo_dice(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Devolver un diccionario vacío parecería «no hay nada que probar»."""
    _control(db, tenant_id, fuente_evidencia="inventada")
    db.flush()

    evaluacion = grc.evaluar_control(
        db, tenant_id=tenant_id, control_codigo="C-1", resultado="efectivo"
    )
    assert "error" in evaluacion.evidencia


# ── Del marco a la capacidad, y de vuelta ─────────────────────────────────


@pytest.mark.db
def test_del_marco_normativo_a_las_capacidades_que_lo_sostienen(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    _control(db, tenant_id, marcos=[{"marco": "ISO 27001", "referencia": "A.9.2.3"}])
    db.flush()

    informe = grc.por_marco(db, tenant_id)

    control = informe["ISO 27001"]["referencias"]["A.9.2.3"]["controles"][0]
    assert control["codigo"] == "C-1"
    # Con el título de la capacidad, no solo el identificador: quien revisa un
    # control necesita saber qué cubre sin abrir otra pestaña.
    assert control["capacidades"][0]["id"] == REAL
    assert control["capacidades"][0]["titulo"]


@pytest.mark.db
def test_de_una_capacidad_a_las_obligaciones_que_responde(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El recorrido de vuelta: antes de tocar una capacidad se ve a qué
    obligaciones está respondiendo."""
    _control(db, tenant_id, marcos=[{"marco": "ISO 27001", "referencia": "A.9.2.3"}])
    db.flush()

    salida = grc.obligaciones_de(db, tenant_id, REAL)
    assert salida["sin_control"] is False
    assert salida["controles"][0]["marcos"][0]["referencia"] == "A.9.2.3"

    otra = grc.obligaciones_de(db, tenant_id, "CRM-01.01.01.01")
    assert otra["sin_control"] is True


@pytest.mark.db
def test_el_grc_de_otro_tenant_no_se_ve(
    db: Any, tenant_id: UUID, otro_tenant_id: UUID, contexto_tenant: UUID
) -> None:
    _control(db, tenant_id)
    db.flush()
    assert grc.cobertura(db, otro_tenant_id)["con_control"] == 0
