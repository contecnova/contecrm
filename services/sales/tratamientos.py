"""Qué hace `sales` con los datos personales que guarda (CRM-07.03.01.04)."""

from __future__ import annotations

from crmcore.cumplimiento import Tratamiento, declarar

RESPONSABLE = "El cliente titular del tenant; el fabricante actúa como encargado"

declarar(
    Tratamiento(
        objeto="leads",
        # Un lead es alguien que todavía no ha pedido nada: la base legal no
        # puede ser el contrato, porque no hay contrato. Decir que sí es el error
        # más repetido de todo el sector.
        finalidad="Evaluar y atender el interés comercial de una persona que ha dejado sus datos",
        base_legal="interes_legitimo",
        plazo="24 meses sin actividad, y luego se suprime o se anonimiza",
        destinatarios=("Equipo comercial del cliente",),
        responsable=RESPONSABLE,
    )
)

declarar(
    Tratamiento(
        objeto="inscripciones_cadencia",
        finalidad="Ejecutar la secuencia de contactos comerciales acordada",
        base_legal="interes_legitimo",
        plazo="Mientras dure la secuencia y 12 meses después",
        responsable=RESPONSABLE,
    )
)

declarar(
    Tratamiento(
        objeto="registros_oportunidad",
        finalidad="Registrar y proteger la oportunidad que trae un partner, evitando que dos la trabajen a la vez",
        base_legal="interes_legitimo",
        plazo="Mientras el registro esté vigente y 6 años después",
        destinatarios=("El partner que registra la oportunidad",),
        responsable=RESPONSABLE,
    )
)

declarar(
    Tratamiento(
        objeto="accesos_partner",
        finalidad="Dar acceso al portal a las personas del partner",
        base_legal="contrato",
        plazo="Mientras dure el acuerdo con el partner",
        destinatarios=("El partner",),
        responsable=RESPONSABLE,
    )
)

declarar(
    Tratamiento(
        objeto="enlaces_acceso_partner",
        finalidad="Dar acceso puntual por enlace y dejar constancia de quién lo usó",
        base_legal="interes_legitimo",
        plazo="90 días desde el último uso",
        responsable=RESPONSABLE,
    )
)
