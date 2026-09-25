"""Lo publicado LLEGA a quien se suscribió (CRM-00.01.01.10).

Esta prueba existe porque durante toda la vida del proyecto no llegó nada.

Se publicaba en `contecrm.<tenant>.<tipo>` y se suscribía a `contecrm.<tipo>`,
sin el segmento del tenant. Ningún subject casaba con ningún patrón, así que el
bus no entregó un solo evento entre servicios: trece esquemas con la tabla de
entrantes a CERO y setecientos cincuenta y siete eventos publicados.

Y no fallaba nada visible. Publicar funcionaba —la tabla de salida se llenaba y
se marcaba como publicada— y lo que dependía de recibir simplemente no ocurría:
la salud de la cuenta no aparecía en su ficha, los ajustes replicados se
quedaban con los de ayer, la clave del tenant no se propagaba. Ninguna de esas
cosas grita; todas se leen como «esto todavía no está hecho».

Sobrevivió porque **ninguna prueba cruzaba las dos mitades**: las que había
comprueban que el evento se ESCRIBE en la tabla de salida, que es la mitad
fácil. Esta comprueba la otra.
"""

from __future__ import annotations

from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def _bus_limpio() -> None:
    from crmcore.bus.memoria import limpiar

    limpiar()
    yield
    limpiar()


def _evento(tipo: str, tenant) -> object:
    from crmcore.events.envelope import Evento, Subject

    return Evento(
        type=tipo,
        tenant_id=tenant,
        subject=Subject(tipo="cuenta", id=str(uuid4())),
    )


async def test_lo_publicado_llega_a_quien_se_suscribio() -> None:
    """El caso que no cubría nadie: publicar y recibir, juntos."""
    from crmcore.bus.memoria import BusEnMemoria

    bus = BusEnMemoria()
    recibidos: list[object] = []

    await bus.suscribir("account.health.scored", lambda e: recibidos.append(e), grupo="prueba")
    await bus.publicar(_evento("account.health.scored", uuid4()))

    assert len(recibidos) == 1, (
        "el evento no ha llegado al suscriptor. Es exactamente el fallo que tuvo "
        "este bus durante toda su vida: publicar y suscribirse construían el "
        "subject de forma distinta."
    )


async def test_llega_sea_cual_sea_el_tenant() -> None:
    """El tenant va en el subject, y el suscriptor de un tipo los quiere todos.

    Si el comodín se perdiera, un servicio recibiría los eventos de un tenant y
    no los de los demás — y eso es peor que no recibir ninguno, porque parece que
    funciona.
    """
    from crmcore.bus.memoria import BusEnMemoria

    bus = BusEnMemoria()
    recibidos: list[object] = []
    await bus.suscribir("account.health.scored", lambda e: recibidos.append(e), grupo="prueba")

    for tenant in (uuid4(), uuid4(), uuid4()):
        await bus.publicar(_evento("account.health.scored", tenant))

    assert len(recibidos) == 3


async def test_no_se_entrega_lo_que_no_se_pidio() -> None:
    """El comodín es de UN segmento, no de todo lo que venga detrás.

    Con `>` en vez de `*`, un `account.created.v2` acabaría en el consumidor de
    `account.created` — y ese consumidor leería una carga con otra forma.
    """
    from crmcore.bus.memoria import BusEnMemoria

    bus = BusEnMemoria()
    recibidos: list[object] = []
    await bus.suscribir("account.created", lambda e: recibidos.append(e), grupo="prueba")

    await bus.publicar(_evento("account.updated", uuid4()))
    await bus.publicar(_evento("account.created.v2", uuid4()))

    assert recibidos == []


def test_el_subject_de_publicar_y_el_de_suscribirse_son_hermanos() -> None:
    """Lo que hacía falta para que esto no volviera a pasar.

    Las dos construcciones tienen que vivir juntas y parecerse: separadas, se
    cambia una y la otra se entera el día que alguien mira por qué no llega un
    evento.
    """
    from crmcore.events.envelope import subject_patron

    from tests.unit.test_bus_entrega import _evento

    tenant = uuid4()
    evento = _evento("account.health.scored", tenant)
    publicado = evento.subject_bus("contecrm")
    patron = subject_patron("contecrm", "account.health.scored")

    assert publicado == f"contecrm.{tenant}.account.health.scored"
    assert patron == "contecrm.*.account.health.scored"
    # Y el uno casa con el otro, que es lo único que de verdad importa.
    from crmcore.bus.memoria import _coincide

    assert _coincide(publicado, patron)


async def test_el_manejador_reconoce_el_tipo_del_evento() -> None:
    """Los consumidores preguntan por `mensaje.tipo`, y el sobre lleva `type`.

    Los dieciséis del sistema hacían `getattr(mensaje, "tipo", None)`, que
    devuelve `None` sin quejarse: el evento llegaba y el manejador decidía en la
    primera línea que no era para él. Ni un error ni un aviso — la tercera capa
    del mismo silencio, detrás del subject sin tenant y del consumidor durable
    que conservaba el filtro viejo.
    """
    from crmcore.bus.memoria import BusEnMemoria

    bus = BusEnMemoria()
    vistos: list[str] = []

    async def manejador(mensaje: object) -> None:
        # Exactamente como lo escriben los consumidores de verdad.
        tipo = getattr(mensaje, "tipo", None)
        if str(tipo or "") == "account.health.scored":
            vistos.append(str(tipo))

    await bus.suscribir("account.health.scored", manejador, grupo="prueba")
    await bus.publicar(_evento("account.health.scored", uuid4()))

    assert vistos == ["account.health.scored"]
