"""El gobierno de la suite **por HTTP y contra una herramienta que contesta**.

`test_suite.py` prueba las funciones. Esto prueba lo otro: que la petición
entra por la ruta, que el permiso deja pasar, que el conector sale a la red de
verdad y que lo que vuelve se puede leer. Es la diferencia entre «está hecho» y
«se ha visto funcionar», y hoy esa diferencia ha costado ocho rutas inalcanzables
y dos pantallas que no pintaban lo que el servidor ya mandaba.

La herramienta del otro lado es un **servidor HTTP de verdad** en un puerto, no
un doble: el conector abre un socket, negocia, manda cabeceras y lee el cuerpo.
Un doble de `httpx` habría dado por buena la parte que aquí falla —la de entrar
con usuario y contraseña antes de leer—, porque el doble contesta a todo.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

from services.tenancy.modelos import Tenant, UnidadNegocio

pytestmark = pytest.mark.db


# ── La herramienta del otro lado ──────────────────────────────────────────


class _Estado:
    """Lo que la herramienta remota sabe de sí misma, para poder preguntárselo."""

    def __init__(self) -> None:
        self.peticiones: list[tuple[str, str, dict[str, Any], dict[str, str]]] = []
        self.usuarios: dict[str, dict[str, Any]] = {}
        self.tokens_emitidos = 0
        self.validos: set[str] = set()
        self.exigir_token = True


def _manejador(estado: _Estado) -> type[BaseHTTPRequestHandler]:
    class Manejador(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_: Any) -> None:  # silencio: la salida es de pytest
            return

        def _cuerpo(self) -> dict[str, Any]:
            largo = int(self.headers.get("Content-Length") or 0)
            if not largo:
                return {}
            try:
                return json.loads(self.rfile.read(largo) or b"{}")
            except json.JSONDecodeError:
                return {}

        def _responder(self, codigo: int, cuerpo: Any) -> None:
            crudo = json.dumps(cuerpo).encode()
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(crudo)))
            self.end_headers()
            self.wfile.write(crudo)

        def _autorizado(self) -> bool:
            """Comprueba el token, no que venga uno.

            La primera versión daba por buena cualquier cabecera que empezara
            por `Bearer`, y con eso una credencial inventada entraba: la prueba
            de la cuarentena pasaba por el camino del éxito y no apartaba nada.
            Una herramienta de mentira que dice que sí a todo no prueba nada.
            """
            if not estado.exigir_token:
                return True
            cabecera = self.headers.get("Authorization", "")
            return cabecera.removeprefix("Bearer ") in estado.validos

        def _atender(self, metodo: str) -> None:
            cuerpo = self._cuerpo()
            estado.peticiones.append((metodo, self.path, cuerpo, dict(self.headers)))

            if self.path == "/entrar":
                estado.tokens_emitidos += 1
                emitido = f"vale-{estado.tokens_emitidos}"
                estado.validos.add(emitido)
                self._responder(200, {"access_token": emitido})
                return

            if not self._autorizado():
                self._responder(401, {"detail": "hace falta entrar"})
                return

            if self.path == "/listar/usuarios":
                self._responder(200, {"items": list(estado.usuarios.values())})
                return

            if self.path.startswith("/usuarios/"):
                ident = self.path.rsplit("/", 1)[-1]
                if metodo == "DELETE":
                    estado.usuarios.pop(ident, None)
                    self._responder(204, {})
                    return
                estado.usuarios[ident] = {"id_externo": ident, **cuerpo}
                self._responder(200, {"id": f"remoto-{ident[:8]}"})
                return

            if self.path.startswith(("/organizaciones/", "/unidades/")):
                self._responder(200, {"id": f"remoto-{self.path.rsplit('/', 1)[-1][:8]}"})
                return

            self._responder(404, {"detail": "no existe"})

        def do_GET(self) -> None:  # noqa: N802 — lo impone BaseHTTPRequestHandler
            self._atender("GET")

        def do_PUT(self) -> None:  # noqa: N802
            self._atender("PUT")

        def do_POST(self) -> None:  # noqa: N802
            self._atender("POST")

        def do_DELETE(self) -> None:  # noqa: N802
            self._atender("DELETE")

    return Manejador


@pytest.fixture
def herramienta_remota() -> Iterator[tuple[str, _Estado]]:
    estado = _Estado()
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), _manejador(estado))
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    try:
        yield f"http://127.0.0.1:{servidor.server_address[1]}", estado
    finally:
        servidor.shutdown()
        servidor.server_close()
        hilo.join(timeout=5)


# ── El servicio de este lado ──────────────────────────────────────────────


@pytest.fixture
def entorno(monkeypatch: Any) -> Iterator[None]:
    """Cifrado puesto y el guard admitiendo el servidor local.

    El guard **no se apaga**: se le declara el host, que es exactamente el
    mecanismo que existe para el IdP o el ERP en la red interna del cliente. Si
    se apagara, esta prueba dejaría de cubrir la ruta por la que pasan las de
    verdad.
    """
    from crmcore.config import get_settings

    monkeypatch.setenv("ENCRYPTION_KEY", "maestra-de-pruebas-suficientemente-larga")
    monkeypatch.setenv("URL_GUARD_HOSTS_PERMITIDOS", "127.0.0.1")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def cliente(entorno: None) -> Iterator[TestClient]:
    from crmcore.service import crear_servicio

    from services.tenancy.api import ROUTERS

    app = crear_servicio(
        nombre="tenancy",
        descripcion="tenancy para el gobierno de la suite",
        routers=ROUTERS,
        necesita_bus=False,
    )
    with TestClient(app) as cli:
        yield cli


@pytest.fixture
def cabeceras(tenant_id: UUID) -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import H_PERMISOS, H_TENANT, H_USER, firmar_cabeceras_internas

    return firmar_cabeceras_internas(
        {H_TENANT: str(tenant_id), H_USER: str(uuid4()), H_PERMISOS: "*:*"},
        get_settings().secret_key.get_secret_value(),
    )


@pytest.fixture
def tenant(db: Any, tenant_id: UUID) -> Tenant:
    fila = db.get(Tenant, tenant_id)
    if fila is None:
        fila = Tenant(id=tenant_id, slug="cliente", nombre="Cliente S.A.")
        db.add(fila)
    db.commit()
    return fila


def _conectar(
    cliente: TestClient,
    cabeceras: dict[str, str],
    base_url: str,
    *,
    con_login: bool = True,
    con_listado: bool = True,
    objetos: list[str] | None = None,
) -> str:
    """Conecta la herramienta por la API, como lo haría el operador.

    `con_login` distingue los dos casos que existen de verdad: la credencial de
    larga vida escrita a mano, y entrar con usuario y contraseña porque el token
    dura quince minutos. La segunda es la de contecmind.
    """
    mapeo_campos: dict[str, Any] = {
        "_rutas": {
            "usuario.alta": "PUT /usuarios/{id_externo}",
            "usuario.actualizacion": "PUT /usuarios/{id_externo}",
            "usuario.baja": "DELETE /usuarios/{id_externo}",
            "unidad.alta": "PUT /unidades/{id_externo}",
            "tenant.alta": "PUT /organizaciones/{id_externo}",
        },
        "_clave_remota": "id_externo",
    }
    if con_listado:
        mapeo_campos["_listados"] = {"usuario": "/listar/usuarios"}
    credenciales = (
        {"usuario": "admin@remota", "clave": "secreta"} if con_login else {"token": "de-larga-vida"}
    )
    if con_login:
        mapeo_campos["_ruta_login"] = "/entrar"

    respuesta = cliente.post(
        "/api/v1/suite/herramientas",
        headers=cabeceras,
        json={
            "nombre": "remota",
            "base_url": base_url,
            "credenciales": credenciales,
            "tipo": "generico",
            "mapeo_roles": {
                "roles": {"director": "admin", "comercial": "editor"},
                "precedencia": ["admin", "editor"],
            },
            "mapeo_campos": mapeo_campos,
            "objetos": objetos or ["usuario"],
            "identificador_externo": "org-remota",
        },
    )
    assert respuesta.status_code == 201, respuesta.text
    return str(respuesta.json()["id"])


# ── CRM-00.01.07.01 — identidad única ─────────────────────────────────────


def test_la_identidad_del_tenant_se_pide_por_http_y_llega_entera(
    cliente: TestClient, cabeceras: dict[str, str], tenant: Tenant
) -> None:
    respuesta = cliente.get("/api/v1/suite/identidad", headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["tenant"]["slug"] == "cliente"
    assert cuerpo["tenant"]["id"] == str(tenant.id)
    # `organizacion` tiene que venir, aunque esté vacía: que falte la clave
    # obliga a quien la consume a distinguir «sin unidades» de «no vino».
    assert cuerpo["organizacion"] == []


# ── CRM-00.01.07.05 — organigrama definido una vez ────────────────────────


def test_el_organigrama_se_define_una_vez_y_se_encola_para_cada_herramienta(
    cliente: TestClient,
    cabeceras: dict[str, str],
    tenant: Tenant,
    db: Any,
    tenant_id: UUID,
    herramienta_remota: tuple[str, _Estado],
) -> None:
    base_url, _ = herramienta_remota
    db.add(UnidadNegocio(tenant_id=tenant_id, codigo="norte", nombre="Delegación Norte"))
    db.commit()
    _conectar(cliente, cabeceras, base_url)

    identidad = cliente.get("/api/v1/suite/identidad", headers=cabeceras).json()
    assert [u["codigo"] for u in identidad["organizacion"]] == ["norte"]

    respuesta = cliente.post("/api/v1/suite/provisionar/organizacion", headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    # La herramienta declara `objetos: ["usuario"]`, así que NO se le manda el
    # organigrama. Encolarlo igualmente llenaría su cuarentena de unidades que
    # nunca pidió, y eso es lo que hace que nadie mire las cuarentenas.
    assert respuesta.json()["herramientas"] == []


# ── CRM-00.01.07.04 — el rol se traduce, y por HTTP ───────────────────────


def test_el_rol_que_viaja_es_el_traducido_por_precedencia(
    cliente: TestClient,
    cabeceras: dict[str, str],
    tenant: Tenant,
    herramienta_remota: tuple[str, _Estado],
) -> None:
    base_url, estado = herramienta_remota
    _conectar(cliente, cabeceras, base_url)

    usuario = str(uuid4())
    alta = cliente.post(
        "/api/v1/suite/provisionar/usuario",
        headers=cabeceras,
        json={
            "id": usuario,
            "email": "ana@cliente.com",
            "nombre": "Ana",
            # En el orden «malo» a propósito: si se cogiera el primero saldría
            # `editor`, y una persona con dos roles recibiría un permiso distinto
            # según cómo estén guardados sus roles.
            "roles": ["comercial", "director"],
            "operacion": "alta",
        },
    )
    assert alta.status_code == 200, alta.text

    aplicado = cliente.post("/api/v1/suite/aplicar", headers=cabeceras)
    assert aplicado.status_code == 200, aplicado.text
    assert aplicado.json()["aplicadas"] == 1, aplicado.text

    escrituras = [p for p in estado.peticiones if p[0] == "PUT"]
    assert len(escrituras) == 1, estado.peticiones
    assert escrituras[0][2]["rol"] == "admin"


# ── CRM-00.01.07.11 — simular antes de aplicar ────────────────────────────


def test_la_simulacion_dice_lo_que_pasaria_y_no_toca_la_herramienta(
    cliente: TestClient,
    cabeceras: dict[str, str],
    tenant: Tenant,
    herramienta_remota: tuple[str, _Estado],
) -> None:
    base_url, estado = herramienta_remota
    _conectar(cliente, cabeceras, base_url)
    cliente.post(
        "/api/v1/suite/provisionar/usuario",
        headers=cabeceras,
        json={"id": str(uuid4()), "email": "ana@cliente.com", "roles": ["director"]},
    )

    respuesta = cliente.get("/api/v1/suite/simular", headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    plan = respuesta.json()
    assert plan["total_a_aplicar"] == 1
    assert plan["herramientas"][0]["altas"] == ["usuario:ana@cliente.com"]
    # Lo que convierte la simulación en simulación: no ha salido nada a la red.
    assert estado.peticiones == []


# ── CRM-00.01.07.10 — la cola: baja primero, cuarentena y reintento ───────


def test_la_baja_sale_antes_que_el_alta_tambien_por_la_ruta(
    cliente: TestClient,
    cabeceras: dict[str, str],
    tenant: Tenant,
    herramienta_remota: tuple[str, _Estado],
) -> None:
    base_url, estado = herramienta_remota
    _conectar(cliente, cabeceras, base_url)

    cliente.post(
        "/api/v1/suite/provisionar/usuario",
        headers=cabeceras,
        json={"id": str(uuid4()), "email": "alta@cliente.com", "roles": ["director"]},
    )
    cliente.post(
        "/api/v1/suite/provisionar/usuario",
        headers=cabeceras,
        json={
            "id": str(uuid4()),
            "email": "baja@cliente.com",
            "roles": ["director"],
            "operacion": "baja",
        },
    )

    assert cliente.post("/api/v1/suite/aplicar", headers=cabeceras).json()["aplicadas"] == 2
    metodos = [p[0] for p in estado.peticiones if p[0] in ("PUT", "DELETE")]
    assert metodos[0] == "DELETE", f"el alta se adelantó a la baja: {metodos}"


def test_lo_que_la_herramienta_rechaza_acaba_en_cuarentena_con_lo_que_se_mando(
    cliente: TestClient,
    cabeceras: dict[str, str],
    tenant: Tenant,
    herramienta_remota: tuple[str, _Estado],
    db: Any,
    tenant_id: UUID,
) -> None:
    """Una herramienta que dice que no, cinco veces, por la ruta de verdad.

    Lo que se salta es **la espera**, no el fallo: cada intento sale a la red y
    la herramienta lo rechaza de verdad. La política de esperas crecientes tiene
    su propia prueba; repetirla aquí costaría media hora de reloj y no cubriría
    nada nuevo.
    """
    from sqlalchemy import update

    from services.tenancy.suite import SincronizacionSuite, _suite_max_intentos

    base_url, estado = herramienta_remota
    _conectar(cliente, cabeceras, base_url, con_login=False)
    # La herramienta exige token y la credencial de larga vida que se le ha dado
    # no le vale: contesta 401 a todo. Es el fallo que más se ve en producción.
    estado.exigir_token = True

    cliente.post(
        "/api/v1/suite/provisionar/usuario",
        headers=cabeceras,
        json={"id": str(uuid4()), "email": "ana@cliente.com", "roles": ["director"]},
    )

    for _ in range(_suite_max_intentos()):
        respuesta = cliente.post("/api/v1/suite/aplicar", headers=cabeceras)
        assert respuesta.status_code == 200, respuesta.text
        db.execute(update(SincronizacionSuite).values(reintentar_at=None))
        db.commit()

    apartado = cliente.get("/api/v1/suite/cuarentena", headers=cabeceras)
    assert apartado.status_code == 200, apartado.text
    filas = apartado.json()
    assert len(filas) == 1, filas
    # Con lo que se mandó dentro: sin eso, quien lo mira tiene que adivinar si el
    # problema es el dato o la herramienta.
    assert "401" in json.dumps(filas), filas

    reintento = cliente.post(
        f"/api/v1/suite/cuarentena/{filas[0]['id']}/reintentar", headers=cabeceras
    )
    assert reintento.status_code == 200, reintento.text
    assert reintento.json()["estado"] == "pendiente", reintento.text
    assert cliente.get("/api/v1/suite/cuarentena", headers=cabeceras).json() == []


# ── CRM-00.01.07.07 — reconciliar con lo que hay allí ─────────────────────


def test_se_reconcilia_con_una_herramienta_que_pide_entrar_con_usuario_y_clave(
    cliente: TestClient,
    cabeceras: dict[str, str],
    tenant: Tenant,
    herramienta_remota: tuple[str, _Estado],
) -> None:
    """El caso de contecmind: token de quince minutos, así que hay que entrar.

    Escribir funcionaba —`aplicar` entra y renueva— y **leer no**: la lectura
    solo miraba un token escrito a mano en la configuración, que en una
    herramienta así no existe. El resultado no era un error: era un
    «no se ha podido comprobar» permanente. La reconciliación entera quedaba
    apagada para la única herramienta para la que se escribió, y de la forma
    más difícil de ver, porque el panel decía exactamente lo que tenía que
    decir.
    """
    base_url, estado = herramienta_remota
    _conectar(cliente, cabeceras, base_url, con_login=True)

    usuario = str(uuid4())
    cliente.post(
        "/api/v1/suite/provisionar/usuario",
        headers=cabeceras,
        json={"id": usuario, "email": "ana@cliente.com", "roles": ["director"]},
    )
    assert cliente.post("/api/v1/suite/aplicar", headers=cabeceras).json()["aplicadas"] == 1

    respuesta = cliente.get("/api/v1/suite/reconciliar/remota", headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    lecturas = [p for p in estado.peticiones if p[0] == "GET"]
    assert cuerpo["medible"] is True, (
        "la herramienta lista sus usuarios y contesta, pero la reconciliación "
        f"dice que no se puede comprobar: {cuerpo}. Lecturas que le llegaron: "
        f"{[(p[1], p[3].get('Authorization', 'SIN AUTORIZACIÓN')) for p in lecturas]}"
    )


def test_lo_que_sobra_en_la_herramienta_se_ve_por_la_ruta(
    cliente: TestClient,
    cabeceras: dict[str, str],
    tenant: Tenant,
    herramienta_remota: tuple[str, _Estado],
) -> None:
    base_url, estado = herramienta_remota
    _conectar(cliente, cabeceras, base_url, con_login=True)
    # Alguien que está allí y que aquí no existe: una baja que no se aplicó, o
    # sea, un acceso abierto.
    estado.usuarios["fantasma"] = {"id_externo": "fantasma", "email": "exempleado@cliente.com"}

    respuesta = cliente.get("/api/v1/suite/reconciliar/remota", headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["medible"] is True, cuerpo
    assert "fantasma" in json.dumps(cuerpo), cuerpo


def test_una_herramienta_que_no_existe_da_404_y_no_500(
    cliente: TestClient, cabeceras: dict[str, str], tenant: Tenant
) -> None:
    respuesta = cliente.get("/api/v1/suite/reconciliar/inventada", headers=cabeceras)
    assert respuesta.status_code == 404, respuesta.text


# ── CRM-00.01.07.12 — auditoría transversal ───────────────────────────────


def test_el_historial_dice_en_que_herramienta_acabo_aplicandose(
    cliente: TestClient,
    cabeceras: dict[str, str],
    tenant: Tenant,
    herramienta_remota: tuple[str, _Estado],
) -> None:
    base_url, _ = herramienta_remota
    _conectar(cliente, cabeceras, base_url)
    usuario = str(uuid4())
    cliente.post(
        "/api/v1/suite/provisionar/usuario",
        headers=cabeceras,
        json={"id": usuario, "email": "ana@cliente.com", "roles": ["director"]},
    )
    cliente.post("/api/v1/suite/aplicar", headers=cabeceras)

    respuesta = cliente.get("/api/v1/suite/historial", headers=cabeceras, params={"limite": 50})
    assert respuesta.status_code == 200, respuesta.text
    texto = json.dumps(respuesta.json())
    assert "remota" in texto, respuesta.text
    assert usuario in texto, respuesta.text


# ── El panel, que es lo que mira una persona ──────────────────────────────


def test_el_panel_contesta_aunque_no_haya_nada_conectado(
    cliente: TestClient, cabeceras: dict[str, str], tenant: Tenant
) -> None:
    respuesta = cliente.get("/api/v1/suite/panel", headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    # Un «todo bien» silencioso haría creer que el cliente está en la suite
    # cuando sólo está en el CRM.
    assert json.dumps(respuesta.json()) != "{}"


# ── CRM-00.01.07.09 — SSO compartido por la suite ─────────────────────────


@pytest.fixture
def cliente_identidad(entorno: None) -> Iterator[TestClient]:
    """El SSO compartido vive en `identity`, que es de quien es el proveedor.

    Estuvo a punto de vivir en `tenancy` importando el módulo del vecino, y el
    gate de arquitectura lo paró con razón: importar los modelos de otro
    servicio convierte la separación en decorativa y obliga a desplegar los dos
    juntos.
    """
    from crmcore.service import crear_servicio

    from services.identity.api import ROUTERS

    app = crear_servicio(
        nombre="identity",
        descripcion="identity para el SSO compartido",
        routers=ROUTERS,
        necesita_bus=False,
    )
    with TestClient(app) as cli:
        yield cli


RUTA_SSO = "/api/v1/proveedores-identidad/suite"


def _con_proveedor(
    db: Any, tenant_id: UUID, certificados: list[str], herramientas: dict[str, Any]
) -> Any:
    from services.identity.modelos import ProveedorIdentidad

    fila = ProveedorIdentidad(
        tenant_id=tenant_id,
        nombre="IdP del cliente",
        tipo="oidc",
        activo=True,
        certificados=certificados,
        # El cableado se declara en el propio proveedor: que empujemos usuarios a
        # una herramienta no dice nada de contra quién autentica.
        config={"herramientas": herramientas},
    )
    db.add(fila)
    db.commit()
    return fila


def test_sin_proveedor_de_identidad_se_dice_que_no_hay_nada_que_compartir(
    cliente_identidad: TestClient, cabeceras: dict[str, str], tenant: Tenant
) -> None:
    respuesta = cliente_identidad.get(RUTA_SSO, headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["hay_proveedor"] is False


def test_una_herramienta_con_otro_certificado_no_comparte_aunque_este_conectada(
    cliente_identidad: TestClient,
    cabeceras: dict[str, str],
    tenant: Tenant,
    db: Any,
    tenant_id: UUID,
) -> None:
    """La distinción que decide qué se cae el día de la rotación.

    Esta comprobación existía entera desde el primer día y **no la llamaba
    nadie**: ni ruta, ni consumidor, ni prueba. La capacidad constaba hecha y no
    había forma de ejercerla, que es la peor manera de estar hecho: nadie lo
    descubre hasta que hace falta, y hace falta el día de una rotación.
    """
    from services.identity.sso_gobierno import _huella_certificados

    proveedor = _con_proveedor(
        db,
        tenant_id,
        ["cert-bueno"],
        {"gestor-documental": {"conectada": True, "huella_certificado": "otra-cualquiera"}},
    )

    cuerpo = cliente_identidad.get(RUTA_SSO, headers=cabeceras).json()
    assert cuerpo["hay_proveedor"] is True
    assert cuerpo["completo"] is False, cuerpo
    assert cuerpo["comparten"] == [], cuerpo
    assert "OTRO certificado" in cuerpo["herramientas"][0]["porque"], cuerpo

    # Y con la huella correcta, sí.
    proveedor.config = {
        "herramientas": {
            "gestor-documental": {
                "conectada": True,
                "huella_certificado": _huella_certificados(["cert-bueno"]),
            }
        }
    }
    db.commit()

    cuerpo = cliente_identidad.get(RUTA_SSO, headers=cabeceras).json()
    assert cuerpo["comparten"] == ["gestor-documental"], cuerpo
    assert cuerpo["completo"] is True, cuerpo


def test_la_ruta_de_la_suite_no_la_tapa_la_ficha_del_proveedor(
    cliente_identidad: TestClient, cabeceras: dict[str, str], tenant: Tenant
) -> None:
    """`/suite` va declarada antes que `/{proveedor_id}`, o no se alcanza nunca.

    Es la lección del mismo día: ocho rutas del producto eran inalcanzables
    porque una ruta con parámetro declarada antes se las comía. Si alguien mueve
    esta declaración detrás de `montar_ficha`, la petición acabaría buscando un
    proveedor llamado «suite» y contestando 422 o 404.
    """
    respuesta = cliente_identidad.get(RUTA_SSO, headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    assert "hay_proveedor" in respuesta.json(), respuesta.text


def test_con_proveedor_y_sin_herramientas_declaradas_no_se_pinta_de_verde(
    cliente_identidad: TestClient,
    cabeceras: dict[str, str],
    tenant: Tenant,
    db: Any,
    tenant_id: UUID,
) -> None:
    """Cero de cero no es «todas comparten».

    Comparar dos listas vacías da verdadero, y con eso un tenant sin ninguna
    herramienta cableada salía «completo». El mismo error que el panel evita
    diciendo «no hay herramientas conectadas» en vez de callarse.
    """
    _con_proveedor(db, tenant_id, ["cert-bueno"], {})
    cuerpo = cliente_identidad.get(RUTA_SSO, headers=cabeceras).json()
    assert cuerpo["hay_proveedor"] is True
    assert cuerpo["completo"] is False, cuerpo
    assert "no hay ninguna herramienta declarada" in cuerpo["que_significa"], cuerpo


# ── CRM-00.01.07.13 — baja en cascada con certificado único ───────────────


def test_el_certificado_no_se_firma_si_la_baja_no_se_ha_pedido(
    cliente: TestClient,
    cabeceras: dict[str, str],
    tenant: Tenant,
    herramienta_remota: tuple[str, _Estado],
) -> None:
    """No haber pedido la baja no es haberla aplicado.

    Es la firma en falso que este certificado existe para no dar: un cliente que
    termina contrato y cuya gente sigue entrando en el gestor documental, con un
    papel que dice que todo está cerrado.
    """
    base_url, _ = herramienta_remota
    _conectar(cliente, cabeceras, base_url, objetos=["tenant"])

    respuesta = cliente.get("/api/v1/suite/certificado-de-cierre", headers=cabeceras)
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["completo"] is False, cuerpo
    assert cuerpo["abiertas"][0]["herramienta"] == "remota", cuerpo
    assert "no se ha pedido la baja" in cuerpo["abiertas"][0]["porque"], cuerpo


def test_la_baja_del_tenant_llega_a_la_herramienta_y_entonces_se_certifica(
    cliente: TestClient,
    cabeceras: dict[str, str],
    tenant: Tenant,
    herramienta_remota: tuple[str, _Estado],
) -> None:
    base_url, estado = herramienta_remota
    _conectar(cliente, cabeceras, base_url, objetos=["tenant"])

    cierre = cliente.post("/api/v1/suite/cerrar", headers=cabeceras)
    assert cierre.status_code == 200, cierre.text
    assert cierre.json()["herramientas"] == ["remota"], cierre.text

    # Antes de aplicar, el certificado sigue sin poder firmarse: encolar no es
    # cerrar, y confundirlo es exactamente lo que no puede pasar aquí.
    previo = cliente.get("/api/v1/suite/certificado-de-cierre", headers=cabeceras).json()
    assert previo["completo"] is False, previo
    assert "sin aplicar todavía" in previo["abiertas"][0]["porque"], previo

    assert cliente.post("/api/v1/suite/aplicar", headers=cabeceras).json()["aplicadas"] == 1
    assert [p[0] for p in estado.peticiones if p[0] == "DELETE"], estado.peticiones

    firmado = cliente.get("/api/v1/suite/certificado-de-cierre", headers=cabeceras).json()
    assert firmado["completo"] is True, firmado
    assert firmado["cerradas"] == ["remota"], firmado
    assert firmado["abiertas"] == [], firmado
