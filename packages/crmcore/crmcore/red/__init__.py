"""Salidas de red del servidor, con guard de SSRF.

Todo sitio que pida una URL **que aporta el tenant** y la busque desde el
servidor pasa por aquí: los webhooks, el conector declarativo de integraciones,
el descubrimiento del proveedor de identidad y el analizador de adjuntos.

Sin esto, un tenant registra un webhook contra `http://169.254.169.254/...` y se
lleva las credenciales de la máquina; o contra `http://postgres:5432` y escanea
la red interna desde dentro. No hace falta ningún fallo del producto: basta la
funcionalidad tal como está diseñada.

Portado de `contecmind/app/core/url_guard.py`, con el transporte **asíncrono**
añadido, que allí no hacía falta y aquí sí: la entrega de webhooks y el conector
son asíncronos.
"""

from crmcore.red.guard_url import (
    Veredicto,
    cliente_seguro,
    cliente_seguro_async,
    evaluar,
    exigir,
)

__all__ = [
    "Veredicto",
    "cliente_seguro",
    "cliente_seguro_async",
    "evaluar",
    "exigir",
]
