"""SSO: OIDC con PKCE (CRM-00.05.01.01) y SAML (CRM-00.05.01.02).

Lo que estas pruebas defienden son los controles que, si fallan, no se notan:
un token firmado con la clave equivocada que pasa, un algoritmo simétrico que
convierte la clave pública en secreto compartido, un estado reutilizable que
deja repetir un inicio de sesión. Ninguno da error en el uso normal.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import pytest
from crmcore.errors import Conflicto, ErrorValidacion, NoAutenticado

from services.identity import oidc as oidc_cli
from services.identity import sso


@pytest.fixture
def proveedor() -> oidc_cli.Proveedor:
    return oidc_cli.Proveedor(
        id="p1",
        tenant_id=uuid4(),
        nombre="Entra",
        issuer_url="https://idp.ejemplo.com",
        client_id="cliente-crm",
        client_secret="secreto",
        redirect_uri="https://crm.ejemplo.com/cb",
        mapeo_roles={"CRM-Comerciales": "comercial"},
    )


@pytest.fixture(autouse=True)
def cache_limpia() -> Any:
    oidc_cli.invalidar_cache()
    yield
    oidc_cli.invalidar_cache()


def _descubrimiento(monkeypatch: pytest.MonkeyPatch, documento: dict[str, Any]) -> None:
    monkeypatch.setattr(oidc_cli, "_descubrir", lambda p: documento)


# ── PKCE ──────────────────────────────────────────────────────────────────


def test_la_url_de_autorizacion_lleva_pkce_con_s256(
    proveedor: oidc_cli.Proveedor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PKCE siempre, incluso habiendo secreto de cliente: OAuth 2.1 lo exige
    para todos los clientes, y sin él quien intercepte el código lo canjea."""
    _descubrimiento(
        monkeypatch, {"authorization_endpoint": "https://idp/auth", "issuer": "https://idp"}
    )

    autorizacion = oidc_cli.construir_autorizacion(proveedor)
    parametros = parse_qs(urlparse(autorizacion.url).query)

    assert parametros["code_challenge_method"] == ["S256"]
    esperado = (
        base64.urlsafe_b64encode(hashlib.sha256(autorizacion.verificador.encode()).digest())
        .decode()
        .rstrip("=")
    )
    assert parametros["code_challenge"] == [esperado]


def test_no_se_ofrece_el_metodo_plain(
    proveedor: oidc_cli.Proveedor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`plain` convierte PKCE en un adorno: el reto y el verificador serían el
    mismo valor."""
    _descubrimiento(
        monkeypatch, {"authorization_endpoint": "https://idp/auth", "issuer": "https://idp"}
    )
    url = oidc_cli.construir_autorizacion(proveedor).url
    assert "plain" not in url


def test_estado_y_nonce_son_distintos_y_aleatorios(
    proveedor: oidc_cli.Proveedor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hacen cosas distintas: el estado ata la respuesta a la petición (CSRF) y
    el nonce ata el token a ese flujo (repetición)."""
    _descubrimiento(
        monkeypatch, {"authorization_endpoint": "https://idp/auth", "issuer": "https://idp"}
    )
    a = oidc_cli.construir_autorizacion(proveedor)
    b = oidc_cli.construir_autorizacion(proveedor)

    assert a.estado != a.nonce
    assert a.estado != b.estado and a.verificador != b.verificador


# ── Selección de clave y algoritmo ────────────────────────────────────────


def test_un_kid_que_no_encaja_no_se_sustituye_por_la_primera_clave() -> None:
    """Sustituirla enmascara una rotación o una configuración cruzada entre
    tenants, y deja pasar un token firmado con otra clave."""
    assert oidc_cli._clave_que_encaja([{"kid": "a"}, {"kid": "b"}], "c") is None


def test_sin_kid_se_usa_la_unica_clave() -> None:
    """Los IdP de una sola clave no mandan `kid`, y es legítimo."""
    assert oidc_cli._clave_que_encaja([{"kid": "a"}], None) == {"kid": "a"}


def test_los_algoritmos_simetricos_no_estan_permitidos() -> None:
    """Con HS256 se puede firmar el token usando la clave pública del proveedor
    —que es pública— como secreto compartido. Es la confusión de algoritmos."""
    assert not any(a.startswith("HS") for a in oidc_cli.ALGORITMOS)
    assert "none" not in oidc_cli.ALGORITMOS


def test_un_algoritmo_fuera_de_la_lista_se_rechaza(
    proveedor: oidc_cli.Proveedor, monkeypatch: pytest.MonkeyPatch
) -> None:
    _descubrimiento(monkeypatch, {"issuer": "https://idp"})
    with pytest.raises(ErrorValidacion) as exc:
        oidc_cli._algoritmo(proveedor, {"alg": "HS256"})
    assert exc.value.error_code == "oidc.algoritmo_no_permitido"


def test_se_respeta_lo_que_anuncia_el_proveedor(
    proveedor: oidc_cli.Proveedor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si el IdP dice que solo firma con RS256, un ES256 es sospechoso."""
    _descubrimiento(
        monkeypatch, {"issuer": "https://idp", "id_token_signing_alg_values_supported": ["RS256"]}
    )
    assert oidc_cli._algoritmo(proveedor, {"alg": "RS256"}) == "RS256"
    with pytest.raises(ErrorValidacion):
        oidc_cli._algoritmo(proveedor, {"alg": "ES256"})


def test_la_cache_es_por_proveedor_no_global(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con una caché global, el segundo tenant se validaría contra las claves
    del primero."""
    oidc_cli._descubrimiento["uno"] = (9e18, {"issuer": "https://a"})
    oidc_cli._descubrimiento["dos"] = (9e18, {"issuer": "https://b"})

    oidc_cli.invalidar_cache("uno")

    assert "uno" not in oidc_cli._descubrimiento
    assert "dos" in oidc_cli._descubrimiento


# ── Estado del flujo ──────────────────────────────────────────────────────


def test_el_estado_se_guarda_hasheado(db: Any, tenant_id: UUID) -> None:
    """Va en la URL, así que acaba en el log del proxy y en el historial. En
    claro, quien lea un log podría cerrar un inicio de sesión ajeno."""
    fila = sso.guardar_estado(
        db,
        tenant_id=tenant_id,
        proveedor_id=uuid4(),
        estado="ESTADO-EN-CLARO",
        nonce="n",
        verificador="v",
    )
    assert fila.estado_hash != "ESTADO-EN-CLARO"
    assert len(fila.estado_hash) == 64


def test_el_estado_es_de_un_solo_uso(db: Any, tenant_id: UUID) -> None:
    """Sin el borrado, quien capture la respuesta la reenvía y entra."""
    sso.guardar_estado(
        db, tenant_id=tenant_id, proveedor_id=uuid4(), estado="e1", nonce="n", verificador="v"
    )

    assert sso.consumir_estado(db, "e1").nonce == "n"
    with pytest.raises(NoAutenticado) as exc:
        sso.consumir_estado(db, "e1")
    assert exc.value.error_code == "sso.estado_desconocido"


def test_un_estado_caducado_no_vale_y_se_borra(db: Any, tenant_id: UUID) -> None:
    fila = sso.guardar_estado(
        db, tenant_id=tenant_id, proveedor_id=uuid4(), estado="e2", nonce="n", verificador="v"
    )
    fila.caduca_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.flush()

    with pytest.raises(NoAutenticado) as exc:
        sso.consumir_estado(db, "e2")
    assert exc.value.error_code == "sso.estado_caducado"
    # Y no se queda ahí para un segundo intento.
    with pytest.raises(NoAutenticado) as exc2:
        sso.consumir_estado(db, "e2")
    assert exc2.value.error_code == "sso.estado_desconocido"


def test_la_purga_limpia_los_inicios_abandonados(db: Any, tenant_id: UUID) -> None:
    """Son muchos: cualquiera que abra el formulario del IdP y cierre la pestaña."""
    for i in range(3):
        fila = sso.guardar_estado(
            db,
            tenant_id=tenant_id,
            proveedor_id=uuid4(),
            estado=f"viejo{i}",
            nonce="n",
            verificador="v",
        )
        fila.caduca_at = datetime.now(timezone.utc) - timedelta(hours=1)
    sso.guardar_estado(
        db, tenant_id=tenant_id, proveedor_id=uuid4(), estado="vivo", nonce="n", verificador="v"
    )
    db.flush()

    assert sso.purgar_estados(db) == 3
    assert sso.consumir_estado(db, "vivo") is not None


# ── Mapeo de grupos a roles ───────────────────────────────────────────────


def test_el_mapeo_ignora_mayusculas() -> None:
    """El IdP devuelve los grupos como los escribió quien los creó, y el
    administrador los teclea otra vez en el mapeo."""
    assert sso.roles_desde_grupos({"CRM-Comerciales": "comercial"}, ["crm-comerciales"]) == [
        "comercial"
    ]


def test_un_grupo_sin_correspondencia_no_da_rol() -> None:
    """Lo contrario convierte crear un grupo en el IdP en conceder acceso al CRM."""
    assert sso.roles_desde_grupos({"CRM-Admins": "admin"}, ["Contabilidad"]) == []


def test_un_grupo_puede_dar_varios_roles() -> None:
    assert sso.roles_desde_grupos({"G": ["a", "b"]}, ["G"]) == ["a", "b"]


# ── Alta automática y roles ───────────────────────────────────────────────


def _proveedor_falso(**extra: Any) -> Any:
    from types import SimpleNamespace

    datos = {"nombre": "idp", "jit": True, "mapeo_roles": {"G-Ventas": "comercial"}}
    datos.update(extra)
    return SimpleNamespace(**datos)


def test_el_alta_automatica_crea_usuario_sin_contrasena(db: Any, tenant_id: UUID) -> None:
    """Sin credencial local no hay forma de saltarse el IdP corporativo; crear
    una vacía sería una puerta trasera."""
    usuario = sso.entrar_o_provisionar(
        db,
        tenant_id=tenant_id,
        proveedor=_proveedor_falso(),
        email="Ana@Cliente.com",
        nombre="Ana",
        sujeto_externo="sub-1",
        grupos=["G-Ventas"],
    )
    assert usuario.email == "ana@cliente.com"
    assert usuario.hash_contrasena is None


def test_sin_alta_automatica_un_usuario_nuevo_se_rechaza(db: Any, tenant_id: UUID) -> None:
    with pytest.raises(Conflicto) as exc:
        sso.entrar_o_provisionar(
            db,
            tenant_id=tenant_id,
            proveedor=_proveedor_falso(jit=False),
            email="nuevo@cliente.com",
            nombre="N",
            sujeto_externo="s",
            grupos=[],
        )
    assert exc.value.error_code == "sso.sin_jit"


def test_sin_correo_no_se_puede_saber_quien_es(db: Any, tenant_id: UUID) -> None:
    with pytest.raises(ErrorValidacion) as exc:
        sso.entrar_o_provisionar(
            db,
            tenant_id=tenant_id,
            proveedor=_proveedor_falso(),
            email="",
            nombre="",
            sujeto_externo="s",
            grupos=[],
        )
    assert exc.value.error_code == "sso.sin_email"


def test_salir_de_un_grupo_retira_el_rol(db: Any, tenant_id: UUID) -> None:
    """Si los roles solo se asignaran al crear el usuario, quien cambia de
    departamento conservaría los permisos antiguos para siempre."""
    from sqlalchemy import select

    from services.identity.modelos import Membresia

    sso.entrar_o_provisionar(
        db,
        tenant_id=tenant_id,
        proveedor=_proveedor_falso(),
        email="luis@cliente.com",
        nombre="Luis",
        sujeto_externo="s",
        grupos=["G-Ventas"],
    )
    db.flush()
    sso.entrar_o_provisionar(
        db,
        tenant_id=tenant_id,
        proveedor=_proveedor_falso(),
        email="luis@cliente.com",
        nombre="Luis",
        sujeto_externo="s",
        grupos=[],
    )
    db.flush()

    membresia = (
        db.execute(select(Membresia).where(Membresia.tenant_id == tenant_id)).scalars().first()
    )
    assert "comercial" not in (membresia.roles or [])


def test_los_roles_puestos_a_mano_no_se_pierden(db: Any, tenant_id: UUID) -> None:
    """El mapeo gobierna los roles que él concede, no todos: quitar el rol que
    un administrador puso a mano sería pisarle la decisión."""
    from sqlalchemy import select

    from services.identity.modelos import Membresia

    sso.entrar_o_provisionar(
        db,
        tenant_id=tenant_id,
        proveedor=_proveedor_falso(),
        email="mar@cliente.com",
        nombre="Mar",
        sujeto_externo="s",
        grupos=["G-Ventas"],
    )
    db.flush()
    membresia = (
        db.execute(select(Membresia).where(Membresia.tenant_id == tenant_id)).scalars().first()
    )
    membresia.roles = [*(membresia.roles or []), "auditor"]
    db.flush()

    sso.entrar_o_provisionar(
        db,
        tenant_id=tenant_id,
        proveedor=_proveedor_falso(),
        email="mar@cliente.com",
        nombre="Mar",
        sujeto_externo="s",
        grupos=[],
    )
    db.flush()

    assert "auditor" in (membresia.roles or [])
    assert "comercial" not in (membresia.roles or [])


# ── SAML ──────────────────────────────────────────────────────────────────


def test_saml_dice_que_le_falta_sin_reventar() -> None:
    """La librería es opcional a propósito: necesita `libxmlsec1` compilada, y
    ponerla en requirements obligaría a compilarla en TODAS las instalaciones,
    incluidas las que usan OIDC o no usan SSO."""
    from services.identity import saml as saml_sp

    if saml_sp.disponible():
        pytest.skip("python3-saml está instalado en este entorno")
    from crmcore.errors import NoDisponible

    with pytest.raises(NoDisponible) as exc:
        saml_sp.exigir_disponible()
    assert "libxmlsec1" in str(exc.value.detalle)


def test_saml_enumera_todo_lo_que_falta_de_una_vez() -> None:
    """A quien configura un IdP le sirve más ver las cuatro cosas que faltan que
    descubrirlas de una en una con un intento de inicio de sesión entre cada dos."""
    from services.identity import saml as saml_sp

    problemas = saml_sp.problemas_de_configuracion({})
    assert len(problemas) == 5


def test_saml_avisa_si_pegan_la_huella_en_vez_del_certificado() -> None:
    from services.identity import saml as saml_sp

    problemas = saml_sp.problemas_de_configuracion(
        {
            "idp_entity_id": "x",
            "idp_sso_url": "https://idp/sso",
            "idp_x509_cert": "AA:BB:CC:DD",
            "sp_entity_id": "y",
            "sp_acs_url": "https://crm/acs",
        }
    )
    assert any("huella" in p for p in problemas)


# ── SAML de verdad, con una aserción firmada ──────────────────────────────
#
# Estas pruebas solo corren donde está la librería opcional. No se saltan en
# silencio: `skip` deja constancia de que el camino NO se ha ejercitado aquí,
# que es exactamente lo que hay que saber antes de decir que SAML funciona.

saml_instalado = pytest.mark.skipif(
    not __import__("services.identity.saml", fromlist=["x"]).disponible(),
    reason="python3-saml no está instalado (extra opcional: requirements-saml.txt)",
)


def _par_de_claves() -> tuple[str, str]:
    """Clave y certificado autofirmados para hacer de IdP en la prueba."""
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
    pem_clave = clave.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pem_cert = cert.public_bytes(serialization.Encoding.PEM).decode()
    return pem_clave, pem_cert


ACS = "https://crm.ejemplo.com/api/v1/sso/saml/acs"


def _config_saml(cert: str) -> dict:
    return {
        "idp_entity_id": "https://idp.ejemplo.com/metadata",
        "idp_sso_url": "https://idp.ejemplo.com/sso",
        "idp_x509_cert": cert,
        "sp_entity_id": "https://crm.ejemplo.com/sp",
        "sp_acs_url": ACS,
    }


def _asercion(correo: str, grupos: list[str]) -> str:
    """La aserción, como documento propio.

    Se construye y se firma **aparte** porque lo que el proveedor de servicio
    exige firmado es la aserción, no la respuesta que la envuelve. Firmar solo
    la envoltura es justo el error que `wantAssertionsSigned` está ahí para
    cazar, y la primera versión de esta prueba cayó en él.
    """
    ahora = datetime.now(timezone.utc)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    atributos = "".join(
        f'<saml:Attribute Name="groups">'
        f"<saml:AttributeValue>{g}</saml:AttributeValue></saml:Attribute>"
        for g in grupos
    )
    return f"""<saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
    xmlns:xs="http://www.w3.org/2001/XMLSchema"
    ID="_asrt1" Version="2.0" IssueInstant="{ahora.strftime(fmt)}">
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
    {atributos}
  </saml:AttributeStatement>
</saml:Assertion>"""


def _envolver(asercion: str) -> str:
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"""<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
    xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
    ID="_resp1" Version="2.0" IssueInstant="{ahora}" Destination="{ACS}">
  <saml:Issuer>https://idp.ejemplo.com/metadata</saml:Issuer>
  <samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>
  {asercion}
</samlp:Response>"""


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


def _respuesta(
    correo: str, grupos: list[str], clave: str, cert: str, *, firmar: bool = True
) -> str:
    asercion = _asercion(correo, grupos)
    if firmar:
        asercion = _firmar(asercion, clave, cert)
        # La declaración XML de la aserción firmada sobra al empotrarla dentro
        # de la respuesta: un documento no puede llevar dos.
        if asercion.startswith("<?xml"):
            asercion = asercion[asercion.index("?>") + 2 :].lstrip()
    return base64.b64encode(_envolver(asercion).encode()).decode()


@saml_instalado
def test_una_asercion_firmada_se_acepta_y_trae_la_identidad() -> None:
    from services.identity import saml as saml_sp

    clave, cert = _par_de_claves()
    config = _config_saml(cert)
    respuesta = _respuesta("ana@cliente.com", ["G-Ventas"], clave, cert)

    correo, nombre, grupos, contexto = saml_sp.procesar_respuesta(
        config, {"SAMLResponse": respuesta}
    )

    assert correo == "ana@cliente.com"
    assert nombre == "Ana Prueba"
    assert grupos == ["G-Ventas"]


@saml_instalado
def test_una_asercion_sin_firmar_se_rechaza() -> None:
    """Es el agujero de libro: `wantAssertionsSigned` apagado aceptaría
    cualquier XML que alguien mande al punto de retorno."""
    from services.identity import saml as saml_sp

    clave, cert = _par_de_claves()
    sin_firma = _respuesta("ana@cliente.com", [], clave, cert, firmar=False)

    with pytest.raises(NoAutenticado) as exc:
        saml_sp.procesar_respuesta(_config_saml(cert), {"SAMLResponse": sin_firma})
    assert exc.value.error_code == "saml.respuesta_invalida"


@saml_instalado
def test_una_asercion_firmada_con_otra_clave_se_rechaza() -> None:
    """Firmar con una clave cualquiera y mandarla es el ataque obvio; lo que lo
    para es que el certificado configurado sea el del IdP de verdad."""
    from services.identity import saml as saml_sp

    clave_atacante, cert_atacante = _par_de_claves()
    _clave_buena, cert_bueno = _par_de_claves()
    respuesta = _respuesta("intruso@cliente.com", [], clave_atacante, cert_atacante)

    with pytest.raises(NoAutenticado):
        saml_sp.procesar_respuesta(_config_saml(cert_bueno), {"SAMLResponse": respuesta})


@saml_instalado
def test_una_asercion_manipulada_despues_de_firmar_se_rechaza() -> None:
    """Cambiar el correo después de firmar rompe el resumen de la referencia.
    Es justo lo que una comprobación de firma escrita a mano suele dejar pasar."""
    from services.identity import saml as saml_sp

    clave, cert = _par_de_claves()
    firmada = base64.b64decode(_respuesta("ana@cliente.com", [], clave, cert)).decode()
    manipulada = base64.b64encode(
        firmada.replace("ana@cliente.com", "jefe@cliente.com").encode()
    ).decode()

    with pytest.raises(NoAutenticado):
        saml_sp.procesar_respuesta(_config_saml(cert), {"SAMLResponse": manipulada})


@saml_instalado
def test_los_metadatos_del_sp_se_generan_y_son_validos() -> None:
    """Es el XML que hay que darle al administrador del IdP."""
    from services.identity import saml as saml_sp

    _clave, cert = _par_de_claves()
    xml = saml_sp.metadatos(_config_saml(cert))

    assert "EntityDescriptor" in xml
    assert ACS in xml


def test_el_margen_de_reloj_del_sso_sale_de_la_configuracion(monkeypatch: Any) -> None:
    """`SSO_MARGEN_RELOJ_S` existía, se documentaba y no lo leía nadie.

    Los relojes del IdP y del servidor no van sincronizados al milisegundo. Sin
    margen, un token recién emitido por un IdP que va unos segundos adelantado
    parece del futuro y se rechaza: el usuario ve «no válido», vuelve a
    intentarlo y le vuelve a pasar, sin nada en ningún registro que lo explique.

    Se comprueban las dos mitades con un token emitido **en el futuro**: sin
    margen se rechaza, con margen se acepta. Sin la segunda, un cambio que
    aceptara cualquier cosa pasaría igual.
    """
    import time

    import jwt as pyjwt
    import pytest
    from crmcore.config import get_settings
    from crmcore.errors import ErrorValidacion

    from services.identity.oidc import Proveedor, verificar_id_token

    secreto = "secreto-de-prueba-para-el-margen"
    ahora = int(time.time())
    # El caso real: el IdP va unos segundos adelantado, así que el token dice
    # que todavía no vale (`nbf`). Es lo que el margen de reloj absorbe.
    dentro_de_un_rato = ahora + 30
    token = pyjwt.encode(
        {
            "iss": "https://idp.ejemplo.com",
            "aud": "cliente-1",
            "sub": "u-1",
            "iat": ahora,
            "nbf": dentro_de_un_rato,
            "exp": ahora + 600,
        },
        secreto,
        algorithm="HS256",
    )
    # El `Proveedor` de verdad y no un objeto inventado: uno a medias pasa
    # hasta que el código lee un campo que no le pusimos, y entonces la prueba
    # falla por el motivo equivocado.
    proveedor = Proveedor(
        id="p-1",
        tenant_id=uuid4(),
        nombre="IdP de prueba",
        issuer_url="https://idp.ejemplo.com",
        client_id="cliente-1",
        client_secret=secreto,
        redirect_uri="https://crm.ejemplo.com/cb",
        # Apagado porque el token de esta prueba no trae correo: lo que se
        # comprueba aquí es el margen de reloj, y un fallo por otra cosa haría
        # pasar la prueba por el motivo equivocado.
        exigir_email_verificado=False,
    )

    # El descubrimiento y la clave se sustituyen: lo que se prueba es el margen
    # de reloj, no la red. Con HS256 la clave es el secreto compartido, en la
    # forma JWK que espera PyJWT.
    import base64
    import json as _json

    from services.identity import oidc as _oidc

    monkeypatch.setattr(_oidc, "_descubrir", lambda _p: {"issuer": "https://idp.ejemplo.com"})
    monkeypatch.setattr(
        _oidc,
        "_resolver_clave",
        lambda _p, _kid: _json.dumps(
            {
                "kty": "oct",
                "k": base64.urlsafe_b64encode(secreto.encode()).decode().rstrip("="),
            }
        ),
    )
    monkeypatch.setattr(_oidc, "_algoritmo", lambda _p, _c: "HS256")

    monkeypatch.setenv("SSO_MARGEN_RELOJ_S", "0")
    get_settings.cache_clear()
    with pytest.raises(ErrorValidacion):
        verificar_id_token(proveedor, token)

    monkeypatch.setenv("SSO_MARGEN_RELOJ_S", "120")
    get_settings.cache_clear()
    claims = verificar_id_token(proveedor, token)
    assert claims["sub"] == "u-1", (
        "con 120 s de margen un token emitido hace 30 s en el futuro tiene que "
        "aceptarse: si no, el margen no se está leyendo"
    )
    get_settings.cache_clear()
