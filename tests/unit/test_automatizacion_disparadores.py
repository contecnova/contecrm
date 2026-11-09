"""Los siete disparadores, cada uno con quien lo dispare (CRM-00.03.03.02).

Se podían elegir creación, modificación, eliminación, webhook, programada,
manual y evento entrante, y **sólo los dos primeros tenían quien los
disparara**: el resto se guardaba, se validaba y no corría nunca. Aquí se
prueba que cada uno tiene su camino:

  · **eliminación**, con el `record.deleted` que publica el borrado común;
  · **evento entrante**, con cualquier tipo del catálogo de eventos;
  · **manual**, con «ejecutar ahora» sobre un registro;
  · **webhook**, con un POST firmado con el secreto de la regla —la misma firma
    que la casa usa para los webhooks salientes— y nada más que lo autorice;
  · y **programada**, cuyo reloj se prueba en `test_automatizacion_momento.py`.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.db

FIJAR = [{"tipo": "fijar", "nombre": "visto", "valor": 1}]


def _regla(db: Any, tenant_id: UUID, **extra: Any) -> Any:
    from services.automation.modelos import Automatizacion

    fila = Automatizacion(
        tenant_id=tenant_id,
        **{
            "nombre": f"Regla {uuid4().hex[:6]}",
            "disparador": "creacion",
            "objetivo": "cuenta",
            "acciones": FIJAR,
            "activa": True,
            **extra,
        },
    )
    db.add(fila)
    db.flush()
    return fila


def _trazas(db: Any, regla: Any) -> list[Any]:
    from sqlalchemy import select

    from services.automation.modelos import EjecucionAutomatizacion

    db.expire_all()
    return list(
        db.execute(
            select(EjecucionAutomatizacion).where(
                EjecucionAutomatizacion.automatizacion_id == regla.id
            )
        )
        .scalars()
        .all()
    )


# ── Por eventos ───────────────────────────────────────────────────────────


def test_cada_evento_despierta_los_disparadores_que_le_tocan() -> None:
    from services.automation.consumidores import encajes

    assert encajes("record.deleted", {"objeto": "oportunidad"}) == [
        ("eliminacion", "oportunidad"),
        ("evento", "record.deleted"),
    ]
    assert ("creacion", "cuenta") in encajes("account.created", {})
    assert ("evento", "account.created") in encajes("account.created", {})
    assert encajes("case.created", {}) == [("evento", "case.created")]
    # Lo que no está en el catálogo no despierta nada: no lo publica nadie.
    assert encajes("inventado.del.todo", {}) == []


def test_el_borrado_dispara_las_de_eliminacion_de_ese_objeto(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from services.automation.consumidores import consumir_evento

    regla = _regla(db, tenant_id, disparador="eliminacion", objetivo="oportunidad")
    otra = _regla(db, tenant_id, disparador="eliminacion", objetivo="cuenta")
    borrada = str(uuid4())
    asyncio.run(
        consumir_evento(
            {
                "id": str(uuid4()),
                "tipo": "record.deleted",
                "tenant_id": str(tenant_id),
                "data": {"objeto": "oportunidad", "registro_id": borrada, "definitivo": False},
            }
        )
    )
    trazas = _trazas(db, regla)
    assert [(t.resultado, t.registro_id) for t in trazas] == [("disparada", borrada)]
    # La de otro objeto no se entera: borrar una oportunidad no es borrar una cuenta.
    assert _trazas(db, otra) == []


def test_un_evento_del_catalogo_dispara_la_regla_enganchada_a_el(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """«Contrato a punto de vencer» no está en la tabla de creación y
    modificación, y aun así se puede reaccionar a él."""
    from services.automation.consumidores import consumir_evento

    regla = _regla(
        db,
        tenant_id,
        disparador="evento",
        objetivo="contract.renewal.due",
        condiciones=[{"atributo": "dias_restantes", "op": "<=", "valor": 30}],
    )
    contrato = str(uuid4())
    for dias in (90, 20):
        asyncio.run(
            consumir_evento(
                {
                    "id": str(uuid4()),
                    "tipo": "contract.renewal.due",
                    "tenant_id": str(tenant_id),
                    "data": {"contrato_id": contrato, "dias_restantes": dias},
                }
            )
        )
    resultados = sorted(t.resultado for t in _trazas(db, regla))
    assert resultados == ["condiciones_no_cumplidas", "disparada"]
    assert {t.registro_id for t in _trazas(db, regla)} == {contrato}


# ── Por HTTP: alta, manual y webhook ──────────────────────────────────────


@pytest.fixture
def cliente(db: Any) -> Any:
    from crmcore.config import get_settings

    previo = os.environ.get("OUTBOX_ENABLED")
    os.environ["OUTBOX_ENABLED"] = "false"
    get_settings.cache_clear()
    try:
        with TestClient(importlib.import_module("services.automation.main").app) as cli:
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


def _crear(cliente: Any, cabeceras: dict[str, str], **datos: Any) -> Any:
    cuerpo = {
        "nombre": f"Regla {uuid4().hex[:6]}",
        "disparador": "manual",
        "objetivo": "oportunidad",
        "acciones": FIJAR,
        **datos,
    }
    return cliente.post("/api/v1/automatizaciones", json=cuerpo, headers=cabeceras)


def _encender(cliente: Any, cabeceras: dict[str, str], regla_id: str) -> None:
    r = cliente.post(
        f"/api/v1/automatizaciones/{regla_id}/activar", json={"activa": True}, headers=cabeceras
    )
    assert r.status_code == 200, r.text[:300]


def test_el_alta_rechaza_lo_que_no_correria_nunca(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    """Una programada sin horario y una «evento» enganchada a un evento que
    nadie publica se guardaban y no corrían jamás."""
    r = _crear(cliente, cabeceras, disparador="programada")
    assert r.status_code == 422 and "programacion" in r.text, r.text[:300]
    r = _crear(cliente, cabeceras, disparador="programada", programacion="0 0 31 2 *")
    assert r.status_code == 422, r.text[:300]
    r = _crear(cliente, cabeceras, disparador="evento", objetivo="no.existe")
    assert r.status_code == 422 and "catálogo" in r.text, r.text[:300]
    r = _crear(cliente, cabeceras, disparador="evento", objetivo="case.created")
    assert r.status_code == 201, r.text[:300]


def test_encender_una_programada_dice_cuando_corre(
    cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    r = _crear(cliente, cabeceras, disparador="programada", programacion="0 8 * * 1")
    regla = r.json()
    assert regla["proxima_ejecucion_at"] is None  # apagada: no le toca nada
    r = cliente.post(
        f"/api/v1/automatizaciones/{regla['id']}/activar", json={"activa": True}, headers=cabeceras
    )
    assert r.status_code == 200, r.text[:300]
    proxima = datetime.fromisoformat(r.json()["proxima_ejecucion_at"])
    assert proxima > datetime.now(timezone.utc) and proxima.weekday() == 0


def test_ejecutar_ahora_corre_la_regla_sobre_el_registro(
    db: Any, cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    regla = _crear(
        cliente,
        cabeceras,
        condiciones=[{"atributo": "importe", "op": ">", "valor": 1000}],
    ).json()
    registro = str(uuid4())
    url = f"/api/v1/automatizaciones/{regla['id']}/ejecutar"
    cuerpo = {"registro_id": registro, "valores": {"importe": 5000}}

    # Apagada no corre: apagarla es como se para una regla.
    r = cliente.post(url, json=cuerpo, headers=cabeceras)
    assert r.status_code == 409, r.text[:300]

    _encender(cliente, cabeceras, regla["id"])
    r = cliente.post(url, json=cuerpo, headers=cabeceras)
    assert r.status_code == 200, r.text[:300]
    assert r.json()["resultado"] == "disparada"
    r = cliente.post(
        url, json={"registro_id": registro, "valores": {"importe": 5}}, headers=cabeceras
    )
    assert r.json()["resultado"] == "condiciones_no_cumplidas"

    historial = cliente.get(
        f"/api/v1/automatizaciones/registro/oportunidad/{registro}", headers=cabeceras
    ).json()
    assert sorted(h["resultado"] for h in historial) == ["condiciones_no_cumplidas", "disparada"]


def _firmado(
    secreto: str, cuerpo: dict[str, Any], momento: int | None = None
) -> tuple[bytes, dict[str, str]]:
    from crmcore.security.firma import H_FIRMA, H_MOMENTO, firmar

    crudo = json.dumps(cuerpo).encode()
    instante = momento if momento is not None else int(time.time())
    return crudo, {
        H_FIRMA: firmar(crudo, secreto, instante),
        H_MOMENTO: str(instante),
        "content-type": "application/json",
    }


def test_el_webhook_firmado_dispara_la_regla_y_nada_mas_lo_autoriza(
    db: Any, cliente: Any, cabeceras: dict[str, str], tenant_id: UUID, contexto_tenant: UUID
) -> None:
    regla = _crear(cliente, cabeceras, disparador="webhook", objetivo="pedido_web").json()
    otra = _crear(cliente, cabeceras, disparador="webhook", objetivo="pedido_web").json()
    _encender(cliente, cabeceras, regla["id"])

    # Sólo las de disparador webhook tienen secreto.
    manual = _crear(cliente, cabeceras).json()
    r = cliente.post(f"/api/v1/automatizaciones/{manual['id']}/secreto-webhook", headers=cabeceras)
    assert r.status_code == 422, r.text[:300]

    r = cliente.post(f"/api/v1/automatizaciones/{regla['id']}/secreto-webhook", headers=cabeceras)
    assert r.status_code == 200, r.text[:300]
    dado = r.json()
    assert dado["url"] == f"/api/v1/automatizaciones/webhook/{tenant_id}/{regla['id']}"
    secreto = dado["secreto"]
    secreto_otra = cliente.post(
        f"/api/v1/automatizaciones/{otra['id']}/secreto-webhook", headers=cabeceras
    ).json()["secreto"]

    # Sin cabeceras de usuario: lo llama otro sistema.
    pedido = str(uuid4())
    crudo, firmas = _firmado(secreto, {"registro_id": pedido, "total": 120})
    r = cliente.post(dado["url"], content=crudo, headers=firmas)
    assert r.status_code == 202, r.text[:300]
    assert r.json()["disparada"] is True and r.json()["resultado"] == "disparada"
    assert [(t.resultado, t.registro_id) for t in _trazas(db, _regla_por_id(db, regla))] == [
        ("disparada", pedido)
    ]

    # El mismo mensaje reenviado dentro de su ventana no vuelve a ejecutarla:
    # la regla es inmediata y antes corría dos veces (09-11-2026).
    r = cliente.post(dado["url"], content=crudo, headers=firmas)
    assert r.status_code == 202, r.text[:300]
    assert r.json().get("duplicada") is True, r.json()
    assert len(_trazas(db, _regla_por_id(db, regla))) == 1

    # Firma de otra regla, firma manipulada, sin firma o vieja: lo mismo, 401.
    for cuerpo, cab in (
        _firmado(secreto_otra, {"total": 1}),
        (crudo, {**firmas, "X-Contecrm-Firma": "0" * 64}),
        (crudo, {"content-type": "application/json"}),
        _firmado(secreto, {"total": 1}, momento=int(time.time()) - 3600),
    ):
        r = cliente.post(dado["url"], content=cuerpo, headers=cab)
        assert r.status_code == 401, r.text[:300]
        assert r.json()["error_code"] == "automatizacion.webhook_no_autorizado"

    # Regenerar el secreto deja el anterior sin valor.
    cliente.post(f"/api/v1/automatizaciones/{regla['id']}/secreto-webhook", headers=cabeceras)
    crudo, firmas = _firmado(secreto, {"total": 1})
    assert cliente.post(dado["url"], content=crudo, headers=firmas).status_code == 401


def test_el_webhook_de_una_regla_apagada_se_acepta_y_no_corre(
    db: Any, cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    regla = _crear(cliente, cabeceras, disparador="webhook", objetivo="pedido_web").json()
    dado = cliente.post(
        f"/api/v1/automatizaciones/{regla['id']}/secreto-webhook", headers=cabeceras
    ).json()
    crudo, firmas = _firmado(dado["secreto"], {"total": 1})
    r = cliente.post(dado["url"], content=crudo, headers=firmas)
    assert r.status_code == 202 and r.json()["disparada"] is False, r.text[:300]


def test_el_secreto_no_sale_por_la_ficha(
    db: Any, cliente: Any, cabeceras: dict[str, str], contexto_tenant: UUID
) -> None:
    regla = _crear(cliente, cabeceras, disparador="webhook", objetivo="pedido_web").json()
    secreto = cliente.post(
        f"/api/v1/automatizaciones/{regla['id']}/secreto-webhook", headers=cabeceras
    ).json()["secreto"]
    ficha = cliente.get(f"/api/v1/automatizaciones/{regla['id']}", headers=cabeceras)
    assert ficha.status_code == 200 and secreto not in ficha.text

    from sqlalchemy import select

    from services.automation.modelos import SecretoWebhookAutomatizacion

    guardado = db.execute(select(SecretoWebhookAutomatizacion.secreto)).scalars().all()
    # Cifrado en la base, no en claro.
    assert guardado and all(g.startswith("enc:") and secreto not in g for g in guardado)


def _regla_por_id(db: Any, salida: dict[str, Any]) -> Any:
    from services.automation.modelos import Automatizacion

    return db.get(Automatizacion, UUID(salida["id"]))


# ── Con qué identidad lanza procesos una regla ────────────────────────────


def _como(usuario: UUID, permisos: str, tenant_id: UUID) -> dict[str, str]:
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
            H_PERMISOS: permisos,
            H_ROLES: "gestor",
            H_FACTOR_FUERTE: datetime.now(timezone.utc).isoformat(),
        },
        get_settings().secret_key.get_secret_value(),
    )


def test_la_regla_guarda_quien_la_activo_y_cambia_si_la_reenciende_otro(
    db: Any, cliente: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Un proceso lanzado por una regla actúa con los permisos de quien la
    ACTIVÓ. Si se apaga y la enciende otra persona, pasa a ser esa."""
    ana, luis = uuid4(), uuid4()
    permisos = "automation:write,automation:read,proceso:write"
    regla = _crear(cliente, _como(ana, permisos, tenant_id)).json()
    url = f"/api/v1/automatizaciones/{regla['id']}/activar"

    cliente.post(url, json={"activa": True}, headers=_como(ana, permisos, tenant_id))
    fila = _regla_por_id(db, regla)
    db.refresh(fila)
    assert fila.activada_por_id == ana
    assert fila.activada_con["permisos"] == sorted(permisos.split(","))
    assert fila.activada_con["roles"] == ["gestor"]

    cliente.post(url, json={"activa": False}, headers=_como(ana, permisos, tenant_id))
    db.refresh(fila)
    assert fila.activada_por_id is None

    cliente.post(url, json={"activa": True}, headers=_como(luis, "*:*", tenant_id))
    db.refresh(fila)
    assert fila.activada_por_id == luis and fila.activada_con["permisos"] == ["*:*"]


def test_lanzar_proceso_lleva_la_identidad_de_quien_activo_la_regla(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    """Del motor al comando: el ejecutor recibe la identidad en su contexto y
    la pone en `datos.lanzado_por`, que es lo que lee el motor de procesos."""
    from crmcore.bus.comandos import Comando

    from services.automation import ejecutores, motor

    quien = uuid4()
    regla = _regla(
        db,
        tenant_id,
        acciones=[{"tipo": "lanzar_proceso", "parametros": {"proceso": "alta_cliente"}}],
        activada_por_id=quien,
        activada_con={"tipo": "usuario", "permisos": ["proceso:write"], "roles": ["gestor"]},
    )
    emitidos: list[Comando] = []

    class _Uow:
        def __init__(self) -> None:
            self.db, self.tenant_id = db, tenant_id

    reales = ejecutores.construir(_Uow())
    import services.automation.ejecutores as mod

    original = mod.emitir
    mod.emitir = lambda _uow, comando: emitidos.append(comando)  # type: ignore[assignment]
    try:
        traza = motor.ejecutar(
            db, regla, valores={}, objeto="cuenta", registro_id=None, ejecutores=reales
        )
    finally:
        mod.emitir = original  # type: ignore[assignment]
    assert traza.resultado == "disparada", traza.error
    assert emitidos[0].datos["lanzado_por"] == {
        "principal_id": str(quien),
        "tipo": "usuario",
        "permisos": ["proceso:write"],
        "roles": ["gestor"],
    }

    # Sin identidad guardada no se inventa ninguna.
    regla.activada_por_id = None
    emitidos.clear()
    mod.emitir = lambda _uow, comando: emitidos.append(comando)  # type: ignore[assignment]
    try:
        motor.ejecutar(db, regla, valores={}, objeto="cuenta", registro_id=None, ejecutores=reales)
    finally:
        mod.emitir = original  # type: ignore[assignment]
    assert "lanzado_por" not in emitidos[0].datos
