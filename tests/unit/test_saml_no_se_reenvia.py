"""Una aserción SAML no vale dos veces (`CRM-00.05.01.11`, `CRM-00.05.01.02`).

`admitir_asercion_idp` estaba escrita, probada y **no la llamaba nadie más que
las pruebas**: el punto de retorno SAML validaba la firma y entraba, sin mirar
si el tenant aceptaba inicios que empiezan en el IdP y sin apuntar la aserción
para que no valiera otra vez.

Y había un segundo tramo del mismo agujero. El código pedía a la librería
`rejectUnsolicitedResponsesWithInResponseTo`, pero **`python3-saml` 1.16.0 no
implementa ese ajuste** —no aparece en su código— así que no hacía nada. Y
`process_response()` se llamaba sin identificador de petición, con lo cual la
librería tampoco comparaba el `InResponseTo`: esa comprobación solo la hace
cuando se le da algo contra lo que comparar. El identificador existía, lo
generaba `url_de_inicio`… y se tiraba.

Resultado medido: cualquier aserción firmada valía, viniera de una petición
nuestra o de ninguna, y valía **tantas veces como se mandara** hasta que
caducara. Una aserción se captura en el registro de un proxy, en el historial
del navegador o en el registro de un servidor; reenviarla abría sesión.

Las pruebas van contra la ruta real y no contra las piezas: las piezas ya
pasaban por separado, y eso es justo lo que no detectó el agujero.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.db

saml_instalado = pytest.mark.skipif(
    not __import__("services.identity.saml", fromlist=["x"]).disponible(),
    reason="python3-saml no está instalado (extra opcional: requirements-saml.txt)",
)

ACS = "https://crm.ejemplo.com/api/v1/sso/saml/acs"

# Un tenant con forma correcta y que no existe: lo que se mira es POR QUÉ
# falla, no que funcione.
UUID_DE_PRUEBA = "00000000-0000-0000-0000-000000000001"


def _par_de_claves() -> tuple[str, str]:
    """Clave y certificado autofirmados para hacer de IdP."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "idp-de-prueba")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(nombre)
        .issuer_name(nombre)
        .public_key(clave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
        .sign(clave, hashes.SHA256())
    )
    return (
        clave.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode(),
        cert.public_bytes(serialization.Encoding.PEM).decode(),
    )


def _config_saml(cert: str) -> dict[str, Any]:
    return {
        "idp_entity_id": "https://idp.ejemplo.com/metadata",
        "idp_sso_url": "https://idp.ejemplo.com/sso",
        "idp_x509_cert": cert,
        "sp_entity_id": "https://crm.ejemplo.com/sp",
        "sp_acs_url": ACS,
    }


def _asercion(correo: str, *, id_asercion: str) -> str:
    ahora = datetime.now(timezone.utc)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return f"""<saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
    xmlns:xs="http://www.w3.org/2001/XMLSchema"
    ID="{id_asercion}" Version="2.0" IssueInstant="{ahora.strftime(fmt)}">
  <saml:Issuer>https://idp.ejemplo.com/metadata</saml:Issuer>
  <saml:Subject>
    <saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">{correo}</saml:NameID>
    <saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">
      <saml:SubjectConfirmationData NotOnOrAfter="{(ahora + timedelta(minutes=5)).strftime(fmt)}"
          Recipient="{ACS}"/>
    </saml:SubjectConfirmation>
  </saml:Subject>
  <saml:Conditions NotBefore="{(ahora - timedelta(minutes=5)).strftime(fmt)}"
      NotOnOrAfter="{(ahora + timedelta(minutes=5)).strftime(fmt)}">
    <saml:AudienceRestriction>
      <saml:Audience>https://crm.ejemplo.com/sp</saml:Audience>
    </saml:AudienceRestriction>
  </saml:Conditions>
  <saml:AuthnStatement AuthnInstant="{ahora.strftime(fmt)}" SessionIndex="_sess1">
    <saml:AuthnContext>
      <saml:AuthnContextClassRef>urn:oasis:names:tc:SAML:2.0:ac:classes:Password</saml:AuthnContextClassRef>
    </saml:AuthnContext>
  </saml:AuthnStatement>
  <saml:AttributeStatement>
    <saml:Attribute Name="email"><saml:AttributeValue>{correo}</saml:AttributeValue></saml:Attribute>
    <saml:Attribute Name="displayName"><saml:AttributeValue>Ana Prueba</saml:AttributeValue></saml:Attribute>
  </saml:AttributeStatement>
</saml:Assertion>"""


def _firmar(xml: str, clave: str, cert: str) -> str:
    from onelogin.saml2.constants import OneLogin_Saml2_Constants
    from onelogin.saml2.utils import OneLogin_Saml2_Utils

    firmado = OneLogin_Saml2_Utils.add_sign(
        xml,
        clave,
        cert,
        sign_algorithm=OneLogin_Saml2_Constants.RSA_SHA256,
        digest_algorithm=OneLogin_Saml2_Constants.SHA256,
    )
    return firmado.decode() if isinstance(firmado, bytes) else str(firmado)


def respuesta_saml(
    clave: str,
    cert: str,
    *,
    correo: str = "ana@cliente.com",
    en_respuesta_a: str | None = None,
    id_asercion: str = "_asrt1",
) -> str:
    """Una respuesta SAML firmada, citando o no una petición nuestra.

    Se firma **la aserción**, no la envoltura: lo que el proveedor de servicio
    exige firmado es la aserción, y firmar solo la envoltura es el error que
    `wantAssertionsSigned` está ahí para cazar.
    """
    asercion = _firmar(_asercion(correo, id_asercion=id_asercion), clave, cert)
    if asercion.startswith("<?xml"):
        asercion = asercion[asercion.index("?>") + 2 :].lstrip()
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cita = f' InResponseTo="{en_respuesta_a}"' if en_respuesta_a else ""
    envoltura = f"""<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
    xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
    ID="_resp1" Version="2.0" IssueInstant="{ahora}" Destination="{ACS}"{cita}>
  <saml:Issuer>https://idp.ejemplo.com/metadata</saml:Issuer>
  <samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>
  {asercion}
</samlp:Response>"""
    return base64.b64encode(envoltura.encode()).decode()


# ── La llave para buscar la petición ──────────────────────────────────────


@saml_instalado
def test_se_lee_a_que_peticion_dice_responder(db: Any) -> None:
    """Se lee con el analizador de XML, no con una expresión regular.

    Un XML trae el atributo de muchas formas y una expresión regular acierta con
    las de prueba. Esto es la llave con la que se busca la petición: si se lee
    mal, no se encuentra y se rechaza un inicio bueno.
    """
    from services.identity import saml as saml_sp

    clave, cert = _par_de_claves()
    con_cita = respuesta_saml(clave, cert, en_respuesta_a="_pet123")
    sin_cita = respuesta_saml(clave, cert)

    assert saml_sp.en_respuesta_a({"SAMLResponse": con_cita}) == "_pet123"
    assert saml_sp.en_respuesta_a({"SAMLResponse": sin_cita}) == ""


@saml_instalado
def test_una_respuesta_ilegible_no_tumba_la_lectura(db: Any) -> None:
    """Se trata como si no citara nada y la validación de la librería la echa:
    reventar aquí convertiría un XML basura en un error 500."""
    from services.identity import saml as saml_sp

    assert saml_sp.en_respuesta_a({}) == ""
    assert saml_sp.en_respuesta_a({"SAMLResponse": "no-es-base64-ni-xml"}) == ""
    assert saml_sp.en_respuesta_a({"SAMLResponse": base64.b64encode(b"<a>").decode()}) == ""


# ── El identificador de la petición se guarda, no se tira ─────────────────


@saml_instalado
def test_el_inicio_devuelve_el_identificador_con_el_que_se_espera(db: Any) -> None:
    """Sin devolverlo no hay nada contra lo que comparar la vuelta, y entonces
    vale cualquier aserción firmada."""
    from services.identity import saml as saml_sp

    _, cert = _par_de_claves()
    inicio = saml_sp.url_de_inicio(_config_saml(cert))

    assert inicio.url.startswith("https://idp.ejemplo.com/sso")
    assert inicio.id_peticion, "se ha tirado el identificador de la petición"


@saml_instalado
def test_la_libreria_compara_el_inresponseto_cuando_se_le_da_con_que(db: Any) -> None:
    """La comprobación NO es automática.

    `python3-saml` solo compara el `InResponseTo` si se le pasa `request_id`;
    sin él no mira. Y el ajuste que el código pedía para cubrirlo
    —`rejectUnsolicitedResponsesWithInResponseTo`— no existe en la versión 1.16.0
    instalada. Esta prueba fija las dos cosas: que comparar funciona cuando se
    le da el identificador, y que rechaza el que no cuadra.
    """
    from crmcore.errors import NoAutenticado

    from services.identity import saml as saml_sp

    clave, cert = _par_de_claves()
    respuesta = respuesta_saml(clave, cert, en_respuesta_a="_pet_bueno")

    correo, _, _, _ = saml_sp.procesar_respuesta(
        _config_saml(cert), {"SAMLResponse": respuesta}, id_peticion="_pet_bueno"
    )
    assert correo == "ana@cliente.com"

    with pytest.raises(NoAutenticado):
        saml_sp.procesar_respuesta(
            _config_saml(cert), {"SAMLResponse": respuesta}, id_peticion="_pet_de_otro"
        )


@saml_instalado
def test_la_asercion_trae_lo_que_hace_falta_para_apuntarla(db: Any) -> None:
    """Sin identificador y sin fecha de caducidad no se puede registrar como
    usada, y sin registrarla el reenvío no se detecta."""
    from services.identity import saml as saml_sp

    clave, cert = _par_de_claves()
    respuesta = respuesta_saml(clave, cert, id_asercion="_asrt_unica")

    _, _, _, contexto = saml_sp.procesar_respuesta(_config_saml(cert), {"SAMLResponse": respuesta})

    assert contexto["id_asercion"] == "_asrt_unica"
    assert contexto["no_despues_de"], "sin caducidad la aserción valdría para siempre"
    # La librería la da como marca de tiempo unix, no como texto ISO: leerla
    # como ISO fallaría siempre y en silencio.
    assert float(contexto["no_despues_de"]) > 0


def test_la_caducidad_se_lee_como_marca_de_tiempo_unix() -> None:
    """Es lo que devuelve `parse_SAML_to_time`, documentado `rtype: int`.

    Si se leyera como ISO, `_momento` devolvería `None` siempre, la aserción se
    quedaría con la ventana por defecto y **nada fallaría**: parecería que la
    caducidad se respeta.
    """
    from services.identity.api_sso import _momento

    esperado = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
    assert _momento(str(esperado.timestamp())) == esperado
    assert _momento("") is None
    assert _momento("2026-09-29T12:00:00Z") is None  # no es lo que da la librería


# ── El punto de retorno, que es donde faltaba todo ────────────────────────


def _proveedor(db: Any, tenant_id: UUID, cert: str, *, idp_initiated: bool = False) -> Any:
    from services.identity.modelos import ProveedorIdentidad

    fila = ProveedorIdentidad(
        tenant_id=tenant_id,
        nombre="Entra",
        tipo="saml",
        config=_config_saml(cert),
        dominios=["cliente.com"],
        activo=True,
        permite_idp_initiated=idp_initiated,
    )
    db.add(fila)
    db.flush()
    return fila


@saml_instalado
def test_una_asercion_del_idp_no_entra_si_el_tenant_no_lo_ha_activado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """El punto de retorno no miraba el interruptor: estaba en el modelo, se
    podía apagar desde la API, y no cambiaba nada."""
    from crmcore.errors import Prohibido

    from services.identity import saml as saml_sp
    from services.identity import sso_gobierno

    clave, cert = _par_de_claves()
    fila = _proveedor(db, tenant_id, cert, idp_initiated=False)
    respuesta = respuesta_saml(clave, cert)

    _, _, _, contexto = saml_sp.procesar_respuesta(_config_saml(cert), {"SAMLResponse": respuesta})

    with pytest.raises(Prohibido) as fallo:
        sso_gobierno.admitir_asercion_idp(
            db,
            fila,
            id_asercion=contexto["id_asercion"],
            no_despues_de=None,
            en_respuesta_a=contexto.get("en_respuesta_a") or None,
        )
    assert fallo.value.error_code == "sso.idp_initiated_desactivado"


@saml_instalado
def test_la_misma_asercion_del_idp_no_vale_dos_veces(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """La avería, con el interruptor encendido: entra una vez y solo una.

    Se ejercita con la MISMA respuesta firmada, byte a byte, que es lo que hace
    quien la captura de un registro o del historial.
    """
    from crmcore.errors import NoAutenticado

    from services.identity import saml as saml_sp
    from services.identity import sso_gobierno
    from services.identity.api_sso import _momento

    clave, cert = _par_de_claves()
    fila = _proveedor(db, tenant_id, cert, idp_initiated=True)
    respuesta = respuesta_saml(clave, cert)

    def entrar() -> None:
        _, _, _, contexto = saml_sp.procesar_respuesta(
            _config_saml(cert), {"SAMLResponse": respuesta}
        )
        sso_gobierno.admitir_asercion_idp(
            db,
            fila,
            id_asercion=contexto["id_asercion"],
            no_despues_de=_momento(contexto["no_despues_de"]),
            en_respuesta_a=contexto.get("en_respuesta_a") or None,
        )

    entrar()
    with pytest.raises(NoAutenticado) as fallo:
        entrar()
    assert fallo.value.error_code == "sso.asercion_reenviada"


@saml_instalado
def test_el_punto_de_retorno_pasa_por_las_dos_defensas(db: Any) -> None:
    """Que la defensa exista no basta: lo que faltaba era que alguien la llamara.

    Se mira el código de la ruta porque es exactamente lo que no tenía: la
    función estaba escrita, probada y sin ningún llamante de producción.
    """
    import inspect

    from services.identity import api_sso

    fuente = inspect.getsource(api_sso.acs_saml) + inspect.getsource(api_sso._acs_saml)
    assert (
        "admitir_asercion_idp" in fuente
    ), "el punto de retorno no registra la aserción: una capturada vale otra vez"
    assert "consumir_estado" in fuente, (
        "el punto de retorno no gasta la petición: la respuesta no se ata a un "
        "inicio nuestro y se puede reenviar"
    )
    assert "id_peticion=" in fuente, (
        "no se le da a la librería con qué comparar el InResponseTo, y entonces " "no lo compara"
    )


def test_el_inicio_guarda_la_peticion_que_abre(db: Any) -> None:
    """Sin guardarla, la vuelta no tiene contra qué compararse. Se tiraba."""
    import inspect

    from services.identity import api_sso

    fuente = inspect.getsource(api_sso.iniciar) + inspect.getsource(api_sso._iniciar)
    assert fuente.count("guardar_estado") >= 2, (
        "solo se guarda el estado de OIDC: el inicio SAML sigue tirando su "
        "identificador de petición"
    )


# ── Y la misma avería, contra la ruta de verdad ───────────────────────────
#
# Las comprobaciones de arriba ejercitan las piezas, y las piezas YA PASABAN
# mientras el agujero estaba abierto: ese es justo el motivo por el que no se
# detectó. Esto POSTea al punto de retorno real, dos veces, con la misma
# respuesta byte a byte.


@pytest.fixture
def identity_arrancado() -> Any:
    """El servicio tal como se despliega, con su arranque.

    Sin el `with`, `TestClient` no ejecuta el ciclo de vida y se probaría una
    aplicación a medio arrancar, que es donde el servicio instala sus garantías.
    """
    import importlib
    import os

    from crmcore.config import get_settings
    from starlette.testclient import TestClient

    previo = os.environ.get("OUTBOX_ENABLED")
    # El relevo del outbox comparte conexión con la sesión de la prueba y sus
    # `RELEASE SAVEPOINT` se cruzan con los de esta transacción. Aquí no se
    # prueba el outbox: se prueba si una aserción vale dos veces.
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        app = importlib.import_module("services.identity.main").app
        with TestClient(app) as cliente:
            yield cliente
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


@pytest.fixture
def tenant_confirmado() -> Any:
    """Un tenant cuyas filas se escriben **de verdad** y se borran al acabar.

    Estas dos pruebas no pueden usar el fixture `db`: envuelve todo en una
    transacción que se deshace, y la aplicación abre su propia conexión, así que
    no vería el proveedor. Hay que confirmar.

    Y por eso hay que limpiar. En la suite el rol de conexión es SUPERUSER, así
    que **no se aplica el aislamiento por tenant**: una fila confirmada aquí la
    ve cualquier prueba posterior que consulte sin filtrar, y ya tumbó una
    —`test_purgar_deja_constancia_del_corte`, que cuenta apuntes de auditoría—.
    Se borra por tenant y en todas las tablas que lo tengan, en vez de ir
    nombrando tablas: el flujo de entrada toca varias y mañana tocará otra.
    """
    from crmcore.db.base import Base
    from crmcore.db.session import sesion

    tenant = uuid4()
    yield tenant

    # UNA TRANSACCIÓN POR TABLA. Con todas dentro de la misma, el primer
    # `UndefinedTable` —hay modelos compartidos que no existen en el esquema de
    # este servicio— aborta la transacción entera y **las demás ni se intentan**:
    # el borrado parece hecho y no lo está. Se cuenta lo borrado para que un cero
    # se vea, en vez de pasar por limpio.
    borradas = 0
    for tabla in reversed(Base.metadata.sorted_tables):
        if "tenant_id" not in tabla.c:
            continue
        try:
            with sesion(None, sistema=True) as db:
                borradas += db.execute(tabla.delete().where(tabla.c.tenant_id == tenant)).rowcount
        except Exception:  # noqa: BLE001 — una tabla que no está en este esquema
            continue
    assert borradas, (
        "la limpieza no ha borrado ni una fila: o la prueba no escribió nada "
        "—y entonces no probaba lo que dice— o el borrado no está llegando"
    )


@saml_instalado
def test_por_la_ruta_real_la_misma_asercion_no_abre_dos_sesiones(
    identity_arrancado: Any, tenant_confirmado: UUID
) -> None:
    """La avería tal cual: capturar la respuesta y reenviarla.

    Lo que se comprueba no es el código de error concreto del segundo intento
    —puede cambiar— sino que **no vuelve a entrar**: dos 200 seguidos con la
    misma aserción es el agujero.

    NO se usa el fixture `db`: ese envuelve todo en una transacción que se
    deshace al acabar, y la aplicación abre su propia conexión, así que no
    vería el proveedor. Se escribe con una sesión propia que confirma, y se
    limpia al final.
    """
    from crmcore.db.session import sesion
    from crmcore.tenancy.context import con_contexto

    clave, cert = _par_de_claves()
    respuesta = respuesta_saml(clave, cert)

    with (
        con_contexto(tenant_id=tenant_confirmado, origen="prueba"),
        sesion(tenant_confirmado) as db,
    ):
        fila = _proveedor(db, tenant_confirmado, cert, idp_initiated=True)
        nombre_proveedor = fila.nombre

    def enviar() -> Any:
        return identity_arrancado.post(
            "/api/v1/sso/saml/acs",
            params={"tenant_id": str(tenant_confirmado), "proveedor": nombre_proveedor},
            data={"SAMLResponse": respuesta},
        )

    primera = enviar()
    segunda = enviar()

    assert primera.status_code == 200, (
        f"la primera entrada no funciona, así que la prueba no dice nada "
        f"del reenvío: {primera.status_code} {primera.text[:300]}"
    )
    assert segunda.status_code != 200, (
        "la MISMA aserción ha abierto una segunda sesión: quien la capture en "
        "un registro o en el historial entra"
    )


@saml_instalado
def test_una_respuesta_que_cita_una_peticion_que_no_hicimos_no_entra(
    identity_arrancado: Any, tenant_confirmado: UUID
) -> None:
    """La otra mitad del mismo agujero, por la ruta real.

    Una aserción firmada que dice responder a una petición nuestra tiene que
    encontrar esa petición emitida y sin gastar. Si el identificador se tira al
    iniciar —como se tiraba— no hay nada contra lo que comparar y entra
    cualquiera que consiga una aserción firmada por el IdP del cliente, por
    ejemplo la suya propia de otro servicio del mismo IdP.
    """
    from crmcore.db.session import sesion
    from crmcore.tenancy.context import con_contexto

    clave, cert = _par_de_claves()
    with (
        con_contexto(tenant_id=tenant_confirmado, origen="prueba"),
        sesion(tenant_confirmado) as db,
    ):
        fila = _proveedor(db, tenant_confirmado, cert, idp_initiated=True)
        nombre_proveedor = fila.nombre

    # `idp_initiated` está ENCENDIDO a propósito: así, si esto pasara, no sería
    # porque el interruptor lo frenó por otro motivo.
    respuesta = respuesta_saml(clave, cert, en_respuesta_a="_peticion_que_nunca_hicimos")

    salida = identity_arrancado.post(
        "/api/v1/sso/saml/acs",
        params={"tenant_id": str(tenant_confirmado), "proveedor": nombre_proveedor},
        data={"SAMLResponse": respuesta},
    )

    assert salida.status_code != 200, (
        "ha entrado citando una petición que nunca emitimos: el identificador "
        "del inicio no se está guardando ni comprobando"
    )


# ── Las tres puertas del SSO, abiertas ────────────────────────────────────
#
# El barrido anónimo general NO cubre esto y está dicho en su cabecera: desde
# que `get_uow` convierte «anónimo sin tenant» en 401, una ruta rota así contesta
# 401 y desde fuera parece correcta. Aquí se mira el **código de error**, que es
# lo único que distingue «no has entrado» de «esta puerta pide la llave que
# reparte».


@pytest.mark.parametrize(
    ("camino", "cuerpo"),
    [
        ("/api/v1/sso/iniciar", {"json": {"tenant_id": UUID_DE_PRUEBA}}),
        ("/api/v1/sso/oidc/callback", {"json": {"code": "x", "state": "y"}}),
        ("/api/v1/sso/saml/acs", {"data": {"SAMLResponse": "x"}}),
    ],
)
def test_las_puertas_del_sso_no_exigen_haber_entrado(
    identity_arrancado: Any, camino: str, cuerpo: dict[str, Any]
) -> None:
    """A las tres se llega sin credencial: es donde se consigue la primera.

    Las tres contestaban 500 «se ha abierto una sesión sin tenant» porque pedían
    la sesión a `UowDep`, que la ata al tenant del principal. Lo que se comprueba
    no es que funcionen —con datos inventados tienen que fallar— sino que fallan
    por el motivo correcto: «no encuentro ese proveedor», no «tienes que haber
    entrado».
    """
    salida = identity_arrancado.post(camino, params={"tenant_id": UUID_DE_PRUEBA}, **cuerpo)

    assert (
        salida.status_code < 500
    ), f"{camino} revienta ante quien llega sin credencial: {salida.text[:200]}"
    codigo = ""
    try:
        codigo = str(salida.json().get("error_code") or "")
    except ValueError:
        pass
    assert codigo != "auth.requerida", (
        f"{camino} pide haber entrado para dejar entrar. El proveedor de "
        "identidad llega anónimo, que es como llega siempre: esta ruta tiene que "
        "abrir su propia sesión con el tenant que pueda probar."
    )
