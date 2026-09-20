"""Canal por HTTP declarativo: SMS, push y lo que venga.

El tenant declara a dónde va, con qué método, qué cabeceras y qué cuerpo. El
sistema rellena la plantilla y manda. **No hay código de ningún proveedor**, y
esa es toda la idea: con un conector por proveedor, cada cliente con un
proveedor distinto es una versión del producto que hay que mantener, probar y
desplegar. Con esto es una fila de configuración.

Es el mismo patrón que el conector de integraciones, que ya lleva en producción
en `contecweb`, y la misma plantilla de sustitución que las de correo: quien
sabe configurar una sabe configurar la otra.

Dos cosas que no son opcionales:

**Sale por el guard de SSRF.** La URL la escribe el tenant, así que sin guard un
canal apuntando a `169.254.169.254` se lleva las credenciales de la máquina. Es
exactamente el mismo riesgo que los webhooks y se resuelve igual.

**Va firmado.** Con el mismo HMAC que los webhooks y el aviso de trabajos, para
que el receptor pueda comprobar que viene de aquí y que no es uno viejo
reenviado — y para que no haya tres implementaciones del mismo HMAC.
"""

from __future__ import annotations

import json
from typing import Any

from crmcore.logging import get_logger
from crmcore.notificaciones.base import Destino, Mensaje, Resultado

logger = get_logger(__name__)

# Códigos que no se reintentan: el proveedor ha dicho que el mensaje está mal, y
# repetirlo no lo va a arreglar. El 429 sí se reintenta porque significa «ahora
# no», que es justo lo que un reintento resuelve.
NO_REINTENTABLES = {400, 401, 403, 404, 405, 410, 422}


class TransporteHTTP:
    """Un canal entero descrito por configuración."""

    def __init__(self, canal: str) -> None:
        self.canal = canal

    def entregar(self, destino: Destino, mensaje: Mensaje, config: dict[str, Any]) -> Resultado:
        from crmcore.config import get_settings
        from crmcore.red import cliente_seguro
        from crmcore.security.firma import cabeceras_firmadas

        if not destino.direccion:
            return Resultado(False, f"el destinatario no tiene {self.canal}", reintentar=False)
        url = str(config.get("url") or "")
        if not url:
            return Resultado(
                False,
                f"el canal «{self.canal}» no está configurado para este tenant",
                reintentar=False,
            )

        cuerpo = self._componer(destino, mensaje, config)
        s = get_settings()
        cabeceras = {
            "content-type": "application/json",
            **{str(k): str(v) for k, v in (config.get("cabeceras") or {}).items()},
            **cabeceras_firmadas(cuerpo, s.secret_key.get_secret_value()),
        }

        try:
            with cliente_seguro(timeout=s.http_externo_timeout_s) as cliente:
                respuesta = cliente.request(
                    str(config.get("metodo") or "POST").upper(),
                    url,
                    content=cuerpo,
                    headers=cabeceras,
                )
        except Exception as exc:  # noqa: BLE001 — un transporte nunca lanza
            return Resultado(False, f"{type(exc).__name__}: {exc}"[:300], reintentar=True)

        if 200 <= respuesta.status_code < 300:
            return Resultado(True, "entregado", referencia=_referencia(respuesta))
        return Resultado(
            False,
            f"HTTP {respuesta.status_code}: {respuesta.text[:200]}",
            reintentar=respuesta.status_code not in NO_REINTENTABLES,
        )

    def _componer(self, destino: Destino, mensaje: Mensaje, config: dict[str, Any]) -> bytes:
        """Rellena la plantilla de cuerpo que declara el tenant.

        Sin plantilla se manda una forma canónica. Es deliberado: un canal que
        no arranca hasta que alguien escribe una plantilla es un canal que nadie
        enciende, y la forma canónica la entiende cualquier receptor que
        controle el propio cliente.
        """
        valores = {
            "destino": destino.direccion,
            "nombre": destino.nombre,
            "titulo": mensaje.titulo,
            "cuerpo": mensaje.cuerpo,
            "tipo": mensaje.tipo,
            "prioridad": mensaje.prioridad,
            "objeto_tipo": mensaje.objeto_tipo,
            "objeto_id": mensaje.objeto_id,
        }
        plantilla = config.get("cuerpo")
        if not plantilla:
            return json.dumps(valores, ensure_ascii=False).encode()

        if isinstance(plantilla, dict):
            return json.dumps(_sustituir(plantilla, valores), ensure_ascii=False).encode()
        return _sustituir_texto(str(plantilla), valores).encode()


def _sustituir(estructura: Any, valores: dict[str, str]) -> Any:
    if isinstance(estructura, dict):
        return {k: _sustituir(v, valores) for k, v in estructura.items()}
    if isinstance(estructura, list):
        return [_sustituir(v, valores) for v in estructura]
    if isinstance(estructura, str):
        return _sustituir_texto(estructura, valores)
    return estructura


def _sustituir_texto(texto: str, valores: dict[str, str]) -> str:
    """`{{clave}}` y nada más: sin condicionales, bucles ni expresiones.

    Una plantilla es dato del tenant, y un motor con lógica sería ejecutar
    código del cliente dentro del proceso que manda sus notificaciones.
    """
    import re

    return re.sub(
        r"\{\{\s*(\w+)\s*\}\}",
        lambda m: str(valores.get(m.group(1), m.group(0))),
        texto,
    )


def _referencia(respuesta: Any) -> str:
    """El identificador que devuelva el proveedor, si devuelve alguno.

    Se busca en las claves que usan de verdad los proveedores de SMS y push.
    Sirve para que, cuando alguien pregunte por un envío concreto, se pueda
    buscar del lado de ellos en vez de decir «nosotros lo mandamos».
    """
    try:
        cuerpo = respuesta.json()
    except Exception:  # noqa: BLE001 — muchos devuelven texto plano
        return ""
    if not isinstance(cuerpo, dict):
        return ""
    for clave in ("id", "sid", "message_id", "messageId", "reference", "referencia"):
        if cuerpo.get(clave):
            return str(cuerpo[clave])[:120]
    return ""
