"""Transportes de notificación: cómo sale un aviso del sistema (CRM-06.02.01.02).

Las notificaciones se creaban, se agrupaban, respetaban la franja de silencio y
se leían en la bandeja. Lo que faltaba es que **saliera alguna**: el repartidor.

La decisión que gobierna todo este módulo es que **no hay código de ningún
proveedor**. Ni Twilio, ni SendGrid, ni Firebase. Hay dos transportes y los dos
son estándares:

  * **SMTP** para el correo. Lo hablan todos los proveedores y todos los
    servidores corporativos, así que enchufar uno u otro es cambiar cuatro
    líneas del `.env` y no desplegar código.
  * **HTTP declarativo** para lo demás —SMS, push, el canal que sea—. El tenant
    declara URL, método, cabeceras y una plantilla de cuerpo; el sistema la
    rellena y la manda firmada. Es el mismo patrón que el conector de
    integraciones, que ya lleva en producción en `contecweb`.

Con un conector por proveedor, cada cliente con un proveedor distinto es una
versión del producto. Con esto, es una fila de configuración.

Tres cosas que hacen que esto sea operable y no un `send()` optimista:

**Todo intento queda registrado**, con su resultado y su error. «No me llegó el
aviso» es la incidencia más frecuente de un CRM y la más difícil de contestar
sin esto — se acaba mirando el log del servidor de correo de otra empresa.

**Los fallos se reintentan con espera creciente y acaban en una cola de
fallidos.** Un proveedor caído diez minutos no puede costar diez minutos de
avisos perdidos, y uno caído tres días no puede costar tres días de reintentos.

**Un destinatario sin dirección no es un error del sistema.** Es un dato
incompleto, se anota como tal y no se reintenta: reintentar cada cinco minutos
un envío a alguien que no tiene teléfono llena la cola de algo que nunca va a
salir.
"""

from __future__ import annotations

from crmcore.notificaciones.base import (
    CANALES,
    Destino,
    Mensaje,
    Resultado,
    Transporte,
    registrar_transporte,
    transporte_de,
    transportes_registrados,
)

__all__ = [
    "CANALES",
    "Destino",
    "Mensaje",
    "Resultado",
    "Transporte",
    "registrar_transporte",
    "transporte_de",
    "transportes_registrados",
]
