"""El código del tenant, de verdad (CRM-00.04.02.01, .04, .05, .06, .07).

Lo que había eran cálculos sobre lo que mandara quien preguntaba y ninguna
ejecución. Aquí se ejercita lo que les faltaba, por HTTP y con el motor real
—QuickJS en WebAssembly—:

- se publica, se prueba, se activa y se vuelve atrás sin pisar versiones;
- un endpoint propio ejecuta la versión activa y contesta lo que devuelve;
- lo que se pasa de sus topes se corta, y se dice por cuál;
- la función no escribe: pide acciones, y se hacen con SUS permisos;
- la de terceros exige firma Ed25519 válida y la revisión de otra persona;
- la cuota mensual corta.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.db


@pytest.fixture
def cli(monkeypatch: Any, db: Any) -> Any:
    import importlib

    from crmcore.config import get_settings
    from crmcore.tareas import RelevoDeTareas
    from starlette.testclient import TestClient

    async def _no_correr(self: Any) -> None:
        return None

    monkeypatch.setattr(RelevoDeTareas, "correr", _no_correr)
    monkeypatch.setenv("OUTBOX_ENABLED", "false")
    get_settings.cache_clear()
    try:
        with TestClient(importlib.import_module("services.automation.main").app) as cliente:
            yield cliente
    finally:
        get_settings.cache_clear()


def _cab(tenant_id: UUID, usuario: UUID | None = None, permisos: str = "*:*") -> Any:
    from crmcore.http.deps import H_PERMISOS, H_USER

    from tests.unit.test_reverificacion_y_mfa_adaptativa import _cabeceras

    return _cabeceras(tenant_id, **{H_USER: str(usuario or uuid4()), H_PERMISOS: permisos})


def _alta(cli: Any, cab: Any, clave: str, **extra: Any) -> str:
    r = cli.post(
        "/api/v1/extensiones",
        headers=cab,
        json={"clave": clave, "nombre": clave.title(), **extra},
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def _publicar(cli: Any, cab: Any, ext: str, codigo: str, **extra: Any) -> Any:
    return cli.post(
        f"/api/v1/extensiones/{ext}/versiones", headers=cab, json={"codigo": codigo, **extra}
    )


def test_publicar_probar_activar_y_volver_atras(cli: Any, tenant_id: UUID) -> None:
    cab = _cab(tenant_id)
    ext = _alta(cli, cab, "precio-con-iva")
    v1 = _publicar(
        cli,
        cab,
        ext,
        "function main(e){ console.log('base', e.base); return {total: e.base * 1.21} }",
    )
    assert v1.status_code == 201 and v1.json()["version"] == 1 and v1.json()["estado"] == "lista"

    prueba = cli.post(
        f"/api/v1/extensiones/{ext}/probar",
        headers=cab,
        json={"entrada": {"base": 100}, "version": 1},
    )
    assert prueba.status_code == 200, prueba.text
    assert prueba.json()["ok"] and prueba.json()["resultado"] == {"total": 121}
    assert prueba.json()["logs"] == [{"nivel": "info", "texto": "base 100"}]

    # Sin activa, un endpoint no tiene qué ejecutar.
    endpoint = cli.post(
        "/api/v1/extensiones/endpoints",
        headers=cab,
        json={"metodo": "POST", "ruta": "precios/con-iva", "extension_id": ext},
    )
    assert endpoint.status_code == 201, endpoint.text
    assert (
        cli.post("/api/v1/propios/precios/con-iva", headers=cab, json={"base": 10}).status_code
        == 409
    )

    assert (
        cli.post(f"/api/v1/extensiones/{ext}/activar", headers=cab, json={"version": 1}).status_code
        == 200
    )
    r = cli.post("/api/v1/propios/precios/con-iva", headers=cab, json={"base": 10})
    assert r.status_code == 200, r.text
    # El endpoint pasa {metodo, ruta, consulta, cuerpo}: la base va en «cuerpo»,
    # así que la v1 —que la lee de arriba— calcula con nada y devuelve null.
    assert r.json() == {"total": None}

    # La v2 lee el cuerpo, y además falla con base negativa.
    v2 = _publicar(
        cli,
        cab,
        ext,
        "function main(e){ const b = e.cuerpo.base;\n if (b < 0) throw new Error('base negativa');\n"
        " return {estado: 201, cuerpo: {total: b * 1.21}} }",
    )
    assert v2.json()["version"] == 2
    # Publicar no activa: sigue la 1.
    assert cli.get(f"/api/v1/extensiones/{ext}", headers=cab).json()["version_activa"] == 1
    cli.post(f"/api/v1/extensiones/{ext}/activar", headers=cab, json={"version": 2})
    bien = cli.post("/api/v1/propios/precios/con-iva", headers=cab, json={"base": 10})
    assert bien.status_code == 201 and bien.json() == {"total": 12.1}
    mal = cli.post("/api/v1/propios/precios/con-iva", headers=cab, json={"base": -1})
    assert mal.status_code == 502 and "base negativa" in mal.json()["detail"]

    # Volver atrás exige motivo y activa la anterior entera.
    assert (
        cli.post(
            f"/api/v1/extensiones/{ext}/volver-atras", headers=cab, json={"motivo": ""}
        ).status_code
        == 422
    )
    atras = cli.post(
        f"/api/v1/extensiones/{ext}/volver-atras", headers=cab, json={"motivo": "La 2 rompe"}
    )
    assert atras.status_code == 200 and atras.json()["version_activa"] == 1
    versiones = cli.get(f"/api/v1/extensiones/{ext}/versiones", headers=cab).json()["items"]
    assert [(v["version"], v["activa"]) for v in versiones] == [(2, False), (1, True)]

    # Lo que pasó queda apuntado, por versión, con el error dentro.
    obs = cli.post(f"/api/v1/extensiones/{ext}/observabilidad", headers=cab).json()
    assert obs["ejecuciones"] == 4 and obs["fallidas"] == 1
    assert {v["version"]: v["fallidas"] for v in obs["por_version"]} == {2: 1, 1: 0}
    ejec = cli.get(f"/api/v1/extensiones/{ext}/ejecuciones", headers=cab).json()["items"]
    assert any("base negativa" in (e["error"] or "") for e in ejec)

    # Y lo de otro tenant no se ve.
    assert cli.get(f"/api/v1/extensiones/{ext}", headers=_cab(uuid4())).status_code == 404
    assert (
        cli.post("/api/v1/propios/precios/con-iva", headers=_cab(uuid4()), json={}).status_code
        == 404
    )


def test_lo_que_se_pasa_se_corta_y_se_dice_por_que(
    cli: Any, tenant_id: UUID, monkeypatch: Any
) -> None:
    from crmcore.config import get_settings

    monkeypatch.setattr(get_settings(), "extensiones_tiempo_ms", 300)
    monkeypatch.setattr(get_settings(), "extensiones_combustible", 10**13)
    cab = _cab(tenant_id)
    ext = _alta(cli, cab, "bucle")
    _publicar(cli, cab, ext, "function main(e){ while(true){} }")
    r = cli.post(f"/api/v1/extensiones/{ext}/probar", headers=cab, json={"version": 1}).json()
    assert not r["ok"] and r["cortada_por"] == "tiempo"

    monkeypatch.setattr(get_settings(), "extensiones_tiempo_ms", 10_000)
    monkeypatch.setattr(get_settings(), "extensiones_combustible", 5_000_000)
    r = cli.post(f"/api/v1/extensiones/{ext}/probar", headers=cab, json={"version": 1}).json()
    assert r["cortada_por"] == "cpu"

    # Sin nada fuera: ni ficheros, ni red, ni la salida estándar.
    ext2 = _alta(cli, cab, "curiosa")
    _publicar(
        cli,
        cab,
        ext2,
        "function main(e){ return [typeof std, typeof os, typeof fetch, typeof require] }",
    )
    monkeypatch.setattr(get_settings(), "extensiones_combustible", 10**10)
    r = cli.post(f"/api/v1/extensiones/{ext2}/probar", headers=cab, json={"version": 1}).json()
    assert r["resultado"] == ["undefined"] * 4


def test_la_funcion_pide_y_se_hace_con_sus_permisos(
    cli: Any, tenant_id: UUID, monkeypatch: Any
) -> None:
    import crmcore.http.interno as interno

    llamadas: list[dict[str, Any]] = []

    def _invocar(**kw: Any) -> dict[str, Any]:
        llamadas.append(kw)
        return {"estado": 201, "datos": {}}

    monkeypatch.setattr(interno, "invocar", _invocar)
    yo = uuid4()
    cab = _cab(tenant_id, yo, permisos="automatizacion:*,account:read")
    # No puede darle a la extensión lo que él no tiene.
    r = cli.post(
        "/api/v1/extensiones",
        headers=cab,
        json={"clave": "lista", "nombre": "Lista", "permisos": ["account:write"]},
    )
    assert r.status_code == 403 and r.json()["error_code"] == "extension.permisos_de_mas"

    ext = _alta(cli, _cab(tenant_id, yo), "nota-de-llamada", permisos=["activity:write"])
    _publicar(
        cli,
        _cab(tenant_id, yo),
        ext,
        "function main(e){ return {acciones: [{metodo: 'POST', ruta: '/api/v1/activities', "
        "cuerpo: {asunto: 'Llamada'}}]} }",
    )
    cab = _cab(tenant_id, yo)
    # En la prueba se enseñan y no se hacen.
    prueba = cli.post(f"/api/v1/extensiones/{ext}/probar", headers=cab, json={"version": 1}).json()
    assert prueba["acciones"][0]["ruta"] == "/api/v1/activities" and not prueba["acciones_hechas"]
    assert llamadas == []
    # Por un endpoint sí, con los permisos de la extensión y no los de quien llama.
    cli.post(f"/api/v1/extensiones/{ext}/activar", headers=cab, json={"version": 1})
    cli.post(
        "/api/v1/extensiones/endpoints",
        headers=cab,
        json={"metodo": "POST", "ruta": "llamada", "extension_id": ext},
    )
    assert cli.post("/api/v1/propios/llamada", headers=cab, json={}).status_code == 200
    assert len(llamadas) == 1 and llamadas[0]["permisos"] == ["activity:write"]

    # Y no puede tocar el código del tenant: sería un bucle que ningún tope ve.
    ext2 = _alta(cli, cab, "recursiva")
    _publicar(
        cli,
        cab,
        ext2,
        f"function main(e){{ return {{acciones: [{{metodo: 'POST', ruta: '/api/v1/extensiones/{ext}/probar'}}]}} }}",
    )
    r = cli.post(f"/api/v1/extensiones/{ext2}/probar", headers=cab, json={"version": 1}).json()
    assert not r["ok"] and "bucle" in r["error"]


def test_la_de_terceros_exige_firma_y_revision_de_otro(cli: Any, tenant_id: UUID) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    privada = Ed25519PrivateKey.generate()
    publica = base64.b64encode(
        privada.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()
    autor, revisor = uuid4(), uuid4()
    cab = _cab(tenant_id, autor)
    firmante = cli.post(
        "/api/v1/extensiones/firmantes",
        headers=cab,
        json={"nombre": "Proveedor X", "clave_publica": publica},
    )
    assert firmante.status_code == 201, firmante.text
    firmante_id = firmante.json()["id"]
    ext = _alta(cli, cab, "conector-x", origen="tercero")
    codigo = "function main(e){ return 1 }"
    huella = hashlib.sha256(codigo.encode()).hexdigest()
    firma = base64.b64encode(privada.sign(huella.encode())).decode()

    assert _publicar(cli, cab, ext, codigo).json()["error_code"] == "extension.sin_firma"
    otra = base64.b64encode(Ed25519PrivateKey.generate().sign(huella.encode())).decode()
    mala = _publicar(cli, cab, ext, codigo, firmante_id=firmante_id, firma=otra)
    assert mala.status_code == 422 and mala.json()["error_code"] == "extension.firma_invalida"
    # Firmado lo de antes y cambiado después: la huella no cuadra.
    cambiado = _publicar(cli, cab, ext, codigo + " ", firmante_id=firmante_id, firma=firma)
    assert cambiado.json()["error_code"] == "extension.firma_invalida"

    buena = _publicar(cli, cab, ext, codigo, firmante_id=firmante_id, firma=firma)
    assert buena.status_code == 201 and buena.json()["estado"] == "pendiente_revision"
    version = buena.json()["version"]
    # Sin revisar no se activa, y quien la publicó no la revisa.
    assert (
        cli.post(
            f"/api/v1/extensiones/{ext}/activar", headers=cab, json={"version": version}
        ).status_code
        == 409
    )
    propia = cli.post(
        f"/api/v1/extensiones/{ext}/versiones/{version}/revisar",
        headers=cab,
        json={"aprobar": True, "nota": "Mirado"},
    )
    assert propia.status_code == 403
    revisada = cli.post(
        f"/api/v1/extensiones/{ext}/versiones/{version}/revisar",
        headers=_cab(tenant_id, revisor),
        json={"aprobar": True, "nota": "Sin llamadas fuera, sólo calcula"},
    )
    assert revisada.status_code == 200 and revisada.json()["estado"] == "revisada"
    assert (
        cli.post(
            f"/api/v1/extensiones/{ext}/activar", headers=cab, json={"version": version}
        ).status_code
        == 200
    )


def test_la_cuota_del_mes_corta(cli: Any, tenant_id: UUID, monkeypatch: Any) -> None:
    from crmcore.config import get_settings

    monkeypatch.setattr(get_settings(), "cuota_extensiones_mes", 2)
    cab = _cab(tenant_id)
    ext = _alta(cli, cab, "cuenta")
    _publicar(cli, cab, ext, "function main(e){ return 1 }")
    for _ in range(2):
        assert (
            cli.post(
                f"/api/v1/extensiones/{ext}/probar", headers=cab, json={"version": 1}
            ).status_code
            == 200
        )
    r = cli.post(f"/api/v1/extensiones/{ext}/probar", headers=cab, json={"version": 1})
    assert r.status_code == 429 and r.json()["error_code"] == "cuota.extensiones"
