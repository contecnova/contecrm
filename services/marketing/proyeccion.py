"""Cómo se rellena el perfil de marketing (CRM-02.01.01.01).

`marketing` no puede leer el esquema de `party` ni el de `sales`, así que la
proyección local se alimenta **por evento**. Es el mismo patrón que ya usan los
ajustes en caliente, los tipos de cambio, los calendarios y el esquema del
tenant, y por el mismo motivo: calcular un segmento no puede depender de que otro
servicio esté en pie ni costar cien mil llamadas de red.

Dos cosas que se dicen en voz alta porque son el precio de esta decisión:

**El perfil va por detrás de la ficha.** Un contacto creado hace dos segundos
puede no estar todavía. Para marketing es aceptable —una campaña no se lanza en
el mismo segundo en que entra un lead—, pero quien mire el tamaño de un segmento
tiene que poder saber de cuándo son los datos, y por eso se guarda
`sincronizado_at` y se enseña.

**Lo que el evento no trae, aquí no existe.** No se inventa: un atributo que el
productor no publica sale como nulo y el segmento que dependa de él no encontrará
a nadie. Es preferible a rellenarlo con un valor por defecto, que daría un
segmento que parece funcionar y selecciona mal.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from crmcore.logging import get_logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.marketing.modelos import PerfilMarketing

logger = get_logger(__name__)

# Qué evento alimenta qué objeto. Cerrado a propósito: un patrón ancho metería en
# el perfil cualquier cosa que llevara un identificador, y esta tabla es la que
# decide a quién se le escribe.
# `contact.updated` **no está** aquí a propósito: hoy nadie lo emite. Declararlo
# como consumo haría que el gate de contratos avisara de un productor que falta, y
# lo que falta de verdad es el evento — mientras no exista, un cambio de correo de
# un contacto no llega al perfil de marketing, y eso está escrito aquí para que se
# vea en vez de descubrirse cuando un envío rebote.
EVENTOS: dict[str, tuple[str, str]] = {
    "contact.created": ("contacto", "contacto_id"),
    "contact.consent.changed": ("contacto", "contacto_id"),
    "lead.created": ("lead", "lead_id"),
    "lead.assigned": ("lead", "lead_id"),
    "lead.converted": ("lead", "lead_id"),
    "account.created": ("cuenta", "cuenta_id"),
    "account.merged": ("cuenta", "cuenta_id"),
    "record.deleted": ("", "objeto_id"),
    # El partner no alimenta el perfil de marketing: alimenta la proyección de
    # los fondos (CRM-03.04.01.04). Se despacha aparte, unas líneas más abajo,
    # porque escribe en otra tabla y mezclarlo aquí habría metido un partner en
    # la lista de contactos segmentables.
}

# Campos del evento que se copian tal cual al perfil.
COPIABLES = (
    "email",
    "telefono",
    "nombre",
    "pais",
    "sector",
    "cargo",
    "origen",
    "estado",
    "empleados",
    "facturacion",
)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def aplicar(
    db: Session, *, tenant_id: UUID, objeto: str, objeto_id: UUID, datos: dict[str, Any]
) -> PerfilMarketing:
    """Crea o actualiza el perfil con lo que traiga el evento.

    Se **fusiona**, no se reemplaza: cada evento trae lo suyo —el de alta trae el
    correo, el de asignación trae el dueño— y reemplazar dejaría el perfil con
    solo lo del último, borrando lo que ya se sabía.
    """
    fila = db.execute(
        select(PerfilMarketing).where(
            PerfilMarketing.tenant_id == tenant_id,
            PerfilMarketing.objeto == objeto,
            PerfilMarketing.objeto_id == objeto_id,
        )
    ).scalar_one_or_none()
    if fila is None:
        fila = PerfilMarketing(
            tenant_id=tenant_id, objeto=objeto, objeto_id=objeto_id, alta_at=_ahora()
        )
        db.add(fila)

    for campo in COPIABLES:
        valor = datos.get(campo)
        if valor not in (None, ""):
            setattr(fila, campo, valor)

    if datos.get("cuenta_id"):
        fila.cuenta_id = UUID(str(datos["cuenta_id"]))
    if datos.get("asignado_a") or datos.get("owner_id"):
        fila.owner_id = UUID(str(datos.get("asignado_a") or datos["owner_id"]))
    if isinstance(datos.get("campos"), dict):
        # Los campos propios también se fusionan: un evento que solo trae el
        # campo que cambió no puede borrar los demás.
        fila.campos = {**(fila.campos or {}), **datos["campos"]}

    fila.ultima_actividad_at = _ahora()
    fila.sincronizado_at = _ahora()
    return fila


def marcar_baja(db: Session, *, tenant_id: UUID, objeto_id: UUID) -> int:
    """Marca de baja un perfil borrado en origen.

    Se marca y **no se borra**: un segmento congelado tiene que poder seguir
    explicando a quién incluía, y si la fila desapareciera la lista quedaría con
    identificadores que no resuelven a nada.
    """
    filas = list(
        db.execute(
            select(PerfilMarketing).where(
                PerfilMarketing.tenant_id == tenant_id,
                PerfilMarketing.objeto_id == objeto_id,
            )
        ).scalars()
    )
    for fila in filas:
        fila.baja = True
        fila.sincronizado_at = _ahora()
    return len(filas)


async def consumir(mensaje: Any) -> None:
    """Consume los eventos de negocio que alimentan el perfil."""
    tipo = getattr(mensaje, "tipo", None) or (
        mensaje.get("tipo") if isinstance(mensaje, dict) else None
    )
    if str(tipo or "") == "partner.activated":
        await _consumir_partner(mensaje)
        return
    if str(tipo or "") == "contact.processing_limited":
        await _consumir_limitacion(mensaje)
        return
    if str(tipo or "") == "contact.processing_lifted":
        await _consumir_levantamiento(mensaje)
        return
    encaje = EVENTOS.get(str(tipo or ""))
    if encaje is None:
        return

    bruto = getattr(mensaje, "tenant_id", None) or (
        mensaje.get("tenant_id") if isinstance(mensaje, dict) else None
    )
    if not bruto:
        logger.warning("marketing.evento_sin_tenant", tipo=tipo)
        return
    datos = (
        getattr(mensaje, "data", None)
        or (mensaje.get("data") if isinstance(mensaje, dict) else {})
        or {}
    )
    objeto, clave_id = encaje
    crudo = datos.get(clave_id)
    if not crudo:
        return

    from crmcore.db.uow import unidad_de_trabajo

    tenant_id = UUID(str(bruto))
    with unidad_de_trabajo(tenant_id) as uow:
        if tipo == "record.deleted":
            marcar_baja(uow.db, tenant_id=tenant_id, objeto_id=UUID(str(crudo)))
            return
        aplicar(
            uow.db,
            tenant_id=tenant_id,
            objeto=objeto,
            objeto_id=UUID(str(crudo)),
            datos=dict(datos),
        )


async def _consumir_partner(mensaje: Any) -> None:
    """Guarda el partner que llega por evento, para los fondos de canal.

    `marketing` no puede leer el esquema de `sales`, así que el nombre del
    partner llega por aquí. Si el evento no trae el identificador no se inventa
    nada: sin él no hay a quién apuntar el fondo.
    """
    bruto = getattr(mensaje, "tenant_id", None) or (
        mensaje.get("tenant_id") if isinstance(mensaje, dict) else None
    )
    datos = (
        getattr(mensaje, "data", None)
        or (mensaje.get("data") if isinstance(mensaje, dict) else {})
        or {}
    )
    partner_id = datos.get("partner_id")
    if not bruto or not partner_id:
        logger.warning("marketing.partner_sin_identificador", tenant=str(bruto))
        return

    from crmcore.db.uow import unidad_de_trabajo

    from services.marketing.fondos import registrar_partner

    tenant_id = UUID(str(bruto))
    with unidad_de_trabajo(tenant_id) as uow:
        registrar_partner(
            uow.db,
            tenant_id=tenant_id,
            partner_id=UUID(str(partner_id)),
            clave=str(datos.get("clave") or ""),
            canal=str(datos.get("canal") or ""),
        )


from crmcore.contratos import Consumo, declarar_consumo  # noqa: E402

# Contract testing dirigido por el consumidor (CRM-00.03.01.03). Los campos van
# como **opcionales** a propósito: no todos los eventos traen todos, y exigirlos
# rompería el preflight por algo que aquí se tolera —el atributo sale nulo y se
# dice—. Lo que sí queda declarado es que marketing los lee, para que quitarlos
# del productor sea una decisión y no un descuido.
for _evento, (_objeto, _clave) in EVENTOS.items():
    declarar_consumo(
        Consumo(
            consumidor="marketing",
            evento=_evento,
            campos=("campos",),
            obligatorio=False,
            motivo=(
                "Rellenar el perfil de marketing para poder segmentar sin leer el "
                "esquema del servicio dueño del dato"
            ),
        )
    )

declarar_consumo(
    Consumo(
        consumidor="marketing",
        evento="partner.activated",
        campos=("partner_id",),
        obligatorio=True,
        motivo=(
            "Poder abrir fondos de marketing a nombre de un partner sin leer el "
            "esquema de ventas"
        ),
    )
)


async def _consumir_limitacion(mensaje: Any) -> None:
    """Deja de escribir a quien ha ejercido su limitación u oposición
    (CRM-02.04.02.03, CRM-02.04.02.05).

    Es el otro extremo del derecho: `party` anota la limitación y **aquí** es
    donde se deja de enviar, porque quien manda los correos es este servicio y
    no puede leer aquel esquema.

    Se suprime **por dirección**, no por identificador, y todas las que traiga el
    evento. La misma persona suele estar en tres fichas duplicadas: bloquear solo
    la que ejerció el derecho deja que las otras dos le sigan escribiendo, que es
    la queja que acaba en denuncia.
    """
    from crmcore.db.uow import unidad_de_trabajo

    from services.marketing.segmentos import suprimir

    bruto = getattr(mensaje, "tenant_id", None) or (
        mensaje.get("tenant_id") if isinstance(mensaje, dict) else None
    )
    datos = (
        getattr(mensaje, "data", None)
        or (mensaje.get("data") if isinstance(mensaje, dict) else {})
        or {}
    )
    destinos = datos.get("destinos") or []
    if not bruto:
        logger.warning("marketing.limitacion_sin_tenant")
        return
    if not destinos:
        # Sin direcciones no hay nada que bloquear aquí, y **se dice**: una
        # limitación que no se puede aplicar no puede pasar en silencio, porque
        # el interesado cree que ya no le escriben.
        logger.warning("marketing.limitacion_sin_destinos", contacto=str(datos.get("contacto_id")))
        return

    contacto = datos.get("contacto_id")
    tenant_id = UUID(str(bruto))
    with unidad_de_trabajo(tenant_id) as uow:
        for destino in destinos:
            suprimir(
                uow,
                direccion=str(destino.get("destino") or ""),
                canal=str(destino.get("canal") or "email"),
                motivo="baja",
                detalle=(
                    "Limitación u oposición del interesado "
                    f"({datos.get('motivo') or 'sin motivo declarado'})"
                ),
                contacto_id=UUID(str(contacto)) if contacto else None,
            )
    logger.info("marketing.limitacion_aplicada", destinos=len(destinos))


async def _consumir_levantamiento(mensaje: Any) -> None:
    """Quita la supresión cuando se levanta la limitación.

    **No se quita a ciegas.** Una supresión puede venir de una queja por spam o
    de un rebote duro, y esas no las levanta el fin de una limitación: quitarlas
    haría que volver a escribir a quien nos denunció fuera un efecto colateral de
    otro trámite. Solo se retira la que puso la propia limitación.
    """
    from crmcore.db.uow import unidad_de_trabajo
    from sqlalchemy import select as _select

    from services.marketing.modelos import Supresion

    bruto = getattr(mensaje, "tenant_id", None) or (
        mensaje.get("tenant_id") if isinstance(mensaje, dict) else None
    )
    datos = (
        getattr(mensaje, "data", None)
        or (mensaje.get("data") if isinstance(mensaje, dict) else {})
        or {}
    )
    destinos = datos.get("destinos") or []
    if not bruto or not destinos:
        return

    tenant_id = UUID(str(bruto))
    with unidad_de_trabajo(tenant_id) as uow:
        for destino in destinos:
            fila = uow.db.execute(
                _select(Supresion).where(
                    Supresion.tenant_id == tenant_id,
                    Supresion.canal == str(destino.get("canal") or "email"),
                    Supresion.direccion == str(destino.get("destino") or "").strip().lower(),
                )
            ).scalar_one_or_none()
            if fila is None:
                continue
            if fila.permanente or fila.motivo in ("queja", "rebote_duro", "lista_negra"):
                logger.info(
                    "marketing.supresion_no_levantada",
                    motivo=fila.motivo,
                    porque="no la puso la limitación",
                )
                continue
            uow.db.delete(fila)
    logger.info("marketing.levantamiento_aplicado", destinos=len(destinos))


declarar_consumo(
    Consumo(
        consumidor="marketing",
        evento="contact.processing_limited",
        campos=("contacto_id", "destinos"),
        obligatorio=True,
        motivo=(
            "Dejar de escribir a quien ejerció su limitación u oposición. Sin las "
            "direcciones no se puede bloquear: aquí se suprime por dirección, "
            "porque la misma persona está a menudo en varias fichas"
        ),
    )
)

declarar_consumo(
    Consumo(
        consumidor="marketing",
        evento="contact.processing_lifted",
        campos=("contacto_id", "destinos"),
        obligatorio=True,
        motivo="Volver a permitir el envío solo de lo que bloqueó la limitación",
    )
)
