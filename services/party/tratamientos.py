"""Qué hace `party` con los datos personales que guarda (CRM-07.03.01.04).

Va aquí, al lado de los modelos, y no en un documento: lo que se actualiza
cuando el producto cambia es el modelo, y un documento aparte se queda viejo el
mismo día que alguien añade un campo.

Lo que se declara aquí es **lo que el software hace**. Lo que decide el cliente
—la finalidad exacta, la base legal que invoca, cuánto lo guarda— puede
ajustarlo por tenant desde la configuración, porque el responsable del
tratamiento es él y el fabricante solo el encargado.
"""

from __future__ import annotations

from crmcore.cumplimiento import Tratamiento, declarar

# Plazo que se repite: mientras dura la relación, más lo que obliga a conservar
# la normativa mercantil. Escrito una vez para que no aparezcan tres redacciones
# distintas del mismo plazo en el mismo registro.
PLAZO_RELACION = (
    "Mientras dure la relación comercial y 6 años después, por la obligación "
    "mercantil de conservar la documentación de las operaciones"
)
RESPONSABLE = "El cliente titular del tenant; el fabricante actúa como encargado"

declarar(
    Tratamiento(
        objeto="contactos",
        finalidad="Gestionar la relación con las personas de contacto de clientes y posibles clientes",
        base_legal="interes_legitimo",
        plazo=PLAZO_RELACION,
        destinatarios=("Personal del cliente con acceso al CRM",),
        responsable=RESPONSABLE,
    )
)

declarar(
    Tratamiento(
        objeto="cuentas",
        finalidad="Gestionar la relación comercial con empresas y profesionales",
        base_legal="contrato",
        plazo=PLAZO_RELACION,
        destinatarios=("Personal del cliente con acceso al CRM",),
        responsable=RESPONSABLE,
    )
)

declarar(
    Tratamiento(
        objeto="direcciones",
        finalidad="Localizar y facturar a clientes y contactos",
        base_legal="contrato",
        plazo=PLAZO_RELACION,
        responsable=RESPONSABLE,
    )
)

declarar(
    Tratamiento(
        objeto="descargas_adjunto",
        # La IP se guarda para poder responder «quién se llevó este documento»,
        # que es la primera pregunta cuando algo se filtra. Decir que se guarda
        # «por seguridad» sin más no es una finalidad: es una excusa.
        finalidad="Dejar constancia de quién descargó cada documento, para poder investigar una fuga",
        base_legal="interes_legitimo",
        plazo="12 meses",
        responsable=RESPONSABLE,
    )
)

declarar(
    Tratamiento(
        objeto="solicitudes_derechos",
        finalidad="Atender las solicitudes de acceso, rectificación, supresión y portabilidad",
        base_legal="obligacion_legal",
        plazo="3 años desde la respuesta, para poder acreditar que se atendió",
        responsable=RESPONSABLE,
    )
)
