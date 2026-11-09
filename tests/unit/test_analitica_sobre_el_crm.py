"""Cohortes, embudo y actividad con los datos del CRM; instantáneas programadas;
consulta federada ejecutada (CRM-05.01.03.04, .05, .06, .07 · CRM-05.01.01.05).

Medido el 09-11-2026: los tres análisis calculaban sobre lo que se tecleara en
el cuerpo, las instantáneas sólo se tomaban a mano y la consulta federada
devolvía un plan que no traducía nadie. Todo «hecho» y nada funcionando.

Las pruebas van por HTTP —la forma que lee la pantalla— y el resto de servicios
se sustituye en `interno.invocar`, que es la única puerta por la que analytics
les pregunta: así se comprueba también que se pregunta con la identidad de quien
pide y con los filtros que tocan.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterator
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

from services.analytics import cohortes as coh

# ── El embudo cuenta las etapas saltadas (sin base de datos) ──────────────


def test_saltarse_una_etapa_cuenta_como_haberla_pasado() -> None:
    """Sin esto, la etapa saltada sale con menos llegadas que la siguiente y una
    conversión por encima del 100 %."""
    recorridos = [
        {
            "id": "1",
            "pasos": [{"etapa": "a", "fecha": "2026-01-01"}, {"etapa": "c", "fecha": "2026-01-05"}],
        },
        {
            "id": "2",
            "pasos": [{"etapa": "a", "fecha": "2026-01-01"}, {"etapa": "b", "fecha": "2026-01-03"}],
        },
    ]
    sin = coh.embudo(etapas=["a", "b", "c"], recorridos=recorridos)
    con = coh.embudo(etapas=["a", "b", "c"], recorridos=recorridos, contar_saltadas=True)
    assert [e["llegaron"] for e in sin["etapas"]] == [2, 1, 1]
    assert sin["etapas"][2]["conversion_desde_anterior"] == 100.0
    assert [e["llegaron"] for e in con["etapas"]] == [2, 2, 1]
    assert con["etapas"][2]["conversion_desde_anterior"] == 50.0


# ── El andamio HTTP ───────────────────────────────────────────────────────


@pytest.fixture
def analytics(db: Any) -> Iterator[Any]:
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        from services.analytics.main import app

        with TestClient(app) as cli:
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


HOY = datetime.now(timezone.utc).date()
COMERCIALES = [str(uuid4()) for _ in range(9)]
ETAPAS = [
    {"id": str(uuid4()), "nombre": "Calificar", "orden": 1, "terminal": False, "ganada": False},
    {"id": str(uuid4()), "nombre": "Proponer", "orden": 2, "terminal": False, "ganada": False},
    {"id": str(uuid4()), "nombre": "Ganada", "orden": 3, "terminal": True, "ganada": True},
    {"id": str(uuid4()), "nombre": "Perdida", "orden": 4, "terminal": True, "ganada": False},
]
PIPELINE = {"id": str(uuid4()), "nombre": "Ventas", "por_defecto": True, "etapas": ETAPAS}


def _iso(d: date) -> str:
    return datetime(d.year, d.month, d.day, 10, tzinfo=timezone.utc).isoformat()


def _crm() -> dict[str, Any]:
    """Un CRM pequeño y coherente: cuentas, actividades y oportunidades."""
    cuentas = [{"id": f"c{i}", "created_at": _iso(HOY - timedelta(days=200 + i))} for i in range(6)]
    actividades = []
    for i, uid in enumerate(COMERCIALES):
        for k in range(i + 1):
            actividades.append(
                {
                    "id": f"a{i}-{k}",
                    "cuenta_id": f"c{k % 6}",
                    "asignada_a": uid,
                    "created_at": _iso(HOY - timedelta(days=10 + k)),
                }
            )
    oportunidades = []
    historiales: dict[str, list[dict[str, Any]]] = {}
    for i, uid in enumerate(COMERCIALES):
        for k in range(i // 2 + (1 if i % 3 else 0)):
            oid = f"o{i}-{k}"
            oportunidades.append(
                {
                    "id": oid,
                    "pipeline_id": PIPELINE["id"],
                    "cuenta_id": f"c{k % 6}",
                    "owner_id": uid,
                    "estado": "ganada",
                    "estado_significa": "ganado",
                    "fecha_cierre_real": str(HOY - timedelta(days=5)),
                    "importe": "1000",
                    "created_at": _iso(HOY - timedelta(days=40)),
                }
            )
            # Una de cada dos se salta «Proponer».
            pasos = [ETAPAS[0], ETAPAS[2]] if k % 2 else [ETAPAS[0], ETAPAS[1], ETAPAS[2]]
            historiales[oid] = [
                {"etapa_hasta_id": e["id"], "created_at": _iso(HOY - timedelta(days=40 - 7 * n))}
                for n, e in enumerate(pasos)
            ]
    abierta = {
        "id": "abierta",
        "pipeline_id": PIPELINE["id"],
        "cuenta_id": "c0",
        "owner_id": COMERCIALES[0],
        "estado": "abierta",
        "estado_significa": "abierto",
        "created_at": _iso(HOY - timedelta(days=3)),
    }
    oportunidades.append(abierta)
    historiales["abierta"] = [
        {"etapa_hasta_id": ETAPAS[0]["id"], "created_at": _iso(HOY - timedelta(days=3))}
    ]
    return {
        "cuentas": cuentas,
        "actividades": actividades,
        "oportunidades": oportunidades,
        "historiales": historiales,
    }


@pytest.fixture
def llamadas(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Sustituye la puerta a los demás servicios y apunta cada llamada."""
    from crmcore.http import interno

    crm = _crm()
    apuntadas: list[dict[str, Any]] = []

    def falso(**kw: Any) -> dict[str, Any]:
        apuntadas.append(kw)
        ruta = kw["ruta"]
        if ruta == "/api/v1/accounts":
            return {
                "estado": 200,
                "ok": True,
                "datos": {"items": crm["cuentas"], "siguiente": None},
            }
        if ruta == "/api/v1/activities":
            return {"estado": 200, "ok": True, "datos": {"items": crm["actividades"]}}
        if ruta == "/api/v1/opportunities":
            return {"estado": 200, "ok": True, "datos": {"items": crm["oportunidades"]}}
        if ruta == "/api/v1/pipelines":
            return {"estado": 200, "ok": True, "datos": {"items": [PIPELINE]}}
        if ruta.endswith("/historial-etapas"):
            oid = ruta.split("/")[-2]
            return {"estado": 200, "ok": True, "datos": crm["historiales"].get(oid, [])}
        if "/integraciones/conexiones/" in ruta:
            n = int(kw["cuerpo"]["parametros"]["limite"]) + 5
            return {
                "estado": 200,
                "ok": True,
                "datos": {
                    "registros": [{"numero": i, "importe": i * 10, "x": 1} for i in range(n)]
                },
            }
        return {"estado": 404, "ok": False, "datos": {}}

    monkeypatch.setattr(interno, "invocar", falso)
    return apuntadas


pytestmark = pytest.mark.db


# ── Cohortes (CRM-05.01.03.04) ────────────────────────────────────────────


def test_la_cohorte_sale_de_las_cuentas_reales_y_dice_de_donde(
    analytics: Any, cabeceras: dict[str, str], llamadas: list[dict[str, Any]], usuario: UUID
) -> None:
    r = analytics.get("/api/v1/analisis/crm/cohortes?periodo=mes&periodos=3", headers=cabeceras)
    assert r.status_code == 200, r.text
    d = r.json()
    assert sum(c["sujetos"] for c in d["cohortes"]) == 6
    assert d["sujeto"] == "cuenta"
    assert d["procedencia"]["cuenta"]["fuente"] == "api"
    assert d["procedencia"]["cuenta"]["leidos"] == 6
    # Se pregunta con la identidad de quien pide, no con la de «la casa».
    assert all(str(c["principal_id"]) == str(usuario) for c in llamadas)
    assert all(c["tipo"] == "usuario" for c in llamadas)


def test_la_cohorte_lee_del_almacen_si_esta_cargado(
    analytics: Any,
    cabeceras: dict[str, str],
    llamadas: list[dict[str, Any]],
    db: Any,
    tenant_id: UUID,
) -> None:
    from crmcore.db.uow import UnidadDeTrabajo

    from services.analytics import almacen as alm

    uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
    alm.declarar_tabla(
        uow,
        clave="cuentas-anl",
        objeto="cuenta",
        columnas=[{"nombre": "created_at", "tipo": "fecha"}],
    )
    alm.cargar(
        uow,
        tabla="cuentas-anl",
        filas=[
            {"clave_origen": f"x{i}", "created_at": _iso(HOY - timedelta(days=90))}
            for i in range(4)
        ],
    )
    db.commit()
    r = analytics.get("/api/v1/analisis/crm/cohortes", headers=cabeceras)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["procedencia"]["cuenta"]["fuente"] == "almacen"
    assert sum(c["sujetos"] for c in d["cohortes"]) == 4
    assert not any(c["ruta"] == "/api/v1/accounts" for c in llamadas)


# ── Embudo (CRM-05.01.03.05) ──────────────────────────────────────────────


def test_el_embudo_sale_del_historial_de_etapas_sin_la_de_perdida(
    analytics: Any, cabeceras: dict[str, str], llamadas: list[dict[str, Any]]
) -> None:
    r = analytics.get("/api/v1/analisis/crm/embudo", headers=cabeceras)
    assert r.status_code == 200, r.text
    d = r.json()
    assert [e["etapa"] for e in d["etapas"]] == ["Calificar", "Proponer", "Ganada"]
    ganadas = len([o for o in _crm()["oportunidades"] if o["estado"] == "ganada"])
    assert d["etapas"][0]["llegaron"] == ganadas + 1
    # Las que se saltaron «Proponer» cuentan como pasadas por ella.
    assert d["etapas"][1]["llegaron"] == ganadas
    assert d["etapas"][2]["llegaron"] == ganadas
    assert d["abiertos"] == 1
    assert d["pipeline"]["nombre"] == "Ventas"
    assert d["etapas"][0]["dias_mediana"] is not None
    # Al listado de oportunidades se le pide TODO, no sólo las abiertas.
    opp = [c for c in llamadas if c["ruta"] == "/api/v1/opportunities"]
    assert opp and opp[0]["parametros"]["estado"] == ""


# ── Actividad y resultados (CRM-05.01.03.06) ──────────────────────────────


def test_la_actividad_se_cruza_con_lo_ganado_por_persona(
    analytics: Any, cabeceras: dict[str, str], llamadas: list[dict[str, Any]]
) -> None:
    r = analytics.get("/api/v1/analisis/crm/actividad", headers=cabeceras)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["medible"] is True
    assert d["sujetos"] == 9
    assert "Correlación no es causa" in d["aviso"]
    por = {p["id"]: p for p in d["por_persona"]}
    assert por[COMERCIALES[8]]["actividades"] == 9
    # Las actividades se piden ya acotadas a la ventana.
    act = [c for c in llamadas if c["ruta"] == "/api/v1/activities"]
    assert act[0]["parametros"]["created_at__desde"] == d["desde"]


def test_sin_permiso_para_leer_se_dice_y_no_se_calcula_sobre_vacio(
    analytics: Any, cabeceras: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from crmcore.http import interno

    monkeypatch.setattr(interno, "invocar", lambda **kw: {"estado": 403, "ok": False, "datos": {}})
    d = analytics.get("/api/v1/analisis/crm/actividad", headers=cabeceras).json()
    assert d["medible"] is False
    assert d["procedencia"]["actividad"]["sin_permiso"] is True


# ── Instantáneas programadas (CRM-05.01.01.05) ────────────────────────────


def test_una_instantanea_se_programa_sin_destino_y_el_barrido_la_toma(
    analytics: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    from crmcore.db.uow import UnidadDeTrabajo

    from services.analytics import informes as inf

    fila = inf.Informe(
        tenant_id=tenant_id,
        clave=f"i-{uuid4().hex[:6]}",
        nombre="Pipeline",
        objeto="oportunidad",
        tipo="tabular",
        columnas=["nombre", "importe"],
    )
    db.add(fila)
    db.commit()
    r = analytics.post(
        f"/api/v1/informes/{fila.id}/programar",
        json={"periodicidad": "diaria", "hora": 6, "accion": "instantanea"},
        headers=cabeceras,
    )
    assert r.status_code == 201, r.text
    programacion_id = r.json()["id"]

    lista = analytics.get("/api/v1/informes/programaciones", headers=cabeceras).json()
    mia = next(p for p in lista["programaciones"] if p["id"] == programacion_id)
    assert mia["accion"] == "instantanea"
    assert mia["proxima_at"]

    # Un envío sin destino sigue sin poder programarse.
    r = analytics.post(
        f"/api/v1/informes/{fila.id}/programar", json={"accion": "enviar"}, headers=cabeceras
    )
    assert r.status_code == 422

    previo = inf._EJECUTOR
    inf.registrar_ejecutor(lambda plan, tenant_id: {"filas": [{"importe": 5}, {"importe": 7}]})
    try:
        uow = UnidadDeTrabajo(db=db, tenant_id=tenant_id)
        prog = db.get(inf.ProgramacionInforme, UUID(programacion_id))
        prog.proxima_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.flush()
        salida = inf.correr_programadas(uow, tenant_id)
    finally:
        inf._EJECUTOR = previo
    assert salida["mandados"][0]["instantanea"]
    assert prog.proxima_at > datetime.now(timezone.utc)
    db.commit()

    t = analytics.get(f"/api/v1/informes/{fila.id}/tendencia", headers=cabeceras).json()
    assert t["cuantos"] == 1
    assert t["puntos"][0]["totales"]["importe"] == "12"

    r = analytics.delete(f"/api/v1/informes/programaciones/{programacion_id}", headers=cabeceras)
    assert r.status_code == 204
    lista = analytics.get("/api/v1/informes/programaciones", headers=cabeceras).json()
    assert all(p["id"] != programacion_id for p in lista["programaciones"])


# ── Consulta federada ejecutada (CRM-05.01.03.07) ─────────────────────────


def _fuente(analytics: Any, cabeceras: dict[str, str], config: dict[str, Any]) -> str:
    clave = f"lake-{uuid4().hex[:6]}"
    r = analytics.post(
        "/api/v1/almacen/federadas",
        json={
            "clave": clave,
            "tipo": "rest",
            "objetos": ["factura"],
            "config": config,
            "tope_filas": 20,
        },
        headers=cabeceras,
    )
    assert r.status_code == 201, r.text
    return clave


def test_la_consulta_federada_se_ejecuta_por_el_conector_y_se_recorta(
    analytics: Any, cabeceras: dict[str, str], llamadas: list[dict[str, Any]]
) -> None:
    conexion = str(uuid4())
    clave = _fuente(
        analytics, cabeceras, {"conexion_id": conexion, "operaciones": {"factura": "leer_facturas"}}
    )
    r = analytics.post(
        f"/api/v1/almacen/federadas/{clave}/consultar",
        json={"objeto": "factura", "campos": ["numero", "importe"], "limite": 500},
        headers=cabeceras,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["cuantas"] == 20
    assert d["recortado"] is True
    assert d["columnas"] == ["numero", "importe"]
    assert set(d["filas"][0]) == {"numero", "importe"}
    assert d["copiado"] is False
    llamada = llamadas[-1]
    assert llamada["ruta"] == (
        f"/api/v1/integraciones/conexiones/{conexion}/operaciones/leer_facturas/invocar"
    )
    assert llamada["cuerpo"]["parametros"]["limite"] == 20
    assert llamada["tipo"] == "usuario"


def test_la_fuente_sin_conector_lo_dice_y_un_objeto_no_declarado_no_se_consulta(
    analytics: Any, cabeceras: dict[str, str], llamadas: list[dict[str, Any]]
) -> None:
    clave = _fuente(analytics, cabeceras, {})
    r = analytics.post(
        f"/api/v1/almacen/federadas/{clave}/consultar",
        json={"objeto": "factura"},
        headers=cabeceras,
    )
    assert r.status_code == 422
    assert r.json()["error_code"] == "almacen.federada_sin_conector"
    r = analytics.post(
        f"/api/v1/almacen/federadas/{clave}/consultar",
        json={"objeto": "nominas"},
        headers=cabeceras,
    )
    assert r.status_code == 422
    assert not llamadas


def test_un_servicio_caido_no_tumba_el_analisis(
    analytics: Any, cabeceras: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin dirección para `party` el análisis contesta 200 y dice qué no pudo
    leer: un 503 dejaría la pantalla entera en blanco por un objeto."""
    from crmcore.errors import NoDisponible
    from crmcore.http import interno

    def caido(**kw: Any) -> dict[str, Any]:
        raise NoDisponible("sin dirección", error_code="interno.servicio_sin_direccion")

    monkeypatch.setattr(interno, "invocar", caido)
    for ruta in ("cohortes", "embudo", "actividad"):
        r = analytics.get(f"/api/v1/analisis/crm/{ruta}", headers=cabeceras)
        assert r.status_code == 200, (ruta, r.text)
    d = analytics.get("/api/v1/analisis/crm/cohortes", headers=cabeceras).json()
    assert d["procedencia"]["cuenta"]["no_leido"] is True
    assert d["procedencia"]["cuenta"]["estado_http"] == 503
