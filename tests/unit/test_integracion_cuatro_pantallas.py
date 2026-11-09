"""Cuatro capacidades de integración que estaban hechas y no se alcanzaban.

* **CRM-00.01.04.08** — las credenciales de una conexión: qué pide su tipo de
  autenticación, cuándo y quién las fijó, y **nunca** el secreto.
* **CRM-00.04.05.06** — el cliente ve sus encargos en el portal, con su token y
  sin ver lo que no es suyo.
* **CRM-06.01.02.11** — mandar un sobre por el operador de verdad: el
  identificador del proveedor se guardaba sólo con el doble de las pruebas.
* **CRM-06.01.03.10** — la reunión en línea se crea DE VERDAD en el proveedor
  de la suite y su enlace queda en la actividad.

Los proveedores se doblan en el transporte HTTP (`httpx.MockTransport`), no
en la función que los llama: lo que se prueba es la petición que sale y lo que
se hace con la respuesta tal como la devuelve el conector de la casa.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator
from uuid import UUID, uuid4

import httpx
import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


# ── El andamio ────────────────────────────────────────────────────────────


@pytest.fixture
def con_cifrado(monkeypatch: Any) -> Iterator[None]:
    from crmcore.config import get_settings

    monkeypatch.setenv("ENCRYPTION_KEY", "maestra-de-pruebas-suficientemente-larga")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def cliente(db: Any, con_cifrado: None) -> Iterator[Any]:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        with TestClient(importlib.import_module("services.integration.main").app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


@pytest.fixture
def usuario() -> UUID:
    return uuid4()


@pytest.fixture
def cabeceras(tenant_id: UUID, usuario: UUID) -> dict[str, str]:
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
            H_USER: str(usuario),
            H_PERMISOS: "*:*",
            H_ROLES: "admin",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> Any:
    from crmcore.db.uow import UnidadDeTrabajo

    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


@pytest.fixture
def proveedor_doble(monkeypatch: Any) -> list[httpx.Request]:
    """El proveedor externo, doblado en el transporte del conector.

    Contesta según la ruta y apunta cada petición. Es el sitio exacto donde la
    casa sale a la red: más arriba se doblaría el código que se quiere probar.
    """
    from services.integration import conector

    pedidas: list[httpx.Request] = []

    def _responder(peticion: httpx.Request) -> httpx.Response:
        pedidas.append(peticion)
        if peticion.url.path.endswith("/envelopes"):
            return httpx.Response(201, json={"envelope_id": "env-77", "status": "sent"})
        if peticion.url.path.endswith("/onlineMeetings"):
            return httpx.Response(
                201, json={"id": "m-1", "joinWebUrl": "https://reuniones.example/join/1"}
            )
        return httpx.Response(404, json={})

    def _fabrica(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return httpx.AsyncClient(transport=httpx.MockTransport(_responder), **kwargs)

    monkeypatch.setattr(conector, "cliente_seguro_async", _fabrica)
    conector.limpiar_tokens()
    return pedidas


def _conexion(uow: Any, *, nombre: str, config: dict[str, Any]) -> Any:
    from services.integration.modelos import Conexion

    fila = Conexion(tenant_id=uow.tenant_id, nombre=nombre, config=config)
    uow.db.add(fila)
    uow.db.flush()
    return fila


# ── CRM-00.01.04.08: credenciales de una conexión ─────────────────────────


def test_la_credencial_dice_que_pide_cuando_y_quien_y_nunca_el_secreto_crm_00_01_04_08(
    cliente: Any, cabeceras: dict[str, str], usuario: UUID, uow: Any, contexto_tenant: UUID
) -> None:
    conexion = _conexion(
        uow,
        nombre="ERP",
        config={
            "url_base": "https://erp.example",
            "auth_tipo": "oauth2_client_credentials",
            "oauth_token_url": "https://erp.example/token",
        },
    )
    ruta = f"/api/v1/integraciones/conexiones/{conexion.id}/credenciales"

    vacia = cliente.get(ruta, headers=cabeceras)
    assert vacia.status_code == 200, vacia.text
    cuerpo = vacia.json()
    # Los campos los decide el tipo de autenticación, con cuál es secreto.
    assert cuerpo["campos"] == [
        {"clave": "client_id", "secreto": False},
        {"clave": "client_secret", "secreto": True},
    ]
    assert cuerpo["actual"] is None
    assert cuerpo["se_puede_probar"] is False

    # Incompleta no se guarda: se descubriría en la primera llamada.
    a_medias = cliente.put(ruta, headers=cabeceras, json={"valores": {"client_id": "app"}})
    assert a_medias.status_code == 422, a_medias.text
    assert "client_secret" in a_medias.text

    secreto = "TESTIGO-secreto-que-no-sale"
    fijada = cliente.put(
        ruta, headers=cabeceras, json={"valores": {"client_id": "app", "client_secret": secreto}}
    )
    assert fijada.status_code == 200, fijada.text
    assert fijada.json() == {"version": 1, "rotada": False}

    rotada = cliente.put(
        ruta, headers=cabeceras, json={"valores": {"client_id": "app", "client_secret": "otro"}}
    )
    assert rotada.json() == {"version": 2, "rotada": True}

    leida = cliente.get(ruta, headers=cabeceras)
    texto = leida.text
    assert secreto not in texto and "otro" not in texto, "el secreto ha salido por la API"
    datos = leida.json()
    assert datos["actual"]["version"] == 2
    assert datos["actual"]["fijada_por"] == str(usuario)
    assert datos["actual"]["fijada_at"]
    assert datos["actual"]["claves"] == ["client_id", "client_secret"]
    assert [v["version"] for v in datos["anteriores"]] == [1]
    assert datos["anteriores"][0]["rotada_at"], "la anterior no dice cuándo se rotó"


def test_un_tipo_sin_credencial_no_pide_campos_crm_00_01_04_08(
    cliente: Any, cabeceras: dict[str, str], uow: Any, contexto_tenant: UUID
) -> None:
    conexion = _conexion(uow, nombre="Abierta", config={"url_base": "https://x.example"})
    datos = cliente.get(
        f"/api/v1/integraciones/conexiones/{conexion.id}/credenciales", headers=cabeceras
    ).json()
    assert datos["auth_tipo"] == "ninguna"
    assert datos["campos"] == []


def test_cada_tipo_de_autenticacion_tiene_sus_campos() -> None:
    """La lista de campos y `cabeceras_auth` no pueden divergir: un tipo que
    autentica sin campos declarados se guardaría con la credencial vacía."""
    import inspect

    from services.integration import conector

    fuente = inspect.getsource(conector.cabeceras_auth)
    for tipo in conector.SECRETOS_POR_AUTH:
        assert f'"{tipo}"' in fuente, f"«{tipo}» tiene campos y cabeceras_auth no lo conoce"
    for tipo, campos in conector.SECRETOS_POR_AUTH.items():
        for campo in campos:
            assert (
                tipo == "oauth2_client_credentials"
                or f'"{campo}"' in fuente
                or (f"'{campo}'" in fuente)
            ), f"«{campo}» se pide y cabeceras_auth no lo lee"


# ── CRM-00.04.05.06: los encargos en el portal ────────────────────────────


def _encargo(uow: Any, *, cuenta_id: UUID, referencia: str) -> Any:
    from services.integration.encargos import Encargo

    fila = Encargo(
        tenant_id=uow.tenant_id,
        proveedor="mensajeria",
        referencia_propia=referencia,
        referencia_externa=f"EXT-{referencia}",
        cuenta_id=cuenta_id,
        estado="en_curso",
        prometido_para=datetime.now(timezone.utc) - timedelta(days=1),
        coste_previsto=12,
        interno={"nota": "TESTIGO-interno"},
    )
    uow.db.add(fila)
    uow.db.flush()
    return fila


def _token_portal(tenant_id: UUID, cuenta_id: UUID, secciones: list[str]) -> dict[str, str]:
    from crmcore.http.portal_deps import emitir_token_portal

    token, _ = emitir_token_portal(
        acceso_id=uuid4(),
        tenant_id=tenant_id,
        nivel="cuenta",
        cuenta_id=cuenta_id,
        secciones=secciones,
    )
    return {"Authorization": f"Bearer {token}"}


def test_el_cliente_ve_sus_encargos_y_no_los_de_otro_crm_00_04_05_06(
    cliente: Any, uow: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    mia, ajena = uuid4(), uuid4()
    propio = _encargo(uow, cuenta_id=mia, referencia="E-1")
    otro = _encargo(uow, cuenta_id=ajena, referencia="E-2")
    token = _token_portal(tenant_id, mia, ["encargos"])

    lista = cliente.get("/api/v1/portal/mi/encargos", headers=token)
    assert lista.status_code == 200, lista.text
    assert [e["referencia"] for e in lista.json()] == ["E-1"]
    fila = lista.json()[0]
    assert fila["va_tarde"] is True
    # Lo interno no sale, ni en la lista ni en el seguimiento.
    for prohibido in ("coste", "interno", "TESTIGO-interno"):
        assert prohibido not in lista.text, prohibido

    seguimiento = cliente.get(f"/api/v1/portal/mi/encargos/{propio.id}/seguimiento", headers=token)
    assert seguimiento.status_code == 200, seguimiento.text
    assert seguimiento.json()["referencia"] == "E-1"
    assert "coste" not in seguimiento.text and "TESTIGO-interno" not in seguimiento.text

    # El de otra empresa da 404, no 403: un 403 confirmaría que existe.
    ajeno = cliente.get(f"/api/v1/portal/mi/encargos/{otro.id}/seguimiento", headers=token)
    assert ajeno.status_code == 404, ajeno.text


def test_sin_la_seccion_no_se_ven_los_encargos_crm_00_04_05_06(
    cliente: Any, uow: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    cuenta = uuid4()
    _encargo(uow, cuenta_id=cuenta, referencia="E-3")
    sin = cliente.get(
        "/api/v1/portal/mi/encargos", headers=_token_portal(tenant_id, cuenta, ["pedidos"])
    )
    assert sin.status_code == 401, sin.text
    # Y un token de empleado no vale en el portal.
    sin_token = cliente.get("/api/v1/portal/mi/encargos")
    assert sin_token.status_code == 401


def test_el_gateway_manda_los_encargos_del_portal_a_quien_los_sigue() -> None:
    from crmcore.rutas_de_api import servicio_de

    assert servicio_de("/api/v1/portal/mi/encargos") == "integration"
    assert servicio_de("/api/v1/portal/mi/encargos/x/seguimiento") == "integration"


def test_los_niveles_con_empresa_anuncian_los_encargos() -> None:
    from services.service import portal as prt

    assert "encargos" in prt.SECCIONES_SERVIDAS
    assert "encargos" in prt.SECCIONES_POR_NIVEL["cuenta"]
    # El nivel «propio» no ve lo de su empresa: tampoco sus encargos.
    assert "encargos" not in prt.SECCIONES_POR_NIVEL["propio"]


# ── CRM-06.01.02.11: enviar el sobre por el operador de verdad ────────────


def test_enviar_por_el_operador_real_guarda_el_id_del_proveedor_crm_06_01_02_11(
    cliente: Any,
    uow: Any,
    tenant_id: UUID,
    contexto_tenant: UUID,
    proveedor_doble: list[httpx.Request],
) -> None:
    """El doble de la prueba anterior devolvía `{"id": …}` pelado y el operador
    de verdad devuelve lo que devuelve el conector, `{"registros": [...]}`. Con
    el de verdad el identificador del proveedor no se guardaba NUNCA."""
    from crmcore.security.cifrado import cifrar_dict

    from services.integration import firma as fir
    from services.integration.main import _operador_de_firma
    from services.integration.modelos import Credencial, Operacion

    conexion = _conexion(
        uow,
        nombre="Firma",
        config={"url_base": "https://firma.example/api", "auth_tipo": "bearer"},
    )
    uow.db.add(
        Credencial(
            tenant_id=tenant_id,
            conexion_id=conexion.id,
            valores=cifrar_dict({"token": "tk-firma"}),
        )
    )
    uow.db.add(
        Operacion(
            tenant_id=tenant_id,
            conexion_id=conexion.id,
            clave="crear_sobre",
            nombre="Crear sobre",
            definicion={
                "metodo": "POST",
                "ruta": "/envelopes",
                "cuerpo": {"subject": "{{asunto}}", "document": "{{documento_id}}"},
                "mapeo": {"id": "envelope_id"},
            },
        )
    )
    uow.db.add(
        fir.ProveedorFirma(
            tenant_id=tenant_id, clave="doble", nombre="Doble", conexion_id=conexion.id
        )
    )
    sobre = fir.Sobre(
        tenant_id=tenant_id,
        referencia="S-9",
        documento_id="doc-9",
        proveedor="doble",
        asunto="Contrato",
        caduca_at=datetime.now(timezone.utc) + timedelta(days=10),
    )
    uow.db.add(sobre)
    uow.db.flush()
    uow.db.add(
        fir.Firmante(
            tenant_id=tenant_id,
            sobre_id=sobre.id,
            nombre="Ana",
            email="ana@example.com",
            orden=0,
            papel="firmante",
        )
    )
    uow.db.flush()

    previo = fir._operador
    fir.registrar_operador(_operador_de_firma)
    try:
        salida = fir.enviar(uow, sobre.id)
    finally:
        fir._operador = previo

    assert salida["estado"] == "enviado"
    assert len(proveedor_doble) == 1
    peticion = proveedor_doble[0]
    assert peticion.headers["authorization"] == "Bearer tk-firma"
    assert json.loads(peticion.content)["subject"] == "Contrato"
    uow.db.refresh(sobre)
    assert sobre.referencia_externa == "env-77", sobre.referencia_externa


def test_el_id_externo_se_lee_venga_como_venga() -> None:
    from services.integration.firma import _id_externo

    assert _id_externo({"id": "a"}) == "a"
    assert _id_externo({"id_externo": "b"}) == "b"
    assert _id_externo({"registros": [{"id": "c"}], "paginas": 1}) == "c"
    assert _id_externo({"registros": []}) == ""
    assert _id_externo(None) == ""


# ── CRM-06.01.03.10: la reunión en línea, de verdad ───────────────────────

PERFIL_TEAMS = {
    "clase": "suite_productividad",
    "url_base": "https://graph.example/v1.0",
    "auth_tipo": "bearer",
    "token_url": "https://login.example/token",
    "recursos": {
        "reuniones": {
            "endpoint": "/users/{{organizador}}/onlineMeetings",
            "incremento": "completo",
            "cuerpo": {
                "subject": "{{asunto}}",
                "startDateTime": "{{inicio}}",
                "endDateTime": "{{fin}}",
                "participants": {"attendees": "{{asistentes}}"},
            },
            "asistente": {"upn": "{{email}}"},
            "campos": {"enlace": "joinWebUrl", "id_externo": "id"},
        }
    },
}


@pytest.fixture
def party_doble(monkeypatch: Any) -> dict[str, Any]:
    """`party`, doblado en la llamada interna: guarda lo que se le escribe."""
    from crmcore.http import interno

    estado: dict[str, Any] = {
        "actividad": {
            "id": str(uuid4()),
            "asunto": "Demo con el cliente",
            "inicio_at": "2026-11-20T10:00:00+00:00",
            "fin_at": "2026-11-20T11:00:00+00:00",
            "detalles": {"duracion": 60},
        },
        "llamadas": [],
    }

    def _invocar(**kw: Any) -> dict[str, Any]:
        estado["llamadas"].append(kw)
        if kw["metodo"] == "GET":
            return {"estado": 200, "ok": True, "datos": dict(estado["actividad"])}
        if kw["metodo"] == "PATCH":
            estado["actividad"]["detalles"] = kw["cuerpo"]["detalles"]
            return {"estado": 200, "ok": True, "datos": dict(estado["actividad"])}
        return {"estado": 201, "ok": True, "datos": {"id": "nueva", **(kw["cuerpo"] or {})}}

    monkeypatch.setattr(interno, "invocar", _invocar)
    return estado


def _suite_con_reuniones(uow: Any, usuario: UUID, *, consentida: bool = True) -> Any:
    from crmcore.security.cifrado import cifrar_dict

    from services.integration.modelos import Credencial
    from services.integration.suites import ConsentimientoSuite

    conexion = _conexion(uow, nombre="m365", config=PERFIL_TEAMS)
    conexion.sistema = "microsoft"
    uow.db.add(
        Credencial(
            tenant_id=uow.tenant_id,
            conexion_id=conexion.id,
            valores=cifrar_dict({"token": "tk-suite"}),
        )
    )
    if consentida:
        uow.db.add(
            ConsentimientoSuite(
                tenant_id=uow.tenant_id,
                usuario_id=usuario,
                perfil="m365",
                recurso="reuniones",
                sentido="escribir",
                concedido_at=datetime.now(timezone.utc),
                concedido_por=usuario,
            )
        )
    uow.db.flush()
    return conexion


def test_la_reunion_se_crea_en_el_proveedor_y_su_enlace_queda_en_la_actividad_crm_06_01_03_10(
    cliente: Any,
    cabeceras: dict[str, str],
    usuario: UUID,
    uow: Any,
    contexto_tenant: UUID,
    proveedor_doble: list[httpx.Request],
    party_doble: dict[str, Any],
) -> None:
    _suite_con_reuniones(uow, usuario)
    actividad_id = party_doble["actividad"]["id"]

    hay = cliente.get("/api/v1/suites/reuniones/proveedor", headers=cabeceras).json()
    assert hay == {"disponible": True, "perfil": "m365", "sistema": "microsoft"}

    r = cliente.post(
        "/api/v1/suites/reuniones",
        headers=cabeceras,
        json={
            "actividad_id": actividad_id,
            "confirmada": True,
            "asistentes": ["Cliente@Example.com"],
            "organizador": "ana@empresa.example",
        },
    )
    assert r.status_code == 200, r.text
    salida = r.json()
    assert salida["enlace"] == "https://reuniones.example/join/1"
    assert salida["guardada"] is True
    assert salida["actividad_id"] == actividad_id

    # Lo que salió al proveedor: su forma, con su credencial y en su ruta.
    assert len(proveedor_doble) == 1
    peticion = proveedor_doble[0]
    assert peticion.method == "POST"
    assert peticion.url.path == "/v1.0/users/ana@empresa.example/onlineMeetings"
    assert peticion.headers["authorization"] == "Bearer tk-suite"
    enviado = json.loads(peticion.content)
    assert enviado["subject"] == "Demo con el cliente"
    assert enviado["startDateTime"].startswith("2026-11-20T10:00")
    assert enviado["participants"]["attendees"] == [{"upn": "cliente@example.com"}]

    # Y el enlace, en la actividad, sin pisar lo que ya tenía.
    detalles = party_doble["actividad"]["detalles"]
    assert detalles["duracion"] == 60
    assert detalles["reunion"]["enlace"] == "https://reuniones.example/join/1"
    assert detalles["reunion"]["id_externo"] == "m-1"
    # Con la identidad de quien pulsa, no la de «la casa».
    patch = [c for c in party_doble["llamadas"] if c["metodo"] == "PATCH"][0]
    assert patch["principal_id"] == usuario
    assert patch["tipo"] == "usuario"

    # Una segunda sala para la misma reunión sería una sala huérfana.
    otra = cliente.post(
        "/api/v1/suites/reuniones",
        headers=cabeceras,
        json={"actividad_id": actividad_id, "confirmada": True},
    )
    assert otra.status_code == 409, otra.text
    assert len(proveedor_doble) == 1, "se ha creado otra sala en el proveedor"


def test_desde_el_registro_se_crea_la_actividad_con_el_enlace_crm_06_01_03_10(
    cliente: Any,
    cabeceras: dict[str, str],
    usuario: UUID,
    uow: Any,
    contexto_tenant: UUID,
    proveedor_doble: list[httpx.Request],
    party_doble: dict[str, Any],
) -> None:
    _suite_con_reuniones(uow, usuario)
    objeto_id = str(uuid4())
    r = cliente.post(
        "/api/v1/suites/reuniones",
        headers=cabeceras,
        json={
            "objeto": "oportunidad",
            "objeto_id": objeto_id,
            "asunto": "Revisión de la propuesta",
            "inicio": "2026-11-21T09:00:00+00:00",
            "fin": "2026-11-21T09:30:00+00:00",
            "confirmada": True,
        },
    )
    assert r.status_code == 200, r.text
    alta = [c for c in party_doble["llamadas"] if c["metodo"] == "POST"][0]
    assert alta["ruta"] == "/api/v1/activities"
    assert alta["cuerpo"]["tipo"] == "reunion"
    assert alta["cuerpo"]["objeto_id"] == objeto_id
    assert alta["cuerpo"]["detalles"]["reunion"]["enlace"] == "https://reuniones.example/join/1"
    assert r.json()["actividad_id"] == "nueva"


def test_sin_consentimiento_no_se_crea_ninguna_sala_crm_06_01_03_10(
    cliente: Any,
    cabeceras: dict[str, str],
    usuario: UUID,
    uow: Any,
    contexto_tenant: UUID,
    proveedor_doble: list[httpx.Request],
    party_doble: dict[str, Any],
) -> None:
    _suite_con_reuniones(uow, usuario, consentida=False)
    r = cliente.post(
        "/api/v1/suites/reuniones",
        headers=cabeceras,
        json={"actividad_id": party_doble["actividad"]["id"], "confirmada": True},
    )
    assert r.status_code == 403, r.text
    assert proveedor_doble == []


def test_sin_suite_conectada_se_dice_por_que_crm_06_01_03_10(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    hay = cliente.get("/api/v1/suites/reuniones/proveedor", headers=cabeceras).json()
    assert hay["disponible"] is False
    assert hay["codigo"] == "suite.sin_proveedor_de_reuniones"
    assert hay["motivo"]


def test_declarar_una_operacion_por_la_api_no_revienta(
    cliente: Any, cabeceras: dict[str, str], uow: Any, contexto_tenant: UUID
) -> None:
    """La respuesta tipaba `estado_transporte` como texto y la fila nueva trae
    `{}`: declarar una operación —sin la que no hay nada que probar— daba 500
    siempre. Salió al montar la prueba de «Probar la conexión»."""
    conexion = _conexion(uow, nombre="Con operación", config={"url_base": "https://x.example"})
    r = cliente.post(
        f"/api/v1/integraciones/conexiones/{conexion.id}/operaciones",
        headers=cabeceras,
        json={"clave": "leer", "nombre": "Leer", "definicion": {"metodo": "GET", "ruta": "/a"}},
    )
    assert r.status_code == 201, r.text
    datos = cliente.get(
        f"/api/v1/integraciones/conexiones/{conexion.id}/credenciales", headers=cabeceras
    ).json()
    assert datos["se_puede_probar"] is True
