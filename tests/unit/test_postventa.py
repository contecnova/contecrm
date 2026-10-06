"""Postventa: devoluciones, resoluciones y expedientes (CRM-04.05.01).

Las pruebas van detrás de los cinco sitios por donde se pierde el dinero o la
razón en una devolución:

  * el material que vuelve y se cierra sin decir qué se hizo con él,
  * la devolución fuera de plazo autorizada en silencio,
  * el abono que el CRM da por hecho y el ERP nunca emitió,
  * la reclamación que se contesta tarde porque el plazo se contó desde que se
    grabó,
  * y la suspensión del plazo legal por «mucho trabajo».
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion
from crmcore.fechas import hoy

from services.service import activos as act
from services.service import postventa as pv


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _devolucion(uow: UnidadDeTrabajo, **kw: Any) -> pv.Devolucion:
    base: dict[str, Any] = {"motivo": "llego_roto", "comprado_el": hoy(uow.db)}
    base.update(kw)
    fila, _ = pv.solicitar(uow, **base)
    return fila


def _hasta_recibida(uow: UnidadDeTrabajo, **kw: Any) -> pv.Devolucion:
    fila = _devolucion(uow, lineas=[{"concepto": "Bomba", "cantidad": 1}], **kw)
    pv.autorizar(uow, fila.id)
    pv.recibir(uow, fila.id)
    return fila


# ── Devoluciones (CRM-04.05.01.01) ────────────────────────────────────────


def test_la_devolucion_nace_solicitada_y_sin_rma_util(uow: UnidadDeTrabajo) -> None:
    """Todavía no autoriza nada: el almacén no espera ese paquete."""
    fila = _devolucion(uow)
    assert fila.estado == "solicitada"
    assert fila.codigo and fila.codigo.startswith("RMA-")


def test_una_devolucion_sin_motivo_no_se_registra(uow: UnidadDeTrabajo) -> None:
    with pytest.raises(ErrorValidacion):
        pv.solicitar(uow, motivo="   ")


def test_sin_fecha_de_compra_el_plazo_no_concluye(uow: UnidadDeTrabajo) -> None:
    """Tomarlo por fuera de plazo rechaza devoluciones legítimas por un dato que
    falta en nuestro sistema, no en el del cliente."""
    fila = _devolucion(uow, comprado_el=None)
    ventana = pv.dentro_de_ventana(uow.db, fila)
    assert ventana["concluyente"] is False
    # Y por eso se autoriza sin pedir excepción.
    autorizada, _ = pv.autorizar(uow, fila.id)
    assert autorizada.estado == "autorizada" and autorizada.fuera_de_plazo is False


def test_fuera_de_ventana_hace_falta_forzar_con_motivo(uow: UnidadDeTrabajo) -> None:
    """Si pasa en silencio, la ventana no significa nada y nadie puede medir
    cuánto se está regalando."""
    fila = _devolucion(uow, comprado_el=hoy(uow.db) - timedelta(days=400))
    with pytest.raises(Conflicto):
        pv.autorizar(uow, fila.id)
    with pytest.raises(ErrorValidacion):
        pv.autorizar(uow, fila.id, forzar=True)
    autorizada, ventana = pv.autorizar(
        uow, fila.id, forzar=True, motivo_excepcion="Cliente grande, decisión comercial"
    )
    assert autorizada.fuera_de_plazo is True
    assert autorizada.motivo_excepcion
    assert ventana["dentro"] is False


def test_una_serie_que_no_consta_instalada_avisa(uow: UnidadDeTrabajo) -> None:
    """Puede ser material sin dar de alta, o una serie que no es nuestra."""
    _, avisos = pv.solicitar(
        uow,
        motivo="averia",
        comprado_el=hoy(uow.db),
        lineas=[{"concepto": "Bomba", "numero_serie": "SN-DESCONOCIDA"}],
    )
    assert any("no consta como activo instalado" in a for a in avisos)


def test_rechazar_exige_motivo(uow: UnidadDeTrabajo) -> None:
    fila = _devolucion(uow)
    with pytest.raises(ErrorValidacion):
        pv.rechazar(uow, fila.id, motivo="")
    assert pv.rechazar(uow, fila.id, motivo="Fuera de garantía").estado == "rechazada"


def test_recibir_dice_las_diferencias_con_lo_autorizado(uow: UnidadDeTrabajo) -> None:
    """Se autorizan tres, llegan dos, y la tercera aparece meses después en un
    descuadre que nadie sabe explicar."""
    fila = _devolucion(uow, lineas=[{"concepto": "Bomba", "cantidad": 3}])
    pv.autorizar(uow, fila.id)
    linea = uow.db.execute(
        pv.select(pv.LineaDevolucion).where(pv.LineaDevolucion.devolucion_id == fila.id)
    ).scalar_one()
    _, informe = pv.recibir(uow, fila.id, recibido=[{"linea_id": str(linea.id), "cantidad": 2}])
    assert informe["sin_diferencias"] is False
    assert informe["diferencias"][0]["esperado"] == "3.000"


def test_recibir_sin_anotar_que_llego_tambien_es_una_diferencia(
    uow: UnidadDeTrabajo,
) -> None:
    fila = _hasta_recibida(uow)
    _, informe = pv.recibir(uow, fila.id)
    assert informe["diferencias"][0]["porque"] == "no se ha anotado qué llegó"


def test_no_se_cierra_sin_decir_que_se_hace_con_el_material(
    uow: UnidadDeTrabajo,
) -> None:
    """Una devolución cerrada sin disposición es una pieza que consta devuelta y
    que nadie ha vuelto a ver."""
    fila = _hasta_recibida(uow)
    pv.inspeccionar(uow, fila.id, inspeccion="Carcasa rota")
    with pytest.raises(ErrorValidacion):
        pv.cerrar(uow, fila.id, disposicion="pendiente")
    cerrada = pv.cerrar(uow, fila.id, disposicion="chatarra")
    assert cerrada.estado == "cerrada" and cerrada.disposicion == "chatarra"


def test_cerrar_una_devolucion_de_activo_lo_retira_del_parque(
    uow: UnidadDeTrabajo,
) -> None:
    """Si no, el parque del cliente sigue contando algo que está en nuestro
    almacén o destruido."""
    activo, _ = act.crear(uow, nombre="Bomba", cuenta_id=uuid4())
    fila = _hasta_recibida(uow, activo_id=activo.id)
    pv.inspeccionar(uow, fila.id, inspeccion="No reparable")
    pv.cerrar(uow, fila.id, disposicion="chatarra")
    assert uow.db.get(act.ActivoInstalado, activo.id).estado == "retirado"


# ── Resoluciones (CRM-04.05.01.02) ────────────────────────────────────────


def test_el_abono_se_queda_en_solicitado(uow: UnidadDeTrabajo) -> None:
    """Darlo por hecho dejaría al cliente esperando un dinero que nadie ha
    emitido, y dos contabilidades que no cuadran."""
    fila = _hasta_recibida(uow)
    resolucion, _ = pv.resolver(uow, fila.id, tipo="abono", importe=Decimal(120))
    assert resolucion.estado_abono == "solicitado"


def test_un_abono_sin_importe_no_se_tramita(uow: UnidadDeTrabajo) -> None:
    fila = _hasta_recibida(uow)
    with pytest.raises(ErrorValidacion):
        pv.resolver(uow, fila.id, tipo="abono")


def test_no_se_cierra_con_un_abono_pendiente(uow: UnidadDeTrabajo) -> None:
    fila = _hasta_recibida(uow)
    resolucion, _ = pv.resolver(uow, fila.id, tipo="abono", importe=Decimal(120))
    with pytest.raises(Conflicto):
        pv.cerrar(uow, fila.id, disposicion="reacondicionar")
    pv.confirmar_abono(uow, resolucion.id, confirmado=True, referencia="AB-2026-9")
    assert pv.cerrar(uow, fila.id, disposicion="reacondicionar").estado == "cerrada"


def test_un_abono_rechazado_sin_motivo_se_vuelve_a_mandar_igual(
    uow: UnidadDeTrabajo,
) -> None:
    fila = _hasta_recibida(uow)
    resolucion, _ = pv.resolver(uow, fila.id, tipo="abono", importe=Decimal(50))
    with pytest.raises(ErrorValidacion):
        pv.confirmar_abono(uow, resolucion.id, confirmado=False)
    actualizada = pv.confirmar_abono(
        uow, resolucion.id, confirmado=False, motivo="Factura ya rectificada"
    )
    assert actualizada.estado_abono == "rechazado" and actualizada.motivo_rechazo_externo


def test_resolver_dos_veces_la_misma_linea_avisa(uow: UnidadDeTrabajo) -> None:
    """Reparar y abonar lo mismo acaba en una factura mal, y aquí todavía se
    puede deshacer."""
    fila = _hasta_recibida(uow)
    pv.resolver(uow, fila.id, tipo="reparacion")
    _, avisos = pv.resolver(uow, fila.id, tipo="abono", importe=Decimal(10))
    assert any("ya tenía resolución" in a for a in avisos)


def test_una_sustitucion_sin_sustituto_avisa(uow: UnidadDeTrabajo) -> None:
    fila = _hasta_recibida(uow)
    _, avisos = pv.resolver(uow, fila.id, tipo="sustitucion")
    assert any("parque instalado" in a for a in avisos)


def test_a_cargo_de_solo_admite_los_tres_valores(uow: UnidadDeTrabajo) -> None:
    fila = _hasta_recibida(uow)
    with pytest.raises(ErrorValidacion):
        pv.resolver(uow, fila.id, tipo="reparacion", a_cargo_de="el_vecino")


# ── Expedientes y plazos legales (CRM-04.05.01.03) ────────────────────────


def _hace(dias: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=dias)


def test_el_plazo_cuenta_desde_que_entro_no_desde_que_se_graba(
    uow: UnidadDeTrabajo,
) -> None:
    """Esa diferencia es el tiempo que estuvo en un cajón, y se la come la
    empresa, no el cliente."""
    fila, avisos = pv.abrir_expediente(
        uow, asunto="Reclamación de consumo", entrada_at=_hace(5), plazo_dias=30
    )
    assert fila.vence_at.astimezone(timezone.utc) < datetime.now(timezone.utc) + timedelta(days=26)
    assert any("ya se ha consumido del plazo" in a for a in avisos)


def test_una_entrada_en_el_futuro_se_rechaza(uow: UnidadDeTrabajo) -> None:
    with pytest.raises(ErrorValidacion):
        pv.abrir_expediente(
            uow,
            asunto="Del futuro",
            entrada_at=datetime.now(timezone.utc) + timedelta(days=10),
        )


def test_sin_calendario_los_dias_habiles_se_cuentan_naturales_y_se_dice(
    uow: UnidadDeTrabajo,
) -> None:
    """Dejar que parezca lo mismo es cómo un plazo de «diez días hábiles» vence
    en Navidad sin que nadie lo entienda."""
    _, avisos = pv.abrir_expediente(
        uow,
        asunto="Hoja de reclamaciones",
        entrada_at=_hace(0),
        plazo_dias=10,
        plazo_habiles=True,
    )
    assert any("días naturales" in a for a in avisos)


def test_la_suspension_solo_admite_motivos_tipificados(uow: UnidadDeTrabajo) -> None:
    """Con texto libre, el plazo se suspendería por «mucho trabajo» y dejaría de
    ser un plazo."""
    fila, _ = pv.abrir_expediente(uow, asunto="Reclamación", entrada_at=_hace(1))
    with pytest.raises(ErrorValidacion):
        pv.suspender(uow, fila.id, motivo="mucho_trabajo")
    suspendido = pv.suspender(uow, fila.id, motivo="prueba_pericial")
    assert suspendido.estado == "suspendido"


def test_reanudar_desplaza_el_vencimiento_lo_que_estuvo_parado(
    uow: UnidadDeTrabajo,
) -> None:
    """Dejarlo donde estaba haría que una suspensión legítima se comiera el plazo
    de respuesta."""
    fila, _ = pv.abrir_expediente(uow, asunto="Reclamación", entrada_at=_hace(1))
    vencia = fila.vence_at
    pv.suspender(uow, fila.id, motivo="subsanacion_solicitada")
    fila.suspendido_desde = datetime.now(timezone.utc) - timedelta(days=3)
    uow.db.flush()
    reanudado = pv.reanudar(uow, fila.id)
    assert reanudado.estado == "abierto"
    assert reanudado.vence_at.astimezone(timezone.utc) > vencia.astimezone(
        timezone.utc
    ) + timedelta(days=2)
    assert reanudado.suspendido_seg > 0


def test_responder_dice_si_fue_en_plazo_y_si_se_puede_demostrar(
    uow: UnidadDeTrabajo,
) -> None:
    """Sin acuse de recibo, «en plazo» es nuestra palabra contra la suya."""
    fila, _ = pv.abrir_expediente(uow, asunto="Reclamación", entrada_at=_hace(1), plazo_dias=30)
    salida = pv.responder(uow, fila.id, respuesta="Se abona el importe", resultado="estimada")
    assert salida["en_plazo"] is True
    assert salida["demostrable"] is False

    otro, _ = pv.abrir_expediente(uow, asunto="Otra", entrada_at=_hace(1), plazo_dias=30)
    pv.acusar_recibo(uow, otro.id)
    con_acuse = pv.responder(uow, otro.id, respuesta="Contestada")
    assert con_acuse["demostrable"] is True


def test_responder_fuera_de_plazo_lo_dice(uow: UnidadDeTrabajo) -> None:
    fila, _ = pv.abrir_expediente(uow, asunto="Reclamación", entrada_at=_hace(60), plazo_dias=30)
    salida = pv.responder(uow, fila.id, respuesta="Tarde")
    assert salida["en_plazo"] is False


def test_responder_exige_la_respuesta_dada(uow: UnidadDeTrabajo) -> None:
    fila, _ = pv.abrir_expediente(uow, asunto="Reclamación", entrada_at=_hace(1))
    with pytest.raises(ErrorValidacion):
        pv.responder(uow, fila.id, respuesta="   ")


def test_los_vencidos_van_aparte_de_los_que_vencen_pronto(uow: UnidadDeTrabajo) -> None:
    """Mezclarlos hace leer un incumplimiento como cola de trabajo."""
    pv.abrir_expediente(uow, asunto="Vencido", entrada_at=_hace(60), plazo_dias=30)
    pv.abrir_expediente(uow, asunto="Pronto", entrada_at=_hace(29.5), plazo_dias=30)
    salida = pv.vencen_pronto(uow.db, uow.tenant_id, horas=48)
    assert [e["asunto"] for e in salida["ya_vencidos"]] == ["Vencido"]
    assert [e["asunto"] for e in salida["vencen_pronto"]] == ["Pronto"]


def test_un_expediente_suspendido_se_ve_como_suspendido(uow: UnidadDeTrabajo) -> None:
    """Quien lo mire tiene que ver que está parado y no asumir que va tarde."""
    fila, _ = pv.abrir_expediente(uow, asunto="Parado", entrada_at=_hace(29.5), plazo_dias=30)
    pv.suspender(uow, fila.id, motivo="traslado_a_tercero")
    salida = pv.vencen_pronto(uow.db, uow.tenant_id, horas=48)
    assert salida["suspendidos"] == 1
    assert salida["vencen_pronto"][0]["suspendido"] is True
