"""Qué dispara una automatización (CRM-00.03.03.02, CRM-00.03.03.03).

Las reglas se guardaban, se validaban y se simulaban, pero `disparar()` no lo
llamaba nadie: **no se ejecutaban nunca**. El camino de producción es este — los
eventos de dominio que publican los demás servicios entran aquí y disparan las
reglas que encajan.

Por eventos y no por llamada directa, por tres razones que se notan:

  * Los servicios no se llaman entre sí. Que `party` tuviera que invocar a
    `automation` al guardar una cuenta ataría sus despliegues y haría que una
    caída del motor de reglas impidiera dar de alta clientes.
  * Una automatización **no debe retrasar** la operación que la dispara. Quien
    guarda una cuenta espera a que se guarde su cuenta.
  * Si el motor está caído, los eventos esperan en el bus y las reglas se
    ejecutan al volver. Con una llamada directa, se habrían perdido.

El precio, dicho: entre que se guarda el registro y se ejecuta la regla pasa
alrededor de un segundo. Para «asigna este lead» es irrelevante; para algo que
tuviera que estar hecho antes de responder al usuario, la herramienta no es una
automatización sino una regla de negocio en el propio servicio.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.logging import get_logger

logger = get_logger(__name__)

# Del tipo de evento al disparador y al objeto. Es una tabla y no una heurística
# sobre el nombre: `contact.consent.changed` tiene tres partes y
# `account.created` dos, y adivinar el objeto partiendo por puntos acierta hasta
# que deja de acertar, en silencio.
DISPARADORES: dict[str, tuple[str, str]] = {
    "account.created": ("creacion", "cuenta"),
    "contact.created": ("creacion", "contacto"),
    "lead.created": ("creacion", "lead"),
    "lead.assigned": ("modificacion", "lead"),
    "opportunity.created": ("creacion", "oportunidad"),
    "opportunity.stage.changed": ("modificacion", "oportunidad"),
    "opportunity.won": ("modificacion", "oportunidad"),
    "opportunity.lost": ("modificacion", "oportunidad"),
    "account.merged": ("modificacion", "cuenta"),
    "contact.consent.changed": ("modificacion", "contacto"),
    "record.commented": ("modificacion", "registro"),
}


async def consumir_evento(mensaje: Any) -> None:
    """Dispara las reglas que encajen con este evento.

    Un evento sin reglas no cuesta nada: `aplicables()` no devuelve ninguna y se
    sale. Por eso el patrón de suscripción es ancho — filtrar aquí es más barato
    que mantener la lista de suscripciones al día con la tabla de arriba.
    """
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto

    from services.automation import ejecutores as ejecutores_mod
    from services.automation.motor import disparar

    tipo = getattr(mensaje, "tipo", None) or (
        mensaje.get("tipo") if isinstance(mensaje, dict) else None
    )
    encaje = DISPARADORES.get(str(tipo or ""))
    if encaje is None:
        return

    bruto = getattr(mensaje, "tenant_id", None) or (
        mensaje.get("tenant_id") if isinstance(mensaje, dict) else None
    )
    if not bruto:
        logger.warning("automatizacion.evento_sin_tenant", tipo=tipo)
        return
    tenant_id = UUID(str(bruto))

    disparador, objetivo = encaje
    datos = (
        getattr(mensaje, "data", None)
        or (mensaje.get("data") if isinstance(mensaje, dict) else {})
        or {}
    )
    registro_id = _registro_de(datos, objetivo)

    with (
        con_contexto(tenant_id=tenant_id, origen="automatizacion"),
        unidad_de_trabajo(tenant_id) as uow,
    ):
        trazas = disparar(
            uow.db,
            tenant_id=tenant_id,
            disparador=disparador,
            objetivo=objetivo,
            valores={**datos, "_evento": tipo},
            registro_id=registro_id,
            # Los ejecutores se construyen atados a ESTA unidad de trabajo: los
            # comandos que emitan salen solo si la transacción se confirma.
            ejecutores=ejecutores_mod.construir(uow),
        )
    if trazas:
        logger.info(
            "automatizacion.disparada",
            evento=tipo,
            reglas=len(trazas),
            disparadas=sum(1 for t in trazas if t.resultado == "disparada"),
        )


def _registro_de(datos: dict[str, Any], objetivo: str) -> str | None:
    """El identificador del registro que provocó el evento.

    Se busca por los nombres que usan los eventos del catálogo, en orden: cada
    uno nombra su sujeto a su manera —`cuenta_id`, `lead_id`, `superviviente_id`—
    y no hay un campo común. Tenerlo es lo que permite que la regla actúe sobre
    el registro en vez de solo mirarlo.
    """
    for clave in (f"{objetivo}_id", "registro_id", "objeto_id", "superviviente_id"):
        valor = datos.get(clave)
        if valor:
            return str(valor)
    return None


from crmcore.contratos import Consumo, declarar_consumo  # noqa: E402

# Contract testing dirigido por el consumidor (CRM-00.03.01.03). `campos` está
# declarado porque una regla puede condicionar por un campo de la implantación
# (CRM-00.04.03.05): quitarlo del evento no rompería nada visible en el
# productor, y dejaría de dispararse una automatización que el cliente configuró
# sin que nadie lo relacionara con el cambio.
for _evento, (_disparador, _objetivo) in DISPARADORES.items():
    declarar_consumo(
        Consumo(
            consumidor="automation",
            evento=_evento,
            campos=("campos",),
            obligatorio=False,
            motivo=(
                "Condicionar reglas por los campos propios del tenant sin leer "
                "el esquema del servicio dueño del dato"
            ),
        )
    )
