"""Firma HMAC de lo que sale hacia un endpoint del cliente.

Estaba en `services/eventing/entrega.py`, que es donde nació con los webhooks.
Se sube al núcleo porque hay más de una cosa que llama a una URL que escribe el
cliente —webhooks, y ahora el aviso de fin de un trabajo asíncrono
(CRM-00.02.01.12)— y las dos tienen exactamente el mismo problema: quien recibe
tiene que poder comprobar que el mensaje viene de aquí y que no es uno viejo
reenviado.

Duplicar la firma habría sido peor que repetir código: dos implementaciones de
un HMAC divergen, el manual del integrador describe una de las dos, y la
integración que verifica bien los webhooks rechaza los avisos de trabajo sin que
nadie entienda por qué.
"""

from __future__ import annotations

import hashlib
import hmac
import time

# Cabeceras del contrato de entrega. Se documentan en el manual del integrador,
# y son las que permiten verificar el mensaje sin confiar en la red.
H_FIRMA = "X-Contecrm-Firma"
H_MOMENTO = "X-Contecrm-Momento"


def ventana_por_defecto() -> int:
    """Ventana en la que se acepta un mensaje firmado, **de la configuración**.

    Cinco minutos por defecto: absorben el desfase de reloj razonable entre dos
    máquinas sin dejar abierta una ventana de reenvío que valga para nada.

    Era una constante —`VENTANA_S = 300`— mientras existía `WEBHOOK_FIRMA_VENTANA_S`
    en los ajustes, documentado en el manual de referencia como configurable
    entre 30 y 3600 segundos, y **sin que lo leyera nadie**. O sea que quien
    bajara la ventana para apretar el anti-replay, o la subiera porque sus
    máquinas van desfasadas, cambiaba un número que no hacía nada. Un límite que
    nadie consulta no limita.

    Se lee de `Settings` y no del ajuste por tenant: quien verifica una firma es
    el que recibe, y en ese momento todavía no se sabe de qué tenant es el
    mensaje —saberlo es justo lo que la firma permite—.
    """
    from crmcore.config import get_settings

    return int(get_settings().webhook_firma_ventana_s)


def firmar(cuerpo: bytes, secreto: str, momento: int) -> str:
    """Firma HMAC-SHA256 del cuerpo y el instante.

    El instante entra en la firma, y esa es la parte que impide el replay: sin
    él, un mensaje capturado se podría reenviar tal cual dentro de un año con su
    firma intacta.
    """
    material = f"{momento}.".encode() + cuerpo
    return hmac.new(secreto.encode(), material, hashlib.sha256).hexdigest()


def verificar_firma(
    cuerpo: bytes, secreto: str, firma: str, momento: int, *, ventana_s: int | None = None
) -> bool:
    """Verificación de referencia, para que el integrador la copie.

    Se publica en el manual porque la mitad de las integraciones que fallan lo
    hacen por implementar mal esta comprobación: comparando con `==` (que filtra
    por tiempo), olvidando la ventana, o firmando el JSON reserializado en vez
    de los bytes recibidos.
    """
    if abs(time.time() - momento) > (ventana_s if ventana_s is not None else ventana_por_defecto()):
        return False
    return hmac.compare_digest(firmar(cuerpo, secreto, momento), firma)


def cabeceras_firmadas(cuerpo: bytes, secreto: str) -> dict[str, str]:
    """Las dos cabeceras que acompañan a un cuerpo firmado.

    Existe para que quien firma no tenga que acordarse de mandar el momento: una
    firma sin su instante es inverificable, y el fallo aparece en el lado del
    integrador como «firma incorrecta», que manda a buscar al sitio equivocado.
    """
    momento = int(time.time())
    return {H_FIRMA: firmar(cuerpo, secreto, momento), H_MOMENTO: str(momento)}
