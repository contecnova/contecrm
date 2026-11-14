"""Emitir y verificar los JWT de la casa, en un solo sitio.

Cuatro tipos de token salían de cuatro `jwt.encode` distintos (sesión de
empleado en `identity`, componente embebido, portal, ticket de cuadro
incrustado) y se verificaban con otros tantos `jwt.decode`. Ninguno llevaba
`iss` ni `aud` y todos se firmaban con la misma `SECRET_KEY` tal cual, así que
lo ÚNICO que separaba una sesión de empleado de un ticket que vive en una página
pública era el campo `tipo`, y bastaba un verificador que se olvidara de mirarlo
para que uno valiera por otro: es exactamente lo que pasó en SEC-2 (auditoría
13-11-2026, SEC-11).

Ahora el tipo queda atado por tres sitios a la vez, y cualquiera basta:

  * **Clave por tipo.** Se deriva de `SECRET_KEY` con HMAC y el nombre de la
    audiencia. Un token de portal no se puede ni comprobar con la clave de
    sesión: falla la firma antes de mirar nada más.
  * **`aud`** = `contecrm:<tipo>`. Lo exige `verificar`.
  * **`iss`** = `EMISOR`. Lo exige `verificar`.

Sigue habiendo un solo secreto que guardar y rotar; lo que cambia es que de él
salen claves distintas para usos distintos (separación de claves).
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Iterable
from typing import Any

import jwt

# Quién emite. Es el nombre del producto en el protocolo, no un ajuste: lo
# comprueba quien verifica, que es este mismo módulo.
EMISOR = "contecrm"


class TipoNoAdmitido(jwt.InvalidTokenError):
    """El token es de un tipo que este verificador no acepta."""


def audiencia(tipo: str) -> str:
    """La audiencia de un tipo de token. Deriva del tipo: no hay tabla que olvidar."""
    return f"{EMISOR}:{tipo}"


def _clave(tipo: str, secreto: str | None = None) -> bytes:
    if secreto is None:
        from crmcore.config import get_settings

        secreto = get_settings().secret_key.get_secret_value()
    return hmac.new(secreto.encode(), f"jwt|{audiencia(tipo)}".encode(), hashlib.sha256).digest()


def _algoritmo() -> str:
    from crmcore.config import get_settings

    return get_settings().jwt_algorithm


def emitir(carga: dict[str, Any], *, secreto: str | None = None) -> str:
    """Firma `carga` para su `tipo` (obligatorio), con `iss` y `aud` puestos."""
    tipo = str(carga.get("tipo") or "")
    if not tipo:
        raise ValueError("Un token de la casa tiene que llevar `tipo`")
    completa = {**carga, "iss": EMISOR, "aud": audiencia(tipo)}
    return jwt.encode(completa, _clave(tipo, secreto), algorithm=_algoritmo())


def verificar(token: str, *, tipos: Iterable[str], secreto: str | None = None) -> dict[str, Any]:
    """Comprueba firma, `exp`, `iss` y `aud` para uno de `tipos` y devuelve la carga.

    El tipo se lee SIN verificar solo para elegir la clave; si es falso, la
    firma no cuadra con esa clave y el token se rechaza. Un tipo fuera de
    `tipos` se rechaza antes de tocar la clave.

    Lanza las excepciones de PyJWT (`ExpiredSignatureError`, `InvalidTokenError`)
    para que cada llamante conserve su propio mensaje y código.
    """
    sin_verificar = jwt.decode(token, options={"verify_signature": False})
    tipo = str(sin_verificar.get("tipo") or "")
    if tipo not in set(tipos):
        raise TipoNoAdmitido(f"tipo de token no admitido: {tipo or '(ninguno)'}")
    return dict(
        jwt.decode(
            token,
            _clave(tipo, secreto),
            algorithms=[_algoritmo()],
            audience=audiencia(tipo),
            issuer=EMISOR,
            options={"require": ["exp", "iss", "aud"]},
        )
    )
