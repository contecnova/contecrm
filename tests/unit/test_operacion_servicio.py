"""Colas, agentes, escalado, entitlements y satisfacción
(CRM-04.01.01.05 a .12, CRM-04.01.02.01, .06, .07, .08, CRM-04.02.02.03).

El peso está en lo que separa un reparto que funciona de uno que solo lo parece:
que se mire la capacidad, que la cola se ordene por lo que vence, que el escalado
llegue antes del incumplimiento y que los números de satisfacción lleven al lado
cuánta gente contestó.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado

from services.service import entitlements as ent
from services.service import operacion as ope
from services.service import servicio as svc
from services.service.modelos import DefinicionSLA
from services.service.operacion import ColaCasos, ReglaAsignacion, ReglaEscalada

HOY = date.today()


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _agente(db: Any, tenant_id: UUID, *, capacidad: dict[str, int] | None = None, **kw: Any) -> Any:
    usuario = kw.pop("usuario_id", None) or uuid4()
    fila = ope.fijar_presencia(db, tenant_id, usuario, presencia=kw.pop("presencia", "disponible"))
    fila.capacidad = capacidad or {}
    for clave, valor in kw.items():
        setattr(fila, clave, valor)
    db.flush()
    return fila


def _regla(db: Any, tenant_id: UUID, **kw: Any) -> ReglaAsignacion:
    base = {
        "nombre": kw.pop("nombre", "reparto"),
        "estrategia": "menos_carga",
        "condiciones": [],
        "candidatos": [],
        "competencias": [],
        "canal": "caso",
    }
    base.update(kw)
    fila = ReglaAsignacion(tenant_id=tenant_id, **base)
    db.add(fila)
    db.flush()
    return fila


# ── Presencia y capacidad (CRM-04.02.02.03) ───────────────────────────────


@pytest.mark.db
def test_ausente_y_no_molestar_no_son_lo_mismo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Fundirlos hace que un supervisor no pueda saber si le falta gente o le
    falta capacidad, que son dos problemas con soluciones opuestas."""
    assert "ausente" in ope.PRESENCIAS and "no_molestar" in ope.PRESENCIAS
    assert "ausente" not in ope.PRESENCIAS_ASIGNABLES
    assert "no_molestar" not in ope.PRESENCIAS_ASIGNABLES


@pytest.mark.db
def test_la_presencia_guarda_desde_cuando(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """«Lleva cuarenta minutos en no molestar» es una conversación distinta de
    «acaba de ponerse»."""
    usuario = uuid4()
    fila = ope.fijar_presencia(db, tenant_id, usuario, presencia="disponible")
    antes = fila.presencia_desde
    ope.fijar_presencia(db, tenant_id, usuario, presencia="disponible")
    assert fila.presencia_desde == antes  # no cambia si no cambia el estado
    ope.fijar_presencia(db, tenant_id, usuario, presencia="no_molestar", motivo="comiendo")
    assert fila.presencia_desde > antes


@pytest.mark.db
def test_una_presencia_inventada_se_rechaza(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    with pytest.raises(ErrorValidacion) as e:
        ope.fijar_presencia(db, tenant_id, uuid4(), presencia="de_cafe")
    assert e.value.error_code == "service.presencia_no_valida"


@pytest.mark.db
def test_sin_capacidad_declarada_el_agente_puede_trabajar(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Tratarlo como saturado dejaría la cola llena sin que nadie entendiera por
    qué."""
    _agente(db, tenant_id, capacidad={})
    assert len(ope.agentes_disponibles(db, tenant_id)) == 1


@pytest.mark.db
def test_un_agente_saturado_no_recibe_mas(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Saltarse la capacidad convierte el reparto en un reparto formal: el caso
    figura asignado, nadie lo mira y el SLA corre igual."""
    agente = _agente(db, tenant_id, capacidad={"caso": 1})
    caso = svc.abrir_caso(uow, asunto="Ocupa")
    caso.owner_id = agente.usuario_id
    db.flush()
    assert ope.agentes_disponibles(db, tenant_id) == []


@pytest.mark.db
def test_sin_las_competencias_exigidas_no_entra(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un caso de facturación en alemán no puede caerle a quien no factura ni
    habla alemán, por mucho turno que le toque."""
    _agente(db, tenant_id, competencias=["facturacion"])
    assert ope.agentes_disponibles(db, tenant_id, competencias=["facturacion", "aleman"]) == []
    assert len(ope.agentes_disponibles(db, tenant_id, competencias=["facturacion"])) == 1


# ── Asignación (CRM-04.01.01.05, .06) ─────────────────────────────────────


@pytest.mark.db
def test_el_reparto_deja_escrito_por_que(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Sin esto, «¿por qué me ha caído a mí?» no tiene respuesta y el reparto
    automático deja de respetarse a la primera discusión."""
    agente = _agente(db, tenant_id)
    _regla(db, tenant_id, nombre="todos", candidatos=[str(agente.usuario_id)])
    caso = svc.abrir_caso(uow, asunto="X")

    registro = ope.asignar(uow, caso)
    assert registro.asignado_a == agente.usuario_id
    assert registro.regla_nombre == "todos"
    assert caso.estado == "asignado"


@pytest.mark.db
def test_sin_nadie_con_hueco_el_caso_va_a_la_cola(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Dejarlo sin dueño y sin cola es el único estado del que nadie se entera:
    no sale en la lista de ninguna persona ni de ningún equipo, y el SLA corre."""
    agente = _agente(db, tenant_id, capacidad={"caso": 1})
    ocupado = svc.abrir_caso(uow, asunto="Ocupa")
    ocupado.owner_id = agente.usuario_id
    db.flush()
    _regla(db, tenant_id, nombre="todos", candidatos=[str(agente.usuario_id)], cola="general")

    caso = svc.abrir_caso(uow, asunto="Nuevo")
    registro = ope.asignar(uow, caso)
    assert registro.asignado_a is None
    assert registro.cola == "general"
    assert caso.equipo == "general"


@pytest.mark.db
def test_se_distingue_no_encaja_de_no_hay_quien(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Son dos problemas distintos y confundirlos lleva a reescribir una regla
    que estaba bien."""
    agente = _agente(db, tenant_id, capacidad={"caso": 1})
    ocupado = svc.abrir_caso(uow, asunto="Ocupa")
    ocupado.owner_id = agente.usuario_id
    db.flush()
    _regla(
        db,
        tenant_id,
        nombre="criticos",
        prioridad=10,
        condiciones=[{"atributo": "caso.prioridad", "operador": "=", "valor": "critica"}],
        candidatos=[str(agente.usuario_id)],
    )
    _regla(db, tenant_id, nombre="resto", prioridad=20, candidatos=[str(agente.usuario_id)])

    caso = svc.abrir_caso(uow, asunto="Medio", prioridad="media")
    registro = ope.asignar(uow, caso)
    resultados = {e["regla"]: e["resultado"] for e in registro.evaluadas}
    assert resultados["criticos"] == "no_encaja"
    assert resultados["resto"] == "sin_agente_disponible"


@pytest.mark.db
def test_menos_carga_ponderada_reparte_por_hueco(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Con carga absoluta, quien tiene capacidad 20 y lleva 5 parece más ocupado
    que quien tiene capacidad 5 y lleva 4, y el reparto satura al que menos cabe."""
    grande = _agente(db, tenant_id, capacidad={"caso": 20})
    pequeno = _agente(db, tenant_id, capacidad={"caso": 5})
    for _ in range(5):
        c = svc.abrir_caso(uow, asunto="x")
        c.owner_id = grande.usuario_id
    for _ in range(4):
        c = svc.abrir_caso(uow, asunto="y")
        c.owner_id = pequeno.usuario_id
    db.flush()

    _regla(
        db,
        tenant_id,
        nombre="ponderada",
        estrategia="menos_carga_ponderada",
        candidatos=[str(grande.usuario_id), str(pequeno.usuario_id)],
    )
    caso = svc.abrir_caso(uow, asunto="Nuevo")
    registro = ope.asignar(uow, caso)
    assert registro.asignado_a == grande.usuario_id


@pytest.mark.db
def test_sin_reglas_ni_cola_general_se_dice_que_queda_sin_dueno(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    caso = svc.abrir_caso(uow, asunto="Huérfano")
    registro = ope.asignar(uow, caso)
    assert registro.asignado_a is None and registro.cola is None
    assert "SIN DUEÑO" in (registro.motivo or "")


# ── La cola (CRM-04.01.01.05) ─────────────────────────────────────────────


@pytest.mark.db
def test_la_cola_se_ordena_por_lo_que_vence_antes(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """La pregunta de quien coge de una cola es «qué se me va a incumplir
    primero»; por prioridad, un caso medio a punto de vencer queda debajo de uno
    crítico con dos días."""
    db.add(ColaCasos(tenant_id=tenant_id, clave="general", nombre="General"))
    db.flush()
    ahora = datetime.now(timezone.utc)

    critico = svc.abrir_caso(uow, asunto="Crítico", prioridad="critica")
    medio = svc.abrir_caso(uow, asunto="Medio", prioridad="media")
    for caso, horas in ((critico, 48), (medio, 1)):
        caso.equipo = "general"
        caso.vence_resolucion_at = ahora + timedelta(hours=horas)
    db.flush()

    lista = ope.cola(db, tenant_id, "general")
    assert lista[0]["caso_id"] == str(medio.id)


@pytest.mark.db
def test_un_caso_sin_sla_se_marca_en_la_cola(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Sin marcarlo queda al final y parece el menos urgente, cuando en realidad
    es el que nadie ha medido."""
    caso = svc.abrir_caso(uow, asunto="Sin SLA")
    caso.equipo = "general"
    db.flush()
    assert ope.cola(db, tenant_id, "general")[0]["sin_sla"] is True


@pytest.mark.db
def test_dos_agentes_no_cogen_el_mismo_caso(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Dos agentes mirando la misma cola pulsan a la vez, y sin la comprobación
    el segundo se queda con el caso del primero sin que ninguno lo sepa."""
    caso = svc.abrir_caso(uow, asunto="X")
    caso.equipo = "general"
    db.flush()
    ope.coger_de_cola(uow, caso.id, uuid4())
    with pytest.raises(Conflicto) as e:
        ope.coger_de_cola(uow, caso.id, uuid4())
    assert e.value.error_code == "service.caso_ya_asignado"


# ── Escalado (CRM-04.01.01.07) ────────────────────────────────────────────


def _escalada(db: Any, tenant_id: UUID, **kw: Any) -> ReglaEscalada:
    base = {"nombre": kw.pop("nombre", "escala")}
    base.update(kw)
    fila = ReglaEscalada(tenant_id=tenant_id, **base)
    db.add(fila)
    db.flush()
    return fila


@pytest.mark.db
def test_se_escala_antes_de_incumplir(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Escalar cuando el SLA ya se ha incumplido llega tarde por definición."""
    _escalada(db, tenant_id, consumido_pct=80, subir_prioridad=True)
    caso = svc.abrir_caso(uow, asunto="Va justo", prioridad="media")
    ahora = datetime.now(timezone.utc)
    caso.created_at = ahora - timedelta(hours=9)
    caso.vence_resolucion_at = ahora + timedelta(hours=1)
    db.flush()

    salida = ope.evaluar_escaladas(uow, tenant_id)
    assert len(salida["escalados"]) == 1
    assert caso.prioridad == "alta"


@pytest.mark.db
def test_un_caso_no_se_escala_dos_veces_por_la_misma_regla(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Si se escalara en cada pasada, el responsable recibiría el mismo aviso
    cada cinco minutos y dejaría de leerlos."""
    _escalada(db, tenant_id, consumido_pct=50)
    caso = svc.abrir_caso(uow, asunto="X")
    ahora = datetime.now(timezone.utc)
    caso.created_at = ahora - timedelta(hours=9)
    caso.vence_resolucion_at = ahora + timedelta(hours=1)
    db.flush()

    assert len(ope.evaluar_escaladas(uow, tenant_id)["escalados"]) == 1
    db.flush()
    assert ope.evaluar_escaladas(uow, tenant_id)["escalados"] == []


@pytest.mark.db
def test_solo_vip_no_escala_a_los_demas(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    _escalada(db, tenant_id, consumido_pct=1, solo_vip=True)
    caso = svc.abrir_caso(uow, asunto="Normal", cuenta_id=uuid4())
    ahora = datetime.now(timezone.utc)
    caso.created_at = ahora - timedelta(hours=9)
    caso.vence_resolucion_at = ahora + timedelta(hours=1)
    db.flush()
    assert ope.evaluar_escaladas(uow, tenant_id)["escalados"] == []


@pytest.mark.db
def test_cambiar_de_cola_suelta_al_dueno(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Si no, el caso figura en la cola nueva y sigue asignado al de antes, y los
    dos equipos creen que lo lleva el otro."""
    _escalada(db, tenant_id, consumido_pct=1, cola_destino="nivel2")
    caso = svc.abrir_caso(uow, asunto="X")
    caso.owner_id = uuid4()
    ahora = datetime.now(timezone.utc)
    caso.created_at = ahora - timedelta(hours=9)
    caso.vence_resolucion_at = ahora + timedelta(hours=1)
    db.flush()

    ope.evaluar_escaladas(uow, tenant_id)
    assert caso.equipo == "nivel2"
    assert caso.owner_id is None


# ── Derivación (CRM-04.01.01.08) ──────────────────────────────────────────


@pytest.mark.db
def test_derivar_exige_decir_que_se_espera(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Una derivación sin motivo obliga a quien la recibe a leerse el caso entero
    para averiguar qué se espera de él, y eso es lo que hace que reboten."""
    db.add(ColaCasos(tenant_id=tenant_id, clave="ingenieria", nombre="Ingeniería", nivel=3))
    db.flush()
    caso = svc.abrir_caso(uow, asunto="X")
    with pytest.raises(ErrorValidacion) as e:
        ope.derivar(uow, caso.id, cola_destino="ingenieria", motivo="  ")
    assert e.value.error_code == "service.derivacion_sin_motivo"


@pytest.mark.db
def test_derivar_no_reinicia_el_reloj(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any, calendario_ok: Any
) -> None:
    """El cliente no tiene por qué esperar otra vez desde cero porque nosotros
    hayamos movido su problema de mesa."""
    db.add(ColaCasos(tenant_id=tenant_id, clave="nivel2", nombre="Nivel 2", nivel=2))
    db.flush()
    caso = svc.abrir_caso(uow, asunto="X")
    vence = caso.vence_resolucion_at
    ope.derivar(uow, caso.id, cola_destino="nivel2", motivo="necesita revisión de producto")
    assert caso.vence_resolucion_at == vence
    assert caso.equipo == "nivel2"


@pytest.mark.db
def test_no_se_deriva_a_una_cola_que_no_existe(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    caso = svc.abrir_caso(uow, asunto="X")
    with pytest.raises(NoEncontrado):
        ope.derivar(uow, caso.id, cola_destino="fantasma", motivo="x")


@pytest.fixture
def calendario_ok(db: Any, tenant_id: UUID) -> Any:
    from crmcore.datos.calendario import CalendarioLaboral

    fila = CalendarioLaboral(
        tenant_id=tenant_id,
        clave="oficina",
        nombre="Oficina",
        por_defecto=True,
        horario={str(d): [{"desde": "00:00", "hasta": "23:59"}] for d in range(7)},
    )
    db.add(fila)
    db.add(
        DefinicionSLA(
            tenant_id=tenant_id,
            clave="estandar",
            nombre="Estándar",
            horas_resolucion=8,
            calendario="oficina",
            vigente_desde=HOY - timedelta(days=1),
        )
    )
    db.flush()
    return fila


# ── Entitlements (CRM-04.01.02.01, .06) ───────────────────────────────────


def _entitlement(db: Any, tenant_id: UUID, **kw: Any) -> ent.Entitlement:
    base = {
        "clave": kw.pop("clave", "soporte"),
        "nombre": "Soporte",
        "vigente_desde": HOY - timedelta(days=30),
    }
    base.update(kw)
    fila = ent.Entitlement(tenant_id=tenant_id, **base)
    db.add(fila)
    db.flush()
    return fila


@pytest.mark.db
def test_gana_el_derecho_mas_especifico(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Un cliente con contrato de soporte negociado aparte no puede recibir lo
    que le da su plan comercial: es justo lo que pagó por mejorar."""
    contrato = uuid4()
    _entitlement(db, tenant_id, clave="plan", plan="basico")
    _entitlement(db, tenant_id, clave="negociado", contrato_id=contrato)
    fila = ent.entitlement_aplicable(db, tenant_id, contrato_id=contrato, plan="basico")
    assert fila is not None and fila.clave == "negociado"


@pytest.mark.db
def test_sin_limite_no_es_lo_mismo_que_cero(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Cero significa «no tienes derecho a ninguna» y nulo «no se cuentan»."""
    fila = _entitlement(db, tenant_id, horas_incluidas=None, casos_incluidos=0)
    estado = ent.saldo(db, tenant_id, fila.id)
    assert estado["horas"]["sin_limite"] is True
    assert estado["casos"]["sin_limite"] is False
    assert estado["casos"]["agotado"] is True


@pytest.mark.db
def test_el_consumo_se_anota_aunque_este_agotado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Negarse a imputar haría que el trabajo ya hecho no se registrara: se ha
    gastado y no consta, que es la peor combinación."""
    fila = _entitlement(db, tenant_id, horas_incluidas=1)
    ent.imputar(uow, entitlement_id=fila.id, caso_id=None, horas=5, concepto="diagnóstico")
    estado = ent.saldo(db, tenant_id, fila.id)
    assert Decimal(estado["horas"]["consumidas"]) == Decimal("5")
    assert estado["horas"]["agotado"] is True


@pytest.mark.db
def test_al_agotar_lo_decide_el_contrato(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Elegir por el cliente significaría cortarle el soporte a alguien que
    pagaba por el exceso."""
    bloquea = _entitlement(db, tenant_id, clave="duro", horas_incluidas=1, al_agotar="bloquear")
    factura = _entitlement(db, tenant_id, clave="blando", horas_incluidas=1, al_agotar="facturar")
    for fila in (bloquea, factura):
        ent.imputar(uow, entitlement_id=fila.id, caso_id=None, horas=2)
    db.flush()

    assert ent.comprobar_antes_de_abrir(db, tenant_id, bloquea.id)["permitido"] is False
    assert ent.comprobar_antes_de_abrir(db, tenant_id, factura.id)["permitido"] is True


@pytest.mark.db
def test_se_avisa_de_la_caducidad_ademas_del_saldo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un derecho con 200 horas libres que vence el viernes es tan inservible
    como uno agotado."""
    fila = _entitlement(db, tenant_id, horas_incluidas=200, vigente_hasta=HOY + timedelta(days=3))
    assert ent.saldo(db, tenant_id, fila.id)["caduca_en_dias"] == 3


@pytest.mark.db
def test_no_se_imputan_horas_negativas(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    fila = _entitlement(db, tenant_id)
    with pytest.raises(ErrorValidacion) as e:
        ent.imputar(uow, entitlement_id=fila.id, caso_id=None, horas=-3)
    assert e.value.error_code == "service.horas_negativas"


# ── Satisfacción (CRM-04.01.01.12) ────────────────────────────────────────


@pytest.mark.db
def test_la_encuesta_no_se_manda_dos_veces(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Recibir la misma encuesta cada vez que alguien toca el caso es la forma
    más rápida de que el cliente la marque como correo no deseado."""
    caso = svc.abrir_caso(uow, asunto="X")
    ent.programar_encuesta(uow, caso)
    with pytest.raises(Conflicto):
        ent.programar_encuesta(uow, caso)


@pytest.mark.db
def test_el_token_no_se_guarda_en_claro(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Quien lea la tabla no puede contestar por el cliente."""
    caso = svc.abrir_caso(uow, asunto="X")
    fila, token = ent.programar_encuesta(uow, caso)
    assert token not in fila.hash_token
    assert len(fila.hash_token) == 64


@pytest.mark.db
def test_un_token_equivocado_no_contesta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    caso = svc.abrir_caso(uow, asunto="X")
    fila, _ = ent.programar_encuesta(uow, caso)
    with pytest.raises(NoEncontrado):
        ent.responder_encuesta(uow, encuesta_id=fila.id, token="otro", puntuacion=5)


@pytest.mark.db
def test_la_puntuacion_respeta_el_rango_del_tipo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    caso = svc.abrir_caso(uow, asunto="X")
    fila, token = ent.programar_encuesta(uow, caso, tipo="csat")
    with pytest.raises(ErrorValidacion) as e:
        ent.responder_encuesta(uow, encuesta_id=fila.id, token=token, puntuacion=9)
    assert e.value.error_code == "service.puntuacion_fuera_de_rango"


@pytest.mark.db
def test_no_se_responde_dos_veces(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    caso = svc.abrir_caso(uow, asunto="X")
    fila, token = ent.programar_encuesta(uow, caso)
    ent.responder_encuesta(uow, encuesta_id=fila.id, token=token, puntuacion=5)
    with pytest.raises(Conflicto):
        ent.responder_encuesta(uow, encuesta_id=fila.id, token=token, puntuacion=1)


@pytest.mark.db
def test_la_tasa_de_respuesta_va_junto_al_numero(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Un CSAT de 5 sobre el 3 % de los clientes no es un CSAT de 5, y
    enseñarlos separados hace que el primero se cite y el segundo no."""
    for i in range(4):
        caso = svc.abrir_caso(uow, asunto=f"C{i}")
        fila, token = ent.programar_encuesta(uow, caso)
        if i == 0:
            ent.responder_encuesta(uow, encuesta_id=fila.id, token=token, puntuacion=5)
    db.flush()

    salida = ent.satisfaccion(
        db, tenant_id, desde=HOY - timedelta(days=1), hasta=HOY + timedelta(days=1)
    )
    assert salida["csat"]["enviadas"] == 4
    assert salida["csat"]["respondidas"] == 1
    assert salida["csat"]["tasa_respuesta_pct"] == 25.0
    assert salida["csat"]["media"] == 5.0


@pytest.mark.db
def test_sin_respuestas_no_es_medible(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    salida = ent.satisfaccion(db, tenant_id, desde=HOY, hasta=HOY)
    assert salida["nps"]["medible"] is False


# ── Cumplimiento desglosado y créditos (CRM-04.01.02.07, .08) ─────────────


@pytest.mark.db
def test_el_desglose_enseña_el_peor_primero(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any, calendario_ok: Any
) -> None:
    """La lista existe para actuar, y ordenarla alfabéticamente obliga a buscar
    el problema en vez de enseñarlo."""
    buena, mala = uuid4(), uuid4()
    for cuenta, incumple in ((buena, False), (mala, True)):
        caso = svc.abrir_caso(uow, asunto="X", cuenta_id=cuenta)
        if incumple:
            caso.vence_resolucion_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            db.flush()
        svc.cerrar_caso(uow, caso.id, motivo="resuelto")
    db.flush()

    salida = ent.cumplimiento_desglosado(
        db, tenant_id, desde=HOY - timedelta(days=1), hasta=HOY + timedelta(days=1)
    )
    assert salida["grupos"][0]["clave"] == str(mala)
    assert salida["grupos"][0]["cumplimiento_pct"] == 0.0


@pytest.mark.db
def test_el_credito_se_propone_y_no_se_aplica(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any, calendario_ok: Any
) -> None:
    """Descontar dinero automáticamente por un incumplimiento que puede tener
    explicación convertiría cada incidencia en una reclamación."""
    cuenta = uuid4()
    caso = svc.abrir_caso(uow, asunto="X", cuenta_id=cuenta)
    caso.vence_resolucion_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.flush()
    svc.cerrar_caso(uow, caso.id, motivo="resuelto")
    db.flush()

    propuestos = ent.calcular_creditos(
        uow,
        periodo="2026-Q1",
        desde=HOY - timedelta(days=1),
        hasta=HOY + timedelta(days=1),
        escala=[{"hasta_pct": 95, "credito_pct": 10}],
    )
    assert propuestos[0]["credito_pct"] == 10.0

    from sqlalchemy import select

    fila = db.execute(select(ent.CreditoServicio)).scalar_one()
    assert fila.estado == "propuesto"


@pytest.mark.db
def test_decidir_un_credito_exige_motivo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any
) -> None:
    """Rechazar sin explicación deja al comercial sin nada que decirle al
    cliente, y aprobar sin explicación hace imposible saber después si fue una
    decisión o un descuido."""
    fila = ent.CreditoServicio(
        tenant_id=tenant_id, cuenta_id=uuid4(), periodo="2026-Q1", credito_pct=5
    )
    db.add(fila)
    db.flush()
    with pytest.raises(ErrorValidacion) as e:
        ent.decidir_credito(uow, fila.id, aprobar=True, motivo="")
    assert e.value.error_code == "service.credito_sin_motivo"


@pytest.mark.db
def test_un_credito_ya_decidido_no_se_recalcula(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, uow: Any, calendario_ok: Any
) -> None:
    """Recalcular un crédito aprobado cambiaría un importe que el cliente ya ha
    visto en su factura."""
    cuenta = uuid4()
    caso = svc.abrir_caso(uow, asunto="X", cuenta_id=cuenta)
    caso.vence_resolucion_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.flush()
    svc.cerrar_caso(uow, caso.id, motivo="resuelto")
    db.flush()

    args = {
        "periodo": "2026-Q1",
        "desde": HOY - timedelta(days=1),
        "hasta": HOY + timedelta(days=1),
        "escala": [{"hasta_pct": 95, "credito_pct": 10}],
    }
    ent.calcular_creditos(uow, **args)
    db.flush()

    from sqlalchemy import select

    fila = db.execute(select(ent.CreditoServicio)).scalar_one()
    ent.decidir_credito(uow, fila.id, aprobar=True, motivo="procede")
    db.flush()

    args["escala"] = [{"hasta_pct": 95, "credito_pct": 50}]
    ent.calcular_creditos(uow, **args)
    db.refresh(fila)
    assert float(fila.credito_pct) == 10.0
