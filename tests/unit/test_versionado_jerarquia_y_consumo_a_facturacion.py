"""Versionado de la configuración, jerarquía de empresas y consumo a facturación
(CRM-00.01.04.02, CRM-00.01.03.07, CRM-00.01.06.07).

Las tres constaban hechas y el 09-11-2026 se midió que no se llegaba a ellas:
el historial de ajustes se guardaba y ninguna ruta lo enseñaba; la jerarquía era
una columna que no decía qué relación era ni dejaba ver nada; y el consumo se
medía y no salía de la pantalla. Aquí se recorren por HTTP y por función.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


@pytest.fixture
def cliente(monkeypatch: Any) -> Any:
    import importlib
    import os

    from crmcore.config import get_settings
    from crmcore.tareas import RelevoDeTareas

    async def _no_correr(self: Any) -> None:
        return None

    monkeypatch.setattr(RelevoDeTareas, "correr", _no_correr)
    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        modulo = importlib.import_module("services.tenancy.main")
        with TestClient(modulo.app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


def _cabeceras(tenant_id: UUID, *, permisos: str = "*:*", plataforma: bool = False) -> dict:
    from crmcore.config import get_settings
    from crmcore.http.deps import (
        H_FACTOR_FUERTE,
        H_PERMISOS,
        H_PLATAFORMA,
        H_ROLES,
        H_TENANT,
        H_USER,
        firmar_cabeceras_internas,
    )

    return firmar_cabeceras_internas(
        {
            H_TENANT: str(tenant_id),
            H_USER: str(uuid4()),
            H_PERMISOS: permisos,
            H_ROLES: "admin",
            H_PLATAFORMA: "1" if plataforma else "",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


def _tenant(db: Any, nombre: str, *, padre: Any = None, relacion: str | None = None) -> Any:
    from services.tenancy.modelos import Tenant

    t = Tenant(
        slug=f"{nombre.lower()}-{uuid4().hex[:6]}",
        nombre=nombre,
        tenant_padre_id=padre.id if padre is not None else None,
        relacion_padre=relacion,
    )
    db.add(t)
    db.flush()
    return t


# ── Versionado (CRM-00.01.04.02) ──────────────────────────────────────────


def test_el_historial_el_diff_y_la_vuelta_atras_se_alcanzan_por_http(
    cliente: Any, db: Any, tenant_id: UUID
) -> None:
    """Las cuatro rutas, en el orden en que las usa la pantalla."""
    cab = _cabeceras(tenant_id)
    desde = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    for valor in ("es", "fr"):
        r = cliente.put("/api/v1/ajustes/idioma", headers=cab, json={"valor": valor})
        assert r.status_code == 200, r.text

    r = cliente.get("/api/v1/ajustes/versiones", headers=cab, params={"clave": "idioma"})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert "idioma" in [c["clave"] for c in cuerpo["claves"]]
    ultima, primera = cuerpo["versiones"][0], cuerpo["versiones"][1]
    assert (ultima["antes"], ultima["despues"]) == ("es", "fr")

    r = cliente.get("/api/v1/ajustes/versiones/diferencias", headers=cab, params={"desde": desde})
    assert r.status_code == 200, r.text
    assert [c["despues"] for c in r.json()["cambios"] if c["clave"] == "idioma"] == ["fr"]

    r = cliente.get(
        "/api/v1/ajustes/versiones/comparar",
        headers=cab,
        params={"a": ultima["id"], "b": primera["id"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["cambios"] == [{"ruta": "", "tipo": "cambiado", "antes": "es", "despues": "fr"}]

    r = cliente.post(f"/api/v1/ajustes/versiones/{ultima['id']}/volver", headers=cab)
    assert r.status_code == 200, r.text
    r = cliente.get("/api/v1/ajustes/versiones", headers=cab, params={"clave": "idioma"})
    versiones = r.json()["versiones"]
    # UN apunte por deshacer, y marcado como lo que es: antes salían dos.
    assert len(versiones) == 3
    assert versiones[0]["tipo"] == "vuelta_atras"
    assert (versiones[0]["antes"], versiones[0]["despues"]) == ("fr", "es")


def test_volver_a_un_cambio_sin_valor_previo_quita_el_del_ambito(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Deshacer el primer cambio de una clave no es fijar `None` —ningún
    ajuste lo admite—: es volver a heredar."""
    from crmcore.runtime import settings as rt
    from crmcore.runtime.versiones import VersionAjuste, historial, volver_a
    from sqlalchemy import select

    rt.fijar(db, "idioma", "fr", ambito="tenant", ambito_id=str(tenant_id))
    db.flush()
    primero = historial(db, tenant_id, clave="idioma")[0]
    # Forzado: en este entorno el efectivo de partida puede no ser None.
    fila = db.execute(
        select(VersionAjuste).where(VersionAjuste.id == UUID(primero["id"]))
    ).scalar_one()
    fila.valor_anterior = None
    db.flush()

    salida = volver_a(db, UUID(primero["id"]), tenant_id=tenant_id)
    assert salida["heredado"] is True
    assert historial(db, tenant_id, clave="idioma")[0]["tipo"] == "vuelta_atras"


def test_comparar_dice_que_entrada_cambio_de_un_ajuste_estructurado() -> None:
    from crmcore.runtime.versiones import diferencias

    assert diferencias({"a": 1, "b": {"c": 2}}, {"a": 1, "b": {"c": 3}, "d": 4}) == [
        {"ruta": "b.c", "tipo": "cambiado", "antes": 2, "despues": 3},
        {"ruta": "d", "tipo": "anadido", "antes": None, "despues": 4},
    ]


def test_la_version_de_otro_tenant_no_existe(
    cliente: Any, db: Any, tenant_id: UUID, otro_tenant_id: UUID
) -> None:
    r = cliente.put("/api/v1/ajustes/idioma", headers=_cabeceras(tenant_id), json={"valor": "fr"})
    assert r.status_code == 200
    vid = cliente.get("/api/v1/ajustes/versiones", headers=_cabeceras(tenant_id)).json()[
        "versiones"
    ][0]["id"]
    r = cliente.post(f"/api/v1/ajustes/versiones/{vid}/volver", headers=_cabeceras(otro_tenant_id))
    assert r.status_code == 404, r.text


# ── Jerarquía (CRM-00.01.03.07) ───────────────────────────────────────────


def test_el_arbol_de_una_filial_no_ensena_a_sus_hermanas(db: Any) -> None:
    from services.tenancy import jerarquia

    matriz = _tenant(db, "Matriz")
    a = _tenant(db, "FilialA", padre=matriz, relacion="matriz_filial")
    _tenant(db, "FilialB", padre=matriz, relacion="matriz_filial")
    nieta = _tenant(db, "Franquiciado", padre=a, relacion="franquicia")

    vista = jerarquia.arbol(db, a.id, es_plataforma=False)
    nombres = [n["nombre"] for n in vista["nodos"]]
    assert nombres == ["Matriz", "FilialA", "Franquiciado"]
    assert [n["nivel"] for n in vista["nodos"]] == [0, 1, 2]

    entera = jerarquia.arbol(db, nieta.id, es_plataforma=True)
    assert {"FilialA", "FilialB"} <= {n["nombre"] for n in entera["nodos"]}


def test_colgar_rechaza_el_circulo_y_la_relacion_inventada(db: Any) -> None:
    from crmcore.errors import Conflicto, ErrorValidacion

    from services.tenancy import jerarquia

    matriz = _tenant(db, "Holding")
    hija = _tenant(db, "Hija", padre=matriz, relacion="holding")
    with pytest.raises(Conflicto):
        jerarquia.colgar(db, matriz.id, padre_id=hija.id, relacion="holding")
    with pytest.raises(ErrorValidacion):
        jerarquia.colgar(db, hija.id, padre_id=matriz.id, relacion="primos")


def test_cambiar_de_padre_borra_lo_que_se_compartia(db: Any) -> None:
    from services.tenancy import jerarquia

    m1, m2 = _tenant(db, "M1"), _tenant(db, "M2")
    hija = _tenant(db, "H", padre=m1, relacion="matriz_filial")
    jerarquia.compartir(db, hija.id, que=["consumo"], por=None)
    jerarquia.colgar(db, hija.id, padre_id=m2.id, relacion="franquicia")
    assert hija.comparte_con_padre == []
    assert hija.relacion_padre == "franquicia"


def test_la_matriz_solo_ve_lo_que_la_hija_ha_compartido(db: Any, contexto_tenant: UUID) -> None:
    from services.tenancy import jerarquia

    matriz = _tenant(db, "Grupo")
    comparte = _tenant(db, "Abierta", padre=matriz, relacion="matriz_filial")
    _tenant(db, "Cerrada", padre=matriz, relacion="matriz_filial")
    jerarquia.compartir(db, comparte.id, que=["consumo", "indicadores"], por=None)
    preguntadas: list[UUID] = []

    def _consumo(tid: UUID) -> dict[str, Any]:
        preguntadas.append(tid)
        fila = {"metrica": "registros", "cantidad": 7, "unidad": "unidades"}
        return {"filas": [fila], "no_leidos": []}

    def _ind(tid: UUID, conf: list) -> list[dict[str, Any]]:
        preguntadas.append(tid)
        return [{"nombre": "Embudo", "valor": 1000.0, "porque": ""}]

    salida = jerarquia.agregado(db, matriz.id, consumo_de=_consumo, indicadores_de_hija=_ind)
    # A la que no comparte NO se le pregunta: el aislamiento no depende de
    # filtrar después, sino de no llamar.
    assert preguntadas == [comparte.id, comparte.id]
    assert salida["no_comparten"] == ["Cerrada"]
    assert salida["totales"]["consumo"] == [
        {"metrica": "registros", "cantidad": 7, "unidad": "unidades"}
    ]
    assert salida["totales"]["indicadores"] == [{"nombre": "Embudo", "valor": 1000.0}]
    cerrada = next(h for h in salida["hijas"] if h["nombre"] == "Cerrada")
    assert cerrada["consumo"] is None and cerrada["indicadores"] is None


def test_lo_que_comparte_una_empresa_lo_decide_ella_y_no_la_plataforma(
    cliente: Any, db: Any
) -> None:
    matriz = _tenant(db, "MatrizHttp")
    hija = _tenant(db, "HijaHttp", padre=matriz, relacion="matriz_filial")
    db.commit()
    ruta = f"/api/v1/tenants/{hija.id}/jerarquia/comparticion"
    plataforma = _cabeceras(matriz.id, plataforma=True)
    r = cliente.put(ruta, headers=plataforma, json={"comparte": ["consumo"]})
    assert r.status_code == 403, r.text
    r = cliente.put(ruta, headers=_cabeceras(hija.id), json={"comparte": ["consumo"]})
    assert r.status_code == 200, r.text
    assert r.json()["comparte"] == ["consumo"]

    # Y el árbol de otra empresa es 404 para quien no es ella ni la plataforma.
    otra = _tenant(db, "Ajena")
    db.commit()
    r = cliente.get(f"/api/v1/tenants/{matriz.id}/jerarquia", headers=_cabeceras(otra.id))
    assert r.status_code == 404


# ── Consumo a facturación (CRM-00.01.06.07) ───────────────────────────────

MEDIDO = {
    "filas": [
        {
            "modulo": "sales",
            "metrica": "registros",
            "cantidad": 120,
            "unidad": "unidades",
            "tope": 1000,
        },
        {
            "modulo": "sales",
            "metrica": "almacenamiento_mb",
            "cantidad": 5,
            "unidad": "MB",
            "tope": None,
        },
    ],
    "no_leidos": ["marketing"],
}


def test_el_corte_sale_en_formato_neutro_y_dice_lo_que_no_pudo_leer(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from services.tenancy import facturacion

    _tenant(db, "Corte")
    c = facturacion.tomar_corte(db, tenant_id, medido=MEDIDO)
    assert c.completo is False and c.no_leidos == ["marketing"]
    texto, tipo = facturacion.descargar(c, "csv")
    assert tipo.startswith("text/csv")
    lineas = texto.strip().splitlines()
    assert lineas[0] == "periodo,tenant,modulo,metrica,cantidad,unidad,tope"
    assert lineas[1].split(",")[2:] == ["sales", "registros", "120", "unidades", "1000"]
    # Sin tope es vacío, no cero: cero se leería «no tiene derecho a nada».
    assert lineas[2].endswith(",MB,")
    js = facturacion.como_json(c)
    assert js["columnas"] == list(facturacion.COLUMNAS) and js["completo"] is False


def test_sin_destino_el_corte_queda_sin_destino_y_no_como_enviado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from services.tenancy import facturacion

    c = facturacion.tomar_corte(db, tenant_id, medido=MEDIDO)
    assert facturacion.enviar(db, c)["estado_envio"] == "sin_destino"


class _Respuesta:
    def __init__(self, codigo: int) -> None:
        self.status_code = codigo
        self.text = "ok" if codigo < 300 else "rechazado"


def _doble(monkeypatch: Any, codigo: int) -> list[dict[str, Any]]:
    """Un sistema de facturación de mentira: guarda lo que recibe."""
    recibido: list[dict[str, Any]] = []

    class _Cli:
        def __enter__(self) -> Any:
            return self

        def __exit__(self, *a: Any) -> None:
            return None

        def post(self, url: str, *, content: bytes, headers: dict[str, str]) -> Any:
            recibido.append({"url": url, "cuerpo": content, "cabeceras": headers})
            return _Respuesta(codigo)

    monkeypatch.setattr("crmcore.red.cliente_seguro", lambda **_: _Cli())
    return recibido


def test_el_envio_va_firmado_con_la_forma_configurada_y_anota_su_estado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    import json

    from crmcore.runtime import settings as rt

    from services.tenancy import facturacion

    recibido = _doble(monkeypatch, 202)
    tid = str(tenant_id)
    rt.fijar(db, "facturacion_destino_url", "https://cobro.example/uso", ambito_id=tid)
    rt.fijar(db, "facturacion_destino_cabeceras", {"x-api-key": "k"}, ambito_id=tid)
    c = facturacion.tomar_corte(db, tenant_id, medido=MEDIDO)
    salida = facturacion.enviar(db, c)
    assert salida["estado_envio"] == "enviado" and salida["respuesta_codigo"] == 202
    envio = recibido[0]
    assert envio["cabeceras"]["x-api-key"] == "k"
    assert envio["cabeceras"]["x-crm-corte"] == str(c.id)
    assert any("firma" in k.lower() or "signature" in k.lower() for k in envio["cabeceras"])
    assert json.loads(envio["cuerpo"])["filas"][0]["cantidad"] == 120

    rt.fijar(db, "facturacion_formato_envio", "csv", ambito_id=tid)
    otro = facturacion.tomar_corte(db, tenant_id, medido=MEDIDO)
    facturacion.enviar(db, otro)
    assert recibido[1]["cuerpo"].decode().startswith("periodo,tenant")


def test_un_rechazo_queda_fallido_con_su_porque(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    from crmcore.runtime import settings as rt

    from services.tenancy import facturacion

    _doble(monkeypatch, 422)
    rt.fijar(db, "facturacion_destino_url", "https://cobro.example/uso", ambito_id=str(tenant_id))
    c = facturacion.tomar_corte(db, tenant_id, medido=MEDIDO)
    salida = facturacion.enviar(db, c)
    assert salida["estado_envio"] == "fallido"
    assert salida["ultimo_error"].startswith("HTTP 422") and salida["intentos"] == 1


def test_la_tarea_rehace_el_corte_abierto_y_manda_el_del_periodo_cerrado(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    from crmcore.runtime import settings as rt
    from sqlalchemy import select

    from services.tenancy import facturacion

    recibido = _doble(monkeypatch, 200)
    tid = str(tenant_id)
    assert facturacion.barrer(db, tenant_id, medido=MEDIDO)["apagado"] is True

    rt.fijar(db, "facturacion_exportar_periodicamente", True, ambito_id=tid)
    rt.fijar(db, "facturacion_destino_url", "https://cobro.example/uso", ambito_id=tid)
    facturacion.barrer(db, tenant_id, medido=MEDIDO)
    facturacion.barrer(db, tenant_id, medido=MEDIDO)
    abiertos = (
        db.execute(
            select(facturacion.CorteConsumo).where(
                facturacion.CorteConsumo.tenant_id == tenant_id,
                facturacion.CorteConsumo.estado_envio == "abierto",
            )
        )
        .scalars()
        .all()
    )
    # El del periodo en curso es UNO: el último que se tomó.
    assert len(abiertos) == 1 and recibido == []

    # El periodo cierra: el abierto pasa a ser de un mes anterior y se manda.
    abiertos[0].periodo = "2000-01"
    db.flush()
    salida = facturacion.barrer(db, tenant_id, medido=MEDIDO)
    assert salida["enviados"] == 1 and len(recibido) == 1
    assert abiertos[0].estado_envio == "enviado"


def test_tomar_y_listar_cortes_por_http(
    cliente: Any, db: Any, tenant_id: UUID, monkeypatch: Any
) -> None:
    monkeypatch.setattr(
        "services.tenancy.facturacion.consumo_compuesto",
        lambda tid, principal_id=None: MEDIDO,
    )
    cab = _cabeceras(tenant_id)
    r = cliente.post("/api/v1/facturacion/cortes", headers=cab, json={"enviar": True})
    assert r.status_code == 200, r.text
    assert r.json()["estado_envio"] == "sin_destino"
    cid = r.json()["id"]
    r = cliente.get(f"/api/v1/facturacion/cortes/{cid}/exportar?formato=csv", headers=cab)
    assert r.status_code == 200, r.text
    assert r.json()["contenido"].startswith("periodo,tenant")
    assert r.json()["fichero"].endswith(".csv")
    r = cliente.get("/api/v1/facturacion/cortes", headers=cab)
    assert [c["id"] for c in r.json()["cortes"]] == [cid]
    assert cliente.get("/api/v1/facturacion/destino", headers=cab).json()["configurado"] is False


def test_un_modulo_que_no_contesta_va_a_no_leidos_y_no_vale_cero(monkeypatch: Any) -> None:
    import httpx

    from services.tenancy import facturacion

    monkeypatch.setattr(
        "crmcore.config.get_settings",
        lambda: type(
            "S",
            (),
            {
                "rutas_servicios": "sales=http://s,marketing=http://m,gateway=http://g",
                "http_interno_timeout_s": 1.0,
                "secret_key": type("K", (), {"get_secret_value": lambda self: "x" * 40})(),
            },
        )(),
    )

    class _R:
        status_code = 200

        @staticmethod
        def json() -> dict[str, Any]:
            return {
                "metricas": [
                    {"metrica": "registros", "consumido": 3, "limite": 10, "sin_limite": False}
                ]
            }

    def _get(url: str, **_: Any) -> Any:
        if "//m" in url:
            raise httpx.ConnectError("caído")
        assert "//g" not in url, "al gateway no se le pregunta: él también suma"
        return _R()

    monkeypatch.setattr(httpx, "get", _get)
    salida = facturacion.consumo_compuesto(uuid4(), principal_id=None)
    assert salida["no_leidos"] == ["marketing"]
    assert salida["filas"] == [
        {
            "periodo": "",
            "modulo": "sales",
            "metrica": "registros",
            "cantidad": 3,
            "unidad": "unidades",
            "tope": 10,
        }
    ]


def test_reenviar_un_corte_y_ver_el_agregado_por_http(
    cliente: Any, db: Any, tenant_id: UUID, monkeypatch: Any
) -> None:
    """Las dos rutas cuya forma lee la pantalla y que no pedía ninguna prueba."""
    monkeypatch.setattr(
        "services.tenancy.facturacion.consumo_compuesto",
        lambda tid, principal_id=None: MEDIDO,
    )
    cab = _cabeceras(tenant_id)
    cid = cliente.post("/api/v1/facturacion/cortes", headers=cab, json={}).json()["id"]
    r = cliente.post(f"/api/v1/facturacion/cortes/{cid}/enviar", headers=cab)
    assert r.status_code == 200, r.text
    assert r.json()["estado_envio"] == "sin_destino"
    assert set(r.json()) >= {"id", "periodo", "estado_envio", "intentos", "ultimo_error"}

    matriz = _tenant(db, "MatrizAgregado")
    _tenant(db, "HijaCallada", padre=matriz, relacion="holding")
    db.commit()
    r = cliente.get(
        f"/api/v1/tenants/{matriz.id}/jerarquia/agregado", headers=_cabeceras(matriz.id)
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["no_comparten"] == ["HijaCallada"]
    assert cuerpo["hijas"][0]["consumo"] is None
    assert set(cuerpo["totales"]) == {"consumo", "indicadores"}
