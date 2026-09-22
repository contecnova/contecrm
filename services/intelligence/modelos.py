"""Estado propio del servicio de inteligencia.

Todo lo que este servicio guarda es **sobre** la IA, no producido por ella: qué
proveedor atiende a quién, qué se filtró, qué se propuso y qué costó. Lo generado
vive como propuesta hasta que una persona lo acepta, y entonces lo escribe el
servicio dueño del objeto — nunca este.
"""

from __future__ import annotations

# ── Tablas compartidas que viven en ESTE esquema ──────────────────────────
from crmcore.authz.politicas import PoliticaAbac, VersionPoliticaAbac  # noqa: E402,F401
from crmcore.datos.retencion import BloqueoLegal, PoliticaRetencion  # noqa: E402,F401
from crmcore.runtime.versiones import VersionAjuste  # noqa: E402,F401
from crmcore.security.byok import ClaveTenant  # noqa: E402,F401

# Las tablas viven en sus módulos, con su lógica, pero tienen que importarse aquí:
# `alembic` solo mira `modelos.py`.
from services.intelligence.enrutador import (  # noqa: F401
    GastoIA,
    PoliticaIA,
    ProveedorIA,
)
from services.intelligence.extraccion import CampoExtraido  # noqa: F401
from services.intelligence.generacion import PlantillaPrompt, Propuesta  # noqa: F401
from services.intelligence.guardias import BloqueoIA, ReglaGuardia  # noqa: F401
from services.intelligence.uso import LlamadaIA  # noqa: F401

__all__ = [
    "BloqueoIA",
    "BloqueoLegal",
    "CampoExtraido",
    "ClaveTenant",
    "GastoIA",
    "LlamadaIA",
    "PlantillaPrompt",
    "PoliticaAbac",
    "PoliticaIA",
    "PoliticaRetencion",
    "Propuesta",
    "ProveedorIA",
    "ReglaGuardia",
    "VersionAjuste",
    "VersionPoliticaAbac",
]
