"""Operar las suites: disponibilidad, chat, import/export, reglas, límites,
salud, baja, identidad y diagnóstico (CRM-06.01.03.11 a .17, .19, .20).

Casi nada de esto falla: **se degrada en silencio**. Una suscripción que caduca,
un proveedor que corta la cuota, un buzón sin credencial. Estas pruebas van
detrás de eso — y de las respuestas cómodas y falsas, que son peores que las
incómodas y ciertas.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from crmcore.errors import ErrorValidacion, Prohibido

from services.integration import suites_operacion as sop

AHORA = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)


# ── Disponibilidad (CRM-06.01.03.11) ──────────────────────────────────────


def test_un_calendario_ilegible_no_esta_libre() -> None:
    """No se sabe y se propone igualmente «porque no consta nada»: así es como se
    cita a alguien encima de la reunión que ya tenía."""
    salida = sop.huecos_libres(
        ocupado=[],
        desde=AHORA,
        hasta=AHORA + timedelta(hours=8),
        minutos=30,
        calendario_legible=False,
    )
    assert salida["fiable"] is False
    assert salida["huecos"] == []


def test_los_huecos_salen_entre_lo_ocupado() -> None:
    salida = sop.huecos_libres(
        ocupado=[{"inicio": AHORA + timedelta(hours=1), "fin": AHORA + timedelta(hours=2)}],
        desde=AHORA,
        hasta=AHORA + timedelta(hours=4),
        minutos=30,
    )
    assert salida["fiable"] is True
    assert salida["huecos"]


def test_del_calendario_ajeno_solo_se_lee_que_esta_ocupado() -> None:
    """El asunto puede ser «revisión médica», y para proponer una hora no hace
    ninguna falta."""
    salida = sop.huecos_libres(
        ocupado=[], desde=AHORA, hasta=AHORA + timedelta(hours=4), minutos=30
    )
    assert salida["lo_que_se_lee"] == "solo si está ocupado, no de qué"


def test_sin_huecos_se_dice_en_vez_de_enseñar_una_lista_vacia() -> None:
    salida = sop.huecos_libres(
        ocupado=[{"inicio": AHORA, "fin": AHORA + timedelta(hours=4)}],
        desde=AHORA,
        hasta=AHORA + timedelta(hours=4),
        minutos=30,
    )
    assert "no hay ningún hueco" in salida["aviso"].lower()


# ── Chat vinculado (CRM-06.01.03.12) ──────────────────────────────────────


def test_un_hilo_de_chat_no_se_copia_al_crm() -> None:
    """Tiene la negociación, el precio y el comentario que alguien hizo sobre un
    compañero: copiarlo lo enseña a quien no estaba en la conversación."""
    salida = sop.vincular_conversacion(
        objeto="oportunidad",
        objeto_id=uuid4(),
        proveedor="teams",
        referencia="hilo-1",
        exportable=True,
    )
    assert salida["contenido_en_el_crm"] is False


def test_lo_que_el_canal_no_exporta_no_se_reconstruye_a_trozos() -> None:
    """Una conversación incompleta que parece completa es peor que un enlace."""
    salida = sop.vincular_conversacion(
        objeto="cuenta",
        objeto_id=uuid4(),
        proveedor="slack",
        referencia="hilo-2",
        exportable=False,
    )
    assert "No se reconstruye a trozos" in salida["aviso"]


# ── Importar y exportar (CRM-06.01.03.13) ─────────────────────────────────


def test_la_exportacion_no_necesita_ninguna_suite_conectada() -> None:
    """Un CRM cuyos datos solo salen por la API de un fabricante tiene al cliente
    atado."""
    salida = sop.preparar_exportacion(formato="icalendar", objetos=["actividad"])
    assert salida["sin_intermediarios"] is True


def test_el_paquete_dice_lo_que_no_lleva_dentro() -> None:
    """Sin esa lista el cliente cree que se lo lleva todo, y descubre el hueco
    cuando ya ha apagado lo otro."""
    salida = sop.preparar_exportacion(
        formato="csv", objetos=["contacto"], incluye_referencias=["notas de OneNote"]
    )
    assert salida["no_lleva_dentro"][0]["que"] == "notas de OneNote"


def test_un_formato_inventado_se_rechaza() -> None:
    with pytest.raises(ErrorValidacion) as fallo:
        sop.preparar_exportacion(formato="lo_que_sea", objetos=[])
    assert fallo.value.error_code == "suite.formato_desconocido"


def test_la_importacion_se_enseña_antes_de_ejecutarse() -> None:
    """Deshacer a mano una importación de diez mil filas no lo hace nadie: se
    queda."""
    salida = sop.comprobar_importacion(
        formato="csv",
        filas=[{"id_externo": "1", "nombre": "A"}, {"nombre": "B"}, {"id_externo": "3"}],
    )
    assert salida["se_importa_ya"] is False
    assert salida["sin_identificador"] == 1
    assert salida["vacias"] == 1


# ── Reglas de qué entra (CRM-06.01.03.14) ─────────────────────────────────


def test_la_regla_del_usuario_no_puede_ensanchar_la_del_tenant() -> None:
    """Si pudiera, la política de la empresa sería una sugerencia."""
    salida = sop.combinar_reglas(
        del_tenant={"criterio": "con_contacto_del_crm", "recursos": ["correo"]},
        del_usuario={"criterio": "todo", "recursos": ["correo"]},
    )
    assert salida["criterio"] == "con_contacto_del_crm"
    assert "sería una sugerencia" in salida["ignorado_del_usuario"]


def test_la_regla_del_usuario_si_puede_estrechar() -> None:
    salida = sop.combinar_reglas(
        del_tenant={"criterio": "todo", "recursos": ["correo", "calendario"]},
        del_usuario={"criterio": "marcado_por_el_usuario", "recursos": ["calendario"]},
    )
    assert salida["criterio"] == "marcado_por_el_usuario"
    assert salida["recursos"] == ["calendario"]


def test_lo_privado_no_entra_diga_lo_que_diga_la_configuracion() -> None:
    """No es una casilla, porque una casilla acaba desmarcada."""
    reglas = sop.combinar_reglas(
        del_tenant={"criterio": "todo", "recursos": ["correo"]}, del_usuario=None
    )
    pasa, porque = sop.entra(elemento={"marcado_privado": True, "recurso": "correo"}, reglas=reglas)
    assert pasa is False
    assert "acaba desmarcada" in porque


def test_se_dice_por_que_algo_no_entro() -> None:
    """Sin el motivo, el usuario ve que «no se sincroniza nada» y no sabe si es
    que no hay nada."""
    reglas = sop.combinar_reglas(
        del_tenant={"criterio": "todo", "recursos": ["correo"]}, del_usuario=None
    )
    pasa, porque = sop.entra(elemento={"recurso": "notas"}, reglas=reglas)
    assert pasa is False
    assert "no está autorizado" in porque


# ── Límites del proveedor (CRM-06.01.03.15) ───────────────────────────────


def test_se_espera_lo_que_diga_el_proveedor() -> None:
    """Reintentar antes gasta cuota para que vuelva a decir que no, y de paso
    parece un ataque."""
    salida = sop.como_reintentar(codigo=429, cabecera_reintento="120", intento=1)
    assert salida["esperar_s"] == 120
    assert salida["lo_dice_el_proveedor"] is True


def test_un_403_no_se_reintenta() -> None:
    """No se arregla insistiendo: falta un permiso, y lo que hay que hacer es
    decirlo."""
    salida = sop.como_reintentar(codigo=403, cabecera_reintento=None, intento=1)
    assert salida["reintentar"] is False
    assert "en el panel" in salida["que_hacer"]


def test_la_espera_creciente_tiene_tope() -> None:
    """Sin tope, el sexto intento espera una hora y parece muerto."""
    salida = sop.como_reintentar(codigo=503, cabecera_reintento=None, intento=9)
    assert salida["esperar_s"] == 900


def test_la_primera_carga_no_se_come_la_cuota_de_los_demas() -> None:
    """El que acaba de conectar su buzón no puede parar al resto."""
    salida = sop.ritmo_de_primera_carga(elementos=30_000, peticiones_por_minuto=600)
    assert salida["peticiones_por_minuto"] == 300
    assert salida["acotado"] is True


def test_sin_limite_declarado_no_se_puede_repartir_y_se_dice() -> None:
    salida = sop.ritmo_de_primera_carga(elementos=100, peticiones_por_minuto=None)
    assert salida["acotado"] is False
    assert "cuota del tenant entero" in salida["aviso"]


# ── Panel de salud (CRM-06.01.03.16) ──────────────────────────────────────


def test_lo_que_no_se_ha_medido_no_esta_en_verde() -> None:
    """Un panel que solo cuenta lo sincronizado enseña un número que sube
    mientras tres buzones llevan una semana parados."""
    salida = sop.salud(
        conexiones=[{"id": "a", "estado": "conectado", "sincronizado_at": None}], ahora=AHORA
    )
    assert salida["todo_bien"] is False
    assert salida["sin_medir"] == ["a"]


def test_sin_ninguna_conexion_no_se_dice_que_va_bien() -> None:
    salida = sop.salud(conexiones=[], ahora=AHORA)
    assert salida["medible"] is False
    assert "sin usar" in salida["que_significa"]


def test_una_conexion_parada_sale_con_sus_horas_y_su_motivo() -> None:
    salida = sop.salud(
        conexiones=[
            {
                "id": "a",
                "estado": "error",
                "motivo": "credencial caducada",
                "sincronizado_at": AHORA - timedelta(days=3),
            }
        ],
        ahora=AHORA,
    )
    assert salida["paradas"][0]["horas_sin_sincronizar"] == 72.0
    assert salida["paradas"][0]["porque"] == "credencial caducada"


def test_una_parada_sin_motivo_anotado_lo_dice() -> None:
    """Sin motivo, nadie sabrá qué mirar."""
    salida = sop.salud(
        conexiones=[{"id": "a", "estado": "error", "sincronizado_at": AHORA}], ahora=AHORA
    )
    assert "nadie sabrá qué mirar" in salida["paradas"][0]["porque"]


def test_las_que_van_por_sondeo_se_dicen_aparte() -> None:
    """Sus cambios entran con retraso, no al instante, y el usuario tiene derecho
    a saberlo."""
    salida = sop.salud(
        conexiones=[
            {"id": "a", "estado": "conectado", "sincronizado_at": AHORA, "en_sondeo": True}
        ],
        ahora=AHORA,
    )
    assert salida["en_sondeo"] == ["a"]
    assert "con retraso" in salida["los_en_sondeo"]


# ── Baja (CRM-06.01.03.17) ────────────────────────────────────────────────


def test_las_actividades_se_quedan_y_la_agenda_se_va() -> None:
    """Las primeras son el registro de la empresa; la segunda era suya."""
    salida = sop.plan_de_baja(motivo="baja_del_usuario")
    assert any("actividades" in x["que"].lower() for x in salida["se_queda"])
    assert any("agenda personal" in x["que"].lower() for x in salida["se_borra"])


def test_la_suscripcion_se_borra_tambien_en_el_proveedor() -> None:
    """Si se quita solo de este lado, el proveedor sigue mandando avisos y el CRM
    sigue teniendo permiso para leer el buzón."""
    salida = sop.plan_de_baja(motivo="revocacion")
    assert salida["se_borra_en_el_proveedor"]


def test_la_prueba_del_consentimiento_no_se_borra() -> None:
    """Borrarla es borrar la prueba de que se hizo bien."""
    salida = sop.plan_de_baja(motivo="fin_del_contrato")
    assert any("consentimiento" in x["que"].lower() for x in salida["se_queda"])


def test_dar_de_baja_a_alguien_no_desconecta_el_buzon_del_equipo() -> None:
    salida = sop.plan_de_baja(motivo="baja_del_usuario", hay_buzon_compartido=True)
    assert "es del equipo" in salida["aviso"]


# ── Identidad (CRM-06.01.03.19) ───────────────────────────────────────────


def test_un_alias_resuelve_a_la_misma_persona() -> None:
    """Si cada alias fuera a un usuario distinto, la misma conversación
    aparecería dos veces atribuida a dos comerciales."""
    usuarios = [{"id": "u1", "email": "juan.perez@acme.com", "alias": ["j.perez@acme.com"]}]
    salida = sop.resolver_cuenta(direccion_del_proveedor="J.Perez@acme.com", usuarios=usuarios)
    assert salida["usuario_id"] == "u1"


def test_un_buzon_compartido_no_tiene_dueno() -> None:
    """Atribuirlo a quien lo conectó le pone en su nombre correos que no
    escribió, y eso acaba en la comisión de alguien."""
    usuarios = [
        {
            "id": "u1",
            "email": "ana@acme.com",
            "compartidos": ["ventas@acme.com"],
            "equipo": "ventas",
        }
    ]
    salida = sop.resolver_cuenta(direccion_del_proveedor="ventas@acme.com", usuarios=usuarios)
    assert salida["es_compartido"] is True
    assert salida["usuario_id"] is None


def test_una_direccion_en_dos_usuarios_es_ambigua_y_no_se_adivina() -> None:
    usuarios = [
        {"id": "u1", "email": "info@acme.com"},
        {"id": "u2", "alias": ["info@acme.com"]},
    ]
    salida = sop.resolver_cuenta(direccion_del_proveedor="info@acme.com", usuarios=usuarios)
    assert salida.get("ambiguo") is True
    assert salida["usuario_id"] is None


def test_una_direccion_desconocida_no_se_atribuye_a_nadie() -> None:
    salida = sop.resolver_cuenta(direccion_del_proveedor="x@y.z", usuarios=[])
    assert salida["usuario_id"] is None
    assert "no se adivina" in salida["porque"].lower()


# ── Diagnóstico (CRM-06.01.03.20) ─────────────────────────────────────────


def test_se_dice_qué_alcance_falta_y_no_error_de_autenticacion() -> None:
    """«Error de autenticación» es el mensaje que atasca una implantación una
    semana y acaba con permisos de administrador global «para descartar»."""
    salida = sop.diagnosticar(
        codigo=403,
        alcances_concedidos=["Calendars.Read"],
        alcances_necesarios=["Calendars.Read", "Mail.Read"],
    )
    assert salida["faltan_alcances"] == ["Mail.Read"]
    assert "para descartar" in salida["que_hacer"]


def test_un_401_es_la_credencial_y_no_los_permisos() -> None:
    salida = sop.diagnosticar(codigo=401, alcances_concedidos=["a"], alcances_necesarios=["a"])
    assert "volver a autorizar" in salida["que_hacer"]


def test_un_403_con_permisos_completos_es_del_inquilino_del_cliente() -> None:
    """No se arregla desde el CRM: hay que hablar con quien administre su suite."""
    salida = sop.diagnosticar(codigo=403, alcances_concedidos=["a"], alcances_necesarios=["a"])
    assert "inquilino del cliente" in salida["que_hacer"]


def test_lo_que_dijo_el_proveedor_se_enseña_tal_cual() -> None:
    salida = sop.diagnosticar(
        codigo=418,
        alcances_concedidos=[],
        alcances_necesarios=[],
        mensaje_del_proveedor="AADSTS50076",
    )
    assert salida["mensaje_del_proveedor"] == "AADSTS50076"


def test_los_alcances_se_comprueban_antes_de_llamar() -> None:
    """Llamar sin el permiso y esperar el 403 gasta una petición de la cuota del
    tenant para averiguar algo que ya se sabía."""
    with pytest.raises(Prohibido) as fallo:
        sop.exigir_alcances(concedidos=["a"], necesarios=["a", "b"])
    assert fallo.value.error_code == "suite.alcance_insuficiente"


def test_todo_en_orden_se_dice_con_los_alcances() -> None:
    salida = sop.diagnosticar(codigo=200, alcances_concedidos=["a"], alcances_necesarios=["a"])
    assert salida["ok"] is True
