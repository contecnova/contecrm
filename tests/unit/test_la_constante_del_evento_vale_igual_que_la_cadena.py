"""Emitir con la constante declarada tenía que valer, y no valía.

Medido el 12-10-2026. El catálogo de eventos da una constante por tipo
—`ALTA_CONFIRMADA`, `AI_BUDGET_EXHAUSTED`— y usarla es lo recomendable: ata la
emisión a la declaración y no se escribe mal. Cuatro sitios del producto la
usaban. **Ninguno funcionaba**, y de dos maneras distintas:

  · al volcar el evento, la constante llegaba entera a una columna de texto y
    reventaba: `TypeError: sequence item 0: expected str instance, TipoEvento
    found`. La transacción del cambio se deshacía con ella — en el alta
    autoservicio, eso es la empresa que no se crea con la persona mirando;

  · y antes de reventar, `comprobar_emision` buscaba el tipo en un registro
    indexado por cadena, no lo encontraba y devolvía «no falta ningún campo».
    El contrato dejaba de comprobarse justo en las emisiones mejor escritas.

Lo tapaba la forma de comprobarlo: la prueba del alta miraba `uow._pendientes`,
donde el objeto entra y sale igual, y la del consumidor construía el sobre con
`type=ALTA_CONFIRMADA`. Las dos mitades hablaban un idioma que no existe fuera
de la prueba.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

pytestmark = pytest.mark.db


def _uow(db: Any, tenant_id: UUID) -> Any:
    from crmcore.db.uow import UnidadDeTrabajo

    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


def test_la_puerta_normaliza_las_dos_formas() -> None:
    from crmcore.events.catalogo import clave
    from crmcore.events.dominio import ALTA_CONFIRMADA

    assert clave(ALTA_CONFIRMADA) == "tenant.alta_confirmada"
    assert clave("tenant.alta_confirmada") == "tenant.alta_confirmada"


def test_emitir_con_la_constante_llega_a_la_tabla_de_salida(db: Any, tenant_id: UUID) -> None:
    """Es el fallo tal cual: lo que no llega a la tabla no lo publica nadie."""
    from crmcore.bus.outbox import EventoSaliente
    from crmcore.events.dominio import ALTA_CONFIRMADA
    from sqlalchemy import select

    uow = _uow(db, tenant_id)
    uow.emitir(
        ALTA_CONFIRMADA,
        subject=("tenant", tenant_id),
        data={
            "tenant_id": str(tenant_id),
            "slug": "acme",
            "email": "ana@acme.example",
            "nombre": "Ana",
        },
    )
    uow.volcar()
    db.flush()

    filas = db.execute(select(EventoSaliente)).scalars().all()
    assert [f.tipo for f in filas] == ["tenant.alta_confirmada"]
    assert isinstance(filas[0].tipo, str)
    # Y el sobre que se publica, también: es lo que lee el integrador.
    assert filas[0].sobre["type"] == "tenant.alta_confirmada"


def test_con_la_constante_el_contrato_se_sigue_comprobando(db: Any, tenant_id: UUID) -> None:
    """**El medio fallo callado.** Con el objeto, `comprobar_emision` no
    encontraba el tipo y daba por bueno un `data` vacío: se podía publicar un
    hecho sin los campos que su contrato promete y nadie decía nada.

    Se comprueba con el interruptor estricto puesto, que es como va en las
    pruebas y en los entornos de verificación.
    """
    from crmcore.config import get_settings
    from crmcore.events.dominio import ALTA_CONFIRMADA

    if not get_settings().contratos_emision_estricta:
        pytest.skip("el modo estricto está apagado en este entorno")

    uow = _uow(db, tenant_id)
    with pytest.raises(ValueError) as fallo:
        uow.emitir(ALTA_CONFIRMADA, subject=("tenant", tenant_id), data={"slug": "acme"})
    assert "tenant_id" in str(fallo.value)


def test_suscribirse_con_la_constante_tambien_vale() -> None:
    """La otra mitad. `identity` se suscribe al alta con la constante: el
    comparador recibía un objeto y no le llegaba nunca nada, así que la empresa
    se creaba sin su primer administrador.

    Se mira el arranque real del servicio y lo que llega al bus, no la lista que
    se le pasa: ahí el objeto también entra y sale igual.
    """
    import asyncio

    recibidos: list[Any] = []

    class _BusDeMentira:
        async def suscribir(self, patron: Any, _manejador: Any, *, grupo: str) -> None:
            recibidos.append((patron, grupo))

    from crmcore.bus.inbox import idempotente
    from crmcore.events.catalogo import clave
    from crmcore.events.dominio import ALTA_CONFIRMADA

    # El bucle del arranque, tal cual, con el patrón que declara `identity`.
    suscripciones = [(ALTA_CONFIRMADA, lambda _h: None, "identity-alta-autoservicio")]
    bus = _BusDeMentira()

    async def _correr() -> None:
        for patron, manejador, grupo in suscripciones:
            await bus.suscribir(
                clave(patron), idempotente(manejador, consumidor=grupo), grupo=grupo
            )

    asyncio.run(_correr())
    assert recibidos == [("tenant.alta_confirmada", "identity-alta-autoservicio")]


def test_el_arranque_normaliza_el_patron() -> None:
    """Y que lo haga **el arranque**, no sólo esta prueba: sin esta línea, lo de
    arriba comprueba una tubería que el producto no usa."""
    from pathlib import Path

    fuente = (
        Path(__file__).resolve().parents[2] / "packages/crmcore/crmcore/service.py"
    ).read_text(encoding="utf-8")
    trozo = fuente.split("for patron, manejador, grupo in suscripciones:")[1][:300]
    assert "_clave_de_tipo(patron)" in trozo, trozo
