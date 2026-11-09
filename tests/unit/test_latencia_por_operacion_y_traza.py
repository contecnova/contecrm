"""Latencia p95/p99 por tipo de operación (CRM-08.01.01.01), el identificador de
petición hasta el audit trail (CRM-00.02.04.07) y el alta del tenant en cascada
desde su botón (CRM-00.01.07.02).

Lo que se fija:

- que el percentil salga de los cubos como lo calcula un histograma, y que **no
  se invente un número** cuando cae por encima del último;
- que la operación salga de las reglas configuradas, no de un `if` en el código;
- que juntar servicios **sume cubos** y no promedie percentiles, que es la
  única forma de que el p95 de la instalación sea el p95 de algo;
- que una petición del navegador lleve su identificador hasta el servicio, y
  que el audit trail se filtre por él;
- que el alta del tenant empuje sólo el alta del tenant, y diga en qué quedó en
  cada herramienta —también la que falló—.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from crmcore.obs import slo


@pytest.fixture(autouse=True)
def _sin_redis(monkeypatch: Any) -> Any:
    """En memoria: la prueba no puede escribir en el Redis de la pila local."""
    from crmcore import redis_cliente

    async def _ninguno() -> Any:
        return None

    monkeypatch.setattr(redis_cliente, "cliente", _ninguno)
    slo.reiniciar()
    yield
    slo.reiniciar()


# ── Percentiles ───────────────────────────────────────────────────────────


def test_el_percentil_se_interpola_dentro_del_cubo() -> None:
    limites = [100, 200, 500]
    # 100 peticiones: 90 por debajo de 100 ms y 10 entre 100 y 200.
    conteos = [90, 10, 0, 0]
    assert slo.percentil(conteos, limites, 0.95)["ms"] == 150
    assert slo.percentil(conteos, limites, 0.5)["ms"] == 56


def test_por_encima_del_ultimo_cubo_no_se_inventa_un_numero() -> None:
    """«Más de 500 ms» es lo que se sabe; un 500 a secas sería mentir."""
    salida = slo.percentil([1, 0, 0, 99], [100, 200, 500], 0.99)
    assert salida == {"ms": None, "por_encima_de_ms": 500}


def test_la_operacion_sale_de_las_reglas_configuradas(monkeypatch: Any) -> None:
    from crmcore.config import get_settings

    assert slo.operacion_de("GET", "/api/v1/accounts/{id}") == "lectura"
    assert slo.operacion_de("POST", "/api/v1/accounts") == "escritura"
    assert slo.operacion_de("GET", "/api/v1/buscar") == "busqueda"
    assert slo.operacion_de("GET", "/api/v1/grc/auditoria/volcado.jsonl") == "exportacion"
    assert slo.operacion_de("OPTIONS", "/api/v1/accounts") == "otra"
    # Y una regla nueva cambia la clasificación sin tocar código.
    monkeypatch.setattr(
        get_settings(),
        "slo_operaciones_reglas",
        [{"operacion": "informe", "metodos": [], "rutas": ["/informes"]}],
    )
    assert slo.operacion_de("GET", "/api/v1/informes/{id}") == "informe"


def test_cada_operacion_contra_su_objetivo_y_con_su_n() -> None:
    """Un p99 de veinte peticiones es la segunda más lenta, no una cola."""
    tenant = uuid4()

    async def _anotar() -> None:
        for _ in range(19):
            await slo.anotar("party", tenant, ok=True, ms=20, operacion="lectura")
        await slo.anotar("party", tenant, ok=True, ms=4_000, operacion="lectura")
        await slo.anotar("party", tenant, ok=True, ms=40_000, operacion="exportacion")

    asyncio.run(_anotar())
    por_op, origen = asyncio.run(slo.latencias_de("party", tenant))
    assert origen == "memoria_del_proceso"
    filas = {
        f["operacion"]: f
        for f in slo.resumen_por_operacion(
            por_op,
            {
                "lectura": {"p95_ms": 500, "p99_ms": 1_500},
                "busqueda": {"p95_ms": 800, "p99_ms": 2_000},
                "exportacion": {"p95_ms": 10_000, "p99_ms": 30_000},
            },
        )
    }
    assert filas["lectura"]["peticiones"] == 20
    assert filas["lectura"]["pocas_muestras"] is True
    assert filas["lectura"]["cumple_p99"] is False
    # La que tiene objetivo y no tiene tráfico sale, como no medible.
    assert filas["busqueda"]["medible"] is False
    assert filas["busqueda"]["cumple_p95"] is None
    assert filas["exportacion"]["p99_ms"] is not None


def test_juntar_servicios_suma_cubos_y_no_promedia_percentiles() -> None:
    from services.gateway.api import _latencias_de_la_instalacion

    limites = [100, 1_000]
    # party: 99 rápidas; sales: 1 lentísima. La media de sus p99 diría 500 ms;
    # el p99 de la instalación es el de 100 peticiones juntas.
    party = {
        "servicio": "party",
        "cubos_ms": limites,
        "operaciones": [{"operacion": "lectura", "cubos": [99, 0, 0], "objetivo_p95_ms": 500}],
    }
    sales = {
        "servicio": "sales",
        "cubos_ms": limites,
        "operaciones": [{"operacion": "lectura", "cubos": [0, 0, 1]}],
    }
    distinto = {
        "servicio": "raro",
        "cubos_ms": [5, 10],
        "operaciones": [{"operacion": "lectura", "cubos": [1000, 0, 0]}],
    }
    filas = _latencias_de_la_instalacion([party, sales, distinto])
    lectura = next(f for f in filas if f["operacion"] == "lectura")
    # El de cubos distintos se queda fuera: mezclarlo daría un número de nada.
    assert lectura["peticiones"] == 100
    assert lectura["objetivo_p95_ms"] == 500
    assert lectura["p95_ms"] is not None and lectura["p95_ms"] <= 100


# ── El identificador de petición ──────────────────────────────────────────


@pytest.mark.db
def test_el_audit_trail_se_filtra_por_peticion(
    db: Any, tenant_id: UUID, contexto_tenant: UUID
) -> None:
    from crmcore.audit import registrar
    from crmcore.seguridad.siem import consultar
    from crmcore.tenancy.context import con_contexto

    with con_contexto(request_id="peticion-de-la-pantalla"):
        registrar(db, accion="prueba.escrita", objeto="cosa", objeto_id=uuid4())
    with con_contexto(request_id="otra-peticion"):
        registrar(db, accion="prueba.escrita", objeto="cosa", objeto_id=uuid4())
    db.flush()

    filas = consultar(db, tenant_id, request_id="peticion-de-la-pantalla")
    assert [f["request_id"] for f in filas] == ["peticion-de-la-pantalla"]


# ── El alta del tenant en cascada ─────────────────────────────────────────


@pytest.mark.db
def test_el_alta_empuja_solo_la_del_tenant_y_dice_como_quedo(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    from crmcore.red import guard_url

    from services.tenancy import suite, suite_conector
    from services.tenancy.modelos import Tenant

    if db.get(Tenant, tenant_id) is None:
        db.add(Tenant(id=tenant_id, slug=f"t{uuid4().hex[:6]}", nombre="Cliente"))
        db.flush()
    monkeypatch.setattr(guard_url, "exigir", lambda url: None)
    monkeypatch.setenv("ENCRYPTION_KEY", "maestra-de-pruebas-suficientemente-larga")
    from crmcore.config import get_settings

    get_settings.cache_clear()
    for nombre in ("contecmind", "contecintelligence"):
        suite.conectar(
            db,
            tenant_id,
            nombre=nombre,
            base_url=f"https://{nombre}.ejemplo.com",
            credenciales={"token": "x"},
            tipo=nombre,
        )
    # Un cambio de usuario pendiente que el botón NO debe empujar.
    suite.encolar(
        db,
        tenant_id,
        herramienta="contecmind",
        objeto="usuario",
        objeto_id="u-1",
        operacion="alta",
        carga={"email": "a@b.c"},
    )
    empujadas: list[tuple[str, str]] = []

    def _aplicar(self: Any, herramienta: Any, fila: Any) -> Any:
        empujadas.append((herramienta.nombre, fila.objeto))
        ok = herramienta.nombre == "contecmind"
        return suite_conector.Resultado(ok=ok, detalle="" if ok else "no contesta")

    monkeypatch.setattr(suite_conector.ConectorGenerico, "aplicar", _aplicar)

    antes = {f["herramienta"]: f["estado"] for f in suite.estado_alta_tenant(db, tenant_id)}
    assert antes == {"contecmind": "sin_alta", "contecintelligence": "sin_alta"}

    suite.provisionar_tenant(db, tenant_id)
    suite_conector.aplicar_alta_tenant(db, tenant_id)

    assert sorted(empujadas) == [("contecintelligence", "tenant"), ("contecmind", "tenant")]
    despues = {f["herramienta"]: f for f in suite.estado_alta_tenant(db, tenant_id)}
    assert despues["contecmind"]["estado"] == "aplicado"
    assert despues["contecintelligence"]["estado"] == "fallido"
    assert despues["contecintelligence"]["ultimo_error"] == "no contesta"
    get_settings.cache_clear()
