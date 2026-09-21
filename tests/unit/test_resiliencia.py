"""Que un tenant saturado no arrastre a los demás
(CRM-00.01.06.03, CRM-00.01.06.04, CRM-00.06.02.07).

Las cuotas dicen cuánto puede consumir cada cliente al mes. Esto es otra cosa:
qué pasa ahora mismo cuando uno satura un recurso compartido. Las cuotas no lo
ven, porque nadie ha superado la suya — simplemente están todos pidiendo a la
vez.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from crmcore import resiliencia
from crmcore.errors import NoDisponible


@pytest.fixture(autouse=True)
def _limpio() -> Any:
    resiliencia.reiniciar()
    yield
    resiliencia.reiniciar()


# ── Mamparos ──────────────────────────────────────────────────────────────


def test_la_mampara_es_por_tenant_y_no_global() -> None:
    """Un tope global protege el sistema y NO protege a los clientes entre sí,
    que es el problema de verdad en multi-tenant."""
    uno, otro = uuid4(), uuid4()

    with resiliencia.mampara("importacion", uno, tope=1):
        # El de al lado sigue pudiendo trabajar aunque el primero tenga el suyo
        # ocupado del todo.
        with resiliencia.mampara("importacion", otro, tope=1):
            pass


def test_pasado_el_tope_se_rechaza_con_un_mensaje_que_dice_qué_hacer() -> None:
    tenant = uuid4()
    with resiliencia.mampara("importacion", tenant, tope=1):
        with pytest.raises(NoDisponible) as e:
            with resiliencia.mampara("importacion", tenant, tope=1):
                pass
    assert e.value.error_code == "resiliencia.mampara_llena"


def test_la_mampara_se_libera_aunque_la_operacion_falle() -> None:
    """Si no, un error deja el cupo ocupado para siempre y el tenant se queda
    sin poder trabajar hasta que alguien reinicie el proceso."""
    tenant = uuid4()
    with pytest.raises(RuntimeError):
        with resiliencia.mampara("importacion", tenant, tope=1):
            raise RuntimeError("algo")
    with resiliencia.mampara("importacion", tenant, tope=1):
        pass


# ── Cortacircuitos ────────────────────────────────────────────────────────


def test_el_circuito_se_abre_tras_los_fallos_seguidos() -> None:
    """Reintentar contra algo caído no lo arregla y sí consume el hilo que lo
    intenta: es como una caída se convierte en una caída total."""
    for _ in range(3):
        with pytest.raises(RuntimeError):
            with resiliencia.circuito("erp", umbral=3, descanso_s=60):
                raise RuntimeError("no responde")

    with pytest.raises(NoDisponible) as e:
        with resiliencia.circuito("erp", umbral=3, descanso_s=60):
            pass
    assert e.value.error_code == "resiliencia.circuito_abierto"


def test_un_exito_borra_el_historial_de_fallos() -> None:
    """Contar fallos acumulados abriría el circuito de un recurso que va bien
    simplemente porque lleva meses funcionando."""
    for _ in range(2):
        with pytest.raises(RuntimeError):
            with resiliencia.circuito("erp", umbral=3):
                raise RuntimeError("x")
    with resiliencia.circuito("erp", umbral=3):
        pass
    with pytest.raises(RuntimeError):
        with resiliencia.circuito("erp", umbral=3):
            raise RuntimeError("x")
    # Van 1 desde el éxito, así que sigue cerrado.
    with resiliencia.circuito("erp", umbral=3):
        pass


def test_al_cerrarse_el_circuito_queda_a_un_fallo_de_reabrirse() -> None:
    """Si siguiera roto, volver a cero obligaría a fallar el umbral entero otra
    vez — y eso son N veces el mismo timeout para todos los que pasen."""
    for _ in range(2):
        with pytest.raises(RuntimeError):
            with resiliencia.circuito("erp", umbral=2, descanso_s=0.01):
                raise RuntimeError("x")
    import time

    time.sleep(0.02)
    assert resiliencia.circuito_abierto("erp") is False
    with pytest.raises(RuntimeError):
        with resiliencia.circuito("erp", umbral=2, descanso_s=0.01):
            raise RuntimeError("x")
    assert resiliencia.circuito_abierto("erp") is True


# ── Degradación ───────────────────────────────────────────────────────────


def test_lo_critico_no_cae_nunca() -> None:
    """Rechazar una escritura de cliente y un recálculo de previsión con el
    mismo criterio es tratar como iguales dos cosas que no lo son."""
    resiliencia.fijar_presion(1.0)
    assert resiliencia.admite(resiliencia.CRITICA) is True
    assert resiliencia.admite(resiliencia.NORMAL) is False
    assert resiliencia.admite(resiliencia.DIFERIBLE) is False


def test_lo_diferible_cae_primero() -> None:
    resiliencia.fijar_presion(0.7)
    assert resiliencia.admite(resiliencia.NORMAL) is True
    assert resiliencia.admite(resiliencia.DIFERIBLE) is False


def test_el_rechazo_dice_que_se_ha_diferido_y_por_qué() -> None:
    resiliencia.fijar_presion(1.0)
    with pytest.raises(NoDisponible) as e:
        resiliencia.exigir(resiliencia.DIFERIBLE)
    assert e.value.error_code == "resiliencia.diferida"
    assert e.value.detalle["presion"] == 1.0


# ── Modo solo lectura ─────────────────────────────────────────────────────


def test_en_modo_degradado_se_lee_pero_no_se_escribe() -> None:
    """Convierte una avería de la base primaria en «no se puede guardar» en vez
    de en «el CRM no funciona»: el comercial que está delante de un cliente
    sigue viendo su ficha."""
    resiliencia.entrar_en_solo_lectura("réplica primaria caída")
    with pytest.raises(NoDisponible) as e:
        resiliencia.exigir_escritura()
    assert e.value.error_code == "resiliencia.solo_lectura"
    # El motivo va en el mensaje: sin él, el usuario cree que su cambio tenía
    # algo malo y lo reintenta cambiándolo, que es cómo se pierde trabajo.
    assert "réplica primaria" in str(e.value)

    resiliencia.salir_de_solo_lectura()
    resiliencia.exigir_escritura()


def test_el_estado_dice_lo_que_esta_pasando() -> None:
    resiliencia.entrar_en_solo_lectura("mantenimiento")
    resiliencia.fijar_presion(0.5)
    estado = resiliencia.estado()
    assert estado["solo_lectura"] is True
    assert estado["presion"] == 0.5
    assert estado["motivo"] == "mantenimiento"
