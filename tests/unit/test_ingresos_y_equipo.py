"""Ingresos recurrentes, calendario, reparto, grupo de compra, plan conjunto,
revisión, métricas embebidas y motor de compensación
(CRM-03.01.01.06, .07, .08, .10, .11 · CRM-03.01.02.05, .06 · CRM-01.01.02.04 ·
CRM-01.01.05.06 · CRM-03.02.03.04).

Todo lo que persiguen estas pruebas acaba en el mismo sitio: números que se
enseñan en un comité y que no significan lo que parece — el ARR con la
implantación dentro, el trimestre excelente que no se nota en caja, el crédito al
60/60, el crecimiento inflado con renovaciones y la comisión que no cuadra con lo
que el comercial cree que vendió.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion
from crmcore.fechas import hoy

from services.integration import compensacion as cmp
from services.party import metricas_embebidas as met
from services.sales import ingresos as ing
from services.sales import plan_conjunto as pc

# ANCLADO AL DÍA DE HOY, no a una fecha escrita.
#
# Era `date(2026, 9, 23)`, y el 4 de octubre la suite empezó a fallar sola: las
# pruebas que piden una homologación «válida hasta dentro de diez días» pasaron
# a pedirla con una fecha ya pasada, y el producto —con razón— las rechaza. Una
# fecha fija en una prueba es una bomba de relojería: funciona hasta que no, y
# el día que revienta no hay ningún cambio que lo explique.
HOY = hoy()
AHORA = datetime.combine(HOY, time(12, 0), tzinfo=timezone.utc)


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


# ── Recurrente frente a puntual (CRM-03.01.01.06) ─────────────────────────


def test_la_implantacion_no_entra_en_el_arr() -> None:
    """Dividir el valor total por los años mete la implantación dentro y la
    métrica con la que se valora la empresa sale inflada."""
    salida = ing.metricas_de_ingreso(
        lineas=[
            {"tipo": "recurrente", "periodo": "mensual", "importe": 1000, "valor_total": 24000},
            {"tipo": "implantacion", "importe": 15000, "valor_total": 15000},
        ]
    )
    assert salida["arr"] == "12000.00"
    assert "implantacion" in salida["lo_que_no_cuenta_como_arr"]


def test_un_tipo_de_ingreso_inventado_se_rechaza() -> None:
    with pytest.raises(ErrorValidacion) as fallo:
        ing.metricas_de_ingreso(lineas=[{"tipo": "lo_que_sea", "importe": 1}])
    assert fallo.value.error_code == "ingresos.tipo_invalido"


# ── Calendario de ingreso (CRM-03.01.01.07) ───────────────────────────────


@pytest.mark.db
def test_el_calendario_cuadra_al_centimo(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Si sobrara un céntimo, el descuadre saldría en un informe seis meses
    después sin que nadie supiera de dónde viene."""
    salida = ing.planificar_ingresos(
        uow,
        oportunidad_id=uuid4(),
        importe_total=Decimal(100),
        desde=HOY,
        meses=3,
    )
    assert salida["cuadra"] is True
    assert salida["suma"] == "100.00"


@pytest.mark.db
def test_un_calendario_de_cero_periodos_no_reparte_nada(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    with pytest.raises(ErrorValidacion) as fallo:
        ing.planificar_ingresos(
            uow, oportunidad_id=uuid4(), importe_total=Decimal(10), desde=HOY, meses=0
        )
    assert fallo.value.error_code == "ingresos.periodos_invalidos"


@pytest.mark.db
def test_el_previsto_por_periodo_no_es_el_forecast_por_cierre(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Una dice cuándo se firma y otra cuándo entra el dinero."""
    ing.planificar_ingresos(
        uow, oportunidad_id=uuid4(), importe_total=Decimal(120), desde=HOY, meses=12
    )
    salida = ing.previsto_por_periodo(
        uow.db, uow.tenant_id, desde=HOY.replace(day=1), hasta=HOY + timedelta(days=400)
    )
    assert len(salida["periodos"]) == 12
    assert "Cuándo entra el dinero" in salida["que_es"]


# ── Reparto entre comerciales (CRM-03.01.01.08) ───────────────────────────


@pytest.mark.db
def test_el_credito_suma_100_o_no_se_guarda(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Con repartos al 60/60 las comisiones cuadran hacia arriba y el descuadre lo
    encuentra finanzas tres meses después."""
    with pytest.raises(ErrorValidacion) as fallo:
        ing.repartir_credito(
            uow,
            oportunidad_id=uuid4(),
            participaciones=[
                {"usuario_id": uuid4(), "porcentaje": 60},
                {"usuario_id": uuid4(), "porcentaje": 60},
            ],
        )
    assert fallo.value.error_code == "ingresos.credito_descuadrado"


@pytest.mark.db
def test_el_overlay_no_resta_al_titular(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Mezclarlo con el crédito hace que la gente invente porcentajes para que
    cuadre."""
    salida = ing.repartir_credito(
        uow,
        oportunidad_id=uuid4(),
        participaciones=[
            {"usuario_id": uuid4(), "porcentaje": 100},
            {"usuario_id": uuid4(), "porcentaje": 50, "papel": "overlay"},
        ],
    )
    assert salida["credito_suma"] == "100"
    assert len(salida["overlay"]) == 1


# ── Grupo de compra (CRM-03.01.01.10, CRM-01.01.02.04) ────────────────────


@pytest.mark.db
def test_llamar_detractor_a_alguien_exige_motivo(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Es una etiqueta que otro leerá en seis meses y aplicará sin poder
    contrastarla."""
    with pytest.raises(ErrorValidacion) as fallo:
        ing.anotar_rol(
            uow,
            oportunidad_id=uuid4(),
            contacto_id=uuid4(),
            rol="decisor",
            postura=-2,
            motivo="",
        )
    assert fallo.value.error_code == "compra.postura_sin_motivo"


@pytest.mark.db
def test_el_mapa_dice_a_quien_no_se_ha_visto(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Un económico con el que nadie ha hablado es la razón más habitual de que un
    cierre «seguro» se caiga en la última semana."""
    op = uuid4()
    decisor = uuid4()
    ing.anotar_rol(uow, oportunidad_id=op, contacto_id=decisor, rol="decisor")
    salida = ing.grupo_de_compra(uow.db, uow.tenant_id, oportunidad_id=op, contactados=set())
    assert salida["clave_sin_hablar"] == [str(decisor)]
    assert "economico" in salida["faltan_por_identificar"]


@pytest.mark.db
def test_un_rol_de_compra_inventado_se_rechaza(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    with pytest.raises(ErrorValidacion) as fallo:
        ing.anotar_rol(uow, oportunidad_id=uuid4(), contacto_id=uuid4(), rol="interlocutor")
    assert fallo.value.error_code == "compra.rol_invalido"


# ── Oportunidades relacionadas (CRM-03.01.01.11) ──────────────────────────


@pytest.mark.db
def test_una_renovacion_no_es_ingreso_nuevo(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Contarla como tal duplica el crecimiento del trimestre, y es de los errores
    que más tarda en descubrirse porque el número sale bien."""
    salida = ing.relacionar(uow, origen_id=uuid4(), destino_id=uuid4(), tipo="renovacion")
    assert salida["suma_ingreso_nuevo"] is False


def test_el_crecimiento_real_descuenta_lo_que_solo_se_mantiene() -> None:
    salida = ing.crecimiento_real(
        cerradas=[
            {"importe": 100, "relacion": "renovacion"},
            {"importe": 50, "relacion": "upsell"},
        ]
    )
    assert salida["ingreso_nuevo"] == "50"
    assert salida["ingreso_mantenido"] == "100"


# ── Plan conjunto (CRM-03.01.02.05) ───────────────────────────────────────


@pytest.mark.db
def test_un_plan_sin_pasos_del_cliente_no_es_conjunto(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Es una lista de seguimiento interna con otro nombre: el cliente ni la
    mira."""
    with pytest.raises(ErrorValidacion) as fallo:
        pc.guardar_plan(
            uow,
            oportunidad_id=uuid4(),
            pasos=[
                {
                    "titulo": "mandar propuesta",
                    "de_quien": "nuestro",
                    "fecha": HOY.isoformat(),
                    "responsable": "ana",
                }
            ],
            fecha_objetivo=HOY,
        )
    assert fallo.value.error_code == "plan.sin_pasos_del_cliente"


@pytest.mark.db
def test_un_paso_sin_fecha_ni_dueño_no_pasa(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    with pytest.raises(ErrorValidacion) as fallo:
        pc.guardar_plan(
            uow,
            oportunidad_id=uuid4(),
            pasos=[{"titulo": "validar", "de_quien": "del_cliente"}],
            fecha_objetivo=HOY,
        )
    assert fallo.value.error_code == "plan.paso_incompleto"


def test_si_lo_retrasado_es_del_cliente_la_fecha_de_cierre_es_una_ilusion() -> None:
    """Y eso hay que contarlo antes del final del trimestre."""
    salida = pc.estado_del_plan(
        plan={
            "pasos": [
                {
                    "titulo": "validar seguridad",
                    "de_quien": "del_cliente",
                    "fecha": (HOY - timedelta(days=5)).isoformat(),
                    "estado": "pendiente",
                }
            ],
            "compartido_con_el_cliente": True,
            "visto_por_el_cliente_at": AHORA,
        },
        hoy=HOY,
    )
    assert salida["la_fecha_es_creible"] is False
    assert "una ilusión" in salida["que_significa"]


def test_un_plan_que_el_cliente_no_ha_visto_no_es_conjunto() -> None:
    salida = pc.estado_del_plan(plan={"pasos": [], "compartido_con_el_cliente": False}, hoy=HOY)
    assert "es nuestro plan" in salida["aviso"]


# ── Revisión de oportunidad (CRM-03.01.02.06) ─────────────────────────────


@pytest.mark.db
def test_una_revision_sin_las_preguntas_incomodas_no_vale(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Sin ellas esto es «¿cómo lo ves?» con acta, y el número sube porque el
    comercial está metido dentro."""
    with pytest.raises(ErrorValidacion) as fallo:
        pc.revisar(
            uow,
            oportunidad_id=uuid4(),
            respuestas={"por_que_compra": "necesita reducir costes"},
            probabilidad_declarada=80,
            fecha_declarada=HOY,
            acuerdos=[],
            revisada_por=uuid4(),
        )
    assert fallo.value.error_code == "revision.faltan_preguntas"


@pytest.mark.db
def test_un_acuerdo_sin_dueño_es_la_misma_reunion_repetida(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    respuestas = {p: "algo" for p in pc.PREGUNTAS}
    with pytest.raises(ErrorValidacion) as fallo:
        pc.revisar(
            uow,
            oportunidad_id=uuid4(),
            respuestas=respuestas,
            probabilidad_declarada=60,
            fecha_declarada=HOY,
            acuerdos=[{"titulo": "hablar con el CFO"}],
            revisada_por=uuid4(),
        )
    assert fallo.value.error_code == "revision.acuerdo_incompleto"


def _revisar_y_cerrar(uow: UnidadDeTrabajo, *, probabilidad: int, ganada: bool) -> None:
    """Una revisión y el cierre que la cierra.

    Se entra por donde se entra de verdad. Antes estas pruebas le pasaban la
    lista de revisiones a `calibracion` por parámetro, así que medían el cálculo
    y **no el circuito** — y el circuito estaba abierto: nadie escribía el
    resultado, así que con el archivo lleno la calibración contestaba siempre
    «no hay suficientes para concluir».
    """
    oportunidad_id = uuid4()
    pc.revisar(
        uow,
        oportunidad_id=oportunidad_id,
        respuestas={
            "que_puede_salir_mal": "Que no haya presupuesto",
            "que_falta_por_saber": "Quién firma",
        },
        probabilidad_declarada=probabilidad,
        fecha_declarada=HOY,
        acuerdos=[],
        revisada_por=uuid4(),
    )
    pc.anotar_resultado(uow, oportunidad_id, ganada=ganada)


@pytest.mark.db
def test_con_pocas_revisiones_no_se_llama_optimista_a_nadie(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Es injusto y le quita credibilidad al ejercicio entero."""
    for _ in range(6):
        _revisar_y_cerrar(uow, probabilidad=80, ganada=False)
    salida = pc.calibracion(uow.db, uow.tenant_id)
    assert salida["medible"] is False
    assert salida["cerradas"] == 6


@pytest.mark.db
def test_una_revision_sin_cerrar_no_cuenta_para_la_calibracion(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Y es lo que hacía que no contara ninguna.

    La columna del resultado existía desde el primer día «para poder compararlo
    con lo que pasó» y no la escribía nadie. Diez años de revisiones habrían dado
    la misma respuesta: «no hay suficientes».
    """
    for _ in range(20):
        pc.revisar(
            uow,
            oportunidad_id=uuid4(),
            respuestas={
                "que_puede_salir_mal": "Nada",
                "que_falta_por_saber": "Nada",
            },
            probabilidad_declarada=85,
            fecha_declarada=HOY,
            acuerdos=[],
            revisada_por=uuid4(),
        )
    salida = pc.calibracion(uow.db, uow.tenant_id)
    assert salida["medible"] is False
    assert salida["cerradas"] == 0


@pytest.mark.db
def test_un_80_que_se_gana_la_mitad_de_las_veces_no_significa_80(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Significa «me gusta este caso», y el forecast construido con eso no cuadra
    nunca."""
    for i in range(20):
        _revisar_y_cerrar(uow, probabilidad=85, ganada=bool(i % 2))
    salida = pc.calibracion(uow.db, uow.tenant_id)
    assert salida["medible"] is True
    assert salida["tramos_desviados"]


def test_las_oportunidades_nunca_revisadas_salen_las_primeras() -> None:
    salida = pc.sin_revisar(
        oportunidades=[
            {"id": "1", "importe": 10, "ultima_revision": HOY.isoformat()},
            {"id": "2", "importe": 20},
        ],
        hoy=HOY,
    )
    assert salida["pendientes"][0]["oportunidad_id"] == "2"


# ── Métricas embebidas (CRM-01.01.05.06) ──────────────────────────────────


@pytest.mark.db
def test_una_metrica_sin_origen_no_se_guarda(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """El día que finanzas pregunte de dónde sale, la respuesta sería «la calcula
    el CRM»."""
    with pytest.raises(ErrorValidacion) as fallo:
        met.registrar(
            uow.db,
            tenant_id=uow.tenant_id,
            cuenta_id=uuid4(),
            clave="margen_12m",
            valor=Decimal(100),
            vigente_at=AHORA,
            origen="  ",
        )
    assert fallo.value.error_code == "metricas.sin_origen"


@pytest.mark.db
def test_sin_dato_no_es_cero(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """«Cero incidencias» y «no tenemos el dato» se pintan igual y significan lo
    contrario."""
    cuenta = uuid4()
    met.registrar(
        uow.db,
        tenant_id=uow.tenant_id,
        cuenta_id=cuenta,
        clave="facturacion_12m",
        valor=Decimal(1000),
        vigente_at=AHORA,
        origen="erp",
    )
    salida = met.panel_de_la_cuenta(uow.db, uow.tenant_id, cuenta_id=cuenta, ahora=AHORA)
    assert "incidencias_abiertas" in salida["sin_dato"]
    assert "NO es cero" in salida["que_significa"]


@pytest.mark.db
def test_una_metrica_vieja_se_marca(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Si el gestor negocia con un margen de hace un trimestre, negocia con un
    número que ya no existe."""
    cuenta = uuid4()
    met.registrar(
        uow.db,
        tenant_id=uow.tenant_id,
        cuenta_id=cuenta,
        clave="margen_12m",
        valor=Decimal(50),
        vigente_at=AHORA - timedelta(days=90),
        origen="erp",
    )
    salida = met.panel_de_la_cuenta(uow.db, uow.tenant_id, cuenta_id=cuenta, ahora=AHORA)
    assert "margen_12m" in salida["caducadas"]


@pytest.mark.db
def test_un_dato_mas_viejo_no_pisa_al_bueno(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    cuenta = uuid4()
    met.registrar(
        uow.db,
        tenant_id=uow.tenant_id,
        cuenta_id=cuenta,
        clave="nps",
        valor=Decimal(9),
        vigente_at=AHORA,
        origen="encuestas",
    )
    met.registrar(
        uow.db,
        tenant_id=uow.tenant_id,
        cuenta_id=cuenta,
        clave="nps",
        valor=Decimal(2),
        vigente_at=AHORA - timedelta(days=10),
        origen="encuestas",
    )
    salida = met.panel_de_la_cuenta(uow.db, uow.tenant_id, cuenta_id=cuenta, ahora=AHORA)
    assert salida["metricas"][0]["valor"] == "9.00"


@pytest.mark.db
def test_sin_metricas_no_se_dice_que_los_clientes_no_tienen_actividad(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    salida = met.salud_de_la_integracion(uow.db, uow.tenant_id, ahora=AHORA)
    assert salida["medible"] is False


# ── Motor de compensación (CRM-03.02.03.04) ───────────────────────────────


def test_no_se_manda_la_comision_calculada() -> None:
    """Habría dos cálculos y la nómina se haría con el que no es."""
    with pytest.raises(ErrorValidacion) as fallo:
        cmp.componer_hecho(
            tipo="cierre",
            referencia="OP-1",
            fecha=HOY,
            importe=Decimal(1000),
            moneda="EUR",
            reparto=[{"usuario_id": uuid4(), "porcentaje": 100}],
            datos={"comision": 100},
        )
    assert fallo.value.error_code == "compensacion.no_se_manda_el_calculo"


def test_el_reparto_que_se_manda_tambien_suma_100() -> None:
    with pytest.raises(ErrorValidacion) as fallo:
        cmp.componer_hecho(
            tipo="cierre",
            referencia="OP-1",
            fecha=HOY,
            importe=Decimal(1000),
            moneda="EUR",
            reparto=[{"usuario_id": uuid4(), "porcentaje": 40}],
        )
    assert fallo.value.error_code == "compensacion.reparto_descuadrado"


def test_el_calculo_del_motor_no_se_recalcula_aqui() -> None:
    """Enseñar otra cifra distinta de la que se va a cobrar hace que nadie se crea
    ninguna de las dos."""
    salida = cmp.recibir_calculo(
        referencia="OP-1", lineas=[{"importe": 123.45}], periodo="2026-Q3", cerrado=False
    )
    assert salida["se_recalcula_aqui"] is False
    assert salida["provisional"] is True


def test_sin_lineas_del_motor_no_es_cero() -> None:
    """Puede ser que el hecho no le llegara."""
    salida = cmp.recibir_calculo(referencia="OP-1", lineas=[], periodo="2026-Q3", cerrado=True)
    assert salida["medible"] is False


def test_un_clawback_no_se_ajusta_solo() -> None:
    """Quitarle dinero a alguien de la próxima nómina sin decírselo es lo que hace
    que un equipo deje de confiar en el sistema."""
    salida = cmp.cambio_despues_de_pagar(
        referencia="OP-1",
        importe_original=Decimal(1000),
        importe_nuevo=Decimal(600),
        ya_pagada=True,
        motivo="el cliente anuló la mitad del pedido",
    )
    assert salida["hay_clawback"] is True
    assert salida["se_ajusta_solo"] is False


def test_lo_que_se_mando_y_no_ha_vuelto_se_detecta_antes_de_cerrar() -> None:
    """No da ningún error: simplemente esa venta no aparece en la comisión de
    nadie, y lo descubre el comercial en su nómina."""
    salida = cmp.conciliar(
        hechos_enviados=[{"referencia": "A"}, {"referencia": "B"}],
        calculos_recibidos=[{"referencia": "A"}],
    )
    assert salida["sin_calculo"] == ["B"]
    assert salida["cuadra"] is False


def test_no_se_mandan_hechos_a_un_periodo_cerrado() -> None:
    """El motor los metería en el siguiente o los descartaría, y las dos cosas
    pasan en silencio."""
    with pytest.raises(Conflicto) as fallo:
        cmp.exigir_periodo_abierto(periodo_cerrado=True, referencia="OP-1")
    assert fallo.value.error_code == "compensacion.periodo_cerrado"
