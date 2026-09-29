"""Activos instalados, jerarquía, garantías e historial (CRM-04.04.02).

Las pruebas van detrás de los cuatro sitios por donde un parque instalado deja de
servir:

  * dos activos vivos con la misma serie, que mezclan dos historiales,
  * el componente que cambia de máquina y pierde de dónde venía,
  * la falta de garantía tomada por falta de cobertura, que factura a quien sí
    la tenía,
  * y el historial recalculado desde las órdenes, que se reescribe al editarlas.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion

from services.service import activos as act


# El «hoy» del producto, no el de la máquina.
#
# Estas comprobaciones construían lo que esperan con `_hoy()` —hora local—
# mientras el producto calcula el día en la zona del tenant, que sin ninguna
# configurada es UTC. Resultado: **verdes veintidós horas al día y rojas dos**,
# entre medianoche y las dos de la mañana en Madrid. Se descubrió porque una
# tanda cruzó la medianoche.
#
# No se toca el producto: calcular en UTC cuando nadie ha dicho su zona es
# correcto. Lo que estaba mal era comparar contra otro reloj.
def _hoy() -> date:
    from crmcore.fechas import hoy

    return hoy()


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _activo(uow: UnidadDeTrabajo, nombre: str = "Compresor", **kw: Any) -> act.ActivoInstalado:
    fila, _ = act.crear(uow, nombre=nombre, **kw)
    return fila


# ── Alta e identificación (CRM-04.04.02.01) ───────────────────────────────


def test_dos_activos_vivos_no_comparten_serie(uow: UnidadDeTrabajo) -> None:
    """Significan una sustitución que nadie registró: la nueva arrastra averías
    de la vieja y la garantía se calcula sobre la fecha equivocada."""
    _activo(uow, numero_serie="SN-1")
    with pytest.raises(Conflicto):
        _activo(uow, "Otro", numero_serie="SN-1")


def test_la_serie_se_puede_reutilizar_tras_retirar(uow: UnidadDeTrabajo) -> None:
    fila = _activo(uow, numero_serie="SN-1")
    act.cambiar_estado(uow, fila.id, estado="retirado", motivo="Fin de vida")
    otro = _activo(uow, "Repuesto", numero_serie="SN-1")
    assert otro.numero_serie == "SN-1"


def test_el_alta_sin_serie_avisa_en_vez_de_bloquear(uow: UnidadDeTrabajo) -> None:
    """Un técnico que da de alta desde casa del cliente no siempre la tiene, y
    bloquearle el alta hace que no la dé."""
    _, avisos = act.crear(uow, nombre="Sin serie")
    assert any("número de serie" in a for a in avisos)


def test_retirar_exige_motivo(uow: UnidadDeTrabajo) -> None:
    fila = _activo(uow)
    with pytest.raises(ErrorValidacion):
        act.cambiar_estado(uow, fila.id, estado="retirado")
    act.cambiar_estado(uow, fila.id, estado="retirado", motivo="Baja del cliente")


def test_una_lectura_que_baja_se_acepta_y_se_marca(uow: UnidadDeTrabajo) -> None:
    """Rechazarla haría que el técnico no anotara nada, que es peor que anotarlo
    con un aviso."""
    fila = _activo(uow, contador=Decimal(1000), unidad_contador="h")
    salida = act.leer_contador(uow, fila.id, valor=Decimal(800))
    assert salida["retrocede"] is True and salida["aviso"]
    assert Decimal(salida["contador"]) == Decimal(800)


# ── Jerarquía (CRM-04.04.02.02) ───────────────────────────────────────────


def test_el_arbol_devuelve_los_componentes(uow: UnidadDeTrabajo) -> None:
    maquina = _activo(uow, "Máquina")
    _activo(uow, "Compresor", padre_id=maquina.id)
    _activo(uow, "Bomba", padre_id=maquina.id)
    arbol = act.arbol(uow.db, uow.tenant_id, maquina.id)
    assert {c["nombre"] for c in arbol["componentes"]} == {"Compresor", "Bomba"}


def test_un_ciclo_se_rechaza_al_moverlo(uow: UnidadDeTrabajo) -> None:
    """Un ciclo no falla al guardarlo: falla al recorrer el árbol, y para
    entonces el error aparece en un sitio que no tiene nada que ver."""
    padre = _activo(uow, "Máquina")
    hijo = _activo(uow, "Compresor", padre_id=padre.id)
    with pytest.raises(ErrorValidacion):
        act.mover_componente(uow, padre.id, nuevo_padre_id=hijo.id)
    with pytest.raises(ErrorValidacion):
        act.mover_componente(uow, hijo.id, nuevo_padre_id=hijo.id)


def test_mover_un_componente_deja_constancia_en_los_dos(uow: UnidadDeTrabajo) -> None:
    """Sin ese rastro, «este modelo falla a los dos años» deja de poder
    calcularse."""
    uno = _activo(uow, "Máquina A")
    dos = _activo(uow, "Máquina B")
    pieza = _activo(uow, "Compresor", padre_id=uno.id)
    act.mover_componente(uow, pieza.id, nuevo_padre_id=dos.id, motivo="Avería en B")

    de_la_pieza = act.historial(uow.db, uow.tenant_id, pieza.id)["eventos"]
    de_la_vieja = act.historial(uow.db, uow.tenant_id, uno.id)["eventos"]
    assert any(e["tipo"] == "componente" for e in de_la_pieza)
    assert any("retiró el componente" in e["descripcion"] for e in de_la_vieja)


def test_el_parque_del_cliente_no_trae_lo_retirado(uow: UnidadDeTrabajo) -> None:
    cuenta = uuid4()
    vivo = _activo(uow, "Vivo", cuenta_id=cuenta)
    muerto = _activo(uow, "Retirado", cuenta_id=cuenta)
    act.cambiar_estado(uow, muerto.id, estado="retirado", motivo="Fin de vida")
    parque = act.parque_de(uow.db, uow.tenant_id, cuenta)
    assert [p["id"] for p in parque] == [str(vivo.id)]


# ── Garantías (CRM-04.04.02.03) ───────────────────────────────────────────


def test_sin_garantias_no_se_dice_que_no_hay_cobertura(uow: UnidadDeTrabajo) -> None:
    """Un `false` por ausencia de datos factura al cliente que sí tenía
    cobertura, y esa factura llega antes que la corrección."""
    fila = _activo(uow)
    estado = act.cobertura_de(uow.db, uow.tenant_id, fila.id)
    assert estado["cubierto"] is False
    assert estado["concluyente"] is False
    assert "no se sabe" in estado["motivo"]


def test_una_garantia_que_no_cubre_nada_no_se_guarda(uow: UnidadDeTrabajo) -> None:
    fila = _activo(uow)
    with pytest.raises(ErrorValidacion):
        act.registrar_garantia(uow, fila.id, desde=_hoy(), hasta=_hoy() + timedelta(days=365))


def test_la_cobertura_va_por_concepto(uow: UnidadDeTrabajo) -> None:
    """Casi ninguna garantía cubre el desplazamiento, y esa es la conversación
    que se tiene en la puerta del cliente."""
    fila = _activo(uow)
    act.registrar_garantia(
        uow,
        fila.id,
        desde=_hoy() - timedelta(days=10),
        hasta=_hoy() + timedelta(days=365),
        cobertura=["piezas", "mano_obra"],
    )
    assert act.cobertura_de(uow.db, uow.tenant_id, fila.id, concepto="piezas")["cubierto"] is True
    viaje = act.cobertura_de(uow.db, uow.tenant_id, fila.id, concepto="desplazamiento")
    assert viaje["cubierto"] is False and viaje["concluyente"] is True


def test_una_garantia_vencida_lo_dice_con_su_fecha(uow: UnidadDeTrabajo) -> None:
    fila = _activo(uow)
    act.registrar_garantia(
        uow,
        fila.id,
        desde=_hoy() - timedelta(days=800),
        hasta=_hoy() - timedelta(days=30),
        cobertura=["piezas"],
    )
    estado = act.cobertura_de(uow.db, uow.tenant_id, fila.id)
    assert estado["cubierto"] is False and estado["concluyente"] is True
    assert "venció" in estado["motivo"]


def test_el_tope_de_uso_corta_antes_que_la_fecha(uow: UnidadDeTrabajo) -> None:
    """Una máquina a triple turno saldría cubierta el doble de lo pactado."""
    fila = _activo(uow, contador=Decimal(5000), unidad_contador="h")
    act.registrar_garantia(
        uow,
        fila.id,
        desde=_hoy() - timedelta(days=10),
        hasta=_hoy() + timedelta(days=365),
        cobertura=["piezas"],
        limite_contador=Decimal(4000),
    )
    estado = act.cobertura_de(uow.db, uow.tenant_id, fila.id)
    assert estado["cubierto"] is False and estado["concluyente"] is True


def test_gana_la_garantia_mas_especifica(uow: UnidadDeTrabajo) -> None:
    """Declarado y no por orden de inserción: el orden cambiaría al restaurar
    una copia."""
    fila = _activo(uow)
    act.registrar_garantia(
        uow,
        fila.id,
        desde=_hoy() - timedelta(days=10),
        hasta=_hoy() + timedelta(days=100),
        cobertura=["piezas"],
        tipo="fabricante",
    )
    act.registrar_garantia(
        uow,
        fila.id,
        desde=_hoy() - timedelta(days=10),
        hasta=_hoy() + timedelta(days=50),
        cobertura=["piezas"],
        tipo="contrato",
        proveedor="Nosotros",
    )
    estado = act.cobertura_de(uow.db, uow.tenant_id, fila.id)
    assert estado["tipo"] == "contrato"


def test_las_garantias_por_vencer_salen_ordenadas(uow: UnidadDeTrabajo) -> None:
    fila = _activo(uow)
    act.registrar_garantia(
        uow,
        fila.id,
        desde=_hoy() - timedelta(days=10),
        hasta=_hoy() + timedelta(days=20),
        cobertura=["piezas"],
    )
    act.registrar_garantia(
        uow,
        fila.id,
        desde=_hoy() - timedelta(days=10),
        hasta=_hoy() + timedelta(days=500),
        cobertura=["piezas"],
        tipo="extension",
    )
    salida = act.garantias_por_vencer(uow.db, uow.tenant_id, dias=60)
    assert len(salida["garantias"]) == 1
    assert salida["garantias"][0]["dias_restantes"] == 20


# ── Sustitución e historial (CRM-04.04.02.04) ─────────────────────────────


def test_sustituir_enlaza_los_dos_y_exige_motivo(uow: UnidadDeTrabajo) -> None:
    viejo = _activo(uow, "Vieja", numero_serie="SN-1")
    with pytest.raises(ErrorValidacion):
        act.sustituir(uow, viejo.id, nuevo_nombre="Nueva", motivo="")
    nuevo = act.sustituir(
        uow, viejo.id, nuevo_nombre="Nueva", numero_serie="SN-2", motivo="Avería irreparable"
    )
    assert nuevo.sustituye_a_id == viejo.id
    assert uow.db.get(act.ActivoInstalado, viejo.id).estado == "sustituido"


def test_las_garantias_no_se_heredan_sin_pedirlo(uow: UnidadDeTrabajo) -> None:
    """Heredarlas en silencio daría cobertura a una máquina que nadie aseguró."""
    viejo = _activo(uow, "Vieja", numero_serie="SN-1")
    act.registrar_garantia(
        uow,
        viejo.id,
        desde=_hoy() - timedelta(days=10),
        hasta=_hoy() + timedelta(days=300),
        cobertura=["piezas"],
    )
    nuevo = act.sustituir(uow, viejo.id, nuevo_nombre="Nueva", motivo="Avería")
    assert act.cobertura_de(uow.db, uow.tenant_id, nuevo.id)["concluyente"] is False

    otro_viejo = _activo(uow, "Vieja2", numero_serie="SN-9")
    act.registrar_garantia(
        uow,
        otro_viejo.id,
        desde=_hoy() - timedelta(days=10),
        hasta=_hoy() + timedelta(days=300),
        cobertura=["piezas"],
    )
    heredado = act.sustituir(
        uow,
        otro_viejo.id,
        nuevo_nombre="Nueva2",
        motivo="Avería",
        heredar_garantias=True,
    )
    assert act.cobertura_de(uow.db, uow.tenant_id, heredado.id)["cubierto"] is True


def test_el_historial_trae_lo_del_equipo_anterior_marcado(uow: UnidadDeTrabajo) -> None:
    """La pregunta real es «¿esto ya había fallado antes?», y la respuesta suele
    estar en el equipo anterior — pero contarlo como de este infla su tasa de
    avería."""
    viejo = _activo(uow, "Vieja", numero_serie="SN-1")
    act.anotar(
        uow.db,
        tenant_id=uow.tenant_id,
        activo_id=viejo.id,
        tipo="intervencion",
        descripcion="Cambio de junta",
    )
    nuevo = act.sustituir(uow, viejo.id, nuevo_nombre="Nueva", motivo="Avería")
    historial = act.historial(uow.db, uow.tenant_id, nuevo.id)
    ajenos = [e for e in historial["eventos"] if e["de_equipo_anterior"]]
    assert any("junta" in e["descripcion"] for e in ajenos)
    assert len(historial["equipos_en_la_cadena"]) == 2


def test_el_historial_es_append_only(uow: UnidadDeTrabajo) -> None:
    """Si se reconstruyera desde las órdenes, editarlas reescribiría el pasado."""
    fila = _activo(uow)
    act.anotar(
        uow.db,
        tenant_id=uow.tenant_id,
        activo_id=fila.id,
        tipo="intervencion",
        descripcion="Revisión",
        origen="orden_trabajo",
        origen_id=uuid4(),
    )
    antes = len(act.historial(uow.db, uow.tenant_id, fila.id)["eventos"])
    act.cambiar_estado(uow, fila.id, estado="en_reparacion")
    despues = act.historial(uow.db, uow.tenant_id, fila.id)["eventos"]
    assert len(despues) == antes + 1
    assert any(e["descripcion"] == "Revisión" for e in despues)
