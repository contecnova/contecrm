"""Cuatro módulos de servicio que no importaba nadie
(CRM-00.03.03.08, CRM-00.03.03.09, CRM-00.04.02.01, .05, .06, .07,
CRM-00.02.02.06, CRM-09.02.01.10).

Ninguno daba error. Los cuatro hacían que el producto se comportara como si esas
capacidades no existieran:

**Probar una automatización sin activarla.** Se escriben en producción porque es
donde están los datos de verdad, y se prueban activándolas. Funciona hasta el día
en que la regla toca cuatro mil registros, y entonces lo que hay que deshacer son
cuatro mil correos ya enviados.

**El código del tenant.** Sandbox, versiones, firma y observabilidad: todo lo que
hace aceptable dejar que un cliente ejecute su código dentro del CRM.

**Los cambios hacia el lago del cliente.** Lo que pide suena simple —«mándanos
los cambios»— y tiene tres formas de salir mal, las tres resueltas y ninguna
alcanzable.

**El coste real frente al ofertado.** El margen de una oferta es una previsión;
el de verdad se sabe cuando llega la factura, y casi nadie vuelve a mirarlo. Por
eso las empresas descubren que un tipo de trabajo pierde dinero después de
haberlo vendido veinte veces.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

# ── Probar y promocionar (CRM-00.03.03.08) ────────────────────────────────


def test_se_ve_a_cuantos_toca_antes_de_tocarlos() -> None:
    """Probarla activándola funciona hasta el día en que la regla toca cuatro
    mil, y entonces lo que hay que deshacer son cuatro mil correos enviados."""
    from services.automation import entornos_auto as ea

    salida = ea.probar_en_seco(
        nombre="avisar morosos",
        afectados=[{"id": str(uuid4()), "nombre": f"cuenta {i}"} for i in range(500)],
        acciones=[{"tipo": "email"}],
        limite_muestra=5,
    )
    assert salida["afectaria_a"] == 500
    # La muestra va acotada: una lista de quinientos no se mira, y lo que se
    # quiere ver es si los que caen son los que uno tenía en la cabeza.
    assert len(salida["muestra"]) == 5
    assert salida["hay_mas"] is True
    assert salida["en_seco"] is True
    # Y se avisa de que es masiva: ahí es donde está el accidente.
    assert salida["es_masiva"] is True
    assert salida["aviso"].strip()


def test_sin_prueba_en_seco_no_se_promociona() -> None:
    """Lo que se promociona toca datos de clientes de verdad."""
    from crmcore.errors import Conflicto

    from services.automation import entornos_auto as ea

    with pytest.raises(Conflicto) as fallo:
        ea.promocionar(
            definicion={"nombre": "x"},
            desde="pruebas",
            hacia="produccion",
            probada_en_seco=False,
        )
    # Y se dice por qué, con el coste de cada lado: la prueba cuesta un minuto.
    assert "cuatro mil correos" in str(fallo.value)

    con = ea.promocionar(
        definicion={"nombre": "x"},
        desde="pruebas",
        hacia="produccion",
        probada_en_seco=True,
        afectados_en_pruebas=3,
    )
    # Llega APAGADA: una que se enciende sola al promocionarse empieza a actuar
    # cuando alguien pulsa «desplegar», que no es cuando alguien ha decidido que
    # actúe.
    assert con["llega_activa"] is False
    # Y no se copia lo ya procesado en pruebas: haría que se saltara justo los
    # registros que tiene que tocar.
    assert con["estado_descartado"] == []
    assert con["porque_sin_estado"].strip()


def test_una_plantilla_instalada_no_se_activa_sola() -> None:
    """Una que se enciende al instalarse manda correos a clientes reales con
    textos que nadie ha leído."""
    from services.automation import entornos_auto as ea

    salida = ea.instalar_plantilla(
        plantilla={"clave": "construccion", "reglas": [{"clave": "aviso"}]},
        existentes=[],
    )
    assert salida["instaladas"] == ["aviso"]
    assert salida["todas_apagadas"] is True
    # Y se dice qué da por supuesto la plantilla: una regla de una industria
    # asume cosas del negocio que pueden no ser verdad en este cliente.
    assert salida["que_hacer_ahora"].strip()


def test_lo_que_ya_existe_no_se_pisa() -> None:
    """Sobrescribir una regla del tenant es perder trabajo de alguien sin
    preguntar."""
    from services.automation import entornos_auto as ea

    salida = ea.instalar_plantilla(
        plantilla={"clave": "construccion", "reglas": [{"clave": "aviso"}]},
        existentes=["aviso"],
    )
    assert salida["saltadas"] == ["aviso"]
    assert not salida["instaladas"]


# ── Código del tenant (CRM-00.04.02) ──────────────────────────────────────


def test_los_tres_limites_se_miran_y_se_dice_cual_se_paso() -> None:
    """Con solo el tiempo, un bucle que no hace nada pasa; con solo la memoria,
    uno que llama mil veces a un tercero también."""
    from services.automation import extensiones as ex

    bien = ex.comprobar_limites(
        consumo={"milisegundos": 100, "memoria_mb": 10, "llamadas_salientes": 1}
    )
    assert bien["dentro"] is True

    mal = ex.comprobar_limites(
        consumo={"milisegundos": 999_999, "memoria_mb": 10, "llamadas_salientes": 1}
    )
    assert mal["dentro"] is False
    # «La extensión ha fallado» no deja arreglar nada: se dice cuál se pasó.
    assert [e["limite"] for e in mal["excedidos"]] == ["milisegundos"]


def test_lo_que_no_esta_permitido_no_se_concede() -> None:
    """La lista es de lo que se permite, no de lo que se prohíbe: una lista de
    prohibiciones nunca está completa."""
    from crmcore.errors import Prohibido

    from services.automation import extensiones as ex

    # Lo que no está en la lista negra pasa: la lista acota lo que NO se
    # ofrece, y lo que no se ofrece se dice con su motivo.
    ex.exigir_permitido(capacidades=["leer_cuentas"])

    with pytest.raises(Prohibido) as fallo:
        ex.exigir_permitido(capacidades=["ejecutar_sql"])
    assert "metamodelo" in str(fallo.value)


def test_un_codigo_cambiado_despues_de_firmarlo_se_detecta() -> None:
    """Se comprueba la huella del código, no quién dice ser el firmante."""
    from services.automation import extensiones as ex

    codigo = b"def principal(): return 1"
    buena = ex.revisar_firma(
        codigo=codigo,
        huella_firmada=ex.huella_de(codigo),
        firmante="acme",
        firmantes_de_confianza=["acme"],
        revisada_por=uuid4(),
    )
    # Firmada **y revisada por una persona**: la firma dice quién lo escribió,
    # no que sea seguro, y automatizar «¿este código es seguro?» es el problema
    # que nadie ha resuelto.
    assert buena["instalable"] is True

    sin_revisar = ex.revisar_firma(
        codigo=codigo,
        huella_firmada=ex.huella_de(codigo),
        firmante="acme",
        firmantes_de_confianza=["acme"],
    )
    assert sin_revisar["instalable"] is False

    cambiada = ex.revisar_firma(
        codigo=b"def principal(): return 2",
        huella_firmada=ex.huella_de(codigo),
        firmante="acme",
        firmantes_de_confianza=["acme"],
        revisada_por=uuid4(),
    )
    assert cambiada["instalable"] is False
    assert cambiada["porque"].strip()


# ── CDC hacia el lago (CRM-00.02.02.06) ───────────────────────────────────


def test_lo_que_nadie_ha_decidido_no_sale_hacia_el_lago() -> None:
    """Un flujo que manda la tabla entera por omisión acaba llevándose el campo
    que alguien creó ayer para una prueba — y de un lago no se borra, se
    reprocesa."""
    from services.eventing import cdc

    salida = cdc.declarar_flujo(
        objeto="cuenta",
        campos=[{"nombre": "nombre", "trato": "tal_cual"}, {"nombre": "nif"}],
        destino="s3://lago/cuentas",
    )
    salen = {c.get("nombre") or c.get("campo") for c in salida["campos_que_salen"]}
    no_salen = {c.get("nombre") or c.get("campo") for c in salida["campos_que_no_salen"]}
    # El que dice qué hacer con él sale; el que no, no.
    assert "nif" in no_salen or "nif" not in salen


def test_el_cambio_lleva_el_antes_y_el_despues() -> None:
    """Solo con el después no se puede saber qué cambió, y cualquier cálculo de
    evolución sale mal."""
    from services.eventing import cdc

    salida = cdc.componer_cambio(
        objeto="cuenta",
        registro_id=uuid4(),
        tipo="modificacion",
        antes={"nombre": "A", "secreto": "x"},
        despues={"nombre": "B", "secreto": "y"},
        campos_permitidos=["nombre"],
        secuencia=7,
    )
    assert salida["antes"] == {"nombre": "A"}
    assert salida["despues"] == {"nombre": "B"}
    # Lo que no está permitido no sale ni en el antes ni en el después.
    assert "secreto" not in str(salida)
    assert salida["secuencia"] == 7


def test_la_marca_avanza_hasta_el_primer_fallo_y_no_mas() -> None:
    """Saltárselo deja un hueco permanente que nadie vuelve a mirar: el lago
    parece completo y le falta un tramo."""
    from services.eventing import cdc

    salida = cdc.avanzar_marca(marca_actual=10, confirmados=[11, 12, 14], fallidos=[13])
    # Hasta 12 y no hasta 14: el 14 confirmado no vale si el 13 falló.
    assert salida["marca"] == 12
    assert salida["parada_en"] == 13
    assert "hueco" in salida["porque"]


# ── Coste real (CRM-09.02.01.10) ──────────────────────────────────────────


def test_lo_que_no_se_puede_comparar_todavia_no_entra_en_la_media() -> None:
    """Un pedido sin factura no es un pedido con desviación cero, y meterlo en la
    media la aplana justo donde hace falta que se note."""
    from services.analytics import coste_real

    salida = coste_real.desviacion(
        pedidos=[
            {"referencia": "A", "coste_ofertado": "100", "coste_real": "130"},
            {"referencia": "B", "coste_ofertado": "100"},
        ]
    )
    assert salida["pedidos"] == 1
    assert salida["pedidos_sin_coste_real"] == 1
    # Un 30 % de desviación sobre lo ofertado: ese es el número que nadie mira.
    assert salida["desviacion_pct"] == "30.00"


def test_quien_siempre_factura_por_encima_se_ve_acumulando() -> None:
    """Un proveedor que siempre factura un 20 % por encima no es más caro: es que
    su oferta no vale."""
    from services.analytics import coste_real

    salida = coste_real.por_proveedor(
        pedidos=[
            {"proveedor_id": "P1", "coste_ofertado": "100", "coste_real": "120"},
            {"proveedor_id": "P1", "coste_ofertado": "200", "coste_real": "240"},
            {"proveedor_id": "P1", "coste_ofertado": "50", "coste_real": "60"},
            {"proveedor_id": "P2", "coste_ofertado": "100", "coste_real": "100"},
            {"proveedor_id": "P2", "coste_ofertado": "100", "coste_real": "100"},
            {"proveedor_id": "P2", "coste_ofertado": "100", "coste_real": "100"},
        ]
    )
    por_id = {p["proveedor_id"]: p for p in salida["proveedores"]}
    assert por_id["P1"]["desviacion_pct"] == "20.00"
    assert por_id["P2"]["desviacion_pct"] == "0.00"
    # Con tres pedidos medidos ya se puede concluir; con uno, no.
    assert por_id["P1"]["concluyente"] is True
    assert "no es caro: es impreciso" in salida["que_significa"]


def _any() -> Any:
    return None
