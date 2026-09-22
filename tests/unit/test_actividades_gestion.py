"""Asignación, delegación, recordatorios y vencidas (CRM-01.02.01.02).

El modelo tenía `asignada_a`, `delegada_por`, `recordar_at` y
`recordatorio_enviado` desde el principio. No había operaciones que los usaran
ni nada que mirara el reloj, así que un recordatorio programado no avisaba nunca
y una tarea delegada desaparecía de la vista de quien la delegó.

Lo que estas pruebas defienden:

  * Que **delegar no es asignar**: quien delega sigue siendo responsable.
  * Que un recordatorio **avisa una vez**, y que moverlo lo rearma.
  * Que una tarea vencida **avisa una vez**, no todos los días.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.errors import Conflicto, ErrorValidacion
from sqlalchemy import select

from services.party import servicio as svc
from services.party.modelos import Actividad


class _Uow:
    def __init__(self, db: Any, tenant_id: UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.emitidos: list[dict[str, Any]] = []

    def emitir(self, tipo: str, *, subject: Any, data: Any, **extra: Any) -> None:
        self.emitidos.append({"tipo": tipo, "data": data})


def _tarea(db: Any, tenant_id: UUID, **extra: Any) -> Actividad:
    fila = Actividad(
        tenant_id=tenant_id,
        tipo="tarea",
        asunto="Llamar al cliente",
        **extra,
    )
    db.add(fila)
    db.flush()
    return fila


def _salientes(db: Any, tipo: str) -> list[Any]:
    from crmcore.bus.modelos import EventoSaliente

    return list(
        db.execute(select(EventoSaliente).where(EventoSaliente.tipo == tipo)).scalars().all()
    )


# ── Asignar ───────────────────────────────────────────────────────────────


@pytest.mark.db
def test_asignar_avisa(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """El aviso importa más que el dato: una tarea que aparece en la lista de
    alguien sin que se entere es una tarea que se hace tarde."""
    uow = _Uow(db, tenant_id)
    tarea = _tarea(db, tenant_id)
    quien = uuid4()

    svc.asignar_actividad(uow, tarea.id, usuario_id=quien)

    assert tarea.asignada_a == quien
    assert uow.emitidos[-1]["tipo"] == "activity.assigned"
    assert uow.emitidos[-1]["data"]["asignada_a"] == str(quien)


@pytest.mark.db
def test_asignar_borra_la_marca_de_delegacion(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Pasar una tarea a otra persona no es lo mismo que delegarla. Dejar el
    rastro haría que la ficha dijera que alguien la delegó a quien ya no la
    tiene."""
    uow = _Uow(db, tenant_id)
    jefa, primero, segundo = uuid4(), uuid4(), uuid4()
    tarea = _tarea(db, tenant_id, asignada_a=jefa)

    svc.delegar_actividad(uow, tarea.id, usuario_id=primero, por=jefa)
    assert tarea.delegada_por == jefa

    svc.asignar_actividad(uow, tarea.id, usuario_id=segundo)
    assert tarea.delegada_por is None


@pytest.mark.db
def test_no_se_asigna_una_actividad_ya_cerrada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    uow = _Uow(db, tenant_id)
    tarea = _tarea(db, tenant_id, estado="completada")
    with pytest.raises(Conflicto, match="cerrada"):
        svc.asignar_actividad(uow, tarea.id, usuario_id=uuid4())


# ── Delegar ───────────────────────────────────────────────────────────────


@pytest.mark.db
def test_delegar_conserva_quien_la_tenia(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Es la diferencia con asignar, y no es cosmética: sin `delegada_por`, una
    tarea delegada desaparece de la vista del que la delegó y nadie vuelve a
    mirarla — que es lo que pasa con las tareas delegadas por correo."""
    uow = _Uow(db, tenant_id)
    jefa, quien = uuid4(), uuid4()
    tarea = _tarea(db, tenant_id, asignada_a=jefa)

    svc.delegar_actividad(uow, tarea.id, usuario_id=quien, por=jefa)

    assert tarea.asignada_a == quien
    assert tarea.delegada_por == jefa
    assert uow.emitidos[-1]["tipo"] == "activity.delegated"


@pytest.mark.db
def test_delegar_a_quien_ya_la_tiene_se_rechaza(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    uow = _Uow(db, tenant_id)
    quien = uuid4()
    tarea = _tarea(db, tenant_id, asignada_a=quien)
    with pytest.raises(ErrorValidacion, match="ya es de esa persona"):
        svc.delegar_actividad(uow, tarea.id, usuario_id=quien, por=uuid4())


# ── Recordatorios ─────────────────────────────────────────────────────────


@pytest.mark.db
def test_un_recordatorio_en_el_pasado_se_rechaza(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """No avisa de nada y deja al usuario creyendo que sí."""
    uow = _Uow(db, tenant_id)
    tarea = _tarea(db, tenant_id)
    with pytest.raises(ErrorValidacion, match="pasado"):
        svc.programar_recordatorio(
            uow, tarea.id, cuando=datetime.now(timezone.utc) - timedelta(hours=1)
        )


@pytest.mark.db
def test_mover_el_recordatorio_lo_rearma(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Quien lo mueve espera que le avisen otra vez; mantener la marca de
    enviado haría que una tarea aplazada nunca volviera a avisar."""
    uow = _Uow(db, tenant_id)
    tarea = _tarea(db, tenant_id, recordatorio_enviado=True)

    svc.programar_recordatorio(uow, tarea.id, cuando=datetime.now(timezone.utc) + timedelta(days=1))
    assert tarea.recordatorio_enviado is False


@pytest.mark.db
def test_el_barrido_emite_el_recordatorio_vencido(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es lo que faltaba: nada miraba el reloj, así que un recordatorio
    programado no avisaba nunca."""
    quien = uuid4()
    _tarea(
        db,
        tenant_id,
        asignada_a=quien,
        recordar_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    db.commit()

    cuenta = svc.barrer_recordatorios(db)

    assert cuenta["recordatorios"] == 1
    evento = _salientes(db, "activity.reminder")[0]
    assert evento.sobre["data"]["asignada_a"] == str(quien)


@pytest.mark.db
def test_el_recordatorio_no_se_repite_en_la_vuelta_siguiente(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un aviso repetido cada minuto enseña a ignorarlos todos."""
    _tarea(
        db,
        tenant_id,
        asignada_a=uuid4(),
        recordar_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    db.commit()

    assert svc.barrer_recordatorios(db)["recordatorios"] == 1
    assert svc.barrer_recordatorios(db)["recordatorios"] == 0


@pytest.mark.db
def test_un_recordatorio_futuro_todavia_no_se_emite(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    _tarea(
        db,
        tenant_id,
        asignada_a=uuid4(),
        recordar_at=datetime.now(timezone.utc) + timedelta(hours=2),
    )
    db.commit()
    assert svc.barrer_recordatorios(db)["recordatorios"] == 0


@pytest.mark.db
def test_un_recordatorio_sin_asignado_se_marca_y_no_avisa_a_nadie(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """No hay a quién avisar. Se marca igual para no volver a mirarla en cada
    vuelta, y queda registrado: una tarea con recordatorio y sin asignar es un
    error de datos que alguien tiene que ver."""
    tarea = _tarea(db, tenant_id, recordar_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    db.commit()

    assert svc.barrer_recordatorios(db)["recordatorios"] == 0
    db.refresh(tarea)
    assert tarea.recordatorio_enviado is True


@pytest.mark.db
def test_una_actividad_completada_no_recuerda_nada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Avisar de algo que ya está hecho es la forma más rápida de que el usuario
    apague los avisos."""
    _tarea(
        db,
        tenant_id,
        asignada_a=uuid4(),
        estado="completada",
        recordar_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    db.commit()
    assert svc.barrer_recordatorios(db)["recordatorios"] == 0


# ── Vencidas ──────────────────────────────────────────────────────────────


@pytest.mark.db
def test_las_vencidas_incluyen_las_que_uno_delego(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es la mitad del valor de delegar: quien delega sigue siendo responsable,
    y sin esta vista la tarea desaparece de su vista en cuanto la pasa."""
    ayer = datetime.now(timezone.utc) - timedelta(days=1)
    jefa, quien = uuid4(), uuid4()
    _tarea(db, tenant_id, asignada_a=jefa, vence_at=ayer)
    _tarea(db, tenant_id, asignada_a=quien, delegada_por=jefa, vence_at=ayer)
    _tarea(db, tenant_id, asignada_a=uuid4(), vence_at=ayer)
    db.flush()

    assert len(svc.actividades_vencidas(db, usuario_id=jefa)) == 2
    assert len(svc.actividades_vencidas(db, usuario_id=jefa, incluir_delegadas=False)) == 1


@pytest.mark.db
def test_lo_que_no_ha_vencido_no_sale(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    quien = uuid4()
    _tarea(
        db,
        tenant_id,
        asignada_a=quien,
        vence_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db.flush()
    assert svc.actividades_vencidas(db, usuario_id=quien) == []


@pytest.mark.db
def test_lo_ya_completado_no_esta_vencido(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Una tarea hecha con retraso está hecha. Seguir contándola como vencida
    haría que la lista no bajara nunca y dejaría de mirarse."""
    quien = uuid4()
    _tarea(
        db,
        tenant_id,
        asignada_a=quien,
        estado="completada",
        vence_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db.flush()
    assert svc.actividades_vencidas(db, usuario_id=quien) == []


@pytest.mark.db
def test_el_aviso_de_vencida_sale_una_sola_vez(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un aviso diario de la misma tarea vencida enseña a ignorarlos todos."""
    _tarea(
        db,
        tenant_id,
        asignada_a=uuid4(),
        vence_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    db.commit()

    assert svc.barrer_recordatorios(db)["vencidas"] == 1
    assert svc.barrer_recordatorios(db)["vencidas"] == 0
    assert len(_salientes(db, "activity.overdue")) == 1


@pytest.mark.db
def test_el_aviso_de_vencida_llega_tambien_a_quien_la_delego(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    jefa, quien = uuid4(), uuid4()
    _tarea(
        db,
        tenant_id,
        asignada_a=quien,
        delegada_por=jefa,
        vence_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db.commit()
    svc.barrer_recordatorios(db)

    datos = _salientes(db, "activity.overdue")[0].sobre["data"]
    assert datos["asignada_a"] == str(quien)
    assert datos["delegada_por"] == str(jefa)


@pytest.mark.db
def test_el_aviso_de_vencida_avisa_a_los_dos(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La regla del consumidor saca los destinatarios de DOS campos distintos.
    La primera versión solo sabía leer uno, y quien delegó no se enteraba."""
    from services.identity.notificaciones import AVISOS, _destinatarios

    jefa, quien = uuid4(), uuid4()
    destinatarios = _destinatarios(
        AVISOS["activity.overdue"],
        {"asignada_a": str(quien), "delegada_por": str(jefa)},
    )
    assert set(destinatarios) == {quien, jefa}


# ── El barrido entero, de punta a punta ───────────────────────────────────


@pytest.mark.db
def test_el_recordatorio_acaba_en_la_bandeja_de_quien_toca(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """De punta a punta: el barrido emite, el consumidor traduce y la
    notificación aparece. Probar solo el barrido dejaría sin comprobar el
    eslabón que ya faltó una vez — el consumidor que nadie había escrito."""
    import asyncio

    from crmcore.datos.seguimiento import Notificacion

    from services.identity.modelos import Membresia, Usuario
    from services.identity.notificaciones import consumir_evento

    # La persona tiene que estar en el tenant: avisar a quien ya no está es
    # exactamente lo que el consumidor filtra, y probarlo sin membresía
    # comprobaría el filtro en vez del recordatorio.
    usuario = Usuario(email="ana@ejemplo.test", nombre="Ana", activo=True)
    db.add(usuario)
    db.flush()
    db.add(Membresia(tenant_id=tenant_id, usuario_id=usuario.id, activa=True))
    db.flush()

    tarea = _tarea(
        db,
        tenant_id,
        asignada_a=usuario.id,
        recordar_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    quien = usuario.id
    db.commit()
    svc.barrer_recordatorios(db)

    evento = _salientes(db, "activity.reminder")[0]
    asyncio.run(
        consumir_evento(
            {
                "tipo": "activity.reminder",
                "tenant_id": str(tenant_id),
                "data": evento.sobre["data"],
            }
        )
    )

    db.expunge_all()
    avisos = db.query(Notificacion).filter_by(usuario_id=quien).all()
    assert len(avisos) == 1
    assert avisos[0].cuerpo == tarea.asunto


# ── Recordatorios que insisten y reprogramación (CRM-01.02.01.09) ─────────


@pytest.mark.db
def test_un_recordatorio_puede_insistir_hasta_su_tope(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un aviso que suena una vez y se calla se pierde entre otros treinta. La
    tarea que de verdad importa es justo la que hay que volver a poner delante.

    Y para en el tope: sin él seguiría sonando cuando el proyecto lleva dos años
    cerrado, y lo único que se consigue es que la gente cierre avisos sin
    leerlos.
    """
    tarea = _tarea(
        db,
        tenant_id,
        asignada_a=uuid4(),
        recordar_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        repetir_cada_min=1,
        max_avisos=3,
    )
    db.commit()

    emitidos = 0
    for _ in range(6):
        emitidos += svc.barrer_recordatorios(db)["recordatorios"]
        # Se adelanta el reloj moviendo el próximo aviso al pasado, que es lo
        # que haría el tiempo.
        db.refresh(tarea)
        if tarea.recordar_at and not tarea.recordatorio_enviado:
            tarea.recordar_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()

    assert emitidos == 3, "insiste tres veces y para en el tope"
    db.refresh(tarea)
    assert tarea.recordatorio_enviado is True


@pytest.mark.db
def test_cada_insistencia_dice_cual_de_cuantas_es(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El tercer aviso de la misma tarea llega igual que el primero, y quien lo
    recibe no sabe si están insistiendo o si el sistema se ha atascado."""
    _tarea(
        db,
        tenant_id,
        asignada_a=uuid4(),
        recordar_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        repetir_cada_min=1,
        max_avisos=2,
    )
    db.commit()

    svc.barrer_recordatorios(db)
    evento = _salientes(db, "activity.reminder")[0]
    assert evento.sobre["data"]["aviso"] == 1
    assert evento.sobre["data"]["de"] == 2


@pytest.mark.db
def test_insistir_sin_tope_se_rechaza(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    from crmcore.db.uow import UnidadDeTrabajo
    from crmcore.errors import ErrorValidacion

    tarea = _tarea(db, tenant_id, asignada_a=uuid4())
    db.commit()
    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    with pytest.raises(ErrorValidacion) as fallo:
        svc.programar_recordatorio(
            uow,
            tarea.id,
            cuando=datetime.now(timezone.utc) + timedelta(hours=1),
            repetir_cada_min=10,
        )
    assert fallo.value.error_code == "party.insistencia_sin_tope"


@pytest.mark.db
def test_la_tarea_no_atendida_se_reprograma_y_se_dice(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Se avisa de que venció **y luego** se mueve. Moverla en silencio haría que
    una tarea no constara vencida nunca, que es la forma más limpia de que no se
    haga y no lo sepa nadie."""
    tarea = _tarea(
        db,
        tenant_id,
        asignada_a=uuid4(),
        vence_at=datetime.now(timezone.utc) - timedelta(days=1),
        reprogramar_cada_dias=3,
        max_reprogramaciones=2,
    )
    db.commit()
    vencia = tarea.vence_at

    cuenta = svc.barrer_recordatorios(db)

    assert cuenta["vencidas"] == 1, "primero se avisa de que venció"
    assert cuenta["reprogramadas"] == 1
    db.refresh(tarea)
    assert tarea.vence_at > vencia
    evento = _salientes(db, "activity.rescheduled")[0]
    assert evento.sobre["data"]["reprogramada_por"] == "sistema"
    assert evento.sobre["data"]["motivo"] == "no atendida en plazo"
    assert evento.sobre["data"]["veces"] == 1


@pytest.mark.db
def test_la_reprogramacion_para_en_su_tope(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Una tarea que va por la cuarta reprogramación no es una tarea con fecha
    nueva: es una tarea que nadie va a hacer, y tiene que verse."""
    tarea = _tarea(
        db,
        tenant_id,
        asignada_a=uuid4(),
        vence_at=datetime.now(timezone.utc) - timedelta(days=1),
        reprogramar_cada_dias=1,
        max_reprogramaciones=2,
    )
    db.commit()

    reprogramadas = 0
    for _ in range(5):
        reprogramadas += svc.barrer_recordatorios(db).get("reprogramadas", 0)
        db.refresh(tarea)
        tarea.vence_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()

    assert reprogramadas == 2
    db.refresh(tarea)
    assert tarea.veces_reprogramada == 2
