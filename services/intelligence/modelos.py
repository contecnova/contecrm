"""Estado propio del servicio de inteligencia.

Todo lo que este servicio guarda es **sobre** la IA, no producido por ella: qué
proveedor atiende a quién, qué se filtró, qué se propuso y qué costó. Lo generado
vive como propuesta hasta que una persona lo acepta, y entonces lo escribe el
servicio dueño del objeto — nunca este.
"""

from __future__ import annotations

# ── Tablas compartidas que viven en ESTE esquema ──────────────────────────
from crmcore.authz.politicas import PoliticaAbac, VersionPoliticaAbac  # noqa: E402,F401

# La papelera de este servicio. Su router se monta —`/<servicio>/papelera`— y sin
# la tabla la pantalla devolvía 500: `relation "papelera" does not exist`. El
# borrado es lógico y cada servicio guarda la suya en su esquema, que es lo que
# impide que uno lea las tablas de otro.
from crmcore.datos.retencion import BloqueoLegal, PoliticaRetencion  # noqa: E402,F401

# La tabla de trabajos asíncronos. La necesita la medición de salud de todas las
# cuentas: son cuatro llamadas a la API por cuenta, y una cartera de mil son
# cuatro mil — eso no cabe en una petición.
from crmcore.datos.trabajos import Trabajo  # noqa: E402,F401
from crmcore.runtime.versiones import VersionAjuste  # noqa: E402,F401
from crmcore.security.byok import ClaveTenant  # noqa: E402,F401

from services.intelligence.agentes import (  # noqa: F401
    Agente,
    EjecucionAgente,
    PasoAgente,
)
from services.intelligence.anomalias import (  # noqa: F401
    Anomalia,
    ObservacionSerie,
    SerieVigilada,
)
from services.intelligence.conversacion import (  # noqa: F401
    ResumenConversacion,
    SenalConversacion,
)

# Las tablas viven en sus módulos, con su lógica, pero tienen que importarse aquí:
# `alembic` solo mira `modelos.py`.
from services.intelligence.enrutador import (  # noqa: F401
    GastoIA,
    PoliticaIA,
    ProveedorIA,
)
from services.intelligence.extraccion import CampoExtraido  # noqa: F401
from services.intelligence.generacion import PlantillaPrompt, Propuesta  # noqa: F401
from services.intelligence.gobierno import MedicionDeriva, ModeloML  # noqa: F401
from services.intelligence.guardias import BloqueoIA, ReglaGuardia  # noqa: F401
from services.intelligence.prediccion import Prediccion  # noqa: F401
from services.intelligence.salud import SaludCuenta  # noqa: F401
from services.intelligence.uso import LlamadaIA  # noqa: F401

__all__ = [
    "Agente",
    "Anomalia",
    "BloqueoIA",
    "BloqueoLegal",
    "CampoExtraido",
    "ClaveTenant",
    "EjecucionAgente",
    "GastoIA",
    "LlamadaIA",
    "MedicionDeriva",
    "ModeloML",
    "ObservacionSerie",
    "PasoAgente",
    "PlantillaPrompt",
    "PoliticaAbac",
    "PoliticaIA",
    "PoliticaRetencion",
    "Prediccion",
    "Propuesta",
    "ProveedorIA",
    "ReglaGuardia",
    "ResumenConversacion",
    "SaludCuenta",
    "SenalConversacion",
    "SerieVigilada",
    "VersionAjuste",
    "VersionPoliticaAbac",
]
