"""La telefonía de verdad (CRM-04.02.01.05) y el marcador que la usa
(CRM-03.03.01.05).

Hasta el 09-11-2026 `/telefonia/*` y `/marcador/*` eran funciones puras:
identificaban contra una lista tecleada, «registraban» devolviendo un
diccionario y no sonaba ningún teléfono. Estas pruebas miran lo que sale y lo
que queda: la petición que llega a la centralita (un servidor HTTP de verdad en
un puerto), la llamada guardada, el llamante identificado preguntando a
`party`, la actividad registrada UNA vez al colgar y lo que el marcador hace
con el resultado.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.errors import ErrorValidacion, Prohibido
from starlette.testclient import TestClient

from services.integration import telefonia as tel
from services.service import marcador

WEBHOOK = {
    "mapeo": {
        "id_externo": "call_id",
        "evento": "event",
        "numero": ["from", "caller"],
        "duracion_s": "duration",
        "grabacion": "recording_url",
        "ivr": "ivr_data",
        "agente": "agent",
    },
    "transformar": {
        "evento": [
            {
                "f": "mapa",
                "arg": {
                    "RINGING": "entrante",
                    "ANSWERED": "contestada",
                    "HANGUP": "colgada",
                    "MISSED": "perdida",
                },
            }
        ]
    },
}


# ── Traducir el aviso: el conector de siempre, sin código por proveedor ──


def test_el_aviso_de_la_centralita_se_traduce_con_el_mapeo_del_perfil() -> None:
    aviso = tel.traducir_aviso(
        WEBHOOK,
        {
            "call_id": "c-1",
            "event": "RINGING",
            "caller": "+34 600 111 222",
            "ivr_data": {"pedido": "P-77"},
        },
    )
    assert aviso["evento"] == "entrante"
    assert aviso["numero"] == "+34 600 111 222"
    assert aviso["sentido"] == "entrante"
    assert aviso["ivr"] == {"pedido": "P-77"}


def test_un_evento_sin_traducir_se_rechaza_en_vez_de_ignorarse() -> None:
    with pytest.raises(ErrorValidacion) as exc:
        tel.traducir_aviso(WEBHOOK, {"call_id": "c-1", "event": "PARKED"})
    assert exc.value.error_code == "cti.evento_invalido"


def test_un_perfil_sin_identificador_de_llamada_no_se_acepta() -> None:
    problemas = tel.validar_aviso({"mapeo": {"evento": "event"}})
    assert any("id_externo" in p for p in problemas)


def test_el_numero_se_pregunta_en_todas_sus_formas() -> None:
    formas = tel.variantes_del_numero("+34 600 111 222")
    assert "+34600111222" in formas and "600111222" in formas


# ── Ingerir: identificar, guardar y registrar una sola vez ────────────────


class _Party:
    """Un `party` de mentira que contesta y apunta lo que se le pide."""

    def __init__(self, contacto: str) -> None:
        self.contacto = contacto
        self.pedido: list[dict[str, Any]] = []
        self.actividad = str(uuid4())

    def __call__(self, **kw: Any) -> dict[str, Any]:
        self.pedido.append(kw)
        ruta, metodo = kw["ruta"], kw["metodo"]
        if ruta == "/api/v1/contacts" and "telefono__en" in kw["parametros"]:
            assert "+34600111222" in kw["parametros"]["telefono__en"]
            return {
                "ok": True,
                "datos": {"items": [{"id": self.contacto, "nombre_completo": "Ana Pérez"}]},
            }
        if ruta in ("/api/v1/contacts", "/api/v1/accounts"):
            return {"ok": True, "datos": {"items": []}}
        if ruta == "/api/v1/activities" and metodo == "GET":
            return {
                "ok": True,
                "datos": {"items": [{"id": "a1", "tipo": "email", "asunto": "Presupuesto"}]},
            }
        if ruta == "/api/v1/casos":
            return {
                "ok": True,
                "datos": {"items": [{"id": "k1", "asunto": "Avería", "estado": "abierto"}]},
            }
        if ruta == "/api/v1/activities" and metodo == "POST":
            return {"ok": True, "estado": 201, "datos": {"id": self.actividad}}
        return {"ok": True, "datos": {}}


@pytest.mark.db
def test_la_llamada_entrante_se_identifica_y_al_colgar_se_registra_una_vez(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    contacto = str(uuid4())
    party = _Party(contacto)
    identidad = {"tenant_id": tenant_id, "principal_id": uuid4(), "permisos": [], "roles": []}

    def aviso(evento: str, **extra: Any) -> tel.LlamadaTelefonica:
        crudo = {"call_id": "c-9", "event": evento, "from": "+34600111222", **extra}
        return tel.ingerir(
            db,
            tenant_id,
            conexion=None,
            aviso=tel.traducir_aviso(WEBHOOK, crudo),
            identidad=identidad,
            invocar=party,
        )

    sonando = aviso("RINGING", ivr_data={"pedido": "P-77"})
    assert str(sonando.contacto_id) == contacto
    assert sonando.contexto["ultimo_caso"]["asunto"] == "Avería"
    # Lo que tecleó en el IVR llega a la pantalla y no se vuelve a preguntar.
    pantalla = tel.a_dict(sonando)["pantalla"]
    assert pantalla["abrir_ficha"] is True
    assert pantalla["no_volver_a_preguntar"] == ["pedido"]

    aviso("ANSWERED", agent="ext-12")
    colgada = aviso("HANGUP", duration="185", recording_url="https://pbx.ejemplo/rec/c-9.mp3")
    assert colgada.estado == "colgada"
    assert colgada.resultado == "contestada"
    assert colgada.duracion_s == 185
    assert str(colgada.actividad_id) == party.actividad

    altas = [p for p in party.pedido if p["ruta"] == "/api/v1/activities" and p["metodo"] == "POST"]
    assert len(altas) == 1
    cuerpo = altas[0]["cuerpo"]
    assert cuerpo["tipo"] == "llamada"
    assert cuerpo["contacto_id"] == contacto
    assert cuerpo["detalles"]["duracion_s"] == 185
    assert cuerpo["detalles"]["grabacion"].endswith("c-9.mp3")
    assert cuerpo["detalles"]["ivr"] == {"pedido": "P-77"}

    # La centralita reenvía el colgado: ni otra llamada ni otra actividad.
    aviso("HANGUP", duration="185")
    altas = [p for p in party.pedido if p["ruta"] == "/api/v1/activities" and p["metodo"] == "POST"]
    assert len(altas) == 1


@pytest.mark.db
def test_la_que_nadie_coge_consta_como_perdida(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    party = _Party(str(uuid4()))
    identidad = {"tenant_id": tenant_id, "principal_id": uuid4()}
    for evento in ("RINGING", "MISSED"):
        llamada = tel.ingerir(
            db,
            tenant_id,
            conexion=None,
            aviso=tel.traducir_aviso(
                WEBHOOK, {"call_id": "p-1", "event": evento, "from": "+34600111222"}
            ),
            identidad=identidad,
            invocar=party,
        )
    assert llamada.resultado == "perdida"
    assert llamada.actividad_id is not None


@pytest.mark.db
def test_si_party_no_acepta_la_actividad_se_dice_y_no_se_da_por_registrada(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    def party(**kw: Any) -> dict[str, Any]:
        if kw["metodo"] == "POST":
            return {"ok": False, "estado": 403, "datos": {"mensaje": "sin permiso"}}
        return {"ok": True, "datos": {"items": []}}

    for evento in ("RINGING", "HANGUP"):
        llamada = tel.ingerir(
            db,
            tenant_id,
            conexion=None,
            aviso=tel.traducir_aviso(
                WEBHOOK, {"call_id": "x-1", "event": evento, "from": "+34911222333"}
            ),
            identidad={"tenant_id": tenant_id, "principal_id": uuid4()},
            invocar=party,
        )
    assert llamada.actividad_id is None
    assert "sin permiso" in (llamada.registro_error or "")


# ── Por HTTP, contra una centralita de verdad en un puerto ────────────────


class _Centralita:
    def __init__(self) -> None:
        self.recibido: list[tuple[str, dict[str, Any]]] = []


@pytest.fixture
def centralita() -> Iterator[tuple[str, _Centralita]]:
    estado = _Centralita()

    class Manejador(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_: Any) -> None:
            return

        def do_POST(self) -> None:  # noqa: N802
            largo = int(self.headers.get("Content-Length") or 0)
            cuerpo = json.loads(self.rfile.read(largo) or b"{}") if largo else {}
            estado.recibido.append((self.path, cuerpo))
            crudo = json.dumps({"call": {"id": f"pbx-{len(estado.recibido)}"}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(crudo)))
            self.end_headers()
            self.wfile.write(crudo)

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    try:
        yield f"http://127.0.0.1:{servidor.server_address[1]}", estado
    finally:
        servidor.shutdown()
        servidor.server_close()
        hilo.join(timeout=5)


@pytest.fixture
def cliente(monkeypatch: Any, db: Any) -> Iterator[TestClient]:
    from crmcore.config import get_settings
    from crmcore.service import crear_servicio

    from services.integration.api import ROUTERS
    from services.integration.api_telefonia import ROUTERS_TELEFONIA

    monkeypatch.setenv("URL_GUARD_HOSTS_PERMITIDOS", "127.0.0.1")
    get_settings.cache_clear()
    app = crear_servicio(
        nombre="integration",
        descripcion="integration para la telefonía de verdad",
        routers=[*ROUTERS, *ROUTERS_TELEFONIA],
        necesita_bus=False,
    )
    with TestClient(app) as cli:
        yield cli
    get_settings.cache_clear()


@pytest.fixture
def cabeceras(tenant_id: UUID) -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import H_PERMISOS, H_TENANT, H_USER, firmar_cabeceras_internas

    return firmar_cabeceras_internas(
        {H_TENANT: str(tenant_id), H_USER: str(uuid4()), H_PERMISOS: "*:*"},
        get_settings().secret_key.get_secret_value(),
    )


def test_de_punta_a_punta_por_http(
    cliente: TestClient,
    cabeceras: dict[str, str],
    centralita: tuple[str, _Centralita],
    monkeypatch: Any,
) -> None:
    """Las rutas que pide la pantalla, por HTTP: perfil, llamar (llega a la
    centralita), aviso entrante, sonando, transferir, anotar y listar."""
    url, estado = centralita
    party = _Party(str(uuid4()))
    monkeypatch.setattr(tel, "_invocar", party)

    conexion = cliente.post(
        "/api/v1/integraciones/conexiones",
        headers=cabeceras,
        json={
            "nombre": f"pbx-{uuid4().hex[:6]}",
            "config": {"url_base": url, "auth_tipo": "ninguna"},
        },
    )
    assert conexion.status_code == 201, conexion.text
    cid = conexion.json()["id"]
    for clave, ruta in (("originar_llamada", "/calls"), ("transferir_llamada", "/transfer")):
        op = cliente.post(
            f"/api/v1/integraciones/conexiones/{cid}/operaciones",
            headers=cabeceras,
            json={
                "clave": clave,
                "nombre": clave,
                "definicion": {
                    "metodo": "POST",
                    "ruta": ruta,
                    "cuerpo": {"to": "{{numero}}", "ref": "{{referencia}}", "target": "{{a}}"},
                    "ruta_resultados": "call",
                    "mapeo": {"id_externo": "id"},
                },
            },
        )
        assert op.status_code == 201, op.text

    sin = cliente.get("/api/v1/telefonia/perfil", headers=cabeceras).json()
    assert sin["conectado"] is False

    perfil = cliente.put(
        "/api/v1/telefonia/perfil",
        headers=cabeceras,
        json={"conexion_id": cid, "webhook": WEBHOOK},
    )
    assert perfil.status_code == 200, perfil.text
    assert perfil.json()["falta"] == []

    llamada = cliente.post(
        "/api/v1/telefonia/llamar",
        headers=cabeceras,
        json={"numero": "+34600111222", "contacto_id": party.contacto},
    )
    assert llamada.status_code == 200, llamada.text
    assert llamada.json()["id_externo"] == "pbx-1"
    assert estado.recibido[0][0] == "/calls"
    assert estado.recibido[0][1]["to"] == "+34600111222"
    assert estado.recibido[0][1]["ref"] == llamada.json()["id"]

    entra = cliente.post(
        "/api/v1/telefonia/avisos",
        headers=cabeceras,
        json={
            "call_id": "in-1",
            "event": "RINGING",
            "from": "+34600111222",
            "ivr_data": {"motivo": "factura"},
        },
    )
    assert entra.status_code == 200, entra.text
    sonando = cliente.get("/api/v1/telefonia/sonando", headers=cabeceras).json()
    assert [x["id_externo"] for x in sonando["llamadas"]] == ["in-1"]
    assert sonando["llamadas"][0]["identificacion"]["nombre"] == "Ana Pérez"
    assert sonando["sondeo_s"] >= 2

    lid = entra.json()["id"]
    pasa = cliente.post(
        f"/api/v1/telefonia/llamadas/{lid}/transferir",
        headers=cabeceras,
        json={"a": "facturacion", "resumen": "Pregunta por la factura de octubre"},
    )
    assert pasa.status_code == 200, pasa.text
    assert estado.recibido[-1] == ("/transfer", {"to": "", "ref": lid, "target": "facturacion"})
    assert pasa.json()["transferencias"][0]["resumen"].startswith("Pregunta")

    sin_resumen = cliente.post(
        f"/api/v1/telefonia/llamadas/{lid}/transferir",
        headers=cabeceras,
        json={"a": "x", "resumen": "  "},
    )
    assert sin_resumen.status_code == 422

    cuelga = cliente.post(
        "/api/v1/telefonia/avisos",
        headers=cabeceras,
        json={"call_id": "in-1", "event": "HANGUP", "duration": 60},
    )
    assert cuelga.json()["actividad_id"] == party.actividad
    nota = cliente.post(
        f"/api/v1/telefonia/llamadas/{lid}/resultado",
        headers=cabeceras,
        json={"resultado_comercial": "hablado", "nota": "Se le reenvía la factura"},
    )
    assert nota.status_code == 200, nota.text

    # COB-16: el listado dice cuántas hay aunque sirva menos. Aquí hay la
    # saliente y la entrante.
    lista = cliente.get("/api/v1/telefonia/llamadas?limite=1", headers=cabeceras).json()
    assert len(lista["llamadas"]) == 1
    assert lista["total"] >= 2
    assert lista["hay_mas"] is True
    assert any(
        p["metodo"] == "PATCH" and p["cuerpo"] == {"cuerpo": "Se le reenvía la factura"}
        for p in party.pedido
    )
    una = cliente.get(f"/api/v1/telefonia/llamadas/{lid}", headers=cabeceras).json()
    assert una["nota"] == "Se le reenvía la factura"
    todas = cliente.get("/api/v1/telefonia/llamadas", headers=cabeceras).json()["llamadas"]
    assert {x["id_externo"] for x in todas} >= {"pbx-1", "in-1"}
    assert cliente.get("/api/v1/telefonia/sonando", headers=cabeceras).json()["llamadas"] == []


# ── El marcador: lo que comprueba antes y lo que hace al colgar ───────────


class _Servicios:
    def __init__(self, *, no_contactar: bool = False) -> None:
        self.no_contactar = no_contactar
        self.pedido: list[dict[str, Any]] = []

    def __call__(self, **kw: Any) -> dict[str, Any]:
        self.pedido.append(kw)
        ruta = kw["ruta"]
        if ruta.endswith("/consentimientos"):
            return {"ok": True, "datos": []}
        if ruta.startswith("/api/v1/contacts/") and kw["metodo"] == "GET":
            return {"ok": True, "datos": {"no_contactar": self.no_contactar}}
        if ruta == "/api/v1/telefonia/llamar":
            return {"ok": True, "datos": {"id": "l1", "estado": "saliente"}}
        if ruta.startswith("/api/v1/telefonia/llamadas/") and kw["metodo"] == "GET":
            return {
                "ok": True,
                "datos": {
                    "id": "l1",
                    "contacto_id": CONTACTO,
                    "duracion_s": 90,
                    "numero": "600111222",
                },
            }
        return {"ok": True, "estado": 200, "datos": {"id": "x"}}


CONTACTO = str(uuid4())
IDENTIDAD = {"tenant_id": uuid4(), "principal_id": uuid4(), "permisos": [], "roles": []}


def test_el_marcador_no_llama_a_quien_pidio_no_ser_llamado() -> None:
    servicios = _Servicios(no_contactar=True)
    with pytest.raises(Prohibido):
        marcador.llamar(
            identidad=IDENTIDAD,
            numero="600111222",
            contacto_id=UUID(CONTACTO),
            cuenta_id=None,
            consiente_grabacion=True,
            invocar=servicios,
        )
    assert not any(p["ruta"] == "/api/v1/telefonia/llamar" for p in servicios.pedido)


def test_el_marcador_pide_a_la_telefonia_y_graba_solo_si_la_politica_y_la_persona_quieren(
    monkeypatch: Any,
) -> None:
    servicios = _Servicios()
    monkeypatch.setattr(
        marcador, "_ajuste", lambda clave: True if clave == "marcador_grabar_por_politica" else 20
    )
    salida = marcador.llamar(
        identidad=IDENTIDAD,
        numero="600111222",
        contacto_id=UUID(CONTACTO),
        cuenta_id=None,
        consiente_grabacion=False,
        invocar=servicios,
    )
    pedida = [p for p in servicios.pedido if p["ruta"] == "/api/v1/telefonia/llamar"][0]
    assert pedida["cuerpo"]["grabar"] is False
    assert salida["llamada"]["id"] == "l1"


def test_al_colgar_se_aplica_lo_que_el_resultado_obliga() -> None:
    servicios = _Servicios()
    salida = marcador.colgar(
        identidad=IDENTIDAD,
        llamada_id=uuid4(),
        resultado="pide_que_no_le_llamen",
        nota="",
        proxima_fecha=None,
        invocar=servicios,
    )
    assert salida["aplicadas"] == ["Ficha marcada como «no contactar»"]
    parche = [p for p in servicios.pedido if p["metodo"] == "PATCH"][0]
    assert parche["ruta"] == f"/api/v1/contacts/{CONTACTO}"
    assert parche["cuerpo"] == {"no_contactar": True}

    servicios = _Servicios()
    salida = marcador.colgar(
        identidad=IDENTIDAD,
        llamada_id=uuid4(),
        resultado="reprogramar",
        nota="Llamar tras el cierre",
        proxima_fecha=date(2026, 11, 20),
        invocar=servicios,
    )
    alta = [p for p in servicios.pedido if p["ruta"] == "/api/v1/activities"][0]
    assert alta["cuerpo"]["vence_at"].startswith("2026-11-20")
    assert salida["aplicadas"] == ["Siguiente llamada creada con fecha"]


def test_las_rutas_del_marcador_por_http(monkeypatch: Any) -> None:
    """La ficha pide `/marcador/llamar` y `/marcador/colgar`: por HTTP."""
    from crmcore.config import get_settings
    from crmcore.http.deps import H_PERMISOS, H_TENANT, H_USER, firmar_cabeceras_internas
    from crmcore.service import crear_servicio

    from services.service.api import router_marcador

    servicios = _Servicios()
    monkeypatch.setattr(marcador, "_invocar", servicios)
    app = crear_servicio(
        nombre="service", descripcion="marcador", routers=[router_marcador], necesita_bus=False
    )
    cab = firmar_cabeceras_internas(
        {H_TENANT: str(uuid4()), H_USER: str(uuid4()), H_PERMISOS: "activity:write"},
        get_settings().secret_key.get_secret_value(),
    )
    with TestClient(app) as cli:
        r = cli.post(
            "/api/v1/marcador/llamar",
            headers=cab,
            json={"numero": "600111222", "contacto_id": CONTACTO},
        )
        assert r.status_code == 200, r.text
        assert r.json()["llamada"]["id"] == "l1"
        r = cli.post(
            "/api/v1/marcador/colgar",
            headers=cab,
            json={"llamada_id": str(uuid4()), "resultado": "hablado", "nota": "Bien"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["falta_la_nota"] is False
        sin = cli.post("/api/v1/marcador/llamar", headers=cab, json={"numero": "600111222"})
        assert sin.status_code == 422
