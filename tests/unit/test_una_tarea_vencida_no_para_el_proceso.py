"""Una tarea humana vencida no deja el proceso parado para siempre (FUN-A-6).

Auditoría 13-11-2026: el worker solo cambiaba la tarea vencida a «escalada» o
«caducada». Salía de la bandeja, nadie podía responderla y la instancia seguía
en «esperando_humano» sin que nada la despertara. «Escalar», documentado en el
propio motor, no reasignaba nada.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from services.orchestrator.modelos import DefinicionProceso, TareaHumana
from services.orchestrator.motor import Motor, validar_definicion


def _definicion(**humano: Any) -> dict[str, Any]:
    return {
        "inicio": "aprobar",
        "pasos": {
            "aprobar": {
                "tipo": "humano",
                "titulo": "Aprobar",
                "asignada_rol": "responsable_ventas",
                "vence_en_horas": 48,
                "rutas": {"aprobar": "fin_ok", "rechazar": "fin_no"},
                **humano,
            },
            "fin_ok": {"tipo": "fin", "resultado": "aprobado"},
            "fin_no": {"tipo": "fin", "resultado": "rechazado"},
        },
    }


def _arrancar(db: Any, tenant_id: UUID, definicion: dict[str, Any]) -> tuple[Any, Any, Motor]:
    db.add(
        DefinicionProceso(
            tenant_id=tenant_id,
            clave="aprobacion",
            version=1,
            nombre="aprobacion",
            definicion=definicion,
            estado="publicada",
        )
    )
    db.flush()
    motor = Motor(db)
    instancia = motor.arrancar(tenant_id=tenant_id, clave="aprobacion", variables={})
    motor.avanzar(instancia)
    tarea = db.query(TareaHumana).filter_by(instancia_id=instancia.id).one()
    tarea.vence_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.flush()
    return instancia, tarea, motor


def test_escalar_reasigna_y_la_tarea_sigue_viva(db: Any, tenant_id: UUID) -> None:
    instancia, tarea, motor = _arrancar(
        db, tenant_id, _definicion(al_vencer="escalar", escalar_a_rol="direccion_comercial")
    )
    assert motor.vencer_tarea(tarea) == "escalada"
    assert tarea.estado == "pendiente"
    assert tarea.asignada_rol == "direccion_comercial"
    assert tarea.vence_at > datetime.now(timezone.utc)
    assert instancia.estado == "esperando_humano"
    # Se escala una vez: al volver a vencer, sin `si_vence`, falla diciéndolo.
    tarea.vence_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    assert motor.vencer_tarea(tarea) == "fallida"
    assert instancia.estado == "fallida"


def test_si_vence_reanuda_el_proceso_por_su_paso(db: Any, tenant_id: UUID) -> None:
    instancia, tarea, motor = _arrancar(db, tenant_id, _definicion(si_vence="fin_no"))
    assert motor.vencer_tarea(tarea) == "seguir"
    assert tarea.estado == "caducada"
    motor.avanzar(instancia)
    assert instancia.estado == "completada"
    assert instancia.variables["resultado"] == "rechazado"
    assert instancia.variables["aprobar_respuesta"] == "vencida"


def test_sin_decir_que_hacer_falla_y_lo_explica(db: Any, tenant_id: UUID) -> None:
    instancia, tarea, motor = _arrancar(db, tenant_id, _definicion())
    assert motor.vencer_tarea(tarea) == "fallida"
    assert instancia.estado == "fallida"
    assert "si_vence" in (instancia.error or "")


def test_el_worker_usa_el_motor_para_vencer(db: Any, tenant_id: UUID) -> None:
    from services.orchestrator.worker import _vencer_tareas

    instancia, _, _ = _arrancar(db, tenant_id, _definicion(si_vence="fin_no"))
    assert _vencer_tareas(db) >= 1
    assert instancia.estado == "ejecutando"


def test_el_validador_exige_a_quien_escalar_y_que_si_vence_exista() -> None:
    sin_destino = validar_definicion(_definicion(al_vencer="escalar"))
    assert any("a quién" in p for p in sin_destino), sin_destino
    roto = validar_definicion(_definicion(si_vence="no_existe"))
    assert any("si_vence" in p for p in roto), roto
    raro = validar_definicion(_definicion(al_vencer="borrar"))
    assert any("al_vencer" in p for p in raro), raro
    assert (
        validar_definicion(
            _definicion(al_vencer="escalar", escalar_a_rol="direccion", si_vence="fin_no")
        )
        == []
    )
