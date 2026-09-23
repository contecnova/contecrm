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

declarar(
    Tratamiento(
        objeto="buzones",
        finalidad="Registrar en el CRM las conversaciones y reuniones con clientes",
        base_legal="interes_legitimo",
        plazo="Mientras la persona tenga el buzón conectado",
        destinatarios=("Proveedor de correo y calendario que use el cliente",),
        responsable=RESPONSABLE,
    )
)

declarar(
    Tratamiento(
        objeto="firmas_presenciales",
        # Categoría especial del artículo 9: el trazo de una firma —velocidad,
        # presión, tiempos— identifica a una persona. Por eso va con
        # consentimiento explícito y cifrado, y por eso se declara aparte.
        finalidad="Probar que una persona firmó un documento concreto, delante de un testigo",
        base_legal="consentimiento",
        plazo="6 años desde la firma, por la obligación de conservar la prueba del acuerdo",
        responsable=RESPONSABLE,
    )
)

# ── Suites de productividad (CRM-06.01.03.18) ─────────────────────────────

declarar(
    Tratamiento(
        objeto="consentimientos_suite",
        # El propio consentimiento es un tratamiento, y conservarlo es lo que
        # permite demostrar que se pidió. Borrarlo al revocar sería borrar la
        # prueba de que se hizo bien.
        finalidad=(
            "Acreditar qué recurso de su correo, calendario o agenda autorizó cada "
            "persona, cuándo y con qué alcance"
        ),
        base_legal="obligacion_legal",
        plazo="3 años desde la revocación, para poder acreditar que hubo consentimiento",
        responsable=RESPONSABLE,
    )
)

declarar(
    Tratamiento(
        objeto="suscripciones_suite",
        finalidad="Recibir del proveedor los cambios del buzón conectado sin sondear",
        base_legal="interes_legitimo",
        plazo="Mientras el recurso siga conectado; se borra también en el proveedor al darse de baja",
        destinatarios=("La suite de productividad que use el cliente",),
        responsable=RESPONSABLE,
    )
)
