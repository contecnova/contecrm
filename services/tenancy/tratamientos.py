"""Qué hace `tenancy` con los datos personales que guarda (CRM-07.03.01.04)."""

from __future__ import annotations

from crmcore.cumplimiento import Tratamiento, declarar

# A diferencia del resto del producto, aquí el responsable es el FABRICANTE y no
# el cliente: una solicitud de alta se recibe antes de que exista el tenant, así
# que no hay todavía ningún cliente titular que pueda serlo. Es la única tabla
# del sistema de la que esto es cierto.
RESPONSABLE = "El fabricante: la solicitud llega antes de que exista el tenant"

declarar(
    Tratamiento(
        objeto="altas_pendientes",
        # Dos datos personales y cada uno por un motivo distinto. El correo es
        # el eje: sin él no hay a quién mandar el enlace ni a quién hacer
        # administrador. La IP es para poder mirar después quién ha estado
        # probando nombres de empresa, que es el abuso que esta puerta invita.
        finalidad=(
            "Verificar que quien pide dar de alta una empresa es dueño del correo "
            "que indica, y poder investigar un uso abusivo del alta pública"
        ),
        base_legal="interes_legitimo",
        plazo=(
            "30 días desde la solicitud, usada o no (ONBOARDING_RETENCION_DIAS). "
            "Pasado el plazo se borran: son correos de gente que nunca llegó a ser "
            "cliente y no hay motivo para guardarlos"
        ),
        responsable=RESPONSABLE,
    )
)
