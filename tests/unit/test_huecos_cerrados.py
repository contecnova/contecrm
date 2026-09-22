"""Los huecos que el manual declaraba, cerrados
(CRM-06.02.01.07, .08, CRM-01.01.01.13, CRM-03.03.02.07, CRM-00.05.01.16, .19,
.21, .22, .23, CRM-06.02.01.06).

Cada prueba de aquí defiende algo que el producto **decía que le faltaba**. No
son mejoras: son promesas que estaban escritas en el manual como pendientes, y lo
que se comprueba es que ahora se cumplen de verdad y no de boquilla.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from crmcore.errors import ErrorValidacion

from services.identity import factores as fac
from services.identity import servicio as idsvc
from services.identity import sso

# ── Plantilla de notificación por canal (CRM-06.02.01.07) ─────────────────


@pytest.mark.db
def test_hay_plantilla_distinta_para_el_sms_y_para_el_correo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Una de SMS no es la de correo con menos letras: dice lo imprescindible y
    pone un enlace. Recortar la de correo a 160 era el problema."""
    from crmcore.notificaciones.plantillas_replicadas import aplicar, elegir

    aplicar(
        db,
        tenant_id=tenant_id,
        clave="tarea_vencida",
        idioma="es",
        canal="correo",
        asunto="Tienes una tarea vencida",
        cuerpo="Hola {{nombre}}, la tarea «{{asunto}}» venció ayer.",
    )
    aplicar(
        db,
        tenant_id=tenant_id,
        clave="tarea_vencida",
        idioma="es",
        canal="sms",
        cuerpo="Tarea vencida: {{asunto}}",
    )
    correo = elegir(db, tenant_id, clave="tarea_vencida", canal="correo", idiomas=["es"])
    sms = elegir(db, tenant_id, clave="tarea_vencida", canal="sms", idiomas=["es"])
    assert correo is not None and sms is not None
    assert correo.cuerpo != sms.cuerpo


@pytest.mark.db
def test_una_plantilla_a_la_que_le_falta_un_dato_no_se_manda(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """«Hola {{nombre}}» llegando así es peor que un texto genérico, porque el
    genérico no parece roto."""
    from crmcore.notificaciones.plantillas_replicadas import aplicar, render

    plantilla = aplicar(
        db,
        tenant_id=tenant_id,
        clave="bienvenida",
        idioma="es",
        canal="correo",
        cuerpo="Hola {{nombre}}, bienvenido.",
    )
    salida = render(plantilla, {})
    assert salida["sirve"] is False
    assert "nombre" in salida["faltan"]


@pytest.mark.db
def test_el_idioma_cae_hacia_atras_con_orden(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """«La primera que haya» manda un aviso en alemán a quien pidió español."""
    from crmcore.notificaciones.plantillas_replicadas import aplicar, elegir

    aplicar(db, tenant_id=tenant_id, clave="aviso", idioma="de", canal="correo", cuerpo="Hallo")
    aplicar(db, tenant_id=tenant_id, clave="aviso", idioma="es", canal="correo", cuerpo="Hola")
    elegida = elegir(db, tenant_id, clave="aviso", canal="correo", idiomas=["es", "de"])
    assert elegida is not None and elegida.idioma == "es"


# ── Estadísticas de entrega (CRM-06.02.01.08) ─────────────────────────────


@pytest.mark.db
def test_sin_proveedor_que_reporte_la_apertura_no_es_cero(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un panel con 0 % de apertura hace que alguien concluya que sus correos no
    interesan, cuando lo que pasa es que su transporte no lo mide."""
    from crmcore.notificaciones.entrega import estadisticas_de_entrega

    salida = estadisticas_de_entrega(db, tenant_id)
    assert salida["medible"] is False
    assert salida["tasa_apertura_pct"] is None
    assert "NO son cero" in salida["porque"]


@pytest.mark.db
def test_un_rebote_duro_cierra_la_direccion(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Anotarlo y seguir escribiendo sería tener la información y no usarla, que
    es peor que no tenerla."""
    from crmcore.notificaciones.entrega import anotar_suceso

    salida = anotar_suceso(
        db,
        tenant_id=tenant_id,
        entrega_id=None,
        direccion="nadie@example.com",
        suceso="rebote_duro",
    )
    assert salida["cierra_la_direccion"] is True
    assert "reputación" in salida["que_hacer"]


@pytest.mark.db
def test_un_suceso_inventado_no_entra(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    from crmcore.notificaciones.entrega import anotar_suceso

    with pytest.raises(ErrorValidacion):
        anotar_suceso(
            db, tenant_id=tenant_id, entrega_id=None, direccion="x@y.com", suceso="lo_que_sea"
        )


# ── MFA adaptativa y ciclo del factor (CRM-00.05.01.19, .21, .23) ─────────


def test_el_salto_imposible_no_se_resuelve_solo_pidiendo_un_codigo() -> None:
    """Dos países en dos horas: o hay un avión imposible o hay dos personas."""
    salida = fac.evaluar_riesgo(
        ip_conocida=True,
        pais_conocido=True,
        dispositivo_conocido=True,
        minutos_desde_otro_pais=30,
    )
    assert salida["exigir_factor"] is True
    assert salida["sospechoso"] is True
    assert "sesiones abiertas" in salida["que_hacer_si_sospechoso"]


def test_cada_motivo_se_explica_con_palabras() -> None:
    """«Por seguridad» no explica nada, y al tercer aviso así la gente teclea el
    código sin mirar."""
    salida = fac.evaluar_riesgo(ip_conocida=False, pais_conocido=True, dispositivo_conocido=True)
    assert "red desde la que no habías entrado" in salida["explicacion"]


def test_sin_cambio_de_contexto_no_se_pide_el_factor() -> None:
    salida = fac.evaluar_riesgo(ip_conocida=True, pais_conocido=True, dispositivo_conocido=True)
    assert salida["exigir_factor"] is False


def test_un_solo_factor_no_es_tener_mfa() -> None:
    """Quien solo tiene el móvil y lo pierde acaba desbloqueado por teléfono, que
    es la puerta de atrás por la que se entra de verdad."""
    salida = fac.plan_de_inscripcion(factores_activos=["totp"])
    assert salida["completo"] is False
    assert any(p["paso"] == "inscribir_respaldo" for p in salida["pasos"])


def test_cambiar_de_movil_sin_respaldo_exige_dos_aprobadores() -> None:
    """Una sola firma convierte una llamada convincente en un acceso."""
    salida = fac.cambio_de_dispositivo(tiene_respaldo=False, factor_verificado=False)
    assert salida["puede_solo"] is False
    assert salida["aprobadores_necesarios"] == fac.APROBADORES_DESBLOQUEO


def test_con_respaldo_el_cambio_de_movil_se_hace_solo() -> None:
    salida = fac.cambio_de_dispositivo(tiene_respaldo=True, factor_verificado=True)
    assert salida["puede_solo"] is True


def test_sin_contrasena_solo_con_factor_resistente_a_phishing() -> None:
    """Con un SMS como método único se quita la contraseña y se queda lo más
    débil de los dos."""
    sms = fac.puede_entrar_sin_contrasena(
        factor="sms", resistente_a_phishing=False, tiene_respaldo=True
    )
    llave = fac.puede_entrar_sin_contrasena(
        factor="fido2", resistente_a_phishing=True, tiene_respaldo=True
    )
    assert sms["puede"] is False
    assert llave["puede"] is True


def test_sin_contrasena_hace_falta_respaldo() -> None:
    """Sin contraseña no hay red debajo: perder la llave deja fuera del todo."""
    salida = fac.puede_entrar_sin_contrasena(
        factor="fido2", resistente_a_phishing=True, tiene_respaldo=False
    )
    assert salida["puede"] is False


# ── Perfiles de proveedor, sin módulo por casa (CRM-00.05.01.16, .22) ─────


def test_un_perfil_desconocido_no_cae_al_generico_en_silencio() -> None:
    """Caer al genérico produce un usuario que entra sin grupos y sin permisos, y
    nadie relaciona eso con que el perfil estaba mal escrito."""
    with pytest.raises(ErrorValidacion) as fallo:
        sso.perfil_sso("el_de_siempre")
    assert fallo.value.error_code == "sso.perfil_desconocido"


def test_el_perfil_de_sso_es_configuracion_y_no_codigo() -> None:
    salida = sso.perfil_sso("oidc_generico", {"campo_grupos": "roles"})
    assert salida["config"]["campo_grupos"] == "roles"
    assert salida["completo"] is True


def test_un_perfil_sin_campo_de_correo_no_esta_completo() -> None:
    """El usuario entra sin identidad utilizable: no es un error visible, es un
    usuario que no encaja con ninguna cuenta."""
    salida = sso.perfil_sso("saml_generico", {"campo_email": ""})
    assert salida["completo"] is False


def test_hay_perfil_de_mfa_declarado() -> None:
    assert "webauthn" in sso.PERFILES_MFA
    assert sso.perfil_mfa("webauthn")["tipo"] == "webauthn"


# ── Invitados externos (CRM-06.02.01.06) ──────────────────────────────────


@pytest.mark.db
def test_una_invitacion_sin_motivo_no_se_puede_revisar(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Quien la mire dentro de un año verá un correo ajeno y no podrá decidir
    nada."""
    from crmcore.db.uow import UnidadDeTrabajo

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    with pytest.raises(ErrorValidacion) as fallo:
        idsvc.invitar_externo(uow, email="auditor@fuera.com", motivo="", permisos=["account:read"])
    assert fallo.value.error_code == "identity.invitacion_sin_motivo"


@pytest.mark.db
def test_una_invitacion_sin_plazo_no_existe(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un acceso de invitado sin fecha se queda abierto para siempre."""
    from crmcore.db.uow import UnidadDeTrabajo

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    with pytest.raises(ErrorValidacion) as fallo:
        idsvc.invitar_externo(
            uow,
            email="auditor@fuera.com",
            motivo="Auditoría anual",
            permisos=["account:read"],
            dias=400,
        )
    assert fallo.value.error_code == "identity.invitacion_plazo_invalido"


@pytest.mark.db
def test_una_invitacion_valida_caduca_sola(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    from crmcore.db.uow import UnidadDeTrabajo

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    salida = idsvc.invitar_externo(
        uow,
        email="Auditor@Fuera.com",
        motivo="Auditoría anual de cumplimiento",
        permisos=["account:read", "contact:read"],
        dias=30,
    )
    assert salida["email"] == "auditor@fuera.com"
    assert salida["caduca_at"]
    assert "caduca solo" in salida["porque"]


# ── Reverificación periódica con cuota (CRM-01.01.01.13) ──────────────────


@pytest.mark.db
def test_el_barrido_de_reverificacion_tiene_tope(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un barrido sin control agota la cuota del registro oficial en una mañana y
    deja sin verificar las altas del día, que son las que alguien espera."""
    from crmcore.db.uow import UnidadDeTrabajo

    from services.party import servicio as psvc

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    salida = psvc.barrer_reverificaciones(uow, limite=10)
    assert salida["tope"] == 10
    assert salida["al_dia"] is True
    assert "urgencia" in salida["que_significa"] or salida["quedan_caducados"] == 0
