"""Leads y oportunidades en lote (CRM-00.02.01.11).

Adaptadores, como en `party`: mismo esquema Pydantic y misma función de
`servicio.py` que el alta de una en una. Aquí importa todavía más que allí,
porque la captura de leads es masiva por naturaleza —una feria, una lista
comprada, un formulario que descarga mil registros de golpe— y es exactamente
donde se pierde el enrutamiento, la puntuación y la trazabilidad de origen si el
camino masivo escribe por su cuenta.

**Ni leads ni oportunidades ofrecen borrado, y no por olvido.** Un lead se
descarta con motivo (`POST /leads/{id}/descartar`) y una oportunidad se cierra
como perdida; ninguno de los dos se borra, porque su valor está justamente en
que consten los que no salieron. Ofrecer un borrado masivo que la API individual
no tiene sería abrir por el lote la puerta que el diseño cerró.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.db.uow import UnidadDeTrabajo
from crmcore.http.masivo_router import RecursoMasivo, registrar_recursos

from services.sales import servicio as svc
from services.sales.esquemas import ActualizarOportunidad, CrearLead, CrearOportunidad


def _crear_lead(uow: UnidadDeTrabajo, elemento: dict[str, Any]) -> UUID:
    datos = CrearLead.model_validate(elemento)
    return svc.crear_lead(uow, **datos.model_dump()).id


def _crear_oportunidad(uow: UnidadDeTrabajo, elemento: dict[str, Any]) -> UUID:
    datos = CrearOportunidad.model_validate(elemento)
    return svc.crear_oportunidad_nueva(uow, **datos.model_dump()).id


def _actualizar_oportunidad(
    uow: UnidadDeTrabajo, oportunidad_id: UUID, campos: dict[str, Any]
) -> None:
    datos = ActualizarOportunidad.model_validate(campos)
    svc.actualizar_oportunidad(
        uow, oportunidad_id, datos.model_dump(exclude_unset=True, exclude_none=True)
    )


# Sin `upsert`: un lead duplicado NO se pisa, se detecta. El servicio ya tiene
# la deduplicación y el enrutamiento, y un upsert por correo fundiría el lead de
# la feria de marzo con el del formulario de octubre, que son dos intenciones de
# compra distintas de la misma persona y valen como dos.
LEADS = RecursoMasivo(
    recurso="leads",
    objeto="lead",
    permisos={"crear": "lead:write"},
    crear=_crear_lead,
)

OPORTUNIDADES = RecursoMasivo(
    recurso="oportunidades",
    objeto="oportunidad",
    permisos={"crear": "opportunity:write", "actualizar": "opportunity:write"},
    crear=_crear_oportunidad,
    actualizar=_actualizar_oportunidad,
)

RECURSOS = (LEADS, OPORTUNIDADES)

registrar_recursos(RECURSOS)
