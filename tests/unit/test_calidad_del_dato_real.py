"""Calidad del dato sobre los registros reales, por HTTP (09-11-2026).

CRM-01.01.04.06 golden record · CRM-01.01.01.08 enriquecimiento · CRM-01.01.05.02
identidad entre canales · CRM-01.01.04.02 umbral por objeto · CRM-01.01.04.04
direcciones.

Medido el 09-11-2026: las cinco constaban hechas y calculaban sobre lo que se
tecleara en el cuerpo —o no las llamaba nadie—. El golden no guardaba; el
enriquecimiento no le preguntaba a ningún proveedor; `observar` y `unir` no
tenían quien los llamara, así que la tabla de señales estaba vacía y «proponer
uniones» contestaba lo mismo que si no hubiera duplicados; el umbral era uno
para todo; y ninguna dirección se normalizaba.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


@pytest.fixture
def cliente(monkeypatch: Any, db: Any) -> Any:
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
        modulo = importlib.import_module("services.party.main")
        with TestClient(modulo.app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


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


def _cuenta(cliente: Any, cabeceras: dict[str, str], **datos: Any) -> str:
    r = cliente.post("/api/v1/accounts", headers=cabeceras, json={"forzar": True, **datos})
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def _contacto(cliente: Any, cabeceras: dict[str, str], **datos: Any) -> str:
    r = cliente.post("/api/v1/contacts", headers=cabeceras, json={"forzar": True, **datos})
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


# ── Golden record (CRM-01.01.04.06) ───────────────────────────────────────


def test_el_golden_se_compone_de_los_registros_reales_y_se_guarda(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    sufijo = uuid4().hex[:6]
    buena = _cuenta(cliente, cabeceras, nombre=f"Golden Uno {sufijo}", telefono="910000001")
    repetida = _cuenta(
        cliente, cabeceras, nombre=f"Golden Uno bis {sufijo}", web="https://golden.example"
    )
    fusion = cliente.post(
        f"/api/v1/data-quality/accounts/{buena}/merge",
        headers=cabeceras,
        json={"absorbido_id": repetida, "motivo": "prueba"},
    )
    assert fusion.status_code == 200, fusion.text
    # El ERP dice otro teléfono, y es la fuente que manda en ese campo.
    linaje = cliente.post(
        "/api/v1/calidad-dato/linaje",
        headers=cabeceras,
        json={
            "objeto": "cuenta",
            "objeto_id": buena,
            "campo": "telefono",
            "fuente": "erp",
            "valor": "930000009",
        },
    )
    assert linaje.status_code == 200, linaje.text
    regla = cliente.put(
        "/api/v1/calidad-dato/golden/reglas/cuenta/telefono",
        headers=cabeceras,
        json={"estrategia": "mayor_confianza", "confianza_por_fuente": {"erp": 90, "crm": 60}},
    )
    assert regla.status_code == 200, regla.text

    candidatas = cliente.get("/api/v1/calidad-dato/golden/candidatas", headers=cabeceras)
    assert candidatas.status_code == 200, candidatas.text
    assert any(c["objeto_id"] == buena and c["fusionadas"] == 1 for c in candidatas.json())

    compuesto = cliente.post(
        f"/api/v1/calidad-dato/golden/cuenta/{buena}/componer",
        headers=cabeceras,
        json={"aplicar": False},
    )
    assert compuesto.status_code == 200, compuesto.text
    cuerpo = compuesto.json()
    assert cuerpo["valores"]["telefono"] == "930000009"
    assert cuerpo["procedencia"]["telefono"]["fuente"] == "erp"
    assert cuerpo["procedencia"]["telefono"]["regla"] == "propia del campo"
    # La web sólo la traía la fusionada: su foto de antes cuenta como fuente.
    fuentes_web = {c["fuente"] for c in cuerpo["procedencia"]["web"]["candidatos"]}
    assert "fusionada" in fuentes_web or "crm" in fuentes_web
    assert cuerpo["fusionadas"] == 1
    # Componer no toca la ficha.
    ficha = cliente.get(f"/api/v1/accounts/{buena}", headers=cabeceras).json()
    assert ficha["telefono"] != "930000009"

    aplicado = cliente.post(
        f"/api/v1/calidad-dato/golden/cuenta/{buena}/componer",
        headers=cabeceras,
        json={"aplicar": True},
    )
    assert aplicado.status_code == 200, aplicado.text
    assert any(c["campo"] == "telefono" for c in aplicado.json()["aplicados"])
    ficha = cliente.get(f"/api/v1/accounts/{buena}", headers=cabeceras).json()
    assert ficha["telefono"] == "930000009"

    guardado = cliente.get(f"/api/v1/calidad-dato/golden/cuenta/{buena}", headers=cabeceras)
    assert guardado.status_code == 200, guardado.text
    assert guardado.json()["aplicado_at"]
    reglas = cliente.get("/api/v1/calidad-dato/golden/reglas/cuenta", headers=cabeceras).json()
    assert [r["campo"] for r in reglas["reglas"]] == ["telefono"]
    assert "telefono" in reglas["campos"]


def test_una_estrategia_inventada_no_se_guarda(cliente: Any, cabeceras: dict[str, str]) -> None:
    r = cliente.put(
        "/api/v1/calidad-dato/golden/reglas/cuenta/telefono",
        headers=cabeceras,
        json={"estrategia": "la_mas_bonita"},
    )
    assert r.status_code == 422, r.text


# ── Enriquecimiento (CRM-01.01.01.08) ─────────────────────────────────────


def test_pedir_revisar_y_aplicar_por_el_conector(
    cliente: Any, cabeceras: dict[str, str], monkeypatch: Any
) -> None:
    from crmcore.http import interno

    llamadas: list[dict[str, Any]] = []

    def falso(**kw: Any) -> dict[str, Any]:
        llamadas.append(kw)
        return {
            "ok": True,
            "estado": 200,
            "datos": {
                "registros": [{"industria": "6201", "sitio": "https://otra.example", "x": 1}]
            },
        }

    monkeypatch.setattr(interno, "invocar", falso)
    sufijo = uuid4().hex[:6]
    cuenta = _cuenta(
        cliente, cabeceras, nombre=f"Enriquecible {sufijo}", web="https://propia.example"
    )
    conexion = str(uuid4())
    perfil = cliente.put(
        "/api/v1/calidad-dato/enriquecimiento/perfiles/firmografico",
        headers=cabeceras,
        json={
            "nombre": "Datos de empresa",
            "objeto": "cuenta",
            "conexion_id": conexion,
            "operacion": "buscar_empresa",
            "parametros": {"nombre": "nombre"},
            "mapeo": {"sector_codigo": "industria", "web": "sitio"},
            "confianza": 45,
        },
    )
    assert perfil.status_code == 200, perfil.text
    perfiles = cliente.get("/api/v1/calidad-dato/enriquecimiento/perfiles", headers=cabeceras)
    assert perfiles.status_code == 200, perfiles.text
    assert {"clave", "nombre", "objeto", "operacion", "mapeo"} <= set(perfiles.json()[0])

    pedido = cliente.post(
        "/api/v1/calidad-dato/enriquecimiento/firmografico/pedir",
        headers=cabeceras,
        json={"objeto_ids": [cuenta]},
    )
    assert pedido.status_code == 200, pedido.text
    # Por el conector de la casa, con la identidad de quien pide.
    assert llamadas[0]["ruta"].endswith(
        f"/integraciones/conexiones/{conexion}/operaciones/buscar_empresa/invocar"
    )
    assert llamadas[0]["tipo"] == "usuario"
    assert llamadas[0]["cuerpo"]["parametros"]["nombre"].startswith("Enriquecible")
    propuesta = pedido.json()["resultados"][0]
    tipos = {c["campo"]: c["tipo"] for c in propuesta["campos"]}
    assert tipos == {"sector_codigo": "hueco", "web": "discrepancia"}

    pendientes = cliente.get(
        "/api/v1/calidad-dato/enriquecimiento/propuestas", headers=cabeceras
    ).json()
    assert any(p["id"] == propuesta["id"] for p in pendientes)

    # Sin elegir, sólo los huecos: la web que escribió alguien no se pisa.
    aplicada = cliente.post(
        f"/api/v1/calidad-dato/enriquecimiento/propuestas/{propuesta['id']}/aplicar",
        headers=cabeceras,
        json={},
    )
    assert aplicada.status_code == 200, aplicada.text
    ficha = cliente.get(f"/api/v1/accounts/{cuenta}", headers=cabeceras).json()
    assert ficha["sector_codigo"] == "6201"
    assert ficha["web"] == "https://propia.example"
    # Y con su procedencia en el linaje.
    linaje = cliente.get(f"/api/v1/calidad-dato/linaje/cuenta/{cuenta}", headers=cabeceras).json()
    assert any(
        f["fuente"] == "firmografico" and f["gana"] for f in linaje["campos"]["sector_codigo"]
    )
    otra_vez = cliente.post(
        f"/api/v1/calidad-dato/enriquecimiento/propuestas/{propuesta['id']}/descartar",
        headers=cabeceras,
    )
    assert otra_vez.status_code == 409, otra_vez.text


def test_si_el_proveedor_falla_se_dice(
    cliente: Any, cabeceras: dict[str, str], monkeypatch: Any
) -> None:
    from crmcore.http import interno

    monkeypatch.setattr(
        interno, "invocar", lambda **kw: {"ok": False, "estado": 502, "datos": {"title": "caído"}}
    )
    cuenta = _cuenta(cliente, cabeceras, nombre=f"Sin proveedor {uuid4().hex[:6]}")
    cliente.put(
        "/api/v1/calidad-dato/enriquecimiento/perfiles/caido",
        headers=cabeceras,
        json={
            "nombre": "Caído",
            "conexion_id": str(uuid4()),
            "operacion": "x",
            "mapeo": {"web": "web"},
        },
    )
    r = cliente.post(
        "/api/v1/calidad-dato/enriquecimiento/caido/pedir",
        headers=cabeceras,
        json={"objeto_ids": [cuenta]},
    )
    assert r.status_code in (502, 503), r.text


# ── Identidad entre canales (CRM-01.01.05.02) ─────────────────────────────


def test_las_senales_se_anotan_al_guardar_y_se_proponen_y_aplican_uniones(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    correo = f"ana.{uuid4().hex[:8]}@empresa-ident.example"
    uno = _contacto(cliente, cabeceras, nombre="Ana", apellidos="Ident", email=correo)
    dos = _contacto(
        cliente, cabeceras, nombre="Ana M.", apellidos="Ident", movil="+34 611 22 33 44"
    )
    # La app ve a la segunda con el mismo correo: lo anota quien lo ve.
    vista = cliente.post(
        "/api/v1/calidad-dato/identidades/observar",
        headers=cabeceras,
        json={"tipo": "email", "valor": correo.upper(), "contacto_id": dos, "origen": "app"},
    )
    assert vista.status_code == 201, vista.text

    # La del alta se anotó sola: la ruta que daba 500 ahora tiene contenido.
    identidades = cliente.get(f"/api/v1/calidad-dato/identidades/contacto/{uno}", headers=cabeceras)
    assert identidades.status_code == 200, identidades.text
    assert identidades.json()["canales"] == ["email"]

    # Corregir la ficha también anota.
    version = cliente.get(f"/api/v1/contacts/{uno}", headers=cabeceras).headers.get("ETag")
    parche = cliente.patch(
        f"/api/v1/contacts/{uno}",
        headers={**cabeceras, "If-Match": version or ""},
        json={"telefono": "611223344"},
    )
    assert parche.status_code == 200, parche.text
    canales = cliente.get(
        f"/api/v1/calidad-dato/identidades/contacto/{uno}", headers=cabeceras
    ).json()["canales"]
    assert canales == ["email", "telefono"]

    propuestas = cliente.get("/api/v1/calidad-dato/identidades/propuestas", headers=cabeceras)
    assert propuestas.status_code == 200, propuestas.text
    par = next(p for p in propuestas.json()["propuestas"] if {p["a"], p["b"]} == {uno, dos})
    assert {s["tipo"] for s in par["senales"]} == {"email", "telefono"}
    assert par["a_nombre"] and par["b_nombre"]

    unida = cliente.post(
        "/api/v1/calidad-dato/identidades/unir",
        headers=cabeceras,
        json={
            "principal_id": uno,
            "secundario_id": dos,
            "senales": par["senales"],
            "puntuacion": par["puntuacion"],
        },
    )
    assert unida.status_code == 200, unida.text
    # Ya no se propone, y resolver el móvil de la segunda lleva a la primera.
    otra = cliente.get("/api/v1/calidad-dato/identidades/propuestas", headers=cabeceras).json()
    assert not any({p["a"], p["b"]} == {uno, dos} for p in otra["propuestas"])
    resuelto = cliente.post(
        "/api/v1/calidad-dato/identidades/resolver",
        headers=cabeceras,
        json={"senales": [{"tipo": "email", "valor": correo}]},
    )
    assert resuelto.status_code == 200, resuelto.text
    assert resuelto.json()["candidatos"][0]["contacto_id"] == uno

    deshecha = cliente.post(
        "/api/v1/calidad-dato/identidades/deshacer",
        headers=cabeceras,
        json={"principal_id": uno, "secundario_id": dos, "motivo": "prueba"},
    )
    assert deshecha.status_code == 200, deshecha.text


def test_las_senales_siguen_a_su_contacto_a_la_papelera_y_de_vuelta(
    cliente: Any, cabeceras: dict[str, str], db: Any
) -> None:
    """Un contacto con correo se puede borrar, y sus señales le siguen.

    Medido el 10-11-2026: las señales se anotan solas al guardar y contaban como
    dependencia, así que todo contacto con correo o teléfono daba 409 al
    borrarlo. Y lo ya unido no se toca: el principal sigue resolviendo.
    """
    from datetime import timedelta

    from crmcore.datos.guard_borrados import con_borrados
    from crmcore.datos.papelera import EntradaPapelera
    from sqlalchemy import select

    from services.party.identidad import Senal

    correo = f"eva.{uuid4().hex[:8]}@papelera-ident.example"
    uno = _contacto(cliente, cabeceras, nombre="Eva", apellidos="Papelera", email=correo)
    dos = _contacto(cliente, cabeceras, nombre="Eva P.", apellidos="Papelera", email=correo)
    unida = cliente.post(
        "/api/v1/calidad-dato/identidades/unir",
        headers=cabeceras,
        json={"principal_id": uno, "secundario_id": dos, "senales": [], "puntuacion": 80},
    )
    assert unida.status_code == 200, unida.text

    def canales(contacto: str) -> list[str]:
        r = cliente.get(f"/api/v1/calidad-dato/identidades/contacto/{contacto}", headers=cabeceras)
        assert r.status_code == 200, r.text
        return list(r.json()["canales"])

    def resuelve() -> list[str]:
        r = cliente.post(
            "/api/v1/calidad-dato/identidades/resolver",
            headers=cabeceras,
            json={"senales": [{"tipo": "email", "valor": correo}]},
        )
        assert r.status_code == 200, r.text
        return [c["contacto_id"] for c in r.json()["candidatos"]]

    # Se borra el secundario: antes, 409 por `senales_identidad`.
    borrado = cliente.delete(f"/api/v1/contacts/{dos}", headers=cabeceras)
    assert borrado.status_code == 204, borrado.text
    assert canales(dos) == []
    # Lo unido sigue: el principal resuelve solo, sin el borrado de candidato.
    assert resuelve() == [uno]

    # Restaurado, sus señales vuelven.
    entrada = db.execute(
        select(EntradaPapelera).where(
            EntradaPapelera.registro_id == UUID(dos), EntradaPapelera.restaurado_at.is_(None)
        )
    ).scalar_one()
    vuelta = cliente.post(f"/api/v1/party-admin/papelera/{entrada.id}/restaurar", headers=cabeceras)
    assert vuelta.status_code == 200, vuelta.text
    assert canales(dos) == ["email"]

    # El principal a la papelera: nadie resuelve a una ficha que no se abre.
    assert cliente.delete(f"/api/v1/contacts/{uno}", headers=cabeceras).status_code == 204
    assert uno not in resuelve()

    # Purgado, sus señales desaparecen de la tabla, no sólo de la vista.
    entrada = db.execute(
        select(EntradaPapelera).where(
            EntradaPapelera.registro_id == UUID(uno), EntradaPapelera.restaurado_at.is_(None)
        )
    ).scalar_one()
    entrada.purgable_at = entrada.purgable_at - timedelta(days=3650)
    db.flush()
    purga = cliente.post(
        "/api/v1/party-admin/papelera/purgar",
        headers=cabeceras,
        json={"motivo": "prueba de purga de señales"},
    )
    assert purga.status_code == 200, purga.text
    with con_borrados(db):
        restos = db.execute(select(Senal).where(Senal.contacto_id == UUID(uno))).scalars().all()
    assert restos == []


def test_la_busqueda_de_contactos_mira_nombre_apellidos_y_correo(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    """Medido el 10-11-2026: sólo miraba la clave canónica, con las palabras
    ordenadas; ni el correo ni «nombre apellido» encontraban a nadie."""
    marca = uuid4().hex[:8]
    correo = f"zoe.{marca}@busqueda.example"
    _contacto(cliente, cabeceras, nombre=f"Zoe{marca}", apellidos="Quíntana Ruiz", email=correo)

    def cuantos(texto: str) -> int:
        r = cliente.get("/api/v1/contacts", headers=cabeceras, params={"buscar": texto})
        assert r.status_code == 200, r.text
        return len(r.json()["items"])

    for texto in (
        f"zoe{marca}",
        "Quíntana",
        "quintana",
        f"ruiz zoe{marca}",
        correo,
        f"zoe.{marca}",
    ):
        assert cuantos(texto) == 1, texto
    assert cuantos(f"zoe{marca} otro") == 0


def test_el_barrido_anota_lo_que_ya_estaba(cliente: Any, cabeceras: dict[str, str]) -> None:
    r = cliente.post("/api/v1/calidad-dato/identidades/barrer", headers=cabeceras)
    assert r.status_code == 200, r.text
    assert {"contactos", "senales", "recortado"} <= set(r.json())


# ── Umbral por objeto (CRM-01.01.04.02) ───────────────────────────────────


def test_el_umbral_se_fija_por_objeto(cliente: Any, cabeceras: dict[str, str]) -> None:
    antes = cliente.get("/api/v1/calidad-dato/umbrales-duplicado", headers=cabeceras)
    assert antes.status_code == 200, antes.text
    general = antes.json()["cuenta"]["sugerencia"]["valor"]
    fijado = cliente.put(
        "/api/v1/calidad-dato/umbrales-duplicado",
        headers=cabeceras,
        json={"por_objeto": {"contacto": {"sugerencia": 0.95}}},
    )
    assert fijado.status_code == 200, fijado.text
    cuerpo = fijado.json()
    assert cuerpo["contacto"]["sugerencia"] == {"valor": 0.95, "propio": True}
    # La cuenta sigue con el general: un objeto no arrastra al otro.
    assert cuerpo["cuenta"]["sugerencia"] == {"valor": general, "propio": False}
    malo = cliente.put(
        "/api/v1/calidad-dato/umbrales-duplicado",
        headers=cabeceras,
        json={"por_objeto": {"contacto": {"sugerencia": 3}}},
    )
    assert malo.status_code == 422, malo.text


def test_el_umbral_del_objeto_cambia_lo_que_se_propone(db: Any) -> None:
    """Sin base de datos de ajustes: el del objeto manda sobre el general."""
    from crmcore.runtime import settings as rt

    from services.party import duplicados

    original = rt.efectivo

    def falso(clave: str, db: Any = None, **kw: Any) -> Any:
        if clave == "dedupe_umbral_por_objeto":
            return {"contacto": {"propuesta": 0.99}}
        return original(clave, db, **kw)

    try:
        rt.efectivo = falso  # type: ignore[assignment]
        assert duplicados.umbral_de(None, "contacto", "propuesta") == 0.99
        assert duplicados.umbral_de(None, "cuenta", "propuesta") != 0.99
    finally:
        rt.efectivo = original  # type: ignore[assignment]


# ── Direcciones (CRM-01.01.04.04) ─────────────────────────────────────────


def test_la_direccion_se_normaliza_al_guardarla(cliente: Any, cabeceras: dict[str, str]) -> None:
    cuenta = _cuenta(cliente, cabeceras, nombre=f"Con dirección {uuid4().hex[:6]}")
    r = cliente.post(
        f"/api/v1/accounts/{cuenta}/direcciones",
        headers=cabeceras,
        json={
            "linea1": "  c/  mayor,  3 ",
            "codigo_postal": "8001",
            "ciudad": "BARCELONA",
            "provincia": "barcelona",
            "pais": "es",
        },
    )
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["linea1"] == "Calle mayor, 3"
    assert d["codigo_postal"] == "08001"
    assert d["ciudad"] == "Barcelona"
    assert d["pais"] == "ES"

    barrido = cliente.post(
        "/api/v1/calidad-dato/direcciones/normalizar",
        headers=cabeceras,
        params={"objeto_id": cuenta},
    )
    assert barrido.status_code == 200, barrido.text
    assert barrido.json()["a_cambiar"] == 0


def test_normalizar_no_inventa() -> None:
    from services.party.direcciones import normalizar_direccion

    salida = normalizar_direccion(
        {"linea1": "Avda. de la Constitución 7", "codigo_postal": "28 001", "pais": "PT"}
    )
    assert salida["linea1"] == "Avenida de la Constitución 7"
    # Portugal no tiene formato declarado: el código se deja como viene.
    assert salida["codigo_postal"] == "28 001"
    assert "provincia" not in salida
