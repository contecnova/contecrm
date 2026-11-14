"""Lo que enchufa la entrega de webhooks al bus.

**Esto no existía, y sin esto el servicio no entregaba nada.** `entrega.py`
tenía el reparto entero —casar la suscripción, firmar, mandar, registrar,
programar el reintento y desactivar el endpoint muerto—, con sus pruebas en
verde, y **no lo importaba nadie**: un `grep` de `services.eventing.entrega` en
todo el árbol daba una sola coincidencia, un fichero de pruebas. El servicio
declaraba sus rutas y ningún consumidor.

El efecto para el cliente era el peor posible: crea su suscripción, la ve en el
listado, mira su historial de entregas, lo ve vacío **y cree que todavía no ha
pasado nada**. No hay error que buscar, porque no hay error.

Y la descripción del propio servicio prometía «reintentos con backoff» y
«desactivación automática de endpoints muertos», que es exactamente el patrón
que nos ha mordido tres veces hoy: no un guardián apagado, sino un guardián que
nunca se encendió y que se contaba como encendido.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from crmcore.events.envelope import Evento
from crmcore.logging import get_logger

logger = get_logger(__name__)


def _evento_de(mensaje: Any) -> Evento | None:
    """El sobre, venga como venga.

    El relevo publica un `Evento`, pero el bus tiene tres implementaciones
    —memoria, Redis y NATS— y la de memoria entrega el objeto tal cual mientras
    las otras pasan por serializar. Aceptar las dos formas cuesta cuatro líneas
    y evita que esto funcione en las pruebas y no en producción, que es
    justamente como se llega a un servicio que no entrega nada.
    """
    if isinstance(mensaje, Evento):
        return mensaje
    if isinstance(mensaje, dict):
        try:
            return Evento.desde_dict(mensaje)
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("webhook.sobre_ilegible", error=str(exc)[:200])
            return None
    sobre = getattr(mensaje, "sobre", None)
    if isinstance(sobre, dict):
        return _evento_de(sobre)
    logger.warning("webhook.sobre_desconocido", clase=type(mensaje).__name__)
    return None


async def consumir_evento(mensaje: Any) -> None:
    """Entrega este evento a quien lo haya pedido.

    El patrón de suscripción al bus es ancho —`*`— y el filtro fino lo hace
    `suscripciones_interesadas`, que compara tipo y condiciones. Mantener aquí
    una lista de tipos al día con lo que los tenants tengan suscrito sería otra
    cosa más que se desincroniza sola.

    Un evento sin suscripciones no cuesta una consulta de más: se resuelve en la
    misma que ya se hace.
    """
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tenancy.context import con_contexto

    from services.eventing.entrega import entregar, es_publico, suscripciones_interesadas

    evento = _evento_de(mensaje)
    if evento is None:
        return
    if not evento.tenant_id:
        # Un evento de plataforma no es de nadie, y las suscripciones son de un
        # tenant. Entregarlo a todos sería mandarle a un cliente lo que pasa en
        # la casa de otro.
        return
    if not es_publico(evento.type):
        # Lo interno no sale: ni por webhook ni por el empuje al navegador. El
        # patrón del bus es `*`, así que aquí llega TODO, también el evento que
        # lleva el enlace para cambiar una contraseña (SEC-19).
        return

    tenant_id = UUID(str(evento.tenant_id))

    # EMPUJE A QUIEN NO TIENE DIRECCIÓN (CRM-00.02.02.10). Un webhook exige que
    # quien escucha tenga una dirección pública y estable, y eso deja fuera a
    # media integración real: un navegador, una aplicación móvil, un servicio
    # dentro de una red cerrada. Todos pueden llamar al CRM y ninguno puede
    # recibir una llamada.
    #
    # Se avisa al gateway, que es la única puerta pública y donde está el flujo.
    # Va **antes** del reparto por webhook y con un aviso que no rompe: si el
    # gateway no está declarado en la configuración o no contesta, lo que no
    # puede pasar es que se caiga la entrega que sí importa.
    from crmcore.http.interno import avisar

    avisar(
        "gateway",
        "/api/v1/interno/empuje",
        {
            "tenant_id": str(tenant_id),
            "tipo": evento.type,
            "id": str(evento.id),
            "datos": evento.data,
        },
    )

    with (
        con_contexto(tenant_id=tenant_id, origen="webhooks"),
        unidad_de_trabajo(tenant_id) as uow,
    ):
        # La copia que hace posibles el reintento y el replay. **No la escribía
        # nadie** (FUN-A-5): el replay devolvía siempre cero, y el reintento
        # buscaba el sobre en la tabla de salida del esquema de eventing, donde
        # no están los eventos que emiten los demás servicios (FUN-A-4), así que
        # ninguna entrega fallida se reintentaba de verdad. Se archiva aunque hoy
        # no haya suscripciones: el replay sirve justo para la que se crea o se
        # arregla después.
        from services.eventing.modelos import EventoArchivado

        uow.db.add(
            EventoArchivado(
                tenant_id=tenant_id,
                tipo=evento.type,
                dedup_key=evento.dedup_key,
                sobre=evento.a_dict(),
                occurred_at=evento.occurred_at,
            )
        )
        interesadas = suscripciones_interesadas(uow.db, evento)
        if not interesadas:
            return
        for suscripcion in interesadas:
            await entregar(uow.db, suscripcion, evento)

    logger.info(
        "webhook.evento_repartido",
        tipo=evento.type,
        suscripciones=len(interesadas),
    )


class RelevoDeReintentos:
    """Recoge las entregas fallidas cuyo momento de reintento ya ha llegado.

    Sin esto, el backoff es una fecha guardada en una fila que nadie vuelve a
    mirar: la primera entrega fallida de un endpoint que estuvo caído un minuto
    se perdía para siempre, aunque la columna dijera cuándo había que
    reintentarla.

    Va en el propio servicio y no en un cron del sistema operativo por lo mismo
    que el relevo del outbox: un despliegue no puede depender de que alguien se
    acuerde de programar una tarea, y lo que no arranca solo no arranca.
    """

    def __init__(self) -> None:
        self._parar = asyncio.Event()

    def parar(self) -> None:
        self._parar.set()

    async def correr(self) -> None:
        from crmcore.config import get_settings

        s = get_settings()
        intervalo = float(s.webhook_reintento_intervalo_s)
        logger.info("webhook.relevo_arranca", intervalo_s=intervalo)
        while not self._parar.is_set():
            try:
                await self._una_vuelta()
            except Exception as exc:  # noqa: BLE001 — el relevo no se muere nunca
                logger.error("webhook.relevo_vuelta_fallida", error=str(exc)[:300])
            try:
                await asyncio.wait_for(self._parar.wait(), timeout=intervalo)
            except TimeoutError:
                continue

    async def _una_vuelta(self) -> int:
        """Un lote de reintentos. Devuelve cuántos se intentaron."""
        from crmcore.db.session import sesion

        from services.eventing.entrega import pendientes_de_reintento

        self._purgar_archivo()
        with sesion(sistema=True) as db:
            pendientes = pendientes_de_reintento(db)
            if not pendientes:
                return 0
            # Se recogen los datos antes de salir a la red: reintentar es una
            # entrega nueva, con su propia fila, y hacerla dentro de la sesión de
            # sistema mezclaría tenants en una misma transacción.
            trabajo = [
                (e.tenant_id, e.suscripcion_id, e.evento_id, e.intento + 1, e.id)
                for e in pendientes
            ]
            # Se RESERVAN en esta misma transacción, antes de soltar el bloqueo.
            # El `FOR UPDATE SKIP LOCKED` solo duraba hasta el commit de esta
            # sesión: otra réplica podía coger la misma entrega mientras ésta la
            # reintentaba, y el endpoint la recibía dos veces (auditoría
            # 13-11-2026, FUN-A-10). Se empuja su próximo intento un plazo que
            # cubre el reintento: las demás la saltan, y si este proceso se cae
            # a mitad vuelve a aparecer al vencer, en vez de perderse.
            from datetime import datetime, timedelta, timezone

            from crmcore.config import get_settings

            # Dos veces lo que puede tardar el endpoint, más una vuelta del relevo.
            s = get_settings()
            reserva = timedelta(
                seconds=2 * float(s.webhook_timeout_s) + float(s.webhook_reintento_intervalo_s)
            )
            hasta = datetime.now(timezone.utc) + reserva
            for e in pendientes:
                e.proximo_intento_at = hasta

        hechos = 0
        for tenant_id, suscripcion_id, evento_id, intento, entrega_id in trabajo:
            if await self._reintentar_una(
                tenant_id, suscripcion_id, evento_id, intento, entrega_id
            ):
                hechos += 1
        if hechos:
            logger.info("webhook.reintentos", cuantos=hechos)
        return hechos

    def _purgar_archivo(self) -> int:
        """Borra del archivo lo que ya pasó de `EVENTOS_ARCHIVO_RETENCION_DIAS`.

        Sin purga, archivar cada evento público haría crecer la tabla para
        siempre. Va en la vuelta del relevo, que ya corre sola en el servicio.
        """
        from datetime import datetime, timedelta, timezone

        from crmcore.config import get_settings
        from crmcore.db.session import sesion
        from sqlalchemy import delete

        from services.eventing.modelos import EventoArchivado

        # Una vez al día basta: la retención se mide en días, y borrar en cada
        # vuelta del relevo (cada pocos segundos) recorrería la tabla sin motivo.
        hoy = datetime.now(timezone.utc).date()
        if getattr(self, "_purgado_el", None) == hoy:
            return 0
        self._purgado_el = hoy

        dias = int(get_settings().eventos_archivo_retencion_dias)
        limite = datetime.now(timezone.utc) - timedelta(days=dias)
        with sesion(sistema=True) as db:
            borrados = db.execute(
                delete(EventoArchivado).where(EventoArchivado.created_at < limite)
            ).rowcount
        if borrados:
            logger.info("webhook.archivo_purgado", borrados=borrados, dias=dias)
        return int(borrados or 0)

    async def _reintentar_una(
        self,
        tenant_id: UUID,
        suscripcion_id: UUID,
        evento_id: UUID,
        intento: int,
        entrega_id: UUID,
    ) -> bool:
        from crmcore.db.uow import unidad_de_trabajo
        from crmcore.tenancy.context import con_contexto
        from sqlalchemy import select

        from services.eventing.entrega import entregar
        from services.eventing.modelos import Entrega, EventoArchivado, Suscripcion

        with (
            con_contexto(tenant_id=tenant_id, origen="webhooks"),
            unidad_de_trabajo(tenant_id) as uow,
        ):
            suscripcion = uow.db.get(Suscripcion, suscripcion_id)
            if suscripcion is None or not suscripcion.activa:
                # La suscripción se ha borrado o se ha desactivado mientras la
                # entrega esperaba: no se reintenta y se cierra la fila, que si
                # no queda pendiente para siempre.
                fila = uow.db.get(Entrega, entrega_id)
                if fila is not None:
                    fila.proximo_intento_at = None
                return False

            # El sobre se lee del ARCHIVO de este servicio. Antes se buscaba en
            # `EventoSaliente`, que es la tabla de salida del esquema de
            # eventing: los eventos de `party`, `sales`… están en la de su
            # servicio, así que nunca aparecían y el reintento se cerraba con
            # «no se conserva el sobre» (FUN-A-4). El identificador del evento
            # vive dentro del sobre.
            sobre = (
                uow.db.execute(
                    select(EventoArchivado).where(
                        EventoArchivado.tenant_id == tenant_id,
                        EventoArchivado.sobre["id"].astext == str(evento_id),
                    )
                )
                .scalars()
                .first()
            )
            if sobre is None:
                # Sin el sobre no se puede reconstruir lo que se mandó, y mandar
                # otra cosa sería peor que no mandar nada.
                fila = uow.db.get(Entrega, entrega_id)
                if fila is not None:
                    fila.proximo_intento_at = None
                    fila.error = "no se conserva el sobre del evento para reintentarlo"
                logger.warning("webhook.reintento_sin_sobre", evento=str(evento_id))
                return False

            evento = Evento.desde_dict(sobre.sobre)
            # La fila vieja deja de estar pendiente: el nuevo intento tiene la
            # suya, y si no, este lote se repetiría en cada vuelta.
            vieja = uow.db.get(Entrega, entrega_id)
            if vieja is not None:
                vieja.proximo_intento_at = None
            await entregar(uow.db, suscripcion, evento, intento=intento)
        return True
