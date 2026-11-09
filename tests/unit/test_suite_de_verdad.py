"""La suite de verdad: avisos al chat que salen, consultas que contestan,
reuniones que quedan registradas y referencias guardadas
(CRM-06.01.01.03, .04 · CRM-06.01.03.08, .09, .12, .18).

Hasta el 09-11-2026 todo esto eran funciones que componían un diccionario y no
llamaban a nadie. Estas pruebas miran lo que sale y lo que queda guardado: el
POST que llega al webhook del canal (un servidor HTTP de verdad en un puerto),
la identidad con la que se pregunta al servicio dueño, la actividad que se pide
a `party` con sus asistentes y la referencia que se puede listar, abrir y
quitar por HTTP.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.db.uow import UnidadDeTrabajo
from starlette.testclient import TestClient

from services.integration import buzon as buz
from services.integration import colaboracion as colab

pytestmark = pytest.mark.db


# ── El otro lado: un servidor que apunta lo que recibe ────────────────────


class _Remoto:
    def __init__(self) -> None:
        self.recibido: list[tuple[str, dict[str, Any]]] = []
        self.respuesta: dict[str, Any] = {}


@pytest.fixture
def remoto() -> Iterator[tuple[str, _Remoto]]:
    estado = _Remoto()

    class Manejador(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_: Any) -> None:
            return

        def do_POST(self) -> None:  # noqa: N802
            largo = int(self.headers.get("Content-Length") or 0)
            cuerpo = json.loads(self.rfile.read(largo) or b"{}") if largo else {}
            estado.recibido.append((self.path, cuerpo))
            crudo = json.dumps(estado.respuesta or {"ok": True}).encode()
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
    """El servicio con sus rutas de chat y de referencias, sin bus.

    El guard de SSRF no se apaga: se le declara el host local, que es el
    mecanismo que existe para un servicio en la red del cliente.
    """
    from crmcore.config import get_settings
    from crmcore.service import crear_servicio

    from services.integration.api_buzon import ROUTERS_BUZON
    from services.integration.api_referencias import ROUTERS_REFERENCIAS

    monkeypatch.setenv("URL_GUARD_HOSTS_PERMITIDOS", "127.0.0.1")
    get_settings.cache_clear()
    app = crear_servicio(
        nombre="integration",
        descripcion="integration para la suite de verdad",
        routers=[*ROUTERS_BUZON, *ROUTERS_REFERENCIAS],
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


# ── Avisos al chat (CRM-06.01.01.03) ──────────────────────────────────────


def test_el_aviso_llega_al_webhook_del_canal_y_queda_constancia(
    cliente: TestClient, cabeceras: dict[str, str], remoto: tuple[str, _Remoto]
) -> None:
    """Antes se componía y no salía. Ahora el POST llega, con el texto y el
    enlace dentro, y el canal guarda que llegó."""
    url, estado = remoto
    clave = f"ventas-{uuid4().hex[:6]}"
    alta = cliente.post(
        "/api/v1/canales-chat",
        headers=cabeceras,
        json={
            "clave": clave,
            "url_entrante": f"{url}/hook",
            "secreto": "un-secreto-largo",
            "recibe_avisos": True,
        },
    )
    assert alta.status_code == 201, alta.text
    assert alta.json()["recibe_avisos"] is True

    registro = uuid4()
    r = cliente.post(
        f"/api/v1/canales-chat/{clave}/aviso",
        headers=cabeceras,
        json={
            "texto": "Oportunidad ganada",
            "objeto": "oportunidad",
            "objeto_id": str(registro),
            "enlace": f"https://crm.ejemplo/abrir/oportunidad/{registro}",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["enviado"] is True
    assert estado.recibido == [
        ("/hook", {"text": f"Oportunidad ganada https://crm.ejemplo/abrir/oportunidad/{registro}"})
    ]

    # La clave sale enmascarada para quien no tiene permiso de verla en claro:
    # se busca por lo que no lo está.
    canales = cliente.get("/api/v1/canales-chat", headers=cabeceras).json()["items"]
    assert [c["ultimo_aviso_ok"] for c in canales if c["recibe_avisos"]] == [True]

    # La ficha del canal llama a sus acciones con el id del registro, no con la
    # clave: también tiene que llegar.
    por_id = cliente.post(
        f"/api/v1/canales-chat/{alta.json()['id']}/aviso",
        headers=cabeceras,
        json={"texto": "Desde la ficha"},
    )
    assert por_id.status_code == 200, por_id.text
    assert estado.recibido[-1] == ("/hook", {"text": "Desde la ficha "})


def test_un_canal_que_no_contesta_queda_marcado_y_no_se_da_por_enviado(
    uow_: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    colab.declarar_canal(
        uow_, clave="caido", url_entrante="http://127.0.0.1:9/no", secreto="un-secreto-largo"
    )
    salida = colab.mandar_aviso(
        uow_.db,
        uow_.tenant_id,
        clave="caido",
        texto="Hola",
        postear=lambda *_a, **_k: (False, "HTTP 500"),
    )
    assert salida["enviado"] is False
    canal = colab.canal_por_clave(uow_.db, uow_.tenant_id, "caido")
    assert canal.ultimo_aviso_ok is False
    assert canal.ultimo_aviso_detalle == "HTTP 500"


def test_los_avisos_de_automatizacion_van_solo_a_los_canales_que_los_reciben(
    uow_: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    for clave, recibe in (("si", True), ("no", False)):
        colab.declarar_canal(
            uow_,
            clave=clave,
            url_entrante=f"https://chat.ejemplo/{clave}",
            secreto="un-secreto-largo",
            recibe_avisos=recibe,
        )
    mandados: list[str] = []

    def postear(url: str, cuerpo: dict[str, Any], **_: Any) -> tuple[bool, str]:
        mandados.append(url)
        return True, "HTTP 200"

    salida = colab.avisar_a_los_canales(uow_.db, uow_.tenant_id, texto="Aviso", postear=postear)
    assert salida == {"canales": 1, "enviados": 1, "fallidos": []}
    assert mandados == ["https://chat.ejemplo/si"]


def test_el_enlace_sale_de_la_direccion_publica_configurada(monkeypatch: Any) -> None:
    from services.integration import ajustes

    monkeypatch.setattr(ajustes, "valor", lambda clave, db=None: "https://crm.ejemplo/")
    rid = uuid4()
    assert (
        colab.enlace_al_registro(None, "cuenta", rid) == f"https://crm.ejemplo/abrir/cuenta/{rid}"
    )
    monkeypatch.setattr(ajustes, "valor", lambda clave, db=None: "")
    # Sin dirección no se inventa: vacío, y el aviso de un registro se rechaza.
    assert colab.enlace_al_registro(None, "cuenta", rid) == ""


# ── La consulta desde el chat, con los permisos de quien pregunta ────────


def test_la_consulta_contesta_con_la_identidad_de_quien_pregunta(monkeypatch: Any) -> None:
    tenant = uuid4()
    usuario = str(uuid4())
    rid = uuid4()
    llamadas: list[dict[str, Any]] = []
    monkeypatch.setattr(colab, "_COLECCIONES", {"oportunidad": "/api/v1/opportunities"})

    def invocar(**kw: Any) -> dict[str, Any]:
        llamadas.append(kw)
        return {
            "ok": True,
            "estado": 200,
            "datos": {"nombre": "Renovación", "estado": "abierta", "importe": "1200", "notas": "x"},
        }

    salida = colab.contestar_consulta(
        tenant,
        objeto="oportunidad",
        objeto_id=rid,
        usuario_externo="Ana@Empresa.com",
        pedir_alcance=lambda t, c: {
            "usuario_id": usuario,
            "permisos": ["opportunity:read"],
            "roles": ["comercial"],
        },
        invocar=invocar,
    )
    assert salida["hecho"] is True
    assert salida["datos"] == {"nombre": "Renovación", "estado": "abierta", "importe": "1200"}
    assert llamadas[0]["ruta"] == f"/api/v1/opportunities/{rid}"
    assert llamadas[0]["principal_id"] == usuario
    assert llamadas[0]["permisos"] == ["opportunity:read"]


def test_sin_saber_quien_pregunta_no_se_contesta_con_datos() -> None:
    def invocar(**_: Any) -> dict[str, Any]:  # pragma: no cover - no debe llamarse
        raise AssertionError("no se pregunta al servicio dueño")

    sin_correo = colab.contestar_consulta(
        uuid4(), objeto="cuenta", objeto_id=uuid4(), usuario_externo="U123", invocar=invocar
    )
    assert sin_correo["hecho"] is False and "datos" not in sin_correo
    desconocido = colab.contestar_consulta(
        uuid4(),
        objeto="cuenta",
        objeto_id=uuid4(),
        usuario_externo="nadie@fuera.com",
        pedir_alcance=lambda t, c: None,
        invocar=invocar,
    )
    assert desconocido["hecho"] is False and "datos" not in desconocido


# ── Reuniones del calendario (CRM-06.01.01.04) ────────────────────────────


@pytest.fixture
def uow_(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def test_la_cita_sincronizada_se_registra_como_reunion_con_sus_asistentes(
    uow_: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    buzon = buz.conectar(
        uow_,
        usuario_id=uuid4(),
        perfil="calendario-generico",
        direccion="comercial@empresa.com",
        ambito="calendario",
        criterio="todo",
    )
    buz.marcar_autorizado(uow_, buzon_id=buzon.id)
    buz.sincronizar(
        uow_,
        buzon_id=buzon.id,
        elementos=[
            {
                "id": "ev-1",
                "asunto": "Revisión trimestral",
                "ocurrido_at": datetime(2026, 11, 9, 10, tzinfo=timezone.utc),
                "participantes": ["ana@cliente.com", "Interno@empresa.com"],
            }
        ],
    )
    contacto = str(uuid4())
    actividad = str(uuid4())
    pedido: list[dict[str, Any]] = []

    def invocar(**kw: Any) -> dict[str, Any]:
        pedido.append(kw)
        if kw["metodo"] == "GET":
            assert "ana@cliente.com" in kw["parametros"]["email__en"]
            return {
                "ok": True,
                "datos": {
                    "items": [
                        {"id": contacto, "email": "ana@cliente.com", "nombre_completo": "Ana"}
                    ]
                },
            }
        return {"ok": True, "estado": 201, "datos": {"id": actividad}}

    identidad = {
        "tenant_id": uow_.tenant_id,
        "principal_id": uuid4(),
        "permisos": ["activity:write"],
    }
    salida = buz.registrar_reuniones(uow_, buzon_id=buzon.id, identidad=identidad, invocar=invocar)
    assert salida["creadas"] == 1
    cuerpo = pedido[-1]["cuerpo"]
    assert cuerpo["tipo"] == "reunion"
    assert cuerpo["contacto_id"] == contacto
    asistentes = {a["email"]: a["contacto_id"] for a in cuerpo["detalles"]["asistentes"]}
    assert asistentes == {"ana@cliente.com": contacto, "interno@empresa.com": None}
    # Con la identidad de quien sincroniza, no la de la casa.
    assert pedido[-1]["principal_id"] == identidad["principal_id"]
    # Y la segunda vuelta no la crea otra vez.
    assert (
        buz.registrar_reuniones(uow_, buzon_id=buzon.id, identidad=identidad, invocar=invocar)[
            "creadas"
        ]
        == 0
    )


def test_una_reunion_que_party_rechaza_queda_en_error_y_se_reintenta(
    uow_: UnidadDeTrabajo, contexto_tenant: UUID
) -> None:
    buzon = buz.conectar(
        uow_,
        usuario_id=uuid4(),
        perfil="calendario-generico",
        direccion="otra@empresa.com",
        ambito="calendario",
        criterio="todo",
    )
    buz.marcar_autorizado(uow_, buzon_id=buzon.id)
    buz.sincronizar(uow_, buzon_id=buzon.id, elementos=[{"id": "ev-2", "participantes": []}])

    def falla(**kw: Any) -> dict[str, Any]:
        return {"ok": False, "estado": 403, "datos": {"mensaje": "sin permiso"}}

    salida = buz.registrar_reuniones(uow_, buzon_id=buzon.id, identidad={}, invocar=falla)
    assert salida == {"creadas": 0, "errores": 1, "reuniones": []}

    def bien(**kw: Any) -> dict[str, Any]:
        return {"ok": True, "estado": 201, "datos": {"id": str(uuid4())}}

    assert (
        buz.registrar_reuniones(uow_, buzon_id=buzon.id, identidad={}, invocar=bien)["creadas"] == 1
    )


def test_sincronizar_por_http_con_la_fecha_en_texto_no_revienta(
    cliente: TestClient, cabeceras: dict[str, str]
) -> None:
    """Por HTTP la fecha llega como texto: se guardaba tal cual y la respuesta
    daba 500 en cada sincronización. Y si party no contesta, la cita queda en
    error para reintentarla, no registrada."""
    alta = cliente.post(
        "/api/v1/buzones",
        headers=cabeceras,
        json={
            "usuario_id": str(uuid4()),
            "perfil": "calendario-generico",
            "direccion": "http@empresa.com",
            "ambito": "calendario",
            "criterio": "todo",
        },
    )
    assert alta.status_code == 201, alta.text
    bid = alta.json()["id"]
    assert cliente.post(f"/api/v1/buzones/{bid}/autorizado", headers=cabeceras).status_code == 200
    r = cliente.post(
        f"/api/v1/buzones/{bid}/sincronizar",
        headers=cabeceras,
        json={
            "elementos": [
                {"id": "ev-http", "asunto": "Visita", "ocurrido_at": "2026-11-09T10:00:00Z"}
            ]
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["registrados"] == 1
    assert r.json()["reuniones"]["creadas"] == 0
    assert r.json()["reuniones"]["errores"] == 1


# ── Referencias de la suite (CRM-06.01.03.08, .09, .12) ───────────────────


def test_la_referencia_se_guarda_se_lista_se_abre_y_se_quita(
    cliente: TestClient, cabeceras: dict[str, str]
) -> None:
    """Sin perfil que sepa comprobarla, se dice que no se puede comprobar:
    nunca que es accesible."""
    registro = str(uuid4())
    alta = cliente.post(
        "/api/v1/referencias-suite",
        headers=cabeceras,
        json={
            "tipo": "fichero",
            "objeto": "cuenta",
            "objeto_id": registro,
            "referencia": "https://almacen.ejemplo/doc/42",
            "nombre": "Contrato marco.pdf",
        },
    )
    assert alta.status_code == 201, alta.text
    rid = alta.json()["id"]

    lista = cliente.get(
        "/api/v1/referencias-suite",
        headers=cabeceras,
        params={"objeto": "cuenta", "objeto_id": registro},
    )
    assert [r["nombre"] for r in lista.json()["referencias"]] == ["Contrato marco.pdf"]

    abierta = cliente.post(f"/api/v1/referencias-suite/{rid}/abrir", headers=cabeceras).json()
    assert abierta["estado"] == "no_comprobable"
    assert abierta["ver"] is None

    assert cliente.delete(f"/api/v1/referencias-suite/{rid}", headers=cabeceras).status_code == 200
    vacia = cliente.get(
        "/api/v1/referencias-suite",
        headers=cabeceras,
        params={"objeto": "cuenta", "objeto_id": registro},
    )
    assert vacia.json()["referencias"] == []


def test_la_conversacion_se_guarda_con_su_resumen_y_sin_mensajes(
    cliente: TestClient, cabeceras: dict[str, str]
) -> None:
    r = cliente.post(
        "/api/v1/referencias-suite",
        headers=cabeceras,
        json={
            "tipo": "conversacion",
            "objeto": "oportunidad",
            "objeto_id": str(uuid4()),
            "referencia": "hilo-123",
            "nombre": "Negociación del precio",
            "resumen": "Acordado un 5 % si firman este mes",
            "exportable": False,
        },
    )
    assert r.status_code == 201, r.text
    detalle = r.json()["detalle"]
    assert detalle["resumen"] == "Acordado un 5 % si firman este mes"
    assert detalle["exportable"] is False and "no deja exportar" in detalle["aviso"]


def test_una_nota_sin_referencia_no_se_guarda(
    cliente: TestClient, cabeceras: dict[str, str]
) -> None:
    r = cliente.post(
        "/api/v1/referencias-suite",
        headers=cabeceras,
        json={"tipo": "nota", "objeto": "cuenta", "objeto_id": str(uuid4()), "referencia": " "},
    )
    assert r.status_code == 422


def test_el_origen_dice_sin_acceso_y_no_se_da_el_enlace(
    cliente: TestClient,
    cabeceras: dict[str, str],
    remoto: tuple[str, _Remoto],
    db: Any,
    tenant_id: UUID,
) -> None:
    """Los permisos se resuelven en el origen: si dice que no, no se ve."""
    from services.integration.modelos import Conexion, Operacion

    url, estado = remoto
    estado.respuesta = {"existe": True, "tiene_acceso": False}
    nombre = f"suite-{uuid4().hex[:6]}"
    conexion = Conexion(
        tenant_id=tenant_id,
        nombre=nombre,
        protocolo="rest",
        config={"clase": "suite_productividad", "url_base": url, "auth_tipo": "ninguna"},
    )
    db.add(conexion)
    db.flush()
    db.add(
        Operacion(
            tenant_id=tenant_id,
            conexion_id=conexion.id,
            clave="resolver_referencia",
            nombre="Resolver",
            definicion={"metodo": "POST", "ruta": "/resolver", "cuerpo": {"ref": "{{referencia}}"}},
        )
    )
    db.commit()

    alta = cliente.post(
        "/api/v1/referencias-suite",
        headers=cabeceras,
        json={
            "tipo": "nota",
            "objeto": "contacto",
            "objeto_id": str(uuid4()),
            "referencia": "nota-77",
            "nombre": "Acta de la visita",
            "perfil": nombre,
        },
    )
    assert alta.status_code == 201, alta.text
    abierta = cliente.post(
        f"/api/v1/referencias-suite/{alta.json()['id']}/abrir", headers=cabeceras
    ).json()
    assert abierta["estado"] == "sin_acceso"
    assert abierta["ver"] is False
    assert abierta.get("url") is None
    assert estado.recibido[-1] == ("/resolver", {"ref": "nota-77"})


# ── El registro de tratamiento (CRM-06.01.03.18) ──────────────────────────


def test_lo_que_ahora_se_guarda_tiene_su_tratamiento_declarado() -> None:
    import importlib

    from crmcore import cumplimiento

    from services.integration import tratamientos

    # Otras pruebas limpian el registro: se vuelve a declarar como al arrancar.
    importlib.reload(tratamientos)
    for objeto in ("llamadas_telefonicas", "hechos_compensacion", "referencias_suite"):
        t = cumplimiento._tratamientos[objeto]
        assert t.finalidad and t.base_legal and t.plazo
