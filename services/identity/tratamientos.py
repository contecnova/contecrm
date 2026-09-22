"""Qué hace `identity` con los datos personales que guarda (CRM-07.03.01.04)."""

from __future__ import annotations

from crmcore.cumplimiento import Tratamiento, declarar

RESPONSABLE = "El cliente titular del tenant; el fabricante actúa como encargado"

declarar(
    Tratamiento(
        objeto="usuarios",
        finalidad="Dar acceso al sistema a las personas autorizadas e identificar quién hace cada cosa",
        base_legal="contrato",
        plazo="Mientras la persona tenga acceso, y 12 meses después para poder auditar",
        destinatarios=("Administradores del tenant",),
        responsable=RESPONSABLE,
    )
)

declarar(
    Tratamiento(
        objeto="sesiones",
        # La IP de una sesión es dato personal aunque nadie la mire nunca, y se
        # guarda por una razón concreta: sin ella no se puede responder «desde
        # dónde entró quien hizo esto», que es la pregunta de toda investigación.
        finalidad="Sostener la sesión y poder investigar un acceso indebido",
        base_legal="interes_legitimo",
        plazo="90 días desde el cierre de la sesión",
        responsable=RESPONSABLE,
    )
)

declarar(
    Tratamiento(
        objeto="dispositivos_confianza",
        finalidad="Reconocer un dispositivo ya verificado y no pedir el segundo factor en cada entrada",
        base_legal="interes_legitimo",
        plazo="Mientras el dispositivo siga marcado como de confianza",
        responsable=RESPONSABLE,
    )
)

declarar(
    Tratamiento(
        objeto="entregas_notificacion",
        finalidad="Entregar avisos del sistema por correo, SMS o el canal configurado",
        base_legal="contrato",
        plazo="90 días, para poder comprobar si un aviso llegó",
        destinatarios=("Proveedor de correo o de SMS configurado por el cliente",),
        responsable=RESPONSABLE,
    )
)
