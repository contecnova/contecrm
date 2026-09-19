"""Cifrado de campo y de secretos (CRM-00.05.03.02, CRM-00.01.04.08).

AES-256-GCM con clave derivada de la maestra. GCM y no CBC porque **autentica**:
un valor alterado en la base no se descifra a otra cosa, falla. Sin
autenticación, quien pueda escribir en la tabla puede cambiar un valor cifrado
por otro y nadie se entera hasta que el dato equivocado ya se ha usado.

Tres decisiones y su porqué:

**Nonce por valor, guardado con él.** Reutilizar un nonce con GCM no es una
debilidad teórica: permite recuperar la clave de autenticación. Se genera uno
aleatorio en cada cifrado y viaja delante del texto cifrado.

**Clave derivada por propósito.** La clave que cifra credenciales de integración
no es la misma que cifra un campo de cliente, aunque las dos salgan de la misma
maestra. Así, comprometer un subsistema no da acceso a lo del otro.

**Rotación con clave anterior.** Al rotar, la maestra vieja se conserva en
`ENCRYPTION_KEY_PREVIA` y se usa para descifrar lo que aún no se ha recifrado.
Sin eso, rotar exige recifrarlo todo en una ventana de parada.

Limitación honesta: esto protege frente a quien lee la base (copia de
seguridad filtrada, acceso al disco), **no** frente a quien ejecuta código en el
proceso, que tiene la clave en memoria. Para eso hace falta un HSM o un KMS
externo, que es lo que enchufa `BYOK_ENABLED` con un backend de vault.
"""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from crmcore.errors import ErrorInterno
from crmcore.logging import get_logger

logger = get_logger(__name__)

# Marca que distingue un valor cifrado por nosotros de uno en claro. Permite
# convivir con datos antiguos sin cifrar durante una migración, y saber de un
# vistazo si una columna está cifrada de verdad.
PREFIJO = "enc:v1:"
# Propósito reservado: el sobre del material BYOK. Ver `_clave_del_tenant`.
PROPOSITO_SOBRE = "byok"
NONCE_BYTES = 12  # tamaño estándar de GCM; otro tamaño degrada la seguridad


def _clave(proposito: str, *, previa: bool = False, db: Any = None) -> bytes:
    """Deriva la clave de 32 bytes para un propósito concreto.

    Con BYOK activo (CRM-00.01.04.09) la clave sale del material que aportó el
    tenant, envuelto con la maestra. Sin BYOK —o para un tenant que no lo usa—
    sale solo de la maestra, que es el camino de siempre.

    Si el tenant **revocó** su clave, esto lanza en vez de caer a la maestra.
    Caer sería seguir descifrando datos que el cliente mandó hacer ilegibles.
    """
    from crmcore.config import get_settings

    if not previa:
        propia = _clave_del_tenant(proposito, db)
        if propia is not None:
            return propia

    s = get_settings()
    maestra = (
        s.encryption_key_previa.get_secret_value()
        if previa
        else s.encryption_key.get_secret_value()
    )
    if not maestra:
        raise ErrorInterno(
            "No hay clave de cifrado configurada (ENCRYPTION_KEY): no se puede "
            "guardar un dato marcado como sensible",
            error_code="cifrado.sin_clave",
        )
    # HKDF simplificado con SHA-256: suficiente porque la maestra ya es de alta
    # entropía (se genera con `openssl rand`), y el propósito actúa de contexto.
    return hashlib.sha256(f"{proposito}|{maestra}".encode()).digest()


def _clave_del_tenant(proposito: str, db: Any) -> bytes | None:
    """La clave BYOK del tenant en curso, si la hay.

    La sesión se resuelve sola cuando no se pasa: el cifrado se invoca desde
    sitios que no la tienen a mano —un validador de Pydantic, un `before_flush`—
    y obligar a pasarla por todos ellos habría significado tocar treinta
    llamadas para una funcionalidad que la mayoría de instalaciones no enciende.
    Cuando BYOK está apagado esto ni siquiera abre una sesión.
    """
    from crmcore.config import get_settings

    if not get_settings().byok_enabled:
        return None
    if proposito == PROPOSITO_SOBRE:
        # El sobre que guarda el material del cliente se cifra SIEMPRE con la
        # maestra, por definición: es lo que envuelve a la clave del cliente, no
        # puede depender de ella.
        #
        # Sin esta línea, abrir el sobre pedía la clave del tenant, que exigía
        # abrir el sobre, que pedía la clave... Cada vuelta abría una sesión
        # nueva y el fallo aparecía como «QueuePool limit reached», que manda a
        # buscar una fuga de conexiones en el sitio equivocado.
        return None

    from crmcore.security.byok import clave_efectiva
    from crmcore.tenancy.context import contexto_actual

    tenant_id = contexto_actual().tenant_id
    if tenant_id is None:
        return None
    if db is None:
        from crmcore.db.session import nueva_sesion

        db = nueva_sesion(tenant_id)
        try:
            return clave_efectiva(db, tenant_id, proposito)
        finally:
            db.close()
    return clave_efectiva(db, tenant_id, proposito)


def cifrar(valor: str, *, proposito: str = "general", db: Any = None) -> str:
    """Cifra un valor. Devuelve `enc:v1:<base64(nonce+cifrado)>`."""
    if valor == "":
        return ""
    nonce = os.urandom(NONCE_BYTES)
    cifrado = AESGCM(_clave(proposito, db=db)).encrypt(nonce, valor.encode(), proposito.encode())
    return PREFIJO + base64.b64encode(nonce + cifrado).decode()


def descifrar(valor: str, *, proposito: str = "general", db: Any = None) -> str:
    """Descifra un valor. Si no lleva la marca, lo devuelve tal cual.

    Devolver el valor sin marca en vez de fallar permite convivir con datos
    antiguos en claro mientras se recifran. Es un compromiso consciente: el
    precio es que un valor en claro pasa desapercibido, y por eso hay un gate
    que comprueba que las columnas declaradas cifradas no tengan valores sin
    marca en producción.
    """
    if not valor or not valor.startswith(PREFIJO):
        return valor
    crudo = base64.b64decode(valor[len(PREFIJO) :])
    nonce, cifrado = crudo[:NONCE_BYTES], crudo[NONCE_BYTES:]
    try:
        return AESGCM(_clave(proposito, db=db)).decrypt(nonce, cifrado, proposito.encode()).decode()
    except InvalidTag:
        # Puede ser un valor cifrado con la clave anterior (rotación en curso) o
        # un valor manipulado. Se prueba con la anterior antes de rendirse.
        try:
            return (
                AESGCM(_clave(proposito, previa=True))
                .decrypt(nonce, cifrado, proposito.encode())
                .decode()
            )
        except (InvalidTag, ErrorInterno):
            logger.error("cifrado.valor_no_descifrable", proposito=proposito)
            raise ErrorInterno(
                "No se ha podido descifrar el valor: o la clave ha cambiado sin "
                "recifrar, o el dato se ha alterado",
                error_code="cifrado.no_descifrable",
            )


def cifrar_dict(valores: dict[str, Any], *, proposito: str = "credenciales") -> dict[str, Any]:
    """Cifra los valores de un diccionario. Las CLAVES quedan en claro.

    A propósito: saber que una credencial tiene `client_id` y `client_secret` no
    es un secreto, y dejarlo legible permite validar la forma de la
    configuración sin descifrar nada.
    """
    return {k: cifrar(str(v), proposito=proposito) for k, v in valores.items()}


def descifrar_dict(valores: dict[str, Any], *, proposito: str = "credenciales") -> dict[str, str]:
    return {k: descifrar(str(v), proposito=proposito) for k, v in valores.items()}


def enmascarar(valor: str, *, visibles: int = 4) -> str:
    """Enmascara un valor dejando los últimos caracteres (CRM-00.05.03.03).

    Para enseñar «····3210» en una pantalla: identificable por quien lo conoce,
    inútil para quien no.
    """
    if not valor:
        return ""
    if len(valor) <= visibles:
        return "·" * len(valor)
    return "·" * (len(valor) - visibles) + valor[-visibles:]
