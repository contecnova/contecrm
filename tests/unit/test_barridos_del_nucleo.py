"""Las tablas del núcleo se purgan en todos los servicios, no en los que alguien recordó.

Tres funciones de purga estaban escritas, probadas y **sin llamador**, así que
tres tablas crecían sin techo en los catorce servicios a la vez:

    crmcore.bus.inbox.purgar            claves de deduplicación de entrantes
    crmcore.bus.outbox.purgar_publicados  eventos ya publicados
    crmcore.datos.adjuntos.purgar_huerfanos  ficheros que nunca se enlazaron

Y con ellas, `INBOX_RETENCION_DIAS` era un ajuste documentado y editable que no
hacía nada: el plazo que el cliente pusiera daba igual porque nadie purgaba.

El guardián que existía para esto —«ninguna tarea periódica queda suelta»— no
las vio porque **solo miraba `services/`**, y estas viven en `packages/crmcore`.
Un guardián que no mira donde está el código pasa en verde por no haber mirado.

Van registradas en `crear_servicio` y no en cada `main.py` por lo mismo que la
idempotencia se monta global: catorce sitios donde acordarse no es una garantía,
y ya se demostró.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

pytestmark = pytest.mark.db


def test_todo_servicio_arranca_con_sus_barridos_del_nucleo() -> None:
    """Cada uno con el nombre del servicio delante, para poder distinguirlos en
    el registro cuando uno falle.

    Se comparan los NOMBRES y no el número: «son tres» obliga a tocar esta
    prueba cada vez que se añade uno, y lo que hay que comprobar es que no
    desaparezca ninguno — que es el fallo que importa, porque un barrido que deja
    de arrancar no se nota hasta que su tabla ha crecido meses.
    """
    from crmcore.service import _barridos_del_nucleo

    nombres = {t.nombre for t in _barridos_del_nucleo("pruebas")}

    assert nombres == {
        "pruebas.inbox",
        "pruebas.outbox",
        "pruebas.adjuntos_huerfanos",
        # El aviso de que un tenant se acerca a un tope. Estaba calculado y sólo
        # se veía abriendo el panel de consumo (11-10-2026).
        "pruebas.aviso_de_cuotas",
    }, nombres


def test_el_plazo_de_la_bandeja_de_entrada_sale_de_la_configuracion(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    """`INBOX_RETENCION_DIAS` existía, se documentaba y no lo leía nadie.

    Se comprueban **las dos mitades** con una clave procesada hace 10 días: con
    el plazo en 30 se queda, con el plazo en 3 se va. Sin la primera, un barrido
    que borrara todo pasaría igual.
    """
    from datetime import datetime, timedelta, timezone

    from crmcore.bus.inbox import purgar
    from crmcore.bus.modelos import EventoEntrante
    from crmcore.config import get_settings
    from sqlalchemy import select

    fila = EventoEntrante(
        tenant_id=tenant_id,
        consumidor="pruebas",
        dedup_key=f"k-{tenant_id}",
        tipo="prueba.evento",
        procesado_at=datetime.now(timezone.utc) - timedelta(days=10),
    )
    db.add(fila)
    db.flush()

    def quedan() -> int:
        return len(
            db.execute(select(EventoEntrante).where(EventoEntrante.tenant_id == tenant_id))
            .scalars()
            .all()
        )

    monkeypatch.setenv("INBOX_RETENCION_DIAS", "30")
    get_settings.cache_clear()
    purgar(db, dias=int(get_settings().inbox_retencion_dias))
    db.flush()
    assert quedan() == 1, "con 30 días de plazo, una clave de hace 10 no se borra"

    monkeypatch.setenv("INBOX_RETENCION_DIAS", "3")
    get_settings.cache_clear()
    purgar(db, dias=int(get_settings().inbox_retencion_dias))
    db.flush()
    assert quedan() == 0, (
        "con 3 días de plazo, una clave de hace 10 tiene que irse: si no, el "
        "plazo no se está leyendo"
    )
    get_settings.cache_clear()


def test_los_huerfanos_se_barren_tenant_a_tenant_y_uno_malo_no_para_al_resto() -> None:
    """Un fallo en el tenant 40 no puede parar a los 200 siguientes, y el que
    falla deja su identificador y su motivo — no un contador."""
    from crmcore.tareas import por_tenant

    vistos: list[str] = []

    def tenants() -> list[str]:
        return ["a", "malo", "b"]

    def trabajo(tenant: str) -> dict[str, Any]:
        if tenant == "malo":
            raise RuntimeError("este revienta")
        vistos.append(tenant)
        return {"borrados": 1}

    salida = por_tenant(tenants, trabajo)()

    assert vistos == ["a", "b"], "un tenant que falla ha parado a los siguientes"
    assert salida["tenants"] == 2
    assert salida["fallidos"] == 1
    # El identificador y el motivo, no un contador: la página de estado enseña
    # esta salida, y un «1» manda a buscar al registro del servidor.
    assert salida["cuales"][0]["tenant"] == "malo"
    assert "este revienta" in salida["cuales"][0]["error"]


# ── El readiness no se cuelga ─────────────────────────────────────────────


def test_el_readiness_se_rinde_a_tiempo_y_lo_dice(monkeypatch: Any) -> None:
    """`HEALTH_CHECK_TIMEOUT_S` existía, se documentaba y no lo leía nadie.

    Con la base colgada, el readiness se colgaba con ella. Entonces el que
    decide es el tiempo de espera del orquestador, que mata el proceso sin dejar
    ni un diagnóstico: en el registro no queda «la base no contesta», queda un
    contenedor reiniciado. Decir «no listo» en tres segundos es infinitamente
    más útil que no decir nada en treinta.

    Se planta una base que tarda, se pone el plazo por debajo, y se comprueba
    que contesta **503 y con el motivo dentro** — no que se cuelgue ni que
    mienta diciendo que está bien.
    """
    import time as _time

    from crmcore.config import get_settings
    from crmcore.service import crear_servicio
    from starlette.testclient import TestClient

    app = crear_servicio(
        nombre="pruebas-readiness",
        descripcion="readiness acotado",
        routers=[],
        necesita_db=False,
        necesita_bus=False,
    )

    def _lenta() -> Any:
        _time.sleep(2.0)
        raise AssertionError("no tendría que haber llegado aquí")

    import crmcore.db.session as sesion_mod

    monkeypatch.setattr(sesion_mod, "get_engine", _lenta)
    monkeypatch.setenv("HEALTH_CHECK_TIMEOUT_S", "0.2")
    get_settings.cache_clear()

    with TestClient(app) as cliente:
        # SE CRONOMETRA LA PETICIÓN, no el bloque entero. `asyncio.to_thread`
        # deja de ESPERAR al hilo, pero no lo interrumpe: la llamada bloqueante
        # sigue durmiendo sus dos segundos, y al cerrar el cliente se espera al
        # ejecutor. Midiendo el `with` entero salían 2,0 s y parecía que el
        # plazo no se aplicaba, cuando la respuesta había salido a los 0,2.
        empezo = _time.perf_counter()
        salida = cliente.get("/health/ready")
        tardo = _time.perf_counter() - empezo

    assert salida.status_code == 503, salida.text[:200]
    assert "no contesta" in salida.json()["comprobaciones"]["db"], salida.json()
    assert tardo < 2.0, (
        f"ha tardado {tardo:.1f} s en rendirse con el plazo en 0,2 s: el plazo "
        "no se está aplicando y el readiness se cuelga con la base"
    )
    get_settings.cache_clear()


# ── El recálculo nocturno de la salud ─────────────────────────────────────


def test_la_salud_se_recalcula_sola_y_con_el_plazo_configurado(monkeypatch: Any) -> None:
    """`SALUD_RECALCULO_HORAS` existía, se documentaba y no lo leía nadie.

    La medición solo se disparaba si alguien pulsaba un botón, así que la lista
    de cuentas en riesgo enseñaba lo que se midió la última vez que alguien se
    acordó. Una lista así se abre dos veces y se deja de mirar — que es
    exactamente lo que ese número venía a evitar.
    """
    from crmcore.config import get_settings

    from services.intelligence.main import _tareas

    monkeypatch.setenv("SALUD_RECALCULO_HORAS", "6")
    get_settings.cache_clear()

    tareas = _tareas()

    assert [t.nombre for t in tareas] == ["intelligence.salud"]
    assert tareas[0].intervalo_s == 6 * 3600, (
        "el intervalo no sale de la configuración: quien lo cambie en la "
        "pantalla de ajustes no cambiará nada"
    )
    get_settings.cache_clear()


# ── La petición que no contesta se corta ──────────────────────────────────


def test_una_peticion_que_no_contesta_se_corta_con_504(monkeypatch: Any) -> None:
    """`REQUEST_TIMEOUT_S` existía, se documentaba y no lo leía nadie.

    Una consulta desbocada retenía su conexión hasta que el cliente se rendía, y
    cuarenta de esas dejan al servicio sin pool con la base perfectamente sana.

    Las dos mitades: con el plazo corto se corta, y con el plazo largo la misma
    ruta contesta. Sin la segunda, un cambio que cortara todo pasaría igual.
    """
    import asyncio

    from crmcore.config import get_settings
    from crmcore.service import crear_servicio
    from fastapi import APIRouter
    from starlette.testclient import TestClient

    router = APIRouter()

    @router.get("/lenta", summary="Tarda más de un segundo")
    async def lenta() -> dict[str, bool]:
        # Por encima del mínimo que admite el ajuste, que es 1 s: no se baja el
        # mínimo para que quepa una prueba.
        await asyncio.sleep(1.4)
        return {"ok": True}

    app = crear_servicio(
        nombre="pruebas-tiempo",
        descripcion="tiempo máximo",
        routers=[router],
        necesita_db=False,
        necesita_bus=False,
    )

    monkeypatch.setenv("REQUEST_TIMEOUT_S", "1")
    get_settings.cache_clear()
    with TestClient(app) as cliente:
        cortada = cliente.get("/api/v1/lenta")
    assert cortada.status_code == 504, cortada.text[:200]
    assert cortada.json()["error_code"] == "http.tiempo_agotado"

    monkeypatch.setenv("REQUEST_TIMEOUT_S", "30")
    get_settings.cache_clear()
    with TestClient(app) as cliente:
        entera = cliente.get("/api/v1/lenta")
    assert entera.status_code == 200, (
        "con 30 s de plazo la misma ruta tiene que contestar: si no, el plazo "
        "no se lee y lo que hay es un corte constante"
    )
    get_settings.cache_clear()


def test_las_purgas_esperan_su_turno_y_lo_que_recupera_trabajo_no() -> None:
    """Una purga no corre en la primera vuelta; un barrido que recupera sí.

    Arrancar catorce servicios a la vez en un despliegue dispararía catorce
    borrados masivos simultáneos contra la misma base, justo en el momento de
    más carga. Y en la suite lo que hacía era peor: cada aplicación de prueba
    que arrancaba borraba filas de las demás, y seis pruebas empezaron a fallar
    en conjunto pasando sueltas.

    Lo contrario para lo que recupera trabajo atrasado —recordatorios vencidos,
    reintentos pendientes—: lo que se quedó sin hacer mientras el servicio
    estaba parado es justo lo primero que hay que hacer.
    """
    import asyncio

    from crmcore.tareas import RelevoDeTareas, Tarea, _estado

    corridas: list[str] = []

    purga = Tarea("prueba.purga", 3600, lambda: corridas.append("purga") or {}, al_arrancar=False)
    recupera = Tarea("prueba.recupera", 3600, lambda: corridas.append("recupera") or {})

    for t in (purga, recupera):
        _estado.pop(t.nombre, None)

    asyncio.run(RelevoDeTareas([purga, recupera]).una_vuelta())

    assert corridas == [
        "recupera"
    ], f"en la primera vuelta tenía que correr solo lo que recupera: {corridas}"
    for t in (purga, recupera):
        _estado.pop(t.nombre, None)
