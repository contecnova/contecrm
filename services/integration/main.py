"""Punto de entrada del servicio de integración."""

from __future__ import annotations

from typing import Any

from crmcore.service import crear_servicio

from services.integration.api import ROUTERS
from services.integration.api_buzon import ROUTERS_BUZON
from services.integration.api_conectividad import ROUTERS_CONECTIVIDAD
from services.integration.api_encargos import ROUTERS_ENCARGOS
from services.integration.api_firma import ROUTERS_FIRMA
from services.integration.api_suites import ROUTERS_SUITES
from services.integration.api_telemetria import ROUTERS_TELEMETRIA
from services.integration.pedidos_erp import consumir_pedido
from services.integration.proyeccion import consumir as consumir_modulo

_relevo: Any = None
_tarea_relevo: Any = None


def _tareas() -> list[Any]:
    """Lo que este servicio hace solo, cada tanto.

    Es **el** agujero de integración: el conector declarativo estaba completo y
    lo disparaba una ruta a mano, así que integrar exigía que alguien pulsara un
    botón cada día. Y como nada corría en bucle, las decisiones que gobiernan
    una sincronización —cuándo avanza la marca, cómo se reintenta cuando el
    proveedor corta, a qué ritmo se trae la primera carga— estaban escritas,
    probadas y sin que las llamara nadie.

    Las funciones se importan **aquí y no dentro del cuerpo**: si alguien
    renombra una, el arranque revienta —que es cuando hay alguien mirando— en
    vez de fallar en la primera vuelta y tardar tres en marcarse averiada.
    """
    from crmcore.config import get_settings
    from crmcore.db.session import sesion
    from crmcore.db.uow import unidad_de_trabajo
    from crmcore.tareas import Tarea, por_tenant

    from services.integration.firma import Sobre, caducar_vencidos
    from services.integration.programador import (
        purgar_registros,
        tenants_con_programacion,
        una_vuelta,
    )
    from services.integration.suites import mantener_suscripciones, tenants_con_suscripciones

    s = get_settings()

    def _purgar() -> dict[str, Any]:
        with sesion(sistema=True) as db:
            return {
                "borrados": purgar_registros(db, dias=int(s.integracion_registros_retencion_dias))
            }

    def _tenants_con_sobres() -> list[Any]:
        from sqlalchemy import select

        with sesion(sistema=True) as db:
            return [t for (t,) in db.execute(select(Sobre.tenant_id).distinct()).all()]

    def _caducar(tenant_id: Any) -> dict[str, Any]:
        with unidad_de_trabajo(tenant_id, sistema=True) as uow:
            return dict(caducar_vencidos(uow, tenant_id))

    def _mantener(tenant_id: Any) -> dict[str, Any]:
        with unidad_de_trabajo(tenant_id, sistema=True) as uow:
            salida = mantener_suscripciones(uow)
        return {"caidas": len(salida["caidas_a_sondeo"])}

    return [
        Tarea(
            "integration.programador",
            int(s.tarea_integraciones_intervalo_s),
            por_tenant(tenants_con_programacion, una_vuelta),
            # No al arrancar: catorce procesos levantándose a la vez dispararían
            # catorce rondas simultáneas contra los mismos proveedores, que es
            # justo lo que hace que corten la cuota.
            al_arrancar=False,
        ),
        Tarea(
            "integration.registros_recibidos",
            int(s.tarea_purgas_intervalo_s),
            _purgar,
            al_arrancar=False,
        ),
        # Las suscripciones a los cambios del proveedor caducan, y **caducar no
        # da ningún error**: deja de llegar lo que llegaba. `caer_a_sondeo`
        # estaba escrita, probada y sin llamante, así que el sistema sabía decir
        # cuáles se iban a morir, lo enseñaba en una pantalla y no hacía nada.
        # Un sobre de firma vencido **no da ningún error**: se queda en el panel
        # como negocio vivo esperando una firma que ya no va a llegar, y con él
        # se queda la previsión. `caducar_vencidos` tenía ruta y sólo corría si
        # alguien pulsaba un botón, que es como no correr.
        Tarea(
            "integration.sobres_vencidos",
            int(s.tarea_purgas_intervalo_s),
            por_tenant(_tenants_con_sobres, _caducar),
            al_arrancar=False,
        ),
        Tarea(
            "integration.suscripciones_suite",
            int(s.tarea_integraciones_intervalo_s),
            por_tenant(tenants_con_suscripciones, _mantener),
            al_arrancar=False,
        ),
    ]


def _operador_de_firma(
    *, conexion_id: Any, operacion: str, parametros: dict[str, Any]
) -> dict[str, Any]:
    """Quien habla de verdad con un proveedor de firma.

    `firma.registrar_operador` existía, estaba probada y **no la llamaba nadie**:
    se podía declarar un proveedor de firma con su conexión y cualquier intento
    de mandar un sobre contestaba «este despliegue no tiene conectado el operador
    de firma». Es decir, la firma electrónica estaba completa salvo por el paso
    de salir.

    No hay código por proveedor, y es el punto: se resuelve con el **mismo
    conector declarativo** que lee un ERP, porque un proveedor de firma es una
    API más —endpoints, credencial y mapeo de campos—. Un módulo por casa
    convierte cada implantación nueva en una versión del producto.

    La operación se busca por su clave en la conexión. Si no está declarada se
    dice **cuál falta**: «no se ha podido crear el sobre» manda a mirar al
    proveedor, donde está todo bien.
    """
    import asyncio

    from crmcore.db.session import sesion
    from crmcore.errors import ErrorDependencia
    from sqlalchemy import select

    from services.integration import conector
    from services.integration.api import _secretos
    from services.integration.modelos import Conexion, Operacion

    with sesion(sistema=True) as db:
        conexion = db.get(Conexion, conexion_id)
        if conexion is None or not conexion.activa:
            raise ErrorDependencia(
                "La conexión del proveedor de firma no existe o está desactivada",
                error_code="firma.conexion_no_disponible",
            )
        fila = db.execute(
            select(Operacion).where(
                Operacion.conexion_id == conexion.id,
                Operacion.clave == operacion,
                Operacion.activa.is_(True),
            )
        ).scalar_one_or_none()
        if fila is None:
            raise ErrorDependencia(
                f"La conexión de firma no declara la operación «{operacion}». "
                "Declararla es configuración, no código.",
                error_code="firma.operacion_no_declarada",
                detalle={"operacion": operacion},
            )
        definicion = dict(fila.definicion or {})
        config = dict(conexion.config or {})
        secretos = _secretos(db, conexion.id)
        tenant = str(conexion.tenant_id)

    # Fuera de la sesión: la llamada sale a la red y puede tardar, y mantener
    # abierta una transacción mientras se espera a un tercero es cómo se agota
    # el pool con una integración lenta.
    return asyncio.run(
        conector.ejecutar(config, definicion, parametros, secretos=secretos, tenant_id=tenant)
    )


async def _al_arrancar() -> None:
    global _relevo, _tarea_relevo
    import asyncio

    from crmcore.tareas import RelevoDeTareas

    # Se registra al arrancar y no en tiempo de importación: en las pruebas, un
    # registro de importación deja el operador vivo entre casos.
    from services.integration.firma import registrar_operador

    registrar_operador(_operador_de_firma)

    _relevo = RelevoDeTareas(_tareas())
    _tarea_relevo = asyncio.create_task(_relevo.correr(), name="integration-tareas")


async def _al_parar() -> None:
    if _relevo is not None:
        _relevo.parar()
    if _tarea_relevo is not None:
        _tarea_relevo.cancel()


app = crear_servicio(
    nombre="integration",
    descripcion=(
        "Conector HTTP/REST declarativo: integrar un sistema externo es "
        "configuración, no código. Credenciales cifradas con rotación, prueba "
        "de conectividad, paginación declarativa y monitor de ejecuciones. "
        "Encima, el seguimiento de lo que se le encarga a un tercero: estados "
        "traducidos por conector, ingesta idempotente, incidencias, "
        "conciliación de facturas y detección del encargo del que nadie dice "
        "nada. Y la firma electrónica: sobres con varios firmantes y orden, "
        "proveedor elegido por regla, niveles eIDAS que deciden la "
        "identificación, y la cadena de custodia guardada aquí y no solo en el "
        "proveedor."
    ),
    routers=[
        *ROUTERS,
        *ROUTERS_ENCARGOS,
        *ROUTERS_FIRMA,
        *ROUTERS_TELEMETRIA,
        *ROUTERS_CONECTIVIDAD,
        *ROUTERS_BUZON,
        *ROUTERS_SUITES,
    ],
    # Los conectores que declara un módulo vertical se convierten aquí en
    # proveedores. Llegan por evento porque este servicio no puede leer el
    # esquema de `metadata`, y si no llegaran habría que teclearlos otra vez en
    # esta pantalla: justo el trabajo manual que el módulo existe para quitar.
    consumidores=[
        ("module.*", consumir_modulo, "integration-modulos"),
        # El pedido que ventas acepta y manda al ERP. `sales.enviar_a_erp` decía
        # en su propio comentario que «la llamada la hace integration con su
        # conector declarativo» y **nadie consumía el evento**: el pedido se
        # marcaba como enviado y no salía de aquí. Se descubre en el cierre de
        # mes, que es cuando ya no se puede arreglar.
        ("order.submitted", consumir_pedido, "integration-pedidos"),
    ],
    al_arrancar=_al_arrancar,
    al_parar=_al_parar,
)
