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


# ── Resincronización con el origen ────────────────────────────────────────
#
# Medido el 10-11-2026 en el tenant de operación: 44 perfiles de cuenta de 66
# cuentas vivas, 9 de 202 contactos y 15 de 436 leads, y NINGUNO con estado,
# empleados, sector o cargo — los eventos de alta sólo traen el nombre y no hay
# evento de modificación. Todos los segmentos daban cero. La proyección por
# evento sigue siendo la vía normal; ésta es la que la pone al día de una vez,
# preguntando a quien tiene el dato por su API pública y con la identidad de
# quien lo pide.

# Qué ruta trae cada objeto y cómo se lee cada campo del perfil en su fila. Es
# la API pública de cada servicio, la misma que ve un integrador: si un campo
# cambia de nombre, se cambia aquí y en ningún otro sitio.
ORIGENES: dict[str, dict[str, Any]] = {
    "cuenta": {
        "ruta": "/api/v1/accounts",
        "campos": {
            "nombre": ("nombre",),
            "email": ("email",),
            "telefono": ("telefono",),
            "estado": ("estado",),
            "sector": ("sector_codigo",),
            "empleados": ("empleados",),
            "facturacion": ("facturacion_anual",),
        },
    },
    "contacto": {
        "ruta": "/api/v1/contacts",
        "campos": {
            "nombre": ("nombre_completo", "nombre"),
            "email": ("email",),
            "telefono": ("movil", "telefono"),
            "cargo": ("cargo",),
        },
    },
    "lead": {
        "ruta": "/api/v1/leads",
        "campos": {
            "nombre": ("empresa", "nombre"),
            "email": ("email",),
            "telefono": ("telefono",),
            "pais": ("pais",),
            "cargo": ("cargo",),
            "origen": ("origen",),
            "estado": ("estado",),
        },
    },
}


def _fecha(valor: Any) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor))
    except ValueError:
        return None


def _leer_origen(
    objeto: str, tenant_id: UUID, principal: Any
) -> tuple[list[dict[str, Any]], set[str]] | None:
    """Todas las filas de un objeto, por su API, y qué campos NO vinieron en claro.

    `None` si no se pudo leer entera. Entera o nada: con media lista no se puede
    decidir quién se ha dado de baja, y marcar de baja a quien simplemente no
    llegó vaciaría los segmentos.

    Se llama como máquina —sin el filtro de compartición, que es de personas—
    pero con los permisos de quien lo pide: un segmento cuenta sobre el tenant
    entero, y lo que esa persona no puede ver en claro llega tapado y se dice.
    """
    from crmcore.config import get_settings
    from crmcore.errors import NoDisponible
    from crmcore.http.interno import invocar

    origen = ORIGENES[objeto]
    pagina_de = get_settings().marketing_resincronizar_pagina
    filas: list[dict[str, Any]] = []
    sin_claro: set[str] = set()
    cursor = ""
    vistos: set[str] = set()
    while True:
        try:
            r = invocar(
                metodo="GET",
                ruta=origen["ruta"],
                parametros={"limite": pagina_de, **({"cursor": cursor} if cursor else {})},
                tenant_id=tenant_id,
                principal_id=principal.id,
                permisos=sorted(getattr(principal, "permisos", None) or []),
                roles=sorted(getattr(principal, "roles", None) or []),
            )
        except NoDisponible:
            return None
        if not r.get("ok"):
            return None
        sin_claro |= set(r.get("campos_tapados") or []) | set(r.get("campos_no_entregados") or [])
        datos = r.get("datos") or {}
        pagina = datos.get("items") if isinstance(datos, dict) else datos
        filas.extend(f for f in (pagina or []) if isinstance(f, dict))
        cursor = str(datos.get("siguiente") or "") if isinstance(datos, dict) else ""
        # Un cursor repetido es un bucle, no una página nueva: se corta y se da
        # la lectura por incompleta.
        if not cursor:
            return filas, sin_claro
        if cursor in vistos:
            return None
        vistos.add(cursor)


def resincronizar(tenant_id: UUID, principal: Any) -> dict[str, Any]:
    """Pone el perfil de marketing al día con el origen, objeto a objeto.

    Lo que el origen dice manda, también cuando dice «vacío»: un cargo borrado
    en la ficha tiene que dejar de casar con «perfiles técnicos». La última
    actividad y el alta se copian del origen si los trae, y no se ponen a
    «ahora»: un volcado no es actividad, y marcarla así metería a todo el mundo
    en «activos en los últimos 30 días».

    **Un campo tapado no se copia.** Medido el 10-11-2026 en la primera vuelta:
    el sector llegó como «····» y el cargo como «·····e IT», y se guardaron.
    Un valor enmascarado tiene la forma de un dato y un segmento por cargo no
    casaba con nadie. Lo que no llega en claro deja el perfil como estaba.
    """
    from crmcore.db.uow import unidad_de_trabajo

    resultado: dict[str, Any] = {}
    for objeto, origen in ORIGENES.items():
        leido = _leer_origen(objeto, tenant_id, principal)
        if leido is None:
            resultado[objeto] = {"leido": False}
            continue
        filas, sin_claro = leido
        ahora = _ahora()
        with unidad_de_trabajo(tenant_id) as uow:
            existentes = {
                p.objeto_id: p
                for p in uow.db.execute(
                    select(PerfilMarketing).where(
                        PerfilMarketing.tenant_id == tenant_id,
                        PerfilMarketing.objeto == objeto,
                    )
                ).scalars()
            }
            altas = 0
            vivos: set[UUID] = set()
            for f in filas:
                try:
                    objeto_id = UUID(str(f.get("id")))
                except ValueError:
                    continue
                vivos.add(objeto_id)
                perfil = existentes.get(objeto_id)
                if perfil is None:
                    perfil = PerfilMarketing(
                        tenant_id=tenant_id, objeto=objeto, objeto_id=objeto_id
                    )
                    uow.db.add(perfil)
                    altas += 1
                for campo, fuentes in origen["campos"].items():
                    if sin_claro & set(fuentes):
                        continue
                    valor = next((f.get(c) for c in fuentes if f.get(c) not in (None, "")), None)
                    if campo == "nombre" and objeto == "lead" and not valor:
                        valor = (
                            " ".join(str(f.get(c)) for c in ("nombre", "apellidos") if f.get(c))
                            or None
                        )
                    setattr(perfil, campo, valor)
                if f.get("cuenta_id"):
                    perfil.cuenta_id = UUID(str(f["cuenta_id"]))
                if f.get("owner_id"):
                    perfil.owner_id = UUID(str(f["owner_id"]))
                if isinstance(f.get("campos"), dict):
                    perfil.campos = dict(f["campos"])
                perfil.alta_at = _fecha(f.get("created_at")) or perfil.alta_at
                actividad = _fecha(f.get("ultima_actividad_at"))
                if actividad is not None:
                    perfil.ultima_actividad_at = actividad
                perfil.baja = False
                perfil.sincronizado_at = ahora
            bajas = 0
            for objeto_id, perfil in existentes.items():
                if objeto_id not in vivos and not perfil.baja:
                    perfil.baja = True
                    perfil.sincronizado_at = ahora
                    bajas += 1
        resultado[objeto] = {
            "leido": True,
            "en_origen": len(vivos),
            "altas": altas,
            "bajas": bajas,
            "sin_claro": sorted(sin_claro),
        }
    logger.info("marketing.perfiles_resincronizados", resultado=resultado)
    return resultado


def estado_de_perfiles(db: Session, tenant_id: UUID) -> list[dict[str, Any]]:
    """Cuántos perfiles hay por objeto y de cuándo es el más viejo y el último."""
    from sqlalchemy import func

    filas = db.execute(
        select(
            PerfilMarketing.objeto,
            func.count(),
            func.min(PerfilMarketing.sincronizado_at),
            func.max(PerfilMarketing.sincronizado_at),
        )
        .where(PerfilMarketing.tenant_id == tenant_id, PerfilMarketing.baja.is_(False))
        .group_by(PerfilMarketing.objeto)
    ).all()
    por_objeto = {o: (n, viejo, ultimo) for o, n, viejo, ultimo in filas}
    return [
        {
            "objeto": objeto,
            "perfiles": por_objeto.get(objeto, (0, None, None))[0],
            "mas_antiguo_at": (
                v.isoformat() if (v := por_objeto.get(objeto, (0, None, None))[1]) else None
            ),
            "ultimo_at": (
                u.isoformat() if (u := por_objeto.get(objeto, (0, None, None))[2]) else None
            ),
        }
        for objeto in ORIGENES
    ]


def _entrar_en_recorridos(mensaje: Any, tipo: str) -> None:
    """Los recorridos que entran por este evento (CRM-02.02.02.02).

    El consumidor ya escucha todos los eventos para el perfil; aquí se mira si
    algún recorrido publicado espera éste. Un fallo no tumba el perfil: se
    registra y sigue.
    """
    bruto = getattr(mensaje, "tenant_id", None) or (
        mensaje.get("tenant_id") if isinstance(mensaje, dict) else None
    )
    if not bruto or not tipo:
        return
    datos = (
        getattr(mensaje, "data", None)
        or (mensaje.get("data") if isinstance(mensaje, dict) else {})
        or {}
    )
    from crmcore.db.uow import unidad_de_trabajo

    from services.marketing.recorridos import entrar_por_evento

    try:
        with unidad_de_trabajo(UUID(str(bruto))) as uow:
            entradas = entrar_por_evento(uow, tipo, dict(datos))
        if entradas:
            logger.info("marketing.recorrido_por_evento", tipo=tipo, entradas=entradas)
    except Exception as exc:  # noqa: BLE001 — el perfil va primero
        logger.warning("marketing.recorrido_por_evento_fallo", tipo=tipo, error=str(exc)[:200])


async def consumir(mensaje: Any) -> None:
    """Consume los eventos de negocio: el perfil primero y luego los recorridos.

    En ese orden: un lead que entra en un recorrido por `lead.created` tiene que
    estar ya en el perfil, o `entrar` no le encuentra el correo y lo deja fuera.
    """
    await _consumir_perfil(mensaje)
    tipo = getattr(mensaje, "tipo", None) or (
        mensaje.get("tipo") if isinstance(mensaje, dict) else None
    )
    # Los que alimentan el perfil entran en su misma unidad de trabajo (ver
    # `_consumir_perfil`); el resto, aquí.
    if str(tipo or "") not in EVENTOS:
        _entrar_en_recorridos(mensaje, str(tipo or ""))


async def _consumir_perfil(mensaje: Any) -> None:
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
        uow.db.flush()
        # En la MISMA unidad de trabajo que el perfil. En otra, el perfil recién
        # escrito aún no se veía y `entrar` lo dejaba fuera por «sin dirección»
        # (medido el 10-11-2026 dando de alta un contacto en pantalla).
        from services.marketing.recorridos import entrar_por_evento

        entradas = entrar_por_evento(uow, str(tipo), dict(datos))
        if entradas:
            logger.info("marketing.recorrido_por_evento", tipo=tipo, entradas=entradas)


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
