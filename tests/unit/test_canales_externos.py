"""Publicidad, canales offline, personalización web, biblioteca de activos,
aprobación, redes sociales, telefonía, marcador y voz
(CRM-02.01.01.09 · CRM-02.03.02.04, .05, .07 · CRM-02.04.01.01, .02 ·
CRM-04.02.01.05, .06, .08 · CRM-03.03.01.05).

Lo que tienen en común: **todo sale fuera** —a una plataforma, a un buzón físico,
a un hilo público, a un teléfono— y eso no se deshace. Estas pruebas van detrás de
lo que no se puede recoger: la lista subida sin base legal, la carta impresa por
error, la respuesta automática a una queja pública y la cancelación hecha por voz.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, Prohibido

from services.integration import telefonia as tel
from services.intelligence import voz
from services.marketing import activos as act
from services.marketing import audiencias_externas as aud
from services.marketing import social as soc
from services.service import marcador as mar

HOY = date(2026, 9, 23)
AHORA = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


# ── Audiencias publicitarias (CRM-02.01.01.09, CRM-02.03.02.04) ───────────


def test_aceptar_el_boletin_no_es_aceptar_los_anuncios() -> None:
    """Es la distinción que se salta todo el mundo."""
    salida = aud.preparar_audiencia(
        personas=[
            {"email": f"a{i}@b.c", "base_legal": "consentimiento_boletin"} for i in range(200)
        ],
        plataforma="x",
        finalidad="captacion",
    )
    assert salida["fuera_por_falta_de_base"] == 200
    assert salida["cuantos_salen"] == 0


def test_una_audiencia_pequeña_no_se_manda() -> None:
    """Con veinte personas la plataforma no anonimiza nada y el segmento se
    convierte en señalar a alguien con el dedo."""
    salida = aud.preparar_audiencia(
        personas=[
            {"email": f"a{i}@b.c", "base_legal": "consentimiento_publicidad"} for i in range(20)
        ],
        plataforma="x",
        finalidad="captacion",
    )
    assert salida["se_puede_mandar"] is False
    assert salida["identificadores"] == []


def test_lo_que_sale_va_troceado_y_nunca_en_claro() -> None:
    salida = aud.preparar_audiencia(
        personas=[
            {"email": f"a{i}@b.c", "base_legal": "consentimiento_publicidad"} for i in range(150)
        ],
        plataforma="x",
        finalidad="captacion",
    )
    assert salida["van_en_claro"] is False
    assert all(len(i["hash"]) == 64 for i in salida["identificadores"])


def test_una_baja_no_espera_al_ciclo_normal() -> None:
    """Seguir apareciendo en los anuncios después de darse de baja es lo que la
    gente denuncia, y con razón."""
    salida = aud.bajas_a_propagar(
        bajas_en_el_crm=[{"email": "a@b.c", "baja_at": AHORA}],
        ultimo_envio=AHORA - timedelta(days=1),
    )
    assert salida["urgente"] is True
    assert len(salida["identificadores"]) == 1


def test_no_se_persigue_con_anuncios_a_quien_ya_compro() -> None:
    """Es la queja más habitual de cualquier campaña."""
    salida = aud.retargeting(visitas=[{"email": "a@b.c", "ya_cliente": True}, {"email": "c@d.e"}])
    assert salida["excluidos_por_ser_clientes"] == 1
    assert len(salida["audiencia"]) == 1


# ── Canales offline (CRM-02.03.02.05) ─────────────────────────────────────


def test_un_paso_offline_no_se_lanza_solo() -> None:
    """Una carta impresa ya está impresa: la comprobación va antes."""
    salida = aud.preparar_paso_offline(
        canal="correo_postal",
        destinatarios=[{"direccion_postal": "Calle 1"}],
        coste_unitario=0.8,
        fecha_lanzamiento=HOY + timedelta(days=3),
        hoy=HOY,
    )
    assert salida["se_lanza_ya"] is False
    assert salida["irreversible"] is True


def test_los_de_la_lista_de_exclusion_no_entran() -> None:
    """Llamar a alguien que está en Robinson es una sanción, no un descuido."""
    salida = aud.preparar_paso_offline(
        canal="telemarketing",
        destinatarios=[
            {"telefono": "600", "excluido_por_lista": True},
            {"telefono": "601"},
        ],
        coste_unitario=1.0,
        fecha_lanzamiento=HOY + timedelta(days=1),
        hoy=HOY,
    )
    assert salida["excluidos_por_lista_de_exclusion"] == 1
    assert salida["destinatarios"] == 1


def test_una_carta_no_tiene_apertura_ni_clic() -> None:
    """Fingir métricas de digital hace que las comparaciones entre canales no
    valgan nada."""
    salida = aud.resultado_offline(envios=[{"devuelto": True}, {"respondio": True}])
    assert salida["no_hay_apertura_ni_clic"] is True
    assert salida["devueltos"] == 1


# ── Personalización web (CRM-02.03.02.07) ─────────────────────────────────


def test_a_un_visitante_anonimo_no_se_le_adivina_nada() -> None:
    """Adivinar por IP produce personalizaciones que dan entre risa y susto."""
    salida = aud.contenido_para(
        visitante={"ip": "1.2.3.4"}, reglas=[], anonimo_por_defecto="generico"
    )
    assert salida["personalizado"] is False
    assert salida["contenido"] == "generico"


def test_la_regla_aplicada_se_devuelve() -> None:
    """La respuesta a «¿por qué le salió esto?» no puede ser «lo decide el
    algoritmo»."""
    salida = aud.contenido_para(
        visitante={"contacto_id": "1", "sector": "banca"},
        reglas=[{"nombre": "banca", "campo": "sector", "valor": "banca", "contenido": "X"}],
    )
    assert salida["regla"] == "banca"


def test_dos_reglas_con_la_misma_prioridad_se_cazan() -> None:
    """El contenido dependería del orden en que lleguen de la base: cambia solo y
    nadie puede reproducirlo."""
    salida = aud.comprobar_reglas_web(
        reglas=[
            {"nombre": "a", "prioridad": 10, "contenido": "A"},
            {"nombre": "b", "prioridad": 10, "contenido": "B"},
        ]
    )
    assert salida["valido"] is False
    assert 10 in salida["empates_de_prioridad"]


# ── Biblioteca de activos (CRM-02.04.01.01) ───────────────────────────────


@pytest.mark.db
def test_un_activo_sin_usos_declarados_no_entra(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """«Uso general» no existe en ningún contrato de imagen, y suponerlo es como
    se acaba con una foto de stock en una valla."""
    with pytest.raises(ErrorValidacion) as fallo:
        act.registrar_activo(
            uow, clave="foto", nombre="Foto", referencia="doc-1", usos_permitidos=[]
        )
    assert fallo.value.error_code == "activos.sin_usos"


@pytest.mark.db
def test_la_version_nueva_no_borra_la_anterior(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Lo que se mandó al cliente el martes tiene que poder recuperarse."""
    primera = act.registrar_activo(
        uow, clave="folleto", nombre="v1", referencia="d1", usos_permitidos=["web"]
    )
    segunda = act.registrar_activo(
        uow, clave="folleto", nombre="v2", referencia="d2", usos_permitidos=["web"]
    )
    assert segunda.version == 2
    assert primera.sustituido_por_id == segunda.id


def test_una_licencia_de_web_no_vale_para_una_valla() -> None:
    salida = act.se_puede_usar(
        activo={"estado": "aprobado", "usos_permitidos": ["web"]}, uso="exterior", hoy=HOY
    )
    assert salida["puede"] is False
    assert salida["motivo"] == "uso_no_cubierto"


def test_un_activo_caducado_no_se_puede_usar() -> None:
    """El folleto con los precios del año pasado sigue estando, y por eso no se
    puede mandar."""
    salida = act.se_puede_usar(
        activo={
            "estado": "aprobado",
            "usos_permitidos": ["correo"],
            "vigente_hasta": (HOY - timedelta(days=1)).isoformat(),
        },
        uso="correo",
        hoy=HOY,
    )
    assert salida["motivo"] == "caducado"


@pytest.mark.db
def test_lo_que_no_declara_vigencia_es_lo_mas_peligroso(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Nunca va a aparecer en ninguna lista de caducados y por eso se queda ahí
    para siempre."""
    act.registrar_activo(uow, clave="x", nombre="X", referencia="d", usos_permitidos=["web"])
    salida = act.revisar_biblioteca(uow.db, uow.tenant_id, hoy=HOY)
    assert salida["sin_vigencia_declarada"] == ["x"]


# ── Aprobación de contenidos (CRM-02.04.01.02) ────────────────────────────


@pytest.mark.db
def test_un_paso_sin_aprobador_concreto_no_es_un_paso(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """«Que lo vea marketing» no lo ve nadie."""
    with pytest.raises(ErrorValidacion) as fallo:
        act.pedir_aprobacion(
            uow,
            objeto="campana",
            objeto_id=uuid4(),
            version=1,
            pasos=[{"nombre": "marketing"}],
        )
    assert fallo.value.error_code == "aprobacion.paso_sin_aprobador"


@pytest.mark.db
def test_rechazar_exige_motivo(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Un rechazo sin motivo devuelve el trabajo al principio sin decir qué
    cambiar."""
    aprobador = uuid4()
    salida = act.pedir_aprobacion(
        uow,
        objeto="campana",
        objeto_id=uuid4(),
        version=1,
        pasos=[{"nombre": "legal", "aprobador_id": aprobador}],
    )
    with pytest.raises(ErrorValidacion) as fallo:
        act.decidir(
            uow,
            aprobacion_id=UUID(salida["pasos"][0]["id"]),
            resultado="rechazado",
            comentario="",
            aprobador_id=aprobador,
            vio_los_cambios=True,
        )
    assert fallo.value.error_code == "aprobacion.rechazo_sin_motivo"


@pytest.mark.db
def test_no_se_aprueba_en_nombre_de_otro(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Dejaría una firma que no corresponde con quien miró el contenido."""
    salida = act.pedir_aprobacion(
        uow,
        objeto="campana",
        objeto_id=uuid4(),
        version=1,
        pasos=[{"nombre": "legal", "aprobador_id": uuid4()}],
    )
    with pytest.raises(Conflicto) as fallo:
        act.decidir(
            uow,
            aprobacion_id=UUID(salida["pasos"][0]["id"]),
            resultado="aprobado",
            comentario="",
            aprobador_id=uuid4(),
            vio_los_cambios=True,
        )
    assert fallo.value.error_code == "aprobacion.aprobador_distinto"


@pytest.mark.db
def test_aprobar_sin_mirar_los_cambios_queda_anotado(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Es el dato que dice si este flujo sirve o es un trámite."""
    aprobador = uuid4()
    salida = act.pedir_aprobacion(
        uow,
        objeto="campana",
        objeto_id=uuid4(),
        version=1,
        pasos=[{"nombre": "legal", "aprobador_id": aprobador}],
    )
    decision = act.decidir(
        uow,
        aprobacion_id=UUID(salida["pasos"][0]["id"]),
        resultado="aprobado",
        comentario="",
        aprobador_id=aprobador,
        vio_los_cambios=False,
    )
    assert decision["sin_mirar_los_cambios"] is True


@pytest.mark.db
def test_publicar_sin_pedir_aprobacion_no_es_aprobacion_implicita(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    salida = act.estado_de_la_aprobacion(
        uow.db, uow.tenant_id, objeto="campana", objeto_id=uuid4(), version=1
    )
    assert salida["se_puede_publicar"] is False


# ── Redes sociales (CRM-04.02.01.06) ──────────────────────────────────────


def test_un_elogio_no_abre_un_caso() -> None:
    """Meterlo en la cola hace que el agente aprenda a cerrar sin leer."""
    salida = soc.clasificar(mencion={"tipo": "elogio", "texto": "gracias"})
    assert salida["abre_caso"] is False


def test_una_sola_mencion_puede_ser_una_crisis() -> None:
    """No por volumen: por las palabras."""
    salida = soc.clasificar(
        mencion={"texto": "os voy a denunciar por esto"},
        palabras_de_crisis=["denunciar"],
    )
    assert salida["tipo"] == "crisis"
    assert salida["minutos_objetivo"] == 15


def test_una_queja_publica_no_la_contesta_una_maquina() -> None:
    """Es lo que convierte a un cliente enfadado en un hilo viral."""
    with pytest.raises(Prohibido) as fallo:
        soc.responder(
            tipo="queja",
            en_publico=True,
            texto="entendemos tu frustración",
            escrito_por_persona=False,
        )
    assert fallo.value.error_code == "social.respuesta_automatica"


def test_no_se_piden_datos_personales_en_publico() -> None:
    with pytest.raises(ErrorValidacion) as fallo:
        soc.responder(
            tipo="pregunta",
            en_publico=True,
            texto="dinos tu número de pedido",
            escrito_por_persona=True,
            pide_datos_personales=True,
        )
    assert fallo.value.error_code == "social.datos_en_publico"


def test_del_perfil_publico_se_guarda_lo_justo() -> None:
    """Traerse su historial entero crea la ficha de alguien que nunca nos dio
    nada."""
    salida = soc.perfil_minimo(
        perfil={"usuario": "@ana", "red": "x", "biografia": "...", "seguidores": 900}
    )
    assert "biografia" in salida["descartado"]
    assert "usuario" in salida["perfil"]


def test_las_menciones_sin_contestar_se_cuentan_aparte() -> None:
    """Una media de treinta minutos calculada solo sobre las contestadas esconde
    las cinco que nadie ha mirado."""
    salida = soc.tiempos(
        menciones=[
            {"tipo": "queja", "recibida_at": AHORA - timedelta(minutes=200)},
            {
                "tipo": "queja",
                "recibida_at": AHORA - timedelta(minutes=30),
                "respondida_at": AHORA,
            },
        ],
        ahora=AHORA,
    )
    assert len(salida["sin_contestar"]) == 1


def test_la_crisis_se_mide_por_cambio_de_ritmo() -> None:
    """Veinte menciones a la hora son normales para una marca grande y un incendio
    para una pequeña."""
    salida = soc.escalar_crisis(menciones_por_hora=[2, 3, 2, 4, 3, 40])
    assert salida["hay_crisis"] is True
    assert "cambio de ritmo" in salida["porque"]


def test_con_pocas_horas_no_se_declara_una_crisis() -> None:
    salida = soc.escalar_crisis(menciones_por_hora=[1, 50])
    assert salida["medible"] is False


# ── Telefonía (CRM-04.02.01.05) ───────────────────────────────────────────


def test_el_mismo_numero_escrito_de_tres_formas_encaja() -> None:
    """Comparar literalmente hace que el screen pop no salte justo con los
    clientes de toda la vida, que son los que están mal escritos."""
    salida = tel.identificar(
        numero="+34 600 11 22 33",
        candidatos=[{"id": "1", "nombre": "Ana", "telefonos": ["0034600112233"]}],
    )
    assert salida["identificado"] is True


def test_tres_fichas_con_el_mismo_numero_no_se_resuelven_a_una() -> None:
    """Abrir la primera hace que el agente salude por el nombre equivocado."""
    salida = tel.identificar(
        numero="600112233",
        candidatos=[
            {"id": "1", "telefonos": ["600112233"]},
            {"id": "2", "telefonos": ["600112233"]},
        ],
    )
    assert salida["identificado"] is False
    assert salida["motivo"] == "ambiguo"


def test_lo_que_tecleo_en_el_ivr_no_se_vuelve_a_preguntar() -> None:
    """Es la forma más rápida de que se enfade antes de empezar."""
    salida = tel.pantalla_al_sonar(
        identificacion={"identificado": True, "contacto_id": "1"},
        datos_del_ivr={"numero_pedido": "A-123"},
    )
    assert salida["no_volver_a_preguntar"] == ["numero_pedido"]


def test_una_transferencia_sin_resumen_no_pasa() -> None:
    """Es la queja número uno de cualquier servicio de atención."""
    with pytest.raises(ErrorValidacion) as fallo:
        tel.transferir(a="soporte", resumen="", contacto_id=None, caso_id=None, lo_ya_hablado=[])
    assert fallo.value.error_code == "cti.transferencia_sin_contexto"


def test_una_llamada_perdida_tambien_se_registra() -> None:
    """Si no consta, el panel enseña un servicio impecable construido solo con las
    que se atendieron."""
    salida = tel.registrar_llamada(
        evento="perdida", resultado="perdida", numero="600112233", duracion_s=0, contacto_id=None
    )
    assert salida["sin_atender"] is True


# ── Marcador (CRM-03.03.01.05) ────────────────────────────────────────────


def test_no_se_llama_a_quien_pidio_no_ser_llamado() -> None:
    with pytest.raises(Prohibido) as fallo:
        mar.preparar_llamada(
            contacto_id=uuid4(),
            numero="600",
            consiente_grabacion=True,
            grabar_por_politica=True,
            en_lista_de_exclusion=True,
        )
    assert fallo.value.error_code == "marcador.en_exclusion"


def test_sin_consentimiento_se_llama_igual_pero_sin_grabar() -> None:
    """Bloquear la llamada convertiría una cuestión de privacidad en un cliente
    que no puede hablar con nadie."""
    salida = mar.preparar_llamada(
        contacto_id=uuid4(),
        numero="600",
        consiente_grabacion=False,
        grabar_por_politica=True,
    )
    assert salida["se_graba"] is False


def test_un_reprogramar_sin_fecha_es_una_llamada_que_se_pierde() -> None:
    with pytest.raises(ErrorValidacion) as fallo:
        mar.registrar_al_colgar(contacto_id=uuid4(), duracion_s=60, resultado="reprogramar")
    assert fallo.value.error_code == "marcador.sin_proxima_fecha"


def test_la_nota_no_se_inventa() -> None:
    """«Contestada, 3 minutos» no es información comercial, y una frase genérica
    es peor que dejarla vacía porque parece que hay contenido."""
    salida = mar.registrar_al_colgar(contacto_id=uuid4(), duracion_s=180, resultado="hablado")
    assert salida["falta_la_nota"] is True


def test_quien_pide_que_no_le_llamen_obliga_a_algo_mas() -> None:
    salida = mar.registrar_al_colgar(
        contacto_id=uuid4(), duracion_s=10, resultado="pide_que_no_le_llamen"
    )
    assert salida["acciones_obligadas"]


def test_el_abandono_tiene_un_tope_que_no_se_negocia() -> None:
    """Además de la multa, es lo que hace que el número acabe marcado como spam."""
    salida = mar.ritmo_de_marcado(
        agentes_libres=5, llamadas_lanzadas=100, abandonadas=15, contestadas=85
    )
    assert salida["dentro_del_limite"] is False
    assert salida["lanzar_como_mucho"] == 5


def test_con_pocas_llamadas_no_se_habla_de_abandono() -> None:
    salida = mar.ritmo_de_marcado(
        agentes_libres=5, llamadas_lanzadas=10, abandonadas=1, contestadas=9
    )
    assert salida["medible"] is False


def test_grabar_sin_avisar_no_es_configurable() -> None:
    salida = mar.politica_de_grabacion(grabar=True, avisar=False, dias_conservacion=90)
    assert salida["valido"] is False


# ── Voz (CRM-04.02.01.08) ─────────────────────────────────────────────────


def test_un_reconocimiento_flojo_puede_significar_lo_contrario() -> None:
    """«No quiero cancelar» y «quiero cancelar» se parecen mucho a bajo volumen."""
    salida = voz.entender(texto="quiero cancelar", confianza=0.4, intento=0)
    assert salida["entendido"] is False
    assert salida["repreguntar"] is True


def test_a_la_tercera_se_pasa_a_una_persona() -> None:
    """Pedirlo otra vez solo confirma que se está hablando con una máquina que no
    funciona."""
    salida = voz.entender(texto="...", confianza=0.3, intento=2)
    assert salida["pasar_a_persona"] is True


def test_no_se_cambian_datos_bancarios_por_voz() -> None:
    """Es el fraude telefónico más común que existe."""
    with pytest.raises(Prohibido) as fallo:
        voz.exigir_que_se_puede_hacer_por_voz(accion="cambiar_datos_bancarios")
    assert fallo.value.error_code == "voz.accion_no_permitida"


def test_se_avisa_de_que_es_una_maquina() -> None:
    """La gente habla más corto y más claro cuando lo sabe, así que funciona
    mejor."""
    salida = voz.guion_de_apertura(nombre_asistente="Ana", es_maquina=True)
    assert salida["dice_que_es_maquina"] is True


def test_avisar_de_que_se_graba_no_es_consentimiento_para_entrenar() -> None:
    """Una cosa es conservar prueba de lo que se dijo y otra usar la voz de alguien
    para construir un producto."""
    salida = voz.usar_audio_para_entrenar(consentimiento_explicito=False)
    assert salida["puede"] is False


def test_un_traspaso_sin_motivo_hace_empezar_de_cero() -> None:
    with pytest.raises(ErrorValidacion) as fallo:
        voz.traspaso_a_persona(motivo="  ", lo_ya_dicho=[], datos_recogidos={})
    assert fallo.value.error_code == "voz.traspaso_sin_motivo"


def test_una_llamada_que_el_cliente_repite_al_dia_siguiente_no_se_resolvio() -> None:
    """Se aplazó, y encima con el cliente ya molesto."""
    salida = voz.rendimiento(
        conversaciones=[
            {"resuelta_sin_persona": True, "volvio_a_llamar_48h": True},
            {"resuelta_sin_persona": True},
        ]
    )
    assert salida["resueltas_de_verdad"] == 1
    assert salida["falsos_resueltos"] == 1


def test_la_centralita_tiene_donde_avisar() -> None:
    """`pantalla_al_sonar` y `registrar_llamada` no tenían ruta
    (`CRM-04.02.01.05`).

    Estaban escritas y probadas, y la centralita no tenía dónde pedir el screen
    pop ni dónde dar el parte. Lo segundo es lo que duele: una llamada que nadie
    cogió es un cliente que lo intentó, y si no consta, **el panel enseña un
    servicio impecable construido con las llamadas que sí se atendieron**.
    """
    import inspect

    from services.integration import api_suites

    fuente = inspect.getsource(api_suites)
    for funcion, ruta in (
        ("pantalla_al_sonar(", '"/pantalla"'),
        ("registrar_llamada(", '"/llamadas"'),
    ):
        assert funcion in fuente, f"«{funcion}» no la llama ninguna ruta"
        assert ruta in fuente, f"falta la ruta {ruta}"


def test_los_valores_admitidos_salen_del_modulo_y_no_se_repiten() -> None:
    """Repetirlos en la API es cómo acaban diciendo cosas distintas la
    documentación y la validación: el cuerpo anuncia un evento que el módulo
    rechaza, y quien integra lo descubre con una llamada perdida."""
    from services.integration import api_suites, telefonia

    assert api_suites.telefonia_eventos() == telefonia.EVENTOS
    assert api_suites.telefonia_resultados() == telefonia.RESULTADOS
