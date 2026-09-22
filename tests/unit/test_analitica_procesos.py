"""Vista de la instancia sobre el gráfico y analítica del flujo
(CRM-00.03.05.14, CRM-00.03.05.16).

Lo que se prueba aquí no es que los números salgan: es que **no engañen**. Un
cuello de botella deducido de tres ejecuciones, o una media que no describe a
ninguna instancia, llevan a rediseñar un flujo que funcionaba.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest
from crmcore.errors import NoEncontrado

from services.orchestrator import analitica as ana
from services.orchestrator.modelos import DefinicionProceso, TareaHumana
from services.orchestrator.motor import Motor


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _publicar(db: Any, tenant_id: UUID, clave: str, definicion: dict[str, Any]) -> None:
    db.add(
        DefinicionProceso(
            tenant_id=tenant_id,
            clave=clave,
            version=1,
            nombre=clave,
            definicion=definicion,
            estado="publicada",
        )
    )
    db.flush()


CON_TAREA = {
    "inicio": "pedir_visto_bueno",
    "pasos": {
        "pedir_visto_bueno": {
            "tipo": "humano",
            "titulo": "Aprobar el descuento",
            "rutas": {"aprobar": "fin", "rechazar": "fin_no"},
        },
        "fin": {"tipo": "fin", "resultado": "aprobado"},
        "fin_no": {"tipo": "fin", "resultado": "rechazado"},
    },
}


# ── La vista sobre el gráfico (CRM-00.03.05.14) ───────────────────────────


def test_el_grafico_dice_por_donde_va(db: Any, tenant_id: UUID) -> None:
    _publicar(db, tenant_id, "descuento", CON_TAREA)
    motor = Motor(db)
    instancia = motor.arrancar(tenant_id=tenant_id, clave="descuento")
    motor.avanzar(instancia)

    vista = ana.vista_de_instancia(db, tenant_id, instancia.id)
    estados = {n["paso"]: n["estado"] for n in vista["nodos"]}
    assert estados["pedir_visto_bueno"] == "actual"
    assert estados["fin"] == "pendiente"


def test_el_grafico_trae_la_tarea_que_bloquea(db: Any, tenant_id: UUID) -> None:
    """Sin ella, quien mira el lienzo ve un nodo encendido y tiene que ir a otra
    pantalla a saber a quién está esperando."""
    _publicar(db, tenant_id, "descuento", CON_TAREA)
    motor = Motor(db)
    instancia = motor.arrancar(tenant_id=tenant_id, clave="descuento")
    motor.avanzar(instancia)

    nodo = next(
        n
        for n in ana.vista_de_instancia(db, tenant_id, instancia.id)["nodos"]
        if n["paso"] == "pedir_visto_bueno"
    )
    assert nodo["tarea_pendiente"]["titulo"] == "Aprobar el descuento"


def test_el_grafico_dice_con_que_version_se_pinta(db: Any, tenant_id: UUID) -> None:
    """Sin la versión, quien lo mira no sabe si está viendo el proceso que se
    ejecutó o el que se publicó después."""
    _publicar(db, tenant_id, "descuento", CON_TAREA)
    motor = Motor(db)
    instancia = motor.arrancar(tenant_id=tenant_id, clave="descuento")
    motor.avanzar(instancia)
    assert ana.vista_de_instancia(db, tenant_id, instancia.id)["version"] == 1


def test_un_camino_no_tomado_no_se_dice_pendiente(db: Any, tenant_id: UUID) -> None:
    """Si la instancia ya terminó, decir «pendiente» haría pensar que falta
    hacerlo."""
    _publicar(db, tenant_id, "descuento", CON_TAREA)
    motor = Motor(db)
    instancia = motor.arrancar(tenant_id=tenant_id, clave="descuento")
    motor.avanzar(instancia)

    from sqlalchemy import select

    tarea = (
        db.execute(select(TareaHumana).where(TareaHumana.instancia_id == instancia.id))
        .scalars()
        .one()
    )
    motor.responder_tarea(tarea, respuesta="aprobar", usuario_id=tenant_id)
    motor.avanzar(instancia)

    estados = {
        n["paso"]: n["estado"] for n in ana.vista_de_instancia(db, tenant_id, instancia.id)["nodos"]
    }
    assert estados["fin_no"] == "no_recorrido"


def test_una_instancia_de_otro_tenant_no_se_ve(db: Any, tenant_id: UUID) -> None:
    from uuid import uuid4

    with pytest.raises(NoEncontrado):
        ana.vista_de_instancia(db, tenant_id, uuid4())


# ── Analítica del flujo (CRM-00.03.05.16) ─────────────────────────────────


def test_sin_ejecuciones_no_se_inventa_un_informe(db: Any, tenant_id: UUID) -> None:
    salida = ana.analitica_de_proceso(db, tenant_id, "no_existe")
    assert salida["instancias"] == 0
    assert salida["concluyente"] is False
    assert "nada que medir" in salida["aviso"]


def test_con_pocas_ejecuciones_se_dice_que_no_es_concluyente(db: Any, tenant_id: UUID) -> None:
    """Un cuello de botella deducido de tres ejecuciones lleva a rediseñar un
    flujo que funcionaba."""
    _publicar(db, tenant_id, "descuento", CON_TAREA)
    motor = Motor(db)
    for _ in range(3):
        instancia = motor.arrancar(tenant_id=tenant_id, clave="descuento")
        motor.avanzar(instancia)

    salida = ana.analitica_de_proceso(db, tenant_id, "descuento")
    assert salida["instancias"] == 3
    assert salida["concluyente"] is False
    assert "no basta para rediseñar" in salida["aviso"]


def test_el_paso_humano_se_mide_por_la_espera_y_no_por_el_motor(db: Any, tenant_id: UUID) -> None:
    """Medir el motor da milisegundos en todos los pasos y esconde los tres días
    que esperó la firma, que es el único número que importa."""
    _publicar(db, tenant_id, "descuento", CON_TAREA)
    motor = Motor(db)
    instancia = motor.arrancar(tenant_id=tenant_id, clave="descuento")
    motor.avanzar(instancia)

    from sqlalchemy import select

    tarea = (
        db.execute(select(TareaHumana).where(TareaHumana.instancia_id == instancia.id))
        .scalars()
        .one()
    )
    tarea.completada_at = _ahora()
    tarea.created_at = _ahora() - timedelta(hours=72)
    tarea.estado = "completada"
    tarea.completada_por = tenant_id
    db.flush()

    paso = next(
        p
        for p in ana.analitica_de_proceso(db, tenant_id, "descuento")["pasos"]
        if p["paso"] == "pedir_visto_bueno"
    )
    assert paso["espera_horas_media"] == 72.0
    assert paso["espera_horas_mediana"] == 72.0


def test_el_cuello_de_botella_sale_señalado(db: Any, tenant_id: UUID) -> None:
    _publicar(db, tenant_id, "descuento", CON_TAREA)
    motor = Motor(db)
    instancia = motor.arrancar(tenant_id=tenant_id, clave="descuento")
    motor.avanzar(instancia)

    from sqlalchemy import select

    tarea = (
        db.execute(select(TareaHumana).where(TareaHumana.instancia_id == instancia.id))
        .scalars()
        .one()
    )
    tarea.completada_at = _ahora()
    tarea.created_at = _ahora() - timedelta(hours=40)
    tarea.completada_por = tenant_id
    db.flush()

    assert (
        ana.analitica_de_proceso(db, tenant_id, "descuento")["cuello_de_botella"]
        == "pedir_visto_bueno"
    )


def test_no_se_señala_a_nadie_por_una_casualidad(db: Any, tenant_id: UUID) -> None:
    """Con menos de tres tareas el número no dice nada de nadie, y publicarlo es
    señalar a una persona por una casualidad."""
    _publicar(db, tenant_id, "descuento", CON_TAREA)
    motor = Motor(db)
    instancia = motor.arrancar(tenant_id=tenant_id, clave="descuento")
    motor.avanzar(instancia)

    from sqlalchemy import select

    tarea = (
        db.execute(select(TareaHumana).where(TareaHumana.instancia_id == instancia.id))
        .scalars()
        .one()
    )
    tarea.completada_at = _ahora()
    tarea.created_at = _ahora() - timedelta(hours=100)
    tarea.completada_por = tenant_id
    db.flush()

    assert ana.analitica_de_proceso(db, tenant_id, "descuento")["personas_mas_lentas"] == []


def test_la_mediana_va_junto_a_la_media(db: Any, tenant_id: UUID) -> None:
    """Un proceso con una instancia de treinta días y cien de una hora tiene una
    media que no describe a ninguna."""
    _publicar(db, tenant_id, "descuento", CON_TAREA)
    motor = Motor(db)
    for horas in (1, 1, 1, 700):
        instancia = motor.arrancar(tenant_id=tenant_id, clave="descuento")
        motor.avanzar(instancia)
        from sqlalchemy import select

        tarea = (
            db.execute(select(TareaHumana).where(TareaHumana.instancia_id == instancia.id))
            .scalars()
            .one()
        )
        tarea.created_at = _ahora() - timedelta(hours=horas)
        tarea.completada_at = _ahora()
        db.flush()

    paso = next(
        p
        for p in ana.analitica_de_proceso(db, tenant_id, "descuento")["pasos"]
        if p["paso"] == "pedir_visto_bueno"
    )
    assert paso["espera_horas_media"] > paso["espera_horas_mediana"]
    assert paso["espera_horas_mediana"] == 1.0
