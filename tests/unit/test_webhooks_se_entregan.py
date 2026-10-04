"""Los webhooks llegan de verdad (CRM-00.03.02, eventos salientes).

**No llegaban.** `entrega.py` tenía el reparto entero —casar la suscripción,
firmar, mandar, registrar, programar el reintento y desactivar el endpoint
muerto— con sus pruebas unitarias en verde, y **no lo importaba nadie**: un
`grep` en todo el árbol daba una sola coincidencia, un fichero de pruebas. El
servicio declaraba sus rutas y ningún consumidor.

Para el cliente era el peor fallo posible: crea su suscripción, la ve en el
listado, mira su historial de entregas, lo ve vacío **y cree que todavía no ha
pasado nada**. No hay error que buscar, porque no hay error.

Por eso estas pruebas son **del camino y no de la función**. Probar `entregar()`
habría salido en verde todo este tiempo: `entregar()` siempre estuvo bien. Lo
que faltaba era que alguien lo llamara, y eso sólo se ve metiendo un evento por
donde entran de verdad y mirando si sale un POST.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

# EN CADA PUSH, y no en el bloque. Aquí se comprueba que un evento de un tenant
# no salga por el webhook de otro, y mandarle a un cliente lo que pasa en la casa
# de otro es la fuga más cara que puede tener un sistema de eventos: no se
# descubre con un 403, se descubre cuando el receptor lo lee. Son tres segundos.
pytestmark = [pytest.mark.db, pytest.mark.despliegue]


def _evento(tenant_id: UUID, tipo: str = "account.created", datos: dict[str, Any] | None = None):
    from crmcore.events.envelope import Evento, Subject

    return Evento(
        id=uuid4(),
        type=tipo,
        version=1,
        tenant_id=tenant_id,
        subject=Subject(tipo="cuenta", id=str(uuid4())),
        data=datos if datos is not None else {"nombre": "ACME", "importe": 100},
    )


def _suscribir(
    db: Any,
    tenant_id: UUID,
    *,
    eventos: list[str],
    url: str = "https://cliente.ejemplo/hook",
    condiciones: list[dict[str, Any]] | None = None,
    activa: bool = True,
) -> Any:
    from services.eventing.modelos import Suscripcion

    fila = Suscripcion(
        tenant_id=tenant_id,
        nombre=f"hook-{uuid4().hex[:6]}",
        url=url,
        secreto="secreto-de-pruebas",
        eventos=eventos,
        condiciones=condiciones or [],
        activa=activa,
    )
    db.add(fila)
    db.commit()
    return fila


class _Respuesta:
    def __init__(self, codigo: int = 200, texto: str = "ok") -> None:
        self.status_code = codigo
        self.text = texto


class _ClienteFalso:
    """Sustituye SOLO la salida a la red, y apunta lo que se mandó.

    No sustituye el consumidor ni la entrega: eso es lo que se está probando.
    Lo único que no puede ocurrir en una prueba es el POST a un dominio de
    fuera.
    """

    def __init__(self, recibidas: list[dict[str, Any]], codigo: int = 200) -> None:
        self._recibidas = recibidas
        self._codigo = codigo

    async def __aenter__(self) -> _ClienteFalso:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def post(self, url: str, *, content: bytes, headers: dict[str, str]) -> _Respuesta:
        self._recibidas.append({"url": url, "cuerpo": content, "cabeceras": headers})
        return _Respuesta(self._codigo)


@pytest.fixture
def salida(monkeypatch: Any) -> list[dict[str, Any]]:
    """La red, apuntada. Devuelve la lista de lo que se mandó de verdad."""
    recibidas: list[dict[str, Any]] = []
    from services.eventing import entrega as mod

    monkeypatch.setattr(
        mod, "cliente_seguro_async", lambda **_: _ClienteFalso(recibidas), raising=True
    )
    return recibidas


# ── El camino entero: del bus al POST ─────────────────────────────────────


async def test_un_evento_del_bus_acaba_en_un_post_al_cliente(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, salida: list[dict[str, Any]]
) -> None:
    """La mitad que no existía.

    Se mete el evento por el consumidor —que es por donde entra de verdad— y no
    se llama a `entregar()`. Si alguien quita el consumidor del `main`, esta
    prueba cae y las unitarias de `entrega.py` siguen en verde, que es
    exactamente lo que pasó durante meses.
    """
    from services.eventing.consumidores import consumir_evento

    _suscribir(db, tenant_id, eventos=["account.created"])
    await consumir_evento(_evento(tenant_id))

    assert len(salida) == 1, f"No ha salido ningún POST: {salida}"
    assert salida[0]["url"] == "https://cliente.ejemplo/hook"


async def test_va_firmado_y_con_la_clave_de_deduplicacion(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, salida: list[dict[str, Any]]
) -> None:
    """Sin firma, el receptor no puede saber que el evento es nuestro."""
    from crmcore.security.firma import H_FIRMA, H_MOMENTO, firmar

    from services.eventing.consumidores import consumir_evento

    _suscribir(db, tenant_id, eventos=["account.*"])
    await consumir_evento(_evento(tenant_id))

    assert salida, "no ha salido nada"
    cabeceras = salida[0]["cabeceras"]
    assert H_FIRMA in cabeceras and H_MOMENTO in cabeceras
    # La firma es la de ESTE cuerpo: una firma que no valida no protege de nada.
    esperada = firmar(salida[0]["cuerpo"], "secreto-de-pruebas", int(cabeceras[H_MOMENTO]))
    assert cabeceras[H_FIRMA] == esperada
    # Y la clave de deduplicación en cabecera, para descartar sin parsear.
    assert cabeceras.get("X-Contecrm-Dedup")


# ── La otra mitad: a quien no lo ha pedido, NO ────────────────────────────


async def test_no_llega_a_quien_no_lo_ha_suscrito(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, salida: list[dict[str, Any]]
) -> None:
    """Sin esto, «entrega webhooks» se implementa como «entrega a todos» y sale
    en verde."""
    _suscribir(db, tenant_id, eventos=["deal.won"], url="https://otro.ejemplo/hook")

    from services.eventing.consumidores import consumir_evento

    await consumir_evento(_evento(tenant_id, tipo="account.created"))

    assert salida == [], f"Se ha entregado un evento que nadie pidió: {salida}"


async def test_una_suscripcion_desactivada_no_recibe(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, salida: list[dict[str, Any]]
) -> None:
    _suscribir(db, tenant_id, eventos=["account.created"], activa=False)

    from services.eventing.consumidores import consumir_evento

    await consumir_evento(_evento(tenant_id))
    assert salida == [], "Una suscripción desactivada ha recibido un evento"


async def test_las_condiciones_de_la_suscripcion_se_respetan(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, salida: list[dict[str, Any]]
) -> None:
    """Suscribirse a «oportunidad ganada de más de 10.000» y recibir todas es
    ruido que acaba con el integrador filtrando de su lado o desconectando."""
    _suscribir(
        db,
        tenant_id,
        eventos=["account.created"],
        condiciones=[{"atributo": "importe", "op": ">", "valor": 1000}],
    )

    from services.eventing.consumidores import consumir_evento

    await consumir_evento(_evento(tenant_id, datos={"importe": 100}))
    assert salida == [], "Ha llegado un evento que la condición excluía"

    await consumir_evento(_evento(tenant_id, datos={"importe": 5000}))
    assert len(salida) == 1, "No ha llegado el evento que la condición SÍ admitía"


async def test_un_evento_de_otro_tenant_no_llega_aqui(
    db: Any,
    tenant_id: UUID,
    otro_tenant_id: UUID,
    contexto_tenant: UUID,
    salida: list[dict[str, Any]],
) -> None:
    """Mandarle a un cliente lo que pasa en la casa de otro es la fuga más cara
    que puede tener un sistema de eventos."""
    _suscribir(db, tenant_id, eventos=["account.created"])

    from services.eventing.consumidores import consumir_evento

    await consumir_evento(_evento(otro_tenant_id))
    assert salida == [], "Un evento de otro tenant ha salido por este webhook"


# ── El reintento: que alguien recoja lo fallido ───────────────────────────


async def test_lo_que_falla_queda_pendiente_y_el_relevo_lo_recoge(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    """La tercera mitad.

    Probar sólo que la lista de pendientes se llena es probar lo que ya
    funcionaba: `pendientes_de_reintento` siempre estuvo bien. Lo que no existía
    era quien la recorriera, así que esto mete un fallo y **ejecuta la vuelta
    del relevo**.
    """
    from datetime import datetime, timezone

    from crmcore.bus.modelos import EventoSaliente

    from services.eventing import entrega as mod
    from services.eventing.consumidores import RelevoDeReintentos, consumir_evento
    from services.eventing.entrega import pendientes_de_reintento

    _suscribir(db, tenant_id, eventos=["account.created"])
    evento = _evento(tenant_id)

    # El sobre se conserva: es lo que permite reconstruir lo que se mandó.
    db.add(
        EventoSaliente(
            tenant_id=tenant_id,
            tipo=evento.type,
            version=evento.version,
            subject_tipo=evento.subject.tipo,
            subject_id=evento.subject.id,
            dedup_key=evento.dedup_key,
            sobre=evento.a_dict(),
            publicado_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    # Primera vuelta: el endpoint contesta 500.
    fallidas: list[dict[str, Any]] = []
    monkeypatch.setattr(
        mod, "cliente_seguro_async", lambda **_: _ClienteFalso(fallidas, codigo=500), raising=True
    )
    await consumir_evento(evento)
    assert len(fallidas) == 1, "no se intentó la primera entrega"

    from sqlalchemy import select

    from services.eventing.modelos import Entrega

    fallada = db.execute(select(Entrega).where(Entrega.resultado == "fallido")).scalars().all()
    assert fallada, "una entrega fallida no ha quedado registrada"
    assert (
        fallada[0].proximo_intento_at is not None
    ), "la entrega fallida no tiene programado un reintento: el backoff no se aplicó"

    # Se adelanta el reloj de la espera. Lo que se prueba es que el relevo la
    # recoja, no la política de backoff, que tiene su propia prueba — y esperar
    # los cinco segundos reales sería pagar reloj por comprobar lo mismo.
    for fila in fallada:
        fila.proximo_intento_at = datetime.now(timezone.utc)
    db.commit()

    assert pendientes_de_reintento(db), "el relevo no vería la entrega que ya toca reintentar"

    # Segunda vuelta: ahora contesta 200 y la recoge EL RELEVO.
    logradas: list[dict[str, Any]] = []
    monkeypatch.setattr(
        mod, "cliente_seguro_async", lambda **_: _ClienteFalso(logradas, codigo=200), raising=True
    )
    hechos = await RelevoDeReintentos()._una_vuelta()

    assert hechos == 1, "el relevo no ha recogido la entrega pendiente"
    assert len(logradas) == 1, "el relevo no ha vuelto a llamar al endpoint"


# ── Y que el servicio lo tenga enchufado ──────────────────────────────────


def test_el_servicio_declara_su_consumidor_y_su_relevo() -> None:
    """Lo que faltaba no era el reparto: era el enchufe.

    Si alguien quita el consumidor del `main`, todas las pruebas de `entrega.py`
    seguirían en verde y los webhooks volverían a no salir. Eso ya pasó.
    """
    import inspect

    from services.eventing import main

    fuente = inspect.getsource(main)
    assert "consumidores=" in fuente, (
        "El servicio de eventos no declara ningún consumidor: nadie repartirá "
        "los eventos y ninguna otra prueba lo notará."
    )
    assert "consumir_evento" in fuente
    assert "al_arrancar" in fuente, (
        "Sin el relevo de reintentos, `proximo_intento_at` es una fecha que "
        "nadie vuelve a mirar."
    )


def test_la_descripcion_del_servicio_no_promete_lo_que_no_hace() -> None:
    """La frase que nos ha mordido tres veces hoy.

    `exigir_operativo` decía «lo llama el gateway en cada petición» y el gateway
    no la llamaba. Aquí la descripción promete reintentos y desactivación
    automática: ahora los dos se ejecutan, y esta prueba ata la promesa a que
    sigan enchufados.
    """
    import inspect

    from services.eventing import main

    fuente = inspect.getsource(main)
    if "reintentos" in main.app.description:
        assert "al_arrancar" in fuente, (
            "La descripción promete reintentos y no hay quien los recoja. O se "
            "enchufa el relevo, o se quita la promesa."
        )


async def test_un_evento_demasiado_grande_no_se_manda_ni_se_reintenta(
    db: Any, tenant_id: UUID, contexto_tenant: UUID, monkeypatch: Any
) -> None:
    """`WEBHOOK_MAX_PAYLOAD_KB` existía, se documentaba y no lo leía nadie.

    Se mandaba lo que hubiera. Un evento gigante revienta al receptor —que es lo
    que el ajuste dice que evita— y encima se reintenta, así que el mismo
    payload imposible vuelve cada pocos minutos.

    Y no se recorta: un JSON cortado por la mitad es peor que no mandarlo,
    porque el receptor lo parsea, falla, y en su registro ve «JSON inválido» en
    vez de «esto era demasiado grande».

    Las dos mitades: con el tope bajo no sale, con el tope alto sale.
    """
    from crmcore.config import get_settings

    from services.eventing.entrega import entregar

    llamadas: list[Any] = []

    async def _post_falso(self: Any, url: str, **kwargs: Any) -> Any:
        llamadas.append(url)

        class _R:
            status_code = 200
            text = "ok"

        return _R()

    import httpx

    monkeypatch.setattr(httpx.AsyncClient, "post", _post_falso)

    suscripcion = _suscribir(db, tenant_id, eventos=["account.created"])
    # Un evento grande de verdad, no uno truncado: lo que se prueba es el tope.
    evento = _evento(tenant_id, datos={"nombre": "ACME", "relleno": "x" * 40_000})

    monkeypatch.setenv("WEBHOOK_MAX_PAYLOAD_KB", "1")
    get_settings.cache_clear()
    salida = await entregar(db, suscripcion, evento)
    assert salida.resultado == "fallido"
    assert "tope de entrega" in (salida.error or ""), salida.error
    assert salida.proximo_intento_at is None, (
        "se ha programado reintento de un evento que no cabe: el mismo payload "
        "imposible volvería cada pocos minutos para siempre"
    )
    assert llamadas == [], "ha llegado a llamar al endpoint con un evento que no cabe"

    monkeypatch.setenv("WEBHOOK_MAX_PAYLOAD_KB", "256")
    get_settings.cache_clear()
    salida = await entregar(db, suscripcion, evento)
    assert salida.resultado == "entregado", (
        "con el tope en 256 KB tendría que entregarse: si no, el tope no se lee "
        "y lo que hay es un rechazo constante"
    )
    assert llamadas, "no ha llamado al endpoint"
    get_settings.cache_clear()
