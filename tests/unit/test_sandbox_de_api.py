"""El sandbox de API crea un entorno, lo llena y da una clave que sólo lo abre a él.

CRM-00.02.01.15. Hasta el 09-11-2026 `POST /integracion/sandbox` devolvía un
diccionario —«se crearía un entorno, caduca tal día»— y no creaba nada.

Lo que se fija aquí:

- Los datos salen **del contrato** y el servicio los acepta: se generan del
  esquema del `POST` publicado y se mandan al servicio de verdad.
- Lo que se genera después cuelga de lo generado antes, por el nombre con que
  el contrato llama a su identificador (`/accounts/{cuenta_id}`).
- **Todo lo que se escribe dentro del sandbox va al tenant del sandbox**, la
  credencial incluida. Una sola llamada con el tenant real y la clave abriría
  los datos de la empresa.
"""

from __future__ import annotations

import importlib
import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.authz.principal import Principal
from crmcore.http.deps import H_TENANT, H_TIPO

from services.gateway import sandbox_api


@pytest.fixture(scope="module")
def contrato_party() -> dict[str, Any]:
    return importlib.import_module("services.party.main").app.openapi()


def test_el_alias_del_identificador_sale_de_la_ruta_de_la_ficha(
    contrato_party: dict[str, Any],
) -> None:
    assert sandbox_api.alias_del_identificador(contrato_party, "/api/v1/accounts") == "cuenta_id"
    assert sandbox_api.alias_del_identificador(contrato_party, "/api/v1/contacts") == "contacto_id"


def test_el_cuerpo_rellena_lo_obligatorio_los_correos_y_las_referencias(
    contrato_party: dict[str, Any],
) -> None:
    esquema = sandbox_api.esquema_de_alta(contrato_party, "/api/v1/contacts")
    assert esquema is not None
    cuerpo = sandbox_api.cuerpo_sintetico(
        esquema, contrato_party, 0, semilla="s", referencias={"cuenta_id": ["c1"]}
    )
    assert cuerpo["nombre"]
    assert "@" in cuerpo["email"]
    assert cuerpo["cuenta_id"] == "c1"
    # Lo opcional que no es correo ni referencia se deja vacío: también hay que
    # poder probar un contacto sin cargo.
    assert "cargo" not in cuerpo
    # Y el mismo índice con la misma semilla da lo mismo: un sandbox que se
    # regenera no cambia de nombres a cada vuelta.
    otra = sandbox_api.cuerpo_sintetico(
        esquema, contrato_party, 0, semilla="s", referencias={"cuenta_id": ["c1"]}
    )
    assert otra == cuerpo


def test_una_coleccion_sin_alta_no_tiene_esquema(contrato_party: dict[str, Any]) -> None:
    assert sandbox_api.esquema_de_alta(contrato_party, "/api/v1/accounts/sin-contacto") is None


@pytest.mark.db
def test_el_servicio_acepta_lo_generado(db: Any, tenant_id: UUID) -> None:
    """Generado del contrato y mandado al servicio de verdad: 201."""
    from crmcore.config import get_settings
    from crmcore.http.deps import H_PERMISOS, H_ROLES, H_USER, firmar_cabeceras_internas
    from starlette.testclient import TestClient

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        app = importlib.import_module("services.party.main").app
        documento = app.openapi()
        cabeceras = firmar_cabeceras_internas(
            {
                H_TENANT: str(tenant_id),
                H_USER: str(uuid4()),
                H_TIPO: "servicio",
                H_PERMISOS: "*:*",
                H_ROLES: "admin",
            },
            get_settings().secret_key.get_secret_value(),
        )
        referencias: dict[str, list[str]] = {}
        with TestClient(app) as cliente:
            for ruta in ("/api/v1/accounts", "/api/v1/contacts", "/api/v1/activities"):
                esquema = sandbox_api.esquema_de_alta(documento, ruta)
                assert esquema is not None
                ids = []
                for i in range(2):
                    cuerpo = sandbox_api.cuerpo_sintetico(
                        esquema, documento, i, semilla="prueba", referencias=referencias
                    )
                    r = cliente.post(ruta, json=cuerpo, headers=cabeceras)
                    assert r.status_code == 201, (ruta, cuerpo, r.text)
                    ids.append(r.json()["id"])
                alias = sandbox_api.alias_del_identificador(documento, ruta)
                if alias:
                    referencias[alias] = ids
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


# ── El sandbox entero, con un doble de los servicios ─────────────────────


class _Respuesta:
    def __init__(self, status: int, cuerpo: Any) -> None:
        self.status_code = status
        self._cuerpo = cuerpo
        self.content = b"x"
        self.text = str(cuerpo)

    def json(self) -> Any:
        return self._cuerpo


class _Destino:
    def __init__(self, nombre: str) -> None:
        self.url_base = f"http://{nombre}"


class _Doble:
    """Contesta como tenancy, party e identity, y apunta con qué tenant se llamó."""

    def __init__(self, contrato: dict[str, Any], hijo: UUID) -> None:
        self.contrato = contrato
        self.hijo = hijo
        self.llamadas: list[tuple[str, str, dict[str, str], Any]] = []

    async def get(self, url: str, **_: Any) -> _Respuesta:
        self.llamadas.append(("GET", url, {}, None))
        return _Respuesta(200, self.contrato)

    async def post(self, url: str, *, json: Any, headers: dict[str, str], **_: Any) -> _Respuesta:
        self.llamadas.append(("POST", url, headers, json))
        if url.endswith("/sandboxes"):
            return _Respuesta(201, {"id": str(uuid4()), "tenant_sandbox_id": str(self.hijo)})
        if url.endswith("/claves-api"):
            return _Respuesta(
                201,
                {
                    "id": str(uuid4()),
                    "prefijo": "crm_abc",
                    "secreto": "crm_abcdef",
                    "expira_at": None,
                },
            )
        return _Respuesta(201, {"id": str(uuid4()), **json})


async def test_todo_lo_de_dentro_va_al_tenant_del_sandbox_y_la_clave_tambien(
    contrato_party: dict[str, Any],
) -> None:
    real, hijo = uuid4(), uuid4()
    doble = _Doble(contrato_party, hijo)
    quien = Principal(
        id=uuid4(),
        tenant_id=real,
        permisos=frozenset({"*:*"}),
        factor_fuerte_at=datetime.now(timezone.utc).isoformat(),
    )
    hecho = await sandbox_api.crear(
        cliente=doble,
        destinos={n: _Destino(n) for n in ("tenancy", "party", "identity")},
        principal=quien,
        nombre="Integración ERP",
        objetos=["accounts", "contacts"],
        filas_por_objeto=3,
    )

    assert hecho["filas"] == 6
    assert hecho["credencial"]["secreto"] == "crm_abcdef"
    posts = [c for c in doble.llamadas if c[0] == "POST"]
    # El entorno se pide con la identidad de quien lo pide, en su tenant.
    assert posts[0][1].endswith("/sandboxes")
    assert posts[0][2][H_TENANT] == str(real)
    # Y TODO lo demás —datos y credencial— en el del sandbox, como servicio.
    for _, url, cabeceras, _cuerpo in posts[1:]:
        assert cabeceras[H_TENANT] == str(hijo), url
        assert cabeceras[H_TIPO] == "servicio"
    # Los contactos cuelgan de las cuentas generadas.
    contactos = [c[3] for c in posts if c[1].endswith("/contacts")]
    assert all(c.get("cuenta_id") for c in contactos)


async def test_una_coleccion_que_no_existe_se_dice_y_no_tumba_el_resto(
    contrato_party: dict[str, Any],
) -> None:
    doble = _Doble(contrato_party, uuid4())
    hecho = await sandbox_api.crear(
        cliente=doble,
        destinos={n: _Destino(n) for n in ("tenancy", "party", "identity")},
        principal=Principal(id=uuid4(), tenant_id=uuid4(), permisos=frozenset({"*:*"})),
        nombre="x",
        objetos=["accounts", "no-existe-esto"],
        filas_por_objeto=1,
    )
    por = {o["objeto"]: o for o in hecho["objetos"]}
    assert por["accounts"]["creadas"] == 1
    assert por["no-existe-esto"]["creadas"] == 0 and por["no-existe-esto"]["error"]


# ── Por la ruta del gateway, que es como lo pide la consola ──────────────


def test_por_la_ruta_del_gateway_devuelve_lo_que_pinta_la_consola(
    contrato_party: dict[str, Any], monkeypatch: Any
) -> None:
    """`POST /api/v1/integracion/sandbox` con los servicios de detrás simulados
    por HTTP: la respuesta trae lo que la pantalla lee —objetos con creadas y
    pedidas, la credencial, la caducidad— y nada se escribe en el tenant real."""
    import json

    import httpx
    from crmcore.config import get_settings
    from crmcore.http.deps import H_PERMISOS, H_ROLES, H_USER, firmar_cabeceras_internas
    from starlette.testclient import TestClient

    from services.gateway import api as gw

    real, hijo = uuid4(), uuid4()
    tenants_vistos: list[tuple[str, str]] = []

    def responder(peticion: httpx.Request) -> httpx.Response:
        ruta = peticion.url.path
        tenants_vistos.append((ruta, peticion.headers.get(H_TENANT.lower(), "")))
        if peticion.method == "GET" and ruta.endswith("/openapi.json"):
            return httpx.Response(200, json=contrato_party)
        if ruta.endswith("/sandboxes"):
            return httpx.Response(201, json={"id": str(uuid4()), "tenant_sandbox_id": str(hijo)})
        if ruta.endswith("/claves-api"):
            return httpx.Response(
                201,
                json={
                    "id": str(uuid4()),
                    "prefijo": "crm_x",
                    "secreto": "crm_xyz",
                    "expira_at": None,
                },
            )
        return httpx.Response(201, json={"id": str(uuid4()), **json.loads(peticion.content)})

    app = importlib.import_module("services.gateway.main").app
    with TestClient(app) as cliente:
        monkeypatch.setattr(
            gw, "_cliente", httpx.AsyncClient(transport=httpx.MockTransport(responder))
        )
        monkeypatch.setattr(
            gw,
            "_destinos",
            {
                n: type("D", (), {"url_base": f"http://{n}"})()
                for n in ("tenancy", "party", "identity")
            },
        )
        cabeceras = firmar_cabeceras_internas(
            {H_TENANT: str(real), H_USER: str(uuid4()), H_PERMISOS: "*:*", H_ROLES: "admin"},
            get_settings().secret_key.get_secret_value(),
        )
        r = cliente.post(
            "/api/v1/integracion/sandbox",
            json={"nombre": "ERP", "objetos": ["accounts", "contacts"], "filas_por_objeto": 2},
            headers=cabeceras,
        )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["filas"] == 4
    assert cuerpo["credencial"]["secreto"] == "crm_xyz"
    assert cuerpo["caduca_at"]
    assert {o["objeto"]: (o["creadas"], o["pedidas"]) for o in cuerpo["objetos"]} == {
        "accounts": (2, 2),
        "contacts": (2, 2),
    }
    escrituras = [t for ruta, t in tenants_vistos if not ruta.endswith("/openapi.json")]
    assert escrituras[0] == str(real)  # el alta del sandbox, como quien lo pide
    assert set(escrituras[1:]) == {str(hijo)}  # todo lo demás, dentro
