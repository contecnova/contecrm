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


def test_responder_relee_la_tarea_bloqueada(db: Any, tenant_id: UUID) -> None:
    """FUN-A-16: dos respuestas a la vez se pisaban. Se lee con FOR UPDATE, y la
    segunda ve lo que dejó la primera aunque su objeto en memoria esté viejo."""
    import pytest
    from crmcore.errors import Conflicto
    from crmcore.ids import nuevo_id

    instancia, tarea, motor = _arrancar(db, tenant_id, _definicion())
    db.execute(
        TareaHumana.__table__.update().where(TareaHumana.id == tarea.id).values(estado="completada")
    )
    tarea.estado = "pendiente"  # lo que cree quien llega segundo
    with pytest.raises(Conflicto) as fallo:
        motor.responder_tarea(tarea, respuesta="aprobar", usuario_id=nuevo_id())
    assert fallo.value.error_code == "tarea.ya_resuelta"


def test_un_fallo_transitorio_de_la_base_no_falla_el_proceso() -> None:
    """FUN-A-17: un corte de conexión o un deadlock marcaban la instancia
    «fallida» para siempre. Se distinguen de un fallo del proceso."""
    from sqlalchemy.exc import DBAPIError, OperationalError

    from services.orchestrator.worker import _es_transitorio

    class _Origen(Exception):
        def __init__(self, sqlstate: str) -> None:
            self.sqlstate = sqlstate

    assert _es_transitorio(OperationalError("SELECT 1", {}, Exception("se cayó")))
    assert _es_transitorio(DBAPIError("SELECT 1", {}, _Origen("40P01")))
    assert _es_transitorio(DBAPIError("SELECT 1", {}, _Origen("40001")))
    assert not _es_transitorio(DBAPIError("SELECT 1", {}, _Origen("23505")))
    assert not _es_transitorio(ValueError("un paso mal escrito"))


def test_una_instancia_que_ya_tiene_otro_worker_no_se_avanza(monkeypatch: Any) -> None:
    """FUN-A-18: si un avance tardaba más que el alquiler de la toma, otro worker
    la volvía a tomar y las dos réplicas ejecutaban los mismos pasos. Ahora se
    relee con FOR UPDATE y, si ya no es nuestra, no se toca."""
    from types import SimpleNamespace

    from crmcore.ids import nuevo_id

    from services.orchestrator import worker

    pedidas: list[dict[str, Any]] = []

    class _Sesion:
        deshecha = False

        def get(self, _modelo: Any, _id: Any, **opciones: Any) -> Any:
            pedidas.append(opciones)
            return SimpleNamespace(tomada_por="worker-b", tenant_id=nuevo_id())

        def rollback(self) -> None:
            self.deshecha = True

    def _no_debe_avanzar(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("ha avanzado una instancia que ya era de otro worker")

    monkeypatch.setattr(worker, "Motor", _no_debe_avanzar)
    sesion = _Sesion()
    worker._avanzar_en(sesion, nuevo_id(), "worker-a", {})

    assert pedidas == [{"with_for_update": True}]
    assert sesion.deshecha
