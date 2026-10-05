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

    import services.party.comandos  # noqa: F401 — registra los manejadores

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
        logger.warning("party.organigrama_sin_identificador")
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
        consumidor="party",
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


async def consumir_salud(mensaje: Any) -> None:
    """Replica la salud de la cuenta para poder enseñarla en la ficha
    (CRM-01.01.05.07).

    Se calcula en `intelligence`, que es donde están las señales, y este servicio
    no lee su esquema. Un número que solo existe allí no lo ve quien tiene al
    cliente delante, con lo cual no cambia ninguna conversación — que era todo el
    objetivo.
    """
    from uuid import UUID

    from crmcore.db.uow import unidad_de_trabajo

    from services.party.salud_replicada import proyectar

    tipo = getattr(mensaje, "tipo", None) or (
        mensaje.get("tipo") if isinstance(mensaje, dict) else None
    )
    if str(tipo or "") != "account.health.scored":
        return

    bruto = getattr(mensaje, "tenant_id", None) or (
        mensaje.get("tenant_id") if isinstance(mensaje, dict) else None
    )
    datos = (
        getattr(mensaje, "data", None)
        or (mensaje.get("data") if isinstance(mensaje, dict) else {})
        or {}
    )
    if not bruto or not datos.get("cuenta_id"):
        logger.warning("party.salud_sin_identificador")
        return

    tenant_id = UUID(str(bruto))
    with unidad_de_trabajo(tenant_id) as uow:
        proyectar(uow.db, tenant_id=tenant_id, datos=dict(datos))


# Contract testing dirigido por el consumidor (CRM-00.03.01.03): queda declarado
# que `party` lee estos campos, para que quitarlos del productor sea una decisión
# y no un descuido. `fiable` va en la lista a propósito — sin él aquí se pintaría
# un número en rojo calculado con la mitad de las señales sin saberlo.
from crmcore.contratos import Consumo, declarar_consumo  # noqa: E402

declarar_consumo(
    Consumo(
        consumidor="party",
        evento="account.health.scored",
        campos=("cuenta_id", "puntuacion", "nivel", "fiable", "medida_at"),
        motivo=(
            "Enseñar la salud en la ficha de la cuenta sin leer el esquema de "
            "intelligence, y poder decir cuándo se midió y si es fiable"
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
        consumidor="party",
        evento="territory.published",
        campos=("territorio_id", "padre_id", "usuarios"),
        obligatorio=True,
        motivo=(
            "Replicar el mapa de territorios para que el acceso por territorio "
            "aplique en los listados de este servicio, sin leer el esquema de sales"
        ),
    )
)
