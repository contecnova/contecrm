"""Coste, tarifas de proveedor y capacidad (CRM-09.02.01.01 a .10).

Un CRM que sabe poner precio y no sabe lo que cuesta no puede decir el margen, y
el margen es lo único que un responsable aprueba de verdad. Estas pruebas van
detrás de lo que hace que ese número mienta: el margen aproximado de una oferta
con costes incompletos, la tarifa que sube y reescribe una oferta aprobada, la
capacidad que se vende tres veces y la desviación media que esconde el pedido que
se fue al 40 %.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from crmcore.errors import Conflicto, ErrorValidacion

from services.analytics import coste_real as cr
from services.sales import coste as cst

HOY = date(2026, 9, 23)


# ── Margen (CRM-09.02.01.02) ──────────────────────────────────────────────


def test_sin_coste_no_hay_margen_cero_hay_margen_desconocido() -> None:
    """Un margen en blanco se lee como «no hay margen» o como «no importa» según
    quien mire, y las dos lecturas son peores que la verdad."""
    salida = cst.margen_de_linea(precio_venta=Decimal(100), coste=None)
    assert salida["calculable"] is False
    assert "aprobar a ciegas" in salida["porque"]


def test_el_margen_de_una_linea_sale_con_su_porcentaje() -> None:
    salida = cst.margen_de_linea(precio_venta=Decimal(100), coste=Decimal(60), cantidad=Decimal(2))
    assert salida["margen"] == "80"
    assert salida["margen_pct"] == "40.00"


def test_una_oferta_con_costes_incompletos_no_tiene_margen_aproximado() -> None:
    """Enseñar la media de lo que sí se sabe es la forma elegante de mentir en una
    hoja de aprobación."""
    salida = cst.margen_de_oferta(
        lineas=[
            {"referencia": "L1", "precio_venta": 100, "coste": 50, "cantidad": 1},
            {"referencia": "L2", "precio_venta": 200, "coste": None, "cantidad": 1},
        ]
    )
    assert salida["completo"] is False
    assert salida["lineas_sin_coste"] == ["L2"]
    assert "mentir" in salida["aviso"]


def test_un_margen_bajo_pide_aprobacion() -> None:
    salida = cst.margen_de_oferta(
        lineas=[{"referencia": "L1", "precio_venta": 100, "coste": 95, "cantidad": 1}]
    )
    assert salida["necesita_aprobacion"] is True


def test_una_linea_en_perdidas_se_marca() -> None:
    salida = cst.margen_de_linea(precio_venta=Decimal(50), coste=Decimal(80))
    assert salida["en_perdidas"] is True


# ── Congelar el coste (CRM-09.02.01.03) ───────────────────────────────────


def test_revisar_los_costes_no_reescribe_la_oferta() -> None:
    """El comercial la manda creyendo que lleva los números que aprobó su jefe."""
    congelada = cst.congelar_coste(
        lineas=[{"referencia": "L1", "coste": Decimal(60), "tarifa": "T-1"}]
    )
    salida = cst.revisar_costes_congelados(
        lineas_congeladas=congelada["lineas"], costes_hoy={"L1": Decimal(70)}
    )
    assert salida["la_oferta_se_ha_tocado"] is False
    assert salida["cambios"][0]["peor"] is True
    assert "ya no es el que hay" in salida["que_hacer"]


def test_si_la_tarifa_no_cambia_no_hay_nada_que_revisar() -> None:
    congelada = cst.congelar_coste(lineas=[{"referencia": "L1", "coste": Decimal(60)}])
    salida = cst.revisar_costes_congelados(
        lineas_congeladas=congelada["lineas"], costes_hoy={"L1": Decimal(60)}
    )
    assert salida["hay_cambios"] is False


# ── Comparar proveedores (CRM-09.02.01.04) ────────────────────────────────


def test_el_mas_barato_que_llega_tarde_no_es_la_opcion_barata() -> None:
    """Es un incumplimiento con descuento."""
    salida = cst.comparar_proveedores(
        ofertas=[
            {
                "proveedor_id": uuid4(),
                "nombre": "Barato",
                "coste": Decimal(80),
                "homologado": True,
                "fecha_entrega": HOY + timedelta(days=40),
            },
            {
                "proveedor_id": uuid4(),
                "nombre": "A tiempo",
                "coste": Decimal(100),
                "homologado": True,
                "fecha_entrega": HOY + timedelta(days=5),
            },
        ],
        fecha_necesaria=HOY + timedelta(days=10),
    )
    assert salida["elegida"]["nombre"] == "A tiempo"
    assert "Barato" in salida["aviso"]


def test_uno_sin_homologar_no_es_una_opcion_por_barato_que_sea() -> None:
    salida = cst.comparar_proveedores(
        ofertas=[{"proveedor_id": uuid4(), "nombre": "X", "coste": Decimal(1), "homologado": False}]
    )
    assert salida["hay_alguna"] is False
    assert "no es una opción" in salida["opciones"][0]["motivos_de_descarte"][0]


def test_se_devuelven_todas_con_su_motivo_de_descarte() -> None:
    """Quien decide necesita poder explicar por qué no eligió la más barata."""
    salida = cst.comparar_proveedores(
        ofertas=[
            {"proveedor_id": uuid4(), "nombre": "A", "coste": Decimal(10), "homologado": False},
            {"proveedor_id": uuid4(), "nombre": "B", "coste": Decimal(20), "homologado": True},
        ]
    )
    assert len(salida["opciones"]) == 2


# ── Petición de oferta (CRM-09.02.01.05) ──────────────────────────────────


def test_una_peticion_con_fecha_pasada_no_se_manda() -> None:
    """La respuesta llegaría cuando el cliente ya ha decidido."""
    with pytest.raises(ErrorValidacion) as fallo:
        cst.preparar_peticion(
            proveedores=[uuid4()],
            lineas=[{"producto": "x"}],
            fecha_limite=HOY - timedelta(days=1),
            oportunidad_id=uuid4(),
            hoy=HOY,
        )
    assert fallo.value.error_code == "rfq.fecha_pasada"


def test_una_peticion_suelta_se_avisa() -> None:
    """No se podrá cerrar nunca: nadie sabrá si aquello se ganó o se perdió."""
    salida = cst.preparar_peticion(
        proveedores=[uuid4()],
        lineas=[{"producto": "x"}],
        fecha_limite=HOY + timedelta(days=5),
        oportunidad_id=None,
        hoy=HOY,
    )
    assert "no se podrá cerrar nunca" in salida["aviso"].lower()


def test_se_dice_quien_no_ha_contestado() -> None:
    """Si tres de cinco no contestan, la comparación no es entre cinco opciones y
    decidir sin saberlo es creer que se ha comparado el mercado."""
    a, b, c = uuid4(), uuid4(), uuid4()
    salida = cst.recoger_respuestas(
        pedidas_a=[a, b, c],
        respuestas=[{"proveedor_id": a, "coste": 10}],
        fecha_limite=HOY + timedelta(days=2),
        hoy=HOY,
    )
    assert len(salida["sin_contestar"]) == 2
    assert "comparado el mercado" in salida["que_significa"]


# ── Capacidad (CRM-09.02.01.06) ───────────────────────────────────────────


def test_la_capacidad_descuenta_lo_ya_comprometido() -> None:
    """Una cuota que solo mira lo contratado deja vender tres veces lo mismo."""
    salida = cst.capacidad_disponible(contratada=Decimal(100), ya_comprometida=Decimal(80))
    assert salida["libre"] == "20"


def test_lo_que_hay_en_ofertas_abiertas_se_enseña_aparte() -> None:
    """Si se ganaran todas no cabría, y esa conversación es mejor tenerla antes de
    mandar la cuarta oferta."""
    salida = cst.capacidad_disponible(
        contratada=Decimal(100), ya_comprometida=Decimal(80), en_ofertas_abiertas=Decimal(50)
    )
    assert salida["libre_si_se_ganan_todas"] == "-30"
    assert "antes de mandar la siguiente" in salida["aviso"]


def test_sobrevender_no_es_un_riesgo_futuro() -> None:
    """Es una entrega que va a fallar."""
    salida = cst.capacidad_disponible(contratada=Decimal(10), ya_comprometida=Decimal(15))
    assert salida["sobrevendida"] is True
    assert "va a fallar" in salida["aviso"]


def test_no_se_reserva_por_encima_de_lo_disponible_sin_decirlo() -> None:
    with pytest.raises(Conflicto) as fallo:
        cst.reservar(disponible=Decimal(5), cantidad=Decimal(10))
    assert fallo.value.error_code == "capacidad.insuficiente"

    forzado = cst.reservar(disponible=Decimal(5), cantidad=Decimal(10), permitir_exceso=True)
    assert forzado["forzado"] is True
    assert "sabiendo que no cabe" in forzado["aviso"]


# ── Plazo (CRM-09.02.01.07) ───────────────────────────────────────────────


def test_sin_plazo_del_proveedor_no_se_promete_fecha() -> None:
    """Prometer sin saber es el origen de casi todos los retrasos, y el que da la
    cara después es el comercial."""
    salida = cst.fecha_que_se_puede_prometer(plazo_proveedor_dias=None)
    assert salida["se_puede_prometer"] is False


def test_al_plazo_del_proveedor_se_le_suma_el_nuestro() -> None:
    salida = cst.fecha_que_se_puede_prometer(plazo_proveedor_dias=10, dias_propios=3, desde=HOY)
    assert salida["fecha"] == (HOY + timedelta(days=13)).isoformat()


def test_un_festivo_por_medio_corre_la_fecha() -> None:
    salida = cst.fecha_que_se_puede_prometer(
        plazo_proveedor_dias=5, dias_propios=0, desde=HOY, festivos=[HOY + timedelta(days=2)]
    )
    assert salida["fecha"] == (HOY + timedelta(days=6)).isoformat()


# ── Reparto (CRM-09.02.01.08) ─────────────────────────────────────────────


def test_el_reparto_sigue_la_regla_declarada() -> None:
    """Sin regla reparte quien monta la oferta, y acaba siendo siempre el mismo
    proveedor sin que nadie lo haya decidido."""
    salida = cst.repartir(
        candidatos=[
            {"id": uuid4(), "nombre": "Caro", "coste": 20, "libre": 100, "homologado": True},
            {"id": uuid4(), "nombre": "Barato", "coste": 10, "libre": 30, "homologado": True},
        ],
        cantidad=Decimal(40),
        regla="menor_coste",
    )
    assert salida["reparto"][0]["nombre"] == "Barato"
    assert salida["reparto"][0]["cantidad"] == "30"
    assert salida["cabe_entero"] is True


def test_si_no_cabe_entero_se_dice_cuanto_falta() -> None:
    """Repartir lo que hay y callar el resto es como se descubre en la entrega."""
    salida = cst.repartir(
        candidatos=[{"id": uuid4(), "coste": 10, "libre": 5, "homologado": True}],
        cantidad=Decimal(20),
    )
    assert salida["cabe_entero"] is False
    assert salida["sin_asignar"] == "15"


def test_los_no_homologados_no_entran_en_el_reparto() -> None:
    salida = cst.repartir(
        candidatos=[{"id": uuid4(), "coste": 1, "libre": 100, "homologado": False}],
        cantidad=Decimal(10),
    )
    assert salida["reparto"] == []


def test_una_regla_de_reparto_inventada_se_rechaza() -> None:
    with pytest.raises(ErrorValidacion) as fallo:
        cst.repartir(candidatos=[], cantidad=Decimal(1), regla="a_ojo")
    assert fallo.value.error_code == "reparto.regla_invalida"


# ── Rappels (CRM-09.02.01.09) ─────────────────────────────────────────────


def test_un_rappel_estimado_no_es_dinero() -> None:
    """Depende de llegar al tramo, y si el año se tuerce no se llega."""
    salida = cst.rappel_estimado(
        compra_acumulada=Decimal(120000), tramos=[{"desde": 100000, "pct": 3}]
    )
    assert salida["es_estimado"] is True
    assert salida["importe"] == "3600.00"


def test_el_rappel_no_se_reparte_hacia_atras() -> None:
    """Haría que una oferta pareciera rentable por algo que todavía no ha pasado."""
    salida = cst.rappel_estimado(compra_acumulada=Decimal(0), tramos=[{"desde": 1, "pct": 5}])
    assert salida["se_imputa_a"].startswith("el periodo")


def test_se_dice_cuanto_falta_para_el_siguiente_tramo() -> None:
    salida = cst.rappel_estimado(
        compra_acumulada=Decimal(90000),
        tramos=[{"desde": 50000, "pct": 2}, {"desde": 100000, "pct": 4}],
    )
    assert salida["falta_para_el_siguiente"] == "10000"


# ── Coste real (CRM-09.02.01.10) ──────────────────────────────────────────


def test_lo_que_no_se_ha_facturado_no_cuenta_como_acertado() -> None:
    """Es lo que hace que estos informes mientan siempre hacia el mismo lado."""
    salida = cr.desviacion(
        pedidos=[{"referencia": "P1", "coste_ofertado": 100, "coste_real": None}]
    )
    assert salida["medible"] is False
    assert salida["pedidos_sin_coste_real"] == 1


def test_la_media_no_enseña_el_pedido_que_se_fue() -> None:
    """Una desviación del 3 % esconde diez clavados y uno que se fue al 40 %."""
    pedidos = [{"referencia": f"P{i}", "coste_ofertado": 100, "coste_real": 100} for i in range(10)]
    pedidos.append({"referencia": "P99", "coste_ofertado": 100, "coste_real": 140})
    salida = cr.desviacion(pedidos=pedidos)
    assert [f["pedido"] for f in salida["los_que_se_fueron"]] == ["P99"]


def test_una_desviacion_sin_explicacion_se_marca() -> None:
    """«El coste subió» no sirve para nada."""
    salida = cr.desviacion(pedidos=[{"referencia": "P1", "coste_ofertado": 100, "coste_real": 150}])
    assert salida["sin_explicacion"] == ["P1"]


def test_con_dos_pedidos_no_se_concluye_de_un_proveedor() -> None:
    """Dos desviaciones seguidas pueden ser dos casualidades, y la etiqueta de
    impreciso hace que nadie se crea el informe."""
    proveedor = uuid4()
    salida = cr.por_proveedor(
        pedidos=[
            {"proveedor_id": proveedor, "coste_ofertado": 100, "coste_real": 120},
            {"proveedor_id": proveedor, "coste_ofertado": 100, "coste_real": 130},
        ]
    )
    assert salida["medible"] is False
    assert salida["proveedores"][0]["concluyente"] is False


def test_un_proveedor_que_siempre_se_pasa_no_es_caro_es_impreciso() -> None:
    """Sus ofertas no sirven para decidir, que es otra conversación."""
    proveedor = uuid4()
    salida = cr.por_proveedor(
        pedidos=[
            {"proveedor_id": proveedor, "coste_ofertado": 100, "coste_real": 115} for _ in range(3)
        ]
    )
    assert salida["medible"] is True
    assert salida["proveedores"][0]["desviacion_pct"] == "15.00"
