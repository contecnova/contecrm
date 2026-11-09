"""Normalización de cuentas y contactos (CRM-01.01.04.04).

La lógica vive en `crmcore.normalizacion`: la usan también los leads de
`sales` para deduplicar al capturar (CRM-01.01.03.03), y una copia por
servicio acabaría normalizando el mismo teléfono de dos formas. Este módulo
se queda para que `party` siga importándola por su nombre de siempre.
"""

from __future__ import annotations

from crmcore.normalizacion import *  # noqa: F403
from crmcore.normalizacion import (  # noqa: F401
    _RE_ESPACIOS,
    _RE_NO_ALFANUM,
    _RE_SOLO_DIGITOS,
    _unir_iniciales,
)
