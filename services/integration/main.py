"""Punto de entrada del servicio de integración."""

from __future__ import annotations

from crmcore.service import crear_servicio

from services.integration import eventos  # noqa: F401  (registra los tipos de evento)
from services.integration.api import ROUTERS
from services.integration.api_buzon import ROUTERS_BUZON
from services.integration.api_conectividad import ROUTERS_CONECTIVIDAD
from services.integration.api_encargos import ROUTERS_ENCARGOS
from services.integration.api_firma import ROUTERS_FIRMA
from services.integration.api_telemetria import ROUTERS_TELEMETRIA
from services.integration.proyeccion import consumir as consumir_modulo

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
    ],
    # Los conectores que declara un módulo vertical se convierten aquí en
    # proveedores. Llegan por evento porque este servicio no puede leer el
    # esquema de `metadata`, y si no llegaran habría que teclearlos otra vez en
    # esta pantalla: justo el trabajo manual que el módulo existe para quitar.
    consumidores=[("module.*", consumir_modulo, "integration-modulos")],
)
