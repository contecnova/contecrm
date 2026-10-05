"""«Escucha, respuesta y conversión a caso» — y lo tercero ocurre
(`CRM-04.02.01.06`).

Auditado el 05-10-2026. La clasificación de una mención decidía `abre_caso` y
**no lo abría nadie**: el enunciado prometía la conversión y lo que había era un
booleano en una respuesta JSON.

Lo que cuesta: una queja pública clasificada como caso y sin caso detrás es peor
que no clasificarla. El panel de social dice que se detectó y la cola de soporte
no la tiene, así que nadie la atiende y nadie lo nota — mientras la queja sigue
en abierto, en público.

Va por **comando** y no escribiendo el caso desde marketing: los casos son de
`service` y ningún servicio escribe en el esquema de otro. Y por la tabla de
salida, de modo que si la transacción se deshace la orden no sale.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from crmcore.db.uow import UnidadDeTrabajo


@pytest.fixture
def uow(db: Any, tenant_id: UUID) -> UnidadDeTrabajo:
    return UnidadDeTrabajo(db=db, tenant_id=tenant_id)


class _Principal:
    id = UUID(int=1)
    tenant_id = UUID(int=2)


def _clasificar(uow: UnidadDeTrabajo, texto: str, crisis: list[str] | None = None) -> Any:
    from services.marketing.api_canales_externos import MencionIn, clasificar

    return clasificar(
        MencionIn(
            mencion={"id": "m1", "texto": texto, "tipo": "queja"}, palabras_de_crisis=crisis or []
        ),
        uow,
        _Principal(),  # type: ignore[arg-type]
    )


def test_una_queja_pide_el_caso(uow: UnidadDeTrabajo) -> None:
    salida = _clasificar(uow, "llevo tres semanas sin que me contesten")
    assert salida["abre_caso"] is True
    assert salida["caso_pedido"] is True
    pedidos = [e for e in uow._pendientes if e.get("data", {}).get("objeto") == "caso"]
    assert pedidos, "se clasificó como caso y no se ha pedido ninguno"
    assert pedidos[0]["data"]["accion"] == "crear"
    assert pedidos[0]["data"]["datos"]["origen"] == "social"


def test_una_crisis_no_entra_en_la_cola_como_una_queja_mas(uow: UnidadDeTrabajo) -> None:
    """Meterlas igual es lo que hace que la crisis espere su turno."""
    salida = _clasificar(uow, "esto es un fraude", crisis=["fraude"])
    assert salida["tipo"] == "crisis"
    pedidos = [e for e in uow._pendientes if e.get("data", {}).get("objeto") == "caso"]
    assert pedidos[0]["data"]["datos"]["severidad"] == "critica"


def test_un_agradecimiento_no_abre_expediente(uow: UnidadDeTrabajo) -> None:
    """Convertir cada mención en un caso llena la cola de cosas que no piden
    nada, y hace que el agente aprenda a cerrar sin leer."""
    from services.marketing.api_canales_externos import MencionIn, clasificar

    salida = clasificar(
        MencionIn(
            mencion={"id": "m2", "texto": "gracias por el envío rápido", "tipo": "mencion_neutra"}
        ),
        uow,
        _Principal(),  # type: ignore[arg-type]
    )
    assert salida["abre_caso"] is False
    assert not [e for e in uow._pendientes if e.get("data", {}).get("objeto") == "caso"]
