"""Aprobar un documento del corpus: el contrato con el gestor (RT-5).

El motor de aprobación es de contecmind y aquí no se reimplementa. Lo que se
defiende en este fichero es lo único que es de este lado y se rompe callado:

  * **Los nombres de campo que salen por el cable.** El gestor valida con
    pydantic, que **ignora lo que no conoce**: un campo mal llamado no da error,
    se pierde. Pasó con el comentario de la decisión —iba como `comment` y el
    gestor lo llama `note`—, así que la decisión quedaba registrada sin el
    porqué y nadie se enteraba. Un 422 habría sido mejor noticia.
  * **La decisión se comprueba aquí, antes de salir.** El gestor sólo acepta
    tres, y su 422 llega en su idioma y sin decir cuáles valen.
  * **Lo que este cliente NO calcula**: `puedo_decidir` y `puedo_pedir` vienen
    dadas. Copiar aquí el quórum y la segregación de funciones acabaría
    enseñando botones que dan 403.

Se prueba contra un transporte HTTP simulado, igual que el resto de la
integración: lo que ha fallado seis veces ha sido el CONTRATO, y un doble del
cliente fija la suposición en vez de lo que el otro lado publica.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
import pytest
from crmcore.documental import cliente
from crmcore.errors import ErrorValidacion


@pytest.fixture
def dms_activo() -> Any:
    from crmcore.config import limpiar_cache_settings

    previo = dict(os.environ)
    os.environ.update(
        DMS_ENABLED="true",
        DMS_BASE_URL="https://dms.ejemplo.test",
        DMS_CLIENT_ID="crm",
        DMS_CLIENT_SECRET="x",
    )
    limpiar_cache_settings()
    yield
    os.environ.clear()
    os.environ.update(previo)
    limpiar_cache_settings()


class _Gestor:
    """Un contecmind de mentira que guarda lo que le llega tal cual llegó."""

    def __init__(self) -> None:
        self.peticiones: list[tuple[str, str, dict[str, Any]]] = []

    def __call__(self, peticion: httpx.Request) -> httpx.Response:
        cuerpo: dict[str, Any] = {}
        if peticion.content:
            cuerpo = json.loads(peticion.content)
        self.peticiones.append((peticion.method, peticion.url.path, cuerpo))

        ruta = peticion.url.path
        if ruta.endswith("/approval") and peticion.method == "GET":
            return httpx.Response(
                200,
                json={
                    "document_id": "d1",
                    "title": "Contrato marco",
                    "control_state": "draft",
                    "current_version_no": 2,
                    "requires_approval": True,
                    "versions": [],
                    "solicitud": None,
                    "puedo_pedir": True,
                },
            )
        if ruta.endswith("/approval") and peticion.method == "POST":
            return httpx.Response(201, json={"id": "s1", "status": "pending"})
        if ruta == "/api/v1/approvals/pending":
            return httpx.Response(200, json={"items": [{"id": "s1"}], "total": 1})
        if ruta == "/api/v1/approvals/workflows":
            return httpx.Response(
                200, json={"items": [{"id": "f1", "name": "Contratos", "exige_aprobadores": True}]}
            )
        if ruta.endswith("/decide"):
            return httpx.Response(200, json={"id": "s1", "status": "approved"})
        if ruta.endswith("/cancel"):
            return httpx.Response(200, json={"id": "s1", "status": "cancelled"})
        return httpx.Response(404, json={"detail": "no"})


@pytest.fixture
def gestor(monkeypatch: pytest.MonkeyPatch) -> _Gestor:
    import contextlib

    g = _Gestor()

    @contextlib.contextmanager
    def _fabrica(**_: Any) -> Any:
        with httpx.Client(transport=httpx.MockTransport(g)) as cli:
            yield cli

    monkeypatch.setattr("crmcore.red.cliente_seguro", _fabrica)
    return g


def _cuerpo_de(g: _Gestor, final: str) -> dict[str, Any]:
    for _metodo, ruta, cuerpo in g.peticiones:
        if ruta.endswith(final):
            return cuerpo
    raise AssertionError(f"no se llamó a nada que acabe en «{final}»: {g.peticiones}")


# ── Los nombres de campo ──────────────────────────────────────────────────


def test_el_comentario_de_la_decision_viaja_como_note(dms_activo: Any, gestor: _Gestor) -> None:
    """Se llamaba `comment` y el gestor lo tiraba sin decir nada.

    Es el fallo que justifica este fichero entero: pydantic ignora los campos
    que no conoce, así que la decisión se registraba —aprobada, con su fecha y
    su firmante— y el porqué desaparecía por el camino.
    """
    cliente.decidir_aprobacion(
        "s1", token_usuario="t", decision="approved", comentario="visto bueno de dirección"
    )
    cuerpo = _cuerpo_de(gestor, "/decide")
    assert cuerpo["note"] == "visto bueno de dirección"
    assert "comment" not in cuerpo


def test_delegar_lleva_en_quien(dms_activo: Any, gestor: _Gestor) -> None:
    cliente.decidir_aprobacion("s1", token_usuario="t", decision="delegated", delegar_en="u-7")
    assert _cuerpo_de(gestor, "/decide")["delegate_to"] == "u-7"


def test_sin_delegar_no_se_manda_el_campo(dms_activo: Any, gestor: _Gestor) -> None:
    """`delegate_to` vacío no es lo mismo que ausente: el gestor lo valida."""
    cliente.decidir_aprobacion("s1", token_usuario="t", decision="approved")
    assert "delegate_to" not in _cuerpo_de(gestor, "/decide")


def test_pedirla_manda_los_aprobadores_el_flujo_y_la_version(
    dms_activo: Any, gestor: _Gestor
) -> None:
    cliente.pedir_aprobacion(
        "d1", token_usuario="t", aprobadores=["u-1", "u-2"], flujo_id="f1", version=3
    )
    cuerpo = _cuerpo_de(gestor, "/approval")
    assert cuerpo["approvers"] == ["u-1", "u-2"]
    assert cuerpo["workflow_id"] == "f1"
    assert cuerpo["version_no"] == 3


def test_sin_flujo_no_se_manda_flujo(dms_activo: Any, gestor: _Gestor) -> None:
    """Mandarlo vacío no es «el que toque»: es un identificador que no existe."""
    cliente.pedir_aprobacion("d1", token_usuario="t")
    assert "workflow_id" not in _cuerpo_de(gestor, "/approval")


# ── La decisión ───────────────────────────────────────────────────────────


def test_una_decision_que_no_es_ninguna_de_las_tres_se_para_aqui(
    dms_activo: Any, gestor: _Gestor
) -> None:
    """Antes de salir a la red: el 422 del gestor no dice cuáles valen."""
    with pytest.raises(ErrorValidacion) as exc:
        cliente.decidir_aprobacion("s1", token_usuario="t", decision="aprobado")
    assert exc.value.error_code == "documental.decision_no_valida"
    assert set(exc.value.detalle["validas"]) == {"approved", "rejected", "delegated"}
    assert not gestor.peticiones, "salió a la red con una decisión que no existe"


# ── Lo que viene dado ─────────────────────────────────────────────────────


def test_el_estado_trae_si_puedo_pedirla_y_no_se_calcula_aqui(
    dms_activo: Any, gestor: _Gestor
) -> None:
    estado = cliente.aprobacion_de("d1", token_usuario="t")
    assert estado["puedo_pedir"] is True


def test_las_rutas_son_las_que_contecmind_publica(dms_activo: Any, gestor: _Gestor) -> None:
    """Fijadas también en `fijar_contratos_vecinos.py`; aquí se recorren."""
    cliente.aprobacion_de("d1", token_usuario="t")
    cliente.aprobaciones_pendientes(token_usuario="t")
    cliente.flujos_de_aprobacion(token_usuario="t")
    cliente.cancelar_aprobacion("s1", token_usuario="t")
    assert [(m, r) for m, r, _ in gestor.peticiones] == [
        ("GET", "/api/v1/documents/d1/approval"),
        ("GET", "/api/v1/approvals/pending"),
        ("GET", "/api/v1/approvals/workflows"),
        ("POST", "/api/v1/approvals/s1/cancel"),
    ]


def test_la_bandeja_de_pendientes_desenvuelve_los_items(dms_activo: Any, gestor: _Gestor) -> None:
    """El gestor contesta `{items, total}`; la pantalla quiere la lista."""
    assert cliente.aprobaciones_pendientes(token_usuario="t") == [{"id": "s1"}]


def test_los_flujos_dicen_cuales_exigen_aprobadores(dms_activo: Any, gestor: _Gestor) -> None:
    """Sin esto la pantalla deja enviar y se come un 422 del gestor."""
    flujos = cliente.flujos_de_aprobacion(token_usuario="t")
    assert flujos[0]["exige_aprobadores"] is True


# ── El sobre vacío ────────────────────────────────────────────────────────


class _Vacio:
    """Un contecmind recién instalado: contesta bien, y no tiene nada."""

    def __call__(self, peticion: httpx.Request) -> httpx.Response:
        if peticion.url.path == "/api/v1/approvals/pending":
            return httpx.Response(200, json={"items": [], "total": 0})
        if peticion.url.path == "/api/v1/approvals/workflows":
            return httpx.Response(200, json={"items": []})
        if peticion.url.path == "/api/v1/documents/search":
            return httpx.Response(200, json={"query": "x", "scope": "all_corpus", "items": []})
        return httpx.Response(404, json={"detail": "no"})


@pytest.fixture
def gestor_vacio(monkeypatch: pytest.MonkeyPatch) -> None:
    import contextlib

    @contextlib.contextmanager
    def _fabrica(**_: Any) -> Any:
        with httpx.Client(transport=httpx.MockTransport(_Vacio())) as cli:
            yield cli

    monkeypatch.setattr("crmcore.red.cliente_seguro", _fabrica)


def test_una_bandeja_vacia_es_una_lista_vacia_y_no_los_nombres_del_sobre(
    dms_activo: Any, gestor_vacio: None
) -> None:
    """Devolvía `["items", "total"]`, y la pantalla pintaba dos filas fantasma.

    El código era `cuerpo.get("items") or cuerpo or []`. Con la bandeja vacía,
    el `or` descarta la lista vacía por falsa, cae al diccionario entero y
    `list()` de un diccionario son sus CLAVES. Justo cuando no hay nada que
    decidir, que es el primer día de cualquier instalación.

    No lo cazó la prueba de más arriba porque su gestor de mentira devuelve una
    solicitud. Se vio llamando a contecmind de verdad con la base vacía: es el
    caso que un doble no te enseña si no se lo pides.
    """
    assert cliente.aprobaciones_pendientes(token_usuario="t") == []
    assert cliente.flujos_de_aprobacion(token_usuario="t") == []


def test_una_busqueda_sin_resultados_tambien(dms_activo: Any, gestor_vacio: None) -> None:
    """El mismo `or` estaba en la búsqueda, esperando su turno."""
    assert cliente.buscar("contrato", token_usuario="t") == []
