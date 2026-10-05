"""El pedido que sale hacia el ERP, y llega (CRM-03.03.02.11).

Medido el 05-10-2026. `sales.enviar_a_erp` dejaba el pedido en «enviado_erp» y
emitía `order.submitted` diciendo en su propio comentario que «la llamada la
hace integration con su conector declarativo». **Nadie consumía ese evento**: el
pedido se marcaba como enviado y no salía de aquí.

El síntoma es el que el propio módulo de ventas describe para otro caso y que
aquí se cumplía entero: se descubre en el cierre de mes que faltan pedidos.

Las decisiones:

**La operación se declara, no se adivina.** Qué conexión y qué operación
atienden un pedido lo dice un ajuste (`INTEGRACION_OPERACION_PEDIDOS`), porque
la clave la pone quien declara la conexión: en un cliente será `pedido.crear` y
en otro `sales_order`. Un nombre fijo en el código obligaría a todos a llamarla
igual, que es pedirle al cliente que se adapte a nuestro vocabulario.

**Un tenant sin ERP declarado no es un error.** La mayoría de los despliegues no
tienen ninguno: se anota y se sigue, en vez de llenar el registro de fallos por
una integración que nadie ha pedido.

**Y el resultado vuelve.** Lo que el ERP conteste —su referencia o su rechazo—
se devuelve a ventas por el bus, porque el estado del pedido es de ventas y
`integration` no escribe en su esquema.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from crmcore.errors import CrmError
from crmcore.logging import get_logger
from sqlalchemy import select

logger = get_logger(__name__)


async def consumir_pedido(mensaje: Any) -> None:
    """Manda al ERP un pedido que ventas acaba de aceptar.

    Va por el conector declarativo, el mismo que lee un maestro de clientes: un
    ERP es una API más —endpoints, credencial y mapeo de campos— y un módulo por
    producto convierte cada implantación en una versión del producto.
    """
    import time

    from crmcore.config import get_settings
    from crmcore.db.uow import unidad_de_trabajo

    from services.integration import conector
    from services.integration.modelos import Conexion, Ejecucion, Operacion

    datos = dict(getattr(mensaje, "data", None) or (mensaje or {}).get("data") or {})
    tenant = str(getattr(mensaje, "tenant_id", "") or (mensaje or {}).get("tenant_id") or "")
    pedido_id = str(datos.get("pedido_id") or "")
    if not tenant or not pedido_id:
        return

    clave = str(get_settings().integracion_operacion_pedidos)
    with unidad_de_trabajo(UUID(tenant), sistema=True) as uow:
        operacion = uow.db.execute(
            select(Operacion).where(Operacion.clave == clave, Operacion.activa.is_(True))
        ).scalar_one_or_none()
        if operacion is None:
            # Sin ERP declarado no pasa nada: la mayoría de los despliegues no
            # tienen ninguno. Se anota a nivel de información, no de error.
            logger.info("pedido_erp.sin_operacion_declarada", pedido=pedido_id, operacion=clave)
            return
        conexion = uow.db.get(Conexion, operacion.conexion_id)
        if conexion is None or not conexion.activa:
            logger.warning("pedido_erp.conexion_inactiva", pedido=pedido_id)
            return

        from services.integration.api import _secretos

        config = dict(conexion.config or {})
        definicion = dict(operacion.definicion or {})
        secretos = _secretos(uow.db, conexion.id)
        inicio = time.perf_counter()
        traza = Ejecucion(
            tenant_id=uow.tenant_id,
            conexion_id=conexion.id,
            operacion=operacion.clave,
            resultado="ok",
            parametros={"pedido_id": pedido_id, "numero": datos.get("numero")},
        )
        try:
            salida = await conector.ejecutar(
                config, definicion, datos, secretos=secretos, tenant_id=tenant
            )
        except CrmError as exc:
            traza.resultado = "error"
            traza.error = f"{exc.error_code}: {exc.mensaje}"[:2000]
            traza.duracion_ms = int((time.perf_counter() - inicio) * 1000)
            uow.db.add(traza)
            # El rechazo vuelve a VENTAS, que es de quien es el estado del
            # pedido. Dejarlo aquí sería un pedido que figura enviado en ventas
            # y rechazado en una traza que nadie mira.
            uow.emitir(
                "order.erp.rejected",
                subject=("pedido", UUID(pedido_id)),
                data={"pedido_id": pedido_id, "error": traza.error},
                dedup_key=f"erp-rechazo:{pedido_id}",
            )
            return

        traza.registros = len(salida.get("registros") or [])
        traza.duracion_ms = int((time.perf_counter() - inicio) * 1000)
        uow.db.add(traza)
        primera = (salida.get("registros") or [{}])[0]
        uow.emitir(
            "order.erp.confirmed",
            subject=("pedido", UUID(pedido_id)),
            data={
                "pedido_id": pedido_id,
                # La referencia con la que el cliente reclamará por teléfono. Si
                # el ERP no la devuelve se dice vacía y no se inventa: una
                # referencia inventada es peor que ninguna.
                "referencia_erp": str(primera.get("referencia") or primera.get("id") or ""),
            },
            dedup_key=f"erp-confirmacion:{pedido_id}",
        )
