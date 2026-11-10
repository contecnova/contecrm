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

# ── Lo que constaba hecho y sólo simulaba, ahora guardado (09-11-2026) ────

declarar(
    Tratamiento(
        objeto="llamadas_telefonicas",
        # El número, quién atendió, lo que tecleó en el IVR y el enlace a la
        # grabación. La grabación vive en la centralita, no aquí.
        finalidad=(
            "Identificar a quien llama, atenderle con su contexto y dejar constancia "
            "de cada llamada como actividad del cliente"
        ),
        base_legal="interes_legitimo",
        plazo="Mientras exista la actividad que la registra; la grabación, el plazo de la centralita",
        destinatarios=("Proveedor de telefonía configurado por el cliente",),
        responsable=RESPONSABLE,
    )
)

declarar(
    Tratamiento(
        objeto="hechos_compensacion",
        finalidad=(
            "Mandar al motor de compensación del cliente las ventas, cobros y "
            "devoluciones de cada comercial y conciliar lo que calcula"
        ),
        base_legal="contrato",
        plazo="4 años desde el periodo liquidado, por la obligación de justificar la nómina",
        destinatarios=("Motor de compensación configurado por el cliente",),
        responsable=RESPONSABLE,
    )
)

declarar(
    Tratamiento(
        objeto="referencias_suite",
        # Sólo la referencia y el nombre: el contenido se queda en el origen.
        finalidad=(
            "Enlazar a un registro del CRM notas, ficheros y conversaciones que "
            "siguen en la suite del cliente, sin copiarlos"
        ),
        base_legal="interes_legitimo",
        plazo="Mientras exista el registro al que cuelgan o hasta que se quite el vínculo",
        destinatarios=("La suite de productividad que use el cliente",),
        responsable=RESPONSABLE,
    )
)

# ── Lo que integración cuenta a otros servicios (09-11-2026) ──────────────

declarar(
    Tratamiento(
        objeto="senales_identidad_salientes",
        # El correo, el teléfono o el identificador externo con que alguien
        # llegó por un canal, hasta que party lo tiene.
        finalidad=(
            "Reconocer a la misma persona cuando llega por canales distintos, "
            "mandando a party la señal con que se la vio"
        ),
        base_legal="interes_legitimo",
        plazo="Mientras exista el contacto o la interacción que la originó",
        destinatarios=(),
        responsable=RESPONSABLE,
    )
)

declarar(
    Tratamiento(
        objeto="elementos_buzon",
        # Asunto, asistentes y remitente de lo sincronizado; nunca el cuerpo.
        finalidad=(
            "Registrar en el CRM los correos y reuniones con clientes y sacar de "
            "las cadencias a quien contesta"
        ),
        base_legal="interes_legitimo",
        plazo="Mientras el buzón siga conectado; el remitente de quien no es nadie en el CRM se borra al avisar",
        destinatarios=("El proveedor de correo y calendario que conecte cada persona",),
        responsable=RESPONSABLE,
    )
)
