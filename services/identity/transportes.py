"""Los transportes que este servicio tiene enchufados (CRM-06.02.01.02).

Registrarlos aquí y no en el núcleo es deliberado: el núcleo sabe **cómo** se
entrega por SMTP o por HTTP, y este servicio decide **qué canales ofrece esta
instalación**. Una instalación sin SMS no registra el suyo, y los avisos por ese
canal se anotan como «sin transporte» en vez de quedarse girando en la cola.
"""

from __future__ import annotations

from crmcore.notificaciones import registrar_transporte
from crmcore.notificaciones.http import TransporteHTTP
from crmcore.notificaciones.smtp import TransporteSMTP

# Correo por SMTP: lo hablan todos los proveedores y el servidor corporativo del
# cliente que no quiere que su correo salga de su red.
registrar_transporte(TransporteSMTP())

# SMS y push por HTTP declarativo. **No hay código de ningún proveedor**: el
# tenant declara URL, método, cabeceras y plantilla de cuerpo en los ajustes
# `canal_sms` y `canal_push`. Con un conector por proveedor, cada cliente con
# uno distinto sería una versión del producto.
registrar_transporte(TransporteHTTP("sms"))
registrar_transporte(TransporteHTTP("push"))
