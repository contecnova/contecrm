"""Todo lo que hay en la aplicación, controlado por el GRC (CRM-07.03.02.12 a .15).

Pedido el 09-11-2026. Medido ese día en el tenant de plataforma: 0 de 781
capacidades hechas con control, la segregación sin enlazar con el GRC, del TCSEC
sólo los cuatro requisitos atestiguados y ninguna revisión de accesos. Una prueba
por comportamiento nuevo, y las rutas que piden las pantallas, por HTTP.

Lo de identity se le pide a tenancy por HTTP firmado; aquí se sustituye esa
llamada (`grc_serie._pedir`) por lo que contestaría identity, porque la prueba
es de lo que el GRC hace con la respuesta.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterator
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


def _app(nombre: str) -> Iterator[Any]:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        with TestClient(importlib.import_module(nombre).app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


@pytest.fixture
def tenancy(db: Any) -> Iterator[Any]:
    yield from _app("services.tenancy.main")


@pytest.fixture
def identidad(db: Any) -> Iterator[Any]:
    yield from _app("services.identity.main")


@pytest.fixture
def quien() -> UUID:
    return uuid4()


@pytest.fixture
def cabeceras(tenant_id: UUID, quien: UUID) -> dict[str, str]:
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
            H_USER: str(quien),
            H_PERMISOS: "*:*",
            H_ROLES: "admin",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


class Identidad:
    """Lo que contestaría identity a tenancy, editable entre llamadas."""

    def __init__(self) -> None:
        manana = (date.today() + timedelta(days=30)).isoformat()
        self.usuario = str(uuid4())
        self.exento = str(uuid4())
        self.reglas = [
            {
                "codigo": "SOD-X",
                "nombre": "Pedir y aprobar",
                "descripcion": "",
                "permisos_a": ["quote:write"],
                "permisos_b": ["aprobacion:decidir"],
                "nivel": "critico",
                "activa": True,
            }
        ]
        self.violaciones = [
            {"usuario_id": self.usuario, "regla": "SOD-X", "nombre": "Pedir y aprobar",
             "nivel": "critico", "por_el_lado_a": ["quote:write"],
             "por_el_lado_b": ["aprobacion:decidir"], "exceptuado": False},
            {"usuario_id": self.exento, "regla": "SOD-X", "nombre": "Pedir y aprobar",
             "nivel": "critico", "por_el_lado_a": ["quote:write"],
             "por_el_lado_b": ["aprobacion:decidir"], "exceptuado": True},
        ]  # fmt: skip
        self.excepciones = [
            {"id": str(uuid4()), "regla_codigo": "SOD-X", "usuario_id": self.exento,
             "motivo": "Es todo el departamento", "aprobada_por": None,
             "caduca_at": manana, "vigente": True},
        ]  # fmt: skip
        self.informes: dict[str, Any] = {}
        self.resumen: dict[str, Any] | None = None

    def __call__(self, cache: Any, *, ruta: str, parametros: Any = None, **_: Any) -> Any:
        if ruta == "/api/v1/segregacion/reglas":
            return self.reglas
        if ruta == "/api/v1/segregacion/violaciones":
            return {"reglas": len(self.reglas), "violaciones": self.violaciones}
        if ruta == "/api/v1/segregacion/excepciones":
            return self.excepciones
        if ruta == "/api/v1/usuarios":
            return {"items": [{"id": self.usuario, "nombre": "Ana"}]}
        if ruta == "/api/v1/recertificacion/resumen":
            return self.resumen
        return self.informes.get(ruta)


@pytest.fixture
def identity(monkeypatch: pytest.MonkeyPatch) -> Identidad:
    from services.tenancy import grc_serie

    falsa = Identidad()
    monkeypatch.setattr(grc_serie, "_pedir", falsa)
    return falsa


def _cobertura(tenancy: Any, cabeceras: dict[str, str]) -> dict[str, Any]:
    r = tenancy.get("/api/v1/grc/cobertura?solo_hechas=true", headers=cabeceras)
    assert r.status_code == 200, r.text
    return r.json()


# ── CRM-07.03.02.12 · Controles de serie por familia ──────────────────────


def test_los_de_serie_se_instalan_y_no_pisan_lo_ajustado_crm_07_03_02_12(
    tenancy: Any, cabeceras: dict[str, str], contexto_tenant: UUID, identity: Identidad
) -> None:
    from services.tenancy import grc_serie

    assert _cobertura(tenancy, cabeceras)["con_control"] == 0
    r = tenancy.post("/api/v1/grc/de-serie", headers=cabeceras)
    assert r.status_code == 200, r.text
    familias = grc_serie.familias()
    assert r.json()["controles"]["familia"]["creado"] == len(familias)
    assert r.json()["controles"]["tcsec"]["creado"] == 15
    # Anclados a TODAS las capacidades hechas: la cobertura anclada es total.
    cob = _cobertura(tenancy, cabeceras)
    assert cob["con_control"] == cob["capacidades"]

    # Desactivar uno lo deja ajustado, y reinstalar no lo vuelve a encender.
    codigo = grc_serie.codigo_de_familia(next(iter(familias)))
    r = tenancy.post(
        f"/api/v1/grc/controles/{codigo}/activo", headers=cabeceras, json={"activo": False}
    )
    assert r.status_code == 200 and r.json()["ajustado"] is True, r.text
    r = tenancy.post("/api/v1/grc/de-serie", headers=cabeceras)
    assert r.json()["controles"]["familia"]["respetado"] == 1, r.text
    detalle = tenancy.get(f"/api/v1/grc/controles/{codigo}", headers=cabeceras).json()
    assert detalle["activo"] is False and detalle["origen"] == "familia"
    assert _cobertura(tenancy, cabeceras)["con_control"] < cob["capacidades"]


def test_anclado_no_es_verificado_crm_07_03_02_12(
    tenancy: Any,
    cabeceras: dict[str, str],
    contexto_tenant: UUID,
    identity: Identidad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La cobertura verificada sólo cuenta lo que una evaluación comprobó."""
    from crmcore.catalogo import capacidades

    from services.tenancy import grc_serie

    tenancy.post("/api/v1/grc/de-serie", headers=cabeceras)
    assert _cobertura(tenancy, cabeceras)["verificadas"] == 0

    # Una familia con capacidades de un servicio desplegado, con y sin `visto`.
    cat = capacidades()
    familia, datos = next(
        (f, d)
        for f, d in grc_serie.familias().items()
        if len({cat[c]["servicio"] for c in d["capacidades"]}) == 1
        and any(cat[c]["visto"] for c in d["capacidades"])
        and not all(cat[c]["visto"] for c in d["capacidades"])
    )
    servicio = cat[datos["capacidades"][0]]["servicio"]
    monkeypatch.setattr(grc_serie, "_servicios_desplegados", lambda: {servicio})
    ruta = f"/api/v1/{servicio}/cumplimiento/informe"
    identity.informes[ruta] = {
        "integridad_del_audit_trail": {"verificacion": {"intacta": True, "apuntes": 5}}
    }
    codigo = grc_serie.codigo_de_familia(familia)
    r = tenancy.post(f"/api/v1/grc/controles/{codigo}/evaluar-automatico", headers=cabeceras)
    assert r.status_code == 200, r.text
    assert r.json()["resultado"] == "parcial" and r.json()["plan_accion"]
    con_visto = {c for c in datos["capacidades"] if cat[c]["visto"]}
    assert _cobertura(tenancy, cabeceras)["verificadas"] == len(con_visto)

    # La cadena rota no verifica nada de ese servicio.
    identity.informes[ruta] = {
        "integridad_del_audit_trail": {
            "verificacion": {"intacta": False, "apuntes": 5, "rota_en": 3}
        }
    }
    r = tenancy.post(f"/api/v1/grc/controles/{codigo}/evaluar-automatico", headers=cabeceras)
    assert r.json()["resultado"] == "inefectivo", r.text
    assert _cobertura(tenancy, cabeceras)["verificadas"] == 0


# ── CRM-07.03.02.13 · La segregación dentro del GRC ───────────────────────


def test_la_segregacion_deja_control_hallazgo_y_evidencia_crm_07_03_02_13(
    tenancy: Any, cabeceras: dict[str, str], contexto_tenant: UUID, identity: Identidad
) -> None:
    r = tenancy.post("/api/v1/grc/segregacion/sincronizar", headers=cabeceras)
    assert r.status_code == 200, r.text

    control = tenancy.get("/api/v1/grc/controles/SOD-X", headers=cabeceras).json()
    assert control["tipo"] == "preventivo" and control["referencia"] == "SOD-X"
    assert control["riesgos"] == ["R-SOD-X"]
    riesgos = tenancy.get("/api/v1/grc/riesgos", headers=cabeceras).json()
    # Critico: probabilidad 4 e impacto 5 con el ajuste de fábrica.
    assert next(x for x in riesgos if x["codigo"] == "R-SOD-X")["inherente"] == 20

    # Sólo el conflicto SIN excepción es hallazgo, contra el riesgo de la regla.
    abiertos = tenancy.get("/api/v1/grc/hallazgos", headers=cabeceras).json()
    assert [h["sujeto_id"] for h in abiertos] == [identity.usuario]
    assert abiertos[0]["riesgo"] == "R-SOD-X" and "Ana" in abiertos[0]["titulo"]
    # Y la excepción aprobada es una evidencia que caduca con ella.
    evidencias = tenancy.get("/api/v1/grc/evidencias?control=SOD-X", headers=cabeceras).json()
    assert evidencias[0]["caduca_at"] == identity.excepciones[0]["caduca_at"]
    assert evidencias[0]["vigente"] is True

    # Evaluar: la evidencia la pone el sistema y el conflicto lo hace inefectivo.
    r = tenancy.post("/api/v1/grc/controles/SOD-X/evaluar-automatico", headers=cabeceras)
    assert r.json()["resultado"] == "inefectivo" and r.json()["evidencia"]["sin_exceptuar"] == 1

    # Resuelto en identity: el hallazgo se cierra diciendo por qué.
    identity.violaciones = [v for v in identity.violaciones if v["exceptuado"]]
    tenancy.post("/api/v1/grc/segregacion/sincronizar", headers=cabeceras)
    assert tenancy.get("/api/v1/grc/hallazgos", headers=cabeceras).json() == []
    cerrado = tenancy.get("/api/v1/grc/hallazgos?estado=cerrado", headers=cabeceras).json()
    assert cerrado[0]["motivo_cierre"] == "resuelto"


# ── CRM-07.03.02.14 · TCSEC entero en el GRC ──────────────────────────────


def test_lo_medido_del_tcsec_deja_evidencia_y_lo_sin_medir_no_se_evalua_crm_07_03_02_14(
    tenancy: Any,
    cabeceras: dict[str, str],
    contexto_tenant: UUID,
    identity: Identidad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from services.tenancy import tcsec

    estados = {"C1-IA": tcsec.CUMPLE, "C1-DAC": tcsec.SIN_MEDIR}
    nuevos = tuple(
        replace(r, comprobar=lambda ctx, e=estados[r.clave]: (e, f"medido: {e}", {"n": 1}))
        if r.clave in estados
        else r
        for r in tcsec.REQUISITOS
    )
    monkeypatch.setattr(tcsec, "REQUISITOS", nuevos)
    monkeypatch.setattr(tcsec, "_POR_CLAVE", {r.clave: r for r in nuevos})
    tenancy.post("/api/v1/grc/de-serie", headers=cabeceras)

    r = tenancy.post("/api/v1/grc/controles/TCSEC-C1-IA/evaluar-automatico", headers=cabeceras)
    assert r.json()["resultado"] == "efectivo", r.text
    assert r.json()["evidencia"]["requisito"] == "C1-IA"
    assert r.json()["evidencia"]["estado"] == tcsec.CUMPLE

    r = tenancy.post("/api/v1/grc/controles/TCSEC-C1-DAC/evaluar-automatico", headers=cabeceras)
    assert r.json()["evaluado"] is False, r.text
    detalle = tenancy.get("/api/v1/grc/controles/TCSEC-C1-DAC", headers=cabeceras).json()
    assert detalle["evaluaciones"] == []
    # Los atestiguados siguen siendo de una persona: sin fuente automática.
    canales = tenancy.get("/api/v1/grc/controles/TCSEC-B2-CANALES", headers=cabeceras).json()
    assert canales["fuente_evidencia"] == "" and canales["origen"] == "tcsec"


# ── CRM-07.03.02.15 · Revisión periódica de accesos ───────────────────────


def _alta(identidad: Any, cabeceras: dict[str, str], email: str, roles: list[str]) -> str:
    r = identidad.post(
        "/api/v1/usuarios",
        headers=cabeceras,
        json={"email": email, "nombre": email.split("@")[0], "roles": roles},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_retirar_en_la_revision_quita_el_acceso_crm_07_03_02_15(
    db: Any,
    identidad: Any,
    cabeceras: dict[str, str],
    contexto_tenant: UUID,
    tenant_id: UUID,
    quien: UUID,
) -> None:
    from sqlalchemy import select

    from services.identity.modelos import Membresia

    persona = _alta(identidad, cabeceras, "rev@example.com", ["comercial", "soporte"])
    r = identidad.post(
        "/api/v1/recertificacion/campanas",
        headers=cabeceras,
        json={"nombre": "T4", "plazo_dias": 7, "revisor_por_defecto": str(quien)},
    )
    assert r.status_code == 201, r.text
    assert r.json()["total"] == 2 and r.json()["pendientes"] == 2

    mias = identidad.get("/api/v1/recertificacion/mias", headers=cabeceras).json()
    suyas = {x["valor"]: x["id"] for x in mias[0]["revisiones"] if x["usuario_id"] == persona}

    sin_motivo = identidad.post(
        f"/api/v1/recertificacion/revisiones/{suyas['comercial']}/decision",
        headers=cabeceras,
        json={"decision": "retirado"},
    )
    assert sin_motivo.status_code == 422, sin_motivo.text
    r = identidad.post(
        f"/api/v1/recertificacion/revisiones/{suyas['comercial']}/decision",
        headers=cabeceras,
        json={"decision": "retirado", "comentario": "Cambió de puesto"},
    )
    assert r.status_code == 200, r.text
    m = db.execute(
        select(Membresia).where(
            Membresia.tenant_id == tenant_id, Membresia.usuario_id == UUID(persona)
        )
    ).scalar_one()
    db.refresh(m)
    assert m.roles == ["soporte"], "la retirada no se aplicó en la membresía"

    # Sólo contesta su responsable.
    from crmcore.config import get_settings
    from crmcore.http.deps import H_PERMISOS, H_TENANT, H_USER, firmar_cabeceras_internas

    otro = firmar_cabeceras_internas(
        {H_TENANT: str(tenant_id), H_USER: str(uuid4()), H_PERMISOS: "*:*"},
        get_settings().secret_key.get_secret_value(),
    )
    r = identidad.post(
        f"/api/v1/recertificacion/revisiones/{suyas['soporte']}/decision",
        headers=otro,
        json={"decision": "confirmado"},
    )
    assert r.status_code == 403, r.text


def test_lo_no_contestado_a_tiempo_se_marca_y_se_avisa_crm_07_03_02_15(
    db: Any,
    identidad: Any,
    cabeceras: dict[str, str],
    contexto_tenant: UUID,
    tenant_id: UUID,
    quien: UUID,
) -> None:
    from crmcore.datos.seguimiento import Notificacion
    from sqlalchemy import select

    from services.identity import recertificacion as rec

    _alta(identidad, cabeceras, "tarde@example.com", ["comercial"])
    r = identidad.post(
        "/api/v1/recertificacion/campanas",
        headers=cabeceras,
        json={"nombre": "Tarde", "revisor_por_defecto": str(quien)},
    )
    campana = db.get(rec.CampanaRecertificacion, UUID(r.json()["id"]))
    campana.plazo_at = date.today() - timedelta(days=1)
    db.flush()

    r = identidad.post("/api/v1/recertificacion/vencidas", headers=cabeceras)
    assert r.status_code == 200 and r.json()["marcadas"] == 1, r.text
    avisos = db.execute(
        select(Notificacion).where(
            Notificacion.tenant_id == tenant_id,
            Notificacion.usuario_id == quien,
            Notificacion.tipo == "recertificacion.pendiente",
            Notificacion.prioridad == "alta",
        )
    ).scalars()
    assert list(avisos), "el responsable no recibió el aviso de fuera de plazo"
    resumen = identidad.get("/api/v1/recertificacion/resumen", headers=cabeceras).json()
    assert resumen["en_curso"][0]["vencidas"] == 1


def test_la_campana_cerrada_es_la_evidencia_del_control_de_accesos_crm_07_03_02_15(
    tenancy: Any, cabeceras: dict[str, str], contexto_tenant: UUID, identity: Identidad
) -> None:
    tenancy.post("/api/v1/grc/de-serie", headers=cabeceras)
    identity.resumen = {"ultima_cerrada": None, "cerradas": [], "en_curso": []}
    r = tenancy.post("/api/v1/grc/controles/REC-ACCESOS/evaluar-automatico", headers=cabeceras)
    assert r.json()["resultado"] == "inefectivo", r.text

    cerrada = {
        "id": str(uuid4()),
        "nombre": "Q4",
        "cerrada_at": datetime.now(timezone.utc).isoformat(),
        "total": 3,
        "confirmados": 2,
        "retirados": 1,
        "vencidas": 0,
    }
    identity.resumen = {"ultima_cerrada": cerrada, "cerradas": [cerrada], "en_curso": []}
    r = tenancy.post("/api/v1/grc/controles/REC-ACCESOS/evaluar-automatico", headers=cabeceras)
    assert r.json()["resultado"] == "efectivo", r.text
    evidencias = tenancy.get("/api/v1/grc/evidencias?control=REC-ACCESOS", headers=cabeceras).json()
    assert evidencias[0]["referencia"] == cerrada["id"]
    assert evidencias[0]["caduca_at"] == (date.today() + timedelta(days=91)).isoformat()
