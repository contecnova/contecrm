"""Qué hace `service` con los datos personales que guarda (CRM-07.03.01.04)."""

from __future__ import annotations

from crmcore.cumplimiento import Tratamiento, declarar

RESPONSABLE = "El cliente titular del tenant; el fabricante actúa como encargado"

declarar(
    Tratamiento(
        objeto="accesos_portal",
        finalidad="Dar acceso al portal de soporte a la persona que abre o sigue un caso",
        base_legal="contrato",
        plazo="Mientras dure la relación de soporte",
        responsable=RESPONSABLE,
    )
)

declarar(
    Tratamiento(
        objeto="enlaces_acceso_portal",
        finalidad="Dar acceso puntual por enlace y dejar constancia de quién lo usó",
        base_legal="interes_legitimo",
        plazo="90 días desde el último uso",
        responsable=RESPONSABLE,
    )
)

declarar(
    Tratamiento(
        objeto="ordenes_trabajo",
        # La dirección de una visita es dato personal cuando el cliente es una
        # persona, y lo es también cuando es su domicilio aunque facture una
        # empresa. Se declara como tal sin buscarle excepciones.
        finalidad="Planificar y ejecutar la visita técnica en el lugar del servicio",
        base_legal="contrato",
        plazo="6 años, por la obligación de conservar la documentación del servicio prestado",
        destinatarios=("Técnicos asignados, propios o subcontratados",),
        responsable=RESPONSABLE,
    )
)
