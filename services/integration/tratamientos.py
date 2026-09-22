"""Qué hace `integration` con los datos personales que guarda (CRM-07.03.01.04)."""

from __future__ import annotations

from crmcore.cumplimiento import Tratamiento, declarar

RESPONSABLE = "El cliente titular del tenant; el fabricante actúa como encargado"

declarar(
    Tratamiento(
        objeto="firmantes",
        finalidad="Enviar el documento a firmar a cada firmante y avisarle del estado",
        base_legal="contrato",
        plazo="6 años desde la firma, por la obligación de conservar la prueba del acuerdo",
        destinatarios=("Proveedor de firma electrónica configurado por el cliente",),
        responsable=RESPONSABLE,
    )
)

declarar(
    Tratamiento(
        objeto="evidencias_firma",
        # La IP y el momento son la prueba: sin ellos, la firma electrónica no
        # sostiene nada el día que alguien la niegue.
        finalidad="Acreditar quién firmó, cuándo y desde dónde",
        base_legal="obligacion_legal",
        plazo="6 años desde la firma",
        responsable=RESPONSABLE,
    )
)
