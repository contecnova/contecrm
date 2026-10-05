"""Un pedido que figura «enviado al ERP» y no salió de aquí (`CRM-03.03.02.11`).

Auditado el 05-10-2026. `sales.enviar_a_erp` marcaba el pedido como enviado y
emitía `order.submitted` diciendo en su propio comentario que «la llamada la
hace integration con su conector declarativo». **Nadie consumía ese evento.**

El síntoma es el que el propio módulo de ventas describe y que aquí se cumplía
entero: no hay error, el pedido figura enviado, y se descubre en el cierre de
mes que faltan pedidos — cuando ya no se puede arreglar.

Y la vuelta tampoco estaba: `enviar_a_erp` deja el pedido **esperando
confirmación** a propósito, porque el ERP puede aceptar el mensaje y rechazar el
pedido después. Quien recogía esa respuesta no existía, así que el pedido se
quedaba en «enviado_erp» para siempre.
"""

from __future__ import annotations

import ast
import inspect


def test_integration_escucha_el_pedido_que_sale() -> None:
    """**Esta es la del agujero.**"""
    import os

    from crmcore.config import limpiar_cache_settings

    previo = os.environ.get("SERVICE_NAME")
    os.environ["SERVICE_NAME"] = "integration"
    limpiar_cache_settings()
    try:
        import importlib

        fuente = inspect.getsource(importlib.import_module("services.integration.main"))
    finally:
        if previo is None:
            os.environ.pop("SERVICE_NAME", None)
        else:
            os.environ["SERVICE_NAME"] = previo
        limpiar_cache_settings()

    assert '"order.submitted"' in fuente, (
        "nadie consume el pedido que ventas manda al ERP: se marca como enviado "
        "y no sale de aquí"
    )


def test_ventas_escucha_la_respuesta_del_erp() -> None:
    import os

    from crmcore.config import limpiar_cache_settings

    previo = os.environ.get("SERVICE_NAME")
    os.environ["SERVICE_NAME"] = "sales"
    limpiar_cache_settings()
    try:
        import importlib

        fuente = inspect.getsource(importlib.import_module("services.sales.main"))
    finally:
        if previo is None:
            os.environ.pop("SERVICE_NAME", None)
        else:
            os.environ["SERVICE_NAME"] = previo
        limpiar_cache_settings()

    assert '"order.erp.*"' in fuente, (
        "nadie recoge lo que el ERP conteste: el pedido se queda «enviado_erp» " "para siempre"
    )


def test_la_operacion_del_erp_es_configuracion_y_no_una_constante() -> None:
    """La clave la pone quien declara la conexión: en un cliente será
    «pedido.crear» y en otro «sales_order». Un nombre fijo obligaría a todos a
    llamarla igual, que es pedirle al cliente que se adapte a nuestro
    vocabulario interno."""
    from crmcore.config import get_settings

    from services.integration import pedidos_erp

    fuente = inspect.getsource(pedidos_erp.consumir_pedido)
    assert "integracion_operacion_pedidos" in fuente
    assert hasattr(get_settings(), "integracion_operacion_pedidos")


def test_un_tenant_sin_erp_declarado_no_es_un_fallo() -> None:
    """La mayoría de los despliegues no tienen ninguno. Tratarlo como error
    llenaría el registro de fallos por una integración que nadie ha pedido, y
    entonces los fallos de verdad no se ven."""
    from services.integration import pedidos_erp

    arbol = ast.parse(inspect.getsource(pedidos_erp.consumir_pedido))
    avisos = [
        n
        for n in ast.walk(arbol)
        if isinstance(n, ast.Call)
        and getattr(n.func, "attr", "") in {"info", "warning", "error"}
        and any(isinstance(a, ast.Constant) and "sin_operacion" in str(a.value) for a in n.args)
    ]
    assert avisos, "no se anota el caso de un tenant sin ERP declarado"
    assert (
        getattr(avisos[0].func, "attr", "") == "info"
    ), "un tenant sin ERP se anota como error, y no lo es"


def test_la_referencia_del_erp_no_se_inventa() -> None:
    """Es la que el cliente cita por teléfono para reclamar. Una referencia
    inventada es peor que ninguna: manda a buscar algo que no existe."""
    from services.integration import pedidos_erp

    fuente = inspect.getsource(pedidos_erp.consumir_pedido)
    assert (
        'or ""' in fuente.split("referencia_erp")[1][:200]
    ), "si el ERP no devuelve referencia hay que dejarla vacía, no componer una"
