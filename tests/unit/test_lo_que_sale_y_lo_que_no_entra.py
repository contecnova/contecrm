"""Tokenizar, y marcar lo que sale (CRM-00.05.03.04, CRM-00.05.03.07, CRM-00.05.04.04).

Tres capacidades de seguridad resueltas por dentro y sin puerta por fuera.

**Tokenizar.** Cifrar un número de tarjeta lo protege de quien lea la base;
tokenizarlo lo **saca** de la base, que es otra cosa — y la diferencia es estar o
no estar dentro del alcance de PCI. El módulo estaba entero: tipos admitidos,
pista que se conserva de cada uno, rechazo a tokenizar en falso sin bóveda,
rastro al recuperar. Y no había forma de pedirlo: lo único que llegaba a
ejecutarse era el detector de números colados por texto libre, que avisa de que
este despliegue no tiene bóveda — un aviso sobre una capacidad que encima no se
podía usar.

**La marca de lo que sale.** La exportación devolvía las filas y la cabecera de
la marca **por separado**, dejando a quien escriba el cliente la tarea de
acordarse de ponerla. Pedirle a cada uno que se acuerde es pedirle al próximo
que se olvide, con el agravante de que el que se olvida produce un fichero
idéntico al bueno salvo en lo único que importa cuando la hoja con la cartera
aparece donde no debe.

**El volcado al SIEM.** Estaba escrito, en formato neutro y en flujo para que un
año de audit trail no se cargue entero en memoria. Sin ruta.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db


@pytest.fixture
def cliente(db: Any) -> Any:
    import importlib
    import os

    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        modulo = importlib.import_module("services.sales.main")
        with TestClient(modulo.app) as cli:
            yield cli
    finally:
        if previo is None:
            os.environ.pop("OUTBOX_ENABLED", None)
        else:
            os.environ["OUTBOX_ENABLED"] = previo
        get_settings.cache_clear()


def _cabeceras(tenant_id: UUID, *, factor_fuerte: bool = True) -> dict[str, str]:
    from crmcore.config import get_settings
    from crmcore.http.deps import (
        H_FACTOR_FUERTE,
        H_PERMISOS,
        H_ROLES,
        H_TENANT,
        H_USER,
        firmar_cabeceras_internas,
    )

    valores = {
        H_TENANT: str(tenant_id),
        H_USER: str(uuid4()),
        H_PERMISOS: "*:*",
        H_ROLES: "admin",
    }
    if factor_fuerte:
        valores[H_FACTOR_FUERTE] = datetime.now(timezone.utc).isoformat()
    return firmar_cabeceras_internas(valores, get_settings().secret_key.get_secret_value())


@pytest.fixture
def cabeceras(tenant_id: UUID) -> dict[str, str]:
    return _cabeceras(tenant_id)


@pytest.fixture
def boveda() -> Any:
    """Una bóveda de mentira, enchufada por el puerto de siempre.

    Es el puerto que usa el despliegue real: aquí se enchufa una de pruebas para
    poder ejercitar la ida y la vuelta. Se desenchufa al terminar, porque el
    registro es global y dejarlo puesto haría que la prueba siguiente creyera que
    este despliegue tiene bóveda.
    """
    from crmcore.security import tokenizacion as tok

    guardados: dict[str, str] = {}

    def _guardar(*, valor: str, tipo: str, tenant_id: Any) -> str:
        token = f"tok_{len(guardados)}"
        guardados[token] = valor
        return token

    def _recuperar(*, token: str, tipo: str, tenant_id: Any) -> str:
        return guardados[token]

    previo = (tok._boveda, tok._destokenizador)
    tok.registrar_boveda(_guardar, _recuperar)
    try:
        yield guardados
    finally:
        tok._boveda, tok._destokenizador = previo


# ── Tokenizar (CRM-00.05.03.04) ───────────────────────────────────────────


def test_sin_boveda_se_dice_antes_de_ofrecer_el_campo(
    cliente: Any, cabeceras: dict[str, str]
) -> None:
    """Una pantalla que ofrece guardar la tarjeta en un despliegue sin bóveda
    promete algo que va a fallar al guardar, con el cliente delante."""
    r = cliente.get("/api/v1/sales/tokenizacion", headers=cabeceras)
    assert r.status_code == 200, r.text
    salida = r.json()
    assert salida["hay_boveda"] is False
    assert "tarjeta" in salida["tipos"]
    assert "NO puede guardar" in salida["que_significa"]


def test_sin_boveda_no_se_tokeniza_en_falso(cliente: Any, cabeceras: dict[str, str]) -> None:
    """Guardar el número «hasta que haya bóveda» mete el sistema en el alcance de
    PCI sin que nadie lo haya decidido."""
    r = cliente.post(
        "/api/v1/sales/tokenizacion",
        json={"valor": "4111111111111111", "tipo": "tarjeta"},
        headers=cabeceras,
    )
    assert r.status_code >= 400, r.text
    assert r.json()["error_code"] == "tokenizacion.sin_boveda"


def test_el_numero_sale_del_crm_y_queda_la_pista(
    cliente: Any, cabeceras: dict[str, str], boveda: Any
) -> None:
    """Lo que queda en el CRM es una referencia sin valor y cuatro dígitos para
    que una persona reconozca su tarjeta."""
    r = cliente.post(
        "/api/v1/sales/tokenizacion",
        json={"valor": "4111 1111 1111 1111", "tipo": "tarjeta"},
        headers=cabeceras,
    )
    assert r.status_code == 200, r.text
    salida = r.json()
    assert salida["pista"] == "1111"
    assert "4111111111111111" not in str(salida), "el número ha vuelto en la respuesta"
    # Y está en la bóveda, sin los espacios con los que vino.
    assert list(boveda.values()) == ["4111111111111111"]


def test_de_un_identificador_fiscal_no_se_guarda_pista(
    cliente: Any, cabeceras: dict[str, str], boveda: Any
) -> None:
    """Con la letra y dos dígitos se adivina el resto."""
    salida = cliente.post(
        "/api/v1/sales/tokenizacion",
        json={"valor": "12345678Z", "tipo": "identificador_fiscal"},
        headers=cabeceras,
    ).json()
    assert salida["pista"] == ""


def test_un_tipo_que_no_se_tokeniza_se_rechaza(
    cliente: Any, cabeceras: dict[str, str], boveda: Any
) -> None:
    """Cada tipo tiene su regla de conservación y su forma de enseñarse: la lista
    es cerrada a propósito."""
    r = cliente.post(
        "/api/v1/sales/tokenizacion",
        json={"valor": "x", "tipo": "lo_que_sea"},
        headers=cabeceras,
    )
    assert r.status_code == 422, r.text
    assert r.json()["error_code"] == "tokenizacion.tipo_invalido"


def test_recuperar_exige_motivo(cliente: Any, cabeceras: dict[str, str], boveda: Any) -> None:
    """Sin motivo, la lista de accesos es una lista de nombres sin nada que
    decidir."""
    token = cliente.post(
        "/api/v1/sales/tokenizacion",
        json={"valor": "4111111111111111", "tipo": "tarjeta"},
        headers=cabeceras,
    ).json()["token"]

    r = cliente.post(
        f"/api/v1/sales/tokenizacion/{token}/resolver",
        json={"tipo": "tarjeta", "motivo": ""},
        headers=cabeceras,
    )
    assert r.status_code == 422, r.text


def test_recuperar_exige_segundo_factor_reciente(
    cliente: Any, tenant_id: UUID, boveda: Any
) -> None:
    """Es la única operación del CRM que devuelve un dato que el CRM no guarda.
    Que la pida una sesión abierta desde esta mañana no basta."""
    con_factor = _cabeceras(tenant_id)
    token = cliente.post(
        "/api/v1/sales/tokenizacion",
        json={"valor": "4111111111111111", "tipo": "tarjeta"},
        headers=con_factor,
    ).json()["token"]

    r = cliente.post(
        f"/api/v1/sales/tokenizacion/{token}/resolver",
        json={"tipo": "tarjeta", "motivo": "llamada del cliente"},
        headers=_cabeceras(tenant_id, factor_fuerte=False),
    )
    assert r.status_code in (401, 403), r.text


def test_recuperar_devuelve_el_numero_y_queda_el_rastro(
    cliente: Any, cabeceras: dict[str, str], boveda: Any, db: Any
) -> None:
    """Y el motivo queda en la auditoría: es lo que hace que tokenizar sirva de
    algo."""
    from crmcore.audit.modelos import ApunteAuditoria
    from sqlalchemy import select

    token = cliente.post(
        "/api/v1/sales/tokenizacion",
        json={"valor": "4111111111111111", "tipo": "tarjeta"},
        headers=cabeceras,
    ).json()["token"]

    r = cliente.post(
        f"/api/v1/sales/tokenizacion/{token}/resolver",
        json={"tipo": "tarjeta", "motivo": "reclamación de un cobro duplicado"},
        headers=cabeceras,
    )
    assert r.status_code == 200, r.text
    assert r.json()["valor"] == "4111111111111111"

    apuntes = list(
        db.execute(
            select(ApunteAuditoria).where(ApunteAuditoria.accion == "tokenizacion.resuelta")
        ).scalars()
    )
    assert apuntes, "recuperar un dato tokenizado no ha dejado rastro"
    assert "cobro duplicado" in (apuntes[-1].motivo or "")
    # Y el número NO está en la auditoría: devolvería el dato a la base por la
    # puerta de atrás.
    assert "4111111111111111" not in str(apuntes[-1].datos)


# ── La marca de lo que sale (CRM-00.05.03.07) ─────────────────────────────


def test_el_csv_sale_ya_montado_y_ya_marcado(cliente: Any, cabeceras: dict[str, str]) -> None:
    """Devolver las filas y la cabecera por separado deja la marca a cargo de
    quien escriba el cliente. El que se olvida produce un fichero idéntico al
    bueno salvo en lo único que importa."""
    r = cliente.get("/api/v1/listas-precio/exportar?formato=csv", headers=cabeceras)
    assert r.status_code == 200, r.text[:300]
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers.get("content-disposition", "")
    # Que no se quede en ninguna caché intermedia.
    assert r.headers.get("cache-control") == "no-store"

    cuerpo = r.text
    lineas = [x for x in cuerpo.splitlines() if x.strip()]
    # Arriba y abajo: recortar las primeras líneas al pegar un fragmento en un
    # correo es lo más habitual, y recortar el final también.
    assert lineas[0].startswith("#"), "el CSV sale sin marca arriba"
    assert lineas[-1].startswith("#"), "el CSV sale sin marca abajo"


def test_el_csv_no_se_rompe_con_una_coma_dentro(
    cliente: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """A mano, el primer nombre con una coma desplaza todo lo que viene detrás: el
    fichero se abre igual y los datos están cambiados de sitio."""
    import csv
    import io

    from services.sales.catalogo import ListaPrecio

    db.add(ListaPrecio(tenant_id=tenant_id, clave="lp-coma", nombre='Acme, S.L. "la buena"'))
    db.commit()

    cuerpo = cliente.get("/api/v1/listas-precio/exportar?formato=csv", headers=cabeceras).text
    sin_marca = [x for x in cuerpo.splitlines() if not x.startswith("#")]
    filas = list(csv.DictReader(io.StringIO("\n".join(sin_marca))))
    assert any(f.get("nombre") == 'Acme, S.L. "la buena"' for f in filas), filas


def test_en_json_siguen_viniendo_las_filas(cliente: Any, cabeceras: dict[str, str]) -> None:
    """El formato de siempre no cambia: quien ya integraba sigue igual."""
    r = cliente.get("/api/v1/listas-precio/exportar", headers=cabeceras)
    assert r.status_code == 200, r.text[:300]
    salida = r.json()
    assert "filas" in salida and "cabecera_csv" in salida


# ── El volcado al SIEM (CRM-00.05.04.04) ──────────────────────────────────


@pytest.fixture
def cliente_tenancy(db: Any) -> Any:
    import importlib
    import os

    from crmcore.config import get_settings

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


def _ventana() -> dict[str, str]:
    ahora = datetime.now(timezone.utc)
    return {
        "desde": (ahora - timedelta(days=1)).isoformat(),
        "hasta": (ahora + timedelta(days=1)).isoformat(),
    }


def test_el_volcado_sale_en_lineas_y_con_marca(
    cliente_tenancy: Any, cabeceras: dict[str, str], db: Any, tenant_id: UUID
) -> None:
    """JSON Lines en formato neutro: escribir el formato de un producto concreto
    ata la instalación a ese producto."""
    import json

    from crmcore.audit.chain import registrar

    registrar(
        db,
        accion="cuenta.creada",
        objeto="cuenta",
        objeto_id=uuid4(),
        datos={"nombre": "Acme"},
        tenant_id=tenant_id,
    )
    db.commit()

    r = cliente_tenancy.get(
        "/api/v1/grc/auditoria/volcado.jsonl", params=_ventana(), headers=cabeceras
    )
    assert r.status_code == 200, r.text[:300]
    assert r.headers["content-type"].startswith("application/x-ndjson")

    lineas = [json.loads(x) for x in r.text.splitlines() if x.strip()]
    assert len(lineas) >= 2, "no ha salido ni la marca ni un apunte"
    # La marca va como una línea del propio formato: un JSONL con una cabecera
    # que no es JSON no lo lee ningún SIEM.
    apuntes = [x for x in lineas if x.get("action")]
    assert any(a["action"] == "cuenta.creada" for a in apuntes)
    # Con secuencia y hash: es lo que permite comprobar que no falta nada.
    assert "sequence" in apuntes[-1] and "hash" in apuntes[-1]


def test_un_periodo_al_reves_se_dice(cliente_tenancy: Any, cabeceras: dict[str, str]) -> None:
    """Devolver cero apuntes sería indistinguible de «no pasó nada»."""
    ahora = datetime.now(timezone.utc)
    r = cliente_tenancy.get(
        "/api/v1/grc/auditoria/volcado.jsonl",
        params={"desde": ahora.isoformat(), "hasta": (ahora - timedelta(days=1)).isoformat()},
        headers=cabeceras,
    )
    assert r.status_code == 422, r.text[:300]
    assert r.json()["error_code"] == "siem.periodo_invalido"


def test_llevarse_el_audit_trail_entero_es_exportacion_masiva(
    cliente_tenancy: Any, tenant_id: UUID
) -> None:
    """Es el registro de todo lo que ha hecho todo el mundo. Que lo pida un SIEM
    no lo hace menos sensible: lo hace más frecuente."""
    r = cliente_tenancy.get(
        "/api/v1/grc/auditoria/volcado.jsonl",
        params=_ventana(),
        headers=_cabeceras(tenant_id, factor_fuerte=False),
    )
    assert r.status_code in (401, 403), r.text[:300]
