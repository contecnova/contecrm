"""Segundo factor verificado por el proveedor del tenant (CRM-00.05.01.22).

Contra un doble HTTP de verdad —un servidor en 127.0.0.1 que contesta como un
proveedor de verificación—, no contra un `MagicMock`: lo que se mide es que la
petición sale con la forma que declara el perfil (formulario o JSON, la
autenticación, el teléfono de la persona) y que la respuesta se lee donde dice.

Lo que decide si sirve:

- las cuatro plantillas (Twilio Verify, Okta Verify, Duo, RSA) son perfiles
  válidos tal cual: si una no pasara la validación, elegirla en el desplegable
  daría un error en vez de un formulario;
- el secreto entra y no sale, ni en el perfil ni en la petición que enseña
  «Probar»;
- el login deja entrar con el código que el proveedor da por bueno y no con
  otro, también a quien no tiene TOTP propio; y si el proveedor no contesta,
  no se entra;
- una marca sin valor corta antes de llamar.
"""

from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs
from uuid import UUID, uuid4

import pytest
from crmcore.errors import Conflicto, ErrorValidacion, NoAutenticado, Prohibido

from services.identity import mfa_proveedor as mp
from services.identity import servicio as svc

CODIGO_BUENO = "246810"
SECRETO = "token-de-la-cuenta-9f8e"


class _Doble(BaseHTTPRequestHandler):
    """Un proveedor de verificación: formulario, básica y `status`."""

    recibidas: list[dict[str, Any]] = []

    def do_POST(self) -> None:  # noqa: N802 — nombre de la biblioteca
        largo = int(self.headers.get("content-length") or 0)
        crudo = self.rfile.read(largo).decode()
        auth = self.headers.get("authorization", "")
        usuario_clave = (
            base64.b64decode(auth.split(" ", 1)[1]).decode() if auth.startswith("Basic ") else ""
        )
        if "json" in (self.headers.get("content-type") or ""):
            cuerpo = json.loads(crudo or "{}")
        else:
            cuerpo = {k: v[0] for k, v in parse_qs(crudo).items()}
        _Doble.recibidas.append(
            {
                "ruta": self.path,
                "cuerpo": cuerpo,
                "auth": usuario_clave,
                "cabeceras": dict(self.headers),
            }
        )
        if usuario_clave != f"AC123:{SECRETO}":
            self._contestar(401, {"message": "Authenticate"})
            return
        ok = cuerpo.get("Code") == CODIGO_BUENO and cuerpo.get("To") == "+34600111222"
        self._contestar(200, {"status": "approved" if ok else "pending", "sid": "VE1"})

    def _contestar(self, estado: int, cuerpo: dict[str, Any]) -> None:
        datos = json.dumps(cuerpo).encode()
        self.send_response(estado)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def log_message(self, *a: Any) -> None:
        pass


@pytest.fixture
def doble(monkeypatch: Any) -> Any:
    """El servidor y el guard de SSRF abierto SOLO a 127.0.0.1, como el ajuste."""
    from crmcore.red import guard_url

    monkeypatch.setattr(guard_url, "_permitidos", lambda: {"127.0.0.1"})
    _Doble.recibidas = []
    servidor = HTTPServer(("127.0.0.1", 0), _Doble)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    yield f"http://127.0.0.1:{servidor.server_address[1]}"
    servidor.shutdown()
    servidor.server_close()


def _perfil_twilio(base: str, **cambios: Any) -> dict[str, Any]:
    """La plantilla de Twilio Verify tal cual, apuntada al doble."""
    plantilla = dict(mp.plantillas()["twilio_verify"])
    datos = {
        **plantilla,
        "nombre": "Verificación de prueba",
        "plantilla": "twilio_verify",
        "url": plantilla["url"].replace("https://verify.twilio.com", base),
        "variables": {"service_sid": "VA1", "account_sid": "AC123"},
        "secreto": SECRETO,
        "activo": True,
    }
    datos.update(cambios)
    return datos


def _persona(db: Any, tenant_id: UUID, *, mfa: bool = False) -> Any:
    from services.identity.modelos import Membresia, Usuario

    usuario = Usuario(
        email=f"mfa-prov-{uuid4().hex[:8]}@ejemplo.com",
        nombre="Con Proveedor",
        hash_contrasena=svc.hashear_contrasena("una-contrasena-larga-2026"),
        activo=True,
        mfa_activo=mfa,
    )
    db.add(usuario)
    db.flush()
    db.add(Membresia(usuario_id=usuario.id, tenant_id=tenant_id, roles=["comercial"], activa=True))
    db.flush()
    return usuario


# ── Las plantillas y la forma del perfil ──────────────────────────────────


@pytest.mark.parametrize("clave", ["twilio_verify", "okta_verify", "duo", "rsa_securid"])
def test_cada_plantilla_es_un_perfil_valido_tal_cual(clave: str) -> None:
    plantilla = mp.plantillas()[clave]
    limpio = mp.validar(plantilla)
    assert "codigo" in str(limpio["cuerpo"]) or "codigo" in limpio["url"]
    assert limpio["respuesta"]["campo"] and limpio["respuesta"]["validos"]


def test_una_marca_que_nadie_rellena_no_se_guarda() -> None:
    datos = {
        **mp.plantillas()["twilio_verify"],
        "cuerpo": {"To": "{{persona.movil}}", "Code": "{{codigo}}"},
    }
    with pytest.raises(ErrorValidacion) as exc:
        mp.validar(datos)
    assert exc.value.error_code == "mfa_proveedor.marca_desconocida"


def test_el_secreto_solo_va_en_la_autenticacion() -> None:
    datos = {
        **mp.plantillas()["twilio_verify"],
        "cuerpo": {"Code": "{{codigo}}", "k": "{{secreto}}"},
    }
    with pytest.raises(ErrorValidacion) as exc:
        mp.validar(datos)
    assert exc.value.error_code == "mfa_proveedor.secreto_fuera_de_sitio"


def test_sin_codigo_el_proveedor_no_tiene_que_comprobar() -> None:
    datos = {**mp.plantillas()["twilio_verify"], "cuerpo": {"To": "{{persona.telefono}}"}}
    with pytest.raises(ErrorValidacion) as exc:
        mp.validar(datos)
    assert exc.value.error_code == "mfa_proveedor.sin_codigo"


# ── La llamada, contra el doble ───────────────────────────────────────────


@pytest.mark.db
def test_el_proveedor_decide_y_la_peticion_lleva_la_forma_del_perfil(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, doble: str
) -> None:
    perfil = mp.guardar(db, tenant_id, _perfil_twilio(doble))
    assert perfil["tiene_secreto"] is True
    assert SECRETO not in json.dumps(perfil)
    persona = _persona(db, tenant_id)
    mp.vincular(db, tenant_id, UUID(perfil["id"]), persona.id, {"telefono": "+34600111222"})

    bien = mp.probar(db, tenant_id, UUID(perfil["id"]), usuario_id=persona.id, codigo=CODIGO_BUENO)
    assert bien["valido"] is True, bien
    assert bien["estado_http"] == 200
    # Lo que recibió el proveedor: formulario, básica con el secreto descifrado
    # y el teléfono de la persona.
    ultima = _Doble.recibidas[-1]
    assert ultima["ruta"] == "/v2/Services/VA1/VerificationCheck"
    assert ultima["cuerpo"] == {"To": "+34600111222", "Code": CODIGO_BUENO}
    assert ultima["auth"] == f"AC123:{SECRETO}"
    # Y lo que enseña «Probar»: ni el secreto ni el código.
    assert SECRETO not in json.dumps(bien["peticion"])
    assert CODIGO_BUENO not in json.dumps(bien["peticion"])

    mal = mp.probar(db, tenant_id, UUID(perfil["id"]), usuario_id=persona.id, codigo="111111")
    assert mal["valido"] is False
    assert "pending" in mal["motivo"]


@pytest.mark.db
def test_sin_el_dato_de_la_persona_no_se_llama(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, doble: str
) -> None:
    perfil = mp.guardar(db, tenant_id, _perfil_twilio(doble))
    persona = _persona(db, tenant_id)
    r = mp.probar(db, tenant_id, UUID(perfil["id"]), usuario_id=persona.id, codigo=CODIGO_BUENO)
    assert r["valido"] is False
    assert "persona.telefono" in r["motivo"]
    assert _Doble.recibidas == []


@pytest.mark.db
def test_un_secreto_vacio_conserva_el_guardado_y_dos_activos_no(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, doble: str
) -> None:
    perfil = mp.guardar(db, tenant_id, _perfil_twilio(doble))
    persona = _persona(db, tenant_id)
    mp.vincular(db, tenant_id, UUID(perfil["id"]), persona.id, {"telefono": "+34600111222"})
    mp.guardar(db, tenant_id, _perfil_twilio(doble, secreto=""), perfil_id=UUID(perfil["id"]))
    r = mp.probar(db, tenant_id, UUID(perfil["id"]), usuario_id=persona.id, codigo=CODIGO_BUENO)
    assert r["valido"] is True, r

    with pytest.raises(Conflicto):
        mp.guardar(db, tenant_id, _perfil_twilio(doble, nombre="Otro"))


# ── El login ──────────────────────────────────────────────────────────────


@pytest.mark.db
def test_el_login_entra_con_el_codigo_del_proveedor_y_sin_totp_propio(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, doble: str, monkeypatch: Any
) -> None:
    monkeypatch.setattr(svc, "mfa_exigida", lambda *a, **k: True)
    persona = _persona(db, tenant_id, mfa=False)

    # Sin proveedor: lo de siempre, no tiene factor y no entra.
    with pytest.raises(Prohibido) as exc:
        svc.autenticar(
            db, email=persona.email, contrasena="una-contrasena-larga-2026", tenant_id=tenant_id
        )
    assert exc.value.error_code == "auth.mfa_no_configurada"

    perfil = mp.guardar(db, tenant_id, _perfil_twilio(doble))
    mp.vincular(db, tenant_id, UUID(perfil["id"]), persona.id, {"telefono": "+34600111222"})

    with pytest.raises(NoAutenticado) as exc:
        svc.autenticar(
            db, email=persona.email, contrasena="una-contrasena-larga-2026", tenant_id=tenant_id
        )
    assert exc.value.error_code == "auth.mfa_requerida"

    with pytest.raises(NoAutenticado) as exc:
        svc.autenticar(
            db,
            email=persona.email,
            contrasena="una-contrasena-larga-2026",
            tenant_id=tenant_id,
            codigo_mfa="999999",
        )
    assert exc.value.error_code == "auth.mfa_invalida"

    entra = svc.autenticar(
        db,
        email=persona.email,
        contrasena="una-contrasena-larga-2026",
        tenant_id=tenant_id,
        codigo_mfa=CODIGO_BUENO,
    )
    assert entra.id == persona.id


@pytest.mark.db
def test_en_el_login_no_hay_tenant_en_el_contexto_y_aun_asi_se_audita(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, doble: str
) -> None:
    """El login corre SIN tenant en el contexto: todavía no se sabe quién entra.

    Medido el 09-11-2026 en la pila: con el código bueno, la auditoría del
    «verificado» contestaba 422 `auditoria.sin_tenant` y deshacía la entrada.
    La prueba de arriba no lo veía porque corre con el tenant puesto.
    """
    from crmcore.audit.chain import ApunteAuditoria
    from crmcore.tenancy.context import con_contexto
    from sqlalchemy import select

    persona = _persona(db, tenant_id, mfa=False)
    perfil = mp.guardar(db, tenant_id, _perfil_twilio(doble))
    mp.vincular(db, tenant_id, UUID(perfil["id"]), persona.id, {"telefono": "+34600111222"})

    with con_contexto(tenant_id=None):
        assert mp.verificar_en_login(db, tenant_id, persona, CODIGO_BUENO) is True
    db.flush()
    acciones = set(
        db.execute(
            select(ApunteAuditoria.accion).where(ApunteAuditoria.tenant_id == tenant_id)
        ).scalars()
    )
    assert "mfa_proveedor.verificado" in acciones


@pytest.mark.db
def test_si_el_proveedor_no_contesta_no_se_entra(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, doble: str, monkeypatch: Any
) -> None:
    monkeypatch.setattr(svc, "mfa_exigida", lambda *a, **k: True)
    persona = _persona(db, tenant_id)
    # Un puerto donde no escucha nadie.
    perfil = mp.guardar(db, tenant_id, _perfil_twilio("http://127.0.0.1:9"))
    mp.vincular(db, tenant_id, UUID(perfil["id"]), persona.id, {"telefono": "+34600111222"})
    with pytest.raises(NoAutenticado) as exc:
        svc.autenticar(
            db,
            email=persona.email,
            contrasena="una-contrasena-larga-2026",
            tenant_id=tenant_id,
            codigo_mfa=CODIGO_BUENO,
        )
    assert exc.value.error_code == "auth.mfa_invalida"


# ── Por HTTP, como lo usa la pantalla ─────────────────────────────────────

from tests.unit.test_reverificacion_y_mfa_adaptativa import (  # noqa: E402
    _cabeceras,
    cliente_identidad,  # noqa: F401 — fixture
)


@pytest.mark.db
def test_la_pantalla_lo_da_de_alta_lo_prueba_y_no_ve_el_secreto(
    cliente_identidad: Any,  # noqa: F811
    db: Any,
    tenant_id: UUID,
    doble: str,
) -> None:
    from crmcore.http.deps import H_PERMISOS

    persona = _persona(db, tenant_id)
    db.commit()
    cab = _cabeceras(tenant_id, **{H_PERMISOS: "tenant:write,user:read"})

    plantillas = cliente_identidad.get("/api/v1/mfa-proveedor/plantillas", headers=cab)
    assert plantillas.status_code == 200, plantillas.text
    assert {"twilio_verify", "okta_verify", "duo", "rsa_securid"} <= set(plantillas.json())

    alta = cliente_identidad.post(
        "/api/v1/mfa-proveedor/perfiles", json=_perfil_twilio(doble), headers=cab
    )
    assert alta.status_code == 201, alta.text
    pid = alta.json()["id"]
    lista = cliente_identidad.get("/api/v1/mfa-proveedor/perfiles", headers=cab)
    assert SECRETO not in lista.text
    assert lista.json()["items"][0]["tiene_secreto"] is True

    v = cliente_identidad.put(
        f"/api/v1/mfa-proveedor/perfiles/{pid}/personas/{persona.id}",
        json={"datos": {"telefono": "+34600111222", "inventado": "x"}},
        headers=cab,
    )
    assert v.status_code == 200, v.text
    # Sólo lo que pide el perfil: lo demás no se guarda.
    assert v.json()["datos"] == {"telefono": "+34600111222"}

    prueba = cliente_identidad.post(
        f"/api/v1/mfa-proveedor/perfiles/{pid}/probar",
        json={"usuario_id": str(persona.id), "codigo": CODIGO_BUENO},
        headers=cab,
    )
    assert prueba.status_code == 200, prueba.text
    assert prueba.json()["valido"] is True
    assert SECRETO not in prueba.text

    # Sin permiso de escritura no se da de alta.
    solo_leer = _cabeceras(tenant_id, **{H_PERMISOS: "user:read"})
    assert (
        cliente_identidad.post(
            "/api/v1/mfa-proveedor/perfiles",
            json=_perfil_twilio(doble, nombre="X"),
            headers=solo_leer,
        ).status_code
        == 403
    )

    borrado = cliente_identidad.delete(f"/api/v1/mfa-proveedor/perfiles/{pid}", headers=cab)
    assert borrado.status_code == 204
