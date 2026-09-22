"""Cadencias, cola de trabajo y metodología (CRM-03.03.01, CRM-03.01.02).

Lo que decide si una cadencia funciona no es el diseño de la secuencia: es **qué
pasa cuando el cliente contesta**. Las pruebas van detrás de eso y de los otros
cuatro sitios donde una herramienta de prospección se vuelve acoso o ruido:

  * el quinto correo a quien ya dijo que sí,
  * los tres compañeros a los que se sigue persiguiendo,
  * la cola que no dice por qué algo está arriba,
  * la plantilla que se elige por aperturas,
  * y la metodología que premia rellenar campos.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, NoEncontrado

from services.sales import cadencias as cad


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def _cadencia(uow: UnidadDeTrabajo, **kw: Any) -> cad.Cadencia:
    base: dict[str, Any] = {
        "clave": "prospeccion",
        "nombre": "Prospección fría",
        "pasos": [
            {"canal": "correo", "espera_dias": 0, "plantilla": "primero"},
            {"canal": "llamada", "espera_dias": 2},
            {"canal": "correo", "espera_dias": 4, "plantilla": "segundo"},
        ],
    }
    base.update(kw)
    fila, _ = cad.crear_cadencia(uow, **base)
    return fila


# ── Validación de la secuencia (CRM-03.03.01.01) ──────────────────────────


def test_una_cadencia_sin_pasos_no_toca_a_nadie() -> None:
    with pytest.raises(ErrorValidacion) as e:
        cad.validar_cadencia([])
    assert e.value.error_code == "cadencia.sin_pasos"


def test_un_correo_sin_plantilla_se_rechaza() -> None:
    """Un paso que manda un correo y no dice cuál falla al ejecutarse, delante de
    nadie y sin que se sepa a quién no le llegó."""
    with pytest.raises(ErrorValidacion) as e:
        cad.validar_cadencia([{"canal": "correo", "espera_dias": 0}])
    assert e.value.error_code == "cadencia.correo_sin_plantilla"


def test_un_canal_inventado_se_rechaza() -> None:
    with pytest.raises(ErrorValidacion):
        cad.validar_cadencia([{"canal": "paloma_mensajera"}])


def test_dos_toques_el_mismo_dia_avisan() -> None:
    """Dos toques en un día se viven como insistencia, no como seguimiento."""
    avisos = cad.validar_cadencia(
        [
            {"canal": "correo", "espera_dias": 0, "plantilla": "a"},
            {"canal": "llamada", "espera_dias": 0},
        ]
    )
    assert any("mismo día" in a for a in avisos)


def test_una_cadencia_de_solo_correo_avisa() -> None:
    """Compite con la bandeja de entrada y pierde."""
    avisos = cad.validar_cadencia(
        [
            {"canal": "correo", "espera_dias": 0, "plantilla": "a"},
            {"canal": "correo", "espera_dias": 3, "plantilla": "b"},
            {"canal": "correo", "espera_dias": 5, "plantilla": "c"},
        ]
    )
    assert any("un solo canal" in a for a in avisos)


# ── Inscripción y salida (CRM-03.03.01.04) ────────────────────────────────


def test_nadie_esta_en_dos_cadencias_a_la_vez(uow: UnidadDeTrabajo) -> None:
    """Es la forma más rápida de que alguien pida la baja, y ocurre sin querer:
    dos comerciales importan la misma lista."""
    una = _cadencia(uow)
    otra = _cadencia(uow, clave="otra", nombre="Otra")
    cad.inscribir(uow, una.id, email="ana@cliente.com")
    with pytest.raises(Conflicto) as e:
        cad.inscribir(uow, otra.id, email="ana@cliente.com")
    assert e.value.error_code == "cadencia.ya_inscrito"


def test_responder_saca_del_recorrido(uow: UnidadDeTrabajo) -> None:
    """Es la regla que hace que una cadencia sea aceptable y no acoso."""
    fila = _cadencia(uow)
    cad.inscribir(uow, fila.id, email="ana@cliente.com")
    salida = cad.registrar_respuesta(uow, email="ana@cliente.com")
    assert salida["sacadas"] == 1


def test_responder_saca_tambien_a_los_companeros_de_cuenta(
    uow: UnidadDeTrabajo,
) -> None:
    """En B2B contesta uno y se siguen persiguiendo sus tres compañeros, y el que
    contestó lo ve."""
    fila = _cadencia(uow)
    cuenta = uuid4()
    cad.inscribir(uow, fila.id, email="ana@acme.com", cuenta_id=cuenta)
    cad.inscribir(uow, fila.id, email="luis@acme.com", cuenta_id=cuenta)
    cad.inscribir(uow, fila.id, email="otro@otra.com", cuenta_id=uuid4())

    salida = cad.registrar_respuesta(uow, email="ana@acme.com")
    assert salida["companeros"] == 1
    # El de la otra cuenta sigue: la regla es por cuenta, no por cadencia.
    from sqlalchemy import select

    activos = (
        uow.db.execute(select(cad.Inscripcion).where(cad.Inscripcion.estado == "activa"))
        .scalars()
        .all()
    )
    assert [i.email for i in activos] == ["otro@otra.com"]


def test_sin_salida_por_cuenta_no_se_saca_a_nadie_mas(uow: UnidadDeTrabajo) -> None:
    """Se declara: hay ventas donde cada persona decide por su cuenta y sacarlas a
    todas sería perder tres conversaciones por una respuesta."""
    fila = _cadencia(uow, salida_por_cuenta=False)
    cuenta = uuid4()
    cad.inscribir(uow, fila.id, email="ana@acme.com", cuenta_id=cuenta)
    cad.inscribir(uow, fila.id, email="luis@acme.com", cuenta_id=cuenta)
    assert cad.registrar_respuesta(uow, email="ana@acme.com")["companeros"] == 0


def test_un_motivo_inventado_se_rechaza(uow: UnidadDeTrabajo) -> None:
    fila = _cadencia(uow)
    inscripcion = cad.inscribir(uow, fila.id, email="a@b.c")
    with pytest.raises(ErrorValidacion):
        cad.salir(uow, inscripcion.id, motivo="porque_si")


def test_no_se_sale_dos_veces(uow: UnidadDeTrabajo) -> None:
    fila = _cadencia(uow)
    inscripcion = cad.inscribir(uow, fila.id, email="a@b.c")
    cad.salir(uow, inscripcion.id, motivo="manual")
    with pytest.raises(Conflicto):
        cad.salir(uow, inscripcion.id, motivo="manual")


# ── Avanzar (CRM-03.03.01.01) ─────────────────────────────────────────────


def test_avanzar_ejecuta_el_paso_y_programa_el_siguiente(uow: UnidadDeTrabajo) -> None:
    fila = _cadencia(uow)
    inscripcion = cad.inscribir(uow, fila.id, email="a@b.c")
    salida = cad.avanzar(uow, uow.tenant_id)
    assert len(salida["ejecutados"]) == 1
    assert inscripcion.paso_actual == 1
    assert inscripcion.proximo_at is not None


def test_el_paso_manual_se_marca_como_manual(uow: UnidadDeTrabajo, db: Any) -> None:
    """Mandar un correo no es lo mismo que llamar, y una herramienta que finge que
    sí acaba con cadencias de cinco correos que nadie llamó."""
    from sqlalchemy import select

    fila = _cadencia(uow, pasos=[{"canal": "llamada", "espera_dias": 0}])
    cad.inscribir(uow, fila.id, email="a@b.c")
    cad.avanzar(uow, uow.tenant_id)
    toque = db.execute(select(cad.ToqueCadencia)).scalars().one()
    assert toque.canal == "llamada"


def test_la_cadencia_termina_sola_al_acabar_los_pasos(uow: UnidadDeTrabajo) -> None:
    fila = _cadencia(uow, pasos=[{"canal": "llamada", "espera_dias": 0}])
    inscripcion = cad.inscribir(uow, fila.id, email="a@b.c")
    cad.avanzar(uow, uow.tenant_id)
    assert inscripcion.estado == "terminada"
    assert inscripcion.motivo_salida == "terminada"


def test_los_toques_no_caen_en_fin_de_semana(uow: UnidadDeTrabajo) -> None:
    """Un correo automático el sábado dice «esto lo manda una máquina» y además
    «y no le importas»."""
    sabado = datetime(2026, 3, 7, 10, 0, tzinfo=timezone.utc)
    assert sabado.weekday() == 5
    movido = cad._siguiente_laborable(sabado, True)
    assert movido.weekday() == 0


def test_de_noche_se_empuja_a_la_manana_siguiente(uow: UnidadDeTrabajo) -> None:
    noche = datetime(2026, 3, 4, 3, 0, tzinfo=timezone.utc)
    assert cad._siguiente_laborable(noche, True).hour == 9


def test_si_no_se_pide_laborable_no_se_toca(uow: UnidadDeTrabajo) -> None:
    sabado = datetime(2026, 3, 7, 3, 0, tzinfo=timezone.utc)
    assert cad._siguiente_laborable(sabado, False) == sabado


def test_sin_pendientes_no_se_dice_que_todo_va_bien(uow: UnidadDeTrabajo) -> None:
    assert cad.avanzar(uow, uow.tenant_id)["medible"] is False


# ── La cola (CRM-03.03.01.02) ─────────────────────────────────────────────


def test_la_cola_dice_por_que_esta_cada_cosa(uow: UnidadDeTrabajo) -> None:
    """Una prioridad sin explicación se ignora: si no se dice por qué algo está
    arriba, la gente baja hasta encontrar lo que reconoce."""
    yo = uuid4()
    fila = _cadencia(uow)
    cad.inscribir(uow, fila.id, email="a@b.c", responsable_id=yo)
    cola = cad.cola_de_trabajo(uow.db, uow.tenant_id, yo)
    assert cola["entradas"][0]["por_que"].startswith("Toca el paso 1")


def test_lo_mas_atrasado_sube(uow: UnidadDeTrabajo) -> None:
    yo = uuid4()
    fila = _cadencia(uow)
    reciente = cad.inscribir(uow, fila.id, email="reciente@b.c", responsable_id=yo)
    viejo = cad.inscribir(uow, fila.id, email="viejo@b.c", responsable_id=yo)
    viejo.proximo_at = datetime.now(timezone.utc) - timedelta(days=10)
    uow.db.flush()
    cola = cad.cola_de_trabajo(uow.db, uow.tenant_id, yo)
    assert cola["entradas"][0]["titulo"].endswith("viejo@b.c")
    assert reciente.estado == "activa"


def test_una_cola_vacia_se_dice_vacia(uow: UnidadDeTrabajo) -> None:
    assert cad.cola_de_trabajo(uow.db, uow.tenant_id, uuid4())["vacia"] is True


# ── Plantillas (CRM-03.03.01.03, CRM-03.03.01.06) ─────────────────────────


def test_con_pocos_envios_no_se_da_una_tasa(uow: UnidadDeTrabajo, db: Any) -> None:
    """Con cinco envíos y una respuesta, el 20 % que saldría no describe nada y se
    usa para descartar una plantilla que nunca se probó."""
    db.add(
        cad.PlantillaCorreo(
            tenant_id=uow.tenant_id,
            clave="a",
            nombre="A",
            asunto="x",
            enviados=5,
            respondidos=1,
        )
    )
    db.flush()
    fila = cad.rendimiento_plantillas(db, uow.tenant_id)["plantillas"][0]
    assert fila["tasa_respuesta"] is None
    assert fila["concluyente"] is False


def test_con_envios_suficientes_si(uow: UnidadDeTrabajo, db: Any) -> None:
    db.add(
        cad.PlantillaCorreo(
            tenant_id=uow.tenant_id,
            clave="a",
            nombre="A",
            asunto="x",
            enviados=100,
            respondidos=12,
        )
    )
    db.flush()
    fila = cad.rendimiento_plantillas(db, uow.tenant_id)["plantillas"][0]
    assert fila["tasa_respuesta"] == 12.0


def test_la_apertura_sale_sin_tasa_y_con_su_advertencia(uow: UnidadDeTrabajo, db: Any) -> None:
    """Darle un porcentaje al lado del de respuesta invita a compararlos, y
    optimizar por aperturas lleva a asuntos que se abren y no se contestan."""
    db.add(
        cad.PlantillaCorreo(
            tenant_id=uow.tenant_id, clave="a", nombre="A", asunto="x", enviados=100, abiertos=80
        )
    )
    db.flush()
    fila = cad.rendimiento_plantillas(db, uow.tenant_id)["plantillas"][0]
    assert fila["abiertos"] == 80
    assert "tasa_apertura" not in fila
    assert "filtros" in fila["aviso_apertura"]


def test_responder_cuenta_en_la_plantilla(uow: UnidadDeTrabajo, db: Any) -> None:
    db.add(cad.PlantillaCorreo(tenant_id=uow.tenant_id, clave="primero", nombre="P", asunto="x"))
    db.flush()
    fila = _cadencia(uow)
    cad.inscribir(uow, fila.id, email="a@b.c")
    cad.avanzar(uow, uow.tenant_id)
    cad.registrar_respuesta(uow, email="a@b.c")

    from sqlalchemy import select

    plantilla = (
        db.execute(select(cad.PlantillaCorreo).where(cad.PlantillaCorreo.clave == "primero"))
        .scalars()
        .one()
    )
    assert plantilla.enviados == 1
    assert plantilla.respondidos == 1


# ── Reuniones (CRM-03.03.01.07) ───────────────────────────────────────────


def _agenda(uow: UnidadDeTrabajo, usuario: UUID, **kw: Any) -> cad.DisponibilidadAgenda:
    base: dict[str, Any] = {
        "tramos": {str(d): [["09:00", "13:00"]] for d in range(5)},
        "duracion_min": 30,
        "margen_min": 0,
        "antelacion_horas": 0,
    }
    base.update(kw)
    fila = cad.DisponibilidadAgenda(tenant_id=uow.tenant_id, usuario_id=usuario, **base)
    uow.db.add(fila)
    uow.db.flush()
    return fila


def _proximo_lunes() -> date:
    """Un lunes futuro. Con una fecha pasada no hay huecos, y con razón: no se
    propone una reunión para ayer."""
    hoy = datetime.now(timezone.utc).date()
    return hoy + timedelta(days=(7 - hoy.weekday()) % 7 + 7)


def test_los_huecos_salen_de_los_tramos_declarados(uow: UnidadDeTrabajo) -> None:
    yo = uuid4()
    _agenda(uow, yo)
    salida = cad.huecos(uow.db, uow.tenant_id, yo, desde=_proximo_lunes(), dias=1)
    assert len(salida) == 8  # de 9 a 13, cada 30 minutos
    assert salida[0]["contrastado"] is False


def test_un_hueco_ocupado_no_se_ofrece(uow: UnidadDeTrabajo) -> None:
    """Una disponibilidad calculada sin mirar el calendario produce la reunión que
    hay que mover, y moverla cuesta más que no haberla propuesto."""
    yo = uuid4()
    _agenda(uow, yo)
    lunes = _proximo_lunes()
    ocupado = [
        (
            datetime.combine(lunes, time(9, 0), tzinfo=timezone.utc),
            datetime.combine(lunes, time(10, 0), tzinfo=timezone.utc),
        )
    ]
    salida = cad.huecos(uow.db, uow.tenant_id, yo, desde=lunes, dias=1, ocupado=ocupado)
    assert len(salida) == 6
    assert salida[0]["contrastado"] is True


def test_la_antelacion_minima_se_respeta(uow: UnidadDeTrabajo) -> None:
    """Proponer un hueco dentro de diez minutos produce la reunión a la que nadie
    llega."""
    yo = uuid4()
    hoy = datetime.now(timezone.utc).date()
    _agenda(
        uow,
        yo,
        tramos={str(d): [["00:00", "23:30"]] for d in range(7)},
        antelacion_horas=48,
    )
    salida = cad.huecos(uow.db, uow.tenant_id, yo, desde=hoy, dias=1)
    assert salida == []


def test_el_round_robin_va_por_quien_lleva_mas_sin_recibir(
    uow: UnidadDeTrabajo,
) -> None:
    """Por orden alfabético o por identificador saldría siempre la misma persona
    primero, y el reparto deja de repartir."""
    a, b = uuid4(), uuid4()
    _agenda(uow, a, equipo="ventas")
    _agenda(uow, b, equipo="ventas")
    primero = cad.siguiente_del_equipo(uow.db, uow.tenant_id, "ventas")
    segundo = cad.siguiente_del_equipo(uow.db, uow.tenant_id, "ventas")
    assert primero != segundo
    assert cad.siguiente_del_equipo(uow.db, uow.tenant_id, "ventas") == primero


# ── Metodología (CRM-03.01.02.01, .02, .03) ───────────────────────────────


def _metodologia(uow: UnidadDeTrabajo, **kw: Any) -> cad.Metodologia:
    base: dict[str, Any] = {"clave": "meddic", "nombre": "MEDDIC", "familia": "meddic"}
    base.update(kw)
    fila = cad.Metodologia(tenant_id=uow.tenant_id, **base)
    uow.db.add(fila)
    uow.db.flush()
    return fila


def test_una_familia_conocida_trae_sus_criterios(uow: UnidadDeTrabajo) -> None:
    """Un tenant que elige MEDDIC espera MEDDIC, no una pantalla en blanco donde
    teclearlo."""
    metodologia = _metodologia(uow)
    salida = cad.evaluar(uow.db, uow.tenant_id, metodologia.id, uuid4())
    assert salida["criterios"] == 6


def test_se_dice_lo_que_falta_antes_que_la_puntuacion(uow: UnidadDeTrabajo) -> None:
    """Un indicador que sube al rellenar campos premia rellenar campos; el que
    sirve devuelve una lista de cosas que hacer."""
    metodologia = _metodologia(uow)
    salida = cad.evaluar(uow.db, uow.tenant_id, metodologia.id, uuid4())
    assert len(salida["lo_que_falta"]) == 6
    assert salida["siguiente_paso"]
    assert salida["puntuacion"] == 0.0


def test_lo_que_falta_sale_ordenado_por_peso(uow: UnidadDeTrabajo) -> None:
    """Lo primero de la lista es lo que más mueve la aguja, que es la única forma
    de que una lista de seis cosas se empiece."""
    metodologia = _metodologia(uow)
    salida = cad.evaluar(uow.db, uow.tenant_id, metodologia.id, uuid4())
    pesos = [c["peso"] for c in salida["lo_que_falta"]]
    assert pesos == sorted(pesos, reverse=True)


def test_con_la_mitad_sin_contestar_no_esta_cualificada(uow: UnidadDeTrabajo, db: Any) -> None:
    """La puntuación entonces no dice si el negocio va bien: dice que no se ha
    cualificado, y son cosas distintas."""
    metodologia = _metodologia(uow)
    oportunidad = uuid4()
    db.add(
        cad.EvaluacionMetodologia(
            tenant_id=uow.tenant_id,
            metodologia_id=metodologia.id,
            oportunidad_id=oportunidad,
            respuestas={"dolor": {"valor": "x"}},
        )
    )
    db.flush()
    salida = cad.evaluar(db, uow.tenant_id, metodologia.id, oportunidad)
    assert salida["cualificada"] is False
    assert salida["cubiertos"] == 1


def test_el_playbook_mas_especifico_gana(uow: UnidadDeTrabajo, db: Any) -> None:
    """Con el orden al revés, el genérico taparía siempre al que alguien escribió
    para su caso."""
    db.add(
        cad.Playbook(
            tenant_id=uow.tenant_id, clave="general", titulo="General", pasos=[{"que": "a"}]
        )
    )
    db.add(
        cad.Playbook(
            tenant_id=uow.tenant_id,
            clave="enterprise",
            titulo="Enterprise en negociación",
            etapa="negociacion",
            segmento="enterprise",
            pasos=[{"que": "b"}],
        )
    )
    db.flush()
    salida = cad.playbook_para(db, uow.tenant_id, etapa="negociacion", segmento="enterprise")
    assert salida is not None
    assert salida["clave"] == "enterprise"
    assert "negociacion" in salida["por_que"]


def test_sin_playbook_que_encaje_no_se_inventa_uno(uow: UnidadDeTrabajo, db: Any) -> None:
    db.add(
        cad.Playbook(tenant_id=uow.tenant_id, clave="solo_cierre", titulo="Cierre", etapa="cierre")
    )
    db.flush()
    assert cad.playbook_para(db, uow.tenant_id, etapa="descubrimiento") is None


def test_una_metodologia_que_no_existe_da_404(uow: UnidadDeTrabajo) -> None:
    with pytest.raises(NoEncontrado):
        cad.evaluar(uow.db, uow.tenant_id, uuid4(), uuid4())
