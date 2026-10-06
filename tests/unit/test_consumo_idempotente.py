"""Ningún consumidor deduplicaba (CRM-00.03.01.06, CRM-00.02.02.04).

La unidad de trabajo lo dice en su primera página: «el precio es entrega
**at-least-once**, y por eso todo consumidor deduplica por `dedup_key`». El
buzón de entrada lo dice en la suya: «si el consumidor no deduplica, un reintento
del productor crea la cuenta dos veces, suma el importe dos veces o manda el
correo dos veces — y esos tres fallos son visibles para el cliente final».

**Y no deduplicaba ninguno.** La tabla estaba creada, el barrido que la purga
estaba registrado en los catorce servicios —barriendo una tabla **siempre
vacía**, que es por lo que nadie lo notó— y la única función que escribe en ella
no la llamaba nadie. La garantía estaba escrita en dos sitios y no existía en
ninguno.

La marca va **dentro de la misma transacción que el efecto**, y eso es lo que
obliga a que la unidad de trabajo del consumidor sea la misma que la del
guardián:

  * **antes y aparte** deja el evento marcado sin haberlo procesado si algo falla
    después, y el reintento lo descarta: el hecho se pierde para siempre;
  * **después y aparte** no cubre el caso real: el bus reclama lo que lleva
    mucho sin confirmar (`xautoclaim` en Redis, `nak` y redelivery en NATS), así
    que la segunda entrega entra mientras la primera sigue dentro y las dos
    hacen el efecto.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.db


def _evento(tenant_id: UUID, *, tipo: str = "account.created", clave: str = "") -> Any:
    from crmcore.events.envelope import Evento

    return Evento(
        type=tipo,
        tenant_id=tenant_id,
        subject=("account", uuid4()),
        data={"nombre": "Acme"},
        dedup_key=clave or f"acme:{uuid4()}",
    )


# ── La marca ──────────────────────────────────────────────────────────────


def test_el_mismo_hecho_solo_se_procesa_una_vez(db: Any, tenant_id: UUID) -> None:
    """Es la garantía que el producto promete por escrito en dos sitios y que no
    cumplía en ninguno."""
    import asyncio

    from crmcore.bus.inbox import idempotente

    veces: list[str] = []

    async def manejador(mensaje: Any) -> None:
        veces.append(mensaje.type)

    envuelto = idempotente(manejador, consumidor="pruebas-cuentas")
    evento = _evento(tenant_id)

    asyncio.run(envuelto(evento))
    asyncio.run(envuelto(evento))

    assert veces == ["account.created"], f"se ha procesado {len(veces)} veces"


def test_dos_hechos_distintos_se_procesan_los_dos(db: Any, tenant_id: UUID) -> None:
    """Una deduplicación que descarta de más es una pérdida de datos silenciosa,
    y es la forma más fácil de equivocarse al escribir esto."""
    import asyncio

    from crmcore.bus.inbox import idempotente

    veces: list[Any] = []

    async def manejador(mensaje: Any) -> None:
        veces.append(mensaje.dedup_key)

    envuelto = idempotente(manejador, consumidor="pruebas-cuentas")
    asyncio.run(envuelto(_evento(tenant_id)))
    asyncio.run(envuelto(_evento(tenant_id)))

    assert len(veces) == 2
    assert len(set(veces)) == 2


def test_cada_consumidor_lo_procesa_por_su_cuenta(db: Any, tenant_id: UUID) -> None:
    """La clave es `(dedup_key, consumidor)`. Si fuera solo la clave, el primer
    servicio que procesara un evento se lo quitaría a los demás — y el bus tiene
    catorce consumidores distintos del mismo flujo."""
    import asyncio

    from crmcore.bus.inbox import idempotente

    vistos: list[str] = []

    def _manejador(quien: str) -> Any:
        async def _m(mensaje: Any) -> None:
            vistos.append(quien)

        return _m

    evento = _evento(tenant_id)
    asyncio.run(idempotente(_manejador("ventas"), consumidor="ventas")(evento))
    asyncio.run(idempotente(_manejador("servicio"), consumidor="servicio")(evento))

    assert sorted(vistos) == ["servicio", "ventas"]


def test_dos_tenants_con_la_misma_clave_no_se_pisan(db: Any) -> None:
    """La clave la pone el productor y puede ser «pedido:42». Dos clientes
    distintos tienen su pedido 42, y descartar el segundo sería perderle el alta
    a uno de los dos."""
    import asyncio

    from crmcore.bus.inbox import idempotente

    vistos: list[Any] = []

    async def manejador(mensaje: Any) -> None:
        vistos.append(mensaje.tenant_id)

    envuelto = idempotente(manejador, consumidor="pruebas")
    uno, dos = uuid4(), uuid4()
    asyncio.run(envuelto(_evento(uno, clave="pedido:42")))
    asyncio.run(envuelto(_evento(dos, clave="pedido:42")))

    assert sorted(map(str, vistos)) == sorted(map(str, [uno, dos]))


def test_si_el_efecto_falla_el_hecho_no_queda_marcado(db: Any, tenant_id: UUID) -> None:
    """**Es la razón de que la marca vaya en la misma transacción.** Marcada
    aparte y antes, un fallo posterior dejaría el evento por procesado sin
    haberlo procesado, y el reintento lo descartaría: el hecho se pierde para
    siempre y nadie lo reclama."""
    import asyncio

    from crmcore.bus.inbox import idempotente

    intentos: list[int] = []

    async def manejador(mensaje: Any) -> None:
        intentos.append(1)
        if len(intentos) == 1:
            raise RuntimeError("la primera vez revienta")

    envuelto = idempotente(manejador, consumidor="pruebas-fallo")
    evento = _evento(tenant_id)

    with pytest.raises(RuntimeError):
        asyncio.run(envuelto(evento))
    # El reintento del bus: tiene que volver a entrar.
    asyncio.run(envuelto(evento))

    assert len(intentos) == 2, "el reintento se ha descartado: el hecho se ha perdido"


def test_el_efecto_y_la_marca_comparten_transaccion(db: Any, tenant_id: UUID) -> None:
    """Si el manejador abriera la suya, «o las dos o ninguna» sería mentira."""
    import asyncio

    from crmcore.bus.inbox import idempotente
    from crmcore.db.uow import _ambiente, unidad_de_trabajo

    vistas: list[tuple[Any, Any]] = []

    async def manejador(mensaje: Any) -> None:
        del_entorno = _ambiente.get()
        with unidad_de_trabajo(mensaje.tenant_id) as uow:
            vistas.append((uow.db, del_entorno.db if del_entorno else None))

    asyncio.run(idempotente(manejador, consumidor="pruebas-tx")(_evento(tenant_id)))

    assert len(vistas) == 1
    del_manejador, del_guardian = vistas[0]
    # **El mismo objeto**, no «una sesión que ve lo mismo». En las pruebas todas
    # las sesiones comparten conexión, así que comprobar que ve la fila pasaría
    # igual abriendo otra transacción: lo que distingue el caso es la identidad.
    assert (
        del_manejador is del_guardian
    ), "el manejador ha abierto su propia transacción: «o las dos o ninguna» sería mentira"


def test_la_unidad_de_trabajo_del_entorno_se_suelta(db: Any, tenant_id: UUID) -> None:
    """Sin soltarla, la siguiente tarea de este mismo hilo escribiría en una
    sesión ya cerrada."""
    import asyncio

    from crmcore.bus.inbox import idempotente
    from crmcore.db.uow import _ambiente

    sesiones: list[Any] = []

    async def manejador(mensaje: Any) -> None:
        entorno = _ambiente.get()
        assert entorno is not None
        sesiones.append(entorno.db)

    envuelto = idempotente(manejador, consumidor="pruebas-suelta")

    async def dos_seguidos() -> None:
        # **En el mismo contexto**, que es donde se nota: cada `asyncio.run`
        # abre uno nuevo y la fuga no se vería. Así es como llegan de verdad los
        # mensajes: dos entregas seguidas en la misma tarea.
        await envuelto(_evento(tenant_id))
        await envuelto(_evento(tenant_id))

    assert _ambiente.get() is None
    asyncio.run(dos_seguidos())
    assert _ambiente.get() is None

    assert len(sesiones) == 2
    assert (
        sesiones[0] is not sesiones[1]
    ), "el segundo mensaje ha reutilizado la transacción del primero, que ya está cerrada"


def test_un_mensaje_sin_sobre_se_procesa_igual_y_se_dice(db: Any) -> None:
    """Dejar de procesarlo convertiría un problema de formato en un hecho
    perdido, que es mucho peor que procesarlo dos veces."""
    import asyncio

    from crmcore.bus.inbox import idempotente

    vistos: list[Any] = []

    async def manejador(mensaje: Any) -> None:
        vistos.append(mensaje)

    envuelto = idempotente(manejador, consumidor="pruebas-sin-sobre")
    asyncio.run(envuelto({"tipo": "algo", "data": {}}))

    assert len(vistos) == 1


# ── Que esté puesto en TODAS, no en las que alguien se acordó ─────────────


def test_todas_las_suscripciones_pasan_por_la_deduplicacion() -> None:
    """Envolverlo en cada consumidor serían catorce sitios donde acordarse, y
    «funciona donde alguien se acordó» no es una garantía."""
    import ast
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    fuente = (raiz / "packages" / "crmcore" / "crmcore" / "service.py").read_text(encoding="utf-8")
    arbol = ast.parse(fuente)

    suscripciones = [
        n
        for n in ast.walk(arbol)
        if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "suscribir"
    ]
    assert suscripciones, "no se ha encontrado ninguna suscripción: el recorrido no mira"
    for llamada in suscripciones:
        envoltorio = llamada.args[1] if len(llamada.args) > 1 else None
        assert (
            isinstance(envoltorio, ast.Call) and getattr(envoltorio.func, "id", "") == "idempotente"
        ), "hay una suscripción que no pasa por la deduplicación"


def test_el_barrido_que_purga_el_buzon_tiene_algo_que_purgar(db: Any, tenant_id: UUID) -> None:
    """Barría una tabla siempre vacía. Un barrido que no barre nada nunca no da
    error: contesta cero, que es exactamente lo que contestaría si todo fuera
    bien."""
    import asyncio

    from crmcore.bus.inbox import idempotente
    from crmcore.bus.modelos import EventoEntrante
    from sqlalchemy import func, select

    antes = db.execute(select(func.count()).select_from(EventoEntrante)).scalar_one()

    async def manejador(mensaje: Any) -> None:
        return None

    asyncio.run(idempotente(manejador, consumidor="pruebas-purga")(_evento(tenant_id)))

    assert db.execute(select(func.count()).select_from(EventoEntrante)).scalar_one() == antes + 1


# ── La caché: una sola copia del recorrido ────────────────────────────────


def test_la_invalidacion_de_cache_tiene_una_sola_implementacion() -> None:
    """Había dos: la del módulo de la caché, que no llamaba nadie, y una copia
    suelta en el arranque del servicio que leía `type` y no `tipo`. Dos copias es
    cómo acaban dos sitios resolviendo distinto lo mismo."""
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[2]
    fuente = (raiz / "packages" / "crmcore" / "crmcore" / "service.py").read_text(encoding="utf-8")
    assert "_invalidar_cache" not in fuente, "ha vuelto la copia suelta"
    assert "consumir_invalidacion" in fuente


def test_la_invalidacion_entiende_las_dos_formas_del_mensaje() -> None:
    """La copia que se queda es la tolerante: el bus entrega un `Evento`, y en
    las pruebas y en el bus en memoria a veces llega un diccionario con `tipo`."""
    import asyncio

    from crmcore.cache.respuestas import Politica, clave, consumir_invalidacion

    tenant = uuid4()
    politica = Politica(nombre="listado", ttl_s=60, invalida_con=("account.updated",))
    antes = clave(politica, tenant_id=tenant, usuario_id=None, partes={"p": 1})

    asyncio.run(consumir_invalidacion({"tipo": "account.updated", "tenant_id": str(tenant)}))
    assert clave(politica, tenant_id=tenant, usuario_id=None, partes={"p": 1}) != antes
