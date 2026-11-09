"""Transcripción y resumen de reuniones con compromisos, variantes de copy
generadas y el dictado del asistente de voz, por HTTP (CRM-01.02.01.05,
CRM-01.02.01.06, CRM-02.04.01.04, CRM-04.02.01.08).

Hasta el 09-11-2026 las tres cosas simulaban: la transcripción recibía el texto
ya transcrito y no resumía ni guardaba, las variantes eran las que tecleaba
quien llamaba, y la voz eran reglas sobre texto ya reconocido. Aquí se recorre
cada ruta como la recorre la pantalla y se fija lo que lo hace real:

  * la plantilla del proveedor se instala en Integraciones por su API y queda
    en uso; sin ella, transcribir dice por qué no;
  * el audio se guarda como adjunto del registro, el proveedor lo descarga de
    un enlace firmado, el modelo resume y extrae, y se guarda todo;
  * de un compromiso sin dueño no sale propuesta, y la cita se comprueba;
  * la tarea se crea al confirmar, colgada de lo mismo que la reunión;
  * las variantes se generan, se guardan, se aprueban de una en una y gana una
    aprobada;
  * el dictado devuelve el texto sin guardar la voz.

Los otros servicios (party, integration) y el modelo son dobles: lo que se
prueba es qué se les pide y qué se hace con lo que devuelven.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from starlette.testclient import TestClient

from services.intelligence import reuniones as reu
from services.intelligence import variantes_copy as vc
from tests.unit.test_ia_generativa import _proveedor, uow  # noqa: F401

pytestmark = pytest.mark.db

TRANSCRITO = (
    "Hola Marta. Te mando la oferta revisada el jueves. Si me la mandas el jueves, "
    "la miro. Yo hablo con compras la semana que viene."
)


@pytest.fixture
def cliente(db: Any) -> Any:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        modulo = importlib.import_module("services.intelligence.main")
        with TestClient(modulo.app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()
        reu._registrar_http(None)
        reu.registrar_resumidor(None)
        vc.registrar_redactor(None)


@pytest.fixture
def cabeceras(tenant_id: UUID) -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import (
        H_FACTOR_FUERTE,
        H_PERMISOS,
        H_ROLES,
        H_TENANT,
        H_USER,
        firmar_cabeceras_internas,
    )

    return firmar_cabeceras_internas(
        {
            H_TENANT: str(tenant_id),
            H_USER: str(uuid4()),
            H_PERMISOS: "*:*",
            H_ROLES: "admin",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


class CRMDeMentira:
    """party e integration: guarda lo que se le pide y contesta lo justo."""

    def __init__(self, *, confianza: float = 0.93) -> None:
        self.pedidas: list[dict[str, Any]] = []
        self.confianza = confianza
        self.cuenta = str(uuid4())

    def __call__(self, **kw: Any) -> dict[str, Any]:
        self.pedidas.append(kw)
        ruta, metodo = kw["ruta"], kw["metodo"]
        if ruta == "/api/v1/integraciones/conexiones":
            return {"estado": 201, "datos": {"id": "c0000000-0000-0000-0000-000000000001"}}
        if ruta.endswith("/operaciones"):
            return {"estado": 201, "datos": {"id": "op"}}
        if ruta.endswith("/invocar"):
            return {
                "estado": 200,
                "datos": {
                    "registros": [
                        {"texto": TRANSCRITO, "confianza": self.confianza, "segundos": 61.2}
                    ]
                },
            }
        if ruta.startswith("/api/v1/adjuntos/") and ruta.endswith("/enlace"):
            return {"estado": 200, "datos": {"token": "tok"}}
        if ruta.startswith("/api/v1/adjuntos/"):
            return {"estado": 201, "datos": {"id": str(uuid4())}}
        if ruta.startswith("/api/v1/activities/") and metodo == "GET":
            return {
                "estado": 200,
                "datos": {"objeto": "cuenta", "objeto_id": self.cuenta, "cuenta_id": self.cuenta},
            }
        if ruta == "/api/v1/activities":
            return {"estado": 201, "datos": {"id": "tarea-1"}}
        return {"estado": 404, "datos": {}}

    def de(self, trozo: str) -> list[dict[str, Any]]:
        return [p for p in self.pedidas if trozo in p["ruta"]]


def _resumidor(**kw: Any) -> dict[str, Any]:
    _resumidor.recibido = kw  # type: ignore[attr-defined]
    return {
        "resumen": "Se revisa la oferta y compras entra la semana que viene.",
        "elementos": [
            {
                "tipo": "compromiso",
                "texto": "Mandar la oferta revisada",
                "quien": "Comercial",
                "cuando": "2026-11-12",
                "cita": "Te mando la oferta revisada el jueves",
            },
            # Sin dueño: no se propone.
            {"tipo": "proximo_paso", "texto": "Mirar la oferta", "quien": "", "cita": "la miro"},
            {
                "tipo": "proximo_paso",
                "texto": "Hablar con compras",
                "quien": "Marta",
                "cita": "hablo con el director financiero",
            },
        ],
        "tokens_entrada": 300,
        "tokens_salida": 80,
    }


def _formulario(objeto_id: str, **extra: Any) -> dict[str, Any]:
    return {
        "objeto": "actividad",
        "objeto_id": objeto_id,
        "base_para_grabar": "consentimiento_de_todos",
        "participantes_avisados": "true",
        **extra,
    }


def test_sin_proveedor_lo_dice_y_la_plantilla_lo_deja_en_uso(
    cliente: TestClient,
    cabeceras: dict[str, str],
    uow: UnidadDeTrabajo,  # noqa: F811
) -> None:
    crm = CRMDeMentira()
    reu._registrar_http(crm)
    p = cliente.get("/api/v1/transcripciones/proveedor", headers=cabeceras)
    assert p.status_code == 200, p.text
    assert p.json()["configurado"] is False and p.json()["porque"]
    assert {pl["clave"] for pl in p.json()["plantillas"]} == {"deepgram", "google_stt"}

    sin = cliente.post(
        "/api/v1/transcripciones/reuniones/transcribir",
        headers=cabeceras,
        data=_formulario(str(uuid4())),
        files={"fichero": ("r.webm", b"audio", "audio/webm")},
    )
    assert sin.status_code == 409 and sin.json()["error_code"] == "reunion.sin_proveedor"

    i = cliente.post(
        "/api/v1/transcripciones/proveedor",
        headers=cabeceras,
        json={"plantilla": "deepgram", "url_base": "http://127.0.0.1:9"},
    )
    assert i.status_code == 200, i.text
    assert i.json()["configurado"] is True and i.json()["envio"] == "enlace"
    alta = crm.de("/integraciones/conexiones")[0]["cuerpo"]
    # La dirección se puede cambiar; la forma de la petición es la de la plantilla.
    assert alta["config"]["url_base"] == "http://127.0.0.1:9"
    assert alta["config"]["auth_tipo"] == "api_key"
    operacion = crm.de("/operaciones")[0]["cuerpo"]
    assert operacion["clave"] == "transcribir"
    assert operacion["definicion"]["cuerpo"] == {"url": "{{audio_url}}"}


def test_el_audio_se_guarda_se_transcribe_se_resume_y_la_tarea_espera(
    cliente: TestClient,
    cabeceras: dict[str, str],
    uow: UnidadDeTrabajo,  # noqa: F811
) -> None:
    _proveedor(uow)
    uow.db.flush()
    crm = CRMDeMentira()
    reu._registrar_http(crm)
    reu.registrar_resumidor(_resumidor)
    cliente.post(
        "/api/v1/transcripciones/proveedor", headers=cabeceras, json={"plantilla": "deepgram"}
    )
    actividad = str(uuid4())

    # Sin avisar a los participantes no sale nada hacia ningún sitio.
    no = cliente.post(
        "/api/v1/transcripciones/reuniones/transcribir",
        headers=cabeceras,
        data=_formulario(actividad, participantes_avisados="false"),
        files={"fichero": ("r.webm", b"audio", "audio/webm")},
    )
    assert no.status_code == 403
    assert not crm.de("/invocar")

    r = cliente.post(
        "/api/v1/transcripciones/reuniones/transcribir",
        headers=cabeceras,
        data=_formulario(actividad),
        files={"fichero": ("r.webm", b"audio-de-verdad", "audio/webm")},
    )
    assert r.status_code == 200, r.text
    t = r.json()
    # El audio, como adjunto de la actividad; el proveedor, con el enlace firmado.
    subida = crm.de("/api/v1/adjuntos/actividad")[0]
    assert subida["fichero"][1] == b"audio-de-verdad"
    assert subida["formulario"]["objeto_id"] == actividad
    invocada = crm.de("/invocar")[0]["cuerpo"]["parametros"]
    assert invocada["audio_url"].endswith("/api/v1/adjuntos/actividad/enlace/tok")
    assert invocada["idioma"] == "es" and invocada["idioma_region"] == "es-ES"
    # Lo transcrito, resumido y guardado; el modelo recibió la transcripción.
    assert _resumidor.recibido["texto"] == TRANSCRITO  # type: ignore[attr-defined]
    assert t["texto"] == TRANSCRITO and t["fiable"] is True and t["minutos"] == 2
    assert t["resumen"].startswith("Se revisa") and t["adjunto_id"]
    # Sin dueño no se propone; la cita que no está en lo transcrito se marca.
    textos = {c["texto"]: c for c in t["compromisos"]}
    assert set(textos) == {"Mandar la oferta revisada", "Hablar con compras"}
    assert textos["Mandar la oferta revisada"]["cita_literal"] is True
    assert textos["Hablar con compras"]["cita_literal"] is False
    assert len(t["descartados"]) == 1
    assert not crm.de("/api/v1/activities")  # nada se crea solo

    lista = cliente.get(
        "/api/v1/transcripciones/reuniones",
        headers=cabeceras,
        params={"objeto": "actividad", "objeto_id": actividad},
    )
    assert lista.status_code == 200 and lista.json()["items"][0]["id"] == t["id"]

    n = textos["Mandar la oferta revisada"]["n"]
    c = cliente.post(
        f"/api/v1/transcripciones/reuniones/{t['id']}/compromisos/{n}",
        headers=cabeceras,
        json={"confirmar": True, "asunto": "Mandar oferta v2", "vence_at": "2026-11-12T10:00:00Z"},
    )
    assert c.status_code == 200, c.text
    hecho = next(x for x in c.json()["compromisos"] if x["n"] == n)
    assert hecho["estado"] == "confirmada" and hecho["tarea_id"] == "tarea-1"
    assert hecho["hubo_correccion"] is True
    tarea = [p for p in crm.de("/api/v1/activities") if p["metodo"] == "POST"][0]["cuerpo"]
    # Cuelga de la cuenta de la reunión, no de la actividad.
    assert tarea["tipo"] == "tarea" and tarea["asunto"] == "Mandar oferta v2"
    assert tarea["objeto"] == "cuenta" and tarea["cuenta_id"] == crm.cuenta
    assert tarea["detalles"]["actividad_id"] == actividad
    otra = cliente.post(
        f"/api/v1/transcripciones/reuniones/{t['id']}/compromisos/{n}",
        headers=cabeceras,
        json={"confirmar": True},
    )
    assert otra.status_code == 409


def test_poco_fiable_no_propone_y_el_texto_pegado_tambien_se_resume(
    cliente: TestClient,
    cabeceras: dict[str, str],
    uow: UnidadDeTrabajo,  # noqa: F811
) -> None:
    _proveedor(uow)
    uow.db.flush()
    reu._registrar_http(CRMDeMentira(confianza=0.4))
    reu.registrar_resumidor(_resumidor)
    cliente.post(
        "/api/v1/transcripciones/proveedor", headers=cabeceras, json={"plantilla": "deepgram"}
    )
    r = cliente.post(
        "/api/v1/transcripciones/reuniones/transcribir",
        headers=cabeceras,
        data=_formulario(str(uuid4()), enlace="https://grabaciones.example.com/r.mp3"),
    )
    assert r.status_code == 200, r.text
    assert r.json()["fiable"] is False and r.json()["compromisos"] == []
    assert r.json()["aviso"]

    pegado = cliente.post(
        "/api/v1/transcripciones/reuniones/transcribir",
        headers=cabeceras,
        data=_formulario(str(uuid4()), texto=TRANSCRITO),
    )
    assert pegado.status_code == 200, pegado.text
    assert pegado.json()["origen"] == "texto" and pegado.json()["compromisos"]

    dos = cliente.post(
        "/api/v1/transcripciones/reuniones/transcribir",
        headers=cabeceras,
        data=_formulario(str(uuid4()), texto="x", enlace="https://a.example.com/b"),
    )
    assert dos.status_code == 422


def test_las_variantes_se_generan_se_revisan_y_gana_una_aprobada(
    cliente: TestClient,
    cabeceras: dict[str, str],
    uow: UnidadDeTrabajo,  # noqa: F811
) -> None:
    _proveedor(uow)
    uow.db.flush()
    recibido: dict[str, Any] = {}

    def redactor(**kw: Any) -> dict[str, Any]:
        recibido.update(kw)
        return {
            "variantes": [
                "Tu oferta te espera",
                "Tu oferta te espera",  # repetida: fuera
                "Ahorra un 40 % este mes",
                "Base de partida",  # igual que la base: fuera
            ],
            "modelo": "m-redaccion",
        }

    vc.registrar_redactor(redactor)
    perdido = cliente.post(
        "/api/v1/variantes/generar",
        headers=cabeceras,
        json={"base": "Tu pedido {{pedido.ref}}", "cuantas": 1, "objeto": "x", "objeto_ref": "y"},
    )
    # El marcador que la variante ha perdido se marca para quien revisa.
    assert {"texto": "{{pedido.ref}}", "es": "un marcador que falta"} in perdido.json()[
        "variantes"
    ][0]["afirmaciones"]
    r = cliente.post(
        "/api/v1/variantes/generar",
        headers=cabeceras,
        json={
            "base": "Base de partida",
            "objetivo": "Que abran el correo",
            "canal": "asunto",
            "cuantas": 3,
            "objeto": "plantilla_correo",
            "objeto_ref": "bienvenida",
        },
    )
    assert r.status_code == 200, r.text
    assert recibido["cuantas"] == 3 and recibido["base"] == "Base de partida"
    variantes = r.json()["variantes"]
    assert [v["texto_propuesto"] for v in variantes] == [
        "Tu oferta te espera",
        "Ahorra un 40 % este mes",
    ]
    assert r.json()["aviso"]
    # La cifra se marca para que el revisor no la lea por encima.
    assert variantes[1]["afirmaciones"][0]["es"] == "un porcentaje concreto"

    demasiadas = cliente.post(
        "/api/v1/variantes/generar", headers=cabeceras, json={"base": "x", "cuantas": 50}
    )
    assert demasiadas.status_code == 422

    sin_aprobar = cliente.post(
        f"/api/v1/variantes/generadas/{variantes[0]['id']}/ganadora", headers=cabeceras
    )
    assert sin_aprobar.status_code == 409

    a = cliente.post(
        f"/api/v1/variantes/generadas/{variantes[0]['id']}/decidir",
        headers=cabeceras,
        json={"aprobar": True, "texto_final": "Tu oferta sigue esperándote"},
    )
    assert a.status_code == 200 and a.json()["hubo_reescritura"] is True
    b = cliente.post(
        f"/api/v1/variantes/generadas/{variantes[1]['id']}/decidir",
        headers=cabeceras,
        json={"aprobar": False, "motivo": "No podemos sostener el 40 %"},
    )
    assert b.status_code == 200 and b.json()["estado"] == "rechazada"
    g = cliente.post(
        f"/api/v1/variantes/generadas/{variantes[0]['id']}/ganadora", headers=cabeceras
    )
    assert g.status_code == 200 and g.json()["ganadora"] is True

    lista = cliente.get(
        "/api/v1/variantes/generadas",
        headers=cabeceras,
        params={"objeto": "plantilla_correo", "objeto_ref": "bienvenida"},
    ).json()["items"]
    assert {v["estado"] for v in lista} == {"aprobada", "rechazada"}
    assert [v["ganadora"] for v in lista].count(True) == 1


def test_el_dictado_devuelve_el_texto_sin_guardar_la_voz(
    cliente: TestClient,
    cabeceras: dict[str, str],
    uow: UnidadDeTrabajo,  # noqa: F811
) -> None:
    crm = CRMDeMentira()
    reu._registrar_http(crm)
    cliente.post(
        "/api/v1/transcripciones/proveedor", headers=cabeceras, json={"plantilla": "deepgram"}
    )
    # Un proveedor que descarga de un enlace obligaría a guardar la voz: no.
    por_enlace = cliente.post(
        "/api/v1/voz/dictado",
        headers=cabeceras,
        files={"fichero": ("p.webm", b"voz", "audio/webm")},
    )
    assert por_enlace.status_code == 409

    cliente.post(
        "/api/v1/transcripciones/proveedor", headers=cabeceras, json={"plantilla": "google_stt"}
    )
    # Con la clave de idempotencia que manda siempre la interfaz: un formulario
    # no se puede leer dos veces y esto daba 500 en toda subida de fichero.
    r = cliente.post(
        "/api/v1/voz/dictado",
        headers={**cabeceras, "Idempotency-Key": str(uuid4())},
        files={"fichero": ("p.webm", b"voz", "audio/webm")},
        data={"idioma": "es"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"texto": TRANSCRITO, "confianza": 0.93, "guardado": False}
    assert crm.de("/invocar")[-1]["cuerpo"]["parametros"]["audio_base64"] == "dm96"
    assert not crm.de("/api/v1/adjuntos")
