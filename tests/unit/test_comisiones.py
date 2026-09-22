"""Incentivos y comisiones (CRM-03.02.03).

La comisión es lo único del CRM que la gente cuadra a mano todos los meses, con
una hoja de cálculo propia. Las pruebas van detrás de lo que hace que esa hoja no
cuadre:

  * el hueco entre tramos que paga cero y nadie ve,
  * el escalado que no dice si es marginal o retroactivo,
  * la liquidación que se recalcula y ya no dice lo que dijo,
  * el pago que sale con una disputa abierta,
  * y la reversión invisible que hace que nadie reconozca su nómina.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion

from services.sales import comisiones as com


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _plan(uow: UnidadDeTrabajo, **kw: Any) -> com.PlanComision:
    base: dict[str, Any] = {
        "clave": kw.pop("clave", "plan-2026"),
        "nombre": "Plan 2026",
        "desde": date(2026, 1, 1),
    }
    base.update(kw)
    return com.crear_plan(uow, **base)


def _op(id_: str, importe: Decimal, **kw: Any) -> dict[str, Any]:
    fila: dict[str, Any] = {"id": str(uuid4()), "concepto": id_, "importe": str(importe)}
    fila.update(kw)
    return fila


# ── Planes y reglas (CRM-03.02.03.01) ─────────────────────────────────────


def test_el_plan_nace_en_borrador(uow: UnidadDeTrabajo) -> None:
    assert _plan(uow).estado == "borrador"


def test_el_devengo_se_declara(uow: UnidadDeTrabajo) -> None:
    """Cierre o cobro cambia el calendario de pagos entero."""
    with pytest.raises(ErrorValidacion):
        _plan(uow, devengo="cuando_sea")


def test_un_plan_activo_ya_no_se_modifica(uow: UnidadDeTrabajo) -> None:
    """Cambiarlo en caliente haría que dos liquidaciones del mismo periodo
    salieran distintas según cuándo se calcularan."""
    plan = _plan(uow)
    com.anadir_regla(uow, plan.id, tipo="porcentaje", porcentaje=Decimal(5))
    com.activar_plan(uow, plan.id)
    with pytest.raises(Conflicto):
        com.anadir_regla(uow, plan.id, tipo="porcentaje", porcentaje=Decimal(7))


def test_el_hueco_entre_tramos_se_detecta(uow: UnidadDeTrabajo) -> None:
    """Un hueco no da error: da cero, y el que vende más cobra menos."""
    plan = _plan(uow)
    com.anadir_regla(
        uow,
        plan.id,
        tipo="escalado",
        desde_valor=Decimal(0),
        hasta_valor=Decimal(50000),
        porcentaje=Decimal(3),
    )
    com.anadir_regla(
        uow, plan.id, tipo="escalado", desde_valor=Decimal(60000), porcentaje=Decimal(5)
    )
    revision = com.revisar_plan(uow.db, uow.tenant_id, plan.id)
    assert revision["listo"] is False
    assert any("Hueco" in p for p in revision["problemas"])


def test_el_solape_entre_tramos_se_detecta(uow: UnidadDeTrabajo) -> None:
    plan = _plan(uow)
    com.anadir_regla(
        uow,
        plan.id,
        tipo="escalado",
        desde_valor=Decimal(0),
        hasta_valor=Decimal(50000),
        porcentaje=Decimal(3),
    )
    com.anadir_regla(
        uow, plan.id, tipo="escalado", desde_valor=Decimal(40000), porcentaje=Decimal(5)
    )
    revision = com.revisar_plan(uow.db, uow.tenant_id, plan.id)
    assert any("Solape" in p for p in revision["problemas"])


def test_mezclar_marginal_y_retroactivo_se_detecta(uow: UnidadDeTrabajo) -> None:
    plan = _plan(uow)
    com.anadir_regla(
        uow,
        plan.id,
        tipo="escalado",
        desde_valor=Decimal(0),
        hasta_valor=Decimal(50000),
        porcentaje=Decimal(3),
    )
    com.anadir_regla(
        uow,
        plan.id,
        tipo="escalado",
        desde_valor=Decimal(50000),
        porcentaje=Decimal(5),
        modo_tramo="retroactivo",
    )
    revision = com.revisar_plan(uow.db, uow.tenant_id, plan.id)
    assert any("marginal y retroactivo" in p for p in revision["problemas"])


def test_un_plan_sin_reglas_paga_cero_y_lo_dice(uow: UnidadDeTrabajo) -> None:
    plan = _plan(uow)
    revision = com.revisar_plan(uow.db, uow.tenant_id, plan.id)
    assert revision["listo"] is False and revision["aviso"]


def test_no_se_activa_un_plan_con_problemas_sin_forzar(uow: UnidadDeTrabajo) -> None:
    plan = _plan(uow)
    with pytest.raises(Conflicto):
        com.activar_plan(uow, plan.id)
    com.activar_plan(uow, plan.id, forzar=True)


def test_un_spiff_sin_premio_no_premia_nada(uow: UnidadDeTrabajo) -> None:
    plan = _plan(uow)
    with pytest.raises(ErrorValidacion):
        com.anadir_regla(uow, plan.id, tipo="spiff")


def test_una_asignacion_no_es_de_persona_y_partner_a_la_vez(uow: UnidadDeTrabajo) -> None:
    """Con los dos, la misma venta se pagaría dos veces."""
    plan = _plan(uow)
    with pytest.raises(ErrorValidacion):
        com.asignar(uow, plan.id, usuario_id=uuid4(), partner_id=uuid4())
    with pytest.raises(ErrorValidacion):
        com.asignar(uow, plan.id)


# ── Cálculo (CRM-03.02.03.02) ─────────────────────────────────────────────


def test_porcentaje_llano(uow: UnidadDeTrabajo) -> None:
    plan = _plan(uow)
    com.anadir_regla(uow, plan.id, tipo="porcentaje", porcentaje=Decimal(5))
    salida = com.calcular(
        uow.db, uow.tenant_id, plan_id=plan.id, operaciones=[_op("A", Decimal(10000))]
    )
    assert Decimal(salida["total"]) == Decimal(500)
    assert salida["lineas"][0]["explicacion"]


def test_el_escalado_marginal_paga_por_tramos(uow: UnidadDeTrabajo) -> None:
    """Dos operaciones de 30.000 pagan igual que una de 60.000: si no, el
    comercial aprende a agrupar pedidos en vez de a vender."""
    plan = _plan(uow)
    com.anadir_regla(
        uow,
        plan.id,
        tipo="escalado",
        desde_valor=Decimal(0),
        hasta_valor=Decimal(50000),
        porcentaje=Decimal(2),
    )
    com.anadir_regla(
        uow, plan.id, tipo="escalado", desde_valor=Decimal(50000), porcentaje=Decimal(6)
    )
    de_golpe = com.calcular(
        uow.db, uow.tenant_id, plan_id=plan.id, operaciones=[_op("A", Decimal(60000))]
    )
    partido = com.calcular(
        uow.db,
        uow.tenant_id,
        plan_id=plan.id,
        operaciones=[_op("A", Decimal(30000)), _op("B", Decimal(30000))],
    )
    # 50.000 al 2 % + 10.000 al 6 % = 1.000 + 600
    assert Decimal(de_golpe["total"]) == Decimal(1600)
    assert Decimal(partido["total"]) == Decimal(1600)


def test_el_escalado_retroactivo_paga_todo_al_tipo_alto(uow: UnidadDeTrabajo) -> None:
    """Es la otra forma legítima, y por eso hay que declararla: 60.000 al 6 %."""
    plan = _plan(uow, clave="retro")
    com.anadir_regla(
        uow,
        plan.id,
        tipo="escalado",
        desde_valor=Decimal(0),
        hasta_valor=Decimal(50000),
        porcentaje=Decimal(2),
        modo_tramo="retroactivo",
    )
    com.anadir_regla(
        uow,
        plan.id,
        tipo="escalado",
        desde_valor=Decimal(50000),
        porcentaje=Decimal(6),
        modo_tramo="retroactivo",
    )
    salida = com.calcular(
        uow.db,
        uow.tenant_id,
        plan_id=plan.id,
        operaciones=[_op("A", Decimal(30000)), _op("B", Decimal(30000))],
    )
    assert Decimal(salida["total"]) == Decimal(3600)


def test_el_spiff_solo_cuenta_dentro_de_su_ventana(uow: UnidadDeTrabajo) -> None:
    """Un premio sin fechas se paga dos años después de la campaña."""
    plan = _plan(uow)
    com.anadir_regla(
        uow,
        plan.id,
        tipo="spiff",
        nombre="Campaña primavera",
        importe_fijo=Decimal(200),
        vigente_desde=date(2026, 3, 1),
        vigente_hasta=date(2026, 3, 31),
    )
    dentro = com.calcular(
        uow.db,
        uow.tenant_id,
        plan_id=plan.id,
        operaciones=[_op("A", Decimal(1000), fecha="2026-03-15")],
    )
    fuera = com.calcular(
        uow.db,
        uow.tenant_id,
        plan_id=plan.id,
        operaciones=[_op("A", Decimal(1000), fecha="2026-05-15")],
    )
    assert Decimal(dentro["total"]) == Decimal(200)
    assert Decimal(fuera["total"]) == Decimal(0)


def test_el_spiff_respeta_su_condicion(uow: UnidadDeTrabajo) -> None:
    plan = _plan(uow)
    com.anadir_regla(
        uow,
        plan.id,
        tipo="spiff",
        importe_fijo=Decimal(100),
        condiciones=[{"atributo": "familia", "operador": "=", "valor": "hardware"}],
    )
    con = com.calcular(
        uow.db,
        uow.tenant_id,
        plan_id=plan.id,
        operaciones=[_op("A", Decimal(1), familia="hardware")],
    )
    sin = com.calcular(
        uow.db,
        uow.tenant_id,
        plan_id=plan.id,
        operaciones=[_op("A", Decimal(1), familia="software")],
    )
    assert Decimal(con["total"]) == Decimal(100)
    assert Decimal(sin["total"]) == Decimal(0)


def test_una_condicion_con_un_operador_inventado_no_se_guarda(uow: UnidadDeTrabajo) -> None:
    """Un operador mal escrito no falla: deja de premiar en silencio, y no
    protesta nadie porque nadie sabía que le tocaba."""
    plan = _plan(uow)
    with pytest.raises(ErrorValidacion):
        com.anadir_regla(
            uow,
            plan.id,
            tipo="spiff",
            importe_fijo=Decimal(100),
            condiciones=[{"atributo": "familia", "operador": "igual", "valor": "hardware"}],
        )
    with pytest.raises(ErrorValidacion):
        com.anadir_regla(
            uow,
            plan.id,
            tipo="spiff",
            importe_fijo=Decimal(100),
            condiciones=[{"operador": "=", "valor": "hardware"}],
        )


def test_el_acelerador_necesita_cuota_y_lo_dice(uow: UnidadDeTrabajo) -> None:
    """Sobre una cuota supuesta de cero se dispararía siempre."""
    plan = _plan(uow)
    com.anadir_regla(uow, plan.id, tipo="porcentaje", porcentaje=Decimal(10))
    com.anadir_regla(
        uow, plan.id, tipo="acelerador", desde_valor=Decimal(100), multiplicador=Decimal("1.5")
    )
    sin_cuota = com.calcular(
        uow.db, uow.tenant_id, plan_id=plan.id, operaciones=[_op("A", Decimal(10000))]
    )
    assert sin_cuota["acelerador_evaluado"] is False
    assert Decimal(sin_cuota["total"]) == Decimal(1000)

    con_cuota = com.calcular(
        uow.db,
        uow.tenant_id,
        plan_id=plan.id,
        operaciones=[_op("A", Decimal(10000))],
        cuota=Decimal(8000),
    )
    assert con_cuota["acelerador_evaluado"] is True
    assert Decimal(con_cuota["total"]) == Decimal(1500)


def test_las_operaciones_sin_la_base_se_dicen(uow: UnidadDeTrabajo) -> None:
    """Tratarlas como cero las haría desaparecer del desglose, y el que falta en
    la lista es siempre el que más protesta."""
    plan = _plan(uow, base="margen")
    com.anadir_regla(uow, plan.id, tipo="porcentaje", porcentaje=Decimal(10))
    salida = com.calcular(
        uow.db,
        uow.tenant_id,
        plan_id=plan.id,
        operaciones=[{"id": str(uuid4()), "importe": "1000"}],
    )
    assert salida["concluyente"] is False
    assert salida["sin_base"][0]["falta"] == "margen"


def test_el_tope_recorta_y_lo_explica(uow: UnidadDeTrabajo) -> None:
    plan = _plan(uow, tope_periodo=Decimal(400))
    com.anadir_regla(uow, plan.id, tipo="porcentaje", porcentaje=Decimal(10))
    salida = com.calcular(
        uow.db, uow.tenant_id, plan_id=plan.id, operaciones=[_op("A", Decimal(10000))]
    )
    assert Decimal(salida["total"]) == Decimal(400)
    assert Decimal(salida["recortado_por_tope"]) == Decimal(600)


def test_la_prevision_separa_lo_ganado_de_lo_previsto(uow: UnidadDeTrabajo) -> None:
    """Mezclarlos da una cifra que parece ganada y se acaba gastando."""
    plan = _plan(uow)
    com.anadir_regla(uow, plan.id, tipo="porcentaje", porcentaje=Decimal(10))
    salida = com.previsionar(
        uow.db,
        uow.tenant_id,
        plan_id=plan.id,
        cerradas=[_op("Cerrada", Decimal(10000))],
        pipeline=[_op("Abierta", Decimal(10000), probabilidad=50)],
    )
    assert Decimal(salida["devengado"]) == Decimal(1000)
    assert Decimal(salida["solo_pipeline"]) == Decimal(500)


# ── Liquidación, disputa y pago (CRM-03.02.03.03) ─────────────────────────


def _plan_activo(uow: UnidadDeTrabajo, **kw: Any) -> com.PlanComision:
    plan = _plan(uow, **kw)
    com.anadir_regla(uow, plan.id, tipo="porcentaje", porcentaje=Decimal(10))
    com.activar_plan(uow, plan.id)
    return plan


def _liquidacion(uow: UnidadDeTrabajo, usuario_id: UUID | None = None) -> com.Liquidacion:
    plan = _plan_activo(uow)
    return com.liquidar(
        uow,
        plan_id=plan.id,
        desde=date(2026, 1, 1),
        hasta=date(2026, 1, 31),
        operaciones=[_op("A", Decimal(10000))],
        usuario_id=usuario_id or uuid4(),
    )


def test_un_plan_en_borrador_no_liquida(uow: UnidadDeTrabajo) -> None:
    plan = _plan(uow)
    com.anadir_regla(uow, plan.id, tipo="porcentaje", porcentaje=Decimal(10))
    with pytest.raises(Conflicto):
        com.liquidar(
            uow,
            plan_id=plan.id,
            desde=date(2026, 1, 1),
            hasta=date(2026, 1, 31),
            operaciones=[],
            usuario_id=uuid4(),
        )


def test_la_liquidacion_guarda_el_plan_aplicado(uow: UnidadDeTrabajo) -> None:
    """Quien cobró en marzo tiene derecho a que marzo siga diciendo lo mismo."""
    fila = _liquidacion(uow)
    assert fila.plan_aplicado["clave"] == "plan-2026"
    assert fila.plan_aplicado["devengo"] == "cierre"


def test_no_se_liquida_dos_veces_el_mismo_periodo(uow: UnidadDeTrabajo) -> None:
    usuario = uuid4()
    fila = _liquidacion(uow, usuario)
    with pytest.raises(Conflicto):
        com.liquidar(
            uow,
            plan_id=fila.plan_id,
            desde=fila.desde,
            hasta=fila.hasta,
            operaciones=[],
            usuario_id=usuario,
        )


def test_no_se_aprueba_con_una_disputa_abierta(uow: UnidadDeTrabajo) -> None:
    """Sin ese freno se paga, luego se corrige y nadie entiende su nómina."""
    fila = _liquidacion(uow)
    com.disputar(uow, fila.id, motivo="Falta el pedido de Talleres")
    with pytest.raises(Conflicto):
        com.aprobar(uow, fila.id)


def test_una_disputa_sin_motivo_no_se_puede_resolver(uow: UnidadDeTrabajo) -> None:
    fila = _liquidacion(uow)
    with pytest.raises(ErrorValidacion):
        com.disputar(uow, fila.id, motivo="   ")


def test_resolver_a_favor_anota_una_linea_nueva(uow: UnidadDeTrabajo) -> None:
    """Corregir en sitio deja un número que ya no coincide con lo comunicado."""
    fila = _liquidacion(uow)
    total_antes = Decimal(fila.total)
    disputa = com.disputar(uow, fila.id, motivo="Falta un pedido")
    com.resolver_disputa(
        uow, disputa.id, aceptar=True, resolucion="Tenía razón", ajuste=Decimal(150)
    )
    detalle = com.detalle(uow.db, uow.tenant_id, fila.id)
    assert Decimal(detalle["total"]) == total_antes + Decimal(150)
    assert any(line["origen"] == "ajuste" for line in detalle["lineas"])
    # Resuelta la única disputa, vuelve a poder aprobarse.
    com.aprobar(uow, fila.id)


def test_resolver_exige_explicar_la_resolucion(uow: UnidadDeTrabajo) -> None:
    fila = _liquidacion(uow)
    disputa = com.disputar(uow, fila.id, motivo="No cuadra")
    with pytest.raises(ErrorValidacion):
        com.resolver_disputa(uow, disputa.id, aceptar=False, resolucion="")


def test_la_disputa_fuera_de_plazo_se_registra_marcada(uow: UnidadDeTrabajo) -> None:
    """Ni se pierde —el dato es real— ni se acepta en silencio."""
    from datetime import datetime, timezone

    fila = _liquidacion(uow)
    fila.calculada_at = datetime.now(timezone.utc) - timedelta(days=400)
    uow.db.flush()
    disputa = com.disputar(uow, fila.id, motivo="Tarde pero cierto")
    assert "plazo" in disputa.resolucion.lower()


def test_solo_se_paga_lo_aprobado_y_con_referencia(uow: UnidadDeTrabajo) -> None:
    """«Pagada» sin dónde mirarlo es lo primero que se pregunta."""
    fila = _liquidacion(uow)
    with pytest.raises(Conflicto):
        com.marcar_pagada(uow, fila.id, referencia="NOM-2026-01")
    com.aprobar(uow, fila.id)
    with pytest.raises(ErrorValidacion):
        com.marcar_pagada(uow, fila.id, referencia="  ")
    pagada = com.marcar_pagada(uow, fila.id, referencia="NOM-2026-01")
    assert pagada.estado == "pagada" and pagada.pagada_at is not None


def test_revertir_deja_linea_negativa_y_no_borra(uow: UnidadDeTrabajo) -> None:
    """Una reversión invisible hace que nadie reconozca su nómina."""
    fila = _liquidacion(uow)
    detalle = com.detalle(uow.db, uow.tenant_id, fila.id)
    original = detalle["lineas"][0]
    com.revertir(uow, fila.id, linea_id=UUID(original["id"]), motivo="El pedido se canceló")
    despues = com.detalle(uow.db, uow.tenant_id, fila.id)
    assert len(despues["lineas"]) == 2
    assert Decimal(despues["total"]) == Decimal(0)
    assert despues["lineas"][1]["reversion_de"] == original["id"]


def test_revertir_exige_motivo(uow: UnidadDeTrabajo) -> None:
    fila = _liquidacion(uow)
    detalle = com.detalle(uow.db, uow.tenant_id, fila.id)
    with pytest.raises(ErrorValidacion):
        com.revertir(uow, fila.id, linea_id=UUID(detalle["lineas"][0]["id"]), motivo="")


def test_la_liquidacion_de_un_partner_usa_el_mismo_motor(uow: UnidadDeTrabajo) -> None:
    """Un segundo motor para el canal habría dado dos formas de calcular un rappel."""
    plan = _plan_activo(uow)
    fila = com.liquidar(
        uow,
        plan_id=plan.id,
        desde=date(2026, 1, 1),
        hasta=date(2026, 1, 31),
        operaciones=[_op("A", Decimal(10000))],
        partner_id=uuid4(),
    )
    assert Decimal(fila.total) == Decimal(1000)
    assert fila.usuario_id is None
