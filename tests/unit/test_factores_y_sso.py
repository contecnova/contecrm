"""Segundo factor y gobierno del SSO (CRM-00.05.01.11 a .25).

El peso está en lo que falla en silencio: un OTP sin tope de intentos, un
step-up que da por bueno un factor de hace ocho horas, un certificado que caduca
un sábado y un «salir» que no sale del IdP.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from crmcore.errors import Conflicto, ErrorValidacion, LimiteExcedido, NoAutenticado, Prohibido
from crmcore.notificaciones import Destino, Mensaje, Resultado

from services.identity import factores, sso_gobierno
from services.identity.modelos import (
    AsercionConsumida,
    Membresia,
    ProveedorIdentidad,
    Sesion,
    Usuario,
)


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


class _TransporteFalso:
    """Transporte de pruebas que guarda lo enviado.

    Se registra con el nombre del canal real porque lo que se quiere comprobar
    es justo el paso por el transporte genérico: sustituir la función de envío
    dejaría sin probar el único sitio donde el código toca el exterior.
    """

    def __init__(self, canal: str) -> None:
        self.canal = canal
        self.enviados: list[Mensaje] = []
        self.falla = False

    def entregar(self, destino: Destino, mensaje: Mensaje, config: dict[str, Any]) -> Resultado:
        if self.falla:
            return Resultado(entregado=False, detalle="pasarela caída", reintentar=True)
        self.enviados.append(mensaje)
        return Resultado(entregado=True, referencia="ref-1")


@pytest.fixture
def transporte_sms(monkeypatch: Any) -> _TransporteFalso:
    falso = _TransporteFalso("sms")
    from crmcore.notificaciones import base

    monkeypatch.setitem(base._TRANSPORTES, "sms", falso)
    return falso


@pytest.fixture
def otp_activo(db: Any, monkeypatch: Any) -> None:
    from crmcore.runtime import settings as rt

    reales = rt.efectivo

    def falso(clave: str, sesion: Any = None, **kw: Any) -> Any:
        if clave == "otp_sms_enabled":
            return True
        if clave == "otp_email_enabled":
            return True
        return reales(clave, sesion, **kw)

    monkeypatch.setattr(rt, "efectivo", falso)
    monkeypatch.setattr(factores.rt, "efectivo", falso)


def _usuario(db: Any, tenant_id: UUID, email: str = "ana@ejemplo.com") -> Usuario:
    usuario = Usuario(email=email, nombre="Ana Ruiz")
    db.add(usuario)
    db.flush()
    db.add(Membresia(tenant_id=tenant_id, usuario_id=usuario.id, roles=[]))
    db.flush()
    return usuario


# ── OTP por SMS y correo (CRM-00.05.01.17) ────────────────────────────────


@pytest.mark.db
def test_el_canal_apagado_no_manda_nada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, transporte_sms: Any
) -> None:
    """El SMS va apagado de fábrica porque es el factor más débil: se intercepta
    con un cambio de SIM que no depende de nadie de aquí."""
    usuario = _usuario(db, tenant_id)
    with pytest.raises(Prohibido) as e:
        factores.emitir_desafio(db, usuario, tenant_id, canal="sms", direccion="+34600000034")
    assert e.value.error_code == "factor.canal_desactivado"
    assert transporte_sms.enviados == []


@pytest.mark.db
def test_el_codigo_nunca_vuelve_en_la_respuesta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, transporte_sms: Any, otp_activo: None
) -> None:
    """Devolverlo «para pruebas» es el atajo que acaba en producción."""
    usuario = _usuario(db, tenant_id)
    salida = factores.emitir_desafio(db, usuario, tenant_id, canal="sms", direccion="+34600000034")
    assert not hasattr(salida, "codigo")
    assert "codigo" not in salida.__dict__ if hasattr(salida, "__dict__") else True
    assert len(transporte_sms.enviados) == 1


@pytest.mark.db
def test_la_direccion_se_enseña_recortada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, transporte_sms: Any, otp_activo: None
) -> None:
    """La pantalla del segundo factor se ve ANTES de estar autenticado del todo:
    enseñar el teléfono entero convertiría el login en una forma de leer el
    número de cualquiera con solo saber su correo."""
    usuario = _usuario(db, tenant_id)
    salida = factores.emitir_desafio(db, usuario, tenant_id, canal="sms", direccion="+34600000034")
    assert salida.destino_visible.endswith("34")
    assert "600000" not in salida.destino_visible


@pytest.mark.db
def test_un_codigo_correcto_vale_una_sola_vez(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, transporte_sms: Any, otp_activo: None
) -> None:
    usuario = _usuario(db, tenant_id)
    factores.emitir_desafio(db, usuario, tenant_id, canal="sms", direccion="+34600000034")
    codigo = transporte_sms.enviados[-1].datos["codigo"]

    factores.comprobar_desafio(db, usuario.id, tenant_id, codigo)
    with pytest.raises(NoAutenticado) as e:
        factores.comprobar_desafio(db, usuario.id, tenant_id, codigo)
    assert e.value.error_code == "factor.sin_desafio"


@pytest.mark.db
def test_los_intentos_estan_contados(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, transporte_sms: Any, otp_activo: None
) -> None:
    """Seis dígitos son un millón de combinaciones: sin tope se agotan a fuerza
    bruta en minutos, y entonces el OTP no aporta nada."""
    usuario = _usuario(db, tenant_id)
    factores.emitir_desafio(db, usuario, tenant_id, canal="sms", direccion="+34600000034")

    for _ in range(4):
        with pytest.raises(NoAutenticado):
            factores.comprobar_desafio(db, usuario.id, tenant_id, "000000")
    with pytest.raises(LimiteExcedido) as e:
        factores.comprobar_desafio(db, usuario.id, tenant_id, "000000")
    assert e.value.error_code == "factor.intentos_agotados"


@pytest.mark.db
def test_un_codigo_caducado_no_vale(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, transporte_sms: Any, otp_activo: None
) -> None:
    from services.identity.modelos import DesafioFactor

    usuario = _usuario(db, tenant_id)
    factores.emitir_desafio(db, usuario, tenant_id, canal="sms", direccion="+34600000034")
    codigo = transporte_sms.enviados[-1].datos["codigo"]

    fila = db.query(DesafioFactor).filter(DesafioFactor.usuario_id == usuario.id).one()
    fila.expira_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.flush()

    with pytest.raises(NoAutenticado) as e:
        factores.comprobar_desafio(db, usuario.id, tenant_id, codigo)
    assert e.value.error_code == "factor.caducado"


@pytest.mark.db
def test_reenviar_demasiado_pronto_se_frena(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, transporte_sms: Any, otp_activo: None
) -> None:
    """Sin espera, «reenviar código» es un amplificador de SMS a costa del
    cliente: un bucle en el navegador y la factura del mes."""
    usuario = _usuario(db, tenant_id)
    factores.emitir_desafio(db, usuario, tenant_id, canal="sms", direccion="+34600000034")
    with pytest.raises(LimiteExcedido) as e:
        factores.emitir_desafio(db, usuario, tenant_id, canal="sms", direccion="+34600000034")
    assert e.value.error_code == "factor.reenvio_demasiado_pronto"


@pytest.mark.db
def test_si_el_envio_falla_se_dice(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, transporte_sms: Any, otp_activo: None
) -> None:
    """Tragarse el error dejaría al usuario esperando un código que no va a
    llegar, con el sistema diciendo que todo fue bien."""
    usuario = _usuario(db, tenant_id)
    transporte_sms.falla = True
    with pytest.raises(Prohibido) as e:
        factores.emitir_desafio(db, usuario, tenant_id, canal="sms", direccion="+34600000034")
    assert e.value.error_code == "factor.envio_fallido"


@pytest.mark.db
def test_sin_direccion_no_es_un_error_del_sistema(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, transporte_sms: Any, otp_activo: None
) -> None:
    """Es un dato que falta, y decirlo así evita que soporte busque un fallo de
    envío que no existe."""
    usuario = _usuario(db, tenant_id)
    with pytest.raises(ErrorValidacion) as e:
        factores.emitir_desafio(db, usuario, tenant_id, canal="sms", direccion="")
    assert e.value.error_code == "factor.sin_direccion"


# ── Step-up (CRM-00.05.01.18) ─────────────────────────────────────────────


def _sesion(db: Any, usuario: Usuario, tenant_id: UUID) -> Sesion:
    fila = Sesion(
        tenant_id=tenant_id,
        usuario_id=usuario.id,
        hash_refresco=uuid4().hex,
        expira_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db.add(fila)
    db.flush()
    return fila


@pytest.mark.db
def test_sin_factor_fuerte_la_operacion_sensible_se_corta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    usuario = _usuario(db, tenant_id)
    sesion = _sesion(db, usuario, tenant_id)
    with pytest.raises(NoAutenticado) as e:
        factores.exige_reautenticacion(db, sesion, "exportacion_masiva")
    assert e.value.error_code == "stepup.requerido"
    # Se distingue «no tienes factor» de «vuelve a verificarte»: para quien está
    # delante de la pantalla son dos cosas muy distintas.
    assert e.value.detalle["tiene_factor"] is False


@pytest.mark.db
def test_un_factor_reciente_deja_pasar(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    usuario = _usuario(db, tenant_id)
    sesion = _sesion(db, usuario, tenant_id)
    factores.anotar_factor(db, sesion, "totp")
    factores.exige_reautenticacion(db, sesion, "exportacion_masiva")


@pytest.mark.db
def test_un_factor_de_hace_horas_ya_no_vale(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Es todo el punto: la sesión dura horas porque renovarla cada cuarto de
    hora haría el producto inusable, y una exportación de toda la base a las seis
    de la tarde no puede apoyarse en un factor de las nueve de la mañana."""
    usuario = _usuario(db, tenant_id)
    sesion = _sesion(db, usuario, tenant_id)
    factores.anotar_factor(db, sesion, "totp")
    sesion.factor_fuerte_at = datetime.now(timezone.utc) - timedelta(hours=8)
    db.flush()

    with pytest.raises(NoAutenticado) as e:
        factores.exige_reautenticacion(db, sesion, "exportacion_masiva")
    assert e.value.detalle["tiene_factor"] is True


@pytest.mark.db
def test_sin_sesion_no_se_deja_pasar(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Dejar pasar «porque no se puede comprobar» es como no tener la
    comprobación."""
    with pytest.raises(NoAutenticado):
        factores.exige_reautenticacion(db, None, "borrado_masivo")


@pytest.mark.db
def test_una_operacion_no_declarada_se_rechaza(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un nombre mal escrito no puede quedarse en «no hace falta step-up»."""
    usuario = _usuario(db, tenant_id)
    sesion = _sesion(db, usuario, tenant_id)
    with pytest.raises(ErrorValidacion) as e:
        factores.exige_reautenticacion(db, sesion, "exportacion_masivaa")
    assert e.value.error_code == "stepup.operacion_desconocida"


def test_un_sms_no_cuenta_como_factor_fuerte() -> None:
    """«Tiene MFA» mete en el mismo saco una passkey y un SMS, y esa es
    exactamente la distinción que alguien querrá hacer al apretar."""
    assert factores.FUERZA["sms"] < factores.FUERZA["totp"] < factores.FUERZA["webauthn"]


# ── Dispositivos de confianza (CRM-00.05.01.20) ───────────────────────────


@pytest.fixture
def confianza_activa(monkeypatch: Any) -> None:
    from crmcore.runtime import settings as rt

    reales = rt.efectivo

    def falso(clave: str, sesion: Any = None, **kw: Any) -> Any:
        if clave == "dispositivo_confianza_dias":
            return 30
        return reales(clave, sesion, **kw)

    monkeypatch.setattr(factores.rt, "efectivo", falso)


@pytest.mark.db
def test_de_fabrica_no_se_recuerda_ningun_equipo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Recordar un equipo es renunciar al segundo factor en ese equipo, y eso lo
    decide el cliente, no nosotros."""
    usuario = _usuario(db, tenant_id)
    with pytest.raises(Prohibido) as e:
        factores.recordar_dispositivo(db, usuario.id, tenant_id, huella="abc")
    assert e.value.error_code == "dispositivo.desactivado"


@pytest.mark.db
def test_un_equipo_recordado_se_reconoce(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, confianza_activa: None
) -> None:
    usuario = _usuario(db, tenant_id)
    factores.recordar_dispositivo(db, usuario.id, tenant_id, huella="portatil-ana")
    assert factores.dispositivo_de_confianza(db, usuario.id, tenant_id, "portatil-ana")


@pytest.mark.db
def test_un_equipo_caducado_deja_de_valer(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, confianza_activa: None
) -> None:
    """La confianza no es para siempre: si lo fuera, el segundo factor se pediría
    una vez en la vida del portátil."""
    usuario = _usuario(db, tenant_id)
    fila = factores.recordar_dispositivo(db, usuario.id, tenant_id, huella="portatil-ana")
    fila.expira_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.flush()
    assert factores.dispositivo_de_confianza(db, usuario.id, tenant_id, "portatil-ana") is None


@pytest.mark.db
def test_la_confianza_no_se_hereda_entre_usuarios(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, confianza_activa: None
) -> None:
    """Un ordenador compartido no hereda la confianza de quien lo usó antes."""
    ana = _usuario(db, tenant_id, "ana@ejemplo.com")
    luis = _usuario(db, tenant_id, "luis@ejemplo.com")
    factores.recordar_dispositivo(db, ana.id, tenant_id, huella="mostrador")
    assert factores.dispositivo_de_confianza(db, luis.id, tenant_id, "mostrador") is None


@pytest.mark.db
def test_revocar_todos_es_el_boton_que_se_usa(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, confianza_activa: None
) -> None:
    """«He perdido el portátil»: uno a uno no sirve cuando ya no se sabe cuáles
    había."""
    usuario = _usuario(db, tenant_id)
    for huella in ("uno", "dos", "tres"):
        factores.recordar_dispositivo(db, usuario.id, tenant_id, huella=huella)
    assert factores.revocar_todos_los_dispositivos(db, usuario.id, tenant_id) == 3
    assert factores.dispositivo_de_confianza(db, usuario.id, tenant_id, "uno") is None


@pytest.mark.db
def test_volver_a_confiar_tras_revocar_es_una_decision_nueva(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, confianza_activa: None
) -> None:
    usuario = _usuario(db, tenant_id)
    fila = factores.recordar_dispositivo(db, usuario.id, tenant_id, huella="portatil")
    factores.revocar_dispositivo(db, fila.id, tenant_id)
    db.flush()
    de_nuevo = factores.recordar_dispositivo(db, usuario.id, tenant_id, huella="portatil")
    assert de_nuevo.revocado_at is None


# ── Delegar el factor al IdP (CRM-00.05.01.24) ────────────────────────────


@pytest.mark.db
def test_sin_lista_declarada_no_se_delega(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Cualquier IdP puede mandar un `amr` que diga lo que sea; creérselo sin
    acuerdo previo convierte la MFA en una casilla que rellena el otro lado."""
    proveedor = ProveedorIdentidad(tenant_id=tenant_id, nombre="Entra", tipo="oidc", acr_con_mfa=[])
    assert factores.el_idp_ya_hizo_mfa(db, proveedor, {"amr": ["mfa", "otp"]}) is False


@pytest.mark.db
def test_con_la_lista_declarada_si_se_delega(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Pedirlo dos veces —en el IdP y aquí— es la queja más repetida de
    cualquier despliegue de SSO, y lo que consigue es que pidan quitar la MFA."""
    proveedor = ProveedorIdentidad(
        tenant_id=tenant_id, nombre="Entra", tipo="oidc", acr_con_mfa=["mfa"]
    )
    assert factores.el_idp_ya_hizo_mfa(db, proveedor, {"amr": ["pwd", "mfa"]}) is True


@pytest.mark.db
def test_el_contexto_saml_vale_igual_que_el_acr(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La configuración es una sola y no una por protocolo."""
    proveedor = ProveedorIdentidad(
        tenant_id=tenant_id,
        nombre="Ping",
        tipo="saml",
        acr_con_mfa=["urn:oasis:names:tc:SAML:2.0:ac:classes:MobileTwoFactorContract"],
    )
    claims = {"authn_context": "urn:oasis:names:tc:SAML:2.0:ac:classes:MobileTwoFactorContract"}
    assert factores.el_idp_ya_hizo_mfa(db, proveedor, claims) is True


# ── Descubrimiento de dominio (CRM-00.05.01.14) ───────────────────────────


def _idp(db: Any, tenant_id: UUID, nombre: str, dominios: list[str]) -> ProveedorIdentidad:
    fila = ProveedorIdentidad(
        tenant_id=tenant_id, nombre=nombre, tipo="oidc", dominios=dominios, activo=True
    )
    db.add(fila)
    db.flush()
    return fila


@pytest.mark.db
def test_varios_dominios_en_un_solo_proveedor(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Con uno solo, cada dominio extra obliga a duplicar el proveedor entero y
    mantener dos copias hasta que divergen."""
    _idp(db, tenant_id, "Entra", ["ejemplo.com", "ejemplo.es", "marca-nueva.com"])
    encontrado = sso_gobierno.proveedor_por_correo(db, tenant_id, "ana@marca-nueva.com")
    assert encontrado is not None and encontrado.nombre == "Entra"


@pytest.mark.db
def test_el_subdominio_hereda_del_padre(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Si no, cada filial obligaría a una fila nueva, y el día que falte una esa
    gente no puede entrar."""
    _idp(db, tenant_id, "Entra", ["ejemplo.com"])
    encontrado = sso_gobierno.proveedor_por_correo(db, tenant_id, "ana@ventas.ejemplo.com")
    assert encontrado is not None and encontrado.nombre == "Entra"


@pytest.mark.db
def test_gana_el_dominio_mas_especifico(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Si alguien configura el subdominio aparte es porque quiere otra cosa para
    esa gente."""
    _idp(db, tenant_id, "General", ["ejemplo.com"])
    _idp(db, tenant_id, "Filial", ["ventas.ejemplo.com"])
    encontrado = sso_gobierno.proveedor_por_correo(db, tenant_id, "ana@ventas.ejemplo.com")
    assert encontrado is not None and encontrado.nombre == "Filial"


@pytest.mark.db
def test_un_proveedor_inactivo_no_se_propone(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    fila = _idp(db, tenant_id, "Viejo", ["ejemplo.com"])
    fila.activo = False
    db.flush()
    assert sso_gobierno.proveedor_por_correo(db, tenant_id, "ana@ejemplo.com") is None


# ── Forzar SSO (CRM-00.05.01.13) ──────────────────────────────────────────


@pytest.mark.db
def test_con_sso_forzado_no_se_entra_con_contrasena(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Con una contraseña local viva, el SSO es una comodidad y no un control:
    quien se va del directorio sigue entrando por la otra puerta."""
    usuario = _usuario(db, tenant_id)
    fila = _idp(db, tenant_id, "Entra", ["ejemplo.com"])
    fila.config = {"forzar_sso": True}
    db.flush()
    with pytest.raises(Prohibido) as e:
        sso_gobierno.exigir_sso_si_toca(db, usuario, tenant_id)
    assert e.value.error_code == "sso.obligatorio"


@pytest.mark.db
def test_la_cuenta_de_rescate_entra_y_queda_escrito(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sin excepción, un certificado caducado un sábado deja al cliente fuera de
    su propio CRM y la salida acaba siendo tocar la base a mano. Con ella, tiene
    nombre y apellidos y deja rastro: una excepción que no se ve deja de ser una
    excepción."""
    usuario = _usuario(db, tenant_id, "rescate@ejemplo.com")
    fila = _idp(db, tenant_id, "Entra", ["ejemplo.com"])
    fila.config = {"forzar_sso": True, "cuentas_de_rescate": ["rescate@ejemplo.com"]}
    db.flush()
    sso_gobierno.exigir_sso_si_toca(db, usuario, tenant_id)

    from crmcore.audit.modelos import ApunteAuditoria

    apuntes = db.query(ApunteAuditoria).filter(ApunteAuditoria.accion == "sso.rescate_usado").all()
    assert len(apuntes) == 1


@pytest.mark.db
def test_se_puede_preguntar_antes_de_poner_contrasena(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Dejar ponerla y después no admitirla al entrar es un camino que acaba en
    un ticket."""
    fila = _idp(db, tenant_id, "Entra", ["ejemplo.com"])
    fila.config = {"forzar_sso": True}
    db.flush()
    assert sso_gobierno.puede_tener_contrasena_local(db, tenant_id, "ana@ejemplo.com") is False
    assert sso_gobierno.puede_tener_contrasena_local(db, tenant_id, "otro@fuera.com") is True


# ── Certificados (CRM-00.05.01.15) ────────────────────────────────────────


@pytest.mark.db
def test_un_certificado_por_caducar_se_avisa(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un certificado de IdP que caduca no avisa: un sábado por la noche deja de
    validar toda aserción y el lunes nadie puede entrar."""
    fila = _idp(db, tenant_id, "Entra", ["ejemplo.com"])
    fila.certificados = [
        {
            "huella": "aa11",
            "caduca_at": (datetime.now(timezone.utc) + timedelta(days=5)).isoformat(),
        }
    ]
    db.flush()
    revision = sso_gobierno.revision_de_certificados(db, tenant_id)
    assert revision["por_caducar"] == ["Entra"]
    assert revision["en_verde"] is False


@pytest.mark.db
def test_un_proveedor_sin_certificado_declarado_no_es_verde(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """No está «en verde»: es uno del que no se sabe nada, y la diferencia
    importa justo el día que caduca."""
    _idp(db, tenant_id, "Entra", ["ejemplo.com"])
    revision = sso_gobierno.revision_de_certificados(db, tenant_id)
    assert revision["proveedores_sin_certificado_declarado"] == ["Entra"]
    assert revision["en_verde"] is False


@pytest.mark.db
def test_se_pueden_tener_dos_certificados_a_la_vez(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sustituir uno por otro convierte la rotación en una ventana de caída para
    todo el tenant, coordinada al minuto con un departamento que no es nuestro."""
    fila = _idp(db, tenant_id, "Entra", ["ejemplo.com"])
    futuro = datetime.now(timezone.utc) + timedelta(days=400)
    sso_gobierno.anadir_certificado(db, fila, huella="viejo", caduca_at=futuro)
    sso_gobierno.anadir_certificado(db, fila, huella="nuevo", caduca_at=futuro)
    assert len(fila.certificados) == 2


@pytest.mark.db
def test_no_se_puede_retirar_el_ultimo_vigente(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Que falle aquí, con el administrador delante, es la diferencia entre un
    mensaje y una caída."""
    fila = _idp(db, tenant_id, "Entra", ["ejemplo.com"])
    futuro = datetime.now(timezone.utc) + timedelta(days=400)
    sso_gobierno.anadir_certificado(db, fila, huella="unico", caduca_at=futuro)
    with pytest.raises(Conflicto) as e:
        sso_gobierno.retirar_certificado(db, fila, "unico")
    assert e.value.error_code == "idp.ultimo_certificado"


# ── SSO iniciado por el IdP (CRM-00.05.01.11) ─────────────────────────────


@pytest.mark.db
def test_de_fabrica_no_se_aceptan_aserciones_del_idp(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Activarlo tiene que ser la decisión de alguien que sepa que está
    aceptando aserciones que él no ha pedido."""
    fila = _idp(db, tenant_id, "Entra", ["ejemplo.com"])
    with pytest.raises(Prohibido) as e:
        sso_gobierno.admitir_asercion_idp(db, fila, id_asercion="_a1", no_despues_de=None)
    assert e.value.error_code == "sso.idp_initiated_desactivado"


@pytest.mark.db
def test_una_asercion_no_se_puede_reenviar(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Sin petición no hay `InResponseTo` que atar, así que una aserción
    interceptada vale otra vez hasta que caduque. Lo único que lo cierra es
    recordar las usadas."""
    fila = _idp(db, tenant_id, "Entra", ["ejemplo.com"])
    fila.permite_idp_initiated = True
    db.flush()
    caduca = datetime.now(timezone.utc) + timedelta(minutes=5)

    sso_gobierno.admitir_asercion_idp(db, fila, id_asercion="_a1", no_despues_de=caduca)
    with pytest.raises(NoAutenticado) as e:
        sso_gobierno.admitir_asercion_idp(db, fila, id_asercion="_a1", no_despues_de=caduca)
    assert e.value.error_code == "sso.asercion_reenviada"


@pytest.mark.db
def test_una_asercion_sin_identificador_no_se_acepta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Aceptar «porque no se puede comprobar» es no tener la comprobación."""
    fila = _idp(db, tenant_id, "Entra", ["ejemplo.com"])
    fila.permite_idp_initiated = True
    db.flush()
    with pytest.raises(NoAutenticado) as e:
        sso_gobierno.admitir_asercion_idp(db, fila, id_asercion="", no_despues_de=None)
    assert e.value.error_code == "sso.asercion_sin_id"


@pytest.mark.db
def test_una_asercion_que_cita_peticion_no_es_del_idp(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Si cita una petición, se valida por el otro camino, que es más fuerte."""
    fila = _idp(db, tenant_id, "Entra", ["ejemplo.com"])
    fila.permite_idp_initiated = True
    db.flush()
    with pytest.raises(ErrorValidacion) as e:
        sso_gobierno.admitir_asercion_idp(
            db, fila, id_asercion="_a1", no_despues_de=None, en_respuesta_a="_req1"
        )
    assert e.value.error_code == "sso.no_es_idp_initiated"


@pytest.mark.db
def test_las_aserciones_caducadas_se_purgan(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    db.add(
        AsercionConsumida(
            tenant_id=tenant_id,
            hash_asercion="x" * 64,
            proveedor_id=uuid4(),
            expira_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )
    db.flush()
    assert sso_gobierno.purgar_aserciones(db) == 1


# ── Cierre de sesión único (CRM-00.05.01.12) ──────────────────────────────


@pytest.mark.db
def test_el_aviso_del_idp_cierra_la_sesion_de_aqui(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sin la correspondencia, el aviso llega con el identificador del IdP y no
    hay a quién aplicárselo: salir del proveedor deja el CRM abierto, que es
    justo lo que el usuario cree que acaba de evitar."""
    usuario = _usuario(db, tenant_id)
    proveedor = _idp(db, tenant_id, "Entra", ["ejemplo.com"])
    sesion = _sesion(db, usuario, tenant_id)
    sso_gobierno.atar_sesion_al_idp(
        db,
        sesion=sesion,
        proveedor_id=proveedor.id,
        usuario_id=usuario.id,
        tenant_id=tenant_id,
        indice_idp="sess-1",
        sujeto_idp="ana",
    )
    salida = sso_gobierno.cerrar_por_aviso_del_idp(db, tenant_id, indice_idp="sess-1")
    db.flush()
    assert salida["sesiones_cerradas"] == 1
    db.refresh(sesion)
    assert sesion.revocada_at is not None


@pytest.mark.db
def test_por_sujeto_cierra_todas_las_suyas(db: Any, tenant_id: UUID, contexto_tenant: UUID) -> None:
    """Hay proveedores que dicen «esta persona ha salido de todo», y eso es lo
    que el usuario ha pedido al pulsar salir."""
    usuario = _usuario(db, tenant_id)
    proveedor = _idp(db, tenant_id, "Entra", ["ejemplo.com"])
    for i in range(3):
        sesion = _sesion(db, usuario, tenant_id)
        sso_gobierno.atar_sesion_al_idp(
            db,
            sesion=sesion,
            proveedor_id=proveedor.id,
            usuario_id=usuario.id,
            tenant_id=tenant_id,
            indice_idp=f"sess-{i}",
            sujeto_idp="ana",
        )
    salida = sso_gobierno.cerrar_por_aviso_del_idp(db, tenant_id, sujeto_idp="ana")
    assert salida["sesiones_cerradas"] == 3


@pytest.mark.db
def test_un_aviso_sobre_algo_ya_cerrado_no_es_un_error(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Devolver error haría que el proveedor reintentara en bucle."""
    salida = sso_gobierno.cerrar_por_aviso_del_idp(db, tenant_id, indice_idp="no-existe")
    assert salida["nada_que_cerrar"] is True
    assert salida["sesiones_cerradas"] == 0


@pytest.mark.db
def test_salir_aqui_dice_a_quien_hay_que_avisar(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Cerrar solo aquí deja la sesión del IdP viva y volver a entrar no pide
    credenciales: para el usuario, el botón de salir no ha hecho nada."""
    usuario = _usuario(db, tenant_id)
    proveedor = _idp(db, tenant_id, "Entra", ["ejemplo.com"])
    sesion = _sesion(db, usuario, tenant_id)
    sso_gobierno.atar_sesion_al_idp(
        db,
        sesion=sesion,
        proveedor_id=proveedor.id,
        usuario_id=usuario.id,
        tenant_id=tenant_id,
        indice_idp="sess-1",
    )
    salida = sso_gobierno.salida_propagada(db, sesion, tenant_id)
    assert salida["avisar_al_idp"][0]["indice_idp"] == "sess-1"
    assert salida["sin_federacion"] is False


@pytest.mark.db
def test_una_sesion_local_no_finge_propagacion(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Decirlo evita que alguien busque un fallo de propagación que no existe."""
    usuario = _usuario(db, tenant_id)
    sesion = _sesion(db, usuario, tenant_id)
    salida = sso_gobierno.salida_propagada(db, sesion, tenant_id)
    assert salida["sin_federacion"] is True


# ── Panel de adopción (CRM-00.05.01.25) ───────────────────────────────────


@pytest.mark.db
def test_el_panel_da_la_lista_de_los_que_faltan(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """«78 % de adopción» no sirve para nada: el trabajo es hablar con los que
    faltan, y para eso hace falta saber quiénes son."""
    con = _usuario(db, tenant_id, "con@ejemplo.com")
    con.mfa_activo = True
    _usuario(db, tenant_id, "sin@ejemplo.com")
    db.flush()

    panel = factores.adopcion_mfa(db, tenant_id)
    assert panel["con_factor"] == 1 and panel["sin_factor"] == 1
    assert [u["email"] for u in panel["usuarios_sin_factor"]] == ["sin@ejemplo.com"]


@pytest.mark.db
def test_sin_usuarios_no_se_dice_cien_por_cien(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Sería un verde que nadie se ha ganado."""
    panel = factores.adopcion_mfa(db, tenant_id)
    assert panel["medible"] is False
    assert panel["adopcion_pct"] is None
