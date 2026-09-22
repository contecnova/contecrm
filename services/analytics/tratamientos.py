"""Qué hace `analytics` con los datos personales que guarda (CRM-07.03.01.04)."""

from __future__ import annotations

from crmcore.cumplimiento import Tratamiento, declarar

declarar(
    Tratamiento(
        objeto="auditoria",
        # El registro de auditoría es el único sitio del sistema donde conservar
        # pesa más que suprimir: borrarlo a petición de alguien destruiría la
        # prueba de lo que esa misma persona hizo.
        finalidad="Dejar constancia de quién hizo qué, desde dónde y cuándo, para poder investigarlo",
        base_legal="obligacion_legal",
        plazo="Según la política de retención del tenant, con un mínimo de 12 meses",
        responsable="El cliente titular del tenant; el fabricante actúa como encargado",
    )
)
