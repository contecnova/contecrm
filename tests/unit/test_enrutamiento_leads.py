"""Enrutamiento y asignación de leads por reglas (CRM-01.01.03.04).

Lo que estas pruebas defienden: **un lead nunca se queda sin destino y siempre
se puede explicar dónde acabó**. Un reparto automático que no se puede explicar
se desactiva a la primera discusión, y entonces vuelven los leads sin dueño.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.errors import ErrorValidacion

from services.sales import enrutamiento as enr
from services.sales.modelos import Lead


def _lead(db: Any, tenant_id: UUID, **extra: Any) -> Lead:
    extra.setdefault("estado", "nuevo")
    lead = Lead(tenant_id=tenant_id, **extra)
    db.add(lead)
    db.flush()
    return lead


def _regla(db: Any, tenant_id: UUID, **extra: Any) -> enr.ReglaEnrutamiento:
    datos: dict[str, Any] = {
        "nombre": "regla",
        "prioridad": 100,
        "condiciones": [{"atributo": "lead.pais", "operador": "=", "valor": "ES"}],
        "estrategia": "round_robin",
        "candidatos": [],
    }
    datos.update(extra)
    regla = enr.ReglaEnrutamiento(tenant_id=tenant_id, **datos)
    db.add(regla)
    db.flush()
    return regla


def test_la_regla_que_encaja_asigna_y_deja_traza(db: Any, tenant_id: UUID) -> None:
    comercial = uuid4()
    _regla(db, tenant_id, nombre="España", candidatos=[str(comercial)])
    lead = _lead(db, tenant_id, pais="ES", empresa="Acme")

    registro = enr.enrutar(db, lead, tenant_id=tenant_id)

    assert lead.owner_id == comercial
    assert registro.regla_nombre == "España"
    assert registro.evaluadas[-1]["resultado"] == "gana"


def test_gana_la_primera_por_prioridad_no_la_mejor(db: Any, tenant_id: UUID) -> None:
    """Con varias que encajan gana la de menor prioridad, sin puntuaciones.

    Es lo que hace el resultado explicable: con un sistema de puntos, «¿por qué
    ganó esta?» no tiene respuesta corta.
    """
    primero, segundo = uuid4(), uuid4()
    _regla(db, tenant_id, nombre="general", prioridad=50, candidatos=[str(primero)])
    _regla(
        db,
        tenant_id,
        nombre="especifica",
        prioridad=10,
        candidatos=[str(segundo)],
        condiciones=[{"atributo": "lead.pais", "operador": "en", "valor": ["ES", "PT"]}],
    )
    lead = _lead(db, tenant_id, pais="ES")

    registro = enr.enrutar(db, lead, tenant_id=tenant_id)

    assert registro.regla_nombre == "especifica"
    assert lead.owner_id == segundo


def test_sin_regla_que_encaje_va_a_la_cola_y_no_se_pierde(db: Any, tenant_id: UUID) -> None:
    _regla(
        db,
        tenant_id,
        nombre="solo_francia",
        condiciones=[{"atributo": "lead.pais", "operador": "=", "valor": "FR"}],
        candidatos=[str(uuid4())],
    )
    lead = _lead(db, tenant_id, pais="ES")

    registro = enr.enrutar(db, lead, tenant_id=tenant_id)

    assert lead.owner_id is None
    assert registro.cola == "sin_asignar"
    # Y queda escrito POR QUÉ no encajó, que es lo que se consulta después.
    assert registro.evaluadas[0]["motivo"]


def test_round_robin_reparte_por_turnos_y_el_cursor_sobrevive(db: Any, tenant_id: UUID) -> None:
    """El turno vive en la fila de la regla, no en memoria del proceso.

    Con el contador en memoria, dos réplicas del servicio empezarían las dos en
    cero y le darían todo al primer candidato.
    """
    a, b, c = uuid4(), uuid4(), uuid4()
    regla = _regla(db, tenant_id, candidatos=[str(a), str(b), str(c)])

    asignados = []
    for _ in range(4):
        lead = _lead(db, tenant_id, pais="ES")
        enr.enrutar(db, lead, tenant_id=tenant_id)
        asignados.append(lead.owner_id)

    assert asignados == [a, b, c, a]
    assert regla.cursor_turno == 1


def test_menos_carga_elige_a_quien_tiene_menos_leads_abiertos(db: Any, tenant_id: UUID) -> None:
    ocupado, libre = uuid4(), uuid4()
    for _ in range(3):
        _lead(db, tenant_id, pais="ES", owner_id=ocupado, estado="contactado")
    _regla(db, tenant_id, estrategia="menos_carga", candidatos=[str(ocupado), str(libre)])

    lead = _lead(db, tenant_id, pais="ES")
    enr.enrutar(db, lead, tenant_id=tenant_id)

    assert lead.owner_id == libre


def test_menos_carga_desempata_por_el_orden_declarado(db: Any, tenant_id: UUID) -> None:
    """Dos a cero leads: gana el primero de la lista, siempre el mismo.

    Con un desempate arbitrario, repetir la misma situación daría resultados
    distintos y el reparto no se podría reproducir al investigarlo.
    """
    a, b = uuid4(), uuid4()
    _regla(db, tenant_id, estrategia="menos_carga", candidatos=[str(a), str(b)])

    lead = _lead(db, tenant_id, pais="ES")
    enr.enrutar(db, lead, tenant_id=tenant_id)
    assert lead.owner_id == a


def test_los_candidatos_no_disponibles_se_saltan(db: Any, tenant_id: UUID) -> None:
    """Un equipo de vacaciones no debe bloquear las reglas siguientes."""
    de_vacaciones, activo = uuid4(), uuid4()
    _regla(db, tenant_id, nombre="preferente", prioridad=10, candidatos=[str(de_vacaciones)])
    _regla(db, tenant_id, nombre="respaldo", prioridad=20, candidatos=[str(activo)])

    lead = _lead(db, tenant_id, pais="ES")
    registro = enr.enrutar(db, lead, tenant_id=tenant_id, disponibles={activo})

    assert lead.owner_id == activo
    assert registro.regla_nombre == "respaldo"
    assert registro.evaluadas[0]["resultado"] == "sin_candidatos_disponibles"


def test_una_regla_con_condicion_mal_formada_no_se_come_todos_los_leads(
    db: Any, tenant_id: UUID
) -> None:
    """Una errata no puede convertir una regla específica en comodín.

    Es el fallo que más caro sale: la regla sigue «activa», encaja con todo y
    todos los leads caen en el mismo sitio sin que nadie entienda por qué.
    """
    erratico, correcto = uuid4(), uuid4()
    _regla(
        db,
        tenant_id,
        nombre="rota",
        prioridad=10,
        candidatos=[str(erratico)],
        condiciones=[{"campo": "lead.pais", "op": "="}],
    )  # claves equivocadas
    _regla(db, tenant_id, nombre="buena", prioridad=20, candidatos=[str(correcto)])

    lead = _lead(db, tenant_id, pais="ES")
    enr.enrutar(db, lead, tenant_id=tenant_id)

    assert lead.owner_id == correcto


def test_combinacion_alguna_es_un_o(db: Any, tenant_id: UUID) -> None:
    quien = uuid4()
    _regla(
        db,
        tenant_id,
        combinacion="alguna",
        candidatos=[str(quien)],
        condiciones=[
            {"atributo": "lead.pais", "operador": "=", "valor": "FR"},
            {"atributo": "lead.origen", "operador": "=", "valor": "feria"},
        ],
    )
    lead = _lead(db, tenant_id, pais="ES", origen="feria")
    enr.enrutar(db, lead, tenant_id=tenant_id)
    assert lead.owner_id == quien


def test_explicar_devuelve_el_historial_de_decisiones(db: Any, tenant_id: UUID) -> None:
    _regla(db, tenant_id, nombre="España", candidatos=[str(uuid4())])
    lead = _lead(db, tenant_id, pais="ES")
    enr.enrutar(db, lead, tenant_id=tenant_id)
    db.flush()

    historial = enr.explicar(db, lead.id, tenant_id)

    assert len(historial) == 1
    assert historial[0]["regla"] == "España"


# ── Validación al guardar ─────────────────────────────────────────────────


def test_una_regla_sin_condiciones_se_rechaza_al_guardarla() -> None:
    with pytest.raises(ErrorValidacion) as exc:
        enr.validar_regla({"condiciones": [], "candidatos": [str(uuid4())]})
    assert exc.value.error_code == "sales.regla_sin_condiciones"


def test_un_operador_desconocido_se_rechaza_al_guardarla() -> None:
    with pytest.raises(ErrorValidacion) as exc:
        enr.validar_regla(
            {
                "condiciones": [{"atributo": "lead.pais", "operador": "parecido_a", "valor": "ES"}],
                "candidatos": [str(uuid4())],
            }
        )
    assert exc.value.error_code == "sales.operador_desconocido"


def test_una_regla_sin_destino_se_rechaza_al_guardarla() -> None:
    """Encajaría sin poder asignar, y el lead se quedaría sin dueño."""
    with pytest.raises(ErrorValidacion) as exc:
        enr.validar_regla(
            {"condiciones": [{"atributo": "lead.pais", "operador": "=", "valor": "ES"}]}
        )
    assert exc.value.error_code == "sales.regla_sin_destino"
