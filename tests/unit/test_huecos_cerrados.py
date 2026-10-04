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


# ── Umbrales que estaban escritos y no se leían ───────────────────────────


def test_el_cortacircuitos_lee_su_umbral_de_la_configuracion(monkeypatch: Any) -> None:
    """`CB_UMBRAL_FALLOS` existía, se documentaba y no lo leía nadie.

    El cortacircuitos llevaba un `5` escrito en el código. Una instalación que
    quisiera abrir antes —porque su proveedor de correo se cae a menudo y no
    quiere gastar hilos reintentando contra algo caído— cambiaba un número en la
    pantalla de ajustes y no pasaba nada. Un umbral que nadie consulta no limita.

    Se comprueban **las dos mitades**: con el umbral en 2 abre al segundo fallo,
    y con el umbral en 10 no ha abierto al segundo. Sin la segunda, un cambio
    que abriera siempre pasaría igual.
    """
    from crmcore.config import get_settings
    from crmcore.resiliencia import _circuitos, anotar_fallo, circuito_abierto

    monkeypatch.setenv("CB_UMBRAL_FALLOS", "2")
    get_settings.cache_clear()
    _circuitos.pop("recurso-a", None)
    anotar_fallo("recurso-a")
    assert not circuito_abierto("recurso-a"), "ha abierto al primer fallo con el umbral en 2"
    anotar_fallo("recurso-a")
    assert circuito_abierto("recurso-a"), "con el umbral en 2 tendría que estar abierto"

    monkeypatch.setenv("CB_UMBRAL_FALLOS", "10")
    get_settings.cache_clear()
    _circuitos.pop("recurso-b", None)
    anotar_fallo("recurso-b")
    anotar_fallo("recurso-b")
    assert not circuito_abierto("recurso-b"), (
        "con el umbral en 10 no puede estar abierto a los dos fallos: si lo está, "
        "el umbral no se está leyendo"
    )
    get_settings.cache_clear()
    _circuitos.pop("recurso-a", None)
    _circuitos.pop("recurso-b", None)


def test_el_cortacircuitos_lee_su_descanso_de_la_configuracion(monkeypatch: Any) -> None:
    """`CB_REPOSO_S`, lo mismo. Se mira el valor que queda apuntado en el
    circuito, no se espera al reloj: una prueba que duerme 30 segundos no la
    corre nadie."""
    from crmcore.config import get_settings
    from crmcore.resiliencia import _circuitos, anotar_fallo

    monkeypatch.setenv("CB_UMBRAL_FALLOS", "1")
    monkeypatch.setenv("CB_REPOSO_S", "120")
    get_settings.cache_clear()
    _circuitos.pop("recurso-c", None)

    anotar_fallo("recurso-c")

    assert _circuitos["recurso-c"].descanso_s == 120.0
    get_settings.cache_clear()
    _circuitos.pop("recurso-c", None)


def test_quien_llame_con_sus_propios_valores_los_impone(monkeypatch: Any) -> None:
    """La configuración es el valor por defecto, no una camisa de fuerza.

    Hay recursos que merecen otro trato —un proveedor de inferencia caro no se
    reintenta como una caché— y eso se decide en la llamada.
    """
    from crmcore.config import get_settings
    from crmcore.resiliencia import _circuitos, anotar_fallo, circuito_abierto

    monkeypatch.setenv("CB_UMBRAL_FALLOS", "10")
    get_settings.cache_clear()
    _circuitos.pop("recurso-d", None)

    anotar_fallo("recurso-d", umbral=1)

    assert circuito_abierto("recurso-d")
    get_settings.cache_clear()
    _circuitos.pop("recurso-d", None)


def test_los_umbrales_de_degradacion_salen_de_la_configuracion(monkeypatch: Any) -> None:
    """`DEGRADACION_UMBRAL_POOL` existía, se documentaba y no lo leía nadie.

    `admite` decidía con un 0.9 y un 0.6 escritos en el código. Quien bajara el
    umbral para proteger antes su instalación cambiaba un número que no hacía
    nada — y lo peor de todo es que la pantalla de ajustes decía que sí.

    Las dos mitades: con el umbral bajo se difiere, con el umbral alto pasa.
    """
    from crmcore.config import get_settings
    from crmcore.resiliencia import CRITICA, DIFERIBLE, NORMAL, admite, fijar_presion

    fijar_presion(0.7)

    monkeypatch.setenv("DEGRADACION_UMBRAL_POOL", "0.5")
    monkeypatch.setenv("DEGRADACION_UMBRAL_NORMAL", "0.8")
    get_settings.cache_clear()
    assert not admite(DIFERIBLE), "con el umbral en 0.5 y presión 0.7 tendría que diferirse"
    assert admite(NORMAL), "con el umbral normal en 0.8 y presión 0.7 tendría que pasar"

    monkeypatch.setenv("DEGRADACION_UMBRAL_POOL", "0.9")
    monkeypatch.setenv("DEGRADACION_UMBRAL_NORMAL", "0.6")
    get_settings.cache_clear()
    assert admite(DIFERIBLE), (
        "con el umbral en 0.9 y presión 0.7 tendría que pasar: si no, el umbral "
        "no se lee y lo que hay es un rechazo constante"
    )
    assert not admite(NORMAL), "con el umbral normal en 0.6 y presión 0.7 tendría que cortarse"

    # Lo crítico no cae nunca, pongamos lo que pongamos: una escritura de
    # cliente no se difiere porque el sistema vaya cargado.
    fijar_presion(1.0)
    assert admite(CRITICA)

    fijar_presion(0.0)
    get_settings.cache_clear()


def test_los_perfiles_de_proveedor_se_alcanzan_desde_la_api() -> None:
    """Estaban declarados, probados y **sin ninguna ruta** (`CRM-00.05.01.16`).

    Quien configuraba un proveedor tenía que saberse de memoria qué campo trae
    el correo en el suyo. Equivocarse ahí no da un error: da un usuario que
    entra sin grupos y sin permisos, y nadie lo relaciona con el campo mal
    escrito — que es exactamente lo que los perfiles existen para evitar.
    """
    import inspect

    from services.identity import api_sso

    fuente = inspect.getsource(api_sso)
    assert (
        "PERFILES_SSO" in fuente
    ), "los perfiles no se alcanzan desde ninguna ruta: existen y no los ve nadie"
    assert "perfil_sso(" in fuente, "no hay forma de resolver un perfil con los ajustes encima"
