"""Suites de productividad: perfil, consentimiento, credencial, incremento,
suscripción, contactos, tareas, notas, ficheros y reuniones
(CRM-06.01.03.01 a .10).

Lo que persiguen estas pruebas es la diferencia entre una integración que se
puede enseñar a un comité de empresa y una que no: el administrador que autoriza
por otro, el alcance pedido de más, la agenda personal volcada entera, la
suscripción que se muere sin avisar y el enlace de reunión metido en un push.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, Prohibido

from services.integration import suites as su
from services.integration import suites_recursos as sur

AHORA = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)

PERFIL = {
    "token_url": "https://proveedor/token",
    "limites": {"peticiones_por_minuto": 600},
    "alcances": {
        "base": "openid",
        "calendario.leer": "Calendars.Read",
        "correo.leer": "Mail.Read",
        "contactos.leer": "Contacts.Read",
    },
    "recursos": {
        "calendario": {
            "endpoint": "/me/events",
            "campos": {"asunto": "subject"},
            "incremento": "token_delta",
            "parametro_incremento": "deltaToken",
            "sentidos": ["leer", "escribir"],
        },
        "correo": {
            "endpoint": "/me/messages",
            "campos": {"asunto": "subject"},
            "incremento": "marca_de_tiempo",
        },
        "contactos": {
            "endpoint": "/me/contacts",
            "campos": {"nombre": "displayName"},
            "incremento": "token_delta",
        },
        "reuniones": {
            "endpoint": "/me/onlineMeetings",
            "campos": {"asunto": "subject"},
            "incremento": "completo",
        },
    },
}


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


# ── El perfil (CRM-06.01.03.01) ───────────────────────────────────────────


def test_un_perfil_completo_vale() -> None:
    assert su.validar_perfil(PERFIL)["valido"] is True


def test_un_recurso_sin_correspondencia_de_campos_no_sustituye_a_nada() -> None:
    """El dato llegaría y no se sabría dónde ponerlo: eso no es un perfil, es un
    módulo a medias."""
    malo = {**PERFIL, "recursos": {"tareas": {"endpoint": "/t", "incremento": "token_delta"}}}
    salida = su.validar_perfil(malo)
    assert salida["valido"] is False
    assert any("correspondencia de campos" in p["problema"] for p in salida["problemas"])


def test_traerlo_todo_cada_vez_se_avisa() -> None:
    """Funciona con cien elementos y deja de funcionar con cien mil, y para
    entonces ya hay gente dependiendo de ello."""
    salida = su.validar_perfil(PERFIL)
    assert any("se trae entero en cada vuelta" in a for a in salida["avisos"])


def test_un_alcance_de_un_recurso_que_no_se_usa_se_rechaza() -> None:
    """Pedir permiso para algo que el CRM no va a leer es justo por lo que a
    muchas integraciones no las dejan entrar."""
    malo = {**PERFIL, "alcances": {**PERFIL["alcances"], "ficheros.leer": "Files.Read"}}
    salida = su.validar_perfil(malo)
    assert salida["valido"] is False
    assert any("alcances de recursos que no se usan" in p["problema"] for p in salida["problemas"])


def test_sin_limite_declarado_se_avisa() -> None:
    """La primera sincronización grande se come la cuota del tenant entero y el
    proveedor corta a todo el mundo, no solo a esta integración."""
    salida = su.validar_perfil({**PERFIL, "limites": {}})
    assert any("límite del proveedor" in a for a in salida["avisos"])


def test_las_capacidades_marcan_el_dato_de_terceros() -> None:
    """Quien autoriza tiene derecho a saber que sus contactos suben el teléfono
    de su médico."""
    salida = su.capacidades_de(PERFIL)
    contactos = next(d for d in salida["detalle"] if d["recurso"] == "contactos")
    assert contactos["trae_dato_de_terceros"] is True
    assert "su médico" in contactos["aviso"]


# ── Consentimiento y alcance mínimo (CRM-06.01.03.02) ─────────────────────


def test_solo_se_piden_los_alcances_de_lo_que_se_va_a_usar() -> None:
    salida = su.alcance_minimo(config=PERFIL, recursos=["calendario"])
    assert salida["alcances"] == ["Calendars.Read", "openid"]
    assert "Mail.Read" in salida["no_se_piden"]


def test_un_recurso_que_el_perfil_no_ofrece_se_rechaza() -> None:
    with pytest.raises(ErrorValidacion) as fallo:
        su.alcance_minimo(config=PERFIL, recursos=["notas"])
    assert fallo.value.error_code == "suite.recurso_no_ofrecido"


def test_no_se_pide_un_alcance_mas_amplio_por_si_acaso() -> None:
    """Es lo que hace que una integración no pase la revisión de seguridad del
    cliente."""
    sin_alcance = {**PERFIL, "alcances": {"base": "openid"}}
    with pytest.raises(ErrorValidacion) as fallo:
        su.alcance_minimo(config=sin_alcance, recursos=["calendario"])
    assert fallo.value.error_code == "suite.alcance_sin_declarar"


@pytest.mark.db
def test_un_administrador_no_autoriza_el_buzon_de_otro(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Conectar el correo de todo un equipo desde una pantalla es exactamente lo
    que hace que esto acabe en el comité de empresa."""
    with pytest.raises(Prohibido) as fallo:
        su.conceder(
            uow,
            usuario_id=uuid4(),
            quien_concede=uuid4(),
            perfil_nombre="m365",
            recursos=["calendario"],
            alcances=["Calendars.Read"],
        )
    assert fallo.value.error_code == "suite.consentimiento_ajeno"


@pytest.mark.db
def test_el_consentimiento_es_recurso_a_recurso(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """«Conectó su Microsoft 365» no es una respuesta cuando alguien pregunta si
    el CRM lee sus correos."""
    usuario = uuid4()
    salida = su.conceder(
        uow,
        usuario_id=usuario,
        quien_concede=usuario,
        perfil_nombre="m365",
        recursos=["calendario", "contactos"],
        alcances=["Calendars.Read", "Contacts.Read"],
    )
    assert salida["recursos"] == ["calendario", "contactos"]
    su.exigir_consentimiento(
        uow.db, uow.tenant_id, usuario_id=usuario, perfil_nombre="m365", recurso="calendario"
    )
    with pytest.raises(Prohibido) as fallo:
        su.exigir_consentimiento(
            uow.db, uow.tenant_id, usuario_id=usuario, perfil_nombre="m365", recurso="correo"
        )
    assert fallo.value.error_code == "suite.sin_consentimiento"


@pytest.mark.db
def test_revocar_para_lo_que_entra_y_no_borra_lo_que_entro(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Lo que entró son actividades del CRM que otra gente ha usado: borrarlas es
    otra decisión."""
    usuario = uuid4()
    su.conceder(
        uow,
        usuario_id=usuario,
        quien_concede=usuario,
        perfil_nombre="m365",
        recursos=["correo"],
        alcances=["Mail.Read"],
    )
    salida = su.revocar(uow, usuario_id=usuario, perfil_nombre="m365")
    assert salida["revocados"] == ["correo"]
    assert "Se queda" in salida["lo_ya_sincronizado"]
    with pytest.raises(Prohibido) as fallo:
        su.exigir_consentimiento(
            uow.db, uow.tenant_id, usuario_id=usuario, perfil_nombre="m365", recurso="correo"
        )
    assert fallo.value.error_code == "suite.consentimiento_revocado"


@pytest.mark.db
def test_no_se_concede_acceso_en_general(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    usuario = uuid4()
    with pytest.raises(ErrorValidacion) as fallo:
        su.conceder(
            uow,
            usuario_id=usuario,
            quien_concede=usuario,
            perfil_nombre="m365",
            recursos=[],
            alcances=[],
        )
    assert fallo.value.error_code == "suite.consentimiento_vacio"


# ── La credencial (CRM-06.01.03.03) ───────────────────────────────────────


def test_una_credencial_sin_refresco_avisa_de_que_se_va_a_romper_sola() -> None:
    """Funciona meses y un martes deja de entrar el correo de veinte personas a
    la vez."""
    salida = su.estado_credencial(
        caduca_at=AHORA + timedelta(days=3), tiene_refresco=False, ahora=AHORA
    )
    assert salida["avisar"] is True
    assert "no hay token de refresco" in salida["porque"]


def test_sin_caducidad_no_se_dice_que_no_caduca() -> None:
    """Que no conste no es que no caduque: es que no se sabe."""
    salida = su.estado_credencial(caduca_at=None, tiene_refresco=True, ahora=AHORA)
    assert salida["fiable"] is False


def test_con_refresco_y_a_punto_de_caducar_se_renueva_sola() -> None:
    salida = su.estado_credencial(
        caduca_at=AHORA + timedelta(hours=1), tiene_refresco=True, ahora=AHORA
    )
    assert salida["renovar"] is True


# ── Incremento (CRM-06.01.03.04) ──────────────────────────────────────────


def test_la_primera_vuelta_es_completa_y_lo_dice() -> None:
    salida = su.parametros_de_incremento(config=PERFIL, recurso="calendario", marca_actual="")
    assert salida["es_completa"] is True
    assert "Primera vuelta" in salida["porque"]


def test_la_marca_se_pasa_tal_cual_la_dio_el_proveedor() -> None:
    """Traducirla sería inventar un estándar que se rompe con el primer proveedor
    que cambie de forma."""
    salida = su.parametros_de_incremento(config=PERFIL, recurso="calendario", marca_actual="abc123")
    assert salida["parametros"] == {"deltaToken": "abc123"}


def test_la_marca_no_avanza_si_algo_fallo() -> None:
    """Avanzar deja un hueco que no se recupera y que nadie nota, porque no falta
    una pantalla: falta una reunión."""
    salida = su.avanzar_incremento(marca_actual="a", marca_nueva="b", hubo_errores=True)
    assert salida["avanza"] is False
    assert salida["marca"] == "a"


def test_un_recurso_sin_estrategia_declarada_no_se_sincroniza() -> None:
    with pytest.raises(ErrorValidacion) as fallo:
        su.parametros_de_incremento(config=PERFIL, recurso="tareas", marca_actual="x")
    assert fallo.value.error_code == "suite.incremento_sin_declarar"


# ── Suscripción a cambios (CRM-06.01.03.05) ───────────────────────────────


@pytest.mark.db
def test_una_suscripcion_sin_identificador_del_proveedor_no_se_registra(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Queda huérfana mandando avisos a una URL que ya no los atiende."""
    with pytest.raises(ErrorValidacion) as fallo:
        su.suscribir(
            uow,
            usuario_id=uuid4(),
            perfil_nombre="m365",
            recurso="calendario",
            externo_id="  ",
            caduca_at=AHORA,
        )
    assert fallo.value.error_code == "suite.suscripcion_sin_id"


@pytest.mark.db
def test_dos_perfiles_no_se_suscriben_al_mismo_recurso(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Con dos, cada cambio entra dos veces y la ficha acaba con la misma reunión
    duplicada."""
    usuario = uuid4()
    su.suscribir(
        uow,
        usuario_id=usuario,
        perfil_nombre="m365",
        recurso="calendario",
        externo_id="s-1",
        caduca_at=AHORA + timedelta(days=2),
    )
    with pytest.raises(Conflicto) as fallo:
        su.exigir_sin_conflicto(
            uow.db,
            uow.tenant_id,
            usuario_id=usuario,
            recurso="calendario",
            perfil_nombre="google",
        )
    assert fallo.value.error_code == "suite.suscripcion_duplicada"


@pytest.mark.db
def test_se_renueva_con_margen_y_se_avisa_de_las_que_no_dicen_cuando_caducan(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Todas caducan: la que no lo declara es la que se muere sin avisar."""
    su.suscribir(
        uow,
        usuario_id=uuid4(),
        perfil_nombre="m365",
        recurso="calendario",
        externo_id="s-1",
        caduca_at=AHORA + timedelta(hours=2),
    )
    su.suscribir(
        uow,
        usuario_id=uuid4(),
        perfil_nombre="m365",
        recurso="correo",
        externo_id="s-2",
        caduca_at=None,
    )
    salida = su.por_renovar(uow.db, uow.tenant_id, ahora=AHORA)
    assert len(salida["por_renovar"]) == 1
    assert salida["sin_caducidad_declarada"]
    assert "se muere sin avisar" in salida["aviso"]


@pytest.mark.db
def test_si_no_se_puede_renovar_se_sigue_sondeando(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Quedarse esperando avisos que ya no llegan no da ningún error:
    simplemente no entra nada."""
    fila = su.suscribir(
        uow,
        usuario_id=uuid4(),
        perfil_nombre="m365",
        recurso="calendario",
        externo_id="s-1",
        caduca_at=AHORA,
    )
    salida = su.caer_a_sondeo(uow, suscripcion_id=fila.id, motivo="el proveedor rechazó renovar")
    assert salida["en_sondeo"] is True
    assert "no habría entrado nada" in salida["que_significa"]


# ── Contactos (CRM-06.01.03.06) ───────────────────────────────────────────


def test_no_se_le_sube_al_movil_el_crm_entero() -> None:
    """Llena su agenda de gente que no conoce, y entonces desconecta la
    integración — con lo que se pierde también lo que sí servía."""
    salida = sur.que_contactos_suben(
        contactos_del_crm=[
            {"id": "1", "nombre": "A", "relacionado_con_el_usuario": True},
            {"id": "2", "nombre": "B"},
        ]
    )
    assert len(salida["suben"]) == 1
    assert salida["no_suben"][0]["contacto"] == "2"


def test_solo_suben_los_campos_declarados() -> None:
    """Un contacto del móvil se sincroniza con el coche y con el reloj: las notas
    internas de la ficha no pintan nada ahí."""
    salida = sur.que_contactos_suben(
        contactos_del_crm=[
            {
                "id": "1",
                "nombre": "A",
                "email": "a@b.c",
                "notas_internas": "regatea mucho",
                "relacionado_con_el_usuario": True,
            }
        ]
    )
    assert "notas_internas" not in salida["suben"][0]


def test_la_agenda_personal_no_entra_en_el_crm() -> None:
    """Su médico y su hermana no son ni clientes ni usuarios, y nadie les ha
    preguntado."""
    salida = sur.que_contactos_entran(
        contactos_del_proveedor=[
            {"email": "cliente@acme.com"},
            {"email": "medico@clinica.es"},
            {"email": "nuevo@acme.com", "marcado_para_el_crm": True},
        ],
        correos_conocidos=["cliente@acme.com"],
    )
    assert salida["actualizan_una_ficha"] == 1
    assert salida["se_quedan_en_su_agenda"] == 1
    assert salida["altas_marcadas_por_la_persona"] == 1


def test_un_vacio_del_proveedor_no_borra_el_dato_bueno() -> None:
    """Casi siempre significa «no lo tengo», no «bórralo»."""
    salida = sur.resolver_campo(
        campo="telefono", valor_crm="600", valor_proveedor="", origen="proveedor"
    )
    assert salida["valor"] == "600"
    assert salida["gana"] == "crm"


def test_la_regla_de_origen_es_por_campo() -> None:
    """El teléfono lo sabe mejor el móvil y el cargo lo sabe mejor el CRM: una
    regla única obliga a elegir entre dos verdades."""
    telefono = sur.resolver_campo(
        campo="telefono", valor_crm="600", valor_proveedor="700", origen="proveedor"
    )
    cargo = sur.resolver_campo(
        campo="cargo", valor_crm="CTO", valor_proveedor="Director", origen="crm"
    )
    assert telefono["valor"] == "700"
    assert cargo["valor"] == "CTO"


# ── Tareas (CRM-06.01.03.07) ──────────────────────────────────────────────


def test_cerrarla_en_el_movil_la_cierra_en_el_crm() -> None:
    salida = sur.sincronizar_tarea(
        en_el_crm={"estado": "pendiente"}, en_el_proveedor={"estado": "hecha"}
    )
    assert salida["accion"] == "cerrar_en_el_crm"


def test_borrarla_en_el_proveedor_no_borra_la_actividad_del_crm() -> None:
    """La actividad tiene historia y puede tener comentarios de otros."""
    salida = sur.sincronizar_tarea(
        en_el_crm={"estado": "pendiente", "existia_en_el_proveedor": True}, en_el_proveedor=None
    )
    assert salida["accion"] == "desvincular"
    assert salida["avisar_al_usuario"] is True


def test_tocada_en_los_dos_lados_es_conflicto() -> None:
    """Elegir uno automáticamente tira el trabajo de alguien sin que se entere."""
    salida = sur.sincronizar_tarea(
        en_el_crm={"estado": "pendiente", "modificada_at": AHORA},
        en_el_proveedor={"estado": "pendiente", "modificada_at": AHORA},
        ultima_sincronizacion=AHORA - timedelta(hours=1),
    )
    assert salida["accion"] == "conflicto"


def test_la_asignacion_no_viaja() -> None:
    """El gestor personal no sabe de quién es la cuenta: dejarle decidir eso
    reasignaría trabajo sin que nadie lo pidiera."""
    salida = sur.sincronizar_tarea(
        en_el_crm={"estado": "pendiente"}, en_el_proveedor={"estado": "pendiente"}
    )
    assert "asignación" in salida["lo_que_no_viaja"].lower()


# ── Notas y ficheros (CRM-06.01.03.08, .09) ───────────────────────────────


def test_una_nota_no_se_copia_al_crm() -> None:
    """Queda vieja el mismo día y duplica el dato: dos sitios que proteger y dos
    que borrar."""
    with pytest.raises(Prohibido) as fallo:
        sur.vincular_nota(
            objeto="cuenta",
            objeto_id=uuid4(),
            proveedor="onenote",
            referencia="r",
            titulo="t",
            copiar_contenido=True,
        )
    assert fallo.value.error_code == "suite.nota_no_se_copia"


def test_se_distingue_no_tienes_acceso_de_ya_no_existe() -> None:
    """Es la diferencia entre pedirle el permiso a un compañero y buscar media
    hora algo que alguien borró hace un mes."""
    sin_acceso = sur.resolver_nota(referencia="r", tiene_acceso=False, existe=True)
    borrada = sur.resolver_nota(referencia="r", tiene_acceso=True, existe=False)
    assert sin_acceso["motivo"] == "sin_acceso"
    assert borrada["motivo"] == "no_existe"


def test_un_fichero_se_enlaza_y_no_se_copia() -> None:
    """Copiar rompe la promesa de «bórralo y desaparece»."""
    salida = sur.vincular_fichero(
        objeto="oportunidad",
        objeto_id=uuid4(),
        proveedor="drive",
        referencia="file-1",
        nombre="contrato.pdf",
    )
    assert salida["copia_en_el_crm"] is False
    assert salida["permisos"] == "se resuelven en el origen"


def test_un_enlace_roto_se_dice_en_la_ficha_y_no_al_pulsarlo() -> None:
    """Quien prepara una reunión mirando la ficha necesita saberlo antes de
    sentarse delante del cliente."""
    salida = sur.estado_del_enlace(existe=False, tiene_acceso=True, nombre="contrato.pdf")
    assert salida["estado"] == "desaparecido"
    assert "antes de la reunión" in salida["que_decir"]


# ── Reunión en línea (CRM-06.01.03.10) ────────────────────────────────────


def test_no_se_crea_la_sala_hasta_que_la_reunion_esta_confirmada() -> None:
    """Crearla al proponer deja salas abiertas de reuniones que no cuajaron, y
    alguien entra a una vacía creyendo que le han dado plantón."""
    with pytest.raises(ErrorValidacion) as fallo:
        sur.crear_reunion(
            perfil_config=PERFIL,
            asunto="Demo",
            inicio=AHORA,
            fin=AHORA + timedelta(hours=1),
            confirmada=False,
            asistentes=["a@b.c"],
        )
    assert fallo.value.error_code == "suite.reunion_sin_confirmar"


def test_sin_proveedor_declarado_no_se_inventa_uno() -> None:
    """Mandar a la gente a la sala de otro producto es justo lo que el cliente no
    quiere."""
    sin_reuniones = {**PERFIL, "recursos": {"correo": PERFIL["recursos"]["correo"]}}
    with pytest.raises(ErrorValidacion) as fallo:
        sur.crear_reunion(
            perfil_config=sin_reuniones,
            asunto="Demo",
            inicio=AHORA,
            fin=AHORA + timedelta(hours=1),
            confirmada=True,
            asistentes=[],
        )
    assert fallo.value.error_code == "suite.sin_proveedor_de_reuniones"


def test_el_enlace_de_la_reunion_no_va_en_un_push() -> None:
    """Es una credencial: quien lo tiene entra, y en un push llega a una pantalla
    bloqueada que ve cualquiera que coja el teléfono."""
    salida = sur.enlace_para(enlace="https://x/y", destino="push")
    assert salida["puede"] is False
    assert "credencial" in salida["porque"]


def test_la_reunion_confirmada_se_prepara_con_el_endpoint_del_perfil() -> None:
    salida = sur.crear_reunion(
        perfil_config=PERFIL,
        asunto="Demo",
        inicio=AHORA,
        fin=AHORA + timedelta(hours=1),
        confirmada=True,
        asistentes=["A@B.C", " "],
    )
    assert salida["endpoint"] == "/me/onlineMeetings"
    assert salida["cuerpo"]["asistentes"] == ["a@b.c"]
    assert salida["el_enlace_es_una_credencial"] is True


@pytest.mark.db
def test_un_perfil_invalido_no_se_guarda(uow: UnidadDeTrabajo, contexto_tenant: UUID) -> None:
    """Guardarlo dejaría una integración que falla en la primera llamada y un
    panel que dice que está configurada."""
    with pytest.raises(ErrorValidacion) as fallo:
        su.declarar_perfil(uow, nombre="roto", sistema="x", config={"recursos": {}})
    assert fallo.value.error_code == "suite.perfil_invalido"


@pytest.mark.db
def test_el_perfil_valido_se_guarda_como_una_conexion_mas(
    uow: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    """Un «módulo de Microsoft» al lado del resto de integraciones sería el
    principio de tener dos formas de integrar y una sola mantenida."""
    fila = su.declarar_perfil(uow, nombre="m365", sistema="microsoft", config=PERFIL)
    assert fila.protocolo == "rest"
    guardado = su.perfil(uow.db, uow.tenant_id, "m365")
    assert guardado["clase"] == "suite_productividad"
