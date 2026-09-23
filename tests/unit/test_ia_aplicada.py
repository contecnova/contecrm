"""Modelos entrenados, transcripción, variantes, hora de envío, sugerencia en el
caso, semántica de campos y salud replicada
(CRM-02.01.01.08, CRM-02.01.02.02, CRM-02.01.02.06, CRM-01.02.01.05,
CRM-01.02.01.06, CRM-02.04.01.04, CRM-02.02.02.05, CRM-04.03.01.04,
CRM-00.04.03.07, CRM-01.01.05.07).

Casi todo lo que sale mal con la IA en un CRM sale mal de la misma manera: el
número tiene buena pinta y nadie puede decir si significa algo. Estas pruebas van
detrás de eso — el modelo que aprende lo que hizo el equipo, el acierto medido
contra sí mismo, la transcripción citada como si fuera un acta y la salud en rojo
de hace tres meses.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import ErrorValidacion, Prohibido

from services.intelligence import caso_semantico as sem
from services.intelligence import entrenamiento as ent
from services.intelligence import transcripcion as trs
from services.intelligence import variantes as var
from services.marketing import momento as mom
from services.metadata import semantica as sm
from services.party import salud_replicada as sr

AHORA = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


# ── Entrenamiento (CRM-02.01.02.02, .06, CRM-02.01.01.08) ─────────────────


def test_un_modelo_no_decide_por_sexo_ni_por_codigo_postal() -> None:
    """Un modelo que decide a quién se llama con esas variables es discriminación
    con un informe bonito delante."""
    with pytest.raises(ErrorValidacion) as fallo:
        ent.comprobar_variables(variables=["importe", "codigo_postal"])
    assert fallo.value.error_code == "modelo.variable_prohibida"


def test_con_poco_historico_no_sale_un_modelo() -> None:
    """Sale una superstición con decimales, y decirlo antes evita que alguien
    decida con ella durante un año."""
    salida = ent.se_puede_entrenar(
        casos=[{"resultado": "ganado"} for _ in range(10)], variables=["importe"]
    )
    assert salida["se_puede"] is False
    assert "superstición" in salida["problemas"][0]


def test_se_avisa_del_sesgo_del_historico() -> None:
    """El modelo aprenderá a qué se dedicó el equipo, no qué convierte."""
    casos = [
        {"resultado": "ganado", "sector": "banca", "cerrado_el": date(2026, 1, 1)}
        for _ in range(100)
    ]
    casos += [
        {"resultado": "perdido", "sector": "industria", "cerrado_el": date(2026, 1, 1)}
        for _ in range(150)
    ]
    salida = ent.se_puede_entrenar(casos=casos, variables=["sector"])
    assert salida["se_puede"] is True
    assert any("a qué se dedicó el equipo" in a for a in salida["sesgos_del_historico"])


def test_la_particion_es_por_fecha_y_no_al_azar() -> None:
    """Repartir al azar mete casos del futuro en el entrenamiento y el acierto
    sale inflado."""
    casos = [
        {"resultado": "ganado", "cerrado_el": date(2026, 1, 1) + timedelta(days=i)}
        for i in range(100)
    ]
    salida = ent.particion_temporal(casos=casos)
    assert salida["entrenamiento"][-1]["cerrado_el"] < salida["validacion"][0]["cerrado_el"]


def test_un_caso_sin_fecha_impide_particionar_por_tiempo() -> None:
    with pytest.raises(ErrorValidacion) as fallo:
        ent.particion_temporal(casos=[{"resultado": "ganado"}])
    assert fallo.value.error_code == "modelo.caso_sin_fecha"


def test_el_modelo_se_compara_con_la_regla_tonta() -> None:
    """Si solo se gana el 15 %, decir «todos pierden» acierta el 85 %: un modelo
    con un 86 % no aporta nada y con ese número se justifica un proyecto."""
    predicciones = [
        {"referencia": f"O{i}", "puntuacion": 0.1, "resultado": "perdido"} for i in range(85)
    ]
    predicciones += [
        {"referencia": f"G{i}", "puntuacion": 0.1, "resultado": "ganado"} for i in range(15)
    ]
    salida = ent.evaluar_modelo(predicciones=predicciones)
    assert salida["aporta"] is False
    assert "no aporta lo suficiente" in salida["veredicto"]


def test_los_falsos_negativos_son_los_que_duelen() -> None:
    """Son las oportunidades que nadie habría llamado."""
    salida = ent.evaluar_modelo(
        predicciones=[
            {"referencia": "O1", "puntuacion": 0.1, "resultado": "ganado"},
            {"referencia": "O2", "puntuacion": 0.9, "resultado": "ganado"},
        ]
    )
    assert salida["falsos_negativos"] == ["O1"]


def test_los_factores_que_restan_tambien_se_enseñan() -> None:
    """Un panel que solo cuenta lo que suma hace pensar que la puntuación es baja
    por falta de datos."""
    salida = ent.factores(contribuciones={"presupuestos": 0.4, "silencio": -0.3})
    assert salida["suman"][0]["factor"] == "presupuestos"
    assert salida["restan"][0]["factor"] == "silencio"


def test_sin_contribuciones_la_puntuacion_no_se_explica_y_se_dice() -> None:
    salida = ent.factores(contribuciones={})
    assert salida["medible"] is False


def test_un_segmento_predictivo_cambia_solo_y_se_avisa() -> None:
    """Comparar resultados de dos ejecuciones es comparar dos audiencias
    distintas creyendo que son la misma."""
    salida = ent.segmento_predictivo(
        candidatos=[{"id": "1", "puntuacion": 0.9}, {"id": "2", "puntuacion": 0.2}],
        minimo_puntuacion=0.5,
    )
    assert salida["cuantos"] == 1
    assert salida["es_dinamico"] is True


def test_los_que_no_se_pueden_puntuar_se_cuentan_aparte() -> None:
    """No es que no encajen: es que no se han podido puntuar."""
    salida = ent.segmento_predictivo(
        candidatos=[{"id": "1", "puntuacion": None}], minimo_puntuacion=0.5
    )
    assert salida["sin_puntuacion"] == 1


def test_la_deriva_se_detecta_antes_de_que_alguien_compare_trimestres() -> None:
    """Un modelo no avisa cuando deja de valer: sigue dando números con la misma
    seguridad."""
    salida = ent.deriva(
        distribucion_entrenamiento={"banca": 70, "industria": 30},
        distribucion_hoy={"banca": 30, "industria": 70},
    )
    assert salida["hay_deriva"] is True


# ── Transcripción y compromisos (CRM-01.02.01.05, .06) ────────────────────


def test_no_se_transcribe_sin_haber_avisado() -> None:
    """Grabar sin decirlo es ilegal en media Europa y una ruptura de confianza en
    la otra media."""
    with pytest.raises(Prohibido) as fallo:
        trs.exigir_permiso_para_grabar(
            base="consentimiento_de_todos",
            participantes_avisados=False,
            participantes_externos=True,
        )
    assert fallo.value.error_code == "transcripcion.sin_aviso"


def test_una_transcripcion_no_es_un_acta() -> None:
    """El modelo confunde nombres y traduce mal las cifras: citarla en una
    discusión con el cliente acaba con la confianza en todo el sistema."""
    salida = trs.registrar_transcripcion(
        referencia="R1", texto="hola", confianza=0.9, idioma="es", minutos=10
    )
    assert "no es un acta" in salida["que_no_es"]


def test_una_transcripcion_poco_fiable_no_propone_nada() -> None:
    """Una propuesta mala también cuesta tiempo: el de leerla y descartarla."""
    salida = trs.proponer_extraidos(
        elementos=[{"tipo": "compromiso", "texto": "x", "quien": "cliente"}],
        confianza_transcripcion=0.4,
    )
    assert salida["propuestas"] == []


def test_un_compromiso_sin_dueño_no_se_asigna_al_comercial_por_defecto() -> None:
    """Le llenaría la agenda de cosas que dijo el cliente."""
    salida = trs.proponer_extraidos(
        elementos=[{"tipo": "compromiso", "texto": "mando la oferta"}],
        confianza_transcripcion=0.9,
    )
    assert salida["propuestas"] == []
    assert "dijo el cliente" in salida["descartados"][0]["porque"]


def test_los_compromisos_no_se_crean_solos() -> None:
    """«Te mando la oferta el jueves» y «si me la mandas, la miro» se parecen
    mucho en un texto y significan lo contrario."""
    salida = trs.proponer_extraidos(
        elementos=[{"tipo": "compromiso", "texto": "x", "quien": "nosotros", "cita": "min 3"}],
        confianza_transcripcion=0.9,
    )
    assert salida["se_crean_solas"] is False
    assert salida["propuestas"][0]["estado"] == "propuesta"


def test_se_guarda_lo_que_propuso_el_modelo_y_lo_que_quedo() -> None:
    """De las correcciones es de donde se aprende si la extracción sirve."""
    salida = trs.confirmar(
        propuesta={"texto": "llamar el martes"},
        confirmada_por=uuid4(),
        corregida={"texto": "llamar el jueves"},
    )
    assert salida["hubo_correccion"] is True
    assert salida["lo_que_propuso_el_modelo"]["texto"] == "llamar el martes"


def test_si_se_corrige_casi_todo_esto_no_ahorra_tiempo() -> None:
    """Lo cambia de sitio: de escribir a revisar, que cansa más."""
    salida = trs.calidad_de_la_extraccion(
        confirmadas=[{"hubo_correccion": True} for _ in range(6)]
        + [{"hubo_correccion": False} for _ in range(4)]
    )
    assert salida["merece_la_pena"] is False


def test_transcribir_tiene_un_precio_que_se_dice_antes() -> None:
    """Una biblioteca de tres años de llamadas es una factura, no un botón."""
    salida = trs.coste_de_transcribir(minutos_totales=10_000, coste_por_minuto=0.01, presupuesto=50)
    assert salida["cabe_en_el_presupuesto"] is False
    assert salida["se_ejecuta_ya"] is False


# ── Variantes de texto (CRM-02.04.01.04) ──────────────────────────────────


def test_las_afirmaciones_comprobables_se_marcan() -> None:
    """Un modelo las escribe con la misma naturalidad con la que escribe «buenos
    días», y el revisor que lee deprisa no distingue lo uno de lo otro."""
    salida = var.marcar_afirmaciones("Somos un 40 % más rápidos y el mejor del mercado")
    assert salida["hay"] is True
    assert len(salida["afirmaciones"]) >= 2


def test_no_hay_aprobacion_en_bloque_sin_leer() -> None:
    """Permitirlo «por comodidad» lo convertiría en la única forma que se usa."""
    with pytest.raises(Prohibido) as fallo:
        var.aprobar(texto_propuesto="a", texto_final="a", aprobada_por=uuid4(), sin_leer=True)
    assert fallo.value.error_code == "variantes.aprobacion_ciega"


def test_con_pocos_envios_no_hay_variante_ganadora() -> None:
    """Declararla ganadora convierte el azar en una decisión de marca que se
    repite dos años porque «los datos lo decían»."""
    salida = var.elegir_ganadora(
        ramas=[
            {"texto": "A", "enviados": 200, "respuestas": 9},
            {"texto": "B", "enviados": 200, "respuestas": 8},
        ]
    )
    assert salida["hay_ganadora"] is False
    assert "ruido" in salida["porque"]


def test_las_variantes_repetidas_se_avisan() -> None:
    salida = var.proponer_variantes(base="x", textos=["Hola", "hola", "Buenas"], canal="email")
    assert salida["repetidas"] == 1


def test_se_mide_cuanto_se_reescribe_de_lo_propuesto() -> None:
    """Si se reescribe casi todo, no es «escribir por ti»: es un punto de
    partida, y conviene no confundirlo."""
    salida = var.rendimiento_de_la_generacion(
        aprobaciones=[{"hubo_reescritura": True} for _ in range(8)]
        + [{"hubo_reescritura": False} for _ in range(2)]
    )
    assert salida["pct_reescritas"] == 80.0
    assert "punto de partida" in salida["que_significa"]


# ── Hora y canal (CRM-02.02.02.05) ────────────────────────────────────────


def test_con_dos_interacciones_no_se_personaliza_la_hora() -> None:
    """Concluir que alguien prefiere las tardes por dos correos es echar una
    moneda dos veces."""
    salida = mom.franja_preferida(
        interacciones=[{"resultado": "clic", "cuando": AHORA} for _ in range(2)]
    )
    assert salida["personalizable"] is False


def test_la_hora_sale_de_las_respuestas_y_no_de_las_aperturas() -> None:
    salida = mom.franja_preferida(
        interacciones=[{"resultado": "abierto", "cuando": AHORA.replace(hour=3)} for _ in range(20)]
        + [{"resultado": "respondido", "cuando": AHORA.replace(hour=17)} for _ in range(10)]
    )
    assert salida["personalizable"] is True
    assert salida["hora_local"].startswith("17")


def test_lo_que_dijo_la_persona_manda_sobre_el_modelo() -> None:
    """Si pidió que no se le llame, eso no es una preferencia estimada: es una
    instrucción."""
    salida = mom.canal_preferido(
        interacciones=[{"canal": "llamada", "resultado": "contestada"} for _ in range(20)],
        prohibidos=["llamada"],
    )
    assert salida["canal"] is None
    assert salida["medible"] is False


def test_si_casi_todo_va_a_la_hora_general_se_dice() -> None:
    """La personalización no está haciendo nada, y conviene saberlo antes de
    contarlo como una mejora."""
    salida = mom.planificar_envio(destinatarios=[{"id": str(i)} for i in range(10)], ahora=AHORA)
    assert salida["a_la_hora_general"] == 10
    assert "casi no está haciendo nada" in salida["que_significa"]


def test_con_pocos_envios_la_mejora_no_es_concluyente() -> None:
    salida = mom.comparar_con_hora_fija(
        con_optimizacion={"enviados": 100, "respuestas": 12},
        sin_optimizacion={"enviados": 100, "respuestas": 10},
    )
    assert salida["concluyente"] is False


# ── Sugerencia en el caso (CRM-04.03.01.04) ───────────────────────────────


def test_un_resultado_sin_cita_no_se_enseña() -> None:
    """El agente tendría que creerse un párrafo generado y responder con él."""
    salida = sem.buscar(
        resultados=[{"fuente": "articulo", "referencia": "A1", "parecido": 0.9, "cita": ""}],
        contexto_del_caso={},
        permisos_del_agente=set(),
    )
    assert salida["hay"] is False


def test_un_caso_parecido_sin_resolver_no_es_una_solucion() -> None:
    """Es otro que tiene el mismo problema."""
    salida = sem.buscar(
        resultados=[
            {
                "fuente": "caso_resuelto",
                "referencia": "C1",
                "parecido": 0.95,
                "cita": "x",
                "resuelto": False,
            }
        ],
        contexto_del_caso={},
        permisos_del_agente=set(),
    )
    assert salida["hay"] is False
    assert "mismo problema" in salida["motivos_de_descarte"][0]["porque"]


def test_lo_que_no_se_puede_ver_se_descarta_sin_decir_de_que_iba() -> None:
    """Decir «hay un caso parecido que no puedes ver» ya filtra información sobre
    otro cliente."""
    salida = sem.buscar(
        resultados=[
            {
                "fuente": "caso_resuelto",
                "referencia": "SECRETO",
                "parecido": 0.99,
                "cita": "x",
                "resuelto": True,
                "permiso": "caso:leer_todos",
            }
        ],
        contexto_del_caso={},
        permisos_del_agente={"caso:leer_propios"},
    )
    assert salida["motivos_de_descarte"][0]["ref"] == "(oculto)"


def test_lo_parecido_no_siempre_es_lo_aplicable() -> None:
    """Dos casos pueden hablar de lo mismo y ser de productos distintos."""
    salida = sem.buscar(
        resultados=[
            {
                "fuente": "caso_resuelto",
                "referencia": "C1",
                "parecido": 0.9,
                "cita": "x",
                "resuelto": True,
                "producto": "A",
            }
        ],
        contexto_del_caso={"producto": "B"},
        permisos_del_agente=set(),
    )
    assert "no siempre es lo aplicable" in salida["sugerencias"][0]["ojo"]


def test_nada_entra_en_el_indice_sin_saber_quien_puede_verlo() -> None:
    """Filtrar después de buscar ya es tarde: el fragmento aparece en el resumen
    aunque el resultado se descarte."""
    with pytest.raises(ErrorValidacion) as fallo:
        sem.exigir_permiso_de_indexacion(objeto="caso", permiso=None)
    assert fallo.value.error_code == "semantica.sin_permiso_declarado"


def test_al_modelo_no_se_le_manda_el_nombre_de_quien_tiene_el_problema() -> None:
    """Para encontrar casos parecidos hace falta el problema, no el nombre."""
    salida = sem.contexto_para_el_modelo(
        caso={"asunto": "no va el correo", "contacto": "Ana Pérez"}
    )
    assert "contacto" not in salida["contexto"]


# ── Semántica de los campos (CRM-00.04.03.07) ─────────────────────────────


def test_una_descripcion_que_repite_la_etiqueta_no_vale() -> None:
    """«Segmento: segmento» deja el catálogo igual de inútil, con la diferencia
    de que ahora parece completo."""
    with pytest.raises(ErrorValidacion) as fallo:
        sm.describir_campo(
            clave="cmp_2",
            etiqueta="Segmento",
            tipo="lista",
            descripcion="Segmento",
            rol="clasificacion",
        )
    assert fallo.value.error_code in (
        "semantica.descripcion_pobre",
        "semantica.descripcion_es_la_etiqueta",
    )


def test_los_valores_de_una_lista_se_explican_uno_a_uno() -> None:
    """Saber que admite «A», «B» y «C» no sirve de nada."""
    salida = sm.describir_campo(
        clave="cmp_2",
        etiqueta="Estado de crédito",
        tipo="lista",
        descripcion="En qué punto está la revisión de crédito del cliente, la rellena finanzas",
        rol="estado",
        valores=[{"valor": "A", "significa": "al corriente"}, {"valor": "C"}],
    )
    assert salida["valores_sin_explicar"] == ["C"]


def test_un_campo_sensible_no_entra_en_el_contexto() -> None:
    """Quien crea el campo rara vez piensa que su contenido se manda a un
    proveedor de inferencia."""
    campo = sm.describir_campo(
        clave="cmp_9",
        etiqueta="Diagnóstico",
        tipo="texto",
        descripcion="Diagnóstico clínico del paciente, lo rellena el personal sanitario",
        rol="texto_libre",
        sensible=True,
    )
    contexto = sm.contexto_semantico(objeto="paciente", campos=[campo])
    assert contexto["fuera_por_sensibles"] == ["cmp_9"]


def test_se_dice_cuanto_del_modelo_se_puede_explotar() -> None:
    """Prometer que «la IA entiende tus datos» con el 30 % descrito es la razón de
    la mayoría de los proyectos decepcionantes."""
    salida = sm.cobertura(
        campos=[
            {"clave": "a", "descripcion": "x" * 40, "explotable": True},
            {"clave": "b", "descripcion": ""},
            {"clave": "c", "descripcion": ""},
        ]
    )
    assert salida["pct"] < 70
    assert "decepcionantes" in salida["que_significa"]


# ── Salud replicada (CRM-01.01.05.07) ─────────────────────────────────────


@pytest.mark.db
def test_una_medida_vieja_no_pisa_la_buena(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Los eventos llegan desordenados: una reentrega antigua haría que la ficha
    volviera a decir «en riesgo» un mes después de arreglarse."""
    cuenta = uuid4()
    sr.proyectar(
        uow.db,
        tenant_id=uow.tenant_id,
        datos={
            "cuenta_id": str(cuenta),
            "puntuacion": 80,
            "nivel": "sana",
            "fiable": True,
            "medida_at": AHORA.isoformat(),
        },
    )
    sr.proyectar(
        uow.db,
        tenant_id=uow.tenant_id,
        datos={
            "cuenta_id": str(cuenta),
            "puntuacion": 20,
            "nivel": "critica",
            "fiable": True,
            "medida_at": (AHORA - timedelta(days=30)).isoformat(),
        },
    )
    salida = sr.de_la_cuenta(uow.db, uow.tenant_id, cuenta_id=cuenta, ahora=AHORA)
    assert salida["puntuacion"] == 80.0


@pytest.mark.db
def test_sin_medida_no_se_dice_que_la_cuenta_va_bien(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Normalmente es que faltan las señales con las que se calcula."""
    salida = sr.de_la_cuenta(uow.db, uow.tenant_id, cuenta_id=uuid4(), ahora=AHORA)
    assert salida["hay"] is False
    assert "no es que vaya bien" in salida["porque"]


@pytest.mark.db
def test_una_medida_de_hace_tres_meses_no_sirve_para_actuar(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Es un recuerdo, y llamar por él molesta a un cliente cuyo problema ya se
    resolvió."""
    cuenta = uuid4()
    sr.proyectar(
        uow.db,
        tenant_id=uow.tenant_id,
        datos={
            "cuenta_id": str(cuenta),
            "puntuacion": 30,
            "nivel": "riesgo",
            "fiable": True,
            "medida_at": (AHORA - timedelta(days=90)).isoformat(),
        },
    )
    salida = sr.de_la_cuenta(uow.db, uow.tenant_id, cuenta_id=cuenta, ahora=AHORA)
    assert salida["sirve_para_actuar"] is False
    assert "es un recuerdo" in salida["aviso"]


@pytest.mark.db
def test_la_lista_de_riesgo_deja_fuera_lo_que_no_se_puede_mirar(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Una lista donde la mitad son falsos positivos se abre dos veces y no se
    abre más — y entonces se pierden también los que sí lo estaban."""
    for i, (fiable, dias) in enumerate([(True, 1), (False, 1), (True, 90)]):
        sr.proyectar(
            uow.db,
            tenant_id=uow.tenant_id,
            datos={
                "cuenta_id": str(uuid4()),
                "puntuacion": 20 + i,
                "nivel": "critica",
                "fiable": fiable,
                "medida_at": (AHORA - timedelta(days=dias)).isoformat(),
            },
        )
    salida = sr.en_riesgo(uow.db, uow.tenant_id, ahora=AHORA)
    assert len(salida["cuentas"]) == 1
    assert salida["descartadas_por_poco_fiables"] == 1
    assert salida["descartadas_por_viejas"] == 1
