"""Comandos que este servicio atiende (CRM-00.03.03.03).

Una automatización no puede escribir en este esquema —los permisos de base de
datos lo impiden, y es lo que mantiene la propiedad exclusiva del dato—, así que
pide por el bus y aquí se ejecuta, con la lista blanca de campos que declara
`comandos.py`.
"""

from __future__ import annotations

from typing import Any

from crmcore.logging import get_logger

logger = get_logger(__name__)


async def consumir_comando(mensaje: Any) -> None:
    """Ejecuta un comando dirigido a un objeto de este servicio.

    Lo que no es para aquí se ignora sin ruido: todos los servicios escuchan el
    mismo bus, y tratar «no es mío» como un error llenaría la cola de fallidos
    con mensajes correctos.
    """
    from uuid import UUID

    from crmcore.bus.comandos import despachar
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto

    import services.sales.comandos  # noqa: F401 — registra los manejadores

    bruto = getattr(mensaje, "tenant_id", None) or (
        mensaje.get("tenant_id") if isinstance(mensaje, dict) else None
    )
    if not bruto:
        logger.warning("comando.sin_tenant", tipo=getattr(mensaje, "tipo", "?"))
        return
    tenant_id = UUID(str(bruto))

    with con_contexto(tenant_id=tenant_id, origen="bus"), unidad_de_trabajo(tenant_id) as uow:
        await despachar(uow.db, mensaje)


async def consumir_organigrama(mensaje: Any) -> None:
    """Mantiene la réplica de la jerarquía de mando (CRM-00.05.02.12).

    Cierra un hueco que el manual llevaba tiempo declarando: la compartición por
    jerarquía no aplicaba en los listados de este servicio, porque `superior_id`
    vive en la membresía de `identity` y aquí no se lee su esquema. Se replica lo
    mínimo —quién depende de quién— igual que se replican los ajustes en caliente
    y la clave del tenant.

    Un `superior_id` vacío **también se aplica**: alguien que deja de depender de
    nadie tiene que dejar de contarse como subordinado ese mismo día. Ignorar el
    vacío dejaría a su antiguo jefe viendo su cartera para siempre.
    """
    from uuid import UUID

    from crmcore.authz.jerarquia import aplicar_mando
    from crmcore.db.uow import unidad_de_trabajo

    tipo = getattr(mensaje, "tipo", None) or (
        mensaje.get("tipo") if isinstance(mensaje, dict) else None
    )
    if str(tipo or "") != "user.org.changed":
        return

    bruto = getattr(mensaje, "tenant_id", None) or (
        mensaje.get("tenant_id") if isinstance(mensaje, dict) else None
    )
    datos = (
        getattr(mensaje, "data", None)
        or (mensaje.get("data") if isinstance(mensaje, dict) else {})
        or {}
    )
    usuario = datos.get("user_id")
    if not bruto or not usuario:
        logger.warning("sales.organigrama_sin_identificador")
        return

    superior = str(datos.get("superior_id") or "")
    tenant_id = UUID(str(bruto))
    with unidad_de_trabajo(tenant_id) as uow:
        aplicar_mando(
            uow.db,
            tenant_id=tenant_id,
            usuario_id=UUID(str(usuario)),
            superior_id=UUID(superior) if superior else None,
        )


from crmcore.contratos import Consumo, declarar_consumo  # noqa: E402

declarar_consumo(
    Consumo(
        consumidor="sales",
        evento="user.org.changed",
        campos=("user_id", "superior_id"),
        obligatorio=True,
        motivo=(
            "Replicar la jerarquía de mando para que la compartición por jerarquía "
            "aplique también en los listados de este servicio, sin leer el esquema "
            "de identity"
        ),
    )
)


async def consumir_firma(mensaje: Any) -> None:
    """Mueve la oportunidad cuando su sobre cambia de estado (CRM-03.03.02.07).

    El motor de firma ya emitía estos eventos con el registro que los originó
    dentro; lo que faltaba era que este servicio los escuchara. Sin eso, el
    comercial firmaba el presupuesto y luego tenía que entrar a mover la
    oportunidad a mano — que es justo el trabajo que la integración existía para
    quitar, y el que se olvida.

    **Solo se mueve lo que el sobre demuestra.** Un sobre completado dice que
    está firmado, no que el negocio esté ganado: puede faltar el pedido, el pago
    o la aprobación interna. Se marca la firma y se deja la etapa a quien la
    gobierna; forzar «ganada» desde aquí se saltaría el motivo de cierre, la
    aprobación de descuento y el forecast.
    """
    from uuid import UUID

    from crmcore.db.uow import unidad_de_trabajo

    tipo = str(
        getattr(mensaje, "tipo", None)
        or (mensaje.get("tipo") if isinstance(mensaje, dict) else "")
        or ""
    )
    if not tipo.startswith("signature.envelope."):
        return

    bruto = getattr(mensaje, "tenant_id", None) or (
        mensaje.get("tenant_id") if isinstance(mensaje, dict) else None
    )
    datos = (
        getattr(mensaje, "data", None)
        or (mensaje.get("data") if isinstance(mensaje, dict) else {})
        or {}
    )
    objeto = str(datos.get("objeto_origen") or "")
    origen_id = datos.get("objeto_origen_id")
    if not bruto or objeto != "oportunidad" or not origen_id:
        # Un sobre que no sale de una oportunidad no es asunto de este servicio,
        # y no tenerlo no es un error: se firman contratos que nacen de un caso,
        # de un pedido o de nada.
        return

    from services.sales.modelos import Oportunidad

    tenant_id = UUID(str(bruto))
    with unidad_de_trabajo(tenant_id) as uow:
        oportunidad = uow.db.get(Oportunidad, UUID(str(origen_id)))
        if oportunidad is None:
            logger.warning("sales.firma_sobre_oportunidad_inexistente", oportunidad=str(origen_id))
            return

        campos = dict(oportunidad.campos or {})
        campos["firma_estado"] = tipo.rsplit(".", 1)[-1]
        campos["firma_sobre_id"] = str(datos.get("sobre_id") or "")
        campos["firma_referencia"] = str(datos.get("referencia") or "")
        if datos.get("motivo"):
            campos["firma_motivo"] = str(datos["motivo"])
        oportunidad.campos = campos
        uow.db.flush()
        logger.info(
            "sales.oportunidad_marcada_por_firma",
            oportunidad=str(origen_id),
            estado=campos["firma_estado"],
        )


declarar_consumo(
    Consumo(
        consumidor="sales",
        evento="signature.envelope.completed",
        campos=("sobre_id", "objeto_origen", "objeto_origen_id"),
        obligatorio=True,
        motivo=(
            "Marcar en la oportunidad que su presupuesto ya está firmado, sin que "
            "el comercial tenga que entrar a moverla a mano"
        ),
    )
)


async def consumir_territorio(mensaje: Any) -> None:
    """Replica el mapa de territorios cuando se publica (CRM-00.05.02.07).

    Es el otro medio circuito que estaba abierto. `visibilidad.py` de este
    servicio resuelve el acceso por territorio contra `TerritorioReplicado`, y
    **esa tabla no la escribía nadie**: `territory.published` lo emitía `sales` y
    no lo consumía ningún servicio. Resultado, la vía por territorio devolvía
    siempre el conjunto vacío — un comercial cuyo acceso venía de su territorio
    no veía nada por ahí, sin error y sin que la pantalla lo dijera.

    Se aplica el mapa **entero**: los que están y, por diferencia, los que ya no.
    Replicar solo las altas dejaría a quien deja un territorio viendo su cartera
    para siempre, que es la mitad que de verdad importa.
    """
    from uuid import UUID

    from crmcore.authz.jerarquia import TerritorioReplicado, aplicar_territorio, quitar_territorio
    from crmcore.db.uow import unidad_de_trabajo
    from sqlalchemy import select

    tipo = getattr(mensaje, "tipo", None) or (
        mensaje.get("tipo") if isinstance(mensaje, dict) else None
    )
    if str(tipo or "") != "territory.published":
        return

    bruto = getattr(mensaje, "tenant_id", None) or (
        mensaje.get("tenant_id") if isinstance(mensaje, dict) else None
    )
    datos = (
        getattr(mensaje, "data", None)
        or (mensaje.get("data") if isinstance(mensaje, dict) else {})
        or {}
    )
    territorio = str(datos.get("territorio_id") or "")
    if not bruto or not territorio:
        # Sin identificador no se puede replicar nada, y adivinar por la clave
        # mezclaría dos territorios que se llamen parecido.
        logger.warning("%s.territorio_sin_identificador", __name__.split(".")[1])
        return

    tenant_id = UUID(str(bruto))
    territorio_id = UUID(territorio)
    padre = str(datos.get("padre_id") or "")
    deben = {UUID(str(u)) for u in (datos.get("usuarios") or [])}

    with unidad_de_trabajo(tenant_id) as uow:
        estan = set(
            uow.db.execute(
                select(TerritorioReplicado.usuario_id).where(
                    TerritorioReplicado.tenant_id == tenant_id,
                    TerritorioReplicado.territorio_id == territorio_id,
                    TerritorioReplicado.usuario_id.is_not(None),
                )
            )
            .scalars()
            .all()
        )
        # El territorio en sí, con su padre: hace falta aunque no tenga a nadie,
        # porque de él cuelgan los de abajo.
        aplicar_territorio(
            uow.db,
            tenant_id=tenant_id,
            territorio_id=territorio_id,
            padre_id=UUID(padre) if padre else None,
            clave=str(datos.get("territorio") or ""),
        )
        for usuario in deben:
            aplicar_territorio(
                uow.db,
                tenant_id=tenant_id,
                territorio_id=territorio_id,
                padre_id=UUID(padre) if padre else None,
                usuario_id=usuario,
                clave=str(datos.get("territorio") or ""),
            )
        for usuario in estan - deben:
            quitar_territorio(
                uow.db, tenant_id=tenant_id, territorio_id=territorio_id, usuario_id=usuario
            )


declarar_consumo(
    Consumo(
        consumidor="sales",
        evento="territory.published",
        campos=("territorio_id", "padre_id", "usuarios"),
        obligatorio=True,
        motivo=(
            "Replicar el mapa de territorios para que el acceso por territorio "
            "aplique en los listados de este servicio, sin leer el esquema de sales"
        ),
    )
)
